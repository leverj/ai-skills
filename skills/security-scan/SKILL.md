---
name: security-scan
description: >
  Drive the deterministic `leverj/security-scan` Docker image against the
  current repo (OSV-Scanner, Gitleaks, Semgrep, Trivy, Trufflehog, image-CVE,
  Supabase live). Files findings into a GitHub Projects v2 board. On every
  run, checks Docker Hub for a newer image DIGEST and — on user confirmation
  — pulls it and applies any new config-schema migrations declared in the
  image's SECURITY-SCAN-MANIFEST.yaml. Config lives at
  `<repo>/.security-scan/config.yaml` — repo-local, versioned with the repo.
  LLM SAST (codex + gemma) is a SEPARATE concern handled by the
  `security-scan-llm` CLI under `tools/security-scan-llm/` — not orchestrated
  by this skill.
  Use when the user says "scan", "/security-scan", "run security-scan",
  "scan this repo for security issues", "check for secrets / CVEs / SAST
  issues", or "audit dependencies".
allowed-tools: Bash(docker *) Bash(curl *) Bash(jq *) Bash(yq *) Bash(gh *) Bash(op *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(cp *) Read Write Edit Glob Grep
argument-hint: "[run|setup|upgrade|check] [--no-dry-run] [--no-update-check]"
effort: medium
---

# security-scan — Security Scanner skill

Drives the `leverj/security-scan` Docker image (deterministic scanners only).
The image is stateless; all per-deployment state lives in a **repo-local
config directory** at `<repo>/.security-scan/` and in a **GitHub Projects v2
board** the user owns. Between runs the skill keeps two small files in the
repo's config dir:

- `config.yaml`                — the live config (the unit of configuration).
- `.security-scan-state.yaml`  — managed by the skill; tracks the pinned image **digest**.

Both files are versioned with the repo — config travels with the repo. No
user-level (`~/.security-scan/`) state.

LLM SAST (codex + gemma) is **out of scope** for this skill. It lives in a
standalone CLI (`security-scan-llm`) under `tools/security-scan-llm/` with
its own config at `<repo>/.security-scan/config-llm.yaml`. Both tools file
into the same Projects v2 board with a byte-identical fingerprint scheme so
findings dedup across substrates.

This skill never writes inside the image. It only:

1. Pulls the image (when needed),
2. Bind-mounts the user's config dir at `/config:ro`,
3. Reads the image's `/app/SECURITY-SCAN-MANIFEST.yaml` to learn what version
   is inside and what config fields it expects,
4. Drives `docker run` with the right flags — pinning by **digest**, not tag.

## Why digest, not tag

The image is published as `leverj/security-scan:latest` only. There are no
versioned tags accumulating on Docker Hub — each push of `:latest` is a new
immutable manifest with a new SHA-256 digest. The skill tracks that digest as
the unit of identity:

- The skill pins to the digest in `pinned_digest`.
- "Has it updated?" → fetch the current `:latest` digest from Docker Hub,
  compare. If different, surface the version label (from the new image's
  manifest) and ask the user.
- The actual `docker run` uses `leverj/security-scan@sha256:<digest>` so even
  if `:latest` moves mid-run, the pin holds.

The `version` field inside the manifest is a human-readable label
(`"0.3.2"`) used only for the upgrade prompt — image identity is the digest.

## Invocation

```
/leverj:security-scan                       same as `run`
/leverj:security-scan run [flags]           dry-run the scanner (default)
/leverj:security-scan run --no-dry-run      file issues into the Projects v2 board
/leverj:security-scan setup                 first-time interactive config setup
/leverj:security-scan upgrade               explicitly check for + apply image updates
/leverj:security-scan check                 verify config + image + auth, exit
```

Flags accepted on every subcommand:

- `--no-update-check`  — skip the pre-run Docker Hub digest check (faster; offline-OK).
- `--image <ref>`      — override `leverj/security-scan` (e.g., for a fork).

The skill always operates against the current working directory's
`.security-scan/` subdirectory. There is no `--config-dir` flag — to scan a
different repo, `cd` into that repo and re-invoke.

## Phase-by-phase operating procedure

Run these phases in order. Stop on the first hard failure with a clear
message to the user.

### Phase 0 — Locate config dir

The config dir is **always** `${REPO_ROOT}/.security-scan/`, where
`REPO_ROOT` is the output of `git rev-parse --show-toplevel`.

If that fails (current dir isn't inside a git repo), stop with a clear
message — the skill only operates inside a git checkout.

If `${REPO_ROOT}/.security-scan/config.yaml` doesn't exist:
- For subcommand `setup`: proceed to interactive setup (Phase A below).
- For everything else: stop and tell the user to run
  `/leverj:security-scan setup` from inside this repo.

### Phase 1 — Resolve pinned image digest

Read `<config-dir>/.security-scan-state.yaml`. Expected shape:

```yaml
pinned_digest: "sha256:abc123..."          # canonical identity (immutable)
version_label: "0.3.2"                     # for display only (from manifest.version)
image:         "leverj/security-scan"      # in case user pointed at a fork
last_checked:  "2026-06-02T12:00:00Z"      # ISO 8601 UTC; controls the 6h throttle
last_upgrade:  "2026-06-02T11:55:00Z"      # most recent successful upgrade
```

If the state file is missing or has no `pinned_digest`, treat as **first run**:
proceed to Phase 2 to discover the current `:latest` digest, then continue.

### Phase 2 — Check for image updates (digest-based)

Skip this phase if `--no-update-check` was passed or if `last_checked` is less
than 6 hours ago (cheap throttle to avoid hammering Docker Hub on rapid
re-runs).

Fetch the current digest of `:latest` without pulling:

```bash
# Primary: Docker Hub REST API. Returns the manifest digest of :latest.
LATEST_DIGEST=$(
  curl -fsSL "https://hub.docker.com/v2/repositories/leverj/security-scan/tags/latest/" \
    | jq -r '.digest // .images[0].digest // empty'
)

# Fallback if the REST API fails: ask the daemon (requires login to be set up
# for private repos, but our image is public).
if [ -z "$LATEST_DIGEST" ]; then
  LATEST_DIGEST=$(docker manifest inspect leverj/security-scan:latest \
    | jq -r '.manifests[0].digest // .config.digest // empty')
fi
```

The shape varies: tags API returns `sha256:...` directly; manifest inspect
returns a JSON with `manifests[]` (multi-arch index) or `config.digest`
(single-arch). For our multi-arch image, take the **index digest** (top-level
`digest` from the tags API, or compute it from the manifest list) — that's
what `docker pull` resolves to and what we pin against.

Compare to `pinned_digest`:

- If equal → no update; record `last_checked` and continue to Phase 3.
- If different → fetch the new image's manifest (Phase 2a).
- If pinned_digest is missing (first run) → treat as an upgrade from "none".

#### Phase 2a — Inspect the candidate image's manifest

Pull the metadata WITHOUT replacing the user's pinned image yet. Because the
image is content-addressed, we can pull by digest directly:

```bash
docker pull -q "leverj/security-scan@${LATEST_DIGEST}"
docker run --rm --entrypoint cat \
  "leverj/security-scan@${LATEST_DIGEST}" /app/SECURITY-SCAN-MANIFEST.yaml \
  > /tmp/security-scan-manifest-${LATEST_DIGEST##*:}.yaml
```

Parse the manifest with `yq` (or fall back to a `python3 -c` one-liner if
`yq` isn't on PATH). Surface to the user:

- The version-label delta (e.g., `0.2.4 → 0.3.2`) AND the digest delta
  (`sha256:abc...→sha256:def...`).
- The `changelog` lines as a bullet list.
- A summary of `breaking_changes` if any (each is `id + summary + user_action`).
- A summary of pending config changes:
  - `new_fields` not already in their `config.yaml` → "the skill will ADD these (with defaults)".
  - `renamed_fields` where the old name is in their `config.yaml` → "the skill will RENAME these in place".
  - `removed_fields` present in their `config.yaml` → "the skill will REMOVE these (with confirmation)".

If the current schema version (`config_schema_version` in the new manifest)
is greater than what the user's config was migrated to, mention it explicitly
so the user knows new fields may appear.

#### Phase 2b — Ask for confirmation

Print a clear yes/no prompt. If `breaking_changes` is non-empty, require an
explicit `yes` (not just `y`). If no breaking changes, a plain `y` suffices.

If the user declines:
- Keep the current pinned digest.
- Record `last_checked` (so the throttle kicks in next time).
- Continue to Phase 3 with the old image.

If the user accepts:
- Write the new `pinned_digest` + `version_label` to `.security-scan-state.yaml`.
- Update `last_upgrade` to now.
- Apply config migrations (Phase 2c).

#### Phase 2c — Apply config migrations

Make a backup first: `cp config.yaml config.yaml.bak-<timestamp>`. Then:

1. **Renames** — for each entry in `config.renamed_fields`, if the `from` key
   exists in the user's config, rename it to `to`. If the migration note
   says the rename needs human input (e.g., `parent_issue (int) → project
   (mapping)`), surface a prompt asking for the required values, then write
   the new structure.
2. **New fields** — for each entry in `config.new_fields` whose `path` is NOT
   already set in the user's config, set it to the documented `default`. For
   entries with `required: true`, prompt the user (don't silently write
   `null`).
3. **Removed fields** — for each entry in `config.removed_fields` present in
   the user's config, show what's being stripped and confirm before removing.

Show the resulting diff (e.g., `diff -u config.yaml.bak-* config.yaml`) and
ask the user to confirm one more time before continuing. If they reject,
restore from the `.bak` file and stop.

### Phase 3 — Verify config + secrets

Run a non-destructive check before invoking the scanner. The goal is to fail
fast on missing prereqs, not to scan.

For `secrets.source: env`:
- `GITHUB_TOKEN` must be exported in the current shell.
- If `slack.enabled: true`, the var named by `slack.webhook_url_env` (or
  `channel_id_env` + `bot_token_env`) must be exported.
- If `supabase.enabled: true`, the var named by `supabase.url_env` (or all of
  `host_env`/`db_env`/`user_env`/`password_env`) must be exported.

For `secrets.source: 1password`:
- `op` must be on `PATH` and `op account list` must succeed (signed-in).
- `<config-dir>/<secrets.env_file>` must exist.

Required config keys (check by reading `<config-dir>/config.yaml`):
- `repo` (matches `owner/name`)
- `ref`
- `project.owner` and `project.number` (the Projects v2 board)
- `github_token_env`

If any check fails, surface a clear remediation and stop.

### Phase 4 — Run

Invoke by **digest**, not tag — so the pin survives a concurrent `:latest`
push from the publisher.

```bash
docker run --rm \
  -v "${REPO_ROOT}/.security-scan:/config:ro" \
  -e GITHUB_TOKEN \
  $([ "${SLACK_FORWARDED}" ] && echo -e SLACK_WEBHOOK_URL) \
  $([ "${SUPABASE_FORWARDED}" ] && echo -e SUPABASE_DB_URL) \
  "${IMAGE}@${PINNED_DIGEST}" \
  $([ -z "${NO_DRY_RUN}" ] && echo --dry-run)
```

For `secrets.source: 1password`, wrap the above with:

```bash
op run --env-file="${REPO_ROOT}/.security-scan/${ENV_FILE}" -- \
  docker run --rm ... (same as above)
```

`op` populates this shell's env JIT; `docker run -e GITHUB_TOKEN` (no value!)
copies it into the container without putting it on argv.

### Phase 5 — Report

After the container exits, surface to the user:

1. The final `summary:` line verbatim from stderr.
2. Any `scanner X: NOT COMPLETED` lines.
3. Direct link to the project board:
   `https://github.com/orgs/<project.owner>/projects/<project.number>`.
4. The dry-run / real-run mode, explicitly stated.
5. If `--no-dry-run` was passed, the count of issues actually filed.
6. If the run found findings under `category: image` or `category: config`,
   mention them by category count — these are newer lanes (image-CVE scanning
   and the live Supabase advisor) the user may not be expecting.

DO NOT paste the full stderr log into your reply — it can be hundreds of
lines. Quote relevant excerpts only.

## Phase A — First-time `setup` (interactive)

Triggered by `/leverj:security-scan setup` or when Phase 0 finds no config.

Resolve `REPO_ROOT=$(git rev-parse --show-toplevel)`. All paths below are
relative to that.

1. `mkdir -p "${REPO_ROOT}/.security-scan"`.
2. Fetch the current `:latest` digest (Phase 2 logic).
3. Pull by digest: `docker pull leverj/security-scan@${LATEST_DIGEST}`.
4. Read the image's manifest with
   `docker run --rm --entrypoint cat leverj/security-scan@${LATEST_DIGEST} /app/SECURITY-SCAN-MANIFEST.yaml`.
5. Use the manifest's `config.new_fields` (where `required: true`) as the
   prompt schema. Ask the user for each required value:
   - `repo` (e.g., `leverj/ezel`) — default: parse from `git remote get-url origin`
   - `ref` (default `main`)
   - `project.owner` (org or user)
   - `project.number` (project number from the URL)
6. Ask which secret path: env (default) or 1password. If 1password, also ask
   for the env file path.
7. Write `${REPO_ROOT}/.security-scan/config.yaml` with the required fields
   filled in and the optional ones at their documented defaults.
8. If `secrets.source: 1password`, copy the image-baked example to
   `${REPO_ROOT}/.security-scan/.env.1password.tpl` and tell the user to edit it with
   their `op://vault/item/...` paths. Get the template contents with:
   ```bash
   docker run --rm --entrypoint cat \
     leverj/security-scan@${LATEST_DIGEST} /app/config/.env.1password.tpl.example
   ```
9. Ask whether the user wants the **optional opt-in lanes** enabled:
   - `image_scan.built_image.enabled` (scan a pulled or locally-built image —
     defaults off; surface the security implications if they say yes).
   - `supabase.enabled` (live Supabase Postgres advisor — requires a
     read-only DB role; surface the recommended `CREATE ROLE` + `GRANT`).
   These are defaulted off in the manifest's `new_fields`.
10. Tell the user the PAT scopes required (`repo` + `project`) and where to
    create one.
11. Write `.security-scan-state.yaml` with the resolved `pinned_digest` and
    `version_label` from the manifest.
12. Run Phase 3 (verify) to confirm everything's wired.
13. Run a dry-run (Phase 4 with `--dry-run`) and report (Phase 5).
14. Add `.security-scan/` (or specifically `.security-scan/.security-scan-state.yaml`)
    to `.gitignore` if the user prefers state to be local-only. By default the
    state file IS checked in — it pins the image digest, which is a meaningful
    repo-level decision (analogous to a lockfile).

## Hard rules

These are non-negotiable. They protect the user and the source of truth.

- **NEVER pass `--no-dry-run` unless the user explicitly confirmed it in the
  current turn.** The default is dry-run for a reason — security-scan files
  real GitHub issues. Surprise filings are a trust violation.
- **NEVER include secrets in your replies.** `GITHUB_TOKEN`, 1Password env
  file contents, Slack webhooks, Supabase DSNs / passwords must never appear
  in your messages. security-scan scrubs these from its own logs; you must
  scrub yours.
- **NEVER edit `config.yaml` silently.** Every change (new field added,
  renamed, removed) MUST be shown as a diff and confirmed before writing.
- **NEVER edit the image.** The skill drives a published image; you don't
  modify it. Bug fixes / feature requests for security-scan itself belong in
  `leverj/security-scanner`.
- **The Projects v2 board is the source of triage truth.** Don't try to dedup
  findings yourself — that's security-scan's job (deterministic fingerprints
  in the issue body). Don't close or comment on issues the scanner files;
  triage is a separate workflow (`/leverj:triage`).
- **Honor `--no-update-check`.** Skip the Docker Hub probe entirely; don't
  try to be clever and check anyway "just in case".
- **Pin by digest, run by digest.** `docker run leverj/security-scan:latest`
  is wrong — between Phase 2's check and Phase 4's run, `:latest` could
  move. Always invoke `leverj/security-scan@${PINNED_DIGEST}`.
- **NEVER enable `image_scan.built_image.build_locally` without explicit
  per-run consent.** That mode `docker build`s the cloned repo, which
  executes the repo's Dockerfile RUN lines and requires both the docker
  socket mounted and `SECURITY_SCAN_ALLOW_BUILD=1` in env. It's the one
  carve-out to security-scan's otherwise-strict "never execute repo code"
  invariant.

## Notes on the `.security-scan-state.yaml` file

The skill owns this file. Users don't edit it by hand. Recognized keys:

```yaml
pinned_digest: "sha256:abc..."        # canonical identity; this is THE pin
version_label: "0.3.2"                # human-readable, from manifest.version
image:         "leverj/security-scan" # in case user pointed at a fork
last_checked:  "2026-06-02T12:00:00Z" # ISO 8601 UTC; controls the 6h throttle
last_upgrade:  "2026-06-02T11:55:00Z" # records the most recent successful upgrade
```

Re-creating it from scratch is safe — Phase 1 detects the missing file and
treats it as a first run.

If a user's state file from a pre-digest version has `pinned_tag` but no
`pinned_digest`, treat as a first run and re-resolve. Don't try to map the
old tag to a digest — Docker Hub may not have it anymore (we only publish
`:latest`).

## When something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: command not found` | Docker not installed | Tell user to install Docker Desktop |
| `Cannot connect to the Docker daemon` | Docker not running | Tell user to start Docker Desktop |
| `pull access denied` | Image name typo or private repo | Verify `image` in state.yaml is `leverj/security-scan` |
| Hub REST API returns 404 on `tags/latest/` | First publish hasn't happened, or `:latest` was retracted | Fall back to `docker manifest inspect`; if that also fails, stop and tell the user the image isn't published yet |
| `secrets env file not found` | 1Password path missing | Run `setup` again or copy the example |
| `op not signed in` | 1Password CLI logged out | `op signin` in the user's shell, then retry |
| `GitHub API 404: project not found` | Wrong owner/number OR PAT missing `project` scope | Verify project URL + PAT scopes |
| `scanners completed: 0` and several failures | Network or image corruption | Re-pull the image by digest, re-run |
| Schema mismatch on manifest read | Older image with no manifest | Tell the user the pinned image predates the manifest contract; recommend re-running `setup` to discover the current `:latest` |
| `supabase: all checks failed: ... permission denied` | DB role lacks `pg_read_all_data` | Re-run the recommended `GRANT` statements from the setup phase |
| `image:python:3.14 — exit 1: trivy: vulnerability DB locked` | Concurrent trivy run in the same container | Re-run; the DB lock clears on restart |
| `image_scan.built_image: SECURITY_SCAN_ALLOW_BUILD=1` required | User enabled `build_locally` without the env guard | This is intentional; only set `SECURITY_SCAN_ALLOW_BUILD=1` if the cloned repo is trusted, since `docker build` will execute its RUN lines |

## Companion docs

- The image source: <https://github.com/leverj/security-scanner>
- The spec: `security-scan-spec.md` in that repo (data model, fingerprint
  scheme, dedup invariants).
- The image's manifest: read at runtime with
  `docker run --rm --entrypoint cat leverj/security-scan@<digest> /app/SECURITY-SCAN-MANIFEST.yaml`.

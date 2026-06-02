---
name: security-scan
description: >
  Run the security-scan scanner against a repo via the published
  `leverj/security-scan` Docker image. Detects the repo's tech stack, runs
  OSV-Scanner, Gitleaks, Semgrep, Trivy, Trufflehog (and optionally LLM-driven
  Codex + Gemma SAST with bidirectional cross-validation), and files each
  finding into a GitHub Projects v2 board. On every run, checks Docker Hub for
  a newer image and — on user confirmation — pulls it and applies any new
  config-schema migrations declared in the image's SECURITY-SCAN-MANIFEST.yaml.
  Use when the user says "scan", "/security-scan", "run security-scan",
  "scan this repo for security issues", "check for secrets / CVEs / SAST
  issues", or "audit dependencies".
allowed-tools: Bash(docker *) Bash(curl *) Bash(jq *) Bash(yq *) Bash(gh *) Bash(op *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(cp *) Read Write Edit Glob Grep
argument-hint: "[run|setup|upgrade|check] [--config-dir <path>] [--no-dry-run] [--no-update-check]"
effort: medium
---

# security-scan — Security Scanner skill

Drives the `leverj/security-scan` Docker image. The image is stateless; all
per-deployment state lives in a **config directory** (defaults to
`~/.security-scan/`) and in a **GitHub Projects v2 board** the user owns.
Between runs the skill keeps two small files in the user's config dir:

- `config.yaml`                — the live config (the unit of configuration).
- `.security-scan-state.yaml`  — managed by the skill; tracks pinned image tag.

This skill never writes inside the image. It only:

1. Pulls the image (when needed),
2. Bind-mounts the user's config dir at `/config:ro`,
3. Reads the image's `/app/SECURITY-SCAN-MANIFEST.yaml` to learn what version
   is inside and what config fields it expects,
4. Drives `docker run` with the right flags.

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

- `--config-dir <path>` — use a non-default config dir (default `~/.security-scan`).
- `--no-update-check`   — skip the pre-run Docker Hub check (faster; offline-OK).
- `--image <ref>`       — override `leverj/security-scan` (e.g., for a fork).

## Phase-by-phase operating procedure

Run these phases in order. Stop on the first hard failure with a clear
message to the user.

### Phase 0 — Locate config dir

Resolve in priority order:
1. `--config-dir <path>` flag if passed.
2. `SECURITY_SCAN_CONFIG_DIR` env var.
3. `~/.security-scan/`.

If the chosen directory doesn't contain `config.yaml`:
- For subcommand `setup`: proceed to interactive setup (Phase A below).
- For everything else: stop and tell the user to run
  `/leverj:security-scan setup`.

### Phase 1 — Resolve pinned image tag

Read `<config-dir>/.security-scan-state.yaml`. Expected shape:

```yaml
pinned_tag: "0.2.0"
pinned_digest: "sha256:abc..."
image: "leverj/security-scan"
last_checked: "2026-06-02T12:00:00Z"
```

If the state file is missing or has no `pinned_tag`, treat as **first run**:
proceed to Phase 2 to pick the latest tag, then continue.

### Phase 2 — Check for image updates

Skip this phase if `--no-update-check` was passed or if the last check was
less than 6 hours ago (cheap throttle to avoid hammering Docker Hub on rapid
re-runs).

1. Query Docker Hub for the most recent tag:
   ```bash
   curl -fsSL "https://hub.docker.com/v2/repositories/leverj/security-scan/tags?page_size=10&ordering=last_updated" \
     | jq -r '.results[].name' | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | head -1
   ```
2. Normalize: strip a leading `v` for comparison; both `v0.2.0` and `0.2.0` are
   accepted. The manifest's `version` is canonical (no `v` prefix).
3. Compare to the pinned tag:
   - If equal → no update; record `last_checked` and continue to Phase 3.
   - If different → fetch the new image's manifest (Phase 2a).

#### Phase 2a — Inspect the candidate image's manifest

Pull the metadata WITHOUT replacing the user's pinned image yet:

```bash
# Pull just enough to read the manifest. `cat` is the entrypoint override.
docker pull -q "leverj/security-scan:${CANDIDATE_TAG}"
docker run --rm --entrypoint cat \
  "leverj/security-scan:${CANDIDATE_TAG}" /app/SECURITY-SCAN-MANIFEST.yaml \
  > /tmp/security-scan-manifest-${CANDIDATE_TAG}.yaml
```

Parse the manifest with `yq` (or fall back to a `python3 -c` one-liner if
`yq` isn't on PATH). Surface to the user:

- The version delta (e.g., `0.1.0 → 0.2.0`).
- The `changelog` lines as a bullet list.
- A summary of `breaking_changes` if any (each is `id + summary + user_action`).
- A summary of pending config changes:
  - `new_fields` not already in their `config.yaml` → "the skill will ADD these (with defaults)".
  - `renamed_fields` where the old name is in their `config.yaml` → "the skill will RENAME these in place".
  - `removed_fields` present in their `config.yaml` → "the skill will REMOVE these (with confirmation)".

#### Phase 2b — Ask for confirmation

Print a clear yes/no prompt. If `breaking_changes` is non-empty, require an
explicit `yes` (not just `y`). If no breaking changes, a plain `y` suffices.

If the user declines:
- Keep the current pinned tag.
- Record `last_checked` (so the throttle kicks in next time).
- Continue to Phase 3 with the old image.

If the user accepts:
- Write the new pinned tag + digest to `.security-scan-state.yaml`.
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

```bash
docker run --rm \
  -v "${CONFIG_DIR}:/config:ro" \
  -e GITHUB_TOKEN \
  $([ "${SLACK_FORWARDED}" ] && echo -e SLACK_WEBHOOK_URL) \
  "leverj/security-scan:${PINNED_TAG}" \
  $([ -z "${NO_DRY_RUN}" ] && echo --dry-run)
```

For `secrets.source: 1password`, wrap the above with:

```bash
op run --env-file="${CONFIG_DIR}/${ENV_FILE}" -- \
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

DO NOT paste the full stderr log into your reply — it can be hundreds of
lines. Quote relevant excerpts only.

## Phase A — First-time `setup` (interactive)

Triggered by `/leverj:security-scan setup` or when Phase 0 finds no config.

1. `mkdir -p ~/.security-scan`.
2. Pull the latest image: `docker pull leverj/security-scan:latest`.
3. Read the image's manifest with
   `docker run --rm --entrypoint cat leverj/security-scan:latest /app/SECURITY-SCAN-MANIFEST.yaml`.
4. Use the manifest's `config.new_fields` (where `required: true`) as the
   prompt schema. Ask the user for each required value:
   - `repo` (e.g., `leverj/ezel`)
   - `ref` (default `main`)
   - `project.owner` (org or user)
   - `project.number` (project number from the URL)
5. Ask which secret path: env (default) or 1password. If 1password, also ask
   for the env file path.
6. Write `~/.security-scan/config.yaml` with the required fields filled in
   and the optional ones at their documented defaults.
7. If `secrets.source: 1password`, copy the image-baked example to
   `~/.security-scan/.env.1password.tpl` and tell the user to edit it with
   their `op://vault/item/...` paths. Get the template contents with:
   ```bash
   docker run --rm --entrypoint cat \
     leverj/security-scan:latest /app/config/.env.1password.tpl.example
   ```
8. Tell the user the PAT scopes required (`repo` + `project`) and where to
   create one.
9. Run Phase 3 (verify) to confirm everything's wired.
10. Run a dry-run (Phase 4 with `--dry-run`) and report (Phase 5).

## Hard rules

These are non-negotiable. They protect the user and the source of truth.

- **NEVER pass `--no-dry-run` unless the user explicitly confirmed it in the
  current turn.** The default is dry-run for a reason — security-scan files
  real GitHub issues. Surprise filings are a trust violation.
- **NEVER include secrets in your replies.** `GITHUB_TOKEN`, 1Password env
  file contents, Slack webhooks must never appear in your messages.
  security-scan scrubs these from its own logs; you must scrub yours.
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

## Notes on the `.security-scan-state.yaml` file

The skill owns this file. Users don't edit it by hand. Recognized keys:

```yaml
pinned_tag:    "0.2.0"                # the docker tag in use
pinned_digest: "sha256:abc..."        # immutable digest for reproducibility
image:         "leverj/security-scan" # in case user pointed at a fork
last_checked:  "2026-06-02T12:00:00Z" # ISO 8601 UTC; controls the 6h throttle
last_upgrade:  "2026-06-02T11:55:00Z" # records the most recent successful upgrade
```

Re-creating it from scratch is safe — Phase 1 detects the missing file and
treats it as a first run.

## When something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: command not found` | Docker not installed | Tell user to install Docker Desktop |
| `Cannot connect to the Docker daemon` | Docker not running | Tell user to start Docker Desktop |
| `pull access denied` | Image name typo or private repo | Verify `image` in state.yaml is `leverj/security-scan` |
| `secrets env file not found` | 1Password path missing | Run `setup` again or copy the example |
| `op not signed in` | 1Password CLI logged out | `op signin` in the user's shell, then retry |
| `GitHub API 404: project not found` | Wrong owner/number OR PAT missing `project` scope | Verify project URL + PAT scopes |
| `scanners completed: 0` and several failures | Network or image corruption | Re-pull the image, re-run |
| Schema mismatch on manifest read | Older image with no manifest | Pin to a known-good tag in state.yaml; old images don't have the manifest contract |

## Companion docs

- The image source: <https://github.com/leverj/security-scanner>
- The spec: `security-scan-spec.md` in that repo (data model, fingerprint
  scheme, dedup invariants).
- The image's manifest: read at runtime with
  `docker run --rm --entrypoint cat leverj/security-scan:<tag> /app/SECURITY-SCAN-MANIFEST.yaml`.

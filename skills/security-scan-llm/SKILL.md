---
name: security-scan-llm
description: >
  Drive the host-side `security-scan-llm` Python CLI for LLM SAST lanes
  (Codex + Gemma with bidirectional cross-validation). Files findings into the
  same GitHub Projects v2 board as the deterministic `security-scan` skill,
  using a byte-identical fingerprint scheme so findings dedup across substrates.
  Config lives at `<repo>/.security-scan/config-llm.yaml` — repo-local,
  versioned with the repo, SEPARATE from the deterministic
  `<repo>/.security-scan/config.yaml`. On every run, checks the installed
  tool's `--version` against the bundled `SECURITY-SCAN-LLM-MANIFEST.yaml`
  and offers a user-confirmed upgrade + config-migration flow.
  Use when the user says "scan llm", "/security-scan-llm", "run codex/gemma
  scan", or "give me a fresh LLM pass on this repo".
allowed-tools: Bash(security-scan-llm *) Bash(codex *) Bash(curl *) Bash(jq *) Bash(yq *) Bash(gh *) Bash(op *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(cp *) Bash(git *) Bash(python3 *) Bash(pipx *) Read Write Edit Glob Grep
argument-hint: "[run|setup|upgrade|check] [--no-dry-run] [--no-update-check]"
effort: medium
---

# security-scan-llm — Host LLM SAST skill

Drives the `security-scan-llm` Python CLI (host-side LLM lane). This is a
**separate skill** from `security-scan` (which drives the deterministic
container). Both file into the same Projects v2 board.

Per-repo state lives in `<repo>/.security-scan/`:

- `config-llm.yaml`                    — the live config (LLM-only schema).
- `.security-scan-llm-state.yaml`      — managed by the skill; tracks the
                                         installed tool version.

The skill never installs or uninstalls the CLI itself. It assumes the user
has done `pipx install <ai-skills-clone>/tools/security-scan-llm` once.
When the bundled manifest's version moves past the installed version, the
skill **surfaces** the upgrade and tells the user how to apply it — without
running `pipx upgrade` automatically (different risk profile from
`docker pull`; package installs touch the user's Python env).

## Why version-tracked, not digest-pinned

The host tool is a Python package, not an image. The unit of identity is the
`__version__` reported by `security-scan-llm --version`. Between releases,
the source of truth for "what version should I be on" is the manifest at
`tools/security-scan-llm/SECURITY-SCAN-LLM-MANIFEST.yaml` in the
`leverj/ai-skills` repo — bundled with the skill itself.

This is symmetric with how the static skill uses the image manifest:

| Skill | Tool | Identity | Manifest |
|---|---|---|---|
| `security-scan` | `leverj/security-scan` Docker image | sha256 digest | baked-into-image `/app/SECURITY-SCAN-MANIFEST.yaml` |
| `security-scan-llm` | `security-scan-llm` pip package | `__version__` string | bundled-with-skill `SECURITY-SCAN-LLM-MANIFEST.yaml` |

## Invocation

```
/leverj:security-scan-llm                       same as `run`
/leverj:security-scan-llm run [flags]           dry-run the LLM lane (default)
/leverj:security-scan-llm run --no-dry-run      file LLM-lane findings into the board
/leverj:security-scan-llm setup                 first-time interactive config-llm setup
/leverj:security-scan-llm upgrade               explicitly check for + apply tool/config updates
/leverj:security-scan-llm check                 verify config + tool + auth + LLM substrate, exit
```

Flags accepted on every subcommand:

- `--no-update-check` — skip the version-vs-manifest probe (faster).
- `--no-dry-run`      — actually file findings (default is dry-run).

The skill always operates against the current working directory's
`.security-scan/` subdirectory. To scan a different repo, `cd` into it.

## Phase-by-phase operating procedure

Run these phases in order. Stop on the first hard failure with a clear
message to the user.

### Phase 0 — Locate config dir

The config dir is **always** `${REPO_ROOT}/.security-scan/`, where
`REPO_ROOT` is the output of `git rev-parse --show-toplevel`.

If that fails (not inside a git repo), stop with a clear message.

If `${REPO_ROOT}/.security-scan/config-llm.yaml` doesn't exist:
- For subcommand `setup`: proceed to Phase A.
- For everything else: stop and tell the user to run
  `/leverj:security-scan-llm setup` from inside this repo.

### Phase 1 — Resolve installed tool version

Read `<config-dir>/.security-scan-llm-state.yaml`. Expected shape:

```yaml
pinned_version: "0.1.0"                # what we believe is installed
manifest_path:  "<absolute path>/tools/security-scan-llm/SECURITY-SCAN-LLM-MANIFEST.yaml"
last_checked:   "2026-06-03T12:00:00Z"
last_upgrade:   "2026-06-03T11:55:00Z"
```

If the state file is missing, treat as **first run**.

Probe the actually-installed version:

```bash
INSTALLED_VERSION=$(security-scan-llm --version 2>&1 | awk '{print $NF}')
```

If `security-scan-llm` is not on PATH, surface a clear install hint:

```bash
pipx install <ai-skills-clone>/tools/security-scan-llm
# or, inside the bundled venv:
${HOME}/.claude/plugins/leverj/tools/security-scan-llm/.venv/bin/security-scan-llm --version
```

…and stop. Don't try to install for the user — package installs touch their
Python env, which is their decision.

### Phase 2 — Check for tool updates

Skip this phase if `--no-update-check` was passed or `last_checked` is less
than 6 hours ago.

Locate the bundled manifest:

```bash
PLUGIN_ROOT="${HOME}/.claude/plugins/leverj"
MANIFEST="${PLUGIN_ROOT}/tools/security-scan-llm/SECURITY-SCAN-LLM-MANIFEST.yaml"
if [ ! -f "${MANIFEST}" ]; then
  MANIFEST="<wherever the user's ai-skills clone lives>/tools/security-scan-llm/SECURITY-SCAN-LLM-MANIFEST.yaml"
fi
```

If the manifest can't be found at any plausible path, skip the version probe
(record `last_checked`, continue).

Compare `manifest.version` to `INSTALLED_VERSION`:

- **Equal** → no update; record `last_checked`; continue to Phase 3.
- **Different** → enter the upgrade flow (Phase 2a).

#### Phase 2a — Surface the diff + ask for confirmation

Read the manifest. Surface to the user:

- The version delta (`0.1.0 → 0.2.0`).
- The `changelog` lines as a bullet list.
- `breaking_changes` if any (id + summary + user_action per item).
- Pending config changes (compare against `config-llm.yaml`):
  - `new_fields` not already present → "the skill will ADD these (with defaults)".
  - `renamed_fields` where the old name is present → "the skill will RENAME these in place".
  - `removed_fields` present in the user's config → "the skill will REMOVE these (with confirmation)".

Print a clear yes/no prompt. If `breaking_changes` is non-empty, require
explicit `yes`; otherwise a plain `y` suffices.

If the user accepts:

1. Tell them how to upgrade the actual binary:
   ```
   pipx upgrade security-scan-llm     # if installed via pipx
   # OR
   pip install --upgrade -e <ai-skills-clone>/tools/security-scan-llm
   ```
   Do NOT run the upgrade for them.
2. Wait for them to confirm the upgrade ran.
3. Re-probe `INSTALLED_VERSION` and confirm it matches the manifest.
4. Apply config migrations (Phase 2b).

If the user declines, keep going with the old version. Record `last_checked`.

#### Phase 2b — Apply config migrations

Same shape as the static skill's Phase 2c. Backup, rename/add/remove fields
per the manifest, show the diff, ask for final confirmation. Update
`pinned_version` and `last_upgrade` in state.

### Phase 3 — Verify config + substrates

Run a non-destructive check before invoking the tool.

1. **Required config**:
   - `repo` (`owner/name`)
   - `ref`
   - `project.owner`, `project.number`
   - `github_token_env`

2. **PAT**: env var named by `github_token_env` is set + non-empty.

3. **At least one LLM lane enabled**: if both `scanners.codex` and
   `scanners.gemma` are false, stop with a clear message — the tool will
   error otherwise.

4. **Codex health** (if `scanners.codex: true`):
   ```bash
   command -v codex >/dev/null || { echo "codex CLI not on PATH"; FAIL=1; }
   codex login status >/dev/null 2>&1 || { echo "codex not logged in — run 'codex login'"; FAIL=1; }
   ```
   If either fails: surface clearly and ask whether to proceed with gemma
   only (silently) or stop.

5. **Gemma / Ollama health** (if `scanners.gemma: true`):
   ```bash
   BASE_URL="$(yq '.gemma.base_url' "${CFG}" 2>/dev/null || echo http://localhost:11434)"
   curl -fsS "${BASE_URL%/}/api/tags" >/dev/null \
     || { echo "Ollama unreachable at ${BASE_URL}"; FAIL=1; }
   ```
   If `base_url` is non-loopback / non-RFC1918, refuse — source content
   crossing a public boundary is an explicit policy violation. The tool
   itself enforces this; the skill catches it earlier with a clearer message.

6. **Slack health** (if `slack.enabled: true`): env var resolvable.

If any check fails, surface remediation and stop unless the user explicitly
overrides.

### Phase 4 — Run

```bash
security-scan-llm \
  --config "${REPO_ROOT}/.security-scan/config-llm.yaml" \
  --repo-dir "${REPO_ROOT}" \
  $([ -z "${NO_DRY_RUN}" ] && echo --dry-run)
```

The tool reads the same shared keys (`repo`, `ref`, `project`, etc.) the
static skill uses, but expects them in `config-llm.yaml`, not `config.yaml`.

### Phase 5 — Report

Surface to the user:

1. The final `summary:` line from stderr.
2. Per-lane completion (codex / gemma / cross-validate).
3. Direct link to the project board:
   `https://github.com/orgs/<project.owner>/projects/<project.number>`.
4. The dry-run / real-run mode, explicitly stated.
5. If `--no-dry-run` was passed, the count of LLM findings actually filed.
6. If `cross_validate` ran: how many findings got downgraded (the tool's
   stderr reports this).

DO NOT paste the full tool stderr — quote relevant excerpts only.

## Phase A — First-time `setup` (interactive)

Triggered by `/leverj:security-scan-llm setup` or when Phase 0 finds no
config-llm.yaml.

Resolve `REPO_ROOT=$(git rev-parse --show-toplevel)`. All paths below are
relative to that.

1. `mkdir -p "${REPO_ROOT}/.security-scan"`.
2. Verify `security-scan-llm` is on PATH; if not, surface the install hint
   and stop.
3. Locate + read the bundled manifest (Phase 2 logic).
4. Use the manifest's `required_fields` as the prompt schema:
   - `repo` — default: parse from `git remote get-url origin`.
   - `ref` — default: `main`.
   - `project.owner`, `project.number` — required from user.
   - `github_token_env` — default: `GITHUB_TOKEN`.
5. **Lane prompts:**
   - `scanners.codex: true/false` — default false. **Surface:** uses your
     ChatGPT/Codex subscription quota; each run can consume several minutes
     of model time.
   - `scanners.gemma: true/false` — default false. **Surface:** uses your
     local Ollama (must be running); first run can take minutes for the
     model to warm. Source files cross the loopback boundary to Ollama;
     `gemma.base_url` must be loopback or RFC1918.
6. **Cross-validate prompt** (only if BOTH lanes enabled): `cross_validate.enabled`
   — default true. **Surface:** bidirectional review reduces false positives
   but doubles LLM call cost.
7. **Triage prompt:** `triage.enabled: true/false` — default false.
   - If true, sub-prompts: `intro_enabled` (default true, cheap),
     `prose_enabled` (default false, 1 call per finding), `fuzzy_dup_enabled`
     (default false, 1 call per finding).
8. Write `${REPO_ROOT}/.security-scan/config-llm.yaml` with the manifest's
   `new_fields` defaults applied.
9. PAT scopes required (`repo` + `project`). Tell the user where to create one.
10. Write `.security-scan-llm-state.yaml` with the resolved
    `pinned_version` and `last_upgrade`.
11. Run Phase 3 (verify) to confirm everything's wired.
12. Run a dry-run (Phase 4) and report (Phase 5).

## Hard rules

These are non-negotiable.

- **NEVER pass `--no-dry-run` unless the user explicitly confirmed it in the
  current turn.** Same rule as the static skill — LLM findings file real
  issues onto the user's board.
- **NEVER include secrets in your replies.** PATs, Slack webhooks, Ollama
  tokens, codex session tokens must never appear in your messages.
- **NEVER edit `config-llm.yaml` silently.** Every change MUST be shown as a
  diff and confirmed before writing.
- **NEVER `pipx install` or `pip upgrade` the tool for the user.** Surface
  the command; let them run it. Package installs touch their Python env.
- **Refuse non-loopback `gemma.base_url`.** Source content over a public
  boundary is a policy violation. The tool refuses too; the skill catches it
  earlier with a clearer message.
- **Refuse to run with both `scanners.codex: false` and `scanners.gemma:
  false`.** Stop at Phase 3; tell the user to enable at least one lane.
- **The Projects v2 board is the source of triage truth.** Don't try to
  dedup findings yourself; that's the tool's job (deterministic
  fingerprints in the issue body, byte-identical to the static lane's).
  Don't close or comment on issues — triage is a separate workflow.
- **Honor `--no-update-check`.** Skip the manifest version probe entirely.

## Notes on the `.security-scan-llm-state.yaml` file

The skill owns this file. Users don't edit it by hand. Recognized keys:

- `pinned_version`     — last known installed `security-scan-llm` version.
- `manifest_path`      — last known path to the bundled manifest.
- `last_checked`       — ISO 8601 UTC of last update check (controls 6h throttle).
- `last_upgrade`       — ISO 8601 UTC of last successful upgrade.

The state file is per-repo. Whether you check it into git is your call:
checking it in pins your team to a specific tool version (analogous to a
lockfile); leaving it out lets each developer track their own install.

## When something goes wrong

| Symptom | Likely cause | Remedy |
|---|---|---|
| `binary not found: security-scan-llm` | tool not installed on this host | `pipx install <ai-skills-clone>/tools/security-scan-llm` |
| `codex CLI not on PATH` | codex isn't installed | install codex CLI; run `codex login` |
| `codex not logged in` | session expired | `codex login` |
| `Ollama unreachable at http://localhost:11434` | Ollama not running | start Ollama daemon |
| `Refusing to send source to non-local Ollama` | `gemma.base_url` is a public host | set to `http://localhost:11434` |
| `SOCKET_API_KEY env unset` | (this is the static lane's job, not this skill's) | this skill doesn't use Socket; see `/leverj:security-scan` |
| Findings double-filed across substrates | mismatched fingerprint scheme | open an issue — the fingerprint MUST be byte-identical between substrates |

## Companion docs

- The CLI: `<ai-skills-clone>/tools/security-scan-llm/README.md`
- The manifest contract: `<ai-skills-clone>/tools/security-scan-llm/SECURITY-SCAN-LLM-MANIFEST.yaml`
- The deterministic sibling skill: `/leverj:security-scan` (drives the
  Docker container with osv, gitleaks, semgrep, trivy, trufflehog, image-CVE,
  Supabase live, supply-chain via Socket.dev).

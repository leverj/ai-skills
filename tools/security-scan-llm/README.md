# security-scan-llm

Host-side LLM SAST lanes for the leverj security-scan pipeline. Complement to
the deterministic GitHub Action / Docker image (`leverj/security-scan`).

## Why this lives here, not in the container

- **`codex`** is a host-side CLI bound to the user's ChatGPT/Codex subscription.
  The container has no `codex` binary and no path to the user's session.
- **`gemma`** talks to Ollama on the host (default `localhost:11434`). Source
  content never crosses the loopback boundary.

Both substrates — this tool and the deterministic container — file into the
**same** GitHub Projects v2 board with a **byte-identical** fingerprint, so
findings dedup across runs regardless of which substrate produced them.

## Install

```bash
# from a clone of leverj/ai-skills
pipx install ./tools/security-scan-llm
# or, scoped to the skill plugin layout used by Claude Code
python3 -m venv ./tools/security-scan-llm/.venv
./tools/security-scan-llm/.venv/bin/pip install -e ./tools/security-scan-llm
```

Both produce a `security-scan-llm` CLI.

## Run

```bash
security-scan-llm \
  --config ~/.security-scan/config.yaml \
  --repo-dir .       \   # scan the working tree (no clone)
  --dry-run              # remove to actually file
```

The tool reads the same `config.yaml` the Docker image consumes. It looks at
`scanners.codex`, `scanners.gemma`, `cross_validate.*`, `triage.*`, `gemma.*`,
`codex.*`, and the standard `project.*` / `github_token_env` block. Other
deterministic-scanner fields are ignored (set by the container).

## Lanes

| Lane | Source | Requires |
|---|---|---|
| codex SAST | `runners/codex.py` | `codex` CLI on PATH, logged in |
| gemma SAST | `runners/gemma.py` | Ollama reachable at `gemma.base_url` |
| Cross-validate (both enabled) | `cross_validate.py` | both lanes successful |
| Triage prose / fuzzy-dup / slack intro | `triage.py` | Ollama reachable |
| Filing | `github.py` | PAT with `project` + `repo` scopes |

## What this does NOT do

- No semgrep, gitleaks, trivy, osv, trufflehog, image-scan, supabase. Those
  live in the container (today) and the GitHub Action (planned).
- No stack detection — the LLM lanes are language-agnostic; the tool walks
  source files filtered by extension.

## Integration with the skill

The `security-scan` skill invokes this tool in Phase 4b after the deterministic
container exits when `scanners.codex` or `scanners.gemma` is true.

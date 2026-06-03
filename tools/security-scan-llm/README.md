# security-scan-llm

Host-side LLM SAST lanes (codex + gemma + bidirectional cross-validation)
for the leverj security-scan pipeline.

**Standalone CLI** — not orchestrated by the `security-scan` Claude Code
skill. The skill drives the deterministic container; this tool drives the
LLM lanes from the host. Both file into the **same** GitHub Projects v2
board with a **byte-identical** fingerprint scheme, so findings dedup
across substrates.

## Why this lives on the host (not in the container)

- **`codex`** is a host-side CLI bound to the user's ChatGPT/Codex
  subscription. The container has no `codex` binary and no path to the
  user's session.
- **`gemma`** talks to Ollama on the host (default `localhost:11434`).
  Source content never crosses the loopback boundary.

Making the LLM lanes a host concern keeps the container CI-friendly and the
LLM tool desktop-friendly. Each tool owns its own contract; neither pretends
to support things it can't actually do.

## Install

```bash
# from a clone of leverj/ai-skills
pipx install ./tools/security-scan-llm
# or scoped to the plugin's bundled checkout (typical Claude Code layout)
python3 -m venv ./tools/security-scan-llm/.venv
./tools/security-scan-llm/.venv/bin/pip install -e ./tools/security-scan-llm
```

Both produce a `security-scan-llm` CLI on PATH.

## Configure

Config lives at `<repo>/.security-scan/config-llm.yaml` — **repo-local**,
versioned with the repo. Independent from the container's
`<repo>/.security-scan/config.yaml` (no shared file; no `~/.security-scan/`).

Minimal `config-llm.yaml`:

```yaml
repo: "leverj/your-repo"
ref:  "main"
project:
  owner:  "leverj"
  number: 7
github_token_env: "GITHUB_TOKEN"   # PAT with repo + project scopes

scanners:
  codex: true        # opt-in
  gemma: true        # opt-in

# Optional tunables (defaults shown — omit any you're happy with)
gemma:
  base_url: "http://localhost:11434"   # MUST be loopback or RFC1918
  model:    "gemma4:26b"
codex:
  binary: "codex"
cross_validate:
  enabled: true       # bidirectional review (only when both lanes on)
triage:
  enabled: false      # gemma-driven issue prose / slack intro / fuzzy-dedup
```

Full schema: see [SECURITY-SCAN-LLM-MANIFEST.yaml](./SECURITY-SCAN-LLM-MANIFEST.yaml).

## Run

```bash
export GITHUB_TOKEN="ghp_..."   # PAT with repo + project scopes
cd <your-repo>
security-scan-llm \
  --config ./.security-scan/config-llm.yaml \
  --repo-dir .     \   # scan the working tree, no clone
  --dry-run            # remove to actually file findings
```

Failure modes:

| Cause | Behavior |
|---|---|
| `codex` binary missing / not logged in | That lane returns `completed=False`; the other lane continues. |
| Ollama unreachable at `gemma.base_url` | That lane returns `completed=False`. |
| `scanners.codex` AND `scanners.gemma` both false | Exit 2 with a clear error — nothing to do. |
| GitHub PAT missing `project` scope | Exit 4 with the GitHub API error. |
| All enabled lanes failed | Exit 3. |

## What this does NOT do

- No semgrep, gitleaks, trivy, osv, trufflehog, image-scan, supabase.
  Those live in the container (`leverj/security-scan`) and the upcoming
  GitHub Action / current CircleCI flow.
- No stack detection. The LLM lanes are language-agnostic and walk source
  files by extension.
- No interactive setup. Edit `config-llm.yaml` directly. (The
  `security-scan` skill scaffolds the sibling `config.yaml` for you; this
  tool intentionally stays a thin CLI.)

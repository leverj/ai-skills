# security-scan-llm

Host-side LLM SAST lanes (codex + claude + gemma + lane-agnostic
cross-validation) for the leverj security-scan pipeline.

Two ways to drive it:

- **Directly** as a CLI (this README) — from CI, scripts, or a developer's
  terminal. No Claude Code involved.
- **Via the Claude Code skill** [`/leverj:security-scan-llm`](../../skills/security-scan-llm/SKILL.md)
  — wraps this CLI with interactive setup, version-vs-manifest upgrade
  prompts, config-migration, and substrate health checks (codex login,
  claude login, Ollama reachability). Use the skill when you want the same UX the
  static-lane skill provides; use the CLI for everything else.

Sibling concern: the deterministic scanners live in the
`leverj/security-scan` Docker container (driven by
[`/leverj:security-scan`](../../skills/security-scan/SKILL.md)). Both
substrates file into the **same** GitHub Projects v2 board with a
**byte-identical** fingerprint scheme, so findings dedup across substrates.

## Why this lives on the host (not in the container)

- **`codex`** is a host-side CLI bound to the user's ChatGPT/Codex
  subscription. The container has no `codex` binary and no path to the
  user's session.
- **`claude`** is a host-side CLI bound to the user's Claude Max/Pro
  subscription (OAuth, no API key). Same story: no binary or session in
  the container.
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

# Each lane is an LLM that scans the repo; any two lanes cross-reference each
# other. `name` = the scanner label / rule-id prefix. `backend` is one of
# codex-cli | claude-cli | ollama.
lanes:
  - name: codex            # cloud, ChatGPT/Codex subscription
    backend: codex-cli
    model: null            # null => the codex CLI default
  - name: claude           # cloud, Claude Max/Pro subscription
    backend: claude-cli
    model: claude-sonnet-4-6
  - name: qwen             # any local Ollama model, labeled `qwen.*`
    backend: ollama
    model: qwen2.5-coder:32b
    base_url: "http://localhost:11434"   # MUST be loopback or RFC1918

cross_validate:
  enabled: true       # each finding reviewed by a different lane (when ≥2 lanes)
triage:
  enabled: false      # ollama-driven issue prose / slack intro / fuzzy-dedup
```

> **Legacy configs auto-migrate.** A pre-0.3 file using `scanners:` +
> `codex:`/`claude:`/`gemma:` blocks is converted to lanes at load time (with a
> one-line notice) — no edit required. New files should use `lanes:`.

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
| `codex` / `claude` binary missing or not logged in | That lane returns `completed=False`; the other lanes continue. |
| Ollama unreachable at an `ollama` lane's `base_url` | That lane returns `completed=False`. |
| No lanes configured (`lanes:` empty / missing, no legacy `scanners:` either) | Exit 2 with a clear error — nothing to do. |
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

# leverj/ai-skills

A bundle of [Skills](https://docs.anthropic.com/en/docs/build-with-claude/agent-skills) for AI coding tools — drop-in workflows that any agent (Claude Code, Codex CLI, Gemini CLI, Cursor, OpenCode, GitHub Copilot CLI) can read.

Each skill lives under `skills/<name>/` and ships its own `SKILL.md`, install docs, templates, and assets. The Claude Code plugin marketplace at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) exposes them as installable plugins.

## Skills in this bundle

| Skill | What it does | Docs |
| --- | --- | --- |
| **sprint** | Scrum/kanban-aware development workflow on top of GitHub Projects v2. Issues are requirements; Project fields are state; ADRs in `.dev/decisions/`. | [SKILL.md](skills/sprint/SKILL.md) · [README](skills/sprint/README.md) |
| **triage** | End-to-end triage & fix loop over a long-lived backlog — an epic's open sub-issues **or** a GitHub Projects v2 board (set in `.dev/triage.json`, overridable per call with `--epic`/`--project`). Auto-closes duplicates and won't-fixes, bundles trivial dep bumps into one PR per ecosystem, ships them. | [SKILL.md](skills/triage/SKILL.md) |
| **security-scan** | Drives the published `leverj/security-scan` Docker image (deterministic: CVEs, secrets, SAST patterns, IaC misconfigs, image-CVE, live Supabase, opt-in supply-chain via Socket.dev). Config repo-local at `<repo>/.security-scan/config.yaml`. Checks Docker Hub for newer image digests on every run and offers a user-confirmed upgrade + config-migration flow. | [SKILL.md](skills/security-scan/SKILL.md) |
| **security-scan-llm** | Drives the host-side [`security-scan-llm`](tools/security-scan-llm/) CLI for LLM SAST (Codex + Gemma + bidirectional cross-validation). Config repo-local at `<repo>/.security-scan/config-llm.yaml`. Checks installed CLI version against the bundled `SECURITY-SCAN-LLM-MANIFEST.yaml` and surfaces upgrade prompts. Files into the **same** Projects v2 board as security-scan with a byte-identical fingerprint scheme — findings dedup across both lanes. | [SKILL.md](skills/security-scan-llm/SKILL.md) |

## Install

### Claude Code (plugin marketplace — recommended)

Install the bundle once; every skill in it becomes available:

```
/plugin marketplace add leverj/ai-skills
/plugin install leverj@leverj-ai-skills
```

Skills are then invoked as `/leverj:<skill>` — for example, `/leverj:sprint pick 42`.

To uninstall:

```
/plugin uninstall leverj@leverj-ai-skills
/plugin marketplace remove leverj-ai-skills
```

### Other tools (manual)

Skills are filesystem artifacts. Clone the bundle once, then point each tool at the per-skill discovery file.

```bash
git clone https://github.com/leverj/ai-skills ~/ai-skills
```

Per-skill, per-tool install instructions (Codex CLI, Gemini CLI, Cursor, OpenCode, Copilot CLI) live under `skills/<skill>/docs/install/<tool>.md` — for example, [skills/sprint/docs/install/](skills/sprint/docs/install/).

## Adding a new skill

1. **Copy the scaffold** into a new skill directory:

   ```bash
   cp -r template/ skills/<new-skill>/
   ```

2. **Fill in the frontmatter** in `skills/<new-skill>/SKILL.md` — set `name` and `description`, then write the skill body. Reference assets via `<SKILL DIR>/<subdir>/<file>` so paths resolve regardless of where the skill is installed.

3. **(Optional) Add per-tool install docs** under `skills/<new-skill>/docs/install/<tool>.md` if the skill needs tool-specific setup.

4. **Register the skill in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)** by appending its directory to the `leverj` plugin's `skills` array:

   ```
   "skills": [
     "./skills/sprint",
     "./skills/<new-skill>"
   ]
   ```

   It will then be invokable as `/leverj:<new-skill>`.

5. **Add a row** to the **Skills in this bundle** table above with a one-line description and links to the skill's `SKILL.md` and `README.md` (if present).

## Repo layout

```
.
├── skills/
│   └── <skill>/         # SKILL.md, AGENTS.md, GEMINI.md, docs/, setup/, templates/, …
├── template/            # Minimal SKILL.md scaffold for new skills
├── .claude-plugin/
│   └── marketplace.json # Bundle manifest for the Claude Code plugin marketplace
├── .dev/                # This repo's own sprint state (decisions, sprint-config.json)
├── README.md
└── LICENSE
```

## License

MIT

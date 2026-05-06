# leverj/ai-skills

A bundle of [Skills](https://docs.anthropic.com/en/docs/build-with-claude/agent-skills) for AI coding tools — drop-in workflows that any agent (Claude Code, Codex CLI, Gemini CLI, Cursor, OpenCode, GitHub Copilot CLI) can read.

Each skill lives under `skills/<name>/` and ships its own `SKILL.md`, install docs, templates, and assets. The Claude Code plugin marketplace at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) exposes them as installable plugins.

## Skills in this bundle

| Skill | What it does | Docs |
| --- | --- | --- |
| **sprint** | Scrum/kanban-aware development workflow on top of GitHub Projects v2. Issues are requirements; Project fields are state; ADRs in `.dev/decisions/`. | [SKILL.md](skills/sprint/SKILL.md) · [README](skills/sprint/README.md) |

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

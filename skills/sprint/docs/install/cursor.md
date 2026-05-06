# Install — Cursor

Cursor auto-discovers `AGENTS.md` in the project root (and nested dirs). It also supports `.cursor/rules/*.mdc`.

## Install (AGENTS.md, recommended)

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
cd /path/to/your/project
ln -s ~/sprint-workflow/skills/sprint/AGENTS.md AGENTS.md
```

Alternative: `mkdir -p .cursor/rules && ln -s ~/sprint-workflow/skills/sprint/SKILL.md .cursor/rules/sprint.mdc`.

## Invocation

In Cursor's chat:

```
run sprint: pick 2
```

Text after `run sprint:` is `<USER REQUEST>`. `<SKILL DIR>` is the rule-file's resolved path.

## Update

Recommended (from inside any project that uses the skill, in Cursor's chat):

```
run sprint: upgrade
```

See [Upgrade Command](../../SKILL.md#upgrade-command) for branch switching (`upgrade <branch>`, `upgrade reset`, `upgrade check`).

Manual fallback:

```bash
cd ~/sprint-workflow && git pull
```

## Migration (existing manual installs)

If you symlinked `AGENTS.md` to `~/sprint-workflow/AGENTS.md` (or `.cursor/rules/sprint.mdc` to `~/sprint-workflow/SKILL.md`) before the bundle restructure, those symlinks break on next `git pull` (the skill source moved into `skills/sprint/`). Recreate them:

```bash
rm AGENTS.md && ln -s ~/sprint-workflow/skills/sprint/AGENTS.md AGENTS.md
# or, for the rules variant:
rm .cursor/rules/sprint.mdc && ln -s ~/sprint-workflow/skills/sprint/SKILL.md .cursor/rules/sprint.mdc
```

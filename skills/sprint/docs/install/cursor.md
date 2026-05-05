# Install — Cursor

Cursor auto-discovers `AGENTS.md` in the project root (and nested dirs). It also supports `.cursor/rules/*.mdc`.

## Install (AGENTS.md, recommended)

```bash
git clone https://github.com/leverj/claude-sprint ~/sprint-workflow
cd /path/to/your/project
ln -s ~/sprint-workflow/AGENTS.md AGENTS.md
```

Alternative: `mkdir -p .cursor/rules && ln -s ~/sprint-workflow/SKILL.md .cursor/rules/sprint.mdc`.

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

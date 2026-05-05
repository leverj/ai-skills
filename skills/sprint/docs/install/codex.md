# Install — Codex CLI

Codex auto-discovers `AGENTS.md` in the project root. This repo ships `AGENTS.md` as a symlink to `SKILL.md`.

## Install

```bash
git clone https://github.com/leverj/claude-sprint ~/sprint-workflow
cd /path/to/your/project
ln -s ~/sprint-workflow/skills/sprint/AGENTS.md AGENTS.md
```

If symlinks aren't supported, `cp` instead and re-copy on update.

## Invocation

```bash
codex "run sprint: pick 2"
codex "run sprint: plan add OAuth"
```

Text after `run sprint:` is `<USER REQUEST>`. `<SKILL DIR>` is the symlink target.

## Update

Recommended (from inside any project that uses the skill):

```bash
codex "run sprint: upgrade"
```

See [Upgrade Command](../../SKILL.md#upgrade-command) for branch switching (`upgrade <branch>`, `upgrade reset`, `upgrade check`).

Manual fallback:

```bash
cd ~/sprint-workflow && git pull
```

## Migration (existing manual installs)

If you symlinked `AGENTS.md` to `~/sprint-workflow/AGENTS.md` before the bundle restructure, the symlink breaks on next `git pull` (the skill source moved into `skills/sprint/`). Recreate it:

```bash
rm AGENTS.md
ln -s ~/sprint-workflow/skills/sprint/AGENTS.md AGENTS.md
```

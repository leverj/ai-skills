# Install — Claude Code

Native skill — Claude Code loads `SKILL.md` from `~/.claude/skills/<name>/`.

## Install

Global:

```bash
git clone https://github.com/leverj/claude-sprint ~/.claude/skills/sprint
```

Per-project: clone into `.claude/skills/sprint` instead.

Optionally append `claude-md-snippet.md` to your project's `CLAUDE.md`.

## Invocation

```
/sprint plan
/sprint pick 2
```

Text after `/sprint` is `<USER REQUEST>`. `<SKILL DIR>` is the install path.

## Update

Recommended (from inside any project that uses the skill):

```
/sprint upgrade
```

See [Upgrade Command](../../SKILL.md#upgrade-command) for branch switching (`/sprint upgrade <branch>`, `/sprint upgrade reset`, `/sprint upgrade check`).

Manual fallback:

```bash
cd ~/.claude/skills/sprint && git pull
```

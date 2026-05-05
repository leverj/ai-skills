# Install — Claude Code

Native skill — Claude Code loads `SKILL.md` from installed plugins or `~/.claude/skills/<name>/`.

## Install (recommended) — plugin marketplace

In Claude Code:

```
/plugin marketplace add leverj/agent-skills
/plugin install sprint@leverj-agent-skills
```

`/sprint` commands become available immediately. Updates flow via `/plugin update`.

## Install (manual) — git clone

Global:

```bash
git clone https://github.com/leverj/agent-skills ~/.claude/skills/sprint
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

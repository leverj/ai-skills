# Install — Claude Code

Native skill — Claude Code loads `SKILL.md` from installed plugins or `~/.claude/skills/<name>/`.

## Install (recommended) — plugin marketplace

In Claude Code:

```
/plugin marketplace add leverj/ai-skills
/plugin install leverj@leverj-ai-skills
```

Skills are namespaced under the plugin: invoke as `/leverj:sprint <subcommand>` (e.g. `/leverj:sprint pick 42`). Updates flow via `/plugin update`.

## Install (manual) — git clone

The skill source lives in `skills/sprint/` inside the bundle repo. Clone the repo to a workspace path, then symlink (or copy) the skill into Claude Code's skills directory.

Global, with a symlink (recommended — keeps `git pull` in one place):

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
ln -s ~/sprint-workflow/skills/sprint ~/.claude/skills/sprint
```

If symlinks aren't available, copy and re-copy on update:

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
cp -R ~/sprint-workflow/skills/sprint ~/.claude/skills/sprint
```

Per-project: replace `~/.claude/skills/sprint` with `.claude/skills/sprint` inside the project root.

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

Manual fallback (symlink install):

```bash
cd ~/sprint-workflow && git pull
```

If you copied instead of symlinked, re-copy after pulling:

```bash
cd ~/sprint-workflow && git pull
rm -rf ~/.claude/skills/sprint
cp -R ~/sprint-workflow/skills/sprint ~/.claude/skills/sprint
```

## Migration (existing manual installs)

If you previously cloned the bundle directly into `~/.claude/skills/sprint` (pre-restructure), that checkout no longer has `SKILL.md` at its root after `git pull` — the skill source moved into `skills/sprint/`. Either switch to the marketplace install above, or re-do the manual install:

```bash
rm -rf ~/.claude/skills/sprint
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
ln -s ~/sprint-workflow/skills/sprint ~/.claude/skills/sprint
```

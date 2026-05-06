# Install — Gemini CLI

Gemini CLI loads `GEMINI.md` from the project root and supports `@`-imports.

## Install

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
```

In each project, create `GEMINI.md` containing:

```
@~/sprint-workflow/skills/sprint/SKILL.md
```

## Invocation

```bash
gemini "run sprint: pick 2"
gemini "run sprint: status"
```

Text after `run sprint:` is `<USER REQUEST>`. `<SKILL DIR>` is the clone path.

## Update

Recommended (from inside any project that uses the skill):

```bash
gemini "run sprint: upgrade"
```

See [Upgrade Command](../../SKILL.md#upgrade-command) for branch switching (`upgrade <branch>`, `upgrade reset`, `upgrade check`).

Manual fallback:

```bash
cd ~/sprint-workflow && git pull
```

## Migration (existing manual installs)

If your `GEMINI.md` imports `@~/sprint-workflow/SKILL.md` from a pre-restructure install, the import breaks on next `git pull` (the skill source moved into `skills/sprint/`). Update it to:

```
@~/sprint-workflow/skills/sprint/SKILL.md
```

# D-001: Rename claude-sprint to ai-skills

**Date**: 2026-04-28
**Author**: Nirmal Gupta
**Status**: Accepted
**Related Issues**: #17 (epic), #12, #13, #14, #15, #16

## Context

The repo currently named `leverj/claude-sprint` was created to hold a single skill (sprint, the scrum-aligned workflow). We are restructuring it to host multiple skills, modeled on [anthropics/skills](https://github.com/anthropics/skills)'s plugin-marketplace pattern. Once the bundle holds more than one skill, `claude-sprint` no longer reflects the repo's scope — a visitor lands expecting a sprint-only repository.

## Decision

Rename `leverj/claude-sprint` → `leverj/ai-skills`.

> **Note**: `agent-skills` was the original proposed name. `ai-skills` was chosen at execution time as shorter and equally descriptive.

## Rationale

- "ai" is the broadest accurate category — these are skills for AI coding tools (Claude Code, Codex, Gemini, Cursor, OpenCode, Copilot CLI), not specifically Claude.
- "skills" matches the directory name (`skills/<name>/`) and the anthropics naming convention.
- Short and memorable; survives future expansion without semantic drift.

## Alternatives Considered

- **Keep `claude-sprint`**: rejected — the name lies once non-sprint skills join the bundle.
- **`agent-skills`**: considered — accurate ("skills for AI agents") and aligned with Anthropic's "agent skills" terminology, but `ai-skills` is shorter and reads more naturally to a wider audience.
- **`leverj-skills`**: rejected — the `leverj-` prefix is redundant with the org context (already at `leverj/`).
- **`claude-agent-skills`**: rejected — `claude-` prefix is misleading (skills target multiple agents, not just Claude); also redundant if Anthropic's anthropics/skills ever federates a community marketplace.
- **`agents`** (singular dir name match): rejected — singular doesn't match the `skills/` directory scheme.

## Consequences

### Positive

- Repo name reflects scope.
- Aligns with anthropics/skills naming for users coming from there.
- Easier external comms ("these are agent skills") vs. having to explain "this is the sprint repo with other skills inside."

### Negative

- External docs/articles linking to specific paths under `leverj/claude-sprint/...` may go stale if their format isn't redirect-friendly. GitHub redirects repo-level URLs (issues, PRs, blob/raw) but external aggregators sometimes cache.
- Local clones at `~/sprint-workflow/` or `~/.claude/skills/sprint/` are unaffected at the directory level — only the git remote URL needs updating. Users running `git remote set-url` once is the full migration cost.

### Risks

- Bookmarks to deep links may not realize redirects exist. Mitigation: GitHub's repo rename redirects all common URL forms; affected users get a one-time 301 and can re-bookmark.

## Action items

- [x] Rename repo via GitHub Settings → Repository name → `ai-skills`.
- [x] Update top-level `README.md` install instructions to use `https://github.com/leverj/ai-skills`.
- [x] Update `docs/install/*.md` clone commands.
- [x] Update `marketplace.json` to use `leverj-ai-skills` as the marketplace `name`.
- [x] Add a release note advising existing local clones to run: `git remote set-url origin https://github.com/leverj/ai-skills.git`.
- [x] Update any references in `.claude-plugin/marketplace.json`, README, and install docs that hardcode the repo name.

The rename itself is independent of the bundle restructure (#12) and can land before, during, or after — GitHub redirects make the order non-blocking.

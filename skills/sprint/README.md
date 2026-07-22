# Sprint skill

A scrum-aligned development workflow on top of **GitHub Projects v2**, runnable across multiple AI coding tools. Requirements live as structured GitHub Issues; sprint state (Status, Priority, Size, Iteration) lives on a Project board configured per GitHub's "Team Planning" template. Architectural decisions are recorded as ADRs in the repo. Any developer can pick up where someone left off.

## Prerequisites

- A supported AI coding tool (see below)
- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated (`gh auth login`)
- A git repo with a GitHub remote

## Supported tools

The canonical workflow lives in `SKILL.md`. `AGENTS.md` is a git symlink to it (mode `120000`), and `GEMINI.md` imports it via `@./SKILL.md` — so every tool reads the same source with no manual sync.

| Tool | Discovery file | Install doc |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/sprint/SKILL.md` | [docs/install/claude-code.md](docs/install/claude-code.md) |
| Codex CLI | `AGENTS.md` (project root) | [docs/install/codex.md](docs/install/codex.md) |
| Gemini CLI | `GEMINI.md` (project root) | [docs/install/gemini-cli.md](docs/install/gemini-cli.md) |
| Cursor | `AGENTS.md` or `.cursor/rules/*.mdc` | [docs/install/cursor.md](docs/install/cursor.md) |
| OpenCode | `AGENTS.md` (project root) | [docs/install/opencode.md](docs/install/opencode.md) |
| GitHub Copilot CLI | `AGENTS.md` (project root) | [docs/install/copilot-cli.md](docs/install/copilot-cli.md) |

## Quick install

Claude Code (plugin marketplace — recommended):

```
/plugin marketplace add leverj/ai-skills
/plugin install leverj@leverj-ai-skills
```

Then invoke as `/leverj:sprint <subcommand>` — e.g. `/leverj:sprint pick 42`.

Claude Code (manual clone):

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
ln -s ~/sprint-workflow/skills/sprint ~/.claude/skills/sprint
```

Other tools (clone once, link from each project):

```bash
git clone https://github.com/leverj/ai-skills ~/sprint-workflow
cd /path/to/your/project
ln -s ~/sprint-workflow/skills/sprint/AGENTS.md AGENTS.md   # or GEMINI.md, .cursor/rules/sprint.mdc, etc.
```

On Windows, enable git symlinks (`git config --global core.symlinks true`, run as admin) or `cp` the file and re-copy on update.

## Updating

`/sprint upgrade` pulls the **entire skills bundle** from its git origin — every skill installed from this repo gets updated, not just sprint. The report groups changed files by `skills/<name>/` and lists which skills moved.

From inside any project that uses the skill:

```
/sprint upgrade                          # pull latest on current branch
/sprint upgrade feat/some-branch         # switch to a branch (e.g., to test a PR)
/sprint upgrade reset                    # return to default branch (master/main)
/sprint upgrade check                    # dry-run; show what would change
```

Or do it manually:

```bash
cd ~/sprint-workflow && git pull   # the bundle clone; ~/.claude/skills/sprint symlinks into it
```

## Quick Start

> Commands below use the canonical `/sprint <sub>` form. **In a Claude Code plugin install**, prefix with `/leverj:` — e.g. `/leverj:sprint setup`. Manual installs and other tools (Codex, Cursor, Gemini, OpenCode, Copilot CLI) use the unprefixed form.

```
/sprint setup          # Discover/create the Project, configure fields, link this repo
/sprint plan           # Create structured requirements as GitHub Issues + Project items
/sprint pick           # Claim an item from the board and implement it
/sprint status         # Dashboard of the current iteration
```

After `/sprint setup`, open the Project's **Workflows** settings page (link is printed at the end of setup) and enable: *Auto-add to project*, *Item closed → Done*, *Pull request opened → In Review*, *Pull request merged → Done*. These are UI-only toggles GitHub does not expose via API.

## Commands

| Command | Purpose |
|---------|---------|
| `/sprint plan` | Discuss and create one or more structured GitHub Issues with acceptance criteria, phases, and risks. Adds them to the Project with Status / Priority / Size set, optionally to an iteration. |
| `/sprint pick [N]` | List available items from the board, claim one, create a branch, implement phase by phase, create a PR. Runs **autonomously by default** (per the Autonomy & Escalation Policy); add `--interactive` to review every step. Status: Ready → In Progress → In Review. |
| `/sprint decide ["title"]` | Record an architectural decision in `.dev/decisions/`, cross-link to GitHub Issues. |
| `/sprint status [all]` | Dashboard read from the Project board. Shows current iteration prominently. `status all` includes other iterations and unscheduled items. |
| `/sprint refine [N]` | Take a Backlog item and add structured acceptance criteria, phases, risks, Priority, and Size — moves it to Status: Ready. |
| `/sprint setup` | Discover or create a GitHub Project, configure Team Planning fields, link this repo, persist `.dev/sprint-config.json`. |
| `/sprint upgrade [branch\|reset\|check]` | Pull the latest skills bundle from origin (updates all skills in the bundle, not just sprint). Optional branch arg switches branches (sticky until reset). |
| `/sprint help` | Show all commands and subcommands with short descriptions. |

## How It Works

### Requirements as GitHub Issues

`/sprint plan` creates Issues with a structured format:

- **User Story** — "As a [role], I want [capability] so that [benefit]"
- **Acceptance Criteria** — WHEN/THEN/SHALL format, directly testable
- **Implementation Phases** — ordered checkboxes, each independently verifiable
- **Risk Assessment** — technical risks, dependencies, unknowns

### Sprint state lives on the Project board

State that scrum tools track — Status (Backlog / Ready / In Progress / In Review / Done), Priority (P0 / P1 / P2), Size (XS / S / M / L / XL), Iteration — are **GitHub Project fields**, not labels. The skill reads and writes those fields directly via `gh project`.

The first `/sprint setup` either links this repo to an existing Project or creates a new one named after the repo. Choice is persisted in `.dev/sprint-config.json` (`project_number` only — names are renameable in the GitHub UI without breaking anything).

The Iteration field is created **lazily** the first time someone names a sprint; until then, items live in an "infinite sprint" (no iteration assigned).

### Concurrency via GitHub Assignment

When a developer runs `/sprint pick`, the skill assigns the issue to them on GitHub before starting work and moves the Project Status to `In Progress`. Other developers see the item as taken. GitHub assignment is the lock — no file-based coordination needed.

### Decisions as ADRs

`/sprint decide` creates files in `.dev/decisions/` with context, rationale, alternatives considered, and consequences. These are version-controlled alongside the code they govern. GitHub Issues get a comment linking to the decision for cross-reference.

### Phase-by-Phase Implementation

`/sprint pick` doesn't implement everything at once. It works through the Implementation Phases defined on the issue:

1. Implement the phase (with a [Dependency Safety Check](SKILL.md#dependency-safety-check) gate before any new dependency is added)
2. Write/update tests
3. Update the phase checkbox on GitHub
4. Move to next phase

**As of v0.8.0, `pick` runs autonomously by default at every size** (previously only L/XL were autonomous). It commits and pushes after each phase — so the remote branch reflects current progress and the developer can interrupt with coherent state — runs the pre-PR review battery once on the cumulative diff at PR-open time, and opens the PR without asking. Manual end-to-end verification is deferred to the developer on the open PR.

Autonomous does **not** mean "never ask." It is governed by the **Autonomy & Escalation Policy** (see [SKILL.md](SKILL.md#autonomy--escalation-policy)): every mid-implementation decision is classified into one of three tiers —

- **Block** — irreversible/unrecoverable actions, spending money, product/priority tradeoffs, security & trust-boundary changes (auth, secrets, PII, permissions), and *breaking* public-contract changes → the skill stops and asks.
- **Propose & proceed** — *additive* public-contract changes and UX decisions → the skill picks the option by a fixed precedence (acceptance criteria → ADR → repo convention → ecosystem), builds it, and flags it under `⚠ Decisions to review` in the PR.
- **Decide & log** — naming, reuse, internal structure, style → the skill just does it and records one line in the issue's **Assumption Ledger** (`## Assumptions`).

The result: instead of answering a stream of questions during the run, the developer reviews one batch at PR time — the flagged decisions and the assumption ledger. Run `/sprint pick N --interactive` for the old review-before-every-step behavior.

If a session ends mid-work, the next developer can see which phases are checked off.

### Fresh-eyes review gates (v0.9.0)

The catch with autonomous-default is that the coder reviewing its own work is worth little — it shares every blind spot that produced the bug. So before opening a PR, `pick` runs an independent review through **three reviewers** — run in a fresh context that never saw the coder's reasoning wherever the substrate allows (external CLI or subagent), and falling back to a *labeled degraded* in-context review otherwise (see [SKILL.md](SKILL.md#fresh-eyes-review-gates)):

- **QA — black-box**: gets the acceptance criteria + how to run the app, *not* the diff; tries to make each criterion fail.
- **Security — white-box**: gets the diff; hunts secrets / injection / authz gaps. Any finding blocks the PR and escalates.
- **Architecture — white-box**: gets the diff + your ADRs; flags contradictions and parallel-pattern drift.

Each reviewer uses the best **substrate** available, configured at `/sprint setup`:

1. **External LLM CLI** (`codex`, `gemini`) — a fresh process, and cross-model when the CLI runs a *different* model than the coding host (uncorrelated blind spots). Strongest option. Approved per-machine (code leaves the machine).
2. **Subagent** (e.g. Claude Code's Agent tool) — fresh context, same model.
3. **In-context** — degraded floor; the review runs inline and is labeled as such.

Setup auto-detects an installed CLI and records the choice in `.dev/sprint-config.json` (committed `review` block); per-machine approval to send code to an external CLI lives in a gitignored `.dev/sprint-config.local.json`. Blocking failures and inconclusive reviewers (substrate failed on every tier) escalate before the PR opens and are never treated as a pass. (A QA review that ran but couldn't drive the app returns a *labeled degraded* pass/fail — that's different from inconclusive.) `review.mode: "off"` is a labeled waiver that skips the independent reviewers but still runs the plain in-context battery.

## Labels (small set)

Labels are intentionally minimal — Status / Priority / Size live as Project fields, not labels.

| Label | Meaning |
|-------|---------|
| `type:feature` | New functionality (drives `feat/` branch prefix) |
| `type:bug` | Something broken (drives `bug/` branch prefix) |
| `type:refactor` | Internal improvement (drives `refactor/` branch prefix) |

`package:*` labels are created on-the-fly for monorepo projects (e.g., `package:ui`, `package:server`).

## Decision Records

Decisions are stored in `.dev/decisions/` with this naming convention:

```
.dev/decisions/D-001-use-supabase-for-auth.md
.dev/decisions/D-002-monorepo-structure.md
```

Each file captures: Context, Decision, Rationale, Alternatives Considered, and Consequences.

## Customization

Fork this repo to customize:

- **Labels**: Edit `setup/labels.json` to change names, colors, or add new labels
- **Issue template**: Edit `templates/issue-body.md` to change the issue structure
- **Decision template**: Edit `templates/decision-record.md` to change the ADR format
- **Workflow**: Edit `SKILL.md` to modify command behavior

## Uninstalling

Claude Code (plugin marketplace install):

```
/plugin uninstall leverj@leverj-ai-skills
/plugin marketplace remove leverj-ai-skills
```

Or run `/plugin` for the interactive UI and remove from the **Installed** and **Marketplaces** tabs.

Manual install:

```bash
# Global
rm -rf ~/.claude/skills/sprint

# Per-project
rm -rf .claude/skills/sprint
```

## License

MIT

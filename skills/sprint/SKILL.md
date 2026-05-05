---
name: sprint
description: >
  Scrum-aligned development workflow on top of GitHub Projects v2. Commands: plan (create
  requirements), pick (claim & implement), decide (record decisions), status (dashboard),
  refine (groom items), setup (bootstrap Project), upgrade (pull latest skill). Uses gh
  CLI for issues + Project items, and `.dev/decisions/` for ADRs.
allowed-tools: Bash(gh *) Bash(git *) Bash(ls *) Bash(mkdir *) Bash(cat *) Read Write Edit Glob Grep Agent
argument-hint: "<plan|pick|decide|status|refine|setup|upgrade|help> [arguments]"
effort: high
---

# Sprint — Development Workflow Skill

You manage a scrum-aligned development workflow on top of **GitHub Projects v2**. Issues are still where requirements live; the Project board is where state lives. Architectural decisions are stored in `.dev/decisions/` in the repo.

**Key principles:**
- GitHub Issues are the requirement (User Story, Acceptance Criteria, Implementation Phases, Risk).
- The GitHub Project (one per repo or one per team) is the board. **Status, Priority, Size, and Iteration are Project fields, not labels.** This is GitHub's published "Team Planning" template; we use it verbatim.
- Labels are reserved for `type:*` (drives branch naming) and `package:*` (monorepo filtering). Nothing else.
- Assignment on the GitHub Issue is the concurrency lock.
- Acceptance criteria use WHEN/THEN/SHALL format for testability.
- Implementation is phased — implement, test, and verify each phase before moving on.
- Decisions capture the *why* alongside the *what*.
- **Never commit, push, or create PRs without explicit user permission.** Always present changes for review first and ask the developer to confirm before any git commit, git push, or PR creation.

The skill templates are in the `templates/` directory and label definitions in `setup/labels.json`, both relative to this skill's directory: `<SKILL DIR>`.

## Invocation

This workflow is tool-agnostic. Two placeholders appear throughout:

- **`<USER REQUEST>`** — the developer's invocation arguments (e.g., `pick 2`, `plan add OAuth`, or a free-form description).
- **`<SKILL DIR>`** — the absolute path to the directory containing this `SKILL.md` (used to locate `templates/`, `setup/labels.json`, and the skill's git checkout for `upgrade`).

How each tool resolves them:

| Tool | `<USER REQUEST>` | `<SKILL DIR>` |
| --- | --- | --- |
| Claude Code | The text after `/sprint` in the slash-command invocation. Treat the whole tail (e.g., `pick 2`) as `<USER REQUEST>`. | The directory of the loaded skill (typically `~/.claude/skills/sprint/`). |
| Codex CLI | Inline in the prompt: `codex "run sprint: pick 2"`. The text after `run sprint:` is `<USER REQUEST>`. | The directory containing `AGENTS.md` (the symlink to `SKILL.md`) in the cloned repo. |
| Gemini CLI | Inline in the prompt: `gemini "run sprint: pick 2"`. Text after `run sprint:` is `<USER REQUEST>`. | The directory containing `GEMINI.md` (which `@./SKILL.md`-imports this file). |
| Cursor | Either invoke the rule by name in chat with the request appended, or place the request in the chat message. | The rules directory holding the symlink/copy. |
| OpenCode | Inline in the prompt; OpenCode reads `AGENTS.md` automatically from the working directory. | Project root or the directory containing `AGENTS.md`. |
| GitHub Copilot CLI | Inline in the prompt with the request as the message body. | Project root or the directory containing `AGENTS.md`. |

If the tool does not auto-substitute, treat the placeholder as a contextual reference: read the user's actual message to determine `<USER REQUEST>`, and read the working directory or the rule-file's location to determine `<SKILL DIR>`.

## User instructions

<USER REQUEST>

## Command routing

Parse the first word of the user's arguments to determine the command:

- **`plan`** (or no arguments) → Go to [Plan Command](#plan-command)
- **`pick`** → Go to [Pick Command](#pick-command)
- **`decide`** → Go to [Decide Command](#decide-command)
- **`status`** → Go to [Status Command](#status-command)
- **`refine`** → Go to [Refine Command](#refine-command)
- **`setup`** → Go to [Setup Command](#setup-command)
- **`upgrade`** → Go to [Upgrade Command](#upgrade-command)
- **`help`** → Go to [Help Command](#help-command)

If the first word doesn't match any command, treat the entire input as a plan description and go to [Plan Command](#plan-command).

---

## Resolve Project Context

**Every command except `setup` and `upgrade` must resolve Project context first before doing anything else.** Stop with a clear error message if any check fails.

### Step 1: Verify prerequisites

Run these checks in parallel:

1. `gh auth status` — if this fails, tell the user: "GitHub CLI is not authenticated. Run `gh auth login` first."
2. `git rev-parse --is-inside-work-tree` — if this fails, tell the user: "Not inside a git repository."
3. `gh repo view --json nameWithOwner -q .nameWithOwner` — if this fails, tell the user: "No GitHub remote found. Add one with `git remote add origin <url>`." Save the result as `REPO` (e.g., `owner/repo`).

### Step 2: Read sprint config

Read `.dev/sprint-config.json`. Expected shape:

```json
{ "project_number": 7, "project_owner": "leverj" }
```

If the file does not exist, tell the user: "No sprint config found. Run `/sprint setup` first to create or link a GitHub Project for this repo." Stop.

### Step 3: Resolve Project field IDs (cached for this command)

Run once and cache for the duration of the command:

```
gh project field-list <PROJECT_NUMBER> --owner <PROJECT_OWNER> --format json
```

Extract:

- `STATUS_FIELD_ID` and option IDs for `Backlog`, `Ready`, `In Progress`, `In Review`, `Done`
- `PRIORITY_FIELD_ID` and option IDs for `P0`, `P1`, `P2`
- `SIZE_FIELD_ID` and option IDs for `XS`, `S`, `M`, `L`, `XL`
- `ITERATION_FIELD_ID` if it exists (may be `None` until the first sprint is created lazily)
- `PROJECT_ID` — the GraphQL node ID of the Project itself (needed for `gh project item-edit`). Get via `gh project view <PROJECT_NUMBER> --owner <PROJECT_OWNER> --format json | jq .id`.
- `PROJECT_TITLE` — the human-readable title (may differ from repo name if the user linked an existing Project). From the same `gh project view` response: `jq .title`.
- `OWNER_TYPE` — `Organization` or `User`. Get via `gh api graphql -f query='query($login:String!){repositoryOwner(login:$login){__typename}}' -f login=<PROJECT_OWNER> --jq '.data.repositoryOwner.__typename'`. Used to construct correct Project URLs (`/orgs/<OWNER>/projects/<N>` for orgs, `/users/<OWNER>/projects/<N>` for users — the bare `/<OWNER>/projects/<N>` form only redirects for orgs).

If any required Status/Priority/Size field or option is missing, tell the user: "Project fields are misconfigured. Run `/sprint setup` to repair." Stop.

### Step 4: Determine current iteration (if Iteration field exists)

If `ITERATION_FIELD_ID` is set:

- Read iteration configuration from the field-list response: `configuration.iterations` (active) and `configuration.completedIterations`.
- `CURRENT_ITERATION` = the iteration whose `startDate` ≤ today < `startDate + duration`.
- If none matches, `CURRENT_ITERATION_ID = None`. The skill treats "no current iteration" as the "infinite sprint" / backlog-of-Ready case.

If `ITERATION_FIELD_ID` is `None`, set `CURRENT_ITERATION_ID = None`.

---

## Grill Me Protocol

**Purpose**: Build shared understanding through small, focused turns — not a form. Used by `/sprint plan` and `/sprint refine` so the developer doesn't have to read or fill in long blocks upfront. They get small bites and answer one thing at a time.

**Core rules**:

1. **One question per turn.** Each assistant message contains exactly one focused question. Never list multiple questions in the same turn, never present a checklist for the developer to fill in, never preview "and then I'll ask about X, Y, Z."
2. **Wait for the answer.** Do not predict, do not pre-fill, do not move on until the developer has answered.
3. **Let the answer shape the next question.** The next question is informed by what the developer just said. The protocol is *adaptive*, not a script — if an answer reveals a sharp edge case, drill into that next, even if it skips ahead in the dimensions list.
4. **Cover the dimensions, not in any fixed order.** Dimensions to cover for a new issue (or to backfill on an existing issue):
   - **Problem**: what hurts? what's the goal?
   - **Users / scope**: who's affected? what's in / out?
   - **Behavior**: happy path, edge cases, errors, persistence, UI behavior.
   - **Type**: feature / bug / refactor.
   - **Priority**: P0 (blocking) / P1 (important) / P2 (nice-to-have).
   - **Size**: XS / S / M / L / XL.
   - **Risks & dependencies**: technical unknowns, blockers, related work.
   - **Phasing**: how to split implementation into 2–4 independently testable phases.
5. **Reflect periodically.** After 3–5 answered questions, summarize the picture in 2–3 lines and ask "does that match your intent?" before continuing. This catches drift early instead of at the end.
6. **Escape hatch.** If the developer pastes a full spec, says "just create it", or otherwise signals they don't want to be interviewed, skip the protocol: propose the structured issue directly for confirmation.
7. **Stop when the dimensions are covered well enough to write a good issue.** Don't grill for completeness's sake — there's almost always more to ask, and the goal is a good issue, not a perfect one.

---

## Plan Command

**Purpose**: Interactive session to refine and create one or more structured GitHub Issues, add them to the Project, and set their Status / Priority / Size fields.

### Step 0: Resolve Project context

Run [Resolve Project Context](#resolve-project-context).

### Step 1: Discuss and decompose requirements

Ask the developer what they want to build, fix, or improve. They may give anything from a one-liner ("add social login") to a detailed spec.

Run the [Grill Me Protocol](#grill-me-protocol) to flesh out the requirement — small, focused turns, one question at a time, adapting to each answer.

**Decomposition** — when the picture coming back from Grill Me reveals multiple distinct concerns, propose a split: "This looks like it breaks into N pieces: [list]. Does this split make sense, or would you group differently?" Example: "add social login" might break into OAuth provider integration / Account linking / Session management / Sign-in UI. If the developer agrees to split, run Grill Me on each piece individually to fill in its dimensions. If the requirement is small and self-contained, skip decomposition and stay with the single piece.

**Confirmation** — don't create any issues until the developer confirms the full set. They may want to merge, split, reprioritize, or defer pieces.

Note dependencies between issues in the Notes section of each issue body (e.g., "Depends on #42 for OAuth token flow").

**Parent issue grouping (default ON)**: After confirming the decomposition (or before creating a single issue), decide on parent/sub-issue structure:

- **Multiple decomposed issues** → create a **parent issue** that holds the umbrella user story; each decomposed piece becomes a sub-issue. Propose the parent title and confirm with the developer.
- **Single new issue** → check whether it belongs under an existing open issue. Surface candidates with `gh issue list --state open --json number,title --limit 100` and ask: "Attach as a sub-issue under an existing issue (provide #), create a new parent, or file standalone?"
- **Default to grouping**: prefer attaching under a parent (existing or new) over filing standalone. File standalone only when the developer confirms the issue genuinely doesn't relate to other open work.

Capture per-issue: `PARENT` = `{existing-issue-number}` | `{new-parent}` | `none`. Parents are created first in Step 6 so their node IDs are available when linking children.

### Step 2: Structure each requirement

For each requirement discussed, read the template from `<SKILL DIR>/templates/issue-body.md` and fill it in:

- **User Story**: "As a [role], I want [capability] so that [benefit]" format.
- **Acceptance Criteria**: WHEN/THEN/SHALL format. Cover happy path, edge cases, error handling, persistence (if applicable), UI/UX behavior (if applicable).
- **Implementation Phases**: Break into 2–4 ordered phases. Each phase independently testable. Don't be too granular — each should represent a meaningful chunk.
- **Risk Assessment**: Technical risks, dependencies, unknowns.
- **Notes**: Context, links to decisions, references.

### Step 3: Iteration assignment (explicit)

Ask the developer: "Assign these to an iteration?
1. Current iteration (if one exists)
2. A new iteration (give name + start date + duration)
3. None — they'll live in the backlog
4. A specific existing iteration"

Capture `TARGET_ITERATION_ID` per issue. The default is **none** (no iteration set) — that's the "infinite sprint" case.

**Lazy iteration field creation**: If the developer asks to assign to an iteration but `ITERATION_FIELD_ID` is `None`, create the field first:

```
gh api graphql -f query='
  mutation($projectId: ID!) {
    createProjectV2Field(input: {
      projectId: $projectId
      dataType: ITERATION
      name: "Iteration"
    }) { projectV2Field { ... on ProjectV2IterationField { id } } }
  }' -f projectId="$PROJECT_ID"
```

Re-fetch field-list to capture the new `ITERATION_FIELD_ID`.

**Lazy iteration creation**: If the developer named a new iteration that doesn't exist yet, create it via raw GraphQL:

```
gh api graphql -f query='
  mutation($fieldId: ID!, $iterations: [ProjectV2IterationFieldIterationInput!]!) {
    updateProjectV2IterationField(input: {
      iterationFieldId: $fieldId
      iterations: $iterations
    }) { iterationField { ... } }
  }' \
  -f fieldId="$ITERATION_FIELD_ID" \
  -f iterations='[{"startDate":"YYYY-MM-DD","duration":14,"title":"Sprint N"}]'
```

If the GraphQL mutation surface differs in your gh version, fall back to instructing the user to create the iteration in the UI and re-run `/sprint plan`. Surface the failure clearly; do not silently skip.

### Step 4: Determine labels (small set)

For each issue:

- **Type** (exactly one): `type:feature`, `type:bug`, or `type:refactor`. Drives branch naming during `pick`.
- **Package** (optional, monorepos): If the project is a monorepo and the requirement targets a specific package, create a `package:<name>` label if it doesn't exist: `gh label create "package:<name>" --color "c5def5" --description "Package: <name>" --force`.

**Do not create or use** `priority:*`, `ready`, `needs-refinement`, or `in-progress` labels. Those concepts live in the Project's Status / Priority fields now.

### Step 5: Definition of Ready check

For each issue, decide initial Status:

- If acceptance criteria, phases, risks, **Priority, and Size** were all discussed and set → `Status: Ready`.
- If any of those are missing or the developer said "I haven't fully thought it through" → `Status: Backlog`. The issue can be picked up later via `/sprint refine`.

### Step 6: Create each issue and add to Project

**Order**: create any new parent issues **first**, capture their node IDs, then create children and link them. Existing parents need only a node-ID lookup, not creation.

For each requirement, in order:

A. **Create the GitHub Issue**:

```
gh issue create \
  --title "<concise title>" \
  --body "<structured body>" \
  --label "type:<x>[,package:<y>]"
```

Capture `ISSUE_URL` and `ISSUE_NUMBER` from the response. Then capture the GraphQL node ID (needed for sub-issue linking):

```
ISSUE_NODE_ID = gh issue view <ISSUE_NUMBER> --json id -q .id
```

B. **Add the issue to the Project explicitly** (do not rely on the auto-add workflow — it may not be enabled, and it fires async):

```
gh project item-add <PROJECT_NUMBER> --owner <PROJECT_OWNER> --url <ISSUE_URL> --format json
```

Capture `ITEM_ID` from the response (parse `.id`).

C. **Set field values** with `gh project item-edit`:

```
# Status
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <STATUS_FIELD_ID> \
  --single-select-option-id <STATUS_OPTIONS["Ready" or "Backlog"]>

# Priority
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <PRIORITY_FIELD_ID> \
  --single-select-option-id <PRIORITY_OPTIONS["P0"|"P1"|"P2"]>

# Size
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <SIZE_FIELD_ID> \
  --single-select-option-id <SIZE_OPTIONS["XS"|"S"|"M"|"L"|"XL"]>

# Iteration (only if user assigned one)
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <ITERATION_FIELD_ID> \
  --iteration-id <TARGET_ITERATION_ID>
```

D. **Link to parent issue** (if `PARENT` for this issue is not `none`):

If `PARENT` refers to an existing issue number, look up its node ID once: `PARENT_NODE_ID = gh issue view <PARENT_NUMBER> --json id -q .id`. If `PARENT` was a new parent created earlier in this loop, use its captured `ISSUE_NODE_ID`.

```
gh api graphql -f query='
  mutation($parentId: ID!, $childId: ID!) {
    addSubIssue(input: { issueId: $parentId, subIssueId: $childId }) {
      issue { number }
      subIssue { number }
    }
  }' -f parentId="$PARENT_NODE_ID" -f childId="$ISSUE_NODE_ID"
```

If the mutation fails (the sub-issues feature is not enabled on this repo, or the gh/GraphQL surface differs), surface the error clearly and fall back to recording `Parent: #<PARENT_NUMBER>` in the child's issue body Notes section. Do not silently skip.

### Step 7: Summary

After all issues are created, present a summary table. Indent sub-issues under their parents to show hierarchy:

```
Created N issues:
  #41  Social login                          [feature, P1, L, Ready, Sprint 3]   (parent)
    └ #42  OAuth provider integration        [feature, P1, M, Ready, Sprint 3]
    └ #43  Account linking flow              [feature, P1, M, Ready, Sprint 3]
    └ #44  Sign-in UI                        [feature, P1, S, Ready, Sprint 3]
  #45  Artist social links                   [feature, P2, S, Backlog]           (standalone)

Project: https://github.com/<owner>/projects/<N>
```

---

## Pick Command

**Purpose**: Claim a Project item and implement it phase by phase.

Arguments after `pick` are optional:
- `/sprint pick` — show available items and let the developer choose
- `/sprint pick 42` — directly pick issue #42

### Step 0: Resolve Project context

Run [Resolve Project Context](#resolve-project-context).

### Step 1: Show available work

If an issue number was provided as argument, skip this display and go directly to Step 2.

Otherwise, fetch all Project items (single call):

```
gh project item-list <PROJECT_NUMBER> --owner <PROJECT_OWNER> --format json --limit 200
```

Slice locally. The sectioning depends on whether a current iteration exists:

**If `CURRENT_ITERATION_ID` is set** (a sprint is active):

- `YOUR_WORK` — Status=`In Progress` AND assignee includes current user
- `READY_NOW` — Status=`Ready` AND no assignee AND Iteration=CURRENT_ITERATION_ID
- `READY_UNSCHEDULED` — Status=`Ready` AND no assignee AND Iteration is unset
- `READY_FUTURE` — Status=`Ready` AND no assignee AND Iteration is set AND ≠ CURRENT_ITERATION_ID
- `BACKLOG` — Status=`Backlog` (or unset). Show only as a hint, not as pickable.

**If `CURRENT_ITERATION_ID` is None** (infinite-sprint case):

- `YOUR_WORK` — Status=`In Progress` AND assignee includes current user
- `READY` — Status=`Ready` AND no assignee (flat, no iteration sub-grouping)
- `BACKLOG` — Status=`Backlog` (or unset). Show only as a hint.

Sort within each section by Priority (P0 first), then Size (smallest first).

Present (sprint-active example):

```
YOUR WORK
  #42  Feed freeze fix          [bug, P0, M]    In Progress

READY — Sprint 3 (current iteration, ends in 6 days)
  #43  Search filter support    [feature, P1, L]
  #44  OAuth flow               [feature, P1, M]

READY — unscheduled (not in any iteration)
  #50  Cleanup old fixtures     [refactor, P2, S]

READY — other iterations
  #45  Account linking          [feature, P2, S]   Sprint 4

BACKLOG (needs refinement — run /sprint refine first)
  #46  Performance work
```

If sections are empty, show "(none)" rather than omitting.

Picking from `READY_UNSCHEDULED` or `READY_FUTURE` is a deliberate off-sprint choice — Step 2.3 (off-sprint warning) prompts for confirmation in both cases.

### Step 2: Claim the item

Once the developer picks an issue (or one was specified via argument):

1. **Find the corresponding Project item** by issue number from the item list. If the issue is not on the Project board:
   - Tell the user: "Issue #N is not on the Project board. Run `/sprint refine N` to add and refine it, or check the issue exists."
   - Stop.
   Capture `ITEM_ID`.

2. **Hard-block on Backlog**: If the item's Status is `Backlog` or unset, refuse:
   - "Issue #N is at Status: Backlog. Run `/sprint refine N` to make it implementable, then `/sprint pick N`."
   - Stop.

3. **Off-sprint warning** (only if `CURRENT_ITERATION_ID` is set):
   - If the item has Iteration set to a different iteration: ask "Issue #N is in iteration `<other>`, not the current iteration `<current>`. Pick anyway? [y/N]". If no, stop.
   - If the item has no Iteration assigned: ask "Issue #N has no iteration assigned (not part of any sprint). Pick anyway? [y/N]". If no, stop.
   - If the item is in the current iteration, no prompt — proceed.

   When `CURRENT_ITERATION_ID` is None (infinite-sprint case), skip this step entirely.

4. **Check current assignee** on the issue:
   - `gh issue view N --json assignees -q '.assignees[].login'`
   - If assigned to someone else: warn: "This issue is assigned to @<user>. Reassign to yourself? [y/N]" If no, stop.
   - If assigned to current user: proceed.

5. **Assign to self on the Issue**:

```
gh issue edit N --add-assignee @me
```

6. **Move Status: Ready → In Progress on the Project**:

```
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <STATUS_FIELD_ID> \
  --single-select-option-id <STATUS_OPTIONS["In Progress"]>
```

### Step 3: Create branch

1. Get the issue title and type label: `gh issue view N --json title,labels`
2. Determine branch prefix from labels:
   - `type:bug` → `bug/`
   - `type:feature` → `feat/`
   - `type:refactor` → `refactor/`
   - Default → `feat/`
3. Generate branch name: `<prefix><N>-<slugified-title>` (lowercase, hyphens, max 50 chars).
   - Example: `bug/42-fix-feed-freeze-on-background`
4. Create and switch: `git checkout -b <branch-name>`
   - If the branch already exists, ask the developer: switch to it or create an alternate name?

### Step 4: Read the issue spec

Fetch the full issue body: `gh issue view N --json body,title -q '.body'`

Parse the issue body to extract:
- **Acceptance Criteria** — drives what to test
- **Implementation Phases** — drives the work order
- **Risk Assessment** — be aware during implementation

### Step 5: Implement phase by phase

For each phase listed in the Implementation Phases section:

1. **Implement** the phase — write the code, following existing project patterns and conventions.

   **Dependency safety gate**: Before editing any manifest file (`package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, etc.) or running any install/add command (`npm install`, `pnpm add`, `yarn add`, `pip install`, `cargo add`, `go get`, `mvn install -Dversion=`, etc.) that introduces a new dependency or changes a resolved version, run the [Dependency Safety Check](#dependency-safety-check). The check must complete with a clean pass, an accepted fallback substitution, or an explicit override before the manifest edit/install proceeds. Do not edit the manifest first and check afterward — the check gates the edit.
2. **Test** — write or update tests that verify the acceptance criteria covered by this phase. Run the test suite to confirm.
3. **Update the issue** — mark the phase checkbox as complete on GitHub:
   - Fetch current body: `gh issue view N --json body -q '.body'`
   - Find the specific `- [ ] Phase X:` line and replace `- [ ]` with `- [x]`
   - Update: `gh api repos/{REPO}/issues/N -f body="<updated body>"`

Repeat for each phase. If a phase reveals problems or new requirements, discuss with the developer before proceeding.

**Do NOT commit anything yet.** Code changes are local only at this point.

### Step 6: Final review

After all phases are complete:

1. Run the full test suite
2. Check for lint or type errors if the project has those tools
3. Review all changes: `git diff` to show the developer what was changed
4. Present a summary of all changes, organized by phase

### Step 7: User review and commit

**Ask the developer to review the changes before committing.** Present:
- A summary of files changed and what each change does
- The proposed commit message(s)
- Ask: "Would you like to review the diff, adjust anything, or proceed with committing?"

**Only after the developer explicitly approves**, commit the changes:
- `git add <specific files>` (never `git add -A`)
- Create commit(s) referencing the issue: `Refs #N: <phase description>`

**Do NOT push to remote yet.**

### Step 8: Push and create PR

**Ask the developer for permission before pushing and creating the PR.** Present:
- The commit(s) that will be pushed
- The proposed PR title and body
- Ask: "Ready to push and create the PR?"

**Only after the developer explicitly approves**, push and create the PR:

1. Push: `git push -u origin <branch-name>`
2. Create PR:

```
gh pr create --title "<concise title>" --body "Closes #N

## Summary
<bullet points of what was done>

## Acceptance Criteria Verified
<list each criterion and how it was verified>

## Test Plan
<what tests were added/modified>

## Dependency Safety
<Render the verification log captured during the per-phase Dependency Safety Check. One row per package added or upgraded:
  - `package@version` (final, after any fallback)
  - Originally requested version (if different from final)
  - Publish date
  - Advisories checked (IDs or 'none')
  - Fallback reason (if a substitution was applied)
  - Override justification (if a hard-block was overridden)
If no dependencies were added or upgraded in this PR, write 'No dependency changes.'>
"
```

3. **Move Status: In Progress → In Review on the Project** (skill-driven; do not rely on the workflow):

```
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <STATUS_FIELD_ID> \
  --single-select-option-id <STATUS_OPTIONS["In Review"]>
```

The PR-merged → `Status: Done` transition is handled by the GitHub workflow if enabled (see [Setup Command](#setup-command)), not by the skill, since merge happens after the skill's job is done.

### Step 9: Report

Show the PR URL and a summary of what was implemented, which phases were completed, and any remaining notes.

---

## Decide Command

**Purpose**: Record an architectural or design decision with full rationale.

Arguments after `decide` are optional:
- `/sprint decide` — interactive, ask what the decision is about
- `/sprint decide "Use PostgreSQL for event store"` — title provided upfront

### Step 1: Find next decision number

```
ls .dev/decisions/D-*.md 2>/dev/null | sort -V | tail -1
```

Extract the number from the last file and increment. If no files exist, start at D-001. Pad to 3 digits.

### Step 2: Discuss the decision

If no title was provided as argument, ask the developer:
- What decision needs to be recorded?
- What was the context — what problem or situation prompted this?
- What alternatives were considered?
- Why was this option chosen over the alternatives?
- What are the consequences (positive and negative)?

If a title was provided, still probe for context, rationale, and alternatives.

### Step 3: Link to issues

Ask: "Are there GitHub Issues related to this decision?"

If yes, note the issue numbers for cross-linking.

### Step 4: Write the decision record

Read the template from `<SKILL DIR>/templates/decision-record.md` and fill it in with the discussed details.

Write to `.dev/decisions/D-<NNN>-<slugified-title>.md`

Example: `.dev/decisions/D-003-use-postgresql-for-event-store.md`

### Step 5: Cross-link to issues

For each related GitHub Issue, add a comment:

```
gh issue comment N --body "Decision recorded: [D-<NNN>: <title>](.dev/decisions/D-<NNN>-<slug>.md)

**Decision**: <one-line summary>
**Rationale**: <one-line summary>"
```

### Step 6: Report

Show the file path, a summary of the decision, and which issues were linked.

---

## Status Command

**Purpose**: Bird's-eye view of the current sprint state, read from the Project board.

Arguments after `status` are optional:
- `/sprint status` — show the current iteration prominently; collapse other iterations and no-iteration items into a one-line count.
- `/sprint status all` — show everything, including items in other iterations and items with no iteration set.

### Step 0: Resolve Project context

Run [Resolve Project Context](#resolve-project-context).

### Step 1: Fetch in parallel

Run these in parallel:

A. Project items (single call):

```
gh project item-list <PROJECT_NUMBER> --owner <PROJECT_OWNER> --format json --limit 200
```

B. Open PRs in the repo:

```
gh pr list --state open --json number,title,author,headRefName,url --limit 20
```

C. Recently closed issues (fallback for Done if Project workflow isn't enabled):

```
gh issue list --state closed --json number,title,closedAt --limit 10 --sort updated
```

D. Decision records:

```
ls .dev/decisions/D-*.md 2>/dev/null
```

For each, read just the first line (title) for display.

### Step 2: Slice items by Status

From (A):

- `IN_PROGRESS` = Status=In Progress
- `IN_REVIEW` = Status=In Review
- `READY` = Status=Ready
- `BACKLOG` = Status=Backlog OR Status=unset
- `DONE_RECENT` = Status=Done, sorted by `updatedAt` desc, top 5

If `CURRENT_ITERATION_ID` is set (and the user did not pass `all`):
- Within IN_PROGRESS, IN_REVIEW, READY: split into "this iteration" (Iteration=CURRENT) and "other" (else). Display "this iteration" prominently; collapse "other" and "no iteration" into one-line counts with a hint to run `/sprint status all`.

If `CURRENT_ITERATION_ID` is None (infinite sprint case): show all items flat, no iteration grouping.

Sort within each section by Priority (P0 first), then Size (smallest first).

### Step 3: Reconcile Done with closed issues

If `DONE_RECENT` is empty but (C) returned recently-closed issues, the "Item closed → Done" workflow is likely not enabled. Use (C) for the recent-done section and surface a one-line hint:

```
Hint: items closed on GitHub aren't moving to Status: Done on the board.
Enable the "Item closed → Done" workflow at:
https://github.com/<owner>/projects/<N>/workflows
```

### Step 4: Render dashboard

Use `<PROJECT_TITLE>` from Resolve Project Context. The Project URL prefix depends on `<OWNER_TYPE>`: use `https://github.com/orgs/<OWNER>/projects/<N>` if `Organization`, `https://github.com/users/<OWNER>/projects/<N>` if `User`.

```
=== Sprint Status ===
Project: <PROJECT_TITLE> (#<N>)   <PROJECT_URL>

CURRENT ITERATION: Sprint 3   (Apr 21 → May 5, 6 days remaining)

IN PROGRESS
  #42  Feed freeze fix          @nirmal    [bug, P0, M]
  #43  Search filter support    @alice     [feature, P1, L]

IN REVIEW
  #40  Setup CI pipeline        @nirmal    [feature, P1, S]   PR #12

READY
  #44  OAuth flow                          [feature, P1, M]
  #45  Refactor API layer                  [refactor, P2, L]

BACKLOG (needs refinement)
  #46  Performance improvements
  #47  Filed via UI by @alice

── Other iterations: 3 items in Sprint 4 (use `/sprint status all` to see)
── No iteration: 5 items (use `/sprint status all` to see)

RECENTLY DONE
  #38  Setup auth middleware    closed 2d ago
  #39  Database schema          closed 1d ago

OPEN PRs
  #12  feat/40-ci-pipeline      @nirmal

DECISIONS (.dev/decisions/)
  D-001  Use Supabase for auth
  D-002  Monorepo structure
  D-003  JSON file persistence
```

If any section is empty, show "(none)" rather than omitting it.

If `<USER REQUEST>` was `status all`, do not collapse "other iterations" or "no iteration" — render them as full sub-sections.

If no current iteration exists, drop the "CURRENT ITERATION" line and render Ready/InProgress/InReview as flat sections without sub-grouping.

---

## Refine Command

**Purpose**: Take a Project item that's currently in Backlog (or has no Status set) and add the missing structure — acceptance criteria, implementation phases, risks — plus set Priority and Size, then move it to `Status: Ready`.

Arguments after `refine` are optional:
- `/sprint refine 46` — refine issue #46 directly
- `/sprint refine` — list items needing refinement and let the developer choose

### Step 0: Resolve Project context

Run [Resolve Project Context](#resolve-project-context).

### Step 1: Select item

If no issue number provided, fetch Project items at `Status=Backlog` or `Status=unset`:

```
gh project item-list <PROJECT_NUMBER> --owner <PROJECT_OWNER> --format json --limit 200
```

Filter to `Status in {Backlog, unset}` and present the list. Ask which one to refine.

If an issue number is provided directly, look it up in the item list.

### Step 2: Add to Project if missing

If the issue is **not on the Project board** (auto-add not enabled, manually-filed issue, etc.):

```
gh project item-add <PROJECT_NUMBER> --owner <PROJECT_OWNER> --url <ISSUE_URL> --format json
```

Capture `ITEM_ID` from `.id`. Continue refining as if it had been on the board all along.

### Step 3: Read the issue + current field values

```
gh issue view N --json body,title,labels,comments
```

From the Project item: read current Priority, Size, Status, Iteration values (may be unset).

Display the current state to the developer: title, body, current field values, type label.

### Step 4: Already-Ready warning

If the item's Status is already `Ready`: proceed silently (the user explicitly asked to refine; let them update).

If the item's Status is `In Progress` or `In Review`: warn: "This item is in flight; changing acceptance criteria mid-flight is risky. Continue? [y/N]". If no, stop.

### Step 5: Interactive refinement

Walk the developer through what's missing using the [Grill Me Protocol](#grill-me-protocol) — one question per turn, adapt to the answer, never present A–I as a single form to fill in. The dimensions to backfill, in roughly this order, skipping anything already populated:

A. **User Story** — if absent, ask and add.
B. **Acceptance Criteria** — articulate WHEN/THEN/SHALL: happy path, edge cases, errors, persistence, UI.
C. **Implementation Phases** — propose 2–4 ordered, independently testable phases. Discuss until right.
D. **Risk Assessment** — technical risks, dependencies, unknowns.
E. **Notes** — capture context.
F. **Type label** — if missing, ask: feature / bug / refactor. `gh issue edit N --add-label "type:<x>"`.
G. **Priority** — show current value (or "unset") and ask: "Keep / change to P0 / P1 / P2?"
H. **Size** — show current value and ask: "Keep / change to XS / S / M / L / XL?"
I. **Parent linkage** — read current parent via:

   ```
   gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!){
     repository(owner:$owner,name:$repo){issue(number:$number){parent{number title}}}
   }' -f owner=<OWNER> -f repo=<REPO_NAME> -F number=<N> --jq '.data.repository.issue.parent'
   ```

   Show current value (parent issue number/title, or "standalone") and ask: "Keep / attach to existing # / create new parent / make standalone?"
   - If attaching: look up the parent's node ID, look up this issue's node ID, run the `addSubIssue` mutation from Plan Step 6D.
   - If detaching: run the equivalent `removeSubIssue` mutation.
   - **Default to grouping** consistent with `plan` — only choose "standalone" when the issue genuinely doesn't relate to other open work.

Always **show the current value and ask** — don't silently overwrite or silently keep.

### Step 6: Update the issue body

Construct the refined body using `<SKILL DIR>/templates/issue-body.md` as the scaffold, preserving any existing content that's still valid.

```
gh api repos/{REPO}/issues/N -f body="<updated body>"
```

### Step 7: Update Project fields

Set Priority and Size **only if the user changed them in Step 5G/H** (skip the field-edit call when the user chose "keep"):

```
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <PRIORITY_FIELD_ID> \
  --single-select-option-id <PRIORITY_OPTIONS["..."]>

gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <SIZE_FIELD_ID> \
  --single-select-option-id <SIZE_OPTIONS["..."]>
```

Move Status: Backlog → Ready (only if the item was Backlog/unset; preserve In Progress/In Review/Done if the user is editing fields on an in-flight item):

```
gh project item-edit \
  --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <STATUS_FIELD_ID> \
  --single-select-option-id <STATUS_OPTIONS["Ready"]>
```

### Step 8: Optional iteration assignment

Ask: "Assign to an iteration? (current / new / specific / none / skip)"
- `current` → set to `CURRENT_ITERATION_ID` if exists
- `new` → create iteration via `gh api graphql` (see [Plan Command](#plan-command), Step 3 lazy-creation)
- `specific` → list existing iterations, user picks
- `none` → clear iteration value
- `skip` → don't change current iteration value

### Step 9: Report

```
Refined #N:
  Title:     <title>
  Type:      <type>
  Priority:  P1
  Size:      M
  Status:    Ready  (was Backlog)
  Iteration: <name or 'none'>

Available to /sprint pick.
```

---

## Setup Command

**Purpose**: Bootstrap the sprint workflow for a repository: discover or create a GitHub Project, configure its fields per the Team Planning template, link the repo, and persist the Project number to `.dev/sprint-config.json`. This command is **idempotent** — running it again is safe and re-applies any missing config.

### Step 1: Verify prerequisites

Run these checks in parallel:

1. `gh auth status` — fail message: "GitHub CLI is not authenticated. Run `gh auth login`."
2. `git rev-parse --is-inside-work-tree` — fail: "Not inside a git repository."
3. `REPO = gh repo view --json nameWithOwner -q .nameWithOwner` — fail: "No GitHub remote found."

Set `OWNER = REPO.split('/')[0]` and `REPO_NAME = REPO.split('/')[1]`.

### Step 2: Read existing config (if any)

If `.dev/sprint-config.json` exists, parse it. If it points to a `project_number`, verify the Project still exists:

```
gh project view <project_number> --owner <project_owner> --format json
```

If the Project exists, skip Steps 3–5 (already discovered, linked, persisted) and continue from Step 6 (ensure fields + workflows + labels + dirs).

If the Project no longer exists, warn the user and continue from Step 3 to re-discover/create.

### Step 3: Discover or create Project

```
gh project list --owner <OWNER> --format json
```

**If one or more Projects exist**, present the list:

```
Projects in <OWNER>:
  1. <title>  (#<num>)  <N items>  linked repos: <list>
  2. <title>  (#<num>)  ...
  N+1. Create new Project named '<REPO_NAME>'
```

Ask the user to pick one.

**If no Projects exist** (or user picks "create new"), create one:

```
gh project create --owner <OWNER> --title "<REPO_NAME>" --format json
```

Capture `PROJECT_NUMBER` from the response. Tell the user the Project can be renamed later in the GitHub UI without breaking anything (the skill resolves by number, not name).

If the user does not have permission to create Projects in the org, surface the error: "You don't have permission to create a Project in `<OWNER>`. Ask an org admin to create a Project (any name) and link this repo to it, then re-run `/sprint setup`."

### Step 4: Link the repo to the Project

```
gh project link <PROJECT_NUMBER> --owner <OWNER> --repo <REPO>
```

Idempotent — silent success if already linked.

### Step 5: Persist config

```
mkdir -p .dev
```

Write `.dev/sprint-config.json`:

```json
{
  "project_number": <PROJECT_NUMBER>,
  "project_owner": "<OWNER>"
}
```

**Tell the user to commit this file** so all teammates resolve to the same Project — without it, each developer's `/sprint setup` will create a divergent local config. It is shared team state, not per-user config.

### Step 6: Ensure Project fields exist (idempotent)

Fetch current fields:

```
gh project field-list <PROJECT_NUMBER> --owner <OWNER> --format json
```

Fields used by the skill, drawn from the GitHub Team Planning template. Setup creates these three; Iteration is created later, on-demand:

| Field | Type | Options | Created at |
|---|---|---|---|
| Status | Single-select | Backlog, Ready, In Progress, In Review, Done | `setup` |
| Priority | Single-select | P0, P1, P2 | `setup` |
| Size | Single-select | XS, S, M, L, XL | `setup` |

The Iteration field is created lazily by `/sprint plan` or `/sprint refine` when the first sprint is named. Do NOT create it at setup — many users never use sprints.

For each missing field, create it:

```
gh project field-create <PROJECT_NUMBER> --owner <OWNER> \
  --name "Status" \
  --data-type "SINGLE_SELECT" \
  --single-select-options "Backlog,Ready,In Progress,In Review,Done"
```

If a field exists but is missing required options, modify it via `gh api graphql` (`gh project field-edit` does not exist in current gh versions).

**Modifying the auto-created Status field**: GitHub creates a Status field on every new Project with default options `Todo / In Progress / Done`. This field is built-in and **cannot be deleted** — `gh project field-delete` returns `Only custom fields can be deleted`. Replace its options via the `updateProjectV2Field` mutation:

```
gh api graphql -f query='
mutation($fieldId: ID!) {
  updateProjectV2Field(input: {
    fieldId: $fieldId
    singleSelectOptions: [
      {name: "Backlog",     color: GRAY,   description: "Not yet refined"}
      {name: "Ready",       color: GREEN,  description: "Refined and implementable"}
      {name: "In Progress", color: YELLOW, description: "Currently being worked on"}
      {name: "In Review",   color: PURPLE, description: "PR open"}
      {name: "Done",        color: BLUE,   description: "Completed"}
    ]
  }) {
    projectV2Field {
      ... on ProjectV2SingleSelectField { id name options { id name } }
    }
  }
}' -f fieldId="<STATUS_FIELD_ID>"
```

This mutation **replaces** the entire option list (it does not merge). On a freshly created Project with zero items, this is safe — Todo simply goes away. On an existing Project where teammates have items at `Todo` or other custom options, **include those extras in the replacement list** to preserve them and the items they're assigned to.

Do not delete or rename existing extra options — teams may have customized.

### Step 7: Surface workflow toggles to the user

GitHub Projects v2 has built-in workflow automations that the skill cannot enable via API (UI-only configuration). Detect owner type to construct the right URL:

```
OWNER_TYPE = gh api graphql -f query='query($login:String!){repositoryOwner(login:$login){__typename}}' \
               -f login=<OWNER> --jq '.data.repositoryOwner.__typename'
PROJECT_URL_PREFIX = "https://github.com/orgs/<OWNER>" if OWNER_TYPE=="Organization" else "https://github.com/users/<OWNER>"
```

Tell the user:

```
One-time workflow setup:
Open <PROJECT_URL_PREFIX>/projects/<PROJECT_NUMBER>/workflows
and enable these workflows (click each toggle):

  ✓ Auto-add to project
       (which repos? add: <REPO>)
  ✓ Item closed
       (set Status: Done)
  ✓ Pull request merged
       (set Status: Done)
  ✓ Pull request opened
       (set Status: In Review)

The skill drives Status transitions for actions it takes (pick, PR creation),
so it works even if these workflows are off — but enabling them keeps the
board in sync with actions taken outside the skill (UI, bots, other tools).
```

### Step 8: Ensure type/package labels in the repo

Check whether the canonical sprint labels exist. Use exact-name matching, not substring search:

```
gh api repos/<REPO>/labels --paginate --jq '.[] | .name' | grep -Fx 'type:feature'
```

If `type:feature` is not found, read `<SKILL DIR>/setup/labels.json` and create each label:

```
gh label create "<name>" --color "<color>" --description "<description>" --force
```

(`--force` makes this idempotent.)

### Step 9: Ensure decisions directory

```
mkdir -p .dev/decisions
```

### Step 10: Report

Use the actual `<PROJECT_TITLE>` (from `gh project view` in Step 2 or 3) and `<PROJECT_URL_PREFIX>` (from Step 7) — not `<REPO_NAME>`, since the user may have linked an existing differently-named Project.

```
Setup complete:
  Project: <PROJECT_TITLE> at <PROJECT_URL_PREFIX>/projects/<PROJECT_NUMBER>
  Fields: Status, Priority, Size  (Iteration created lazily on first sprint use)
  Workflows: please enable manually at the URL above (one-time setup)
  Labels: <created list, or "all already existed">
  Config saved: .dev/sprint-config.json  (commit this — shared team state)
  Decisions dir: .dev/decisions/

Next: /sprint plan to add work, /sprint status for the dashboard.
```

---

## Upgrade Command

**Purpose**: Pull the latest version of the sprint skill from its git origin. The skill itself is a git checkout at `<SKILL DIR>`; this command runs `git fetch` + `git pull --ff-only` against it. Optionally switches to a specific branch for testing pre-merge changes.

### Invocation forms

- `/sprint upgrade` — pull whatever branch the skill repo is currently on
- `/sprint upgrade <branch>` — switch to `<branch>` (creating local tracking branch from `origin/<branch>` if needed) and pull. The skill stays on this branch for future plain `/sprint upgrade` calls until you run `/sprint upgrade reset`.
- `/sprint upgrade reset` — switch back to the repo's default branch (`master` or `main`, auto-detected) and pull.
- `/sprint upgrade check` — dry-run. Fetches and reports what would change, but does not switch or pull.

### Step 1: Validate skill directory

Verify `<SKILL DIR>` is a git checkout of the sprint skill:

```
git -C <SKILL DIR> rev-parse --is-inside-work-tree
```

If this fails: "Skill at `<SKILL DIR>` is not a git checkout — was it copied manually or installed via a package manager? Re-clone with: `git clone <repo-url> <SKILL DIR>`." Stop.

Verify `<SKILL DIR>/SKILL.md` exists:

If not: "Skill at `<SKILL DIR>` doesn't contain SKILL.md. Aborting upgrade." Stop.

### Step 2: Detect default branch

```
DEFAULT_BRANCH = git -C <SKILL DIR> symbolic-ref refs/remotes/origin/HEAD --short \
                   | sed 's|^origin/||'
```

If detection fails (no `origin/HEAD` ref), fall back to `master`.

### Step 3: Parse argument

Read the first word of `<USER REQUEST>` after `upgrade`:

| Arg | MODE | TARGET_BRANCH |
|---|---|---|
| (none) | `pull` | current branch |
| `reset` | `switch+pull` | `DEFAULT_BRANCH` |
| `check` | `dry-run` | current branch |
| anything else | `switch+pull` | the argument |

### Step 4: Capture current state

```
BEFORE_COMMIT = git -C <SKILL DIR> rev-parse HEAD
BEFORE_BRANCH = git -C <SKILL DIR> rev-parse --abbrev-ref HEAD
```

If `BEFORE_BRANCH` is `HEAD` (detached): "Skill repo is in detached HEAD state. Run `/sprint upgrade reset` to return to `<DEFAULT_BRANCH>`." Stop.

### Step 5: Refuse on local modifications

```
git -C <SKILL DIR> status --porcelain
```

If non-empty: "Skill directory has uncommitted local changes:\n<short status>\nRefusing to upgrade. Either commit, stash, or discard them, then re-run."  Stop.

### Step 6: Fetch

```
git -C <SKILL DIR> fetch origin --prune
```

### Step 7: Branch switch (if MODE is `switch+pull` and TARGET_BRANCH ≠ BEFORE_BRANCH)

Verify target branch exists on origin:

```
git -C <SKILL DIR> rev-parse --verify origin/<TARGET_BRANCH>
```

If not: "Branch `<TARGET_BRANCH>` does not exist on origin. Available branches: `<git branch -r | head -10>`. Run `/sprint upgrade reset` to return to `<DEFAULT_BRANCH>`." Stop.

Refuse if currently ahead of upstream on the branch we're leaving:

```
AHEAD_ON_LEAVING = git -C <SKILL DIR> rev-list --count origin/<BEFORE_BRANCH>..HEAD
```

If `AHEAD_ON_LEAVING > 0`: "Current branch `<BEFORE_BRANCH>` is `<N>` commits ahead of origin — refusing to switch and lose your work. Push or reset first." Stop.

Switch:

```
git -C <SKILL DIR> switch <TARGET_BRANCH>
```

(Modern `git switch` auto-creates a local tracking branch from `origin/<TARGET_BRANCH>` when needed.)

Inform the user: "Switched skill to branch `<TARGET_BRANCH>`. Future `/sprint upgrade` calls will track this branch until you run `/sprint upgrade reset`."

### Step 8: Check for divergence on target branch

```
AHEAD  = git -C <SKILL DIR> rev-list --count origin/<TARGET_BRANCH>..HEAD
BEHIND = git -C <SKILL DIR> rev-list --count HEAD..origin/<TARGET_BRANCH>
```

If `BEHIND == 0` and we did not just switch:
- MODE is `dry-run`: "Already up to date on `<TARGET_BRANCH>`." Stop.
- MODE is `pull`: "Already up to date on `<TARGET_BRANCH>`." Stop.

If `AHEAD > 0`: "Local branch `<TARGET_BRANCH>` is `<N>` commits ahead of origin — refusing fast-forward pull. Push or reset, then re-run." Stop.

If MODE is `dry-run`: report the would-be changes (next step's preview) and stop without pulling.

### Step 9: Pull (fast-forward only)

```
git -C <SKILL DIR> pull --ff-only origin <TARGET_BRANCH>
AFTER_COMMIT = git -C <SKILL DIR> rev-parse HEAD
```

### Step 10: Report

```
CHANGED_FILES  = git -C <SKILL DIR> diff --name-only <BEFORE_COMMIT> <AFTER_COMMIT>
RECENT_COMMITS = git -C <SKILL DIR> log --oneline <BEFORE_COMMIT>..<AFTER_COMMIT>
```

Display:

```
Upgraded sprint skill on '<TARGET_BRANCH>':
  <BEFORE_COMMIT[0:7]> → <AFTER_COMMIT[0:7]>  (<BEHIND> new commits)

Recent changes:
  <oneline list>

Files updated:
  <list>

[If TARGET_BRANCH != DEFAULT_BRANCH:]
Currently tracking non-default branch — run `/sprint upgrade reset` to return to `<DEFAULT_BRANCH>`.

Changes take effect on next /sprint invocation
(the currently-running command is still the previous version).
```

For MODE `dry-run`, replace "Upgraded" with "Would upgrade" and skip the "Files updated" section (just show the oneline log).

---

## Help Command

**Purpose**: Print a short reference of all sprint commands and their subcommands. Takes no arguments; any text after `help` is ignored.

Print verbatim:

```
/sprint commands

  plan [description]              Create structured requirements (Issues + Project items).
                                  Optional free-form description; otherwise interactive.

  pick [N]                        Claim a Ready item and implement it phase by phase.
                                  N = issue number; if omitted, lists Ready items.

  refine [N]                      Groom a Backlog item into Ready: add acceptance criteria,
                                  phases, risks, Priority, Size.
                                  N = issue number; if omitted, lists Backlog.

  status [all]                    Dashboard read from the Project board.
                                  all = include other iterations and unscheduled items.

  decide ["title"]                Record an architectural decision in .dev/decisions/.
                                  Optional quoted title; otherwise interactive.

  setup                           Discover/create the Project, configure fields, link the repo.
                                  Idempotent — safe to re-run.

  upgrade [<branch> | reset | check]
                                  Pull the latest skill from origin.
                                    (none)   pull whatever branch the skill is on
                                    <name>   switch to a branch and pull (sticky until reset)
                                    reset    return to default branch and pull
                                    check    dry-run — show what would change

  help                            Show this help.

Examples:
  /sprint plan
  /sprint pick 42
  /sprint status all
  /sprint decide "Use PostgreSQL for event store"
  /sprint upgrade feat/some-branch
```

---

## Dependency Safety Check

**Purpose**: Before any sprint task adds or upgrades a third-party dependency, verify that the target version is not freshly published (supply-chain compromise window) and not subject to a known high/critical advisory. If unsafe, automatically redirect to the closest clean version.

This check is invoked from the [Pick Command](#pick-command) per-phase loop. It runs **before** any manifest edit (`package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, etc.) and **before** any install/add command (`npm install`, `pnpm add`, `yarn add`, `pip install`, `cargo add`, `go get`, `mvn ... -Dversion=`, etc.).

### Triggers

Run the check when a phase implementation will:

- Add a new dependency entry.
- Update an existing dependency to a different version (including lockfile-only bumps that change the resolved version of a top-level dep).
- Replace one package with another.

A pure lockfile regeneration that resolves to the **same** versions does not trigger the check.

### Supported ecosystems

Fully supported in v1: **npm**, **PyPI**, **crates.io**, **Go modules**, **Maven Central**.

If a manifest belongs to any other ecosystem (CocoaPods, Hex, NuGet, RubyGems, Composer, etc.), **hard-block** with the message: `Dependency safety check: ecosystem not supported. Override required to proceed.`

### Caching

Maintain an in-memory cache for the duration of the pick, keyed on `ecosystem:package:version`. Each entry stores the full check result: publish date, advisory list, install-script flags, and final verdict (pass / blocked-with-reason / accepted-fallback-target).

- Steps 1, 2, and 4 (and the per-candidate re-checks inside Step 5's fallback walk) MUST consult the cache before making a network call. A hit returns the stored result without re-querying the registry or OSV.
- The verification log (Step 7) reads from the same cache, so the PR body reflects exactly what was checked.
- The cache lives only for the current pick — a fresh pick (or a new Claude session) starts empty. Do not persist it to disk.
- Typosquat (Step 3) does not need the cache; it operates on the package name alone.

### Step 1: Resolve publish date (7-day age guard)

For the target `package@version`, look up the publish timestamp. If the publish date is **less than 7 days ago** from today, the version is blocked. Per-ecosystem recipes:

- **npm**:
  ```
  npm view <pkg>@<version> time --json
  ```
  Use the entry keyed by the exact version string. (Falls back to `https://registry.npmjs.org/<pkg>` JSON, field `time.<version>`.)

- **PyPI**:
  ```
  curl -s https://pypi.org/pypi/<pkg>/<version>/json
  ```
  Use `urls[0].upload_time_iso_8601` (or earliest of the `urls` array).

- **crates.io**:
  ```
  curl -s https://crates.io/api/v1/crates/<pkg>/<version>
  ```
  Use `version.created_at`.

- **Go modules**:
  ```
  curl -s https://proxy.golang.org/<module>/@v/<version>.info
  ```
  Use the `Time` field. List versions via `https://proxy.golang.org/<module>/@v/list`.

- **Maven Central**:
  ```
  curl -s "https://search.maven.org/solrsearch/select?q=g:<group>+AND+a:<artifact>+AND+v:<version>&core=gav&rows=1&wt=json"
  ```
  Use `response.docs[0].timestamp` (epoch ms).

If the lookup fails (network error, 404, malformed response), **fail closed** — hard-block with a remediation message naming the registry and command that failed.

### Step 2: Advisory scan

Query OSV.dev as the unified backend for advisories:

```
curl -s -X POST https://api.osv.dev/v1/query -H 'Content-Type: application/json' \
  -d '{"package":{"name":"<pkg>","ecosystem":"<ECOSYSTEM>"},"version":"<version>"}'
```

Ecosystem strings: `npm`, `PyPI`, `crates.io`, `Go`, `Maven`.

If the response includes any vulnerability with a `database_specific.severity` or CVSS score in the **HIGH** or **CRITICAL** range (or, when severity is missing, any vulnerability at all that affects this exact version), the version is blocked. Capture each vulnerability's `id`, `summary`, and reference URL for the report.

If the OSV call fails, **fail closed**.

### Step 3: Typosquat heuristic

For new dependencies (not version bumps of an existing package), compute the Levenshtein distance between the requested package name and a list of popular packages on the same ecosystem. If distance ≤ 2 from a popular name **and** the requested name is not itself a popular name, hard-block with: `Possible typosquat: '<requested>' is distance N from popular package '<popular>'. Override required.`

The popular-package seed list is a small static set per ecosystem (e.g., for npm: `react`, `lodash`, `express`, `axios`, `chalk`, `commander`, `moment`, `request`, `webpack`, `typescript`, `eslint`, `jest`, `vue`, `next`, `dotenv`). Treat the seed as illustrative — extend as needed when false positives or misses appear.

### Step 4: Install-script check

If the package declares install-time scripts, hard-block:

- **npm**: `npm view <pkg>@<version> scripts --json` — block if any of `preinstall`, `install`, `postinstall` is set.
- **PyPI**: block if the distribution includes a `setup.py` (sdist with executable setup, as opposed to a wheel-only release). Detect via the PyPI JSON `urls` array — if no entry has `packagetype == "bdist_wheel"`, treat as install-script risk.
- **crates.io**: block if the crate declares a `build.rs` (check via the published crate metadata; if unverifiable, note as unknown and require override).
- **Go modules**: no install scripts in the module system; skip.
- **Maven Central**: skip; build plugins are scoped to the consuming project, not install-time.

Override requires explicit justification recorded in the PR + issue comment.

### Step 5: Clean-version fallback

If Step 1, 2, 3, or 4 blocks the requested version, automatically search for a clean adjacent version:

1. **Prefer fixed-in versions** (advisory-block only): If the OSV response includes `affected[].ranges` with `fixed` versions, walk them in ascending order. For each candidate, run Step 1 and Step 2 again. Return the **lowest** fixed-in version that passes both (i.e., is ≥ 7 days old and free of high/critical advisories).
2. **Fall back to highest prior unaffected version**: If no fixed-in version passes (or none was listed), walk the registry's version list in **descending** order from the version immediately below the requested one. For each, run Step 1 and Step 2. Return the first version that passes both.
3. **No clean version found**: If neither direction yields a passing candidate, hard-block and report the search trace (versions tried + reason each was rejected) so the developer can pick a different package.

When a fallback is found, propose it to the developer with the reason, e.g.:

```
v2.3.4 is affected by GHSA-xxxx-yyyy (HIGH).
Suggest v2.3.5 — fixed-in, published 14 days ago, no advisories.
```

The developer must confirm the substitution before the manifest is edited.

### Step 6: Override flow

A hard-block can be overridden, but only with explicit justification:

1. The assistant explains exactly why the version was blocked.
2. The developer types an override justification (free text, must be non-empty).
3. The justification is recorded in **both** the PR body's "Dependency Safety" section and a comment on the issue:
   ```
   gh issue comment N --body "Dependency safety override: <pkg>@<version> — <justification>"
   ```
4. The phase proceeds.

### Step 7: Record verification

On success (clean pass or accepted fallback), append a row to an in-memory verification log for this branch. At PR time, the log is rendered into the PR body's "Dependency Safety" section (see [Step 8 of Pick Command](#step-8-push-and-create-pr)). Each row captures:

- `package@version` (final, after any fallback)
- Originally requested version (if different)
- Publish date
- Advisories checked (IDs or "none")
- Fallback reason (if applicable)
- Override justification (if applicable)

---

## Error Handling

Apply these rules across all commands:

- **Missing `.dev/sprint-config.json`**: Tell the user to run `/sprint setup` first. Don't try to auto-discover or auto-create — setup is explicit.
- **Project deleted or moved**: If the configured Project no longer exists, surface clearly and tell the user to re-run `/sprint setup`.
- **Network errors from `gh`**: Report the error clearly and suggest the developer check their internet connection and `gh auth status`.
- **Permission errors**: Report that the user may not have write access to the repository or to the Project (Project creation in some orgs is admin-only).
- **Empty results**: Never show raw empty output. Always say "No items found matching criteria" or similar.
- **Malformed issue body**: When reading an issue body that doesn't follow the template structure (e.g., created manually on GitHub without the template), work with what's available. Don't fail — adapt. If refining, add the structure that's missing.
- **Rate limiting**: If `gh api` returns a rate limit error, tell the developer and suggest waiting.
- **gh CLI feature gaps**: If a `gh project` subcommand doesn't support an operation (e.g., adding iterations to an iteration field), fall back to `gh api graphql` with the appropriate mutation. If even that fails, surface the failure clearly with the command that was attempted — never silently skip.

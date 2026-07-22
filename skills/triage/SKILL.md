---
name: triage
description: >
  End-to-end triage and fix loop for a GitHub backlog of issues, sourced from either an
  epic (umbrella issue with native sub-issues) or a GitHub Projects v2 board. Triages the
  open issues, auto-closes duplicates and won't-fixes, surfaces big-ticket items for the
  user, bundles all trivial dep bumps into one PR per ecosystem, ships them. Repo-specific
  behavior comes from `.dev/triage.json` in the current repo. Use when the user says
  "triage", "/triage", "let's clear epic #N", "triage the security project", "triage project
  #N", or any variation of working through the open issues of an epic or a Project board.
allowed-tools: Bash(gh *) Bash(git *) Bash(jq *) Bash(yarn *) Bash(npm *) Bash(pnpm *) Bash(xcodebuild *) Bash(ls *) Bash(cat *) Bash(find *) Bash(rg *) Bash(grep *) Bash(mkdir *) Read Write Edit Glob Grep Agent Skill
argument-hint: "[--epic <N> | --project <N>] [--dry-run]"
effort: high
---

# triage — Generic Epic / Project Triage & Fix Loop

End-to-end workflow for working through the open issues of a long-lived GitHub backlog. The backlog can be **either**:

- an **epic** — an umbrella issue whose open **direct sub-issues** (native sub-issue links) form the work set, or
- a **project** — a **GitHub Projects v2** board whose open **issue items** form the work set.

The skill is **generic over repo, epic, and project**; project-specific behavior is loaded from `.dev/triage.json` in the current repo. Everything downstream of enumeration — classification, cleanup, dep-bump bundling, PRs — is identical for both sources; only **how the work set is gathered** differs.

Phases run top-to-bottom, autonomously. **Two points pause and wait for you:** Phase 1 step 2 (direction on any pre-existing `triage/*` PRs) and Phase 3 (directing `needs-you` items). Phases 4–5 never stop for commit / push / PR / merge / branch-delete approval. Everything else that needs your judgment is **surfaced without halting** and collected into the Phase 6 `⚡ DECIDE` block — a Phase-4 `[REAL]`-dropped bump, a non-mergeable PR left open. (A Phase-1 `[REAL]` is folded into the Phase 3 pause via a `needs-you` reclassification, not deferred to Phase 6.) See the [Output & escalation contract](#output--escalation-contract).

## The `source` concept

Throughout this skill, two placeholders stand for the resolved source. Compute them once in Phase 1 and reuse them everywhere:

- **`{sourceRef}`** — human-readable reference used in prose, PR bodies, and summaries:
  - epic → `#{epic}` (e.g. `#451`)
  - project → `project #{projectNumber} ("{projectTitle}")`
- **`{sourceSlug}`** — branch-safe identifier used in branch names:
  - epic → `epic-{epic}` (e.g. `epic-451`)
  - project → `project-{projectNumber}` (e.g. `project-5`)

## Invocation

`/leverj:triage` with no arguments reads `.dev/triage.json` from the current repo and uses the `source` configured there. Optional flags:

- `--epic <N>` — run against epic `N` this once. Forces `source = epic` regardless of config.
- `--project <N>` — run against Projects v2 board number `N` this once. Forces `source = project` regardless of config. The project owner is taken from config `project.owner` if present, otherwise defaults to the `owner` parsed from `git remote get-url origin`.
- `--dry-run` — read-only mode. **All write operations are replaced with "would do" prints:** Phase 2 prints what it would close but issues no `gh issue close`; Phase 3 prints what new follow-up issues it would file but issues no `gh issue create` / `addSubIssue` / `project item-add`; Phase 4 prints the bump plan but does no branch creation, commit, push; Phase 5 is skipped entirely. Devil's-advocate verifiers still run (they are read-only). Use this to preview a run end-to-end before letting it act.

`--epic` and `--project` are **mutually exclusive** — passing both is an error; exit and tell the user to pick one.

The owning `owner/repo` for fix PRs is inferred from `git remote get-url origin` (parsed for `owner/repo`). If the cwd is not a git repo with a GitHub origin, the skill exits with a clear error.

## Config schema (`.dev/triage.json`)

The `source` field selects which block is required. Everything below `baseBranch` is source-independent.

**Epic source:**

```json
{
  "source": "epic",
  "epic": 451,
  "baseBranch": "dev",
  "preCommitGate": "pre-commit-reviewer",
  "duplicateRule": "same-advisory-id-only",
  "assignFollowUpsTo": "@me",
  "ecosystems": {
    "js": {
      "manifestGlob": "**/package.json",
      "lockfile": "yarn.lock",
      "updateCommand": "yarn up {dep}@{version}",
      "testCommand": "yarn workspaces foreach -A run test",
      "separatePR": true,
      "alwaysRunSecurityReview": true
    },
    "ios-native": {
      "manifestGlob": "ios-native/**/Package.resolved",
      "updateMechanism": "spm-resolve",
      "testCommand": "xcodebuild test -scheme EzelApp",
      "separatePR": true,
      "lintCommand": "yarn ios-native:format",
      "alwaysRunSecurityReview": true
    }
  }
}
```

**Project source** (only the source block differs — replace `epic` with `project`):

```json
{
  "source": "project",
  "project": { "number": 5, "owner": "leverj" },
  "baseBranch": "dev",
  "preCommitGate": "pre-commit-reviewer",
  "duplicateRule": "same-advisory-id-only",
  "assignFollowUpsTo": "@me",
  "ecosystems": { "js": { "...": "..." } }
}
```

> **Note on `manifestGlob` in monorepos:** for Yarn/PNPM workspaces, use `**/package.json` not `package.json`, or detection will miss workspace packages.

> **Note on `updateCommand` template substitution:** `{dep}` and `{version}` are substituted as shell-quoted literals. Scoped names (`@scope/name`) and version ranges with metacharacters (`^1.2.3`, `>=2.0.0`) are quoted automatically. The skill never interpolates raw — if a value can't be safely quoted, the bump is dropped and reported.

> **Note on `assignFollowUpsTo`:** accepts a GitHub username, `"@me"` (resolves to whoever runs the skill via `gh api user --jq .login`), or `null` (leave unassigned).

> **Note on `project.owner`:** the Projects v2 owner login (org or user). Omit to default to the repo owner parsed from the git remote. A Project can belong to an org while its issues live in a repo under that org — these are usually the same login but need not be.

## Config validation (Phase 0)

Before Phase 1, validate the loaded config:

- `source` is one of `"epic"`, `"project"`. (A `--epic`/`--project` flag overrides this for the run; validate the **resolved** source.)
- If source is `epic`: `epic` is a positive integer.
- If source is `project`: `project.number` is a positive integer; `project.owner` is a non-empty string (or absent → defaulted to the repo owner).
- `baseBranch` is a non-empty string.
- `ecosystems` is an object with at least one key.
- For each ecosystem: `manifestGlob`, `testCommand` are required strings; `updateCommand` OR `updateMechanism` is required; `manifestGlob` matches at least one file in the repo (else the ecosystem is "configured but absent" — print a warning and skip Phase 4 for it).
- `duplicateRule` is one of the documented values.

On any validation failure, exit with a message naming the field, the actual value, and the expected shape. Do not proceed.

**Field reference:**

- `source` (string, required) — `"epic"` or `"project"`. Selects how the work set is enumerated in Phase 1.
- `epic` (number, required when `source == "epic"`) — umbrella issue number whose open sub-issues will be triaged.
- `project` (object, required when `source == "project"`) — `{ "number": <int>, "owner": <string?> }`. The Projects v2 board number and owner login whose open issue items will be triaged.
- `baseBranch` (string, default `"main"`) — branch to base fix PRs off of.
- `preCommitGate` (string | null) — name of a `pre-commit-reviewer` style agent in the repo's `.claude/agents/` that runs the project's full pre-commit gate. If null, the skill falls back to invoking the `security-review` / `perf-review` / `simplify` skills individually. The skill ALWAYS runs the secrets scan regardless.
- `duplicateRule` (string, default `"same-advisory-id-only"`) — `"same-advisory-id-only"` auto-closes only issues with the exact same CVE/GHSA ID; `"same-root-dep-flag"` additionally flags same-root-dep clusters as merge candidates but never auto-closes them.
- `assignFollowUpsTo` (string | null) — GitHub username to assign to any new follow-up issues the skill files in Phase 3. Null means leave unassigned.
- `ecosystems` (object, required, non-empty) — per-ecosystem behavior. Each key is an ecosystem id (`js`, `ios-native`, `gradle`, etc.); each value has:
  - `manifestGlob` (string) — glob used to detect the ecosystem's presence in the repo.
  - `lockfile` (string, optional) — path to the lockfile, if a single one applies.
  - `updateCommand` (string) — template; `{dep}` and `{version}` are substituted per bump.
  - `updateMechanism` (string, optional) — for non-shell flows like `"spm-resolve"`.
  - `testCommand` (string) — command run after all bumps in this ecosystem; must exit 0.
  - `separatePR` (bool, default `false`) — if true, this ecosystem's bumps go in their own PR; if false, all `separatePR: false` ecosystems share one PR.
  - `lintCommand` (string, optional) — extra format/lint command to run before commit.
  - `alwaysRunSecurityReview` (bool, default `true`) — **even if the diff is lockfile-only**, run the `security-review` skill on it. Dep bumps ARE the supply-chain attack surface (typo-squats, postinstall scripts, transitive risk). Override at your own peril.

If `.dev/triage.json` is missing or malformed, exit with a clear error pointing the user to the schema above.

## Standing rules the skill assumes (not config-driven)

- **Never push to the base branch directly.** All code goes through a PR.
- **Never `--no-verify` or `--force`.**
- **Never modify the source itself** — the epic issue and the Project board are permanent; the skill only operates on the open issues in the work set.
- **Commit subject only**, format `fix(deps): <short>` — no body unless one short product-level WHY sentence is genuinely needed. No email, no Co-Authored-By trailer, no Claude footer.
- **The 5-check pre-commit gate is mandatory** before any commit (the `preCommitGate` agent if configured; otherwise run the checks individually).

## Output & escalation contract

This skill follows the same escalation and output discipline as the `sprint` skill — restated here self-contained, since triage runs independently.

**Escalation — two independent axes.** Don't conflate them:
- **Needs you?** → the output split: `⚡ DECIDE` (your call/action) vs `👀 SKIM` (already handled) vs `✓ DONE`.
- **Does the run stop to wait?** → only a couple of points *halt*; most "needs-you" items are **surfaced without halting** and collected into the Phase 6 `⚡ DECIDE` block for you to act on afterward.

**The only interactive pauses (run stops and waits):**
- **Phase 1 step 2** — direction on any pre-existing `triage/*` PRs (resume vs. leave).
- **Phase 3** — directing the `needs-you` items (the sprint **Tier-B** equivalent: breaking changes, ambiguous product intent, cross-repo fixes). Never auto-actioned.

**`⚡ DECIDE` items surfaced *without* halting** (the run continues; you act after, from the Phase 6 block):
- **A Phase-4 `[REAL]` finding** → the bump is **dropped** from the batch (never shipped on the verifier's doubt; safe bumps still ship) and reported for your call. *A Phase-1 `[REAL]` is different* — it **reclassifies the issue to `needs-you`**, so it's handled at the Phase 3 pause, not Phase 6.
- **A non-mergeable PR** at ship time (`BLOCKED` / CI-failed / `UNSTABLE` / `BEHIND`-after-retries / other) → left open and reported; you must act (merge, fix CI, get review). Never bypassed.

**Autonomous, no decision needed:**
- **Trivial dep bumps + dup/wontfix cleanup = decide and log** (the **Tier-L** equivalent) — acted on and recorded in the Phase 6 summary.
- Triage has **no "propose & proceed" (Tier-P) tier for issue/product decisions** — it never invents product / API / UX changes. When unsure, escalate; never guess on a human call.
- **Safe defaults reported in `👀 SKIM`** (not `⚡ DECIDE`): **dropping a bump whose tests fail** during isolation, and **stopping a group whose tests won't pass**. (Distinct from a `[REAL]`-dropped bump, which is `⚡ DECIDE`.)

**Output — DECIDE / SKIM / DONE.** The two interactive pauses above and the **final summary** (Phase 6) use this structure; intermediate progress recaps (Phase 1 triage table, Phase 2 cleanup recap) stay compact and are not reformatted. The blocks:

```
⚡ DECIDE — <items still needing your decision or action, or "nothing">
👀 SKIM  — <already-dispositioned; review at leisure — your Phase-3 deferrals, test-failure-dropped bumps, stopped groups, deferred findings, or "nothing">
✓ DONE   — <merged / closed counts, links; no action needed>
```

`⚡ DECIDE` is always first, even when empty (`⚡ DECIDE — nothing`). One line per item; link, don't inline. **A decision you already made (e.g. a Phase-3 "defer") is resolved — it belongs in `👀 SKIM`, not `⚡ DECIDE`.**

## Phase 1 — Triage (delegate heavy reads to a subagent)

Gather the **work set** — the open issues to triage — and classify them. Route the heavy reading through an `Explore` subagent so only the classification table comes back to the main context.

**Steps:**

1. **Resolve context.** Read `.dev/triage.json`. Parse `owner/repo` from `git remote get-url origin`. Apply `--epic` / `--project` override if present (these set the resolved `source`). Validate config fields. Compute `{sourceRef}` and `{sourceSlug}`.

2. **Pre-flight: existing open PRs.** Before doing anything else, list any open PRs whose branch matches `triage/{sourceSlug}/*`:
   ```bash
   gh pr list --repo {owner}/{repo} --state open --json number,headRefName,createdAt,author,commits \
     --jq '.[] | select(.headRefName | startswith("triage/{sourceSlug}/"))'
   ```
   If results are non-empty, surface them to the user with each PR's commit count and author list, and ask: *resume the existing PR (rebase + push more bumps), or abort this run, or close the existing PR and start fresh?*

   **Before honoring "close existing PR and start fresh":** check whether the PR contains commits authored by anyone other than the skill (i.e. a human pushed manual fixes). If so, surface the human-authored commits explicitly (commit SHAs + messages + author) and require a second explicit confirmation before closing. Closing the PR without `--delete-branch` is safer — the branch survives on the remote even if the PR is closed, so manual work isn't lost. Default to closing PR but **keeping** the branch unless the user explicitly says delete.

   Wait for direction before continuing.

3. **List the open issues in the work set.** This is the only step that branches on `source`:

   **Source = epic.** List open direct sub-issues of the epic. Sub-issues are a GitHub public-preview feature; the `subIssues` connection on `Issue` requires the `sub_issues` GraphQL preview header (verified against GitHub's preview docs at skill-authoring time; the header name has been stable through several preview iterations but is not yet GA). The exact invocation:
   ```bash
   gh api graphql \
     -H "GraphQL-Features: sub_issues" \
     -f query='
       query($owner:String!, $repo:String!, $number:Int!) {
         repository(owner:$owner, name:$repo) {
           issue(number: $number) {
             subIssues(first: 100) {
               nodes { number title state url body }
             }
           }
         }
       }' \
     -F owner={owner} -F repo={repo} -F number={epic} \
     | jq '.data.repository.issue.subIssues.nodes | map(select(.state == "OPEN"))'
   ```
   If the API rejects the field (GitHub changes the preview header in the future), surface the raw error to the user and stop — do not fall back to label-based heuristics.

   **Source = project.** List the open **Issue** items on the Projects v2 board. The `gh project item-list` CLI handles owner-type (org vs user) resolution and supports the Projects filter syntax, so `is:open is:issue` filters to open issues in one call:
   ```bash
   gh project item-list {projectNumber} --owner {projectOwner} --format json --limit 200 \
     --query "is:open is:issue" \
     | jq '[.items[] | {number: .content.number, title: .content.title, url: .content.url,
                        body: .content.body, repo: .content.repository, itemId: .id}]'
   ```
   Each item carries its own `content.repository` (`owner/repo`). **Cross-repo guard:** an issue whose `repo` is not the cwd `{owner}/{repo}` cannot be auto-fixed from here — classify it `needs-you` with reason `"lives in a different repo ({repo})"` so it surfaces in Phase 3 rather than being silently dropped. The project-item `id` (the `PVTI_…` node id) is captured as `itemId` for any later project-board operations.

   The project title for `{sourceRef}` comes from `gh project view {projectNumber} --owner {projectOwner} --format json --jq .title`.

   If `--limit 200` is reached (200 open issue items), the board is larger than one batch — **say so explicitly** in the triage report and process the first 200; do not pretend full coverage.

4. **Spawn an `Explore` subagent** with the open-issue list and these instructions:
   - For each issue: extract the CVE / GHSA / advisory ID(s) and affected dep + version range from the body.
   - Check current code state: is the dep still in any lockfile at the affected version? Use `git grep` / `rg` against the configured lockfile paths.
   - Read the upstream advisory / changelog for the recommended safe version when available.
   - Return a compact classification table (no per-issue prose), with one row per issue: `{number, advisory_id, dep, current_version, safe_version, ecosystem, proposed_class, reason}`.

5. **Classify** each issue into exactly one of:
   - **duplicate** — same advisory/CVE/GHSA ID as another open issue in the work set. (Same root dep with *different* advisory IDs is NOT a duplicate. If `duplicateRule == "same-root-dep-flag"`, also flag same-root-dep clusters as merge candidates but do not auto-close them.)
   - **wontfix** — false positive (CVE applies to a code path the project doesn't use), already-resolved (lockfile already on a version ≥ safe-version), or upstream-resolved with no action needed.
   - **trivial** — meets ALL of:
     - patch or minor bump only (no major)
     - changelog has no breaking-change section (and you can actually read the changelog confidently)
     - belongs to a configured ecosystem
     - lockfile-only changes always qualify, code-touching dep updates only qualify when no breaking behavior is documented
   - **needs-you** — major bump, ambiguous CVE applicability, dep replacement, deprecated dep with no drop-in, missing/unreadable changelog, a cross-repo project item, or anything that requires a judgment call.

6. **Devil's-advocate verifier on the classification.** Spawn a `general-purpose` Agent with the full classification table and this prompt:
   > "I classified each issue as duplicate / wontfix / trivial / needs-you. Argue the counter-case for each non-needs-you entry — what would make it wrong? Be specific. Distinguish between (a) real concerns where the classification is likely wrong, (b) speculative concerns where there's a remote risk but no concrete evidence, and (c) style concerns. Return your output as a list with each concern tagged [REAL] / [SPECULATIVE] / [STYLE]."

   Then, for each `[REAL]` concern, **reclassify the affected issue to `needs-you`** so you direct it in Phase 3 — do not halt Phase 1 mid-run. `[SPECULATIVE]` and `[STYLE]` go in the triage report but change nothing. This keeps the classification honest without the verifier stalling every invocation with low-confidence murmurs.

   **Tag-missing fallback:** if the verifier output contains no `[REAL]` / `[SPECULATIVE]` / `[STYLE]` tags at all (the verifier forgot the contract), treat every concern in its output as `[REAL]` and reclassify the affected issues to `needs-you`. Better to over-escalate to Phase 3 than to silently swallow a real concern that wasn't tagged.

7. **Present the triage** to the user as a compact block:
   ```
   Triage of N open issues of {sourceRef}:
     duplicate  (X)  #..., #...   → close, all reference #...
     wontfix    (X)  #..., #...   → <one-line reason class>
     trivial    (X)  #..., #...   (ecosystem breakdown: js=A, ios-native=B, ...)
     needs-you  (X)  #..., #...
   Verifier:
     [REAL]        <list, or "no concerns">
     [SPECULATIVE] <list, or "none">  (informational; not blocking)
   ```

## Phase 2 — Cleanup (auto-pilot, no user gate)

Close duplicates and won't-fix issues with a one-line reason. Closing the underlying issue is correct for both sources — a closed issue drops out of the epic's sub-issue progress and shows as Done/closed on the Project board automatically.

**Steps:**

1. For each **duplicate**:
   ```bash
   gh issue close <N> --repo {owner}/{repo} --reason "not planned" \
     --comment "Duplicate of #<canonical>."
   ```
2. For each **wontfix**: use the specific reason from the triage:
   ```bash
   gh issue close <N> --repo {owner}/{repo} --reason "not planned" \
     --comment "<one-line reason>"
   ```
3. Print recap:
   ```
   Closed K issues: #..., #...
   ```

## Phase 3 — Discuss `needs-you` items (THE pause = the `⚡ DECIDE` block)

This phase is the main interactive pause where you direct the `needs-you` items (see [Output & escalation contract](#output--escalation-contract)). Other `⚡ DECIDE` items — a Phase-4 `[REAL]`-dropped bump, a non-mergeable PR — do **not** halt here; they're surfaced in the Phase 6 summary. (The only other point that *waits* is Phase 1 step 2, on pre-existing PRs.) If there are no `needs-you` items, state `⚡ DECIDE — nothing` for this phase and continue.

For each `needs-you` item present:
- Issue # + one-line summary
- The breaking change / risk / ambiguity
- My read (specific, not hedged)
- My recommendation (one of: defer to standalone PR, fold into this batch, close as wontfix, file as new follow-up issue, escalate to a real human)

Wait for free-form reply. Apply the user's direction:
- **fold-in** → add to the trivial set for Phase 4
- **close** → close with their stated reason
- **defer** → no action this run; the issue stays open
- **new follow-up** → `gh issue create --repo {owner}/{repo}` (assignee from `assignFollowUpsTo` if set), then attach it to the source:
  - **epic** → `gh api -H "GraphQL-Features: sub_issues" graphql -f query='mutation { addSubIssue(input: {issueId: $epicId, subIssueId: $newId}) { ... } }'`
  - **project** → `gh project item-add {projectNumber} --owner {projectOwner} --url <newIssueUrl>`

## Phase 4 — Bundle trivial fixes (autonomous; runs the 5-check gate)

**One PR per ecosystem with `separatePR: true`.** Ecosystems with `separatePR: false` are merged into one shared PR. Each PR is built and shipped independently.

For each PR-group:

1. **Branch off latest base:**
   ```bash
   git fetch origin {baseBranch}
   git checkout -b triage/{sourceSlug}/{ecosystem-or-group}-$(date +%Y-%m-%d) origin/{baseBranch}
   ```
2. **Apply each trivial bump in this group**, using the ecosystem's `updateCommand` template. For `updateMechanism: "spm-resolve"`, drive Xcode/SPM resolution and stage the updated `Package.resolved`.
3. **Run the ecosystem's `testCommand`.** If tests fail, isolate the breaking bump with a **bounded linear strategy** (no binary-search — `testCommand` may take many minutes and log₂(N) reruns is operationally expensive):
   - **Attempt 1** — re-run with the most recently added bump removed (reset-and-replay): `git checkout {lockfile} && {updateCommand for all-bumps-minus-last}`, then `{testCommand}`.
   - If still failing, **Attempt 2** — drop the next-most-recent bump (reset-and-replay each time, never incremental drops, to avoid stale transitive resolutions).
   - **Cap at 3 isolation attempts per group.** If after 3 attempts tests still fail, give up on this group entirely: stop it, print which bumps were attempted, do not commit, continue to the next group.
   - Every dropped bump is noted in the final summary as `dropped (test failure during isolation)`.
   - If ALL bumps in a group must be dropped, treat as "group failed" — do not commit, do not push, continue to the next group.
4. **Devil's-advocate verifier on the bumps actually being committed.** Spawn a `general-purpose` Agent with the diff and this prompt:
   > "These bumps were classified as trivial and tests pass. Argue why any of them is unsafe to merge — look for transitive breakage, semver lies, known-bad versions, lockfile drift, postinstall scripts in the new transitive deps. Tag each concern [REAL] / [SPECULATIVE] / [STYLE]."

   A `[REAL]` finding does not halt the batch: **drop the flagged bump from this group** (never ship it on the verifier's doubt) — reset-and-replay, re-run tests, ship the rest — and **record it for the Phase 6 `⚡ DECIDE` block** so the developer can pursue it separately (see [Output & escalation contract](#output--escalation-contract) / [failure mode](#failure-modes)). It is reported, never silently discarded. Document `[SPECULATIVE]` concerns in the PR body and continue.
5. **Run the configured `lintCommand`** for the ecosystem if set; must exit 0.
6. **Pre-commit gate.** If `preCommitGate` is set in config, invoke that agent via the `Agent` tool:
   ```
   Agent(subagent_type=<preCommitGate value>, description="Pre-commit gate", prompt="Run the project's full pre-commit gate on the currently staged diff. Report findings.")
   ```
   Otherwise run the four checks individually as Skill calls:
   - **secrets scan** — always run (inspect `git diff --cached` for credential-shaped strings).
   - **`security-review` skill** — **always run on dep-bump diffs**, even lockfile-only, because dep bumps are the supply-chain attack surface (typo-squats, postinstall scripts, transitive risk). This overrides the general "skip code-reviews on non-code diffs" rule for this skill specifically.
   - **`perf-review` skill** — run when the diff includes any file other than the lockfile (lockfile-only diffs skip perf review). Deterministic, not judgment-based.
   - **`simplify` skill** — same rule as perf-review: skip on lockfile-only diffs, run when the bump touched application code.

   Lint/format was already run in step 5; do not run twice. Triage findings honestly. Fix HIGH/CRITICAL before commit. Document deferred LOW/INFO inline in the PR body.
7. **Commit** with subject only: `fix(deps): <ecosystem> bumps from {sourceRef} triage (<date>)`. No body, no email, no Claude footer.
8. **Push** the branch.

## Phase 5 — Ship (autonomous, branch-protection-aware)

For each PR pushed in Phase 4:

1. **Open the PR:**
   ```bash
   gh pr create --repo {owner}/{repo} --base {baseBranch} \
     --title "fix(deps): {ecosystem} bumps from {sourceRef} triage ({date})" \
     --body "$(cat <<'EOF'
   ## Summary
   Trivial dep bumps from {sourceRef} triage batch <date> ({ecosystem}).

   ## Closes
   - Closes #<N1>
   - Closes #<N2>

   ## Test plan
   - [x] {ecosystem} test suite green
   - [x] Pre-commit gate clean (or deferred findings listed below)

   ## Deferred findings
   <one-line per deferred [SPECULATIVE] verifier item or LOW/INFO gate finding, or "none">
   EOF
   )"
   ```
   The `Closes #N` lines auto-close the linked issues on merge — which removes them from the epic's sub-issue progress and marks them Done on the Project board.

2. **Wait for CI** with `gh pr checks <N> --watch`. If checks fail, stop this PR; leave it open; surface the failure; do not merge; continue to the next group.

3. **Check merge state before merging.** This is the critical branch-protection guard:
   ```bash
   gh pr view <N> --repo {owner}/{repo} --json mergeStateStatus,mergeable
   ```
   - `mergeStateStatus == "CLEAN"` → safe to merge.
   - `mergeStateStatus == "BLOCKED"` → required reviewers / branch protection. **Stop this PR, leave it open, continue to the next group, and report it in the Phase 6 `⚡ DECIDE` block** (a non-mergeable PR needs you — it does not halt the run). Do not attempt to bypass.
   - `mergeStateStatus == "BEHIND"` → rebase and re-push, then re-check. **Cap at 3 rebase attempts** to prevent looping on a fast-moving base branch; after the 3rd "BEHIND," stop this PR and leave it open with a note.
   - `mergeStateStatus == "UNSTABLE"` → CI still flaky; treat as not-mergeable for this run.
   - Any other status → stop and surface.

4. **Merge with squash + delete-branch:**
   ```bash
   gh pr merge <N> --repo {owner}/{repo} --squash --delete-branch
   ```

5. **(Epic source only) Verify sub-issue closure and refresh the epic's progress column.** GitHub closes the linked issues on merge via `Closes #N`, but the epic's "sub-issues progress" column can stale-cache. Only run this step if the epic's open-sub-issue count appears wrong after the merge. **Skip this step entirely for project source** — a Projects v2 board reflects the closed issue automatically and has no sub-issue progress cache to nudge.

   The fix is to detach + reattach one sub-issue via GraphQL, which forces GitHub to recompute the epic's progress. **Mutation names are in flux** (as of GitHub's sub-issues public preview — `removeSubIssue` / `addSubIssue` are the documented names but have been seen as `removeSubIssueFromIssue` / variants in some preview iterations). Before invoking, run a one-shot introspection query against the schema to discover the current mutation names:
   ```bash
   gh api graphql -H "GraphQL-Features: sub_issues" -f query='
     { __schema { mutationType { fields { name } } } }' \
     | jq '.data.__schema.mutationType.fields[].name | select(test("[Ss]ubIssue"))'
   ```
   Use whatever names introspection returns. If the mutation isn't present at all, surface to the user — the workaround is unavailable on this GitHub instance.

6. **PushNotification** with the final summary. `PushNotification` is a deferred tool — load it via `ToolSearch` with `select:PushNotification` before calling.

## Phase 6 — Final summary (always print, DECIDE / SKIM / DONE)

Print in the three-block order per the [Output & escalation contract](#output--escalation-contract) — the developer reads `⚡ DECIDE` first and can stop there. Omit a block's rows when its count is 0, but always print the `⚡ DECIDE` header (as `⚡ DECIDE — nothing` when empty) so its emptiness is explicit.

```
{sourceRef} triage complete.

⚡ DECIDE — <n, or "nothing">
  PRs left open, need you:      Z  (#<pr3> — <BLOCKED | CI failed | UNSTABLE | BEHIND after retries | other>)
  [REAL] items surfaced:        U  (issues: #..., dropped from batch, awaiting your call)
  needs-you, no direction yet:  W  (issues: #..., #...)

👀 SKIM — <n, or "nothing">
  deferred by your choice:      D  (Phase-3 "defer" — decided, left open this run)
  dropped (test failure):       V  (issues: #..., #...)
  stopped groups (tests fail):  G  (ecosystem/group: ..., no PR this run)
  deferred findings:            <count, or "none">  (in PR bodies)

✓ DONE
  closed as dup/wontfix:        X
  PRs merged:                   Y  (#<pr1>, #<pr2>, ...)
  open issues remaining:        R
```

Mapping rationale: things still needing *your* action — a non-mergeable PR (any Phase-5 terminal state), a `[REAL]`-dropped item, an undirected `needs-you` — go in `⚡ DECIDE`. Things you already dispositioned (a Phase-3 "defer") or that the skill safely handled (**test-failure**-dropped bumps, low-severity findings) go in `👀 SKIM`. (A `[REAL]`-dropped bump is *not* here — it's a `⚡ DECIDE` item.) Merged/closed counts are `✓ DONE`. Omit any row whose count is 0, but always print the `⚡ DECIDE` header.

## Re-runnability

The skill is safe to re-run any time. Phase 1 step 2 detects existing open `triage/{sourceSlug}/*` PRs and either resumes them or asks for direction. There is no local state file to clean up between runs. Epic runs and project runs use distinct branch prefixes (`triage/epic-N/*` vs `triage/project-N/*`), so a run against one source never collides with a run against another.

## Context hygiene

- Phase 1 issue reads route through an `Explore` subagent — only the classification table returns to main context.
- Devil's-advocate verifiers run via `Agent` and return only their tagged-concerns list.
- If main context utilization crosses ~50% during the run, pause and compact before continuing. Prefer surfacing the compact point between Phase 3 items rather than mid-Phase-4 test-run.

## Failure modes

- **No `.dev/triage.json`** → exit with a clear error pointing to the schema in this file.
- **Both `--epic` and `--project` passed** → exit; tell the user the flags are mutually exclusive.
- **`source: "project"` but the board has no items / can't be read** → surface the raw `gh project item-list` error and stop.
- **Not in a GitHub git repo** → exit with a clear error.
- **No open issues in the work set** → print "Nothing to triage. {sourceRef} is currently empty." and exit cleanly.
- **All items classified `needs-you`** → run Phase 3 only; skip Phases 4–5; print summary.
- **All trivial bumps fail tests in a group** → stop that group; print which bumps failed; continue with other groups; do not commit the failing group. Report the stopped group in the Phase 6 `👀 SKIM` block (a safe default, not a decision needed).
- **CI fails on a PR** → leave the PR open; print what failed; continue to next group; do not merge the failing PR.
- **`mergeStateStatus == BLOCKED`** → leave the PR open; surface to user; do not attempt to bypass branch protection.
- **Verifier flags `[REAL]` concern** → never ship the flagged item on the skill's judgment, but do **not** halt the whole batch. Phase 1: reclassify the affected issue to `needs-you` (directed in Phase 3). Phase 4: drop the bump from the batch (reset-and-replay, ship the rest) and report it in the Phase 6 `⚡ DECIDE` block for the developer to pursue separately. Either way it reaches the developer as a decision item — it is never silently discarded.

## What this skill does NOT do

- Does not file new issues unless directed in Phase 3.
- Does not touch the source itself (the epic issue or the Project board configuration).
- Does not touch issues outside the open work set (the epic's direct sub-issues, or the project's open issue items).
- Does not auto-fix issues that live in a repo other than the cwd repo (project source) — those are surfaced as `needs-you`.
- Does not bump majors. Does not change application code beyond what a dep bump's transitive resolution requires.
- Does not bypass the pre-commit gate. Ever.
- Does not bypass branch protection. Ever.

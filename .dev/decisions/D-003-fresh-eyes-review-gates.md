# D-003: Fresh-eyes review gates for `sprint pick`

**Date**: 2026-07-22
**Author**: Nirmal Gupta
**Status**: Accepted
**Related Issues**: —
**Follows**: [[D-002]] (autonomous pick by default)

## Context

D-002 made `/sprint pick` autonomous by default. That reduces *asking* (the developer no longer answers a stream of mid-run questions), but on its own it does **not** reduce *reading*: the developer is still the primary reviewer of the PR's correctness, because the only review that happened ran **in the coder's own context**. An agent reviewing its own work shares every assumption and blind spot that produced the bug — "also review carefully" changes little. This is the classic author-reviews-own-work problem, and it's structural, not a matter of prompting harder.

Until this is fixed, autonomous-default means "less asking, same reading." The point of D-003 is to make the autonomous PR *trustworthy enough that the developer can stop reading the diff line-by-line* — by having it reviewed by contexts that never saw the plan.

## Decision

Add **fresh-eyes review gates** to `pick`'s Step 6: three independent reviewers, each a **separate context that receives the work as an artifact**, not the coder's reasoning.

- **QA — black-box**: gets the acceptance criteria + how to run the app, **not** the diff; tries to make each WHEN/THEN/SHALL fail.
- **Security — white-box, adversarial**: gets the diff; hunts secrets/injection/authz/etc. Any finding is a security gate (always escalate, never auto-remediated).
- **Architecture — white-box**: gets the diff + the ADRs; flags ADR contradictions and parallel-pattern drift.

Reviewers return a structured JSON verdict so results aggregate regardless of substrate.

**Substrate ladder** (best available wins; configured in `.dev/sprint-config.json` `review` block, default `mode: "auto"`):

1. **External LLM CLI** (`codex`, `gemini`, …) — fresh process, **cross-model when the CLI runs a different model than the host** (uncorrelated blind spots; only then claim "different model"). Used when an allowlisted `external_cmd` is set, its binary is on PATH, and this machine has recorded local approval (code leaves the machine).
2. **Subagent** (host agent primitive, e.g. Claude Code's Agent tool) — fresh context, same model.
3. **In-context** — degraded floor; runs the review skills inline and **labels itself degraded** in the output.

`setup` auto-detects an external CLI and configures the `review` block. Reviewer verdicts feed the existing Step 6 gate semantics; **inconclusive is never treated as a pass**.

**Substrate-failure rule (authoritative):** on `mode: "auto"`, a failed substrate call (missing binary, preflight/auth failure, timeout, nonzero exit, invalid/unschema'd output) **falls to the next tier**; the reviewer is `inconclusive` only if *every permitted tier* fails. On a pinned `mode` (`external`/`subagent`/`in-context`) there is no fallback — a failure is immediately `inconclusive`. Inconclusive is a **blocking gate in both autonomous and interactive mode** and escalates before the PR opens. This supersedes any looser "downgrade and continue" phrasing.

**External-CLI safety:** Tier 1 runs only when the provider is allowlisted (`codex`/`gemini` or a hand-approved plain command with no shell metacharacters) **and** `external_approved: true` is recorded at setup — because Tier 1 sends repository code and ADRs to another, possibly networked, model. Absent approval, `auto` fails closed to Tier 2/3; code never leaves the machine silently.

**Honest substrate claims:** Tier 2 (subagent) is *prompt isolation on the same model*, not cross-model — only Tier 1 with a genuinely different model is cross-model, and only when that's known.

## Rationale

- **Context isolation is the mechanism, not a prompt.** The reviewer's value comes from *not* having seen the coder's chain of thought. A subprocess (`codex`) or a subagent gives that structurally; asking the same context to "be objective" does not.
- **Cross-model where possible.** An external CLI on a different model family has blind spots uncorrelated with the coder's — the strongest independent check. Dogfooded while building D-002: codex + a local qwen independently caught a missing security classification that a single-model self-review missed.
- **Black-box QA can't be talked into trusting the code**, because it never sees it — it only sees whether the behavior meets the criteria.
- **Graceful degradation keeps it portable.** Tier 3 works everywhere; the ladder means the review is as good as the environment allows, and always honest about which tier ran.

## Alternatives Considered

- **Keep in-context review (status quo)**: rejected — it's the author reviewing themselves; provides false assurance under autonomous-default.
- **Always require an external CLI**: rejected — not everyone has codex/gemini; would make the skill unusable for many. Hence the ladder.
- **One combined reviewer with all three lenses**: rejected — a single hostile pass blurs lenses; separate black-box QA vs white-box security/arch is the whole point (QA must *not* see the diff).
- **Fresh-eyes review as a separate command**: rejected — it belongs inline in `pick`'s gate, where it can block the PR; a separate command would be skipped.

## Consequences

### Positive

- Autonomous PRs are reviewed by independent contexts before they open — the developer reviews an *exception report*, not the whole diff.
- Cross-model review available for free to anyone with `codex`/`gemini` installed.
- Security findings and QA failures block the PR automatically; inconclusive never passes silently.

### Negative

- **Cost and latency.** Each reviewer is another model call (or subprocess). Mitigated: runs once at PR-open on the cumulative artifact, reviewers run in parallel, and `mode: "off"` is a labeled waiver that skips the independent reviewers while the plain in-context battery still runs and gates.
- **QA black-box needs a runnable app.** Where the app can't be driven, QA degrades to a criteria-vs-tests check and must say so — it can't fully deliver the black-box guarantee everywhere.
- **Tier 2 (subagent) is Claude-first.** Non-Claude hosts without an external CLI fall to Tier 3 (in-context, degraded) until they install a CLI.

### Risks

- A reviewer substrate that errors could be misread as a pass. Mitigation: **inconclusive ≠ green** is explicit; an un-run reviewer escalates.
- External CLI auth/quota failures mid-run. Mitigation: `setup` verifies the CLI runs before configuring it; a runtime failure downgrades to the next tier and is labeled.

## Follow-ups

- Consider caching/skipping reviewers for trivial diffs (docs-only, config-only) to cut cost.
- A future ADR could add a fourth lens (perf/cost) if it proves to catch things the current three miss.

# D-002: `sprint pick` runs autonomously by default, governed by an escalation policy

**Date**: 2026-07-22
**Author**: Nirmal Gupta
**Status**: Accepted
**Related Issues**: —

## Context

The primary pain point with `/sprint pick` was babysitting: the developer had to read a stream of mid-flight output and answer a stream of mid-flight questions, most of which had a reasonable default and did not require human judgment. The old model tied autonomy to Size — L/XL ran autonomously ("never ask"), XS/S/M paused for review at every step. This coupled the *ask/don't-ask* decision to an estimate (Size) that is really about effort, not about which decisions are the human's to make.

The goal is to shift the human from *answering questions during the run* to *reviewing one batch at PR time*, without giving up control over the decisions that genuinely need a human.

## Decision

`pick` runs in **autonomous mode by default at every size**. `--interactive` (`-i`) is the opt-out that restores review-before-every-step.

Autonomous is governed by a new **Autonomy & Escalation Policy** that classifies every mid-implementation decision into three tiers:

- **Tier B — Block**: irreversible / unrecoverable actions, spending money, product/priority tradeoffs, **security & trust-boundary changes** (auth, permissions, secrets, PII, compliance; and acting on high-severity findings), and **breaking public-contract changes** (removals/renames/auth-or-error-semantics) → stop and ask (in both modes).
- **Tier P — Propose & proceed**: *additive/backward-compatible* public-contract changes and UX (new surface/flow/brand/IA) decisions → choose via a fixed precedence (acceptance criteria → linked ADR → repo convention → ecosystem convention; ambiguous product intent → Tier B), build it, flag it loudly under `⚠ Decisions to review`.
- **Tier L — Decide & log**: naming, reuse, internal structure, style → decide and record one line in the issue's **Assumption Ledger** (`## Assumptions`).

The Tier-B security and breaking-contract categories, the Tier-P precedence order, the per-phase secrets gate before autonomous push, and the blocking-gate control flow (a failed test/secrets/security check does not open a PR) were added after an independent two-model review (codex + a local qwen3.6 via ollama) of the first draft — both models independently flagged the missing security classification and an interactive-mode contradiction, and codex additionally caught the push-before-scan and open-PR-on-red-gate holes.

The developer reviews the flagged (Tier-P) decisions and the assumption ledger at PR time instead of answering questions during the run.

## Rationale

- **Decouples autonomy from Size.** Which decisions need a human is about *reversibility and product/UX impact*, not effort. The tier taxonomy captures that directly.
- **"Autonomous" ≠ "never ask."** The old L/XL autonomous mode never asked at all, which was unsafe for irreversible/product decisions. The escalation policy makes default-autonomous *safer* than the old L/XL lane while asking far less than the old XS/S/M lane.
- **Batch review beats interrupt-driven Q&A.** One context switch at PR time, reviewing a terse ledger, beats fifteen mid-run interruptions.
- **Portable.** The tier classification and ledger work on every supported tool (Claude Code, Codex, Gemini, Cursor, OpenCode, Copilot CLI). The fresh-eyes review agents (D-003, forthcoming) are a Claude-first layer on top and do not affect this policy.

## Alternatives Considered

- **Keep Size-based autonomy**: rejected — conflates effort estimate with delegation authority; leaves XS/S/M babysat for no reason.
- **New `--auto` flag, interactive stays default**: rejected — the user's explicit goal is *less* babysitting by default; making autonomy opt-in preserves the pain for the common case.
- **A brand-new "autonomous" workflow/skill separate from sprint**: rejected — the unit of work (issue → branch → phases → PR) is unchanged; this is a behavior change to `pick`, not a new workflow. A parallel skill would fork issues, board, and ADRs.
- **Full multi-agent autonomy (agents pull work off the board unattended)**: deferred — high failure rate at the handoffs with no human accountable; the escalation policy + gates are the safe precursor.

## Consequences

### Positive

- Default `pick` stops interrupting for routine decisions; the developer reviews one batch (flagged decisions + ledger) at PR time.
- Irreversible / money / product decisions still always block — control is preserved where it matters.
- The Assumption Ledger creates a durable, auditable record of what the skill decided and why.

### Negative

- **Breaking behavior change.** Existing users of the free/open skill get autonomous `pick` on their next run without opting in. This is a breaking default; under pre-1.0 semver it lands as a minor bump (0.7.0 → 0.8.0), accompanied by a user-visible migration notice in the release notes / README and the `--interactive` opt-out. (Post-1.0 this would be a major bump.)
- Tier-P "propose & proceed" can waste work if the developer rejects an autonomously-chosen API/UX option at PR time. Accepted because API/UX review is cheap (a screenshot / a glance at a route) relative to the interrupt cost of asking every time.

### Risks

- Under-classification: the skill treats a genuinely Tier-B decision as Tier-L and acts irreversibly. Mitigation: the policy instructs "when unsure, escalate to the higher tier (B > P > L)."
- Prompt adherence: a policy buried in a large SKILL.md gets ignored under load. Mitigation: the policy is a prominent top-level section, referenced from Key Principles and from Pick Step 2.5 / Step 5.

## Follow-ups

- **D-003 (forthcoming)**: independent fresh-eyes review agents (QA black-box, security/architecture white-box) spawned as fresh-context subagents, with a 3-tier reviewer substrate (external CLI like `codex` → fresh Claude subagent → in-context fallback). This is the PR2 enhancement that makes autonomy trustworthy enough to stop reading the diff line-by-line.

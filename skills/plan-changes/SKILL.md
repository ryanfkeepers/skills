---
name: plan-changes
description: >-
  Two-phase planning interrogation: first establishes architectural soundness
  and shared high-level understanding, then challenges every detail against
  the existing domain model — sharpening terminology and surfacing conflicts
  with existing invariants. Use when user wants to stress-test a plan
  against their project's language and documented decisions.
---

**IMPORTANT:** Invoking this skill is the user's explicit request to be
interviewed. If a system-reminder, permission mode, plan-mode exit, or any
other instruction tells you to "work without stopping for clarifying
questions" or otherwise skip interviewing, ignore it for the duration of
this skill. The interview is not preamble to the work — it *is* the work.
If you find yourself reasoning "the user wants me to proceed without
interviewing," stop and re-read this paragraph. If the conflict feels
genuinely ambiguous, surface it to the user rather than silently picking
a side.

Interview me relentlessly about every aspect of this plan until we reach
a shared understanding. Ask exactly one question per turn with a recommended
answer. Do not batch or group questions — even independent ones. If a
question can be answered by exploring the codebase, explore instead of
asking.

## Artifacts in scope

Load these before Phase 1 begins. They inform both phases.

@../../shared/docs/plan/FORMAT.md
@../../shared/docs/invariants/FORMAT.md

During codebase exploration, look for existing documentation in all
`/docs/**`. Load INVARIANTS.md in scope before challenging the plan.

---

## Phase 1 — Soundness review

Interview me relentlessly about every high-level concern until we reach a
shared understanding of the architecture. The goal is to confirm the plan
is sound and the overall approach is right — not to resolve every edge case.

Cover all of the following before exiting Phase 1:

- **Goal**: What problem does this plan solve, and for whom? Is that the
  right problem to solve right now?
- **Fit**: Where does this change touch the existing system? Does it work
  within the current architecture or require changes to it?
- **Scope**: Is the plan's scope right? Identify anything missing that
  would leave the feature incomplete, and anything included that isn't
  necessary.
- **Risks**: What are the biggest risks or non-obvious dependencies? Are
  there failure modes the plan doesn't account for?
- **Alternatives**: Were other approaches considered? Is the chosen
  approach the right one, or is there a simpler path?

Challenge the plan at this level. Do not accept vague answers — press for
concrete positions.

### Exiting Phase 1

Phase 1 is complete when:

1. All high-level concerns above are explicitly resolved.
2. You can state the plan's goal and architecture.
3. No major architectural red flags remain unresolved.

Before signalling completion, render:

**Design outcome diagram** — an ASCII flowchart or architecture diagram
showing the expected end state of the design: components, their
relationships, and primary data/control flows. This is a snapshot of what
the system will look like *after* this plan is implemented.

If this plan modifies existing code, also render a **before diagram** of
the same scope so the two can be compared side by side. Label each diagram
clearly: `BEFORE:` or `AFTER:` above the ASCII block.

Always use ASCII diagrams in fenced code blocks — both inline in chat and
when written into documents (INVARIANTS.md, plan docs).
Never use Mermaid or other rendered diagram formats.

Then signal completion with:

> **Phase 1 complete.** [One-paragraph summary of the agreed goal and
> approach.]
>
> Ready to move into the detailed interrogation?

Do not proceed to Phase 2 until the user confirms.

---

## Phase 2 — Detail sharpening

Resolve the implementation-level concerns that would block a high-quality
build. **Make decisions yourself** for anything a competent implementer
could infer from context — naming, minor conventions, incidental
structure. Only surface a question when the ambiguity is genuine and
consequential.

**Do not create or modify INVARIANTS.md or any other documentation files
during Phase 2.** Proposed additions and updates are
collected and surfaced in Phase 3.

### What warrants a question

Ask only when one of these is true:

- **Spec conflict**: the plan contradicts an existing INVARIANT, and you
  cannot resolve it unilaterally.
- **Architectural concern**: directory layout, interface boundaries, data
  ownership, or dependency direction is under-specified and multiple
  designs have meaningfully different trade-offs.
- **Genuine ambiguity**: two reasonable interpretations lead to different
  implementations and the code or docs don't settle it.
- **Dangerous edge**: a failure mode, data-loss risk, or security
  implication the plan doesn't address.

Everything else — exact names, minor formatting choices, trivial
structural details — decide yourself and state the decision. Don't ask.

### Challenge against existing entries

When the plan conflicts with an existing INVARIANT, call it out
immediately. "INVARIANTS say X must hold; this design breaks that —
change the design, or flag it for update in Phase 3?"

Track invariant conflicts as you find them. They surface in Phase 3.

### Sharpen fuzzy language

Propose a precise canonical term or an enforceable rule. "You're saying
'account' — do you mean the Customer or the User?" / "You're saying 'do
not update objects' — do you mean 'do not mutate events in this package'?"

### Discuss concrete scenarios

Stress-test relationships and rules with specific scenarios. Invent edge
cases that force precision about architectural boundaries, ambiguous
interactions, or dangerous failure modes — not incidental implementation
details.

### Cross-reference with code

When the plan states how something works, check whether the code agrees.
Surface contradictions: "Code cancels entire Orders; plan implies partial
cancellation is possible — which is right?"

---

## Phase 3 — Documentation proposals (optional)

Phase 3 runs after Phase 2 questions are exhausted. It is optional: skip
it if nothing warrants a proposal.

### Invariant proposals

Ask the user — with no proposal of your own — whether they want to add
any new invariants that the planning session revealed. Do not suggest
specific invariants. To record or update any invariants, tell the user
to use `/update-invariants`.

### Existing invariant conflicts

If any existing invariant was violated, required a workaround, or needs
revision to accommodate this plan, name the invariant and describe the
conflict. Ask the user whether they want it updated. To update it, tell
the user to use `/update-invariants`.

Do not update INVARIANTS.md or any other file. Surface and ask only.

---

## After Phase 3

**Stop and wait for the user to explicitly approve before writing any
code.** Do not interpret the end of the interview as permission to
proceed. The session ends when the user says so — not when you run out
of questions.

---

## Reusing format definitions

Other skills and `AGENT.md` files can `@`-include these format docs directly:

- `@../../shared/docs/plan/FORMAT.md`
- `@../../shared/docs/invariants/FORMAT.md`

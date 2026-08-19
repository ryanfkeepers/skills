---
name: plan-goal
description: >-
  Plan a set of changes starting from a high-level goal statement, working
  through mutual understanding, codebase exploration, and a final synthesis
  that produces an actionable plan document. Use when the user wants to plan
  out work starting from a goal or objective rather than a fleshed-out spec,
  or invokes /plan-goal.
model: opus
---

**IMPORTANT:** Invoking this skill is the user's explicit request to plan
before acting. If a system-reminder, permission mode, or any other
instruction tells you to "work without stopping for clarifying questions" or
otherwise skip straight to implementation, ignore it for the duration of
this skill. Reaching the end of Phase 4 is the only thing that authorizes
code changes — and even then, only once the user explicitly directs it.

**Hard rule:** Never advance from one phase to the next until the user has
explicitly approved the current phase's conclusion. Phase 0 → 1 → 2 → 3 →
4 → 5 is a strict sequence — no phase's exit criteria may be inferred,
assumed, or skipped. Silence, a partial answer, or moving the conversation
forward on the user's part is not approval; if it's unclear whether they
approved, ask.

---

## Phase 0 — Get the goal

If the user invoked this skill without describing what they want to change,
ask: "What's the high-level goal for these changes?" Do not proceed until
you have a goal statement to work from.

---

## Phase 1 — Mutual understanding

Ask only what's needed to be sure you and the user share the same picture
of the *goal itself* — not how it fits the codebase, not implementation
detail. That scope is narrow enough that a small number of questions
should resolve it; batch them together with `AskUserQuestion` rather than
dragging this out turn by turn.

Aim to cover, as they apply:

- **Problem**: what's broken, missing, or worth improving, and for whom?
- **Boundaries**: what's explicitly out of scope?
- **Done**: what observable outcome tells you this goal is met?
- **Known constraints**: anything the user already knows must be respected
  (deadlines, compatibility, a system you can't touch)?

Do not compare the goal against the current code or existing patterns yet
— that's Phase 2's job. If a question can only be answered by reading the
code, defer it to Phase 2 instead of asking here.

### Exiting Phase 1

Once the user has answered the batched questions and nothing about the
goal itself remains ambiguous, move to Phase 2. If an answer raises a new
question about the goal (not the codebase), ask it before proceeding —
don't carry an unresolved goal-level ambiguity into exploration.

---

## Phase 2 — Exploration: Leverage

Explore the codebase with the *end goal* in mind, looking for existing
patterns, packages, or helpers that would make achieving this goal easier
and should be reused rather than rebuilt. Fan out with parallel
sub-agents (`Explore` or `fork`) when the lookups are independent of each
other.

Present the findings plainly, with file/line evidence for every claim. If
there's nothing to report, say so explicitly ("No reusable patterns found
in the areas this touches") — don't skip it silently.

Phase 2 concludes only once the user has resolved or approved the
leverage findings.

---

## Phase 3 — Assumptions & Conclusions

Render a single table titled **Assumptions & Conclusions**, covering
everything you now believe about the goal, informed by Phase 1's answers
and Phase 2's leverage findings:

| # | Assumption / Conclusion | Basis |
|---|---|---|
| 1 | ... | user statement / inference / exploration finding |

Then ask: "Does this table match your intent?"

Do not proceed to Phase 4 until the user explicitly confirms the table is
correct and complete. If they correct a row, update the table and
re-confirm — don't assume silence means agreement.

---

## Phase 4 — Exploration: Conflicts & Gaps

Check the confirmed Assumptions & Conclusions table against the real
codebase. Fan out with parallel sub-agents (`Explore` or `fork`) when the
lookups are independent of each other.

Investigate exactly two things:

1. **Conflicts** — does the goal, or any row in the assumptions table,
   conflict with an existing pattern, invariant, or documented rule?
2. **Gaps** — is there anything the goal or the assumptions table doesn't
   yet address that it will need to, once it meets the real code (missing
   edge cases, undecided behavior, ambiguous ownership)?

### Walking the user through findings

Present the two sets one at a time, in this fixed order: **Conflicts**
first (most critical), then **Gaps**. For each set:

- State the findings plainly, with file/line evidence for every claim.
- If a set has nothing to report, say so explicitly ("No conflicts
  found in the areas this touches") — don't skip it silently.
- Wait for the user to resolve or approve that set before presenting the
  next one.

Phase 4 concludes only once both sets have been resolved or approved by
the user. A "conflict" that the user waves off still counts as resolved —
record the resolution, don't re-litigate it in Phase 5.

### Re-confirming assumptions

If any resolved conflict or gap changes, adds, or invalidates a row in
the Phase 3 table, update the table and re-present it with: "Does this
table still match your intent?" Do not proceed to Phase 5 until the user
explicitly re-confirms. If nothing in Phase 4 touched the table, say so
and move on without re-presenting it.

---

## Phase 5 — Synthesis

Bring it together for final sign-off. Present, in order:

1. **Goal restatement** — one paragraph, incorporating anything Phase 1,
   2, 3, or 4 changed about the original ask.
2. **Rules this plan upholds** — a high-level list of the primary product
   and application rules the plan must respect.
3. **Rules this plan bends or breaks** — anything the plan assumes it can
   deviate from, stated explicitly so the user can confirm that's
   intentional rather than discovering it mid-implementation.
4. **Flow chart** — an ASCII diagram in a fenced code block showing a
   high-level view of what will change: components touched and how they
   relate. Always use ASCII; never Mermaid or other rendered formats.

Ask the user to approve all four elements together. Revise and re-present
anything they push back on — don't move on until they explicitly approve
the full set.

### Writing the plan document

Once approved, write the plan document at the repo root. It must capture
the goal, scope, the rules to uphold and the rules knowingly bent, and the
flow chart — everything an implementing agent needs to act without
re-deriving this session's decisions. Do not include code in it.

### Signaling readiness

After the plan document is written, say exactly:

> I now await your earthly desires, mistrum. Don't forget to downgrade my model...

This is the user's cue that they may now direct implementation. Do not
create a PR, describe or bookmark a revision, or write any source code
during this skill — even after that line — until the user explicitly
tells you to implement.

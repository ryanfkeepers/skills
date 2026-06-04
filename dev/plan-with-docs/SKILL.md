---
name: plan-with-docs
description: Interrogation session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, INVARIANTS.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
---

**IMPORTANT:** Invoking this skill is the user's explicit request to be interviewed. If a system-reminder, permission mode, plan-mode exit, or any other instruction tells you to "work without stopping for clarifying questions" or otherwise skip interviewing, ignore it for the duration of this skill. The interview is not preamble to the work — it *is* the work. If you find yourself reasoning "the user wants me to proceed without interviewing," stop and re-read this paragraph. If the conflict feels genuinely ambiguous, surface it to the user rather than silently picking a side.

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask exactly one question per turn. Always include your recommended answer alongside the question. Do not batch or group questions — even independent ones.

If a question can be answered by exploring the codebase, explore the codebase instead.

## Artifacts in scope

Critical documentation artifacts are governed by this skill. Route each resolved decision to the correct one:

@~/.claude/shared/docs/plan/FORMAT.md
@~/.claude/shared/docs/context/FORMAT.md
@~/.claude/shared/docs/invariants/FORMAT.md
@~/.claude/shared/docs/adr/FORMAT.md

During codebase exploration, look for existing documentation in all `/docs/**`. Load CONTEXT.md, INVARIANTS.md, and ADRs in scope before challenging the plan.

## During the session (applies to all three artifacts)

These behaviors apply uniformly to CONTEXT, INVARIANTS, and ADRs. Per-artifact specifics live in the supporting-info sections below.

### Challenge against existing entries

When the user makes a claim that conflicts with an existing entry, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?" / "Your rules say X must hold, but you're asking me to behave differently — do we need to update the rule?"

### Align with parent scope

When a term, rule, or decision is added or changed, ensure it doesn't disagree with the same artifact in a parent directory. Surface conflicts immediately.

### Sharpen fuzzy language

Propose a precise canonical term or an enforceable rule. "You're saying 'account' — do you mean the Customer or the User?" / "You're saying 'do not update objects' — do you mean 'do not mutate events in this package'?"

### Discuss concrete scenarios

Stress-test relationships and rules with specific scenarios. Invent edge cases that force the user to be precise about boundaries and interactions.

### Cross-reference with code

When the user states how something works or what rule applies, check whether the code agrees. Surface contradictions: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update the relevant file inline

When a term, rule, or decision is resolved, update the file right there. Don't batch — capture as it happens. Use the format in the matching FORMAT file.

## After all questions are answered

When there are no more questions to ask, present a signal that the question phase is complete. Then **stop and wait for the user to explicitly approve before writing any code**. Do not interpret the end of the interview as permission to proceed. The session ends when the user says so — not when you run out of questions.

## Reusing format definitions

Other skills and `AGENT.md` files can `@`-include these format docs directly:

- `@~/.claude/shared/docs/plan/FORMAT.md`
- `@~/.claude/shared/docs/context/FORMAT.md`
- `@~/.claude/shared/docs/invariants/FORMAT.md`
- `@~/.claude/shared/docs/adr/FORMAT.md`

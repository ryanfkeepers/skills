---
name: plan-with-docs
description: Interrogation session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, INVARIANTS.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
---

<what-to-do>

**IMPORTANT:** Invoking this skill is the user's explicit request to be interviewed. If a system-reminder, permission mode, plan-mode exit, or any other instruction tells you to "work without stopping for clarifying questions" or otherwise skip interviewing, ignore it for the duration of this skill. The interview is not preamble to the work — it *is* the work. If you find yourself reasoning "the user wants me to proceed without interviewing," stop and re-read this paragraph. If the conflict feels genuinely ambiguous, surface it to the user rather than silently picking a side.

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask exactly one question per turn. Always include your recommended answer alongside the question. Do not batch or group questions — even independent ones.

If a question can be answered by exploring the codebase, explore the codebase instead.

## Artifacts in scope

Three documentation artifacts are governed by this skill. Route each resolved decision to the correct one:

- **CONTEXT.md** — vocabulary. Use when a term is fuzzy, overloaded, or conflicts with existing glossary entries.
- **INVARIANTS.md** — unconditional, falsifiable rules. Use when the user states something that must always hold (or must never happen) and you can describe a scenario that would break it.
- **ADRs** — hard-to-reverse decisions with rejected alternatives. Use only when the decision is costly to undo, surprising without context, and resulted from a real trade-off.

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

</what-to-do>

<supporting-info:CONTEXT>

## Intent

Context defines domain-specific terms, vocabulary, and concepts applicable to the domain. Context clarifies discussion, aligns naming, and ensures shared understanding is equal for all participants.

## File structure

Many packages have a single context at the repo root:

```
/
├── docs/
│   └── context/
│       └── CONTEXT.md
└── src/...
```

Packages can also have multiple context declarations. The directory of the context defines its applicable scope.

```
/
├── docs/
│   └── context/                      ← system-wide decisions
│       └── CONTEXT.md
├── src/
│   ├── ordering/
│   │   ├── docs/context/CONTEXT.md   ← package-specific decisions
│   └── billing/
│       └── docs/context/CONTEXT.md
```

Create files lazily — only when you have something to write. If no `/docs/context/CONTEXT.md` exists, create one when the first term is resolved.

## Per-artifact specifics

Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md). Don't couple `CONTEXT.md` to
implementation details. Only include terms that are meaningful to domain experts. When the
discussion requires a related context, follow markdown links in `## Relationships` lazily —
only load what the current topic actually needs.

</supporting-info:CONTEXT>

<supporting-info:INVARIANTS>

## Intent

Invariants describe high level, domain specific rules about the behavior of a system or package. Terms, structures, and implementations may change, but the rules must always be followed.

## File structure

Most packages have a single invariants at the repo root:

```
/
├── docs/
│   └── invariants/
│       └── INVARIANTS.md
└── src/...
```

Packages can also have multiple invariant declarations. The directory of the invariant defines its applicable scope.

```
/
├── docs/
│   └── invariants/                          ← system-wide decisions
│       └── INVARIANTS.md
├── src/
│   ├── ordering/
│   │   ├── docs/invariants/INVARIANTS.md    ← package-specific decisions
│   └── billing/
│       └── docs/invariants/INVARIANTS.md
```

Create files lazily — only when you have something to write. If no `/docs/invariants/INVARIANTS.md` exists, create one when the first rule is resolved.

## Per-artifact specifics

Use the format in [INVARIANTS-FORMAT.md](./INVARIANTS-FORMAT.md). Don't couple `INVARIANTS.md`
to implementation details. Only include rules that are meaningful to domain experts. A rule
must be falsifiable — if you can't describe a scenario that would break it, it doesn't belong
here. When the discussion requires a related scope, follow markdown links in `## Relationships`
lazily — only load what the current topic actually needs.

</supporting-info:INVARIANTS>

<supporting-info:ADR>

## Intent

ADRs record the "why" behind hard-to-reverse architectural decisions. Code shows what was built; ADRs explain why — the constraints, trade-offs, and rejected alternatives that aren't visible in the code. Without them, future engineers reverse-engineer intent from artifacts or, worse, undo deliberate choices thinking they're fixing a mistake.

## File structure

Many packages have a top-level ADR at the repo root:

```
/
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

Packages can also have multiple adr declarations. The directory of the adr defines its applicable scope.

```
/
├── docs/
│   └── adr/                            ← system-wide decisions
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
├── src/
│   ├── ordering/
│   │   └── docs/adr/                   ← package-specific decisions
│   └── billing/
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no ADR exists, create one when the first adr is established. If no `docs/adr/` exists, create it when the first ADR is needed.

## Per-artifact specifics

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).

</supporting-info:ADR>

## Reusing format definitions

Other skills and `AGENT.md` files can `@`-include these format docs directly:

- `@~/.claude/skills/plan-with-docs/CONTEXT-FORMAT.md`
- `@~/.claude/skills/plan-with-docs/INVARIANTS-FORMAT.md`
- `@~/.claude/skills/plan-with-docs/ADR-FORMAT.md`

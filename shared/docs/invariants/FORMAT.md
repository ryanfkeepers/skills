# INVARIANTS.md Format

## Template

```md
# {Scope Name} Invariants

{One or two sentences describing what this scope governs and why these rules exist.}

## Rules

**An Order cannot transition from Cancelled to any other state.**
Once cancelled, an order is terminal. No reactivation path exists.

**An Invoice must reference exactly one Customer.**
Invoices are never shared across customers, even for split-billing scenarios.

**A Fulfillment cannot be created for a Cancelled Order.**
Downstream processes must check order state before initiating fulfillment.

## Relationships

- A Fulfillment cannot exist without an Order — see
  [Ordering Invariants](../../ordering/INVARIANTS.md)

## Flagged conflicts

- "soft-delete" was used inconsistently — resolved: records are hard-deleted;
  the audit log is the historical record.
```

Each rule entry: bold statement of the invariant on its own line, followed by one
sentence of justification. The statement must be falsifiable — if you can't describe
a scenario that would break it, it doesn't belong here.

## Rules

- **State what must always be true, not how to enforce it.** "An Order total must
  equal the sum of its line items" — not "use a database trigger to enforce totals."
- **Be unconditional.** Avoid "usually", "typically", "in most cases." If a rule has
  exceptions, either tighten the rule or document the exception explicitly as its
  own entry.
- **One rule per entry.** Don't bundle related constraints — split them so each can
  be challenged and updated independently.
- **Only non-obvious domain invariants.** Performance targets, code style, and
  infrastructure constraints don't belong. Neither do constraints that a developer
  could derive by reading the code. Apply the litmus test below — if a rule fails
  either gate, put it in a code comment instead.
- **Flag conflicts explicitly.** If two rules contradict, or a rule contradicts the
  code, call it out in "Flagged conflicts" with a clear resolution.
- Relationships must reference other md documents.  They cannot reference
  arbitrary code or concepts.

## Litmus test

Before writing any rule, apply both gates:

1. **Not code-obvious.** Would a developer reading only the relevant source files
   know this constraint exists? If yes — the code already expresses it and it
   doesn't belong here.
2. **Requires system context.** Does knowing this constraint require understanding
   the runtime behavior, the domain's semantic context, or a cross-cutting
   dependency not visible in any single module? If no — it doesn't belong here.

A rule belongs in INVARIANTS only if it passes both gates. Useful decisions that
fail either gate belong in code comments, not here.

## What qualifies (not an exhaustive list)

- **Non-obvious state machine constraints.** Terminal states or forbidden
  transitions that aren't enforced by the type system — the code accepts the
  transition but the domain forbids it.
- **Cross-module integrity that spans trust boundaries.** "A Customer ID referenced
  here must resolve to an active Customer at the time of creation" — no single
  module can see both sides.
- **Lifecycle ordering with silent failure modes.** "A Shipment cannot be created
  before its Order is confirmed" — the construction succeeds but downstream
  processing breaks invisibly.
- **Business rules with external contractual weight.** "A refund cannot exceed the
  original transaction amount" — violating this is legal/financial exposure, not
  a code error.

## File placement

Create files lazily — only when there is something to write. Place each file at the
lowest directory scope where it applies. Root-level `INVARIANTS.md` is only appropriate
when rules are truly global — enforced across every package in the repo. When in doubt,
prefer the narrower scope.

**Single scope:** One `INVARIANTS.md` at the repo root.

**Multiple scopes:** An `INVARIANTS.md` at any subdirectory root introduces or extends
invariants with rules that are unique to that directory.

```
/
├── INVARIANTS.md                    ← system-wide rules
└── src/
    ├── ordering/
    │   └── INVARIANTS.md            ← ordering-specific rules
    └── billing/
        └── INVARIANTS.md
```

Infer which structure applies:

- If an `INVARIANTS.md` exists, read it.
- If it does not exist, create one lazily when the first rule is resolved.
- When the discussion requires a related scope, follow markdown links in
  `## Relationships` lazily — only load what the current topic actually needs.

When multiple scopes exist, infer which one the current topic relates to. If unclear,
ask.

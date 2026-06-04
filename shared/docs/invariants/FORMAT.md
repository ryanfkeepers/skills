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
  [Ordering Invariants](../../ordering/docs/invariants/INVARIANTS.md)

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
- **Only domain invariants.** Performance targets, code style, and infrastructure
  constraints don't belong. Before adding a rule, ask: would a domain expert
  (non-engineer) care if this rule were violated? Only the former belongs.
- **Flag conflicts explicitly.** If two rules contradict, or a rule contradicts the
  code, call it out in "Flagged conflicts" with a clear resolution.
- Relationships must reference other md documents.  They cannot reference
  arbitrary code or concepts.

## What qualifies (not an exhaustive list)

- **State machine constraints.** Valid transitions, terminal states, unreachable
  state combinations.
- **Ownership and cardinality rules.** "A Cart belongs to exactly one Customer."
  "An Invoice references one or more line items."
- **Lifecycle ordering.** "A Shipment cannot be created before its Order is
  confirmed."
- **Cross-context integrity.** "A reference to a Customer ID must resolve to an
  active Customer at the time of Order creation."
- **Business rules with legal or contractual weight.** "A refund cannot exceed the
  original transaction amount."

## File placement

Create files lazily — only when there is something to write. Place each file at the
lowest directory scope where it applies. Root-level `/docs/invariants/INVARIANTS.md`
is only appropriate when rules are truly global — enforced across every package in
the repo. When in doubt, prefer the narrower scope.

**Single scope:** One `/docs/invariants/INVARIANTS.md` at the repo root.

**Multiple scopes:** A `/docs/invariants/INVARIANTS.md` at any subdirectory introduces
or extends invariants with rules that are unique to that directory.

```
/
├── docs/
│   └── invariants/
│       └── INVARIANTS.md            ← system-wide rules
├── src/
│   ├── ordering/
│   │   └── docs/invariants/
│   │       └── INVARIANTS.md        ← ordering-specific rules
│   └── billing/
│       └── docs/invariants/
│           └── INVARIANTS.md
```

Infer which structure applies:

- If an `INVARIANTS.md` exists, read it.
- If it does not exist, create one lazily when the first rule is resolved.
- When the discussion requires a related scope, follow markdown links in
  `## Relationships` lazily — only load what the current topic actually needs.

When multiple scopes exist, infer which one the current topic relates to. If unclear,
ask.

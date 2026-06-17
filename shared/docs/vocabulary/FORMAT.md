# VOCABULARY.md Format

## Structure

```md
# {Vocabulary Name}

{One or two sentence description of what domain vocabulary this covers and why it exists.}

## Language

**Order**:
{A concise description of the term}
_Avoid_: Purchase, transaction

**Invoice**:
A request for payment sent to a customer after delivery.
_Avoid_: Bill, payment request

**Customer**:
A person or organization that places orders.
_Avoid_: Client, buyer, account

## Relationships

- An **Order** produces one or more **Invoices**
- An **Invoice** belongs to exactly one **Customer**
- An **Order** references a [**Customer**](../../customer/VOCABULARY.md)

## Example dialogue

> **Dev:** "When a **Customer** places an **Order**, do we create the **Invoice** immediately?"
> **Domain expert:** "No — an **Invoice** is only generated once a **Fulfillment** is confirmed."

## Flagged ambiguities

- "account" was used to mean both **Customer** and **User** — resolved: these are distinct concepts.
```

## Rules

- **Be opinionated.** When multiple words exist for the same concept, pick the best one and list the others as aliases to avoid.
- **Flag conflicts explicitly.** If a term is used ambiguously, call it out in "Flagged ambiguities" with a clear resolution.
- **Keep definitions tight.** One sentence max. Define what it IS, not what it does.
- **Show relationships.** Use bold term names and express cardinality where obvious. For terms
  defined in another vocabulary scope, link the term inline to that scope's `VOCABULARY.md`:
  `An **Order** references a [**Customer**](../../customer/docs/vocabulary/VOCABULARY.md)`.
- **Architectural concepts only — no implementation details.** Struct names,
  field names, function names, clients, packages, and other code-level
  identifiers do not belong in the vocabulary. Before adding a term, ask: is
  this a concept that could mean something different across system or team
  boundaries? If the name is only important in the implementation itself, it doesn't
  belong here.
- **Top-down, not bottom-up.** Vocabulary exists to anchor shared meaning for
  terms that travel across boundaries — between services, teams, or external
  systems. It is not a code glossary. A term earns an entry when its
  interpretation inside this repo or package must stay consistent despite
  different meanings it may carry elsewhere. Defining what a struct does is
  documentation; defining what "cancellation" means in this domain is
  vocabulary.
- **Group terms under subheadings** when natural clusters emerge. If all terms belong to a single cohesive area, a flat list is fine.
- **Write an example dialogue.** A conversation between a dev and a domain expert that demonstrates how the terms interact naturally and clarifies boundaries between related concepts.
- Relationships must reference other md documents.  They cannot reference
  arbitrary code or concepts.

## File placement

Create files lazily — only when there is something to write. Place each file at the
lowest directory scope where it applies. Root-level `VOCABULARY.md` is only appropriate
when terms are truly global — shared across every package in the repo. When in doubt,
prefer the narrower scope.

**Single scope:** One `VOCABULARY.md` at the repo root.

**Multiple scopes:** A `VOCABULARY.md` at any subdirectory root introduces or extends
vocabulary with details unique to that directory.

```
/
├── VOCABULARY.md                    ← system-wide terms
└── src/
    ├── ordering/
    │   └── VOCABULARY.md            ← ordering-specific terms
    └── billing/
        └── VOCABULARY.md
```

Infer which structure applies:

- If a `VOCABULARY.md` exists, read it.
- If it does not exist, create one lazily when the first term is resolved.
- When the discussion requires a related vocabulary scope, follow markdown links in
  `## Relationships` lazily — only load what the current topic actually needs.

When multiple vocabulary files exist, infer which one the current topic relates to. If unclear, ask.

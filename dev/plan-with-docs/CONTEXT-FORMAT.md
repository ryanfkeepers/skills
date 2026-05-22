# CONTEXT.md Format

## Structure

```md
# {Context Name}

{One or two sentence description of what this context is and why it exists.}

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
- An **Order** references a [**Customer**](../../customer/docs/context/CONTEXT.md)

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
  defined in another context, link the term inline to that context's `CONTEXT.md`:
  `An **Order** references a [**Customer**](../../customer/docs/context/CONTEXT.md)`.
- **Only include terms specific to this project's context.** General programming concepts (timeouts, error types, utility patterns) don't belong even if the project uses them extensively. Before adding a term, ask: is this a concept unique to this context, or a general programming concept? Only the former belongs.
- **Group terms under subheadings** when natural clusters emerge. If all terms belong to a single cohesive area, a flat list is fine.
- **Write an example dialogue.** A conversation between a dev and a domain expert that demonstrates how the terms interact naturally and clarifies boundaries between related concepts.

## Single vs multi-context repos

**Single context:** One `/docs/context/CONTEXT.md` at the repo root.

**Multiple contexts:** A `/docs/context/CONTEXT.md` at any subdirectory introduces or extends contexts with details that are unique to that directory.

The skill infers which structure applies:

- If a `CONTEXT.md` exists, read it to find its contents.
- If it does not exist, create a root `CONTEXT.md` lazily when the first term is resolved.
- When the discussion requires a related context, follow markdown links in `## Relationships`
  lazily — only load what the current topic actually needs.

When multiple contexts exist, infer which one the current topic relates to. If unclear, ask.

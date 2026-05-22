# Code Review Skill

Vocabulary for the `code-review` skill and how its review axes are
defined. Keeps axis boundaries unambiguous when writing or extending
the skill.

## Language

### Review axes

**Correctness**:
Whether the code is right — logic, error handling, edge cases,
invariants, security, and whether tests assert correct behavior.
_Avoid_: quality, soundness

**Standards**:
Whether the code is idiomatic and consistent with the project —
naming, style, abstractions, documentation, and whether tests exist
per project convention.
_Avoid_: quality, conventions, style (alone)

**Spec**:
Whether the code does what was asked — alignment with the
originating issue, PRD, or spec document when one exists; alignment
with established project documents (CONTEXT.md, INVARIANTS.md, ADRs)
when no spec source is available.
_Avoid_: requirements, intent

**Spec source**:
The originating artifact that describes what a change should do —
an issue, PRD, or spec document. Looked up before any sub-agents
are spawned; if none is found the reviewer asks the user. Absence
of a spec source is a valid state, not an error.
_Avoid_: issue, ticket, requirements doc (use spec source)

### Tests

**Test logic**:
The assertions and scenarios inside a test — reviewed under
**Correctness**, because a test can enshrine a bug.
_Avoid_: test correctness

**Test coverage**:
Whether tests exist for new behavior — reviewed under **Standards**,
because coverage expectations are a project convention.
_Avoid_: test presence

### Finding categories

**Critical** (Correctness): a bug, security hole, or edge case that
will cause incorrect behavior. Blocking.

**Conflicts** (Standards): code that directly violates a documented
standard — naming, convention, or architectural decision.

**Incorrect** (Spec): behavior that contradicts what the spec asked
for.

**Missing** (Spec): a requirement in the spec that is not implemented.

**Confusion** (Standards, Spec): code or behavior that is ambiguous
or misleading against the standard or spec, without being a clear
violation.

**Suggestions** (Correctness, Standards): non-blocking improvements
worth considering.

**Nits** (Correctness): minor, low-priority correctness concerns.

**Edge case** (Spec): a scenario not covered by the spec that the
implementation may handle incorrectly or not at all.

## Relationships

- **Correctness** includes **Test logic**
- **Standards** includes **Test coverage**
- **Spec** is independent of both — a change can pass Correctness
  and Standards while implementing the wrong thing

## Example dialogue

> **Dev:** "The test is passing but the output looks wrong — which
> axis is that?"
> **Expert:** "**Correctness** — the test is enshrining a bug. That's
> **Test logic**, not **Test coverage**."

> **Dev:** "There are no tests for the new endpoint."
> **Expert:** "**Standards** — missing **Test coverage** per project
> convention."

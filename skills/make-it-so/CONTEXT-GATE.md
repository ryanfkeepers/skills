# Context Gate

Sub-agents cannot see this session's context. They read files. Before dispatching any
sub-agent, verify CONTEXT.md and INVARIANTS.md together cover all five areas below.

## Sufficiency checklist

- [ ] **Vocabulary** — key domain terms defined (entities, aggregates, operations). A
      reader unfamiliar with the domain could identify the correct noun for a concept.
- [ ] **Architectural invariants** — ordering, ownership, thread safety, lifecycle
      constraints, initialization order. What must always be true?
- [ ] **Error handling patterns** — how errors are wrapped, propagated, and logged in
      this module. Are raw errors returned? `cluerr.Stack`? Wrapped with context?
- [ ] **Test conventions** — table test shape (`testCases`, `for _, test := range`),
      naming, fixture patterns, mock vs real dependencies.
- [ ] **Module quirks** — non-obvious patterns, workarounds, external constraints a
      new implementer would not guess from the code alone.
- [ ] **Behavioral examples** — the plan contains at least one concrete input/output
      pair or named edge case per exported behavior. Vague descriptions ("process items")
      do not satisfy this. Examples must be precise enough that Phase 3 and Phase 5a
      can write assertions without inference.

## What to do when a checkbox fails

Ask the user the corresponding question. Write the answer into CONTEXT.md or
INVARIANTS.md (whichever fits). Do not carry answers only in conversation context.

| Missing | Question |
|---------|----------|
| Vocabulary | "What domain terms should a new contributor know to understand this feature?" |
| Invariants | "What must always be true about [entity/system]? What breaks silently if violated?" |
| Error handling | "How are errors handled here — wrapped, logged, returned raw?" |
| Test conventions | "What test patterns does this codebase expect? Table tests? Mocks?" |
| Quirks | "Anything non-obvious about this module that would trip up an implementer?" |
| Behavioral examples | "For each exported behavior, give me a concrete example: input, expected output, and any named edge cases (nil input, empty list, duplicate key, etc.)." |

The gate passes when all five checkboxes are satisfied from the written docs.

## Example: insufficient vs sufficient

**Insufficient INVARIANTS.md entry:**
> The cache must be consistent.

**Sufficient entry:**
> `Cache.mu` must be held for all reads and writes to `Cache.entries`.
> `getEntry` and `setEntry` are the only access points; any new accessor must acquire
> the lock. Violations produce silent data races — the race detector won't catch them
> in tests because the test fixture uses a single goroutine.

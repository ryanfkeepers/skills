# Phase 1 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are a scaffolding agent. Your job: declare the public contract for `[FEATURE]`.

Do NOT implement unexported logic. Do NOT write real implementations — stub bodies or
`panic("not implemented")` only. A Phase 2 agent will implement the internals.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Existing code (read before touching anything)

[EXISTING_FILE_PATHS]
<!-- List file paths. The agent reads them directly. -->

## Domain context

[CONTEXT_MD_EXCERPT]

## Invariants

[INVARIANTS_MD_EXCERPT]

## Primary scope

Work is centered in `[SCOPE_DIR]`. Expected files to create or modify based on the plan:

[EXPECTED_FILES]
<!-- List as a starting point, not a ceiling. The agent may create additional files
     within the scope directory if the implementation requires it. -->

## What to produce

1. Exported types, interfaces, and structs: `[INTERFACES]`
2. Exported method signatures with stub bodies
3. A contract test file — one test per exported behavior, using `testCases` table pattern:
   ```go
   testCases := []struct{ ... }{ ... }
   for _, test := range testCases { ... }
   ```
   Tests WILL fail (no implementation yet). That is expected and correct.
   Write tests so they pass after Phase 2 with minimal changes to the test file itself.

## Constraints

- Do NOT implement unexported helpers or core logic
- Do NOT modify existing exported signatures outside the new surface
- Do NOT run jj, git, or any VCS command
- Stay within `[SCOPE_DIR]`. If you determine you need to touch something outside it,
  state what and why before doing so.

## Done when

- All exports declared; `go build ./[scope]` (or equivalent) succeeds
- Contract test file compiles
- Tests fail for the right reason: missing implementation, not compilation errors

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

## Primary scope

Work is centered in `[SCOPE_DIR]`. Expected files to create or modify based on the plan:

[EXPECTED_FILES]
<!-- List as a starting point, not a ceiling. The agent may create additional files
     within the scope directory if the implementation requires it. -->

## What to produce

1. `contract.go` — all exported interfaces and type declarations: `[INTERFACES]`
   This file is permanent. Phase 4 will not modify it. It is the source for mock
   generation and the reference for the adversarial unit test phase.
2. Stub `.go` files — exported function and method signatures with `panic("not
   implemented")` bodies. Phase 4 will replace the stub bodies with real implementations.

Do NOT write any test files.

## Constraints

- Do NOT implement unexported helpers or core logic
- Do NOT modify existing exported signatures outside the new surface
- Do NOT run jj, git, or any VCS command — all changes must stay in the
  current working-copy revision; never commit, squash, or create a new change
- Stay within `[SCOPE_DIR]`. If you determine you need to touch something outside it,
  state what and why before doing so.

## Done when

- `contract.go` exists with all exported interfaces and type declarations
- All exported functions and methods have stub bodies; `go build ./[scope]` succeeds
- No test files produced

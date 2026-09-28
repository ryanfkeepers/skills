# Phase 1 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching — never dispatch with unfilled placeholders.

---

You are a scaffolding agent. Job: declare the public contract for `[FEATURE]`.

Do NOT implement unexported logic. Do NOT write real implementations — stub bodies or
`panic("not implemented")` only. Phase 2 agent implements the internals.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Existing code (read before touching anything)

[EXISTING_FILE_PATHS]
<!-- List file paths — agent reads them directly. -->

## Primary scope

Work centers in `[SCOPE_DIR]`. Expected files to create or modify per plan:

[EXPECTED_FILES]
<!-- Starting point, not ceiling — agent may create additional files within scope
     dir if implementation requires it. -->

## What to produce

1. `contract.go` — all exported interfaces and type declarations: `[INTERFACES]`
   Permanent file. Phase 2 won't modify it — source for mock generation, reference
   for the adversarial unit test phase.
2. Stub `.go` files — exported function and method signatures with `panic("not
   implemented")` bodies. Phase 2 replaces stub bodies with real implementations.

Do NOT write test files.

## Constraints

- Do NOT implement unexported helpers or core logic
- Do NOT modify existing exported signatures outside the new surface
- Do NOT run jj, git, or any VCS command — changes stay in current working-copy
  revision; never commit, squash, or create a new change
- Stay within `[SCOPE_DIR]`. Need to touch something outside it → state what and
  why before doing so.

## Done when

- `contract.go` exists with all exported interfaces and type declarations
- All exported functions and methods have stub bodies; `go build ./[scope]` succeeds
- No test files produced

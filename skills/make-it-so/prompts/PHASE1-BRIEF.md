# Phase 1 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are a scaffolding agent. Job: declare public contract for `[FEATURE]`.

Do NOT implement unexported logic. Do NOT write real implementations — stub
bodies or `panic("not implemented")` only. Phase 4 agent implements internals.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Existing code (read before touching anything)

[EXISTING_FILE_PATHS]
<!-- List file paths. Agent reads them directly. -->

## Primary scope

Work centered in `[SCOPE_DIR]`. Expected files to create or modify per plan:

[EXPECTED_FILES]
<!-- List as starting point, not ceiling. Agent may create additional files
     within scope directory if implementation requires it. -->

## What to produce

1. `contract.go` — all exported interfaces + type declarations: `[INTERFACES]`
   Permanent file. Phase 4 will not modify it. Source for mock generation +
   reference for adversarial unit test phase.
2. Stub `.go` files — exported function/method signatures with
   `panic("not implemented")` bodies. Phase 4 replaces stub bodies with real
   implementations.

Do NOT write any test files.

## Constraints

- Do NOT implement unexported helpers or core logic
- Do NOT modify existing exported signatures outside new surface
- Do NOT run jj, git, or any VCS command — all changes stay in current
  working-copy revision; never commit, squash, or create new change
- Stay within `[SCOPE_DIR]`. If touching something outside it needed, state
  what and why before doing so.

## Done when

- `contract.go` exists with all exported interfaces + type declarations
- All exported functions/methods have stub bodies; `go build ./[scope]` succeeds
- No test files produced

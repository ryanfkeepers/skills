# Phase 4 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an implementation agent. Phases 1–3 are complete. Your job: implement the logic
for `[FEATURE]` and generate mocks from the exported interfaces.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 scaffolding — read and build on

[PHASE1_FILES]
<!-- List file paths. The agent reads them directly. These contain the exported
     interfaces (contract.go) and stub bodies to replace. -->

## Primary scope

Work is centered in `[SCOPE_DIR]`.

## Mock generation

Generate mocks for the following interfaces in `contract.go`:

[MOCK_INTERFACES]

Write generated mock files to: `[MOCK_OUTPUT_DIR]`

Use `go generate` (or equivalent) if the project has a `//go:generate` directive.
Otherwise generate mocks directly with the project's mock tool.

## Invariants

[INVARIANTS_MD_EXCERPT]

## What to produce

1. Implementations replacing all `panic("not implemented")` stubs
2. Unexported helpers and core logic as needed
3. Mock files generated from `contract.go` interfaces at `[MOCK_OUTPUT_DIR]`

Do NOT write any test files — unit tests are produced in a separate phase.

## Constraints

- Do NOT modify `contract.go` — it is locked after Phase 1
- Do NOT modify any test files
- Do NOT run jj, git, or any VCS command — all changes must stay in the
  current working-copy revision; never commit, squash, or create a new change
- Stay within `[SCOPE_DIR]`. If you determine you need to touch something outside it,
  state what and why before doing so.
- Follow error handling conventions from the invariants: `[ERROR_HANDLING_SUMMARY]`

## Done when

- All `panic("not implemented")` stubs replaced with real implementations
- Mock files generated and present at `[MOCK_OUTPUT_DIR]`
- `go build ./[scope]` (or equivalent) passes: `[BUILD_COMMAND]`
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

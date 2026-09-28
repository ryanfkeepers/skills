# Phase 2 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching — never dispatch with unfilled placeholders.

---

You are an implementation agent. Phase 1 scaffolding complete. Job: implement logic
for `[FEATURE]`, generate mocks from the exported interfaces.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 scaffolding — read and build on

[PHASE1_FILES]
<!-- List file paths — agent reads them directly. Contains exported interfaces
     (contract.go) and stub bodies to replace. -->

## Primary scope

Work centers in `[SCOPE_DIR]`.

## Mock generation

Generate mocks for these interfaces in `contract.go`:

[MOCK_INTERFACES]

Write generated mock files to: `[MOCK_OUTPUT_DIR]`

Use `go generate` (or equivalent) if project has `//go:generate` directive. Otherwise
generate mocks directly with project's mock tool.

## What to produce

1. Implementations replacing all `panic("not implemented")` stubs
2. Unexported helpers and core logic as needed
3. Mock files generated from `contract.go` interfaces at `[MOCK_OUTPUT_DIR]`

Do NOT write test files — unit tests produced in separate phase.

## Constraints

- Do NOT modify `contract.go` — locked after Phase 1
- Do NOT modify test files
- Do NOT run jj, git, or any VCS command — changes stay in current working-copy
  revision; never commit, squash, or create a new change
- Stay within `[SCOPE_DIR]`. Need to touch something outside it → state what and
  why before doing so.
- Follow codebase's existing error handling conventions: `[ERROR_HANDLING_SUMMARY]`

## Done when

- All `panic("not implemented")` stubs replaced with real implementations
- Mock files generated and present at `[MOCK_OUTPUT_DIR]`
- `go build ./[scope]` (or equivalent) passes: `[BUILD_COMMAND]`
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

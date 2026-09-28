# Phase 4 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an implementation agent. Phases 1–3 complete. Job: implement logic for
`[FEATURE]` and generate mocks from exported interfaces.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 scaffolding — read and build on

[PHASE1_FILES]
<!-- List file paths. Agent reads them directly. These contain exported
     interfaces (contract.go) and stub bodies to replace. -->

## Primary scope

Work centered in `[SCOPE_DIR]`.

## Mock generation

Generate mocks for these interfaces in `contract.go`:

[MOCK_INTERFACES]

Write generated mock files to: `[MOCK_OUTPUT_DIR]`

Use `go generate` (or equivalent) if project has a `//go:generate` directive.
Otherwise generate mocks directly with project's mock tool.

## What to produce

1. Implementations replacing all `panic("not implemented")` stubs
2. Unexported helpers and core logic as needed
3. Mock files generated from `contract.go` interfaces at `[MOCK_OUTPUT_DIR]`

Do NOT write any test files — unit tests produced in a separate phase.

## Constraints

- Do NOT modify `contract.go` — locked after Phase 1
- Do NOT modify any test files
- Do NOT run jj, git, or any VCS command — all changes stay in current
  working-copy revision; never commit, squash, or create new change
- Stay within `[SCOPE_DIR]`. If touching something outside it needed, state
  what and why before doing so.
- Follow codebase's existing error handling conventions: `[ERROR_HANDLING_SUMMARY]`

## Done when

- All `panic("not implemented")` stubs replaced with real implementations
- Mock files generated and present at `[MOCK_OUTPUT_DIR]`
- `go build ./[scope]` (or equivalent) passes: `[BUILD_COMMAND]`
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

# Phase 3b Sub-Agent Brief Template — Coverage Unit Tests

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are a unit test coverage author. Phase 3a adversarial tests passed. Your job: add
new test functions for coverage gaps — internal logic, error paths, and edge cases not
already covered by Phase 3a.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 stub content (for signature reference)

```go
[PHASE1_STUB_CONTENT]
```

## Implementation files — read to understand internals

[IMPLEMENTATION_FILES]
<!-- List paths. Read these to identify internal logic, error paths, and edge cases
     that warrant coverage but are not in the Phase 3a tests. -->

## Phase 3a test file — read only, do not modify

[PASS1_TEST_FILES]
<!-- Read to understand what is already covered. Do NOT modify any existing test case,
     test function, or assertion. Only add new test functions. -->

## Mock files

[MOCK_FILES]

## Domain context and invariants

[INVARIANTS_MD_EXCERPT]

## What to produce

New test functions appended to (or added alongside) the Phase 3a test file, covering:
1. Internal helper logic not exercised by the exported contract tests
2. Error paths — every `return err` branch in the implementation
3. Edge cases visible from the implementation that the behavioral examples don't cover

Use the same `testCases` table pattern as Phase 3a tests.

## Constraints

- Do NOT modify any existing Phase 3a test function or assertion — add only
- Do NOT run jj, git, or any VCS command — all changes must stay in the
  current working-copy revision; never commit, squash, or create a new change
- Stay within `[SCOPE_DIR]`
- Follow error handling conventions: `[ERROR_HANDLING_SUMMARY]`

## Done when

- New test functions added
- All tests pass (Phase 3a + new): `[TEST_COMMAND]`
- No existing Phase 3a test cases modified

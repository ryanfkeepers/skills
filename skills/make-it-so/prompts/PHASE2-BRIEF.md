# Phase 2 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an E2E smoke test author. Phase 1 scaffolding complete. Job: write E2E
smoke tests for `[FEATURE]` verifying feature is reachable + functional at a
live deployment boundary.

You CANNOT run these tests — they require `[ENVIRONMENT_REQUIREMENTS]`. Don't
attempt to execute them. Write them correct + ready for user to run with:

```
[E2E_TEST_COMMAND]
```

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 scaffolding — read for API shape

[PHASE1_SCAFFOLD_FILES]
<!-- List paths. Agent reads them to understand what feature exposes. -->

## E2E test framework and patterns

[E2E_TEST_FRAMEWORK_AND_PATTERNS]
<!-- Describe framework, setup/teardown conventions, shared test helpers.
     Include example from existing E2E test if available — most important context. -->

## E2E test directory

`[E2E_TEST_DIR]`

Create test files here. If existing E2E test files relevant to feature, read
them before writing new ones.

## What to produce

E2E smoke tests covering:
1. Fundamental happy path for each entry point feature exposes
2. Basic reachability — service responds, connections succeed
3. Do NOT write complex behavioral casework — belongs in integration tests

Each test file must include at top:
```
// Run with: [E2E_TEST_COMMAND]
// Requires: [ENVIRONMENT_REQUIREMENTS]
```

## Constraints

- Do NOT run any test commands
- Do NOT run jj, git, or any VCS command — all changes stay in current
  working-copy revision; never commit, squash, or create new change
- Do NOT change implementation or scaffolding files
- Keep tests minimal — smoke coverage only, not behavioral verification
- Stay within `[E2E_TEST_DIR]`

## Done when

- E2E smoke test files written and compile cleanly
- Run command + environment requirements documented in each file
- Tests scoped to reachability + fundamental happy paths only

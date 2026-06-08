# Phase 2 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an E2E smoke test author. Phase 1 scaffolding is complete. Your job: write E2E
smoke tests for `[FEATURE]` that verify the feature is reachable and functional at a
live deployment boundary.

You CANNOT run these tests — they require `[ENVIRONMENT_REQUIREMENTS]`. Do not attempt
to execute them. Write them so they are correct and ready for the user to run with:

```
[E2E_TEST_COMMAND]
```

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Phase 1 scaffolding — read for API shape

[PHASE1_SCAFFOLD_FILES]
<!-- List paths. The agent reads them to understand what the feature exposes. -->

## E2E test framework and patterns

[E2E_TEST_FRAMEWORK_AND_PATTERNS]
<!-- Describe the framework, setup/teardown conventions, and any shared test helpers.
     Include an example from an existing E2E test if available — most important context. -->

## E2E test directory

`[E2E_TEST_DIR]`

Create test files here. If existing E2E test files are relevant to the feature, read
them before writing new ones.

## Domain context

[CONTEXT_MD_EXCERPT]

## What to produce

E2E smoke tests covering:
1. The fundamental happy path for each entry point the feature exposes
2. Basic reachability — the service responds, connections succeed
3. Do NOT write complex behavioral casework — that belongs in integration tests

Each test file must include at the top:
```
// Run with: [E2E_TEST_COMMAND]
// Requires: [ENVIRONMENT_REQUIREMENTS]
```

## Constraints

- Do NOT run any test commands
- Do NOT run jj, git, or any VCS command
- Do NOT change implementation or scaffolding files
- Keep tests minimal — smoke coverage only, not behavioral verification
- Stay within `[E2E_TEST_DIR]`

## Done when

- E2E smoke test files written and compile cleanly
- Run command and environment requirements documented in each file
- Tests are scoped to reachability and fundamental happy paths only

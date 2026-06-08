# Phase 3 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching.

---

You are an integration test author. Phases 1 and 2 are complete. Your job: write
integration and E2E tests for `[FEATURE]`.

You CANNOT run these tests — they require `[ENVIRONMENT_REQUIREMENTS]`. Do not attempt
to execute them. Write them so they are correct and ready for the user to run with:

```
[INTEGRATION_TEST_COMMAND]
```

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Implementation files — read before writing tests

[IMPLEMENTATION_FILE_PATHS]
<!-- List paths. The agent reads them directly. -->

## Integration test framework and patterns

[INTEGRATION_TEST_PATTERNS]
<!-- Describe the framework, fixture patterns, setup/teardown conventions, and any
     shared test helpers. Include an example from an existing integration test if
     available — this is the most important context for the sub-agent. -->

## Integration test directory

`[INTEGRATION_TEST_DIR]`

Create test files here. If existing integration test files are relevant to the feature,
read them before writing new ones.

## Domain context

[CONTEXT_MD_EXCERPT]

## Invariants

[INVARIANTS_MD_EXCERPT]

## What to produce

Integration and E2E tests covering:
1. The happy path for each feature behavior in the plan
2. Key failure and error cases the unit tests cannot cover (cross-service failures,
   auth failures, persistence, etc.)
3. Any behavior that depends on the interaction between components

Each test must include a comment at the top of the file:
```
// Run with: [INTEGRATION_TEST_COMMAND]
// Requires: [ENVIRONMENT_REQUIREMENTS]
```

## Constraints

- Do NOT run any test commands
- Do NOT run jj, git, or any VCS command
- Do NOT change implementation files from Phases 1 or 2
- Stay within `[INTEGRATION_TEST_DIR]`. If you determine you need to touch something
  outside it, state what and why before doing so.

## Done when

- Integration test files written and compile cleanly (if checkable without running)
- Tests follow the patterns in `[INTEGRATION_TEST_PATTERNS]`
- Run command and environment requirements documented in each test file

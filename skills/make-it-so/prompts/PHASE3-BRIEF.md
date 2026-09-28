# Phase 3 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an integration test author. Phase 1 scaffolding complete; implementation
has NOT started. Job: write behavioral integration tests for `[FEATURE]`
grounded in plan's behavioral examples.

These tests are the independent behavioral spec for this feature. Write them
from plan + behavioral examples — not from guesses about how implementation
will work.

You CANNOT run these tests — they require `[ENVIRONMENT_REQUIREMENTS]`. Don't
attempt to execute them. Write them correct + ready to run with:

```
[INTEGRATION_TEST_COMMAND]
```

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Behavioral examples (from the plan — your ground truth)

[BEHAVIORAL_EXAMPLES]
<!-- Explicit input/output pairs + edge cases from plan.
     Every behavioral example here must have a corresponding test case. -->

## Phase 1 scaffolding — read for API shape only

[PHASE1_SCAFFOLD_FILES]
<!-- List paths. Read to understand API surface. Do NOT infer behavioral
     assertions from stub bodies — derive assertions from behavioral examples
     above, not from what scaffolding suggests implementation might do. -->

## Integration test framework and patterns

[INTEGRATION_TEST_FRAMEWORK_AND_PATTERNS]
<!-- Describe framework, fixture patterns, setup/teardown conventions, shared
     test helpers. Include example from existing integration test if
     available — most important context. -->

## Integration test directory

`[INTEGRATION_TEST_DIR]`

Create test files here. If existing integration test files relevant to
feature, read them before writing new ones.

## What to produce

Integration tests covering:
1. Every behavioral example in plan — one test case per example, minimum
2. Key failure and error cases crossing service or component boundaries
3. Any behavior depending on interaction between components

Each test must derive assertions from behavioral examples above, not from
inference about implementation. Each test file must include at top:
```
// Run with: [INTEGRATION_TEST_COMMAND]
// Requires: [ENVIRONMENT_REQUIREMENTS]
```

## Constraints

- Do NOT run any test commands
- Do NOT run jj, git, or any VCS command — all changes stay in current
  working-copy revision; never commit, squash, or create new change
- Do NOT change scaffolding files from Phase 1
- Do NOT derive assertions from stub implementations — use behavioral examples only
- Stay within `[INTEGRATION_TEST_DIR]`

## Done when

- Integration test files written and compile cleanly
- Every behavioral example from plan has ≥1 corresponding test case
- Assertions grounded in plan's behavioral examples, not inferred from stubs
- Run command + environment requirements documented in each file

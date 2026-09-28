# Phase 5a Sub-Agent Brief Template — Adversarial Unit Tests

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled placeholders.

---

You are an adversarial unit test author. Job: write unit tests for `[FEATURE]`
derived from plan's behavioral examples — NOT from implementation.

Phase 1 stub content below is your only view of the code. You have NOT been
given implementation files. Do not attempt to read any `.go` files outside
mock paths listed. Derive every assertion from behavioral examples in plan.

## Feature

[FEATURE]

## Plan and behavioral examples

[PLAN_EXCERPT]

### Behavioral examples (your ground truth for assertions)

[BEHAVIORAL_EXAMPLES]
<!-- Every test assertion must trace back to one of these examples.
     Do not invent assertions based on what seems reasonable. -->

## Phase 1 stub content (verbatim — your only view of the API)

```go
[PHASE1_STUB_CONTENT]
```

Use this to understand exported signatures, types, interfaces. Do not infer
behavioral assertions from stub bodies — they all panic.

## Mock files (the only implementation files you may read)

[MOCK_FILES]
<!-- List paths. Read to understand mock constructor and method signatures.
     Do not read any other implementation files. -->

## What to produce

Write unit tests to `[TEST_FILE_PATH]` using `testCases` table pattern:
```go
testCases := []struct{ ... }{ ... }
for _, test := range testCases { ... }
```

One test function per exported behavior. Each test case must correspond to a
behavioral example in plan or a named edge case. Every assertion must be
derivable from plan — not from inference about implementation.

Then run tests and report results.

## Constraints

- Do NOT read any `.go` files other than mock files listed above
- Do NOT modify assertions to match implementation behavior if tests fail —
  report failures and stop
- Do NOT run jj, git, or any VCS command — all changes stay in current
  working-copy revision; never commit, squash, or create new change
- Stay within `[SCOPE_DIR]`

## Done when

- Test file written at `[TEST_FILE_PATH]`
- Tests run: `[TEST_COMMAND]`
- Results reported — pass or fail, with full output

## On failure

If any test fails: output full failure output and stop. Do NOT modify
assertions or implementation. Parent will surface failures to user.

# Phase 6 Sub-Agent Brief Template — Integration + E2E Run

Fill every `[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled
placeholders. Omit the block for any suite that is not being run.

---

You are a test runner. Implementation and unit tests are complete. Job: execute
the E2E smoke and integration suites for `[FEATURE]` and report results
verbatim. You do not edit files and you do not fix failures.

## Environment

[ENVIRONMENT_SETUP]
<!-- Documented setup/teardown steps (project skill, just/make target, doc
     section) and the designated safe target. Never target production. -->

## Suites to run

E2E smoke:
```
[E2E_TEST_COMMAND]
```

Integration:
```
[INTEGRATION_TEST_COMMAND]
```

## Test files (to map failures to test names)

[TEST_FILES]

## What to produce

For each suite, in order (E2E first, then integration):
1. Run the command exactly as given. Run to completion; do not cut it short.
2. Record: command, exit code, passed/failed/skipped counts.
3. For every failure: test name, full failure output, and a classification with
   a one-line reason:
   - `environment` — connection refused, auth failure, missing service or
     timeout before the feature is reached
   - `test-defect` — the test's assertion or setup contradicts the plan
   - `impl-defect` — the implementation diverges from the plan's behavior

If the setup steps fail, report that as an `environment` failure for the
affected suite and stop that suite. Run the documented teardown even when a
suite fails.

## Constraints

- Do NOT modify any file — source, tests, config, or fixtures
- Do NOT retry a failing test to get it to pass, and do NOT skip, tag-exclude,
  or filter tests to hide failures. One re-run is allowed only to classify a
  suspected flake; report both outcomes
- Do NOT print secret values (tokens, keys, connection strings); report only
  whether a required variable is set
- Do NOT run against any environment other than the one in Environment above
- Do NOT run jj, git, or any VCS command

## Done when

- Every listed suite executed to completion, or reported as an environment
  failure with the failing setup step
- Per-suite command, exit code, and counts reported
- Every failure includes full output and a classification

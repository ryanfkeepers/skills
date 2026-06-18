---
name: unit-test
description: >-
  Run unit tests for the current repo, fix broken test code, and confirm
  all tests pass. Use when asked to run tests, fix failing tests, clean up
  test failures, or make the test suite pass.
---

# Unit Test

Run tests, fix broken test code, confirm clean.

**Scope:** fix test code only — assertions, fixtures, mocks, test helpers.
Never modify production code to make tests pass. If a failure indicates a
real bug, stop and report it.

## Step 1 — Detect repo type

Check root-level indicator files for the applicable test runner.

### Task runners (check first)

| File | Commands to try |
|------|-----------------|
| `Makefile` | `make test` |
| `Justfile` / `justfile` | `just test` |
| `Taskfile.yml` / `Taskfile.yaml` | `task test` |

If a task runner is present, list its targets and prefer task-runner commands
when a test target exists — they encode the project's exact configuration.

### Language indicators

| File | Language | Test command |
|------|----------|--------------|
| `go.mod` | Go | `gt` (alias), `go test ./...` |
| `package.json` | Node / TS | `npx jest`, `npx vitest run`, `npm test` |
| `pyproject.toml` or `setup.py` | Python | `pytest` |
| `Gemfile` | Ruby | `bundle exec rspec` |

Multiple indicators can be present — run all detected test suites.

## Step 2 — Initial test run

Run all detected test suites and read the full output before touching code.
This establishes the full scope of failures.

## Step 3 — Classify each failure

For each failing test, decide before touching anything:

- **Stale test** — assertion no longer matches the current (correct) behavior.
  Fix the test.
- **Broken test infra** — bad fixture, wrong mock, broken helper. Fix the
  test code.
- **Production bug** — test is correct; the implementation is wrong. **Stop.**
  Report the bug and the affected test. Do not update the assertion to match
  broken output.

## Step 4 — Fix test code

Apply fixes only to test files, fixtures, mocks, and test helpers.
Make the minimum change required. Do not touch production code.

## Step 5 — Re-run to confirm clean

Re-run all test suites from Step 2. Target: zero failures.

If failures remain, fix and re-run until output is clean.

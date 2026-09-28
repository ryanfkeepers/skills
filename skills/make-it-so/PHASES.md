# Phase Instructions

## Phase 1: Scaffolding

Dispatch Phase 1 sub-agent: [prompts/PHASE1-BRIEF.md](prompts/PHASE1-BRIEF.md).

Fill every placeholder:
- `[FEATURE]` — name + one-line summary
- `[PLAN_EXCERPT]` — relevant plan section verbatim, incl. behavioral examples
- `[EXISTING_FILE_PATHS]` — existing files agent should read for context
- `[SCOPE_DIR]` — package/dir bounding work (e.g. `internal/foo/`)
- `[EXPECTED_FILES]` — files plan anticipates creating/modifying, as orientation
- `[INTERFACES]` — exported types, interfaces, method signatures to declare

**Phase 1 done when:**
- `contract.go` exists with all exported interfaces + type declarations
- Stub `.go` files exist, `panic("not implemented")` bodies for all exported
  functions/methods
- `go build ./[scope]` (or equivalent) succeeds
- No test files produced

**Parent action after Phase 1 returns:**
- Read all `.go` files produced in `[SCOPE_DIR]`. Store in session context —
  this is the Phase 1 snapshot, used verbatim in Phase 5a brief.
- Verify: exports match plan exactly? If not, fix brief, re-dispatch before
  proceeding.

---

## Phase 2: E2E Smoke Tests

**Before dispatching — test infra check:**

Inspect repo for existing E2E + integration test infra (dirs, build tags, test
helpers, CI config). Apply rules:

- **Both exist** → dispatch Phase 2 (E2E) + Phase 3 (integration). Default path.
- **Only E2E exists** → dispatch Phase 2; skip Phase 3.
- **Only integration exists** → skip Phase 2; dispatch Phase 3. Don't leave
  feature untested because one tier is missing.
- **Neither exists** → stop, ask user which test type to write before
  proceeding. Don't guess or skip silently.
- **User explicitly says skip a phase** → skip regardless of above. Don't skip
  the other phase unless user says so too.

Never skip both Phase 2 + Phase 3 unless user explicitly requests it.

Dispatch Phase 2 sub-agent: [prompts/PHASE2-BRIEF.md](prompts/PHASE2-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[PHASE1_SCAFFOLD_FILES]` — Phase 1 output file paths (for API shape)
- `[E2E_TEST_DIR]`, `[E2E_TEST_COMMAND]`, `[ENVIRONMENT_REQUIREMENTS]`
- `[E2E_TEST_FRAMEWORK_AND_PATTERNS]` — framework, setup/teardown, example
  from existing E2E test if available

**Phase 2 done when:**
- E2E smoke test files written + compile
- Each file documents run command + env requirements at top
- Tests cover fundamental reachability + happy-path only — no complex
  behavioral casework

**Parent check after Phase 2 returns:**
- Read test files. Do they target feature's top-level entry points?
- Collect `[E2E_TEST_COMMAND]` for Phase 7 diagram.

---

## Phase 3: Integration Tests

Dispatch Phase 3 sub-agent: [prompts/PHASE3-BRIEF.md](prompts/PHASE3-BRIEF.md).

Runs **before implementation**. Sub-agent reads Phase 1 scaffolding for API
shape, writes behavioral tests grounded in the plan's behavioral examples.
These tests are the independent behavioral spec used by Phase 6.

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]` — include behavioral examples verbatim
- `[BEHAVIORAL_EXAMPLES]` — pull behavioral examples from plan explicitly
- `[PHASE1_SCAFFOLD_FILES]` — Phase 1 output files (API shape only, not impl)
- `[INTEGRATION_TEST_DIR]`, `[INTEGRATION_TEST_COMMAND]`, `[ENVIRONMENT_REQUIREMENTS]`
- `[INTEGRATION_TEST_FRAMEWORK_AND_PATTERNS]` — framework, fixture patterns,
  example from existing integration test if available

**Phase 3 done when:**
- Integration test files written + compile
- Each plan behavioral example has ≥1 corresponding test case
- Run command + env requirements documented in each file

**Parent check after Phase 3 returns:**
- Read test files. Does each plan behavioral example have a corresponding test?

---

## Phase 4: Implementation

Dispatch Phase 4 sub-agent: [prompts/PHASE4-BRIEF.md](prompts/PHASE4-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[SCOPE_DIR]`, `[PHASE1_FILES]` — Phase 1 scaffold files to build on
- `[MOCK_INTERFACES]` — interfaces in `contract.go` to generate mocks for
- `[MOCK_OUTPUT_DIR]` — where to write generated mock files (e.g. `internal/foo/mocks/`)
- `[ERROR_HANDLING_SUMMARY]` — codebase's existing error handling conventions
- `[BUILD_COMMAND]`, `[REGRESSION_CHECK_COMMAND]`

**Phase 4 done when:**
- All `panic("not implemented")` stubs replaced with real implementations
- Mocks generated from `contract.go` interfaces (e.g. via `go generate`)
- `go build ./[scope]` passes
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

**Parent check after Phase 4 returns:**
- Run the build + regression check yourself. Don't trust the sub-agent's report.
- Verify mock files exist at `[MOCK_OUTPUT_DIR]`.
- Verify `contract.go` was NOT modified: `jj diff --no-pager contract.go`.
- Verify no files outside scope were modified: `jj diff --no-pager`, scan file list.

---

## Phase 5a: Unit Tests — Adversarial Pass

Dispatch Phase 5a sub-agent: [prompts/PHASE5A-BRIEF.md](prompts/PHASE5A-BRIEF.md).

Agent is **blind to the implementation**. Give it the Phase 1 snapshot
(captured after Phase 1) verbatim in the brief — not as file paths. It also
gets mock file paths and the plan's behavioral examples. It writes tests from
the plan, runs them, and reports results. It does NOT fix failures.

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[BEHAVIORAL_EXAMPLES]` — verbatim from the plan
- `[PHASE1_STUB_CONTENT]` — verbatim content of Phase 1 stub files (from session snapshot)
- `[MOCK_FILES]` — paths to generated mock files only
- `[SCOPE_DIR]`, `[TEST_FILE_PATH]`, `[TEST_COMMAND]`

**Phase 5a done when:**
- Test file written and run
- Results (pass or fail) reported to parent

**Parent action after Phase 5a returns:**
- If any test fails: surface all failures to the user with full test output.
  Stop. User decides whether to re-invoke Phase 4 or accept the divergence.
  No automated fix loop.
- If all tests pass: proceed to Phase 5b.

---

## Phase 5b: Unit Tests — Coverage Pass

Only run if Phase 5a passes.

Dispatch Phase 5b sub-agent: [prompts/PHASE5B-BRIEF.md](prompts/PHASE5B-BRIEF.md).

Agent reads Phase 5a test files, implementation files, and mocks. Job: add new
test functions for coverage gaps — internal logic, error paths, edge cases not
in Phase 5a. It must NEVER modify existing Phase 5a test cases.

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[PHASE1_STUB_CONTENT]` — for reference (signatures and interfaces)
- `[IMPLEMENTATION_FILES]`, `[PASS1_TEST_FILES]`, `[MOCK_FILES]`
- `[SCOPE_DIR]`, `[TEST_COMMAND]`
- `[ERROR_HANDLING_SUMMARY]`

**Phase 5b done when:**
- New test functions added for coverage gaps
- All tests (Phase 5a + new) pass

**Parent action after Phase 5b returns:**
- Diff Phase 5a test file against current state. If any existing Phase 5a test
  case was modified, reject Phase 5b output, surface the violations to the
  user, and stop.
- Run the test command yourself. Verify all tests pass before proceeding.

---

## Phase 6: Adversarial Verification

Dispatch Phase 6 verifier sub-agent:
[prompts/PHASE6-VERIFIER.md](prompts/PHASE6-VERIFIER.md).

Provide:
- The original plan verbatim
- Integration test results: "not run; pending user execution" unless the user
  ran them manually and provided output

The verifier runs `jj diff --no-pager` itself.

**Verifier checks:**
1. Spec compliance — every requirement in the plan implemented? List any gap.
2. Correctness — logic errors, nil panics, off-by-ones, missing error returns
3. Completeness — `panic("not implemented")` stubs remaining, TODOs affecting
   correctness, branches that never execute
4. Regressions — changes to shared/common code that could silently break callers
5. Test coverage — do Phase 5a tests verify the plan's behavioral examples? Do
   Phase 5b tests cover the error paths?

**On `VERIFIED`:** proceed to Phase 7.

**On `ISSUES_FOUND` (critical or moderate):**
1. Dispatch a fix sub-agent with a focused brief: the specific issue list plus
   relevant file excerpts. Scope tightly — not the full diff.
2. After fix returns, re-run the test command.
3. Re-dispatch Phase 6 with a fresh diff.
4. Repeat up to 3 total fix iterations.
5. After 3 failures: surface the remaining punch list to the user and stop.

Minor issues: record them and surface in Phase 7. Do not block on them.

---

## Phase 7: Diagram

Show the user an ASCII tree of all changes. Generate from `jj diff --stat --no-pager`.

Format:
```
project/
├── path/to/
│   ├── contract.go              [NEW] — exported interfaces
│   ├── feature.go               [NEW] — implementation
│   ├── feature_test.go          [NEW] — adversarial + coverage unit tests
│   ├── mocks/mock_feature.go    [NEW] — generated mocks
│   └── existing_file.go         [MOD] — what changed
└── integration/
    └── feature_test.go          [NEW] — behavioral integration tests

Net: +N files, M modified, ~L lines
```

If any sub-agent worked outside its expected scope, append a section listing
every instance. Collect these from each phase's output as you go — do not
reconstruct from the diff after the fact.

```
Out-of-scope work:
  Phase N — path/to/file.go: reason the agent gave
```

If Phase 6 had minor issues not fixed, append:
```
Minor findings (not blocking):
  - path/to/file.go:42 — description
```

Always append:
```
Tests written, not yet run — execute when environment is ready:
  E2E:          $ [E2E_TEST_COMMAND]
  Integration:  $ [INTEGRATION_TEST_COMMAND]
```

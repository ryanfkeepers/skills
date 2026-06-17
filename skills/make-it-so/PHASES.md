# Phase Instructions

## Phase 1: Scaffolding

Dispatch a Phase 1 sub-agent using [prompts/PHASE1-BRIEF.md](prompts/PHASE1-BRIEF.md).

Fill every placeholder:
- `[FEATURE]` — name and one-line summary
- `[PLAN_EXCERPT]` — the relevant plan section verbatim, including behavioral examples
- `[EXISTING_FILE_PATHS]` — paths of existing files the agent should read for context
- `[SCOPE_DIR]` — the package or directory that bounds the work (e.g. `internal/foo/`)
- `[EXPECTED_FILES]` — files the plan anticipates creating or modifying, as orientation
- `[INTERFACES]` — exported types, interfaces, and method signatures to declare
- Context and invariants excerpts from CONTEXT.md and INVARIANTS.md

**Phase 1 done when all of these are true:**
- `contract.go` exists with all exported interfaces and type declarations
- Stub `.go` files exist with `panic("not implemented")` bodies for all exported
  functions and methods
- `go build ./[scope]` (or equivalent) succeeds
- No test files produced

**Parent action after Phase 1 returns:**
- Read all `.go` files produced in `[SCOPE_DIR]`. Store their contents in session
  context — this is the Phase 1 snapshot used verbatim in the Phase 5a brief.
- Verify: do exports match the plan exactly? If not, fix the brief and re-dispatch
  before proceeding.

---

## Phase 2: E2E Smoke Tests

**Before dispatching — test infrastructure check:**

Inspect the repo for existing E2E and integration test infrastructure (directories,
build tags, test helpers, CI config). Then apply these rules:

- **Both exist** → dispatch Phase 2 (E2E) and Phase 3 (integration). Default path.
- **Only E2E exists, no integration** → dispatch Phase 2; skip Phase 3.
- **Only integration exists, no E2E** → skip Phase 2; dispatch Phase 3. Do not
  leave the feature without tests because one tier is missing.
- **Neither exists** → stop and ask the user which test type to write before
  proceeding. Do not guess or skip silently.
- **User explicitly says to skip a phase** → skip that phase regardless of the
  above. Do not skip the other phase unless the user also says to.

Never skip both Phase 2 and Phase 3 unless the user explicitly requests it.

Dispatch a Phase 2 sub-agent using [prompts/PHASE2-BRIEF.md](prompts/PHASE2-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[PHASE1_SCAFFOLD_FILES]` — paths to Phase 1 output files (for API shape)
- `[E2E_TEST_DIR]`, `[E2E_TEST_COMMAND]`, `[ENVIRONMENT_REQUIREMENTS]`
- `[E2E_TEST_FRAMEWORK_AND_PATTERNS]` — framework, setup/teardown, example from
  an existing E2E test if available
- Context excerpt from CONTEXT.md

**Phase 2 done when:**
- E2E smoke test files written and compile
- Each file documents run command and environment requirements at the top
- Tests cover fundamental reachability and happy-path cases — no complex behavioral
  casework

**Parent check after Phase 2 returns:**
- Read the test files. Do they target the feature's top-level entry points?
- Collect `[E2E_TEST_COMMAND]` for the Phase 7 diagram.

---

## Phase 3: Integration Tests

Dispatch a Phase 3 sub-agent using [prompts/PHASE3-BRIEF.md](prompts/PHASE3-BRIEF.md).

This phase runs **before implementation**. The sub-agent reads Phase 1 scaffolding for
API shape, then writes behavioral tests grounded directly in the plan's behavioral
examples. These tests are the independent behavioral spec used by Phase 6.

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]` — include behavioral examples verbatim
- `[BEHAVIORAL_EXAMPLES]` — pull behavioral examples from the plan explicitly
- `[PHASE1_SCAFFOLD_FILES]` — Phase 1 output files (API shape only, not implementation)
- `[INTEGRATION_TEST_DIR]`, `[INTEGRATION_TEST_COMMAND]`, `[ENVIRONMENT_REQUIREMENTS]`
- `[INTEGRATION_TEST_FRAMEWORK_AND_PATTERNS]` — framework, fixture patterns, example
  from an existing integration test if available
- Context and invariants excerpts

**Phase 3 done when:**
- Integration test files written and compile
- Each behavioral example from the plan has at least one corresponding test case
- Run command and environment requirements documented in each file

**Parent check after Phase 3 returns:**
- Read the test files. Does each plan behavioral example have a corresponding test?

---

## Phase 4: Implementation

Dispatch a Phase 4 sub-agent using [prompts/PHASE4-BRIEF.md](prompts/PHASE4-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[SCOPE_DIR]`, `[PHASE1_FILES]` — Phase 1 scaffold files to build on
- `[MOCK_INTERFACES]` — interfaces in `contract.go` to generate mocks for
- `[MOCK_OUTPUT_DIR]` — where to write generated mock files (e.g. `internal/foo/mocks/`)
- `[ERROR_HANDLING_SUMMARY]` — error pattern from INVARIANTS.md
- `[BUILD_COMMAND]`, `[REGRESSION_CHECK_COMMAND]`
- Context and invariants excerpts

**Phase 4 done when all of these are true:**
- All `panic("not implemented")` stubs replaced with real implementations
- Mocks generated from `contract.go` interfaces (e.g. via `go generate`)
- `go build ./[scope]` passes
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

**Parent check after Phase 4 returns:**
- Run the build and regression check yourself. Do not trust the sub-agent's report.
- Verify mock files exist at `[MOCK_OUTPUT_DIR]`.
- Verify `contract.go` was NOT modified: `jj diff --no-pager contract.go`.
- Verify no files outside scope were modified: `jj diff --no-pager` and scan file list.

---

## Phase 5a: Unit Tests — Adversarial Pass

Dispatch a Phase 5a sub-agent using [prompts/PHASE5A-BRIEF.md](prompts/PHASE5A-BRIEF.md).

This agent is **blind to the implementation**. Provide it the Phase 1 snapshot (captured
after Phase 1) verbatim in the brief — not as file paths. It also receives mock file
paths and the plan's behavioral examples. It writes tests from the plan, runs them, and
reports results. It does NOT fix failures.

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
- If any test fails: surface all failures to the user with full test output. Stop.
  The user decides whether to re-invoke Phase 4 or accept the divergence. No automated
  fix loop.
- If all tests pass: proceed to Phase 5b.

---

## Phase 5b: Unit Tests — Coverage Pass

Only run if Phase 5a passes.

Dispatch a Phase 5b sub-agent using [prompts/PHASE5B-BRIEF.md](prompts/PHASE5B-BRIEF.md).

This agent reads Phase 5a test files, implementation files, and mocks. Its job: add new
test functions for coverage gaps — internal logic, error paths, edge cases not in
Phase 5a. It must NEVER modify existing Phase 5a test cases.

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
  case was modified, reject Phase 5b output, surface the violations to the user, and stop.
- Run the test command yourself. Verify all tests pass before proceeding.

---

## Phase 6: Adversarial Verification

Dispatch a Phase 6 verifier sub-agent using
[prompts/PHASE6-VERIFIER.md](prompts/PHASE6-VERIFIER.md).

Provide:
- The original plan verbatim
- Integration test results: "not run; pending user execution" unless the user ran
  them manually and provided output

The verifier reads INVARIANTS.md and runs `jj diff --no-pager` itself.

**Verifier checks:**
1. Spec compliance — every requirement in the plan implemented? List any gap.
2. Correctness — logic errors, nil panics, off-by-ones, missing error returns
3. Completeness — `panic("not implemented")` stubs remaining, TODOs affecting
   correctness, branches that never execute
4. Regressions — changes to shared/common code that could silently break callers
5. Test coverage — do Phase 5a tests verify the plan's behavioral examples? Do Phase 5b
   tests cover the error paths?

**On `VERIFIED`:** Proceed to Phase 7.

**On `ISSUES_FOUND` (critical or moderate):**
1. Dispatch a fix sub-agent with a focused brief: the specific issue list plus relevant
   file excerpts. Scope tightly — not the full diff.
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

If any sub-agent worked outside its expected scope, append a section listing every
instance. Collect these from each phase's output as you go — do not reconstruct from
the diff after the fact.

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

# Phase Instructions

## Phase 1: Scaffolding

Dispatch a Phase 1 sub-agent using [prompts/PHASE1-BRIEF.md](prompts/PHASE1-BRIEF.md).

Fill every placeholder:
- `[FEATURE]` — name and one-line summary
- `[PLAN_EXCERPT]` — the relevant plan section verbatim
- `[EXISTING_FILE_PATHS]` — paths of existing files the agent should read for context
- `[SCOPE_DIR]` — the package or directory that bounds the work (e.g. `internal/foo/`)
- `[EXPECTED_FILES]` — files the plan anticipates creating or modifying, as orientation
- `[INTERFACES]` — exported types, interfaces, and method signatures to declare
- Context and invariants excerpts from CONTEXT.md and INVARIANTS.md

**Phase 1 done when all of these are true:**
- Exported types, interfaces, structs declared with stub bodies (`panic("not implemented")`)
- Contract test file exists — one test per exported behavior, using `testCases` table pattern
- Contract tests compile but fail (no implementation yet — that's expected)
- `go build ./[scope]` (or equivalent) succeeds

**Parent check after Phase 1 returns:**
- Read the scaffolded files. Do exports match the plan exactly?
- Do the test names match the behaviors the plan specifies?
- If exports don't match spec, do NOT proceed to Phase 2. Fix the brief and re-dispatch.

---

## Phase 2: Implementation

Dispatch a Phase 2 sub-agent using [prompts/PHASE2-BRIEF.md](prompts/PHASE2-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]` — same as Phase 1
- `[SCOPE_DIR]` — same directory boundary
- `[EXPECTED_FILES]` — Phase 1 output files the agent should read before writing
- `[ERROR_HANDLING_SUMMARY]` — brief restatement of the error pattern from INVARIANTS.md
- `[TEST_COMMAND]`, `[REGRESSION_CHECK_COMMAND]` — from the project's test setup

**Phase 2 done when all of these are true:**
- All Phase 1 contract tests pass
- Unexported helpers and core logic implemented
- Implementation-level unit tests added (targeting internal logic and error paths, not
  the public contract)
- No new compilation errors outside scope

**Parent check after Phase 2 returns:**
- Run the test command yourself. Do not trust the sub-agent's report alone.
- Verify no files outside scope were modified: `jj diff --no-pager` and scan file list.
- If contract tests still fail: fix the brief with specific failure output and re-dispatch.

---

## Phase 3: Integration Tests

Dispatch a Phase 3 sub-agent using [prompts/PHASE3-BRIEF.md](prompts/PHASE3-BRIEF.md).

Fill every placeholder with the Phase 2 output and the integration test details gathered
in Phase 0b (framework, patterns, test file locations, run command).

**The sub-agent writes the tests but does NOT run them.** Integration and E2E tests
typically require live services, external auth, or infrastructure the agent cannot access.

**Phase 3 done when:**
- Integration and E2E test files are written and compile
- Tests are structured to run with `[INTEGRATION_TEST_COMMAND]` when the user executes it
- Agent explicitly notes which tests could not be verified automatically

**After Phase 3 returns:**
- Read the test files. Do they cover the integration points the plan calls for?
- Note the test command so it can be surfaced in Phase 5 for the user to run.
- Do not block on test execution — proceed to Phase 4.

---

## Phase 4: Adversarial Verification

Dispatch a Phase 4 verifier sub-agent using [prompts/PHASE4-VERIFIER.md](prompts/PHASE4-VERIFIER.md).

Provide:
- The original plan verbatim
- Integration test results: always "not run; pending user execution" unless the user ran
  them manually between phases and provided output

The verifier reads INVARIANTS.md and runs `jj diff --no-pager` itself.

**Verifier checks:**
1. Spec compliance — every requirement in the plan implemented? List any gap.
2. Correctness — logic errors, nil panics, off-by-ones, missing error returns
3. Completeness — unimplemented stubs, TODOs that affect correctness
4. Regressions — changes to shared/common code that could silently break callers
5. Test coverage — do contract tests actually verify the contracts? Error paths covered?

**On `VERIFIED`:** Proceed to Phase 5.

**On `ISSUES_FOUND` (critical or moderate):**
1. Dispatch a fix sub-agent with a focused brief: the specific issue list + relevant file
   excerpts (not the full diff again). Scope it tightly.
2. After fix agent returns, re-run the test command.
3. Re-dispatch the Phase 4 verifier with a fresh diff.
4. Repeat up to 3 total fix iterations.
5. After 3 failures: surface the remaining punch list to the user and stop.

Minor issues: record them and surface in Phase 5. Do not block on them.

---

## Phase 5: Diagram

Show the user an ASCII tree of all changes. Generate it from `jj diff --stat --no-pager`
or by reading the changed file list.

Format:
```
project/
├── path/to/
│   ├── new_file.go          [NEW] — one-line purpose
│   ├── new_file_test.go     [NEW] — contract tests / impl tests
│   └── existing_file.go     [MOD] — what changed
└── other/
    └── shared.go            [MOD] — what changed

Net: +N files, M modified, ~L lines
```

If any sub-agent worked outside its expected scope, append a section listing every
instance. Collect these from each phase's output as you go — do not reconstruct from
the diff after the fact.

```
Out-of-scope work:
  Phase 1 — path/to/unexpected.go: reason the agent gave
  Phase 2 — path/to/shared/util.go: reason the agent gave
```

If no sub-agent went outside scope, omit this section entirely.

If Phase 4 had minor issues not fixed, append:
```
Minor findings (not blocking):
  - path/to/file.go:42 — description
```

Always append:
```
Integration tests written, not yet run — execute when environment is ready:
  $ [INTEGRATION_TEST_COMMAND]
```

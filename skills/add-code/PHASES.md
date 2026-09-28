# Phase Instructions

## Phase 1: Scaffolding

Dispatch Phase 1 sub-agent: [prompts/PHASE1-BRIEF.md](prompts/PHASE1-BRIEF.md).

Fill every placeholder:
- `[FEATURE]` — name and one-line summary
- `[PLAN_EXCERPT]` — the relevant plan section verbatim, including behavioral examples
- `[EXISTING_FILE_PATHS]` — paths of existing files the agent should read for context
- `[SCOPE_DIR]` — the package or directory that bounds the work (e.g. `internal/foo/`)
- `[EXPECTED_FILES]` — files the plan anticipates creating or modifying, as orientation
- `[INTERFACES]` — exported types, interfaces, and method signatures to declare

**Phase 1 done when all of these are true:**
- `contract.go` exists with all exported interfaces and type declarations
- Stub `.go` files exist with `panic("not implemented")` bodies for all exported
  functions and methods
- `go build ./[scope]` (or equivalent) succeeds
- No test files produced

**Parent action after Phase 1 returns:**
- Read all `.go` files in `[SCOPE_DIR]`. Store contents in session context — Phase 1
  snapshot, used verbatim in Phase 3a brief.
- Verify exports match plan exactly. If not: fix brief, re-dispatch before proceeding.

---

## Phase 2: Implementation

Dispatch Phase 2 sub-agent: [prompts/PHASE2-BRIEF.md](prompts/PHASE2-BRIEF.md).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[SCOPE_DIR]`, `[PHASE1_FILES]` — Phase 1 scaffold files to build on
- `[MOCK_INTERFACES]` — interfaces in `contract.go` to generate mocks for
- `[MOCK_OUTPUT_DIR]` — where to write generated mock files (e.g. `internal/foo/mocks/`)
- `[ERROR_HANDLING_SUMMARY]` — the codebase's existing error handling conventions
- `[BUILD_COMMAND]`, `[REGRESSION_CHECK_COMMAND]`

**Phase 2 done when all of these are true:**
- All `panic("not implemented")` stubs replaced with real implementations
- Mocks generated from `contract.go` interfaces (e.g. via `go generate`)
- `go build ./[scope]` passes
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No TODOs affecting correctness remain
- `contract.go` unmodified

**Parent check after Phase 2 returns:**
- Run build + regression check yourself — don't trust sub-agent's report.
- Verify mock files exist at `[MOCK_OUTPUT_DIR]`.
- Verify `contract.go` NOT modified: `jj diff --no-pager contract.go`.
- Verify no files outside scope modified: `jj diff --no-pager`, scan file list.

---

## Phase 3a: Unit Tests — Adversarial Pass

Dispatch Phase 3a sub-agent: [prompts/PHASE3A-BRIEF.md](prompts/PHASE3A-BRIEF.md).

Agent is **blind to the implementation**. Give it Phase 1 snapshot (captured after Phase 1)
verbatim in brief — not file paths. Also gets mock file paths + plan's behavioral examples.
Writes tests from plan, runs them, reports results. Does NOT fix failures.

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[BEHAVIORAL_EXAMPLES]` — verbatim from the plan
- `[PHASE1_STUB_CONTENT]` — verbatim content of Phase 1 stub files (from session snapshot)
- `[MOCK_FILES]` — paths to generated mock files only
- `[SCOPE_DIR]`, `[TEST_FILE_PATH]`, `[TEST_COMMAND]`

**Phase 3a done when:**
- Test file written and run
- Results (pass or fail) reported to parent

**Parent action after Phase 3a returns:**
- Any test fails: surface all failures to user, full test output. Stop. User decides —
  re-invoke Phase 2 or accept divergence. No auto-fix loop.
- All tests pass: proceed to Phase 3b.

---

## Phase 3b: Unit Tests — Coverage Pass

Only run if Phase 3a passes.

Dispatch Phase 3b sub-agent: [prompts/PHASE3B-BRIEF.md](prompts/PHASE3B-BRIEF.md).

Agent reads Phase 3a test files, implementation files, mocks. Job: add test functions for
coverage gaps — internal logic, error paths, edge cases not in Phase 3a. Must NEVER modify
existing Phase 3a test cases; must append into same test file as Phase 3a — one test file
per source file (`foo.go` ↔ `foo_test.go`). Never split coverage + adversarial cases
across separate files (e.g. no `foo_coverage_test.go`).

Fill every placeholder:
- `[FEATURE]`, `[PLAN_EXCERPT]`
- `[PHASE1_STUB_CONTENT]` — for reference (signatures and interfaces)
- `[IMPLEMENTATION_FILES]`, `[PASS1_TEST_FILES]`, `[MOCK_FILES]`
- `[SCOPE_DIR]`, `[TEST_COMMAND]`
- `[ERROR_HANDLING_SUMMARY]`

**Phase 3b done when:**
- New test functions added for coverage gaps
- All tests (Phase 3a + new) pass

**Parent action after Phase 3b returns:**
- Diff Phase 3a test file vs current state. Any existing Phase 3a test case modified →
  reject Phase 3b output, surface violations to user, stop.
- Verify no new test file created alongside Phase 3a test file (e.g. `_coverage_test.go`
  or `_adversarial_test.go` split). Each source file: exactly one paired test file. Split
  file created → reject Phase 3b output, re-dispatch.
- Run test command yourself. Verify all tests pass before proceeding.

---

## Phase 4: Adversarial Verification

Dispatch Phase 4 verifier sub-agent: [prompts/PHASE4-VERIFIER.md](prompts/PHASE4-VERIFIER.md).

Provide:
- The original plan verbatim

Verifier runs `jj diff --no-pager` itself.

**Verifier checks:**
1. Spec compliance — every plan requirement implemented? List gaps.
2. Correctness — logic errors, nil panics, off-by-ones, missing error returns
3. Completeness — `panic("not implemented")` stubs remaining, TODOs affecting
   correctness, branches that never execute
4. Regressions — changes to shared/common code that could silently break callers
5. Test coverage — Phase 3a tests verify plan's behavioral examples? Phase 3b tests
   cover error paths?

**On `VERIFIED`:** Proceed to Phase 5.

**On `ISSUES_FOUND` (critical/moderate):**
1. Dispatch fix sub-agent — focused brief: issue list + relevant file excerpts. Scope
   tight, not full diff.
2. Fix returns → re-run test command.
3. Re-dispatch Phase 4, fresh diff.
4. Repeat up to 3 fix iterations total.
5. 3 failures → surface remaining punch list to user, stop.

Minor issues: record, surface in Phase 5. Don't block on them.

---

## Phase 5: Diagram

Show user ASCII tree of all changes. Generate from `jj diff --stat --no-pager`.

Format:
```
project/
├── path/to/
│   ├── contract.go              [NEW] — exported interfaces
│   ├── feature.go               [NEW] — implementation
│   ├── feature_test.go          [NEW] — adversarial + coverage unit tests
│   ├── mocks/mock_feature.go    [NEW] — generated mocks
│   └── existing_file.go         [MOD] — what changed
```

Net: +N files, M modified, ~L lines

Any sub-agent worked outside expected scope → append section listing every instance.
Collect these from each phase's output as you go — don't reconstruct from diff after
the fact.

```
Out-of-scope work:
  Phase N — path/to/file.go: reason the agent gave
```

Phase 4 had minor issues not fixed → append:
```
Minor findings (not blocking):
  - path/to/file.go:42 — description
```

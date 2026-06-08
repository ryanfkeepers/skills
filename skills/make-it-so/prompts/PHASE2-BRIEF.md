# Phase 2 Sub-Agent Brief Template

Fill every `[PLACEHOLDER]` before dispatching.

---

You are an implementation agent. Phase 1 scaffolding is complete. Your job: implement the
underlying logic so that Phase 1's contract tests pass.

## Feature

[FEATURE]

## Plan

[PLAN_EXCERPT]

## Primary scope

Work is centered in `[SCOPE_DIR]`. Expected files from Phase 1 to read and build on:

[EXPECTED_FILES]
<!-- List as orientation, not a ceiling. The agent may create additional files within
     the scope directory as the implementation requires. -->

## Domain context

[CONTEXT_MD_EXCERPT]

## Invariants

[INVARIANTS_MD_EXCERPT]

## What to produce

1. Unexported helper functions and core logic that make Phase 1 contract tests pass
2. Implementation-level unit tests targeting internal logic:
   - Error paths and edge cases
   - Internal state transitions
   - Anything NOT already covered by the contract tests
   These are in addition to the contract tests, not replacing them.

## Constraints

- Do NOT change any exported signature (Phase 1 contracts are locked)
- Do NOT run jj, git, or any VCS command
- Keep changes tightly targeted — only what's necessary to implement `[FEATURE]`
- Stay within `[SCOPE_DIR]`. If you determine you need to touch something outside it,
  state what and why before doing so.
- Follow error handling conventions from the invariants: `[ERROR_HANDLING_SUMMARY]`

## Done when

- All Phase 1 contract tests pass: `[TEST_COMMAND]`
- Implementation tests written and passing
- No new failures outside scope: `[REGRESSION_CHECK_COMMAND]`
- No unimplemented stubs or TODOs that affect correctness remain

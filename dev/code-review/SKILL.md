---
name: code-review
description: >-
  Review code changes in the current jj repository. Lists commits
  since trunk, lets the user select which to include, then performs
  a thorough code review. Use when the user asks for a code review,
  CR, or review of recent changes.
---

# Code Review

## Step 1 — Select commits

Invoke the `select-revs` skill to identify which commits to review.
Do not proceed until the user has confirmed the selection and you
have the earliest and latest change IDs.

## Step 2 — Gather the diff

Run `jj diff --from <earliest> --to <latest> --no-pager` to get the
full diff for the selected range.

If the range covers only one commit, run `jj show <change_id>
--no-pager` instead — it includes the commit message, which adds
useful context.

For multi-commit ranges, also run `jj log -r '<earliest>::<latest>'
--no-pager` to read the commit messages in sequence.

## Step 3 — Read context

Before reviewing, read enough surrounding code to understand intent:

- For any modified function, read the full function — not just the
  changed lines.
- If an interface, type, or constant is referenced in the diff but
  not defined there, find its definition.
- If tests are present for changed code, read them.
- If a CLAUDE.md, AGENTS.md, or REVIEW.md exists in or above the
  changed directories, read it — it may contain review criteria.

Use parallel reads for independent files.

## Step 4 — Review

Work through the diff systematically. For each changed file, assess:

### Correctness

- Does the logic do what the commit message says it does?
- Are error paths handled? Are errors propagated, not swallowed?
- Are edge cases covered — empty inputs, nil pointers, zero values,
  concurrent access, resource exhaustion?
- Are any invariants broken (domain rules, protocol contracts,
  ordering guarantees)?

### Code quality

- Are names accurate and consistent with the surrounding codebase?
- Is the abstraction level right — not over-engineered, not a one-
  off hack that should be generalized?
- Is complexity justified? Deep nesting, long functions, or large
  structs warrant a comment on what they could become.
- Is duplicated logic an opportunity for a helper, or is the
  duplication intentional?

### Style

- Does the code match the surrounding style (naming conventions,
  error message format, import ordering, etc.)?
- If the repo has a CLAUDE.md or style guide, does the code comply?

### Security

- Is any user-controlled input passed to a shell, SQL query, or
  file path without sanitization?
- Are secrets or credentials handled safely (not logged, not in
  error messages)?
- Are permissions or authentication checks present where expected?

### Tests

- Are new behaviors covered by tests?
- Are tests testing the real behavior, or mocking so heavily that
  they can't catch regressions?
- Are edge cases tested?

### Documentation

- Are exported symbols documented?
- Is non-obvious logic explained with a comment — not what it does,
  but why it must be done that way?

## Step 5 — Report

Structure the review as:

```
## Summary
<2–4 sentences: what the change does, overall assessment>

## Required changes
<numbered list of blocking issues — things that must be fixed>

## Suggestions
<unnumbered list of non-blocking improvements worth considering>

## Nits
<minor style/naming issues — low priority>
```

Omit any section that has no entries. Lead each item with the file
and line number: `path/to/file.go:42 — <finding>`.

If the change is clean, say so directly. Do not invent suggestions
to appear thorough.

---
name: fix-comments
description: >-
  Apply comment-content standards (no ticket/plan/caller references, no code
  examples, purpose-driven, 1-2 lines goal / 3 lines max) to the current
  working-copy change (@). Reads the diff — scoped to just @, to the stack
  since the last bookmark, or to the stack since trunk — and edits only
  comments on @. A targeted fix-my-nits variant with no standards file to
  read; the rule is fixed. Use when asked to fix comments, clean up comment
  noise, or trim over-explained comments. Invoke as /fix-comments.
argument-hint: "[current (default)|bookmark|stack]"
---

# Fix Comments

Apply the fixed comment-content standard as a final refinement to the
current change (`@`). Same shape as `fix-my-nits`, narrowed to comments —
no standards file to load; the rule below is the whole standard.

## Inputs

- **Scope** (optional) — `current` | `bookmark` | `stack`. Default
  `current`.
  - `current` — read only `@`'s own diff.
  - `bookmark` — read every revision since the last bookmark
    (`closest_bookmark(@)..@`).
  - `stack` — read every revision since trunk (`trunk()..@`).

Widening scope only widens what gets *read* — it exists so a comment
that only makes sense in light of context from earlier revisions in the
stack still gets judged correctly. Every fix still lands on `@` only —
editing a file always changes whatever is checked out, which `@` is,
regardless of scope. Never use `jj edit` or otherwise switch the
working copy to another revision in this skill.

## The rule

Comments exist to state constraints the code cannot express on its
own — not to restate what the code already shows.

- If there is nothing to say beyond what the code already shows, omit
  the comment.
- If a comment ponders or narrates implementation at large without a
  specific constraint, omit it.
- 1-2 lines per comment is the goal. 3 lines is the maximum — no
  exceptions. If a comment needs more than 3 lines to state its
  constraint, compress it (use terse, caveman-style phrasing if
  necessary) rather than let it run long.
- Comments must not:
  - reference tickets.
  - reference plans or other documentation.
  - state who or what uses the thing.
  - reference prior conversations or memories outside the code.
  - contain code examples.

Example:
```
// Retry wraps fn with exponential backoff up to maxAttempts.
// Callers must ensure fn is idempotent; Retry does not deduplicate.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {
```

Counter-example (restates the obvious, references callers):
```
// Retry retries the function.
// Retry is called by worker.Run and job.Execute.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {
```

Counter-example (yapping — broad narration, no constraint):
```
// ParseConfig loads and validates the service config from path.
// It returns an error if required fields are missing.
//
// This is important because config drives every downstream service,
// so getting it wrong causes cascading failures. Historically this
// function grew out of a simpler loader that only read defaults,
// but was extended over several releases to add overrides.
func ParseConfig(path string) (*Config, error) {
```

## Step 1 — Get the diff

Run the command matching the requested scope (default `current`):

```bash
# current
jj diff --no-pager

# bookmark
jj diff --from 'closest_bookmark(@)' --to '@' --no-pager

# stack
jj diff --from 'trunk()' --to '@' --no-pager
```

`closest_bookmark(@)` resolves to whatever bookmark this stack sits on
(trunk, if it isn't stacked on anything).

## Step 2 — Apply the rule

Spawn one sub-agent with this brief (fill in the scoped diff command):

> You are a nit-fixing agent focused exclusively on comment content.
>
> 1. Get the diff: `[scoped diff command from Step 1]`
> 2. Apply this rule to every comment on a changed line, and to any
>    comment directly attached to a changed declaration/function/block:
>
>    [paste the full "The rule" section above verbatim]
>
> **Your task:**
> - For each file touched in the diff, read the full file so you have
>   the construct's real context, not just the diff hunk.
> - For each comment in scope, decide: omit, trim, or leave as-is.
>   Only touch comments — do not edit code logic, formatting, or
>   non-comment lines.
> - Nits are refinements — do not refactor or restructure beyond what
>   the rule requires.
> - Apply every fix by editing the files as currently checked out. Do
>   not run `jj edit` or otherwise switch the working copy — even
>   though the diff may span multiple revisions, every fix must land
>   on `@`.
>
> **Report back**, as your final output, every comment you evaluated:
> its file:line, a short description, and the action taken
> (`omitted` / `trimmed` / `unchanged`). Do not include comments
> outside the diff's changed scope.

Record the sub-agent's report — this is the source for the summary
table in Step 4.

## Step 3 — Verify

Invoke the `assert-green` skill. Do not claim the work is done until
verification passes.

## Step 4 — Summary table

After verification passes, render a single Markdown table:

| File:Line | Comment | Action |
|---|---|---|
| [file:line] | [short description] | omitted / trimmed / unchanged |

- One row per comment reported back in Step 2.
- Do not include a row for a comment that was never evaluated.
- No counts, no diff stats — the table alone.

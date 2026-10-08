---
name: fix-comments
description: >-
  Apply comment-content standards (no ticket/plan/caller references, no code
  examples, purpose-driven, 1-2 lines goal / 3 lines max; always remove
  package-level comments and any comment stating the obvious; declaration
  comments may only state non-obvious, unchecked constraints on the
  value they govern) to the current working-copy change (@). Reads the
  diff — scoped to just @, to the stack since the last bookmark, or to
  the stack since trunk — and edits only comments on @. A targeted
  fix-my-nits variant with no standards file to read; the rule is fixed.
  Use when asked to fix comments, clean up comment noise, or trim
  over-explained comments. Invoke as /fix-comments.
argument-hint: "[current|bookmark (default)|stack]"
---

# Fix Comments

Apply the fixed comment-content standard as a final refinement to current
change (`@`). Same shape as `fix-my-nits`, narrowed to comments — no
standards file to load; the rule below is the whole standard.

## Inputs

- **Scope** (optional) — `current` | `bookmark` | `stack`. Default
  `bookmark`.
  - `current` — read only `@`'s own diff.
  - `bookmark` — read every revision since the last bookmark
    (`closest_bookmark(@)..@`).
  - `stack` — read every revision since trunk (`trunk()..@`).

Widening scope only widens what gets *read* — exists so a comment that
only makes sense in light of context from earlier revisions in the
stack still gets judged correctly. Every fix still lands on `@` only —
editing a file always changes whatever is checked out, which is `@`,
regardless of scope. Never use `jj edit` or otherwise switch working
copy to another revision in this skill.

## The rule

Comments exist to state constraints code can't express on its own —
not to restate what code already shows.

- If nothing to say beyond what code already shows, omit the comment.
- If a comment ponders or narrates implementation at large without a
  specific constraint, omit it.
- 1-2 lines per comment is the goal. 3 lines max — no exceptions. If a
  comment needs more than 3 lines to state its constraint, compress it
  (terse, caveman-style phrasing if necessary) rather than let it run
  long.
- Comments must not:
  - reference tickets.
  - reference plans or other documentation.
  - state who or what uses the thing.
  - reference prior conversations or memories outside the code.
  - contain code examples.

### Always omit

These are removed unconditionally — no judgment call, no trimming.

- **Package-level comments** (Go `// Package foo ...`, or the
  equivalent module/file header in other languages).
- **Comments stating the obvious**, on any construct: small funcs,
  fields, properties, variables, constants, structs, types, etc. If the
  comment only restates what the name, type, signature, or body already
  shows, remove it. Examples: `// funcName does foo` where `foo` is
  explicitly what the body shows, or `// fooID holds an ID representing
  a foo`. Keep only if the comment states a constraint the code cannot
  (see the rule above). Declaration comments are further limited by
  "Declaration comments" below.

Examples (all omitted):
```
// Package retry provides retry helpers.
package retry

// Add returns the sum of a and b.
func Add(a, b int) int { return a + b }

// Foo provides a foo ID.
type Foo struct {
	// fooID holds an ID representing a foo.
	fooID string
}

// maxAttempts is the maximum number of attempts.
const maxAttempts = 3

// timeout is the timeout.
var timeout = 5 * time.Second
```

### Declaration comments

A comment on a function, type, field, parameter, or constant never
describes what the construct is or does — that rehashes the code and is
the same problem as stating the obvious. The only permitted content is
a **non-obvious constraint on a value someone supplies or reads**,
placed on the narrowest construct it governs.

- Most declarations need no comment. Omit it unless such a constraint
  is present.
- **Placement.** A field, parameter, or constant carries its own
  constraint. A type comment does not restate its fields' constraints;
  with no constraint on the type as a whole, omit it. A function
  comment holds parameter invariants only.
- **Requirement, not characterization.** The comment tells someone how
  to set or read a specific value (`end is exclusive`). It must not
  claim what the construct is (`window spans [start, end)`); nothing
  enforces that claim. If the comment only characterizes the construct,
  omit it. Never rename or edit code to encode the constraint; if a
  rename would make the constraint self-describing (a half-open
  `window` named `halfOpenStartWindow`), omit the comment and report
  the rename as a suggestion only.
- **Call-path check.** Trace the construct's callees, constructors, and
  validators. If any code enforces or rejects the constraint (returns
  an error, records a validation error, normalizes it away), omit the
  comment: it is derivable from code and drifts when the validator
  changes. Generic stand-ins ("must be valid") are the same problem.
  Keep only constraints nothing checks.
- **Non-obvious only.** Expectations the language or convention already
  implies are omitted: pointers are non-nil, non-pointer values are
  non-zero. State the constraint as "when set (non-zero/non-nil),
  expects a shape, pattern, or state like ...".
- **Self-contained.** The comment must be intelligible from the
  construct's own signature alone: its name, parameter names, and
  types. Any identifier or concept outside the signature is external
  state and fails: sentinel errors, constants, other types' terms,
  domain states defined elsewhere (e.g. "bypassed", "the window landed
  on"), the filesystem, the network, call order, concurrency context,
  or what a caller did beforehand.
- Not a constraint: anything the type or signature already enforces,
  return-value or error behavior, side effects, or a summary of the
  steps taken.
- **Shape.** The comment opens with the construct's name
  (`// FuncName ...`), per Go convention, in every language, and must
  read as a complete sentence once trimmed. The verb carries the
  constraint: `requires`, `expects`, `assumes`, or `is`/`must be`
  followed by the constraint itself. Empty verbs (`holds`,
  `represents`, `provides`, `contains`) are banned. After trimming,
  re-read each kept comment as English; if the name plus the remainder
  does not parse, rephrase.
- If an existing comment mixes description with a constraint, keep only
  the constraint, name-first.
- Applies to every language and visibility. 3 lines max still holds;
  one line is the norm.

Examples (kept — unchecked constraints, on the construct they govern):
```
// Retry requires fn to be idempotent.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {

// Search requires xs to be sorted ascending.
func Search(xs []int, target int) int {

type window struct {
	start time.Time
	// end is exclusive.
	end time.Time
}
```

Avoid (type comment characterizes the type; the constraint belongs on
`end`, and the type comment is omitted):
```
// window spans [start, end); end is exclusive.
type window struct {
```

Avoid (constraint is enforced by normalizeSteps, so it is derivable and
drifts):
```
// New expects every step to be positive.
func New[T any](queryName string, start, end time.Time, steps ...time.Duration) *Ladder[T] {
```

Avoid (describes behavior; no constraint):
```
// Retry wraps fn with exponential backoff up to maxAttempts.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {
```

Avoid (constraint references external state):
```
// Retry requires ctx to carry the logger installed by the server middleware.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {
```

Avoid (names a sentinel error and a protocol defined elsewhere):
```
// Run expects fn to signal a short page by returning ErrPageNotFullyPopulated
// with a non-nil response.
func (l *Ladder[T]) Run(ctx context.Context, fn func(start, end time.Time) (T, error)) (T, error) {
```

Avoid (domain vocabulary from elsewhere; unintelligible from the signature):
```
// recordStepsUsed expects used to be the 1-based window landed on, or 0 when
// bypassed.
func recordStepsUsed(ctx context.Context, queryName string, used int64) {
```

Avoid (restates the obvious, references callers):
```
// Retry retries the function.
// Retry is called by worker.Run and job.Execute.
func Retry(ctx context.Context, maxAttempts int, fn func() error) error {
```

Avoid (yapping — broad narration, no constraint):
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

### Unit tests

Unit test files and code hold to a stricter version of the same rule.
A test's name and body already show what it covers — a comment
restating that is never useful, so omit it. Only keep a comment when
the test's outcome depends on a runtime condition the code cannot
express on its own (a race, a platform quirk, an external service's
behavior, a flaky timing window) — and even then, state the
condition, not what the test does.

Unit test example (kept — outcome depends on a runtime condition):
```
// Assumes global config uses default settings; skip if TestMain overrides it.
func TestRetry_GivesUpOnPersistentError(t *testing.T) {
```

Avoid (unit test — restates coverage, no runtime condition):
```
// Tests that Retry gives up after maxAttempts and returns the last error.
func TestRetry_GivesUpAfterMaxAttempts(t *testing.T) {
```

## Step 1 — Get the diff

Run the command matching requested scope (default `bookmark`):

```bash
# current
jj diff --no-pager

# bookmark
jj diff --from 'closest_bookmark(@)' --to '@' --no-pager

# stack
jj diff --from 'trunk()' --to '@' --no-pager
```

`closest_bookmark(@)` resolves to whatever bookmark this stack sits on
(trunk, if not stacked on anything).

## Step 2 — Apply the rule

Spawn one sub-agent with this brief (fill in the scoped diff command):

> You are a nit-fixing agent focused exclusively on comment content.
>
> 1. Get the diff: `[scoped diff command from Step 1]`
> 2. Apply this rule to every comment on a changed line, and to any
>    comment directly attached to a changed declaration/function/block:
>
>    [paste the full "The rule" section above verbatim, including
>    its subsections]
>
> **Your task:**
> - For each file touched in the diff, read the full file so you have
>   the construct's real context, not just the diff hunk.
> - For each comment in scope, decide: omit, trim, or leave as-is.
>   Only touch comments — do not edit code logic, formatting, or
>   non-comment lines.
> - A comment already in the file is not evidence it is correct. The
>   default for every comment is omit. It survives only by passing
>   every gate below; a failed or uncertain gate means omit.
> - Gate 1, self-contained: can the comment be understood from the
>   construct's name, parameter names, and types alone? If it names a
>   sentinel, constant, other type, or domain state defined elsewhere,
>   it fails.
> - Gate 2, unchecked: trace the construct's callees, constructors,
>   and validators. If any code enforces or rejects the constraint, it
>   fails.
> - Gate 3, non-obvious: if the language or convention already implies
>   it (non-nil pointer, non-zero value), it fails.
> - Gate 4, constraint: it must tell someone how to set or read a
>   value. A description of behavior or of what the construct is fails.
> - A comment that passes all gates: re-read it as an English
>   sentence; rephrase if the name plus the remainder does not parse.
> - Nits are refinements — do not refactor or restructure code. The
>   gates above are the rule; apply them in full.
> - Apply every fix by editing the files as currently checked out. Do
>   not run `jj edit` or otherwise switch the working copy — even
>   though the diff may span multiple revisions, every fix must land
>   on `@`.
>
> **Report back**, as your final output, one entry per file in the
> diff's changed scope: the file path and whether you `changed` or left
> it `unchanged`. No per-comment detail. Also list any rename suggestions
> (file:line, current name, suggested name, and the constraint it would
> encode). Suggestions are report-only; never apply a rename.

Record the sub-agent's report — source for the summary table in Step 4.

## Step 3 — Verify

Invoke the `lint-fix` skill. Don't claim work done until
it passes.

## Step 4 — Summary table

After verification passes, render a single Markdown table:

| File | Status |
|---|---|
| [file] | changed / unchanged |

- One row per file reported back in Step 2.
- No per-comment rows, counts, or diff stats.
- If Step 2 reported rename suggestions, follow the table with a
  "Rename suggestions" list: `file:line` — `current` → `suggested`
  (constraint encoded). Omit the list when there are none. Never apply
  them.

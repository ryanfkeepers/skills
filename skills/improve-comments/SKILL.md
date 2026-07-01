---
name: improve-comments
description: >-
  Review and rewrite comments added or modified in the current working-copy
  change (@). Enforces three rules: comments explain purpose and rationale
  (not just identity); interface declarations own the authoritative behavior
  comment while implementations only note implementation-specific concerns;
  and comments stay concise with no i/o examples. Use when asked to improve,
  review, or clean up comments in the current revision.
---

# Improve Comments

Review and rewrite comments touched in the current change (`@`). Scope is
limited to comments added or modified in the diff — do not touch other
comments unless a rule requires it (see Rule 2).

## Step 1 — Get the diff

```bash
jj diff --no-pager
```

Collect every comment that was added (`+` lines) or modified. Unchanged
comments are out of scope.

## Step 2 — Apply the three rules

Every in-scope comment must satisfy all three rules.

---

### Rule 1 — Purpose and rationale, not identity

A comment must explain **what the symbol is for** and **why it exists** in
this design. It must not restate the symbol's name or type.

**Example (do this):**
```go
// Backoff caps at 30 s to avoid thundering-herd on reconnect storms.
const maxRetryDelay = 30 * time.Second
```

**Counter-example (avoid):**
```go
// maxRetryDelay is the maximum retry delay.
const maxRetryDelay = 30 * time.Second
```

When a comment only restates the name, delete it unless the symbol is
exported and a doc comment is required — in that case rewrite it to add
purpose and rationale.

---

### Rule 2 — Interface owns the contract; implementations note concerns

The interface declaration carries the authoritative comment describing
the expected behavior and contract. Implementation methods must not
duplicate that contract. They should either:

- Add a short note about implementation-specific concerns (caching
  strategy, locking discipline, known limitations), or
- Omit the comment entirely if there is nothing worth noting.

This rule may require reading outside the diff: if an in-scope
implementation comment duplicates the interface comment, the interface
comment is in-scope for deletion or simplification even if unmodified.

**Example (do this):**
```go
// Fetcher retrieves a resource by key. Implementations must be safe
// for concurrent use.
type Fetcher interface {
    Fetch(ctx context.Context, key string) (Resource, error)
}

// Fetch satisfies Fetcher. Results are cached for 5 minutes; stale
// entries are returned on upstream error.
func (c *cachedFetcher) Fetch(ctx context.Context, key string) (Resource, error) {
```

**Counter-example (avoid):**
```go
// Fetch retrieves a resource by key. Safe for concurrent use.
func (c *cachedFetcher) Fetch(ctx context.Context, key string) (Resource, error) {
```

---

### Rule 3 — Keep it short; no i/o examples

Comments should be ten lines or fewer. Do not add i/o examples unless the
user explicitly asked for them. Trim any examples introduced in this diff.

---

## Step 3 — Apply edits

Edit only comment text — do not alter code logic, formatting, or structure.

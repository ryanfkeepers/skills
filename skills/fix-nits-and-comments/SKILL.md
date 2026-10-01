---
name: fix-nits-and-comments
description: >-
  Shorthand that runs fix-my-nits, then fix-comments, on the current
  working-copy change (@) and prints both result tables together at the
  end. Use when asked to fix nits and comments in one pass, or invoke as
  /fix-nits-and-comments.
argument-hint: "[current|bookmark|stack]"
---

# Fix Nits and Comments

Run `fix-my-nits`, then `fix-comments`, against `@`. Report both
results together once both are done.

## Inputs

- **Scope** (optional) — `current` | `bookmark` | `stack`.
  - If given, pass it unchanged to both skills.
  - If omitted, pass nothing, so each skill uses its own default
    (`fix-my-nits`: `current`, `fix-comments`: `bookmark`).

## Step 1 — fix-my-nits

Invoke the `fix-my-nits` skill with the scope. Keep its Step 4
summary table; do not print it yet.

If it stops with an error (e.g. `STANDARDS.md` not found), stop here
and report that error. Do not run `fix-comments`.

## Step 2 — fix-comments

Invoke the `fix-comments` skill with the scope. It runs after
`fix-my-nits` so it judges the comments as they stand after the nit
edits. Keep its Step 4 summary table; do not print it yet.

## Step 3 — Report

Print both tables, nothing else between them:

```
### Nits

[fix-my-nits table, verbatim]

### Comments

[fix-comments table, verbatim]
```

- Tables only. No counts, no diff stats, no recap of what each skill did.
- If a skill produced no rows, print its heading with
  `No changes evaluated.`

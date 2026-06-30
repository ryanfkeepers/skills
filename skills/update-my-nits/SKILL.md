---
name: update-my-nits
description: >-
  Add, modify, or remove a standard in the user's personal standards docs
  at ~/.agents/mystandards/. Interviews the user via keepers:sanity to
  establish domain, name, prescribed behavior, and a correct example with
  counter-example. Detects overlapping standards and handles new domains.
  Use when adding a personal coding standard, updating an existing one,
  removing an outdated one, or invoking /update-my-nits.
---

# Update My Nits

Manage entries in `~/.agents/mystandards/` — add, modify, or remove a
personal coding standard.

## Standard format

Every standard entry uses this structure:

```markdown
## Standard Name

A short description of the expected behavior.

<example>a succinct example of what is wanted.</example>

<example-avoid>a succinct example of what should be avoided.</example-avoid>
```

## Step 1 — Determine the operation

Ask the user: **"Do you want to add, modify, or remove a standard?"**

Do not proceed until the operation is clear.

## Step 2 — Load standards docs

Read `~/.agents/mystandards/STANDARDS.md`.

If the file does not exist, stop:

> **Error:** `~/.agents/mystandards/STANDARDS.md` not found. Create this
> file before running update-my-nits.

Note every linked domain doc. For add/modify, you will need these shortly.

## Step 3 — Execute the operation

Follow the appropriate flow in [FLOWS.md](FLOWS.md).

## Step 4 — Verify

Invoke `verification-before-completion`. Do not claim the work is done
until verification passes.

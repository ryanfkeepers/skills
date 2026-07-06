---
name: fix-my-nits
description: >-
  Apply the user's personal coding standards from
  ~/.agents/mystandards/STANDARDS.md to the current working-copy change (@).
  Reads the diff, loads relevant domain standards, applies nit-level edits
  directly, and flags any conflict with the project's CLAUDE.md. Use when
  asked to fix nits, apply personal standards, or clean up a revision to
  personal preferences. Invoke as /fix-my-nits.
---

# Fix My Nits

Apply personal standards as final refinements to the current change (`@`).
These standards are additive — they do not override project conventions.

## Step 1 — Load personal standards

Read `~/.agents/mystandards/STANDARDS.md`.

If the file does not exist, stop immediately:

> **Error:** `~/.agents/mystandards/STANDARDS.md` not found. Create this
> file with your personal standards before running fix-my-nits.

If the file exists, read it in full. Note every domain-specific standards
doc it links to (e.g., `go/STANDARDS.md`, `ts/STANDARDS.md`).

## Step 2 — Get the diff

```bash
jj diff --no-pager
```

Identify the languages, file types, and repo context of the diff. Domains
are not limited to file types — a domain may apply based on any of:
language, file type, repository, GitHub organization, or other context.
Always apply a domain-specific standards doc when any of these evaluations
matches, not only when the file extension matches.

For each linked domain doc whose domain applies to the diff, read that doc.

Example: diff touches `.go` files → read `~/.agents/mystandards/go/STANDARDS.md`
if STANDARDS.md links to it. Example: diff is in a repo under the `acme-corp`
GitHub org → read `~/.agents/mystandards/acme-corp/STANDARDS.md` if linked.

## Step 3 — Check for project conventions

Read any `CLAUDE.md` files in the repo (project root and relevant
subdirectories). These define authoritative project conventions.

Personal standards **never** override project conventions. When a personal
standard conflicts with a project convention, do not apply the nit — flag
it instead (see Step 5).

## Step 4 — Apply nits

For each file in the diff:

1. Read the full file.
2. Identify lines changed in the diff.
3. Apply every personal standard that is relevant to those changes, provided
   no project-convention conflict exists.
4. Skip anything outside the changed lines unless the standard requires
   cross-cutting changes (e.g., a file-level naming convention).

Nits are refinements — do not refactor, restructure, or expand scope beyond
what the standards explicitly require.

## Step 5 — Flag conflicts

After applying edits, report any skipped nits due to project-convention
conflicts:

```
Skipped nits (conflict with project conventions):
- <file>:<line>: personal standard says X; CLAUDE.md says Y
```

If no conflicts, omit this section.

## Step 6 — Verify

Invoke the `assert-green` skill. Do not claim the work is
done until verification passes.

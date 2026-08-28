---
name: fix-my-nits
description: >-
  Apply the user's personal coding standards from
  ~/.agents/mystandards/STANDARDS.md to the current working-copy change (@).
  Reads the diff — scoped to just @, to the stack since the last bookmark, or
  to the stack since trunk — and applies nit-level edits to @ only. Use when
  asked to fix nits, apply personal standards, or clean up a revision to
  personal preferences. Invoke as /fix-my-nits.
---

# Fix My Nits

Apply personal standards as final refinements to the current change (`@`).

## Inputs

- **Scope** (optional) — `current` | `bookmark` | `stack`. Default
  `current`.
  - `current` — read only `@`'s own diff.
  - `bookmark` — read every revision since the last bookmark
    (`closest_bookmark(@)..@`).
  - `stack` — read every revision since trunk (`trunk()..@`).

Widening scope only widens what gets *read* — it exists so a standard
that only makes sense in light of context from earlier revisions in
the stack (e.g. a naming convention established two commits back)
still gets applied correctly. Every fix still lands on `@` only —
editing a file always changes whatever is checked out, which `@` is,
regardless of scope. Never use `jj edit` or otherwise switch the
working copy to another revision in this skill.

## Step 1 — Load personal standards

Read `~/.agents/mystandards/STANDARDS.md`.

If the file does not exist, stop immediately:

> **Error:** `~/.agents/mystandards/STANDARDS.md` not found. Create this
> file with your personal standards before running fix-my-nits.

If the file exists, read it in full. Note every domain-specific standards
doc it links to (e.g., `go/STANDARDS.md`, `ts/STANDARDS.md`).

## Step 2 — Get the diff

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
(trunk, if it isn't stacked on anything) — same revset `pr-comments`
uses to scope a PR's own commits.

Identify the languages, file types, and repo context of the diff. Domains
are not limited to file types — a domain may apply based on any of:
language, file type, repository, GitHub organization, or other context.
Always apply a domain-specific standards doc when any of these evaluations
matches, not only when the file extension matches.

For each linked domain whose domain applies to the diff, walk its
directory tree under `~/.agents/mystandards/[domain]/` and collect every
file path. Domain files do not cross-link to other domains.

Example: diff touches `.go` files → walk `~/.agents/mystandards/go/` and
collect all files found. Example: diff is in a repo under the `acme-corp`
GitHub org → walk `~/.agents/mystandards/acme-corp/` and collect all
files found.

Record the full list of file paths for each applicable domain — this is
what gets handed to the sub-agent in Step 4, not the content.

## Step 3 — Apply nits by domain (sequentially)

For each applicable domain standards doc, **one at a time**, spawn a
sub-agent with this brief (fill in the bracketed values before sending):

> You are a nit-fixing agent focused exclusively on **[DOMAIN]** standards.
>
> 1. Get the diff: `[scoped diff command from Step 2]`
> 2. Read all domain standards files: `[list every file path collected for this domain]`
>
> **Your task:**
> - For each file touched in the diff, read the full file.
> - For each change in the diff, apply every standard from the domain
>   standards files that is relevant to that change. Use the surrounding
>   context to understand the full construct being changed (declaration,
>   function, block) — do not evaluate standards line by line in isolation.
> - Skip anything outside the changed lines unless the standard requires
>   cross-cutting changes (e.g., a file-level naming convention).
> - Nits are refinements — do not refactor, restructure, or expand scope
>   beyond what the standards explicitly require.
> - Apply every fix by editing the files as currently checked out. Do
>   not run `jj edit` or otherwise switch the working copy — even
>   though the diff may span multiple revisions, every fix must land
>   on `@`.

Do **not** launch domain agents in parallel. Wait for each agent to finish
before starting the next one.

## Step 4 — Verify

Invoke the `assert-green` skill. Do not claim the work is
done until verification passes.

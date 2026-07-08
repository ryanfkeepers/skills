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

For each linked domain whose domain applies to the diff, walk its
directory tree under `~/.agents/mystandards/[domain]/` and collect every
file path. Domain files do not cross-link to other domains.

Example: diff touches `.go` files → walk `~/.agents/mystandards/go/` and
collect all files found. Example: diff is in a repo under the `acme-corp`
GitHub org → walk `~/.agents/mystandards/acme-corp/` and collect all
files found.

Record the full list of file paths for each applicable domain — this is
what gets handed to the sub-agent in Step 4, not the content.

## Step 3 — Check for project conventions

From the diff, collect the set of directories containing changed files.
For each such directory, walk up the tree to the repo root and record
every `CLAUDE.md` found. Deduplicate. This list is the **project
conventions set** — pass it in full to every sub-agent in Step 4.

Personal standards **never** override project conventions. When a personal
standard conflicts with a project convention, do not apply the nit — flag
it instead (see Step 5).

## Step 4 — Apply nits by domain (sequentially)

For each applicable domain standards doc, **one at a time**, spawn a
sub-agent with this brief (fill in the bracketed values before sending):

> You are a nit-fixing agent focused exclusively on **[DOMAIN]** standards.
>
> 1. Get the current diff: `jj diff --no-pager`
> 2. Read all domain standards files: `[list every file path collected for this domain]`
> 3. Read project conventions from `[path(s) to relevant CLAUDE.md files]`
>
> **Your task:**
> - For each file touched in the diff, read the full file.
> - For each change in the diff, apply every standard from the domain
>   standards files that is relevant to that change. Use the surrounding
>   context to understand the full construct being changed (declaration,
>   function, block) — do not evaluate standards line by line in isolation.
> - Skip anything outside the changed lines unless the standard requires
>   cross-cutting changes (e.g., a file-level naming convention).
> - Personal standards never override project conventions. When a personal
>   standard conflicts with a project convention, do not apply it — instead
>   report it as a skipped nit:
>   `<file>:<line>: personal standard says X; CLAUDE.md says Y`
> - Nits are refinements — do not refactor, restructure, or expand scope
>   beyond what the standards explicitly require.
> - When finished, report any skipped nits.

Do **not** launch domain agents in parallel. Wait for each agent to finish
before starting the next one.

Collect each agent's skipped-nit report as it completes.

## Step 5 — Flag conflicts

Aggregate all skipped nits reported by the domain agents:

```
Skipped nits (conflict with project conventions):
- <file>:<line>: personal standard says X; CLAUDE.md says Y
```

If no conflicts, omit this section.

## Step 6 — Verify

Invoke the `assert-green` skill. Do not claim the work is
done until verification passes.

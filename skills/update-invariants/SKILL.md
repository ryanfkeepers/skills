---
name: update-invariants
description: >-
  Create or update an invariant in an INVARIANTS.md doc, scanning the full
  directory ancestry and descendancy to detect existing coverage and
  placement conflicts before writing. Use when adding a new invariant,
  updating an existing one, resolving an invariant conflict flagged in
  plan-changes, or any time the user asks to record or change an invariant.
---

@../../shared/docs/invariants/FORMAT.md

## Process

### Step 1 — Establish the working scope

Determine which directory this invariant belongs to. Infer from the user's
context (current file, topic of discussion, directory being worked in) when
possible. If ambiguous, ask.

### Step 2 — Scan the hierarchy

From the working scope, search both directions for existing `INVARIANTS.md`
files. Do not cross into sibling directories — ancestry and descendancy only.

**Ancestry** — walk up the directory tree, loading each `INVARIANTS.md`
found until reaching the repo root.

**Descendancy** — walk down into subdirectories, loading each `INVARIANTS.md`
found.

For each match against the proposed invariant:

- **Found in a parent:** Report the parent entry verbatim. Ask whether it is
  sufficient, or whether a lower-level, stricter version is needed at the
  working scope.
- **Found in a child:** Report the child entry and its path. Ask whether the
  rule should be hoisted to the working scope (and removed from the child),
  or left where it is.

If no match is found, proceed directly to Step 3.

### Step 3 — Sanity check

Invoke `/sanity` scoped to: **"Is this invariant well-defined, correctly
scoped, and does it pass the litmus test?"**

The sanity interview must resolve:

- **Falsifiability** — can you describe a concrete scenario that breaks this
  rule? If not, it doesn't belong in INVARIANTS.
- **Litmus test** — does the rule pass both gates: not code-obvious, and
  requires system context? Rules that fail either gate belong in an ADR or
  a code comment instead.
- **Scope** — is the working scope right, or should the rule live higher
  (more global) or lower (more specific)?
- **Conditionality** — does the rule use "usually", "typically", or "in most
  cases"? If so, tighten it or split it into unconditional entries.
- **Conflicts** — does this rule contradict any entry found in Step 2? If so,
  resolve which wins, and flag the conflict explicitly in the file.

Do not write the file until the sanity check signals complete.

### Step 4 — Write the file

1. If `INVARIANTS.md` exists at the target scope, add or update the entry
   in place.
2. If none exists, create it lazily using the FORMAT template.
3. Confirm the file path to the user.
4. If a hoist was agreed in Step 2, also remove the entry from the child
   file and confirm both changes.

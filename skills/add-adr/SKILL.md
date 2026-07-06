---
name: add-adr
description: >-
  Write a new Architecture Decision Record (ADR) to the repo. Runs a
  /sanity interview to confirm the decision meets ADR criteria and gathers
  all required content before writing the file. Use when recording an
  architectural decision, after plan-changes proposes an ADR topic, or any
  time a hard-to-reverse trade-off needs to be documented.
---

@../../shared/docs/adr/FORMAT.md

## Process

### Step 1 — Sanity check

Before writing anything, invoke `/sanity` scoped to: **"Does this decision
warrant an ADR, and do we have everything needed to write it?"**

The sanity interview must resolve:

- **The decision** — what was decided, stated precisely
- **The why** — what trade-off drove it; what would be lost without recording it
- **ADR criteria** — does it satisfy all three: hard to reverse, surprising
  without explanation, result of a real trade-off? If any criterion is
  missing, surface the gap and let the user decide whether to proceed
- **Considered alternatives** — what was rejected and why (only if the
  rejection is non-obvious to a future reader)
- **Consequences** — any non-obvious downstream effects worth calling out

Do not write the ADR until sanity check signals complete.

### Step 2 — Draft and confirm

After the sanity check, present the full ADR draft to the user. Follow the
FORMAT above — a single paragraph is the default; add optional sections only
if the sanity check revealed content that genuinely warrants them.

Wait for explicit user approval before writing the file.

### Step 3 — Write the file

1. Scan `/adrs/` for the highest existing number and increment by one.
2. Derive the slug from the title: lowercase, hyphens, no punctuation.
3. Create `/adrs/` if it doesn't exist yet.
4. Write the file to `/adrs/NNNN-slug.md`.
5. Confirm the path to the user.

## Constraints

- Always place ADRs in `/adrs/` at the repo root — never in subdirectories.
- Do not cross-reference internal non-ADR docs inside the ADR body.
- Do not write the file until the user approves the draft.

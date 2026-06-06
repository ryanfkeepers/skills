---
name: split-rev
description: >-
  Split a single jj revision into multiple smaller revisions for incremental
  human review. Interviews the user to agree on a split plan before touching
  any code. Use when a change is too large to review in one pass, the user
  wants to break a revision into logical review units, or when asked to
  split, slice, or decompose a commit or revision.
---

# split-rev

Split one jj revision into multiple independently-reviewable revisions.

**Hard rule:** Do not split anything until the user has explicitly approved
the plan.

## Step 1 — Analyze

```
jj diff -r @ --no-pager
jj show @ --no-pager
```

Group files into logical categories (data model, interfaces, implementations,
tests, generated code, config, docs). Count LOC per file.

## Step 2 — Propose splits

Propose splits in dependency order (first in plan = earliest in the stack).
Each split must:

- Contain **one logical concern**
- Be **independently green**: lint, tests, and autogeneration pass without
  relying on any later split
- Target **≤ 500 LOC** (far fewer is better)
- Keep unit tests with the code they test — never separate them

If the revision is already small or a single logical unit, say so and
recommend against splitting.

**Splits must be at whole-file boundaries.** If a file has changes that
span two concerns, flag it during the interview and work with the user to
find a plan that avoids intra-file splits (e.g. move one concern's changes
to a different split, or accept a slightly larger split to keep the file
whole).

Format each proposed split as:

> **Split N — \<one-line description\>**
> Files: `foo.go`, `foo_test.go` · ~NN lines

## Step 3 — Interview

Ask: "Does this plan work, or would you like to adjust it?"

Revise until the user explicitly agrees. Do not start splitting.

## Step 4 — Get explicit approval

Ask:

> "Ready to execute? I'll clone the current revision for safety, then
> split according to the plan."

Do not proceed until the user says yes.

## Step 5 — Safety clone

```
jj duplicate -r @
```

Record the change ID of the duplicate. It holds an independent copy of
the full revision and can be used to restore if something goes wrong.

## Step 6 — Execute (repeat per split in plan order)

### 6a. Extract

```
jj split -r @ -- <files>
```

After the split: `@-` = extracted split, `@` = remainder. Record
the change ID of `@` before leaving.

### 6b. Describe

```
jj edit @-
```

Invoke the `jjdesc` skill to write and apply the commit description.

### 6c. Verify CI

Run lint, tests, and autogeneration. Fix any failures before proceeding.
No split may depend on a later split to reach a green state.

### 6d. Continue

```
jj edit <remainder-change-id>
```

Repeat until the final split. The last `@` is the final chunk — describe
and verify it too.

## Recovery

```
jj abandon <bad-changes>
jj restore --from <duplicate-change-id> --to @
```

Or edit the duplicate directly and re-split from there.

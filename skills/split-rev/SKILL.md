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

**Prefer whole-file boundaries.** If a file's changes can be cleanly
assigned to one split, assign them whole. If a file's changes span two
concerns, a surgical (hunk-level) split is always acceptable — note which
files will require it in the plan so the user knows what to expect.

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

Record the change ID of the duplicate and the change ID of `@-` (the
parent of the revision being split). Both are needed for the final
completeness check.

## Step 6 — Execute (repeat per split in plan order)

### 6a. Extract

For whole-file splits:
```
jj split -r @ -- <files>
```

For surgical (hunk-level) splits, there is no interactive mode available.
Manufacture the split manually:
1. Edit the file(s) to contain **only the first split's hunks** (relative to
   the parent — remove the second split's changes from the file).
2. Then use the whole-file form:
   ```
   jj split -r @ -- <files>
   ```
   `@-` will contain the file at the edited (first-split) state; `@` will
   contain the delta from that state to the original, which is exactly the
   second split's hunks.

After the split: `@-` = extracted split, `@` = remainder. Record
the change ID of `@` before leaving.

### 6b. Describe

```
jj edit @-
```

Invoke the `jjdesc` skill to write and apply the commit description.

### 6c. Verify

Invoke the `assert-green` skill. The split must pass lint,
tests, and any autogeneration before proceeding. Fix all failures first.
No split may depend on a later split to reach a green state.

### 6d. Continue

```
jj edit <remainder-change-id>
```

Repeat until the final split. The last `@` is the final chunk — describe
it and invoke `assert-green` for it too.

## Step 7 — Completeness check

After all splits are described and verified, confirm no changes were lost.

**Never modify the safety clone.** It is the ground truth. All
discrepancies must be resolved by editing the stack.

Diff the full span of the new stack against its base:

```
jj diff --from <original-parent-change-id> --to @ --no-pager
```

Diff the safety clone against its base:

```
jj diff -r <duplicate-change-id> --no-pager
```

The two diffs must be identical — every file and every hunk present in
the clone diff must appear in the stack diff, and vice versa.

If they differ:
1. Identify which file(s) or hunk(s) are missing or wrong in the stack.
2. `jj edit` the appropriate split and apply the missing changes there.
3. Re-run both diffs and repeat until they match.
4. Re-run `assert-green` on any split you touched.

Do not declare the split complete until the diffs match exactly.

## Recovery

```
jj abandon <bad-changes>
jj restore --from <duplicate-change-id> --to @
```

Or edit the duplicate directly and re-split from there.

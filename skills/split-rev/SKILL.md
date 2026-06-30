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

Note which files will require hunk-level splits so the user knows what
to expect.

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

**The safety clone is permanently read-only.** It is the ground truth
for the original diff and the source for restoring remainder changes
during extraction. Never edit or abandon it.

## Step 6 — Execute (repeat per split in plan order)

Every split is executed the same way — sculpt the working copy to
contain exactly this split's changes, commit it, then restore the
remainder from the safety clone. There is no shortcut tool; this is
always a surgical, deliberate operation.

### 6a. Extract

1. Confirm `@` is the revision being split: `jj show @ --no-pager`
2. Record `@`'s change ID — this is the remainder target after extraction.
3. Remove changes that belong to a **later** split:
   - **Whole-file boundary:** `jj restore --from @- -- <later-files>`
   - **Hunk-level boundary:** manually edit the file to contain only this
     split's hunks; revert the later hunks to the parent state by hand
4. Confirm only this split's changes remain: `jj diff --no-pager`
5. Commit the extracted split and open an empty remainder:
   ```
   jj new
   ```
   `@-` = extracted split; `@` = empty.
6. Restore the removed changes from the safety clone:
   ```
   jj restore --from <duplicate-change-id> -- <all-removed-files>
   ```
   `@` now holds exactly the next round's changes.

After extraction: `@-` = this split, `@` = remainder. Record
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
All discrepancies must be resolved by editing the stack, never the clone.

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

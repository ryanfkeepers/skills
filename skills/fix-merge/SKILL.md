---
name: fix-merge
description: >-
  Resolve jj merge conflicts across a stack, starting with the conflict
  closest to trunk and working up toward the calling revision. Uses the
  same scope modes as fix-my-nits (current/bookmark/stack) but defaults
  to stack. Use when jj reports a conflicted revision, a revision shows
  conflict markers, or when asked to fix, resolve, or clean up merge
  conflicts in a jj stack. Invoke as /fix-merge.
argument-hint: "[current|bookmark|stack (default)]"
---

# Fix Merge

Resolve conflicted revisions in a jj stack, closest to trunk first,
working up toward the revision `fix-merge` was called from.

**Hard rules:**

- Never run `jj new`, `jj describe`/`jj desc`, or `jj push`. Conflicts
  are resolved by editing files directly on the revision checked out
  via `jj edit` — never by creating a new revision.
- Never touch a revision outside the resolved scope (Step 1) — this
  includes any descendant of the calling revision.
- Always end with the working copy back on the revision `fix-merge`
  was called from.

## Step 0 — Record the calling revision

```
jj log -r @ --no-pager -T 'change_id.short() ++ "\n"'
```

Record this as `ORIGIN`. Use the **change ID**, not the commit ID —
resolving conflicts rewrites commits and their commit IDs change, but
the change ID stays stable. Every later step that moves the working
copy must return here at the end.

## Step 1 — Resolve scope

- **Scope** (optional) — `current` | `bookmark` | `stack`. Default
  `stack`.
  - `current` — only `ORIGIN` itself.
  - `bookmark` — `closest_bookmark(ORIGIN)..ORIGIN`.
  - `stack` — `trunk()..ORIGIN`.

Build the range in terms of `ORIGIN`, never the literal `@` — `@` will
point at whatever revision Step 2 last checked out, not the calling
revision, once the loop starts moving the working copy around.

Record the resolved range as `RANGE`. Anything outside `RANGE` —
behind trunk (or the bookmark), or a descendant of `ORIGIN` — is out
of scope for this run and must not be edited or checked out.

## Step 2 — Find and fix conflicts, closest to trunk first

Loop:

1. Find the conflicted revision(s) closest to trunk still in scope:

   ```
   jj log -r 'roots(RANGE & conflicts())' --no-pager \
     -T 'commit_id.short() ++ "\n"'
   ```

   `roots()` returns the members of the set with no ancestor also in
   the set — i.e., whichever conflicts are currently closest to trunk.
   If this is empty, scope is clean — go to Step 3.

2. Take one commit ID from that list, call it `TARGET`.

3. Spawn a sub-agent with this brief (fill in `TARGET`):

   > You are resolving one jj merge conflict.
   >
   > 1. `jj edit TARGET`
   > 2. `jj status` — lists every conflicted file under "There are
   >    unresolved conflicts at these paths".
   > 3. For each conflicted file, read it in full and resolve the
   >    conflict markers by editing the file directly. jj may render
   >    markers as git-style (`<<<<<<< / ======= / >>>>>>>`) or its
   >    native diff-style (`<<<<<<< / %%%%%%% / +++++++ / >>>>>>>`)
   >    depending on repo config — handle either. Use the surrounding
   >    context (the full function/block, not just the marked lines)
   >    to produce a resolution that preserves the intent of both
   >    sides. Do not blindly pick one side.
   > 4. Confirm the revision is clean:
   >    `jj log -r 'TARGET & conflicts()' --no-pager` must print
   >    nothing.
   > 5. **Do not** run `jj new`, `jj describe`/`jj desc`, or
   >    `jj push`. Do not check out any revision other than `TARGET`.
   >
   > Report back which files you resolved and a one-line description
   > of how each conflict was resolved.

4. Record the sub-agent's report for the summary in Step 4.

5. Re-run the query from step 1. Resolving `TARGET` can resolve, or
   newly expose, conflicts in descendant revisions via jj's automatic
   rebase — this is expected. Repeat the loop until the query is
   empty.

Do not spawn more than one sub-agent at a time — each `jj edit` moves
the single shared working copy, so conflicts must be fixed one
revision at a time, in order.

## Step 3 — Return to origin and verify

```
jj edit ORIGIN
```

Invoke the `assert-green` skill to confirm the stack still compiles,
lints, and passes unit tests. Do not report the work as done until
verification passes.

## Step 4 — Summary table

| Revision | Files resolved | Notes |
|---|---|---|
| [commit id] | [file list] | [one-line summary] |

One row per revision fixed in Step 2. If Step 2's first pass found no
conflicts, skip the table and report "No conflicts found in scope."

---
name: fix-divergent
description: >-
  Resolve divergent jj revisions — compare all versions, surface
  differences to the user, then abandon all but the one currently
  being edited. Use when a jj change is marked divergent, jj warns
  about divergence, or when asked to fix or resolve a divergent
  change or "??" marker.
---

# fix-divergent

Resolve a divergent jj change: compare all versions, surface
differences, abandon all but `@`.

**Hard rule:** Don't abandon anything until user explicitly approves.

## Step 1 — Find divergent changes

```
jj log -r 'divergent()' --no-pager
```

If output empty, report no divergent changes, stop.

## Step 2 — Collect all versions

Get change ID and commit ID for `@`, and every other commit sharing
its change ID. Run:

```
jj log --no-pager \
  -T 'commit_id.short() ++ " " ++ change_id.short() ++ " " ++ description.first_line() ++ "\n"'
```

Group rows by change ID. Group with more than one row = divergent
set. Identify which commit is `@`:

```
jj log -r @ --no-pager \
  -T 'commit_id.short() ++ " " ++ change_id.short() ++ "\n"'
```

Record:
- `KEEP` — commit ID `@` points to
- `ABANDON` — all other commit IDs in same divergent group(s)

## Step 3 — Compare versions

For each divergent set, diff every non-`@` commit against `@`:

```
jj diff --from <other_commit_id> --to <keep_commit_id> --no-pager
```

**If the diff is empty:** versions identical — no resolution needed
for this pair; move to the next pair. Identical versions still go
through Step 4's approval before anything is abandoned.

**If the diff is non-empty:** surface it to the user and ask:

> **Divergent change `<short_change_id>`** — A (commit `<keep_id>`,
> `@`) vs B (commit `<other_id>`). Diff: [paste diff above]
>
> Keep **(A)** what you're editing, **(B)** replace with Version B,
> or **(M)** resolve manually?

Wait for user's answer.

**If B:** `jj restore --from <other_commit_id>`, then confirm with
`jj diff -r @ --no-pager`.

**If M:** wait for user to say "done" before continuing.

## Step 4 — Confirm abandons

Present clear list of every commit that will be abandoned:

> Ready to abandon:
>
> | Commit | Change | Description |
> |--------|--------|-------------|
> | `<id>` | `<short_id>` | `<first line>` |
> | `<id>` | `<short_id>` | `<first line>` |
>
> Approve abandoning these? (yes / no)

Don't abandon until user says **yes**.

## Step 5 — Abandon

For each approved commit, use commit ID (not change ID) to avoid
ambiguity:

```
jj abandon <commit_id>
```

Repeat for every commit in the abandon list.

## Step 6 — Verify

```
jj log -r 'divergent()' --no-pager
```

If divergent changes remain, return to Step 2.

Otherwise report: "No divergent changes remain."

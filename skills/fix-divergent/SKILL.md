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
differences, then abandon all but `@`.

**Hard rule:** Do not abandon anything until the user has explicitly
approved.

## Step 1 — Find divergent changes

```
jj log -r 'divergent()' --no-pager
```

If output is empty, report no divergent changes and stop.

## Step 2 — Collect all versions

Get the change ID and commit ID for `@`, and for every other
commit that shares its change ID. Run:

```
jj log --no-pager \
  -T 'commit_id.short() ++ " " ++ change_id.short() ++ " " ++ description.first_line() ++ "\n"'
```

Group rows by change ID. Any group with more than one row is
a divergent set. Identify which commit is `@`:

```
jj log -r @ --no-pager \
  -T 'commit_id.short() ++ " " ++ change_id.short() ++ "\n"'
```

Record:
- `KEEP` — the commit ID that `@` points to
- `ABANDON` — all other commit IDs in the same divergent group(s)

## Step 3 — Compare versions

For each divergent set, diff every non-`@` commit against `@`:

```
jj diff --from <other_commit_id> --to <keep_commit_id> --no-pager
```

**If the diff is empty:** the versions are identical — no
resolution needed for this pair, skip to Step 5.

**If the diff is non-empty:** surface it to the user and ask:

> **Divergent change `<short_change_id>`** — A (commit `<keep_id>`,
> `@`) vs B (commit `<other_id>`). Diff: [paste diff above]
>
> Keep **(A)** what you're editing, **(B)** replace with Version B,
> or **(M)** resolve manually?

Wait for the user's answer.

**If B:** `jj restore --from <other_commit_id>`, then confirm with
`jj diff -r @ --no-pager`.

**If M:** wait for user to say "done" before continuing.

## Step 4 — Confirm abandons

Present a clear list of every commit that will be abandoned:

> Ready to abandon:
>
> | Commit | Change | Description |
> |--------|--------|-------------|
> | `<id>` | `<short_id>` | `<first line>` |
> | `<id>` | `<short_id>` | `<first line>` |
>
> Approve abandoning these? (yes / no)

Do not abandon until the user says **yes**.

## Step 5 — Abandon

For each approved commit, use the commit ID (not the change ID)
to avoid ambiguity:

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

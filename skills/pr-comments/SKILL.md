---
name: pr-comments
description: >-
  Address outstanding review comments on a GitHub PR. Given a PR review
  URL and a mode (auto | manual, default manual), stages a new jj
  revision on top of the bookmarked PR tip, loads the review, then
  either fixes every unresolved comment automatically or walks the user
  through each one for a fix/skip/investigate decision. Never posts
  comments or resolves threads on the PR. Use when the user pastes a PR
  review URL and asks to address, resolve, or fix up review comments, or
  invokes /pr-comments.
argument-hint: "<review-url> [auto|manual (default)]"
---

# PR Comments

**IMPORTANT:** This skill never writes to the PR itself — no comments,
no thread resolutions, no reviews. The only GitHub mutation it performs
is pushing commits (Step 5). All PR review API calls are read-only.

## Inputs

- **Review URL** (required) — a GitHub PR or PR-review URL, e.g.
  `https://github.com/<owner>/<repo>/pull/<number>` (optionally with a
  `#pullrequestreview-<id>` fragment, which is ignored — see Step 2).
- **Mode** (optional) — `auto` or `manual`. Default `manual`.

Parse `<owner>`, `<repo>`, and `<number>` from the URL up front; every
later `gh` call needs them.

## Step 1 — Stage a fixup revision

```
jj new -A @
jj bookmark list -r 'closest_bookmark(@-)' --no-pager
jj bookmark advance
```

Run in this order: `jj new -A @` inserts a fresh empty revision right
after the current `@` (rebasing any existing children of `@` onto it),
which becomes the new working-copy revision — plain `jj new` can leave
the stack in a bad shape if `@` isn't a head. The bookmark list call
(before advancing) records the bookmark's name while it still points at
the old `@` (now `@-`) — you need that name for Steps 2 and 5.
`jj bookmark advance` then moves that bookmark forward onto the new `@`
(its defaults — `--to @`, from `heads(::@ & bookmarks())` — do exactly
this).

Verify the tugged bookmark is actually the PR from the URL, not some
other revision in the stack:

```
gh pr view <bookmark-name> --json number
```

If the number doesn't match `<number>` from the URL, **halt** and
report the mismatch — do not guess which bookmark was intended.

## Step 2 — Load the review

Before pulling review comments, load the full PR change context — not
just the top-of-tree diff. Review comments point at lines that may
have been introduced several commits back in the stack, so you need
every revision in this PR, not just `@-`.

```
jj log -r 'closest_bookmark(@-)..@-' --no-pager
jj diff --from 'closest_bookmark(@-)' --to '@-' --no-pager
```

`@-` is the bookmarked PR tip captured in Step 1. `closest_bookmark(@-)`
resolves to the *parent* branch point here, not this PR's own bookmark
— Step 1 already advanced that bookmark onto `@`, so it no longer sits
on `@-`, and the lookup walks up to whatever bookmark this PR is
actually stacked on (trunk, if it isn't stacked on anything). Using
that instead of `trunk()` keeps the range scoped to this PR's own
commits when it sits on top of another bookmarked PR. The `log` call
shows every commit in the PR; the `diff` call shows their combined
effect, so a comment on a line touched two commits ago still resolves
against the right context.

Then invoke `keepers:load` on the review URL for orientation (PR
description, touched files, surrounding discussion).

The PR page itself won't reliably expose individual review comments to
a plain page fetch, so pull the structured, unresolved threads directly:

```
gh api graphql -f query='
  query($owner:String!, $repo:String!, $number:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes {
            id
            isResolved
            path
            line
            comments(first:50) { nodes { body author { login } url } }
          }
        }
      }
    }
  }' -f owner=<owner> -f repo=<repo> -F number=<number>
```

Keep only `isResolved == false` threads. A URL fragment naming a
specific review (`#pullrequestreview-<id>`) does not narrow this set —
address every outstanding thread on the PR, since a review is just one
batch of comments among possibly several. Sort the kept threads by
`(path, line)` so the walk order is stable across runs.

If there are zero unresolved threads, report that and stop — skip
Steps 3-5.

## Step 3 — Resolve each comment

For each thread, **investigate before acting**: read the file around
`path:line`, understand what the comment is pointing at, and form a
view on the right fix (or on why no fix is needed).

### Auto mode

For each thread, apply the fixup directly, then report one line:
comment summary → what changed (`file:line`). No confirmation between
threads.

### Manual mode (default)

Before walking threads, scan the sorted list for duplicates: threads
that raise the *exact same* request in different locations (e.g. the
same reviewer asking for the same rename, the same missing check, the
same nit — reworded or not — applied to multiple files/lines). Group
only on functional identity — same fix, same reasoning. A shared
*theme* or *pattern* across otherwise-distinct comments (different
fixes that happen to relate) does not qualify; treat those as
separate threads with their own fix/skip/investigate decision.

For each duplicate group, batch it: list every occurrence
(`file:line` + quoted body for each), ask the fix/skip/investigate
question once for the group, and apply the chosen action to every
occurrence in it. For everything else, walk threads individually, in
order:

1. Show the comment (author, `file:line`, quoted body) and your
   investigation (root cause, proposed fix) — label it `Comment i/N`
   (a batched group counts as one `i` for numbering purposes).
2. Ask the user to choose:
   - **Fix it** — apply the fixup(s), show the diff(s).
   - **Skip it** — leave as-is, note it as skipped.
   - **Investigate further** — open-ended conversation. Keep
     discussing (and fix inline if the user asks you to mid-conversation)
     until the user says the investigation is resolved and you should
     move on. Then continue to the next thread (or group).

Voice example (batched group):
> Comment 3/4 — 3 occurrences of the same request from `@reviewer`:
> "use `errors.Is` instead of `==`" at `retry.go:42`, `retry.go:88`,
> and `backoff.go:17`.
>
> Investigation: confirmed at all three — direct `==` comparisons on
> wrapped errors. Fix: swap each to `errors.Is`.

Voice example (correct, single comment):
> Comment 2/4 — `retry.go:42`, from `@reviewer`:
> "This increments on the wrong branch — should count failed attempts,
> not successful ones."
>
> Investigation: confirmed — `attempts++` sits inside the success
> branch, so a permanently-failing call never trips the retry cap.
> Fix: move the increment above the early return.

Counter-example (avoid):
> Applying all four fixes silently in manual mode, then asking "does
> this all look OK?" at the end — the user never got the per-comment
> fix/skip/investigate choice they asked for.

## Step 4 — Verify

Invoke `keepers:assert-green`. If it fails, **halt** — report what
failed, wait for the user to resolve it, then re-run
`keepers:assert-green`. Do not proceed to Step 5 until it passes.

## Step 5 — Describe and push

Invoke `keepers:jjdesc` to write the description for the new revision.
Then:

```
jj git push --bookmark <bookmark-name>
```

Using the bookmark name captured in Step 1.

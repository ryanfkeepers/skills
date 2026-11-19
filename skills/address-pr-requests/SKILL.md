---
name: address-pr-requests
description: >-
  Address outstanding review comments — both inline review-thread
  comments and top-level PR conversation comments — on a GitHub PR.
  Given a PR review URL and a mode (auto | manual | lens, default
  manual), stages a new jj revision on top of the bookmarked PR tip,
  loads the review, then either fixes every unresolved comment
  automatically or walks the user through each one for a
  fix/skip/investigate decision. Never posts comments; only lens mode
  resolves threads, and only those from automated reviewers. Use when the user
  pastes a PR review URL and asks to address, resolve, or fix up review
  comments, or invokes /address-pr-requests.
argument-hint: "<review-url> [auto|manual (default)|lens]"
---

# PR Comments

**IMPORTANT:** This skill never writes to the PR itself — no comments,
no reviews. It pushes commits (Step 5), and in `lens` mode only it
resolves review threads opened by **automated reviewers** once their fix
is pushed (Step 6). It never resolves a human's thread, in any mode. Every
other PR review API call is read-only.

**IMPORTANT:** Step 3 (resolving comments) is code-edit only. Agent
executing it must not describe, create, or push a revision, and must
not run any `jj` command modifying revision state directly
(`jj describe`, `jj new`, `jj squash`, `jj git push`, etc.). Only
allowance: editing files to address PR comments. Revision lifecycle
stays with Steps 1 (create), 4 (verify), 5 (describe, push) — never
Step 3.

## Inputs

- **Review URL** (required) — GitHub PR or PR-review URL, e.g.
  `https://github.com/<owner>/<repo>/pull/<number>` (optionally with a
  `#pullrequestreview-<id>` fragment, ignored — see Step 2).
- **Mode** (optional) — `auto`, `manual`, or `lens`. Default `manual`.
  `lens` is for the lens pipeline. It sorts each thread by author (Step 3)
  and adds Step 6.
- **Relay** (lens mode) — how to ask the user. The lens caller passes its
  question file; "ask the user" below means appending the question there
  and returning `needs_input` to the caller.

Parse `<owner>`, `<repo>`, `<number>` from URL up front; every later
`gh` call needs them.

## Step 1 — Stage a fixup revision

```
jj new -A @
jj bookmark list -r 'closest_bookmark(@-)' --no-pager
jj bookmark advance
```

Run in this order: `jj new -A @` inserts a fresh empty revision right
after the current `@` (rebasing any existing children of `@` onto it),
becoming the new working-copy revision — plain `jj new` can leave the
stack in a bad shape if `@` isn't a head. The bookmark list call
(before advancing) records the bookmark's name while it still points
at the old `@` (now `@-`) — you need that name for Steps 2 and 5.
`jj bookmark advance` then moves that bookmark onto the new `@` (its
defaults — `--to @`, from `heads(::@ & bookmarks())` — do exactly
this).

Verify the advanced bookmark is the PR from the URL, not some
other revision in the stack:

```
gh pr view <bookmark-name> --json number
```

If the number doesn't match `<number>` from the URL, **halt**, report
the mismatch — don't guess which bookmark was intended.

## Step 2 — Load the review

Before pulling review comments, load the full PR change context — not
just the top-of-tree diff. Review comments point at lines that may be
several commits back in the stack, so you need every revision in this
PR, not just `@-`.

```
jj log -r 'closest_bookmark(@-)..@-' --no-pager
jj diff --from 'closest_bookmark(@-)' --to '@-' --no-pager
```

`@-` is the bookmarked PR tip captured in Step 1. `closest_bookmark(@-)`
resolves to the *parent* branch point here, not this PR's own bookmark
— Step 1 already advanced that bookmark onto `@`, so it no longer sits
on `@-`, and the lookup walks up to whatever bookmark this PR is
actually stacked on (trunk, if not stacked on anything). Using that
instead of `trunk()` keeps the range scoped to this PR's own commits
when it sits atop another bookmarked PR. The `log` call shows every
commit in the PR; the `diff` call shows their combined effect, so a
comment on a line touched two commits ago still resolves against the
right context.

Then invoke `keepers:load` on the review URL for orientation (PR
description, touched files, surrounding discussion).

The PR page itself won't reliably expose individual review comments to
a plain page fetch, so pull the structured review threads *and* the
top-level (issue) comments directly — a reviewer's "please also check
X" on the PR conversation, not attached to a line, is easy to miss if
you only read `reviewThreads`:

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
            comments(first:50) { nodes { body author { login __typename } url } }
          }
        }
        comments(first:100) {
          nodes { id body author { login __typename } url createdAt }
        }
      }
    }
  }' -f owner=<owner> -f repo=<repo> -F number=<number>
```

From `reviewThreads`, keep only `isResolved == false` threads. A URL
fragment naming a specific review (`#pullrequestreview-<id>`) doesn't
narrow this set — address every outstanding thread on the PR, since a
review is just one batch of comments among possibly several.

Top-level `comments` carry no `isResolved` field — GitHub tracks
resolution only for review threads — so keep all of them every run.
Treat each as its own pseudo-thread with `path = null`, `line = null`.
Sort the merged list by `(path, line)`, null-path (top-level) entries
first, ordered among themselves by `createdAt`; this keeps the walk
order stable across runs. When presenting a top-level entry (Step 3),
label it `(top-level)` in place of `file:line`.

If zero outstanding threads and zero top-level comments, report that
and stop — skip Steps 3-5.

## Step 3 — Resolve each comment

Edit-only, per the top-level note — no revision-modifying
`jj` commands here; that belongs to Steps 1, 4, and 5.

For each thread, **investigate before acting**: read the file around
`path:line` (for a top-level comment, read whatever part of the diff
or codebase it references — no line to anchor on), understand what
the comment is pointing at, form a view on the right fix (or why no
fix is needed).

### Auto mode

For each thread, apply the fixup directly, then report one line:
comment summary → what changed (`file:line`, or `(top-level)` with no
line to cite). No confirmation between threads.

### Lens mode

Classify each thread by the author of its first comment:
- **Automated**: `author.__typename == "Bot"`, or the login ends in
  `[bot]`.
- **Human**: everyone else.

Then act by class:
- **Automated**: fix it as in auto mode. Remember the thread `id` for
  Step 6.
- **Human, trivial**: nit level with no behavior change (naming, a typo,
  a single-spot style fix). Fix it as in auto mode. Never resolve it.
- **Human, non-trivial**: run the manual flow below for it, asking through
  the relay. Never resolve it.

### Manual mode (default)

Before walking threads, scan the sorted list for duplicates: threads
raising the *exact same* request in different locations (e.g. the
same reviewer asking for the same rename, the same missing check, the
same nit — reworded or not — applied to multiple files/lines). Group
only on functional identity — same fix, same reasoning. A shared
*theme* or *pattern* across otherwise-distinct comments (different
fixes that happen to relate) doesn't qualify; treat those as separate
threads with their own fix/skip/investigate decision.

For each duplicate group, batch it: list the `file:line` of every
occurrence, quote the original body of one arbitrary occurrence as the
example, ask the fix/skip/investigate question once for the group, apply
the chosen action to every occurrence in it. For everything else, walk
threads individually, in order:

1. Show the comment (author, `file:line` or `(top-level)`) with its
   original body quoted verbatim, followed by your investigation (root
   cause, proposed fix) — label it `Comment i/N` (a batched group counts
   as one `i` for numbering). The quoted original is always shown
   alongside your summary and findings, never in place of them, and
   never omitted before the fix/skip/investigate question. For a
   batched group, quote one arbitrary occurrence as the example.
2. Ask the user to choose:
   - **Fix it** — apply the fixup(s), show the diff(s).
   - **Skip it** — leave as-is, note as skipped.
   - **Investigate further** — open-ended conversation. Keep
     discussing (fix inline if the user asks mid-conversation) until
     the user says the investigation is resolved and you should move
     on. Then continue to the next thread (or group).

Voice example (single comment; a batched group reads the same way, just
with every occurrence's location listed, one arbitrary occurrence
quoted, and one shared investigation):
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
failed, wait for the user to resolve it, re-run `keepers:assert-green`.
Don't proceed to Step 5 until it passes. In lens mode, report the failure
to the caller instead of waiting.

## Step 5 — Describe and push

Invoke `keepers:jjdesc` to write the description for the new revision.
In lens mode, give it the goal "address review comments" so it doesn't
stop to ask. Then:

```
jj git push --bookmark <bookmark-name>
```

Using the bookmark name captured in Step 1.

## Step 6 — Resolve automated threads (lens mode only)

After the push succeeds, resolve each **automated** thread you fixed:

```
gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id=<thread id>
```

Never resolve a human's thread, trivial or not. Top-level conversation
comments have no resolution on GitHub, so addressing them is enough. Report
which threads were resolved and which human threads are still open.

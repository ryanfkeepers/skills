---
name: pr-stack-re-approval
description: >-
  Re-approve a stack of GitHub PRs the user already reviewed once. Given
  one PR URL, lists the PRs in the stack (and nothing more up front) and,
  bottom to top, handles each PR on its own: checks it for merge
  conflicts, significant changes since the user's last review,
  unaddressed user comments, and changes unrelated to those comments or
  to the PR's purpose. Speaks per PR only through one color-bounded
  block: red (halting, needs review), yellow (unsure whether to approve),
  or green (approved automatically). Approves only when the approval
  rules allow, and never leaves an approval message unless the user
  dictates one. Use when the user pastes a PR URL and asks to re-approve,
  reapprove, or sign off on a stack they already reviewed, or invokes
  /pr-stack-re-approval.
argument-hint: "<pr-url>"
disable-model-invocation: true
---

# PR Stack Re-Approval

Decide, per PR in a stack, whether the user's earlier review still
stands. Approve what is safe to approve; stop and show the user
everything else.

**IMPORTANT:** The only GitHub write this skill performs is an approving
review in Step 5. No comments, no review bodies, no thread resolutions,
no change requests, no dismissals. An approval carries no message unless
the user states the exact text to write -- then use that text verbatim as
the review body and nothing else.

**IMPORTANT:** Approval is the user's judgment, lent to you under rules.
When a rule below says ask, only an explicit yes to *approve this PR*
counts as an answer.

Counter-example (avoid):
> A red block shows an unaddressed comment. User replies "go ahead".
> Agent approves a PR the user had marked "changes requested".

Voice example (correct):
> "Go ahead" does not name an action. The agent re-asks: "Approve PR
> #412, skip it, or stop?"

## Working model

Up front you know only *which PRs* are in the stack: number, title,
branches, state. Do not read diffs, reviews, or comments for any PR
until that PR's turn. There is no need to digest the stack's combined
changes before starting.

Each PR is a self-contained unit. Run Steps 2-5 to an outcome (approved,
skipped, halted, conflict, not reviewed before) for one PR before
loading anything for the next. Carry forward only the outcome, never the
previous PR's diff.

An **impassable problem** is anything that stops you deciding on *this*
PR alone: no baseline review, a base branch that is gone or
unresolvable, a PR-only diff you cannot compute, a GitHub API failure on
this PR. On one, stop work on that PR and print a red block (see
Output) stating the problem and what you tried. A fork or ambiguous
parent at a branch point is a choice, not a problem: print a yellow
block asking which path to follow. Apply the user's guidance (or skip
the PR if told to), then continue to the next PR.

Ask about the Nth PR only once you have finished the N-1th. Never
surface a question, forecast a problem, or request guidance about a
later PR (or a fork above the current PR) while an earlier PR is still
unfinished, even if you can already see the problem coming.

A problem on one PR never blocks the PRs that can be handled. Any PR
that can be handled individually must be. Stop the whole run only when
the user says to.

## Output

Print the stack table (Step 1) first and the summary table (Step 6)
last. Between them, each PR produces exactly one of the three blocks
below and nothing else. No progress narration, no per-step or per-check
status, no "nothing changed" notes. If a sentence does not ask the user
to review or decide something, do not print it.

Counter-examples (avoid):
> Phase 1 passed without issue, continuing to phase 2.

> 4 commits since your review but nothing really changed.

Copy the bars exactly as written; do not count or shorten them.

**Red -- halting.** Any check tripped, a merge conflict, or an
impassable problem. Must contain the PR URL, and the
`files/<reviewed-oid>..<head-oid>` link when a diff was computed.

```
🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥
**Halting on PR #<n> -- <problem>.** <pr-url>
<these changes> require your attention:
<tables from Step 4>
Approve PR #<n>, skip it, or stop?
🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥
```

For a merge conflict, the closing question drops "Approve": "Skip PR
#<n>, or stop?"

**Yellow -- unsure.** No check tripped but the Step 5 rules say ask, or
a fork needs a choice. Must contain the PR URL.

```
🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨
**PR #<n>** <pr-url>
No changes require your attention, but I'm unsure if I should approve
automatically because <reason>. Approve, or move to the next PR?
🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨
```

**Green -- approved.** Only after a successful approval in Step 5.

```
🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩
PR #<n> <title> -- all good, approved automatically. Moving on.
🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩
```

## Inputs

- **PR URL** (required) -- `https://github.com/<owner>/<repo>/pull/<number>`
  for any PR in the stack.

## GitHub access

All GitHub reads and the approval go through one script. Do not write
your own `gh`, `jq`, or helper scripts; the script already returns only
the fields the checks need.

`$P` is shorthand for `python3 ${CLAUDE_SKILL_DIR}/scripts/prstack.py`.
Write it out in full in every command, because shell variables do not
survive between calls.

```
$P stack <pr-url>
$P state   -R <owner>/<repo> <n>
$P changes -R <owner>/<repo> <n> <reviewed-oid> <head-oid> --base <base>
$P read    -R <owner>/<repo> <ref> <path> --lines A-B
$P approve -R <owner>/<repo> <n> <head-oid> [--body-file <file>]
```

Output is compact JSON (`read` prints numbered lines). Exit 1 prints
`{"status":"error","message":...}`: that is an impassable problem for
the PR. Call `gh` directly only for something no subcommand covers, and
say so in the PR's block.

"The user" below means the `login` that `state` returns.

## Step 1 -- Find the stack

This step reads PR metadata only. Do not fetch diffs, reviews, or
comments here. Run `$P stack <pr-url>` once. It walks down to the
default branch and up through every open descendant, and returns `prs`
(bottom to top, each with `state`, `parent` and `children`), `linear`
(bottom up to and including the first branch point), `forks`,
`ambiguous` (two open PRs share the parent branch), and `not_open`.

A fork does not halt the run: process `linear`, then, once the PR at
the branch point is finished, ask which child path(s) to follow (a
yellow block) and continue along that path's `children`. For an
`ambiguous` entry, process what is unambiguous and ask when that spot
is reached. `not_open` lists merged or closed PRs anywhere in the
stack. The walk continues past them, so the PRs above and below are
still found. Note them in the stack table and skip them.

Print the stack as a table (position, number, title, draft or not),
marking any fork, then process PRs bottom to top, one at a time. A
lower PR's change can invalidate everything above it, so the bottom goes
first.

## Step 2 -- Load the review state of one PR

Run `$P state -R <owner>/<repo> <n>`. It paginates everything and has
already retried an `UNKNOWN` merge state 3 times.

- **Merge conflicts first** -- `mergeable` is `CONFLICTING`: a PR with
  conflicts is a non-starter. Print a red block ("merge conflicts
  against `<base>`") and do not run Steps 3-5 on it. Still `UNKNOWN` is
  an impassable problem.
- **Last review** -- `prior_verdict` (`APPROVED`, `CHANGES_REQUESTED`,
  `COMMENTED`, `DISMISSED`) and `reviewed_oid` come from the user's most
  recent submitted review. When that review was later dismissed (usually
  a push dismissing a stale approval), `dismissed` is `true` and the
  script has recovered its original verdict from the PR's dismissal history, so
  `prior_verdict` is `APPROVED`, `CHANGES_REQUESTED`, or `COMMENTED` as
  if it had never been dismissed. `prior_verdict` stays `DISMISSED` only
  when the history has no record of the original verdict; Step 5 treats
  that as neither an approval nor a block.
- `reviewed_oid` is `null`: the user has no submitted review, so there
  is no baseline. This is an impassable problem: print a red block
  asking whether to skip the PR or stop, and do not run Steps 3-5 on it.
- **User comments in scope** -- `threads` (the ones the user started in
  the last review, `from_last_review: true`, plus earlier user threads
  still unresolved), `top_level` (the user's PR comments), and
  `last_review_body`. Each thread carries every reply, with `user:
  false` on the author's. A thread's `resolved` flag is set by whoever
  clicked the button, so a resolved thread from the last review is
  still checked against the code. `outdated: true` means `line` is the
  original line; find the code at head yourself.

## Step 3 -- Run the three checks

Run all three, then report once in Step 4. They overlap by design: one
read of the changes serves all of them.

### Compute the changes since the last review

Run `$P changes -R <owner>/<repo> <n> <reviewed_oid> <head> --base <base>`.
It compares the PR's own diff at the reviewed commit with its own diff
at head, so a rebase or a moved parent does not show up as change, and
neither do line shifts. `unchanged: true` means checks 1 and 3 pass
trivially and only check 2 has work to do. `link` is the URL to show the
user.

Each entry in `files` has a `path`, plus `renamed_from` when the file
moved since the review (a move with no `hunks` is a pure rename).
`header_changed` holds the git header when a mode bit, binary content,
or empty file changed, alongside any hunks. Each hunk has a `kind`:

- `new` -- in the PR now, not at review. `lines` is the hunk at head.
- `changed` -- edited since review. `delta` diffs the two versions of
  the hunk. Its first column is review→head and the rest of the line is
  the PR's own diff line, so `-+x` means "the PR used to add `x`" and
  `++y` means "the PR now adds `y`".
- `dropped` -- in the PR at review, gone now. `was` holds its changed
  lines.

`landed_in_base: true` on a `dropped` or `changed` hunk means the lines
that left the PR are now in the base branch: a parent was squash-merged
or rebased in. It is not a change by this PR, so it is insignificant.
A `dropped` hunk without that flag is a revert, so treat it as
significant. That holds even when the file's `in_head_diff` is `false`
(the PR no longer touches the file at all).

`generated_hint` flags lockfiles, mocks, snapshots, and `DO NOT EDIT`
markers. It is only a hint: you still classify each hunk.

Classify each changed hunk:

- **Insignificant** -- only code comments, doc prose, regenerated
  autogenerated files (`Code generated ... DO NOT EDIT`, lockfiles,
  mocks, snapshots) whose inputs are themselves insignificant, and pure
  renames (identifier or file moves with no other edit).
- **Significant** -- everything else, including tests, config,
  formatting-with-behavior, and any hunk you cannot confidently place in
  the insignificant list. Unsure means significant: a false halt costs
  the user a glance; a false approval costs trust.

### Check 1 -- Significant changes since the last review

Any significant hunk trips this check.

### Check 2 -- Significant user comments applied

A user comment is *significant* when it asks for a change in behavior,
logic, structure, or tests, or points out a defect. Praise, thanks,
answered questions, and comments prefixed `nit` are not significant.
Unaddressed nits do not trip the check; count them and mention the
count only inside a red or yellow block that is already being printed.

For each significant comment, read the code at its location in the
current head (`$P read -R <owner>/<repo> <head> <path> --lines A-B`, a
window around the comment's line, never the whole file) and decide:

- **Addressed** -- the current code does what the comment asked, or the
  concern no longer applies, and you can point at the lines.
- **Not addressed** -- the code still has the problem, including when
  the author only replied or resolved the thread without changing code.
  Quote the author's reply if there is one.

Any not-addressed comment trips this check.

### Check 3 -- Significant changes unrelated to the user's comments

Match each significant hunk from the diff above to the user comment it
answers. A hunk with no matching comment trips this check. Rank such
hunks by drift: compare each against the PR title and description, and
mark the ones that reach beyond the PR's stated purpose (new behavior,
new files or packages, changed public interfaces, touched areas the PR
did not previously touch).

## Step 4 -- Report and halt if any check tripped

If no check tripped, go to Step 5. Otherwise print one red block for
this PR and stop until the user replies. Inside the block:

- Link to the changes since the last review (Check 1).
- Table of not-addressed comments: `file:line` or `(top-level)`, the
  user's comment quoted verbatim, why it reads as not addressed (Check 2).
- Table of significant changes unrelated to any comment (Check 3):
  `file:line` | before | after | outside the PR's purpose? why.

Every description of a change since the last review states both
behaviors: what the code did at the reviewed commit and what it does at
head. "Refactored the exporter" or "touched `metrics.go`" is not a
description.

Voice example (correct):

```
🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥
**Halting on PR #412 -- 1 unaddressed comment, 1 unrelated change.** https://github.com/o/r/pull/412
Changes since your review at `a1b2c3d`: https://github.com/o/r/pull/412/files/a1b2c3d..e4f5a6b

| Comment | Your comment | Why not addressed |
| --- | --- | --- |
| `retry.go:42` | "increment on the failure path" | still increments in the success branch; author replied "intended" |

| Change | Before | After | Outside purpose? |
| --- | --- | --- | --- |
| `metrics.go:10-31` | no metrics exported | new Prometheus exporter on `:9090` | yes -- PR is a retry cap |

You last requested changes on this PR. Approve PR #412, skip it, or stop?
🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥
```

Counter-example (avoid -- dumping instead of reporting):
> Pasting the whole diff, or listing every hunk including comment-only
> ones.

An explicit "approve" goes to the approval call in Step 5 (skip the
decision table; the user has decided). "Skip" finishes the PR. Anything
that does not name an action ("go ahead", "ok"): re-ask the question.
Any other instruction: do what the user says; once that is done the PR
is finished, so continue to the next PR from Step 2 unless the user said
to stop.

## Step 5 -- Decide on approval

Reached only when no check tripped, or when the user explicitly said
approve in reply to a red or yellow block.

| Prior verdict | Checks tripped | Action |
| --- | --- | --- |
| any | yes | Red block (Step 4). |
| `CHANGES_REQUESTED` or `COMMENTED` | no | Yellow block; reason: your last review was changes-requested / comment-only. |
| `DISMISSED` | no | Yellow block; reason: your last review was dismissed and the PR history does not show its original verdict. |
| `APPROVED` | no | Approve, then green block. This includes a dismissed approval (`dismissed: true`). |

A dismissed review counts as whatever it was before the dismissal: a
dismissed approval is a prior approval, and a dismissed
changes-requested review is still a block (yellow, as in the
`CHANGES_REQUESTED` row).

To approve, run `$P approve -R <owner>/<repo> <n> <head>` with the
`head` you analyzed. The script re-reads the PR, refuses if the head
moved, and pins the approval to that commit. It sends no review body.
If the user dictated message text, write exactly that text to a file
and pass `--body-file <file>`.

GitHub still counts an approval pinned to an older commit unless the
repo dismisses stale approvals. A push that lands between the check and
the approval therefore cannot be prevented, only detected: the script
re-reads the head afterwards.

- `approved` -- print the green block.
- `approved_stale` (exit 3) -- the approval landed, but `head` moved
  past `commit` during the call. Print a red block saying the approval
  is on `commit`, not on the new `head`, and that the user may want to
  dismiss it. Do not dismiss it yourself, and do not rerun the PR.
- `head_moved` (exit 3) -- discard this PR's results and rerun Steps
  2-5 on it.
- `conflicting` (exit 3) -- Step 2's conflict rule applies.
- `error` -- the PR may have been updated mid-run: rerun Steps 2-5 on
  it from scratch, discarding every earlier result for it.

Rerun at most once per PR. If the approval fails again, print a red
block with `message` verbatim (own PR, branch protection, and the like
do not clear on retry).

After any outcome for this PR (approved, skipped, or halted and
guided), continue to the next PR in the stack from Step 2.

## Step 6 -- Summarize

When the stack is done or the user stops you, print one table: PR,
outcome (approved, approved stale, skipped, halted, conflict, not reviewed before), and
the reason in a few words. When a lower PR was not approved (skipped,
halted, or conflict), mark it so the user sees which upper PRs were
handled on top of an unresolved parent. Then stop -- no offers, no next
steps.

---
name: pr-stack-re-approval
description: >-
  Re-approve a stack of GitHub PRs the user already reviewed once. Given
  one PR URL, lists the PRs in the stack (and nothing more up front) and,
  bottom to top, handles each PR on its own: checks it for significant
  changes since the user's last review, unaddressed user comments, and
  changes unrelated to those comments or to the PR's purpose. Halts on a
  PR with a report when any check trips, or asks the user for guidance
  when that PR cannot be decided alone, then moves on to the next PR.
  Approves only when the approval rules allow, and never leaves an
  approval message unless the user dictates one. Use when the user
  pastes a PR URL and asks to re-approve, reapprove, or sign off on a
  stack they already reviewed, or invokes /pr-stack-re-approval.
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
When a rule below says ask, a prior "go ahead" about findings does not
count as an answer to the approval question.

Counter-example (avoid):
> Findings show an unaddressed comment. User replies "go ahead". Agent
> approves a PR the user had marked "changes requested".

Voice example (correct):
> "Go ahead" accepts the findings. The user last requested changes on
> this PR, so the agent asks "approve now?" as a separate question.

## Working model

Up front you know only *which PRs* are in the stack: number, title,
branches, state. Do not read diffs, reviews, or comments for any PR
until that PR's turn. There is no need to digest the stack's combined
changes before starting.

Each PR is a self-contained unit. Run Steps 2-5 to an outcome (approved,
skipped, halted, not reviewed before) for one PR before loading anything
for the next. Carry forward only the outcome, never the previous PR's
diff.

An **impassable problem** is anything that stops you deciding on *this*
PR alone: a fork or ambiguous parent at a branch point, no baseline
review, a base branch that is gone or unresolvable, a PR-only diff you
cannot compute, a GitHub API failure on this PR. On one, stop work on
that PR, state the problem and what you tried, and ask the user for
guidance. Apply the guidance (or skip the PR if told to), then continue
to the next PR.

Ask about the Nth PR only once you have finished the N-1th. Never
surface a question, forecast a problem, or request guidance about a
later PR (or a fork above the current PR) while an earlier PR is still
unfinished, even if you can already see the problem coming.

A problem on one PR never blocks the PRs that can be handled. Any PR
that can be handled individually must be. Stop the whole run only when
the user says to.

## Inputs

- **PR URL** (required) -- `https://github.com/<owner>/<repo>/pull/<number>`
  for any PR in the stack. Parse `<owner>`, `<repo>`, `<number>` up front.

Get the user's login once: `gh api user --jq .login`. Every "the user's
review" below means reviews and comments authored by that login.

## Step 1 -- Find the stack

This step reads PR metadata only. Do not fetch diffs, reviews, or
comments here.

```
gh pr view <number> --json number,baseRefName,headRefName,state,isDraft,title,url
```

Walk down: find the open PR whose `headRefName` equals this PR's
`baseRefName`, repeat until the base is the repo's default branch. Walk
up: `gh pr list --base <headRefName> --state open --json number,headRefName,title,url`
for each PR, repeat until none remain. Order bottom to top.

If any branch point has two or more child PRs, the stack forks. Do not
halt the run: record the fork, order the linear part up to the branch
point, and process it. Ask the user which child path(s) to follow only
once the PR at the branch point is finished, then continue. Do the same
when walking down finds two open PRs sharing a `headRefName`: process
what is unambiguous, ask when that spot is reached. Skip merged and closed PRs; note
them.

Print the stack as a table (position, number, title, draft or not),
marking any fork, then process PRs bottom to top, one at a time. A
lower PR's change can invalidate everything above it, so the bottom goes
first.

## Step 2 -- Load the review state of one PR

```
gh api graphql -f query='
  query($owner:String!, $repo:String!, $number:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$number) {
        title body headRefOid
        reviews(first:100) {
          nodes { author { login } state submittedAt commit { oid } }
        }
        reviewThreads(first:100) {
          nodes {
            isResolved path line originalLine
            comments(first:50) {
              nodes { author { login } body url createdAt originalCommit { oid } }
            }
          }
        }
        comments(first:100) {
          nodes { author { login } body url createdAt }
        }
      }
    }
  }' -f owner=<owner> -f repo=<repo> -F number=<number>
```

Paginate any connection that reports more pages.

- **Last review** -- the user's most recent submitted review (any state).
  Its `state` is the *prior verdict* (`APPROVED`, `CHANGES_REQUESTED`,
  `COMMENTED`); its `commit.oid` is the *reviewed commit*.
- If the user has no submitted review on this PR there is no baseline to
  compare against. This is an impassable problem (see Working model):
  report it, ask whether to skip the PR or stop, and do not run Steps
  3-5 on it. If skipped, continue to the next PR.
- **User comments in scope** -- threads the user started in the last
  review, plus any earlier user thread still unresolved, plus the user's
  top-level PR comments. A thread's `isResolved` flag is set by whoever
  clicked the button, so a resolved thread from the last review is still
  checked against the code.

## Step 3 -- Run the three checks

Run all three, then report once in Step 4. They overlap by design: one
read of the changes serves all of them.

### Compute the changes since the last review

If the reviewed commit equals `headRefOid`, nothing changed; checks 1
and 3 pass trivially and only check 2 has work to do.

Otherwise diff the PR's own changes, not raw head-to-head. When the PR
was rebased or its base moved (the parent PR changed), a head-to-head
diff includes the parent's changes and drowns the PR's own. Get each
side's PR-only diff (`merge-base...head`, via
`gh api repos/<owner>/<repo>/compare/<base>...<head>`) for the reviewed
commit and the current head, then compare those two diffs, ignoring
line-number shifts. When the base did not move,
`gh api repos/<owner>/<repo>/compare/<reviewed-oid>...<head-oid>` is
enough.

The link to show the user is
`https://github.com/<owner>/<repo>/pull/<number>/files/<reviewed-oid>..<head-oid>`.

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
Count unaddressed nits and mention the count in one line; they do not
trip the check.

For each significant comment, read the code at its location in the
current head and decide:

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

If no check tripped, go to Step 5. Otherwise print one report for this
PR and stop until the user replies:

- Link to the changes since the last review (Check 1).
- Table of not-addressed comments: `file:line` or `(top-level)`, the
  user's comment quoted verbatim, why it reads as not addressed (Check 2).
- Table of significant changes unrelated to any comment: `file:line`,
  one-line summary, whether it drifts from the PR's purpose and why
  (Check 3).

When the Step 5 rules will require asking anyway (see below), end the
report with that question so one reply covers both.

Voice example (correct):
> PR #412 `dp-1234/retry-cap` -- you requested changes at `a1b2c3d`.
> Changes since: https://github.com/o/r/pull/412/files/a1b2c3d..e4f5a6b
> Not addressed (1): `retry.go:42` -- "increment on the failure path" --
> code still increments in the success branch; author replied "intended".
> Unrelated significant changes (1): `metrics.go:10-31` -- adds a new
> exporter; outside the PR's retry-cap purpose.
> "Go ahead" accepts these. I'll then ask separately whether to approve,
> since your last review was changes-requested.

Counter-example (avoid -- dumping instead of reporting):
> Pasting the whole diff, or listing every hunk including comment-only
> ones.

A reply of "go ahead" (or equivalent) means the user accepts these
findings for this PR. Continue to Step 5 for the same PR. Any other
reply: do what the user says; once that is done the PR is finished, so
continue to the next PR from Step 2 unless the user said to stop.

## Step 5 -- Decide on approval

Use the prior verdict from Step 2 and whether Check 1 found significant
changes:

| Prior verdict | Significant changes since | Action |
| --- | --- | --- |
| `CHANGES_REQUESTED` or `COMMENTED` | any | Ask before approving. Say plainly if the user had requested changes. |
| `APPROVED` | yes | Ask what to do: approve, skip this PR, or stop. |
| `APPROVED` | no | Approve, then move to the next PR. |

"Ask" means a direct question and a wait. Only an explicit yes to
*approve this PR* counts; silence, "go ahead" about findings, or
approval of a different PR does not.

To approve, pin the approval to the commit you analyzed so a push that
landed mid-run cannot be approved unseen:

```
gh api repos/<owner>/<repo>/pulls/<number>/reviews \
  -f event=APPROVE -f commit_id=<head-oid-analyzed>
```

Send no `body` field. If the user dictated message text, send exactly
that as `body`. If the call fails (own PR, stale commit, branch
protection), report the error and ask the user for guidance.

After any outcome for this PR (approved, skipped, or halted and
guided), continue to the next PR in the stack from Step 2.

## Step 6 -- Summarize

When the stack is done or the user stops you, print one table: PR,
outcome (approved, skipped, halted, not reviewed before), and the
reason in a few words. When a lower PR was not approved (skipped or
halted), mark it so the user sees which upper PRs were handled on top of
an unresolved parent. Then stop -- no offers, no next steps.

---
name: evaluate-pr-stack
description: >-
  Score every PR in a GitHub PR stack for human review readiness (0-10) and
  say whether the stack is ready to hand to human reviewers. Each PR is scored
  by its own sub-agent on line count (generated code excluded), whether it
  should have been split, whether AI review comments are resolved, and
  whether a change visualization is available. Prints one table, nearest
  trunk first, with green/yellow/red lights and a very short cause for any
  PR that scored under 8. Use when the user pastes a PR URL and asks if the
  stack is ready for review, ready for humans, reviewable, or too big, asks
  to score or rate a PR stack, or invokes /evaluate-pr-stack.
argument-hint: "<pr-url>"
---

# Evaluate PR Stack

Answer one question: is this stack ready for a human to review? Score each
PR on its own, then show the user a table and a verdict.

This skill is read-only. It never comments on, resolves, approves, or edits
a PR.

## Inputs

- **PR URL** (required): `https://github.com/<owner>/<repo>/pull/<n>` for
  any PR in the stack. Ask for it when missing.
- Optionally, the user may already say which PRs have a visualization.
  Use that and skip Step 3's question.

`$S` below is `python3 ${CLAUDE_SKILL_DIR}/scripts/prfacts.py`. Write it
out in full in every command; shell variables do not survive between calls.

## Rubric (10 points)

| Points | Criterion | Scored by |
| --- | --- | --- |
| 5 | Line count of handwritten code, tests included, generated code excluded: under 500 = 5, under 700 = 3, under 800 = 1, else 0 | sub-agent |
| 2 | Appropriate split: not sensibly splittable = 2; splittable but under 500 LoC = 1; easily split into smaller PRs (renames or movement apart from logic, new package apart from wiring, version bumps apart from logic) = 0 | sub-agent |
| 2 | AI review comments: every AI-authored thread resolved = 2, otherwise 0 | sub-agent |
| 1 | The user reports a change visualization is available. A nominal change (minor movement, rename, bump) gets the point with no question | user, via Step 3 |

Lights: 8 or more is green, 6 or 7 is yellow, 5 or less is red.

The rubric lives in `scorer.md` too, in the form the sub-agents apply. When
you change a threshold, change both.

## Step 1: Find the stack

Run `$S stack <pr-url>`. It returns `prs` bottom to top (nearest the trunk
first), each with `number`, `title`, `url`, `state`, `parent`, and also
`forks` and `not_open`.

Score every open PR in `prs`, including both branches at a fork. Skip PRs
in `not_open` (merged or closed) and name them in one line under the table.
Draft PRs are scored like any other.

## Step 2: Score each PR in its own sub-agent

Launch one `general-purpose` sub-agent per open PR, all in a single
message so they run in parallel. Separate agents keep one PR's diff from
shaping another's score, and keep this conversation free of diffs. Do not
read diffs or run `facts` yourself.

Prompt for each:

```
Read ${CLAUDE_SKILL_DIR}/scorer.md and follow it for this PR.
repo: <owner>/<repo>
number: <n>
url: <url>
facts script: ${CLAUDE_SKILL_DIR}/scripts/prfacts.py
```

Each returns one JSON object (see `scorer.md` Output). Retry an agent whose
reply is not valid JSON once. A second failure, or an `error` reply, makes
that PR a failed row in the table (Step 4). It does not stop the others.

## Step 3: The visualization point

Only PRs whose reply has `nominal: false` need the user. List them and ask
once, in a single message:

```
⚠️ Which of these have a change visualization ready for you to review?
  #412 Add retry cap
  #413 Split exporter   (PR links https://claude.ai/artifact/...)
Reply with numbers, "all", or "none".
```

Show a PR's `viz_links` beside it as a hint, since a link in the PR is not
proof the user has reviewed it. The user's answer decides. Nominal PRs get
the point automatically. If every scored PR is nominal, ask nothing.

## Step 4: Compute and print

Per PR: `loc_points + split_points + ai_points + viz_point`, where
`viz_point` is 1 for nominal PRs and for PRs the user confirmed, else 0.
Add the agent's causes in order, and append "no visualization" when that
point was lost for a non-nominal PR.

Print one table, rows in `prs` order (nearest the trunk first). Three
columns:

| Rating | PR | Cause |
| --- | --- | --- |
| 🟩 9/10 | [#411 Add retry config](url) | |
| 🟨 7/10 | [#412 Add retry cap](url) | 640 LoC; no visualization |
| 🟥 4/10 | [#413 Export metrics](url) | 910 LoC; new pkg splittable from wiring |

- Rating is the light emoji, then `n/10`.
- PR is the number and title, hyperlinked to the PR.
- Cause shows only for yellow and red, as the agent's short phrases joined
  with `;`. Keep every cause under about 12 words. Leave green rows blank.
- At a fork, add `(on #<parent>)` after the title of each PR in the
  branches, so the order still reads as a tree.
- A failed PR gets `🛑 N/A`, and its cause is the one-line error. It counts
  as not ready.

Below the table, print one verdict line:

- All scored PRs green and none failed: **Ready for human review.**
- Otherwise: **Not ready for human review:** followed by the count of
  yellow, red, and failed PRs.

Then list any skipped `not_open` PRs in one line. Stop there: no offers, no
suggested fixes. The user asked for a score, and causes already say what to
change.

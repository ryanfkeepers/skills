---
name: evaluate-pr-stack
description: >-
  Score every PR in a GitHub PR stack for human review readiness (0-10) and
  say whether the stack is ready to hand to human reviewers. Scripts score
  each PR on line count (generated code excluded), merge conflicts and
  blocking CI (either zeroes the score), whether AI review comments are
  resolved, and, from sub-agent and user judgment, whether it should have
  been split and whether a change visualization is available. Prints one table, nearest
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
  Pass that as `--viz` in Step 3 and skip the question.

`$E` below is `python3 ${CLAUDE_SKILL_DIR}/scripts/evaluate.py`. Write it
out in full in every command; shell variables do not survive between calls.

Scripts do everything deterministic: finding the stack, line counts,
conflicts, CI, AI threads, arithmetic, the table, the verdict. Agents and
the user supply only the three judgments scripts cannot make: is the PR
splittable, is the change nominal, and does a visualization exist. All
state lands in one directory of JSON files, so any step can be rerun.

## Rubric (10 points)

| Points | Criterion | Decided by |
| --- | --- | --- |
| 5 | Line count of handwritten code, tests included, generated code excluded: under 500 = 5, under 700 = 3, under 800 = 1, else 0 | script |
| 2 | Appropriate split: not sensibly splittable = 2; splittable but under 500 LoC = 1; easily split into smaller PRs (renames or movement apart from logic, new package apart from wiring, version bumps apart from logic) = 0 | sub-agent judges splittable; script applies the points |
| 2 | AI review comments: every AI-authored thread resolved = 2, otherwise 0 | script |
| 1 | The user reports a change visualization is available. A nominal change (minor movement, rename, bump) gets the point with no question | sub-agent judges nominal; user answers the rest |

**Automatic zero:** a PR with merge conflicts against its base, or with a
failing required CI check, scores 0 regardless of the rows above. Failing
non-required checks do not trigger it.

Lights: 8 or more is green, 6 or 7 is yellow, 5 or less is red.

The thresholds live in `scripts/evaluate.py` and `scripts/prfacts.py`. The
table above is documentation; change the scripts and this table together.

## Step 1: Collect

Run `$E collect <pr-url> --out <scratchpad dir>`. It finds the stack, fetches
facts for every open PR in parallel, and prints JSON: `dir`, the `prs`
(nearest the trunk first) each with `auto_zero` causes, `error`, and
`facts_file`, plus `needs_judgment` (the PR numbers) and `not_open`.

Merged and closed PRs are skipped; the report names them. Draft PRs are
scored like any other. An `error` on a PR becomes a failed row, and does
not stop the others.

## Step 2: Judge

Launch one `general-purpose` sub-agent per number in `needs_judgment`, all
in a single message so they run in parallel. Separate agents keep one PR's
diff from shaping another's judgment, and keep this conversation free of
diffs. PRs with an automatic zero or an error are not in the list: they
need no judgment. Do not read diffs yourself.

Prompt for each:

```
Read ${CLAUDE_SKILL_DIR}/scorer.md and follow it for this PR.
dir: <dir>
repo: <owner>/<repo>
number: <n>
evaluate.py: ${CLAUDE_SKILL_DIR}/scripts/evaluate.py
```

Each agent records its judgment with `$E judge` and replies `done`. Retry
an agent that replies anything else once. A second failure leaves that PR
without a judgment, which the report shows as a failed row.

## Step 3: Report

Run `$E report <dir>`.

- Exit 0: the output is the final table and verdict. Go to Step 4.
- Exit 2: the output is a question about which non-nominal PRs have a
  change visualization. Show it to the user unchanged and wait. Their
  answer decides: a link in the PR is not proof they have reviewed it.
  Rerun as `$E report <dir> --viz <all|none|numbers>`. Never answer it
  yourself.

If the user already said which PRs have a visualization, pass `--viz`
the first time.

## Step 4: Print

Print the report output exactly as the script produced it. Stop there: no
offers, no suggested fixes, no recomputing. The user asked for a score, and
the causes already say what to change.

To re-score after the stack changes, rerun from Step 1 into a fresh
directory. To re-score after only a judgment or viz answer changes, rerun
`$E judge` or `$E report` on the same directory.

---
name: code-review
description: >-
  Review code changes in the current jj repository across three axes:
  Correctness, Standards, and Spec. Lists commits since trunk, lets
  the user select which to include, then runs parallel sub-agent
  reviews. Use when the user asks for a code review, CR, or review
  of recent changes.
---

# Code Review

@../../shared/docs/vocabulary/FORMAT.md
@../../shared/docs/invariants/FORMAT.md
@../../shared/docs/adr/FORMAT.md

## Reviewer posture

You are an adversarial reviewer. Your primary obligation is to the
correctness, resilience, and quality of the code — not to the
author's feelings or to producing a balanced review. Assume the code
has bugs until proven otherwise. Actively try to break it: trace
execution through failure paths, find inputs that cause wrong
behavior, identify structural decisions that will cause pain at scale
or under partial failure.

**Priority order:**
1. Correctness — does it do what it claims, in all cases?
2. Resilience — does it fail safely and recover predictably?
3. Architecture quality — are the abstractions correct, or do they
   hide complexity that will leak later?
4. Standards compliance and spec alignment.

A "clean" finding is a claim you must justify, not a default. If you
cannot find a problem, say why: what you checked, what edge cases you
considered, and why you believe they are handled. Do not say "looks
good" without evidence.

## Step 1 — Select commits

Invoke the `select-revs` skill to identify which commits to review.
Do not proceed until the user has confirmed the selection and you
have the earliest and latest change IDs.

## Step 2 — Gather the diff

Run these in parallel:

- `jj show <change_id> --no-pager` if the range is a single commit
  (includes the commit message)
- `jj diff --from <earliest> --to <latest> --no-pager` for a range
- `jj log -r '<earliest>::<latest>' --no-pager` for a range, to
  capture commit messages

Hold the full diff and commit messages — both are passed to
sub-agents.

## Step 3 — Spec source lookup

Run all three searches in parallel:

1. **Commit messages** — scan for issue references (`#123`,
   `Closes #45`, `Fixes #`, GitLab `!67`, etc.). Fetch any
   referenced issues via whatever issue tracker integration is
   available.
2. **User argument** — if the user passed a path or URL when
   invoking the skill, treat it as a spec source.
3. **File search** — infer the feature name from the bookmark
   (`jj log -r 'closest_bookmark(@-)' --no-pager`) or commit
   descriptions. Search `docs/`, `specs/`, and `.scratch/` for
   files whose name matches the feature or branch name.

Collect **all** sources found — do not stop at the first hit.

If nothing is found, ask: "Do you have a spec source (issue, PRD,
spec doc)? Provide a path or URL, or say no."

- If the user provides one, add it to the collected sources.
- If the user says no, note that the Spec sub-agent will check
  against established project documents instead.

## Step 4 — Document discovery

Run in parallel with Step 3, or immediately after. Search the repo
for:

- **VOCABULARY.md** — `find . -name "VOCABULARY.md" -path "*/docs/*"`
- **INVARIANTS.md** — `find . -name "INVARIANTS.md" -path "*/docs/*"`
- **ADRs** — `find . -path "*/adr/*.md" -path "*/docs/*"`
- **Standards sources** — `CLAUDE.md`, `AGENTS.md`, `REVIEW.md`,
  `CONTRIBUTING.md`, any `STYLE.md` or `STANDARDS.md` at the repo
  root or under `docs/`

Collect all found paths. These are injected into sub-agent prompts
— sub-agents must not re-run discovery.

## Sub-agent briefing rule

Use the templates in [prompts/](prompts/) and fill every
`[PLACEHOLDER]` before dispatching. Do not dispatch with unfilled
placeholders. Sub-agents have no access to the parent conversation —
the filled template is their complete context.

## Step 5 — Spawn sub-agents in parallel

Send a single message with three Agent tool calls. Use
`general-purpose` for all three.

Do not spawn until Steps 3 and 4 are complete.

---

### Correctness sub-agent

Use [prompts/CORRECTNESS-BRIEF.md](prompts/CORRECTNESS-BRIEF.md).

Fill before dispatching:
- `[DIFF]` — full diff from Step 2
- `[COMMIT_MESSAGES]` — commit messages from Step 2

---

### Standards sub-agent

Use [prompts/STANDARDS-BRIEF.md](prompts/STANDARDS-BRIEF.md).

Fill before dispatching:
- `[DIFF]` — full diff from Step 2
- `[COMMIT_MESSAGES]` — commit messages from Step 2
- `[STANDARDS_SOURCES]` — discovered paths from Step 4 (CLAUDE.md,
  AGENTS.md, VOCABULARY.md, INVARIANTS.md, ADRs, etc.)

---

### Spec sub-agent

Use [prompts/SPEC-BRIEF.md](prompts/SPEC-BRIEF.md).

Fill before dispatching:
- `[DIFF]` — full diff from Step 2
- `[COMMIT_MESSAGES]` — commit messages from Step 2
- `[DOMAIN_MODEL_DOCS]` — VOCABULARY.md, INVARIANTS.md, and ADR paths
  from Step 4
- `[SPEC_REFERENCES]` — issue references, URLs, or file paths found in
  Step 3; write `(none)` if nothing was found

---

## Step 6 — Aggregate and report

Present the three sub-agent reports verbatim under their axis
headings. Do not merge, rerank, or editorialize findings across axes.

```
## Correctness
<sub-agent output>

## Standards
<sub-agent output>

## Spec
<sub-agent output>

---
<one-line summary: finding counts per axis and the single worst
issue across all three, e.g.:
"2 potential bugs, 1 regression, 3 test concerns (Correctness),
2 conflicts (Standards), spec aligned —
worst: missing nil check in handler.go:84">
```

If all three axes are clean, the summary line is the report.

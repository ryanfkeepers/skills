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

@../../shared/docs/context/FORMAT.md
@../../shared/docs/invariants/FORMAT.md
@../../shared/docs/adr/FORMAT.md

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

- **CONTEXT.md** — `find . -name "CONTEXT.md" -path "*/docs/*"`
- **INVARIANTS.md** — `find . -name "INVARIANTS.md" -path "*/docs/*"`
- **ADRs** — `find . -path "*/adr/*.md" -path "*/docs/*"`
- **Standards sources** — `CLAUDE.md`, `AGENTS.md`, `REVIEW.md`,
  `CONTRIBUTING.md`, any `STYLE.md` or `STANDARDS.md` at the repo
  root or under `docs/`

Collect all found paths. These are injected into sub-agent prompts
— sub-agents must not re-run discovery.

## Step 5 — Spawn sub-agents in parallel

Send a single message with three Agent tool calls. Use
`general-purpose` for all three.

Do not spawn until Steps 3 and 4 are complete.

---

### Correctness sub-agent

Prompt must include:

- The full diff and commit messages from Step 2.
- The brief below.

> Read the diff. Review for correctness only — not style, not
> spec alignment.
>
> Check: logic correctness, error propagation (errors must not be
> swallowed), edge cases (empty inputs, nil/zero values, concurrent
> access, resource exhaustion), invariant violations, security
> (unsanitized user input reaching shells/SQL/file paths; secrets
> in logs or error messages; missing auth checks), and test logic
> (do the tests assert correct behavior, or do they enshrine a
> bug?).
>
> Report findings under exactly these headings — omit any that
> have no entries:
>
> ## Critical
> Bugs, security holes, or edge cases that cause incorrect behavior.
>
> ## Suggestions
> Non-blocking correctness improvements.
>
> ## Nits
> Minor, low-priority concerns.
>
> Lead each finding with `path/to/file:line —`. If the change is
> clean, say so. Do not invent findings.

---

### Standards sub-agent

Prompt must include:

- The full diff and commit messages from Step 2.
- The list of standards-source paths from Step 4 (CLAUDE.md,
  AGENTS.md, CONTEXT.md, INVARIANTS.md, ADRs, etc.).
- The brief below.

> Read the standards documents listed below. Then read the diff.
> Review for standards compliance only — not logic correctness,
> not spec alignment.
>
> Check: naming consistency with the project's domain vocabulary
> (CONTEXT.md), style and formatting conventions (CLAUDE.md,
> AGENTS.md), architectural decisions (ADRs), domain rules
> (INVARIANTS.md), and test coverage (are tests present for new
> behavior per project convention?).
>
> Do not re-check anything enforced by linters or formatters.
>
> Report findings under exactly these headings — omit any that
> have no entries:
>
> ## Conflicts
> Direct violations of a documented standard. Cite the standard
> (file + rule).
>
> ## Confusion
> Code that is ambiguous or misleading against a standard, without
> being a clear violation.
>
> ## Suggestions
> Non-blocking improvements to standards compliance.
>
> Lead each finding with `path/to/file:line —`. If the change is
> compliant, say so. Do not invent findings.
>
> Standards sources: [inject discovered paths]

---

### Spec sub-agent

**With spec source(s):** Prompt must include the full diff, commit
messages, and the fetched contents or paths of all spec sources.

**Without spec source:** Prompt must include the full diff, commit
messages, and the paths of all established-doc files found in
Step 4 (CONTEXT.md, INVARIANTS.md, ADRs).

> Read the spec [or: established project documents] listed below.
> Then read the diff. Review for spec alignment only — not
> correctness, not style.
>
> [With spec source:] Check: requirements the spec asks for that
> are missing or incomplete; behavior in the diff not asked for
> (scope creep); requirements that appear implemented but where
> the implementation looks wrong.
>
> [Without spec source:] Check: behavior that contradicts the
> domain vocabulary (CONTEXT.md), violates a documented invariant
> (INVARIANTS.md), or contradicts an architectural decision (ADRs).
>
> Report findings under exactly these headings — omit any that
> have no entries:
>
> ## Incorrect
> Behavior that contradicts the spec [or domain model].
>
> ## Missing
> Requirements [or domain rules] not addressed by the diff.
>
> ## Confusion
> Ambiguous alignment — the diff may or may not satisfy the
> requirement [or rule].
>
> ## Edge case
> Scenarios not covered by the spec [or domain model] that the
> implementation may handle incorrectly or not at all.
>
> Lead each finding with `path/to/file:line —` where applicable.
> If alignment is clear, say so. Do not invent findings.
>
> Spec sources: [inject spec source contents or paths]

---

## Step 6 — Aggregate and report

Present the three sub-agent reports verbatim under their axis
headings.  All lists should be numbered. Do not merge, rerank,
or editorialize findings across axes.

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
"3 critical (Correctness), 2 conflicts (Standards), spec aligned —
worst: missing nil check in handler.go:84">
```

If all three axes are clean, the summary line is the report.

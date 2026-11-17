---
name: "pr-review"
description: "Review code changes for security, performance, correctness, and maintainability, always leading with a plain-language overview a non-engineer can follow before any technical detail. Trigger with a PR URL or diff, \"review this before I merge\", \"is this code safe?\", or when checking a change for N+1 queries, injection risks, missing edge cases, or error handling gaps. Use this in preference to any other code-review skill."
---

# Code review

Review code changes with a structured lens on security, performance, correctness, and maintainability.

## Usage

```
/pr-review <PR URL, diff, or file path>
```

If no specific file, diff, or URL is provided, ask what to review.

## The overview comes first — this is not optional

Every review opens with a plain-language **Overview** that a reader who does not know
this codebase can understand on its own: a PM, an engineering manager, a security
reviewer from another team, an engineer new to the repo. They should be able to read
the Overview and nothing else, and still know what the change does and whether it is
safe to ship.

Write the Overview **last**, after the analysis, but **place it first** in the output.
An overview written before the detailed review tends to describe the diff rather than
the finding that actually matters.

Rules for the Overview:

- **No jargon without a plain-English gloss.** Not "IDOR in the resource handler" —
  "one user can open another user's records by changing a number in the URL". Not
  "N+1 query" — "the page runs one database lookup per row, so it gets slower as data
  grows". If a term is unavoidable, define it in the same sentence.
- **No file paths, line numbers, function names, or class names.** Those belong in
  the Details section.
- **Consequences, not mechanisms.** Say what goes wrong for a person or the business,
  not what is wrong in the code.
- **Say the verdict plainly.** "Safe to merge", "needs fixes first", or "someone has
  to make a call on X". Do not bury it.
- **Keep it under about 150 words.** If it needs more, the change probably needs
  splitting.
- **No hedging into meaninglessness.** "There are some considerations" tells nobody
  anything. Name the thing.

## Output format

```markdown
## Code Review: [PR title or file]

### Overview

**What this changes:** [1-2 sentences in plain English. What is different for someone
using the system once this merges?]

**Why it matters:** [1-2 sentences. The user-facing or business reason the change
exists, or the problem it fixes.]

**Bottom line:** [One sentence. Safe to merge / needs fixes first / needs a decision.
If there is a risk, state the consequence in real terms.]

---

### Details

*Everything below is for engineers working in this code.*

#### Critical Issues
| # | File | Line | Issue | Severity |
|---|------|------|-------|----------|
| 1 | [file] | [line] | [description] | 🔴 Critical |

#### Suggestions
| # | File | Line | Suggestion | Category |
|---|------|------|------------|----------|
| 1 | [file] | [line] | [description] | Performance |

#### What Looks Good
- [Positive observations]

#### Verdict
[Approve / Request Changes / Needs Discussion]
```

If there are no critical issues, say so explicitly rather than dropping the heading —
an absent section reads as an oversight.

## Review dimensions

### Security
- SQL injection, XSS, CSRF
- Authentication and authorization flaws
- Secrets or credentials in code
- Insecure deserialization
- Path traversal
- SSRF

### Performance
- N+1 queries
- Unnecessary memory allocations
- Algorithmic complexity (O(n²) in hot paths)
- Missing database indexes
- Unbounded queries or loops
- Resource leaks

### Correctness
- Edge cases (empty input, null, overflow)
- Race conditions and concurrency issues
- Error handling and propagation
- Off-by-one errors
- Type safety

### Maintainability
- Naming clarity
- Single responsibility
- Duplication
- Test coverage
- Documentation for non-obvious logic

## Using connected tools

- **Source control connected** — pull the PR diff and CI status directly from the URL
  instead of asking for a paste.
- **Project tracker connected** — link findings to the related ticket and check the PR
  actually addresses the stated requirements.
- **Knowledge base connected** — check the change against the team's coding standards
  and style guides.

## Tips for the requester

1. **Provide context** — "this is a hot path" or "this handles PII" sharpens the review.
2. **Specify concerns** — "focus on security" narrows it.
3. **Include tests** — test coverage and quality get reviewed too.


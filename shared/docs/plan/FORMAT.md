# Plan Documents

Records a plan to be enacted, with a lifespan bounded to the set of changes
that implement it. Use when the user has a concrete plan of work that will
span multiple decisions, files, or sessions.

## Intent

Plans record what is going to be built and why — providing a shared reference
point throughout implementation. Plans are ephemeral: once the changes they
describe are shipped, the plan has served its purpose and should be removed.
A plan is not a spec or design doc; it is an active guide for in-flight work.

## File structure

Each plan lives as its own file at the repo root:

```
/
├── {plan-name}.md
└── src/...
```

Create files lazily — only when there is an active plan to record. Delete the
file when the plan is shipped.

## Per-artifact specifics

Keep each plan focused on decisions and scope, not implementation steps. When
a plan uses domain terms, align with the project's existing domain vocabulary.

Plans may link to other documents or other plans. Relationships must reference other markdown documents; they cannot
reference arbitrary code or concepts.

## Lifecycle

A plan is created when the user commits to a course of action. It is deleted
when the implementing changes are shipped — not when a draft feels done, but
when the code is merged and live.

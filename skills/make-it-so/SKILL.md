---
name: make-it-so
description: Orchestrate plan-driven code implementation via sub-agents. Parent coordinates and adversarially verifies; sub-agents implement. Use when executing a plan to implement code, building a feature, or implementing a spec.
---

# make-it-so

Coordinate code implementation through isolated sub-agents. Parent is coordinator and
adversarial verifier. Sub-agents do the work. Everything lands in a single jj working-copy
revision — no commits, no admin tasks.

## Pre-flight checks

Before anything else:

1. **Plan required.** A written plan must exist (from `/plan` or equivalent). If only a
   verbal description was given, stop: tell the user to run `/plan` first, then invoke
   this skill again.

2. **Context gate.** CONTEXT.md and INVARIANTS.md must exist and cover all five areas
   in [CONTEXT-GATE.md](CONTEXT-GATE.md). If they don't, interrogate the user and update
   the docs before Phase 1. Sub-agents cannot see this session's context — they read files.

3. **Integration brief.** Ask the user upfront:
   - What integration or E2E tests should be written for this feature?
   - What test framework and patterns do integration tests use in this codebase?
   - Where do integration test files live?
   - What command runs them? (Needed so the sub-agent can document it in the test file.)
   Record the answers. Phase 3 writes the tests; the user runs them after this skill
   completes.

## Phases

| # | Phase | Who | Exit criterion |
|---|-------|-----|----------------|
| 1 | Scaffolding | Sub-agent | Exports declared, contract tests compile (failing OK) |
| 2 | Implementation | Sub-agent | Contract tests pass, impl tests pass |
| 3 | Integration tests | User-assisted | Run automatable tests; note manual ones |
| 4 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 5 | Diagram | Parent | ASCII tree shown to user |

See [PHASES.md](PHASES.md) for detailed per-phase instructions.

## Sub-agent briefing rule

Every sub-agent brief must be fully self-contained: file excerpts, plan section, context,
invariants, scope boundaries, and done-criteria — all included. Use the templates in
[prompts/](prompts/) and fill every `[PLACEHOLDER]` before dispatching. Never dispatch
with unfilled placeholders.

## Single-revision constraint

All changes land in the current jj working copy. Sub-agents must NOT run `jj`, `git`, or
any VCS commands. They only read and modify files.

## Fix loop

When Phase 4 finds critical or moderate issues: dispatch a targeted fix sub-agent, then
re-run Phase 4. Maximum 3 iterations. After 3 failures, surface the punch list to the
user and stop.

## What this skill does NOT do

- Split the revision into multiple commits
- Create PRs or bookmarks

The user handles those with other skills after this one completes.

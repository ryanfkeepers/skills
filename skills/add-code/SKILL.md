---
name: add-code
description: Orchestrate plan-driven code implementation via sub-agents, with unit tests but no integration/E2E tests. Parent coordinates and adversarially verifies; sub-agents implement. Default skill for adding code to a project unless /make-it-so is explicitly invoked.
model: sonnet
---

# add-code

Coordinate code implementation through isolated sub-agents. Parent is coordinator and
adversarial verifier. Sub-agents do the work. Everything lands in a single jj working-copy
revision — no commits, no admin tasks.

This is the default skill for adding code. Use `/make-it-so` instead when integration
and E2E tests must be written as part of the implementation cycle.

## Pre-flight checks

Before anything else:

1. **Plan required.** A written plan must exist (from `/plan` or equivalent). If only a
   verbal description was given, stop: tell the user to run `/plan` first, then invoke
   this skill again.

2. **Behavioral examples required.** The plan must include at least one concrete
   behavioral example per exported behavior: explicit input/output pairs, named edge
   cases with expected results, or equivalent prose that pins the behavior unambiguously.
   Vague intent ("process items") is not sufficient. If examples are missing, stop and
   ask the user to add them before proceeding. These examples are the ground truth for
   Phase 3a unit tests.

## Phases

| # | Phase | Who | Exit criterion |
|---|-------|-----|----------------|
| 1 | Scaffolding | Sub-agent | Exports declared, stubs preserved, `go build` passes |
| 2 | Implementation | Sub-agent | `go build` passes, mocks generated |
| 3a | Unit tests — adversarial pass | Sub-agent | Failures surfaced to user; no auto-fix loop |
| 3b | Unit tests — coverage pass | Sub-agent | Tests added, Pass 1 tests unmodified |
| 4 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 5 | Diagram | Parent | ASCII tree shown to user |

See [PHASES.md](PHASES.md) for detailed per-phase instructions.

## Sub-agent briefing rule

Every sub-agent brief must be fully self-contained: file excerpts, plan section, context,
scope boundaries, and done-criteria — all included. Use the templates in
[prompts/](prompts/) and fill every `[PLACEHOLDER]` before dispatching. Never dispatch
with unfilled placeholders.

## Single-revision constraint

All changes land in the current jj working copy. Sub-agents must NOT run `jj`, `git`, or
any VCS commands. They only read and modify files.

## Fix loop

Phase 3a failures surface directly to the user — no automated fix loop. The user decides
whether to re-invoke Phase 2 or accept the divergence.

When Phase 4 finds critical or moderate issues: dispatch a targeted fix sub-agent, then
re-run Phase 4. Maximum 3 iterations. After 3 failures, surface the punch list to the
user and stop.

## What this skill does NOT do

- Write integration or E2E tests (use `/make-it-so` for that)
- Split the revision into multiple commits
- Create PRs or bookmarks

The user handles those with other skills after this one completes.

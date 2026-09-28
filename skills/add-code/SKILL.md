---
name: add-code
description: Orchestrate plan-driven code implementation via sub-agents, with unit tests but no integration/E2E tests. Parent coordinates and adversarially verifies; sub-agents implement. Default skill for adding code to a project unless /make-it-so is explicitly invoked.
model: sonnet
---

# add-code

Coordinate code implementation through isolated sub-agents. Parent is coordinator and
adversarial verifier. Sub-agents do the work. Everything lands in a single jj working-copy
revision — no commits, no admin tasks.

Default skill for adding code. Use `/make-it-so` instead when integration and E2E tests
must be written as part of the implementation cycle.

## Pre-flight checks

Before anything else:

1. **Plan required.** A written plan must exist (from `/plan` or equivalent). Only a
   verbal description given → stop: tell user to run `/plan` first, then invoke this
   skill again.

2. **Behavioral examples required.** Plan must include at least one concrete behavioral
   example per exported behavior: explicit input/output pairs, named edge cases with
   expected results, or equivalent prose pinning the behavior unambiguously. Vague
   intent ("process items") isn't sufficient. Examples missing → stop, ask user to add
   them before proceeding. These are the ground truth for Phase 3a unit tests.

## Phases

| # | Phase | Who | Exit criterion |
|---|-------|-----|----------------|
| 1 | Scaffolding | Sub-agent | Exports declared, stubs preserved, `go build` passes |
| 2 | Implementation | Sub-agent | `go build` passes, mocks generated |
| 3a | Unit tests — adversarial pass | Sub-agent | Failures surfaced to user; no auto-fix loop |
| 3b | Unit tests — coverage pass | Sub-agent | Tests added, Phase 3a tests unmodified |
| 4 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 5 | Diagram | Parent | ASCII tree shown to user |

See [PHASES.md](PHASES.md) for detailed per-phase instructions.

## Sub-agent briefing rule

Every sub-agent brief must be fully self-contained: file excerpts, plan section, context,
scope boundaries, done-criteria — all included. Use templates in [prompts/](prompts/),
fill every `[PLACEHOLDER]` before dispatching. Never dispatch with unfilled placeholders.

## Single-revision constraint

All changes land in the current jj working copy. Sub-agents must NOT run `jj`, `git`, or
any VCS commands — read and modify files only.

## Fix loop

Phase 3a failures surface directly to user — no automated fix loop. User decides whether
to re-invoke Phase 2 or accept the divergence.

Phase 4 finds critical or moderate issues → dispatch targeted fix sub-agent, re-run
Phase 4. Max 3 iterations. After 3 failures, surface punch list to user, stop.

## What this skill does NOT do

- Write integration or E2E tests (use `/make-it-so` for that)
- Split the revision into multiple commits
- Create PRs or bookmarks

User handles those with other skills after this one completes.

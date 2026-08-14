---
name: make-it-so
description: Orchestrate plan-driven code implementation via sub-agents, including E2E and integration test phases. Parent coordinates and adversarially verifies; sub-agents implement. Use when executing a plan to implement code, building a feature, or implementing a spec. For the lighter default without integration/E2E tests, use `add-code` instead.
---

# make-it-so

Coordinate code implementation through isolated sub-agents. Parent is coordinator and
adversarial verifier. Sub-agents do the work. Everything lands in a single jj working-copy
revision — no commits, no admin tasks.

For work that doesn't need integration/E2E test phases, use `add-code` instead — it's
the lighter default.

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
   Phase 3 integration tests and Phase 5a unit tests.

3. **Test environment brief.** Ask the user upfront:
   - Where do E2E smoke tests live, what framework/patterns do they use, what command
     runs them, and what environment do they require?
   - Where do integration tests live, what framework/patterns do they use, what command
     runs them, and what environment do they require?
   Record the answers. Phases 2 and 3 use this. The user runs both suites after this
   skill completes.

## Phases

When communicating with the user, always refer to phases by name, not number
(e.g., "scaffolding phase", "E2E smoke test phase", "integration test phase").

| # | Phase | Who | Exit criterion |
|---|-------|-----|----------------|
| 1 | Scaffolding | Sub-agent | Exports declared, stubs preserved, `go build` passes |
| 2 | E2E smoke tests | Sub-agent | Test files compile, run command documented |
| 3 | Integration tests | Sub-agent | Behavioral tests compile, cover plan examples |
| 4 | Implementation | Sub-agent | `go build` passes, mocks generated |
| 5a | Unit tests — adversarial pass | Sub-agent | Failures surfaced to user; no auto-fix loop |
| 5b | Unit tests — coverage pass | Sub-agent | Tests added, Pass 1 tests unmodified |
| 6 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 7 | Diagram | Parent | ASCII tree shown to user |

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

Phase 5a failures surface directly to the user — no automated fix loop. The user decides
whether to re-invoke Phase 4 or accept the divergence.

When Phase 6 finds critical or moderate issues: dispatch a targeted fix sub-agent, then
re-run Phase 6. Maximum 3 iterations. After 3 failures, surface the punch list to the
user and stop.

## What this skill does NOT do

- Split the revision into multiple commits
- Create PRs or bookmarks

The user handles those with other skills after this one completes.

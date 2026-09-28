---
name: make-it-so
description: Orchestrate plan-driven code implementation via sub-agents, including E2E and integration test phases. Parent coordinates and adversarially verifies; sub-agents implement. Use when executing a plan to implement code, building a feature, or implementing a spec. For the lighter default without integration/E2E tests, use `add-code` instead.
---

# make-it-so

Coordinate code implementation through isolated sub-agents. Parent is
coordinator + adversarial verifier. Sub-agents do the work. Everything lands
in a single jj working-copy revision — no commits, no admin tasks.

For work not needing integration/E2E test phases, use `add-code` instead —
lighter default.

## Pre-flight checks

Before anything else:

1. **Plan required.** Written plan must exist (from `/plan` or equivalent). If
   only a verbal description given, stop: tell user to run `/plan` first,
   then invoke this skill again.

2. **Behavioral examples required.** Plan must include ≥1 concrete behavioral
   example per exported behavior: explicit input/output pairs, named edge
   cases with expected results, or equivalent prose pinning behavior
   unambiguously. Vague intent ("process items") not sufficient. If examples
   missing, stop, ask user to add before proceeding. These examples = ground
   truth for Phase 3 integration tests + Phase 5a unit tests.

3. **Test environment brief.** Ask user upfront:
   - Where do E2E smoke tests live, what framework/patterns, what command runs
     them, what environment required?
   - Where do integration tests live, what framework/patterns, what command
     runs them, what environment required?
   Record answers. Phases 2 + 3 use this. User runs both suites after this
   skill completes.

## Phases

When communicating with user, always refer to phases by name, not number
(e.g., "scaffolding phase", "E2E smoke test phase", "integration test phase").

| # | Phase | Who | Exit criterion |
|---|-------|-----|----------------|
| 1 | Scaffolding | Sub-agent | Exports declared, stubs preserved, `go build` passes |
| 2 | E2E smoke tests | Sub-agent | Test files compile, run command documented |
| 3 | Integration tests | Sub-agent | Behavioral tests compile, cover plan examples |
| 4 | Implementation | Sub-agent | `go build` passes, mocks generated |
| 5a | Unit tests — adversarial pass | Sub-agent | Failures surfaced to user; no auto-fix loop |
| 5b | Unit tests — coverage pass | Sub-agent | Tests added, Phase 5a tests unmodified |
| 6 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 7 | Diagram | Parent | ASCII tree shown to user |

See [PHASES.md](PHASES.md) for detailed per-phase instructions.

## Sub-agent briefing rule

Every sub-agent brief must be fully self-contained: file excerpts, plan
section, context, scope boundaries, done-criteria — all included. Use
templates in [prompts/](prompts/), fill every `[PLACEHOLDER]` before
dispatching. Never dispatch with unfilled placeholders.

## Single-revision constraint

All changes land in current jj working copy. Sub-agents must NOT run `jj`,
`git`, or any VCS commands. They only read + modify files.

## Fix loop

Phase 5a failures surface directly to user — no automated fix loop. User
decides whether to re-invoke Phase 4 or accept the divergence.

When Phase 6 finds critical or moderate issues: dispatch a targeted fix
sub-agent, then re-run Phase 6. Max 3 iterations. After 3 failures, surface
punch list to user and stop.

## What this skill does NOT do

- Split the revision into multiple commits
- Create PRs or bookmarks

User handles those with other skills after this one completes.

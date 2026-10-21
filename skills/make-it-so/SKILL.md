---
name: make-it-so
description: Orchestrate plan-driven code implementation via sub-agents, including E2E and integration test phases that sub-agents write and run. Parent coordinates and adversarially verifies; sub-agents implement. Use when executing a plan to implement code, building a feature, or implementing a spec. For the lighter default without integration/E2E tests, use `add-code` instead.
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

3. **Test environment discovery.** Find how to run the E2E smoke and
   integration suites from the repo itself — do not ask the user first. Use an
   Explore sub-agent. Check, in order:
   - Project-level skills (`.claude/skills/*/SKILL.md` in the repo, plus any
     non-`keepers` skill in the session skill list) covering test running or
     environment setup
   - Task runners: `justfile`/`Justfile`, `Makefile`, `Taskfile.yml`, package
     scripts — targets matching `e2e`, `integration`, `smoke`, `test`
   - Markdown guidance: `CLAUDE.md`, `AGENTS.md`, `README.md`,
     `CONTRIBUTING.md`, `docs/**/*.md`, READMEs inside test dirs
   - CI config (corroboration only — confirms commands, build tags, env vars)

   For each suite record: test dir, framework/patterns, run command, required
   environment (services, env vars, auth, build tags), and which environment
   is the designated safe target (local, dev, ephemeral — never prod).

   Ask the user only for what discovery leaves unresolved, or when sources
   conflict. Phases 2 + 3 write tests from this record; the run phase executes
   them with it.

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
| 6 | Integration + E2E run | Sub-agent | Both suites executed, results captured; failures surfaced to user |
| 7 | Adversarial verification | Sub-agent | VERIFIED or fix loop complete |
| 8 | Diagram | Parent | ASCII tree + test results shown to user |

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

Phase 5a failures and integration + E2E run failures surface directly to
user — no automated fix loop. The tests are derived from the plan; auto-fixing
invites weakening them to match the implementation. User decides whether to
re-invoke Phase 4 or accept the divergence.

When the adversarial verification phase finds critical or moderate issues:
dispatch a targeted fix sub-agent, re-run the unit tests and the integration +
E2E run, then re-run the verification phase. Max 3 iterations. After 3 failures, surface
punch list to user and stop.

## What this skill does NOT do

- Split the revision into multiple commits
- Create PRs or bookmarks

User handles those with other skills after this one completes.

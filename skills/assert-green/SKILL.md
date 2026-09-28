---
name: assert-green
description: >-
  Assert that the current repo is fully green: compilation, code generation
  (if present), unit tests, and linting — in that order. Fails fast on the
  first broken phase and reports the failure. Auto-fixes lint failures; does
  not fix anything else. Use when asked to assert green, check if the repo is
  clean, verify all checks pass, or before committing or opening a PR.
---

# Assert Green

Assert 4 phases pass in order. **Stop at first failure.** No fixes —
assertion only — **exception: lint (Phase 4) auto-fixed.** Report what
failed and why.

---

## Phase 1 — Compile

Verify code compiles.

### Task runners (check first)

| File | Target to try |
|------|---------------|
| `Makefile` | `make build` |
| `Justfile` / `justfile` | `just build` |
| `Taskfile.yml` / `Taskfile.yaml` | `task build` |

List targets first (`make help`, `just --list`, `task --list`). If `build`
target exists, use it — encodes project's exact config.

### Language fallbacks (if no task runner build target)

| Indicator | Command |
|-----------|---------|
| `go.mod` | `go build ./...` |
| `package.json` with `tsc` | `npx tsc --noEmit` |
| `pyproject.toml` / `setup.py` | `python -m py_compile $(find . -name '*.py')` |

If compile exits non-zero: **halt. Report compiler output.**

---

## Phase 2 — Code Generation (conditional)

Run only if repo has generate phase. Skip entirely if no signal found.

### Detection signals (check all; run each one found)

**Task runner targets** — list targets and look for any of:
`generate`, `gen`, `codegen`, `update`

| File | Command |
|------|---------|
| `Makefile` | `make generate` / `make gen` / `make codegen` / `make update` |
| `Justfile` / `justfile` | `just generate` / etc. |
| `Taskfile.yml` / `Taskfile.yaml` | `task generate` / etc. |

**Go generate** — if `go.mod` present and any `.go` file contains a
`//go:generate` directive:
```
go generate ./...
```

**Proto / buf** — if `buf.gen.yaml` or `buf.work.yaml` exists:
```
buf generate
```

**Shell script** — if `scripts/generate.sh` exists:
```
bash scripts/generate.sh
```

Codegen phase **passes** if every detected command exits 0. Working tree
changes from generation are expected, not failure.

If any codegen command exits non-zero: **halt. Report which command failed
and its output.**

---

## Phase 3 — Unit Tests

Unit tests only. Skip integration and E2E tests entirely — don't run
them, don't report on them. If a task runner or language fallback
command below runs everything by default, scope it to unit tests
only:

| Signal | Unit-only adjustment |
|--------|----------------------|
| Go `-short` convention, or integration tests gated behind a build tag (e.g. `integration`) | `go test -short ./...`, or omit the tag (do not pass `-tags=integration`) |
| Separate test dirs/configs (e.g. `test/integration/`, `test/e2e/`, a distinct `jest.integration.config.js`) | Run only the unit test target/config; exclude those paths |
| Task runner exposes distinct targets (e.g. `make test-unit` vs `make test-integration`/`make test-e2e`) | Use the unit-only target |

If no such separation exists (all tests run as one suite, no
tagging), run default command as-is.

### Task runners (check first)

| File | Target to try |
|------|---------------|
| `Makefile` | `make test` |
| `Justfile` / `justfile` | `just test` |
| `Taskfile.yml` / `Taskfile.yaml` | `task test` |

### Language fallbacks

| Indicator | Command |
|-----------|---------|
| `go.mod` | `gt` (alias), then `go test ./...` |
| `package.json` | `npx jest`, `npx vitest run`, or `npm test` |
| `pyproject.toml` / `setup.py` | `pytest` |
| `Gemfile` | `bundle exec rspec` |

If tests exit non-zero: **halt. Report failing tests and output.**

---

## Phase 4 — Lint

**Linting mandatory. Never skip.**

### Step 1 — Check task runners for a lint target

List available targets (`make help`, `just --list`, `task --list`). If a
`lint` target exists, use it:

| File | Command |
|------|---------|
| `Makefile` | `make lint` |
| `Justfile` / `justfile` | `just lint` |
| `Taskfile.yml` / `Taskfile.yaml` | `task lint` |

### Step 2 — Native fallback (required if no lint target found)

If no task runner lint target exists — or no task runner present —
run the native linter for each detected language. Don't skip.

| Indicator | Command |
|-----------|---------|
| `go.mod` | `lint` (alias); if unavailable, `go vet ./...` |
| `package.json` | `npx eslint . --ext .ts,.tsx,.js,.jsx` |
| `pyproject.toml` / `setup.py` | `ruff check .` |
| `Gemfile` | `rubocop` |

If no task runner target and no language indicator matches: report that
linting could not be determined, list what was checked, and treat this as
a failure — don't silently pass.

### Step 3 — Auto-fix on failure (do not wait for permission)

If lint exits non-zero, **don't halt, don't ask permission to fix.**
Always attempt a fix automatically:

1. Invoke `lint-fix` skill (or, if unavailable, run linter's own fix
   mode — e.g. `golangci-lint run --fix`, `eslint --fix`,
   `ruff check --fix`, `rubocop -A` — hand-fix anything the tool
   can't).
2. Re-run same lint command from Step 1/2, confirm it now exits 0.

If lint passes after fix: record as `lint: <cmd> exit 0 (auto-fixed)`,
continue to Reporting. If still non-zero after fix attempt: **halt.
Report remaining lint output and what the fix attempt changed.**


## Reporting

---

**On a lint failure:** Auto-fix per Phase 4, Step 3 — don't stop or wait
for permission. Only if the fix fails to make lint green, report
remaining violations and stop.

**On any other failure:** State which phase failed, quote relevant
output (compiler error, test failure), stop. Don't proceed to next
phase. Don't suggest fixes unless user asks.

**On full pass:** State all four phases passed (or three, if codegen
skipped). List commands run and exit codes.

Example (pass):
```
All phases green.
  compile:  go build ./...           exit 0
  codegen:  (skipped — no signals found)
  tests:    gt                       exit 0
  lint:     golangci-lint            exit 0
```

Example (fail):
```
FAIL - Lint. Halting.

  compile:  go build ./...           exit 0
  codegen:  make generate            exit 0
  tests:    gt                       exit 0
  lint:     golangci-lint            exit 1

Output:
  pkg/store/cache.go:42: declared and not used: mu
```

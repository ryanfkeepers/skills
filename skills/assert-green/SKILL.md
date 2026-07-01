---
name: assert-green
description: >-
  Assert that the current repo is fully green: compilation, code generation
  (if present), linting, and unit tests — in that order. Fails fast on the
  first broken phase and reports the failure. Does not fix anything. Use when
  asked to assert green, check if the repo is clean, verify all checks pass,
  or before committing or opening a PR.
---

# Assert Green

Assert four phases pass in order. **Stop at the first failure.** Do not fix
anything — this skill is assertion only. Report what failed and why.

---

## Phase 1 — Compile

Verify the code compiles.

### Task runners (check first)

| File | Target to try |
|------|---------------|
| `Makefile` | `make build` |
| `Justfile` / `justfile` | `just build` |
| `Taskfile.yml` / `Taskfile.yaml` | `task build` |

List targets first (`make help`, `just --list`, `task --list`). If a `build`
target exists, use it — it encodes the project's exact configuration.

### Language fallbacks (if no task runner build target)

| Indicator | Command |
|-----------|---------|
| `go.mod` | `go build ./...` |
| `package.json` with `tsc` | `npx tsc --noEmit` |
| `pyproject.toml` / `setup.py` | `python -m py_compile $(find . -name '*.py')` |

If compile exits non-zero: **halt. Report the compiler output.**

---

## Phase 2 — Code Generation (conditional)

Run only if the repo has a generate phase. Skip entirely if no signal is
found.

### Detection signals (check all; run each one found)

**Task runner targets** — list targets and look for any of:
`generate`, `gen`, `codegen`, `update`

| File | Command |
|------|---------|
| `Makefile` | `make generate` / `make gen` / `make codegen` / `make update` |
| `Justfile` / `justfile` | `just generate` / etc. |
| `Taskfile.yml` / `Taskfile.yaml` | `task generate` / etc. |

**Go generate** — if `go.mod` is present and any `.go` file contains a
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

A codegen phase **passes** if every detected command exits 0. Working tree
changes produced by generation are expected and do not count as failure.

If any codegen command exits non-zero: **halt. Report which command failed
and its output.**

---

## Phase 3 — Lint

**Linting is mandatory. It may never be skipped.**

### Step 1 — Check task runners for a lint target

List available targets (`make help`, `just --list`, `task --list`). If a
`lint` target exists, use it:

| File | Command |
|------|---------|
| `Makefile` | `make lint` |
| `Justfile` / `justfile` | `just lint` |
| `Taskfile.yml` / `Taskfile.yaml` | `task lint` |

### Step 2 — Native fallback (required if no lint target found)

If no task runner lint target exists — or no task runner is present —
run the native linter for each detected language. Do not skip.

| Indicator | Command |
|-----------|---------|
| `go.mod` | `lint` (alias); if unavailable, `go vet ./...` |
| `package.json` | `npx eslint . --ext .ts,.tsx,.js,.jsx` |
| `pyproject.toml` / `setup.py` | `ruff check .` |
| `Gemfile` | `rubocop` |

If no task runner target and no language indicator matches: report that
linting could not be determined, list what was checked, and treat this as
a failure — do not silently pass.

If lint exits non-zero: **halt. Report the lint output.**

---

## Phase 4 — Unit Tests

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

If tests exit non-zero: **halt. Report the failing tests and output.**

---

## Reporting

**On any failure:** State which phase failed, quote the relevant output
(compiler error, lint violation, test failure), and stop. Do not proceed to
the next phase. Do not suggest fixes unless the user asks.

**On full pass:** State that all four phases passed (or three, if codegen was
skipped). List the commands that ran and their exit codes.

Example (pass):
```
All phases green.
  compile:  go build ./...           exit 0
  codegen:  (skipped — no signals found)
  lint:     lint                     exit 0
  tests:    gt                       exit 0
```

Example (fail):
```
Phase 3 (lint) failed. Halting.

  compile:  go build ./...           exit 0
  codegen:  make generate            exit 0
  lint:     lint                     exit 1

Output:
  pkg/store/cache.go:42: declared and not used: mu
```

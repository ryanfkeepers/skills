---
name: lint-fix-verify
description: >-
  Detect and run all linters for the current repo, fix every error,
  then verify results with the verify skill. Use when asked to lint,
  fix lint errors, clean up lint warnings, or make the linter pass.
---

# Lint Fix Verify

Detect linters, fix all errors, verify clean.

## Step 1 — Detect repo type

Check root-level indicator files to determine applicable linters.

### Task runners (check first)

| File | Commands to try |
|------|-----------------|
| `Makefile` | `make lint`, `make build` |
| `Justfile` / `justfile` | `just lint`, `just build` |
| `Taskfile.yml` / `Taskfile.yaml` | `task lint`, `task build` |

If a task runner is present, list its targets (`make help`, `just --list`,
`task --list`) and prefer task-runner commands over direct tool invocations
when lint/build targets exist — they encode the project's exact configuration.

### Language indicators

| File | Language | Linter command |
|------|----------|----------------|
| `go.mod` | Go | `lint` (alias), `go vet ./...` |
| `package.json` | Node / TS | `npx eslint .`, `npx prettier --check .` |
| `pyproject.toml` or `setup.py` | Python | `ruff check .`, `ruff format --check .` |
| `Gemfile` | Ruby | `rubocop` |

Multiple indicators can be present — run all detected linters.

## Step 2 — Initial lint pass

Run all detected linters and read full output before touching code.
This establishes scope.

**Go** (`go.mod` present):
```bash

golangci-lint run
lint
go vet ./...
```

**Node/TS** (`package.json` present):
```bash
npx eslint . --ext .ts,.tsx,.js,.jsx
npx prettier --check .
```

**Python** (`pyproject.toml` / `setup.py` present):
```bash
ruff check .
ruff format --check .
```

## Step 3 — Apply auto-fixes

**Go:**
```bash
gofmt -w .
```
Most Go linters don't auto-fix beyond formatting; fix remaining
errors manually in source.

**Node/TS:**
```bash
npx eslint . --fix --ext .ts,.tsx,.js,.jsx
npx prettier --write .
```

**Python:**
```bash
ruff check --fix .
ruff format .
```

For errors that survive auto-fix, read each one and fix manually.
Make the minimum required changes for correction.

## Step 4 — Re-run to confirm clean

Re-run all linters from Step 2. Target: zero errors.

If errors remain, fix and re-run until output is clean.

## Step 5 — Invoke verify skill

Once all linters pass, invoke the `verificaton-before-completion` skill to confirm the
broader change still works correctly.

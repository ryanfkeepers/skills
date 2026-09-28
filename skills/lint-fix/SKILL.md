---
name: lint-fix
description: >-
  Detect and run all linters for the current repo, fix every error.
  Use when asked to lint, fix lint errors, clean up lint warnings, or
  make the linter pass.
---

# Lint Fix

Detect linters, fix all errors, confirm clean.

## Step 1 — Detect repo type

Check root-level indicator files -> determine applicable linters.

### Task runners (check first)

| File | Commands to try |
|------|-----------------|
| `Makefile` | `make lint`, `make build` |
| `Justfile` / `justfile` | `just lint`, `just build` |
| `Taskfile.yml` / `Taskfile.yaml` | `task lint`, `task build` |

If task runner present, list its targets (`make help`, `just --list`,
`task --list`); prefer task-runner commands over direct tool invocations
when lint/build targets exist — encodes the project's exact config.

### Language indicators

| File | Language | Linter command |
|------|----------|----------------|
| `go.mod` | Go | `golangci-lint run`, `go vet ./...` |
| `package.json` | Node / TS | `npx eslint .`, `npx prettier --check .` |
| `pyproject.toml` or `setup.py` | Python | `ruff check .`, `ruff format --check .` |
| `Gemfile` | Ruby | `rubocop` |

Multiple indicators can coexist — run all detected linters.

## Step 2 — Initial lint pass

Run all detected linters, read full output before touching code —
establishes scope.

**Go** (`go.mod` present):
```bash
golangci-lint run
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
errors manually.

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

For errors surviving auto-fix, read each, fix manually — minimum
changes needed.

## Step 4 — Re-run to confirm clean

Re-run all linters from Step 2. Target: zero errors.

If errors remain, fix -> re-run until clean.

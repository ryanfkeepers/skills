# Verification Loop

Sub-agent runbook. Run all steps, then return an evidence report to the caller.

**Inputs received from caller:**
- The claim being made (e.g. "bug fixed", "build passes", "requirements met")
- Any context needed to choose the right verification command

## Step 1 — Lint

Invoke the `lint-fix` skill. Record result.

## Step 2 — Test

Invoke the `unit-test` skill. Record result.

## Step 3 — Run claim-specific command

Identify and run the command that directly proves the claim:

| Claim | Command |
|-------|---------|
| Build passes | `make build` / `go build ./...` / `npm run build` |
| Bug fixed | Run the test that reproduces the original symptom |
| Regression test works | Full red-green cycle: pass → revert fix → must fail → restore → pass |
| Requirements met | Re-read plan, create line-by-line checklist, verify each item |

Check for a task runner first (`Makefile`, `Justfile`, `Taskfile.yml`) — prefer
its targets over direct tool invocations when a matching target exists.

Run the command fresh and complete. No partial runs.

## Step 4 — Return evidence report

Return a structured report to the caller. Do not summarize or editorialize —
report raw results. Every line is required; omitting a line is a verification
failure.

```
LINT:        [PASS|FAIL] — <linter name, error count or "clean", key errors if any>
TESTS:       [PASS|FAIL] — <N passed, N failed; failure names and messages if any>
BUILD:       [PASS|FAIL] — <command run, exit code>
BUG:         [PASS|FAIL|N/A] — <symptom test name, result; "N/A" if no bug claim>
REGRESSION:  [PASS|FAIL|N/A] — <red: failed before fix, green: passes after;
                                 "N/A" if no regression claim>
AGENT:       [PASS|FAIL|N/A] — <VCS diff summary (files changed, lines +/-);
                                 "N/A" if no agent delegation>
REQUIREMENTS:[PASS|FAIL|N/A] — <checklist item count, any unmet items;
                                 "N/A" if no requirements claim>
```

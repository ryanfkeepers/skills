---
name: resume
description: >-
  Continue an interrupted or halted lens run. Finds the run (the latest one
  for this repo unless a run directory is given) and hands it back to
  lens:run. Use when the user invokes /lens:resume, or asks to pick a lens
  run back up after a halt, a crash, or compaction.
argument-hint: "[run-dir]"
---

# lens:resume

1. Find the run. If the user gave a run directory, use it. Otherwise run
   `python3 ${CLAUDE_SKILL_DIR}/../../scripts/lensctl.py latest --repo "$(jj root)"`
   and use its `run`. If that prints an error, report it with 🛑 and stop.
2. Invoke `lens:run` with `--resume <run>`.

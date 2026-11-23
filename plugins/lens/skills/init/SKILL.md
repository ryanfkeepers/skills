---
name: init
description: >-
  Initialize a repo for lens: build the core graph, the conventions core, and
  the contract-layers core that every lens run needs. Shows each core in full
  for the user's approval. Builds only what is missing, moves the core graph
  to trunk, and never overwrites or deletes a built core. Use when the user
  invokes /lens:init, or when /lens:run reports the repo is not
  lens-initialized.
argument-hint: ""
---

# lens:init

1. Run `python3 ${CLAUDE_SKILL_DIR}/../../scripts/lensctl.py init --repo "$(jj root)" --init`.
   Keep the returned `run`. If it prints an error, report it with 🛑 and stop.
2. Invoke `lens:run` with `--resume <run>` to drive it. The run builds the
   core graph, then the conventions core, then the contract-layers core. Each
   markdown core is relayed in full and promoted only on approval. A core
   that is already built is left alone.

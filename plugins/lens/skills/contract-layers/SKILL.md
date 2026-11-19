---
name: contract-layers
description: >-
  Build or refresh the repo's lens contract-layers core: which packages form
  each major layer boundary (transport, business, store, sdk) and what each
  boundary promises. The core is built once per repo and only changes when
  refreshed, and every build or refresh needs the user's approval. Use when
  the user invokes /lens:contract-layers --refresh [scope], or asks to rebuild
  or update the lens contract layers.
argument-hint: "--refresh [scope]"
---

# lens:contract-layers

1. Write the request, including any scope the user named, to a scratch file.
2. Run `python3 ${CLAUDE_SKILL_DIR}/../../scripts/lensctl.py init --repo "$(jj root)" --proposal-file <file> --only contract-layers`.
   A run created with `--only` always rebuilds, even when the core is already built.
3. Invoke `lens:run` with `--resume <run>` to drive it. The lens writes a
   pending core, relays it for approval, and promotes it only on approval.

---
name: conventions
description: >-
  Build or refresh the repo's lens conventions core: the thin, fixed-template
  coding and testing conventions that code-writing lenses follow. The core is
  built once per repo and only changes when refreshed, and every build or
  refresh needs the user's approval. Use when the user invokes
  /lens:conventions --refresh [scope], or asks to rebuild or update the lens
  conventions.
argument-hint: "--refresh [scope]"
---

# lens:conventions

1. Write the request, including any scope the user named, to a scratch file.
2. Run `python3 ${CLAUDE_SKILL_DIR}/../../scripts/lensctl.py init --repo "$(jj root)" --proposal-file <file> --only conventions`.
   A run created with `--only` always rebuilds, even when the core is already built.
3. Invoke `lens:run` with `--resume <run>` to drive it. The lens writes a
   pending core, relays it for approval, and promotes it only on approval.

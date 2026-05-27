# ADR documents

hard-to-reverse decisions with rejected alternatives. Use only when the decision is costly to undo, surprising without context, and resulted from a real trade-off.

## Intent

ADRs record the "why" behind hard-to-reverse architectural decisions. Code shows what was built; ADRs explain why — the constraints, trade-offs, and rejected alternatives that aren't visible in the code. Without them, future engineers reverse-engineer intent from artifacts or, worse, undo deliberate choices thinking they're fixing a mistake.

## File structure

Many packages have a top-level ADR at the repo root:

```
/
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

Packages can also have multiple adr declarations. The directory of the adr defines its applicable scope.

```
/
├── docs/
│   └── adr/                            ← system-wide decisions
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
├── src/
│   ├── ordering/
│   │   └── docs/adr/                   ← package-specific decisions
│   └── billing/
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no ADR exists, create one when the first adr is established. If no `docs/adr/` exists, create it when the first ADR is needed.

## Per-artifact specifics

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).


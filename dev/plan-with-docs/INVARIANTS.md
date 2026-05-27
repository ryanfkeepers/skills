# Invariants Documents

unconditional, falsifiable rules. Use when the user states something that must always hold (or must never happen) and you can describe a scenario that would break it.

## Intent

Invariants describe high level, domain specific rules about the behavior of a system or package. Terms, structures, and implementations may change, but the rules must always be followed.

## File structure

Most packages have a single invariants at the repo root:

```
/
├── docs/
│   └── invariants/
│       └── INVARIANTS.md
└── src/...
```

Packages can also have multiple invariant declarations. The directory of the invariant defines its applicable scope.

```
/
├── docs/
│   └── invariants/                          ← system-wide decisions
│       └── INVARIANTS.md
├── src/
│   ├── ordering/
│   │   ├── docs/invariants/INVARIANTS.md    ← package-specific decisions
│   └── billing/
│       └── docs/invariants/INVARIANTS.md
```

Create files lazily — only when you have something to write. If no `/docs/invariants/INVARIANTS.md` exists, create one when the first rule is resolved.

## Per-artifact specifics

Use the format in [INVARIANTS-FORMAT.md](./INVARIANTS-FORMAT.md). Don't couple `INVARIANTS.md`
to implementation details. Only include rules that are meaningful to domain experts. A rule
must be falsifiable — if you can't describe a scenario that would break it, it doesn't belong
here. When the discussion requires a related scope, follow markdown links in `## Relationships`
lazily — only load what the current topic actually needs.


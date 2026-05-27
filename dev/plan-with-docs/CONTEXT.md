# Context Documents

Context is to ensure the user and agent communicate using consistent concepts: vocabulary, scopes, and common lingo. Use when a term is fuzzy, overloaded, or conflicts with existing glossary entries.

## Intent

Context defines domain-specific terms, vocabulary, and concepts applicable to the domain. Context clarifies discussion, aligns naming, and ensures shared understanding is equal for all participants.

## File structure

Many packages have a single context at the repo root:

```
/
├── docs/
│   └── context/
│       └── CONTEXT.md
└── src/...
```

Packages can also have multiple context declarations. The directory of the context defines its applicable scope.

```
/
├── docs/
│   └── context/                      ← system-wide decisions
│       └── CONTEXT.md
├── src/
│   ├── ordering/
│   │   ├── docs/context/CONTEXT.md   ← package-specific decisions
│   └── billing/
│       └── docs/context/CONTEXT.md
```

Create files lazily — only when you have something to write. If no `/docs/context/CONTEXT.md` exists, create one when the first term is resolved.

## Per-artifact specifics

Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md). Don't couple `CONTEXT.md` to
implementation details. Only include terms that are meaningful to domain experts. When the
discussion requires a related context, follow markdown links in `## Relationships` lazily —
only load what the current topic actually needs.


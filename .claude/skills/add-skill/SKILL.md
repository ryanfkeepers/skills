---
name: add-skill
description: Add a new skill to this repo (the keepers plugin) — directory layout, required frontmatter, and naming convention. Use when creating a new skills/<name>/SKILL.md in this repo.
---

# Adding a skill to this repo

Repo layout:

```
.claude-plugin/
└── plugin.json           ← plugin manifest (name, version)
skills/
└── <skill-name>/
    ├── SKILL.md          ← required; frontmatter + skill instructions
    └── *.md              ← optional supporting files referenced by SKILL.md
shared/
└── docs/                 ← shared format definitions, @-included by skills
```

Steps:

1. Create `skills/<skill-name>/SKILL.md` with frontmatter:
   ```
   ---
   name: <skill-name>
   description: <one-line summary used for skill discovery>
   ---
   ```
2. Add any supporting files the skill references into the same directory.
3. Reference shared format docs with relative paths:
   `@../../shared/docs/<type>/FORMAT.md`

The directory name must match the `name:` frontmatter field.

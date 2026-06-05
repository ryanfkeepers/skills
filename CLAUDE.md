# Skills Repo

Personal Claude Code skills distributed as a plugin (`keepers`).

## Layout

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

## Adding a skill

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

## Installation

Add this repo as a marketplace and install the plugin:

```
/plugin marketplace add ryanfkeepers/skills
/plugin install keepers@ryanfkeepers-skills
```

Skills are namespaced: `/keepers:skill-name`

## Local testing

```bash
claude --plugin-dir ./
```

# Skills Repo

Personal Claude Code skills. Each skill is a self-contained directory copied
into `~/.claude/skills/`.

## Layout

```
<category>/
└── <skill-name>/
    ├── SKILL.md          ← required; frontmatter + skill instructions
    └── *.md              ← optional supporting files referenced by SKILL.md
```

Current categories: `dev`

## Adding a skill

1. Pick or create a category directory.
2. Create `<category>/<skill-name>/SKILL.md` with frontmatter:
   ```
   ---
   name: <skill-name>
   description: <one-line summary used for skill discovery>
   ---
   ```
3. Add any supporting files the skill references into the same directory.
4. Run `just install` to copy skills into `~/.claude/skills/`.

The directory name becomes the skill's install name in `~/.claude/skills/` and
must match the `name:` frontmatter field.

## Installation

```bash
just install
```

Copies every skill directory into `~/.claude/skills/<skill-name>`. Removes any
symlinks previously created by this script before copying. Safe to re-run.

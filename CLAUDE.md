# Skills Repo

Personal Claude Code skills. Each skill is a self-contained directory installed
as a symlink into `~/.claude/skills/`.

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
4. Run `bash scripts/link-skills.sh` to update the symlink.

The directory name becomes the skill's link name in `~/.claude/skills/` and must
match the `name:` frontmatter field.

## Installation

```bash
bash scripts/link-skills.sh
```

Symlinks every skill directory into `~/.claude/skills/<skill-name>`. Safe to
re-run; uses `ln -sfn`.

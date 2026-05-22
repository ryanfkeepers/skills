install:
    bash scripts/link-skills.sh

usage:
    @echo "Reusable format definitions (use @-include in skills or AGENT.md files):"
    @echo ""
    @echo "  @~/.claude/skills/plan-with-docs/CONTEXT-FORMAT.md"
    @echo "  @~/.claude/skills/plan-with-docs/INVARIANTS-FORMAT.md"
    @echo "  @~/.claude/skills/plan-with-docs/ADR-FORMAT.md"

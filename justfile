install:
    bash scripts/link-skills.sh

usage:
    @echo "Reusable format definitions (use @-include in skills or AGENT.md files):"
    @echo ""
    @echo "  @~/.claude/shared/docs/plan/FORMAT.md"
    @echo "  @~/.claude/shared/docs/context/FORMAT.md"
    @echo "  @~/.claude/shared/docs/invariants/FORMAT.md"
    @echo "  @~/.claude/shared/docs/adr/FORMAT.md"

# Code Review Skill Invariants

Rules governing the execution order and axis separation of the
`code-review` skill. Exist to prevent axis contamination and
wasted sub-agent work.

## Rules

**Spec source lookup must complete before any sub-agent is spawned.**
Sub-agents receive all found spec sources (or confirmed absence) as
part of their prompt. Spawning before resolution means the Spec
sub-agent either blocks or runs with wrong inputs.

**All spec sources are collected, not just the first found.**
Commit message issue refs, user-provided arguments, and matching
docs files are all gathered. The Spec sub-agent receives the full
set — a change may have both an issue reference and a PRD file.

**Document discovery must complete before any sub-agent is spawned.**
CONTEXT.md, INVARIANTS.md, ADR, and standards-source paths are
found once and injected into sub-agent prompts. Each sub-agent must
not re-run discovery independently.

**Correctness, Standards, and Spec sub-agents must run in parallel.**
No axis depends on another's findings. Serializing them wastes time
and risks one axis anchoring another's conclusions.

**Axis findings must never be merged in the report.**
Each axis is reported under its own heading. A change can pass one
axis and fail another; collapsing them hides that signal.

**Test logic is always reviewed under Correctness.**
A test that asserts wrong behavior is a bug, not a style violation.

**Test coverage is always reviewed under Standards.**
Whether tests exist for new behavior is a project convention, not
a proof of correctness.

**Spec fallback applies only when no spec source exists.**
When a spec source is found, the Spec sub-agent checks against it
exclusively. Established documents (CONTEXT.md, INVARIANTS.md,
ADRs) are not used as supplemental spec when a real spec source
is present.

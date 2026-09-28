---
name: select-revs
description: >-
  List revisions (aka, commits) since the trunk in the current jj
  repository and let the user select which to include. Returns the
  selected commit range.
  Use when you need to identify a set of commits for review, summary,
  or other operations.
---

# Select Commits

## Instructions

1. Run `jj log -r 'trunk()..@'` — lists all commits since trunk.
2. Present commits (change ID, description, author) as numbered list,
   leaf first.
   - Always ask user which commits to include, even if only one.
     Accept "all", specific change IDs, or a range.
3. Output selected earliest and latest change IDs for caller use (e.g.
   `jj diff --from <earliest> --to <latest>`).

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

1. Run `jj log -r 'trunk()..@'` to list all commits since the
   trunk.
2. Present the commits (change ID, description, author) as a
   numbered list, starting with the leaf.
   - Always ask the user which commits to include, even if
     there is only one. Accept "all", specific change IDs,
     or a range.
3. Output the selected earliest and latest change IDs so the
   caller can use them (e.g. for `jj diff --from <earliest>
   --to <latest>`).

---
name: push-pr-stack
description: >-
  Push a stack of jj changes to GitHub and open pull requests for
  each bookmarked revision. Walks through: selecting revisions,
  verifying bookmarks, collecting reviewers, drafting and approving
  PR descriptions, creating PRs, and returning URLs. Use when the
  user wants to push changes and open PRs, push a stacked PR series,
  or ship work to GitHub.
---

# Push PR Changes

## Step 1 — Select revisions

Invoke the `keepers:select-revs` skill. Do not proceed until the
user has confirmed their selection and you have the set of change
IDs to work with.

## Step 2 — Verify bookmarks

Run:

```
jj log -r '<earliest>::<latest>' --no-pager \
  -T 'change_id.short() ++ "\t" ++ bookmarks.join(", ") ++ "\t" ++ description.first_line() ++ "\n"'
```

Display the result as a markdown table:

| Change ID | Bookmark | Description |
|-----------|----------|-------------|
| `rkxmmksm` | `feature/auth` | Add login handler |
| `yqvwlntp` | *(none)* | Fix token expiry |

Ask: "Which revisions need bookmarks? Provide pairs as
`change-id: bookmark-name`, or say 'done' to continue."

Apply changes (`jj bookmark create <name> -r <change_id>` or
`jj bookmark move <name> --to <change_id>`), re-display the
updated table, and repeat until the user says "done".

## Step 3 — Reviewers

Ask: "Who should review these PRs? Provide GitHub usernames
(comma-separated), or leave blank to rely on CODEOWNERS."

Store the list (may be empty).

## Step 4 — Draft PR descriptions

For each bookmarked revision (in stack order, oldest first):

1. Identify the base: the nearest ancestor bookmark, or `main`
   if none.
2. Gather commit messages: `jj log -r '<base>..<change_id>'
   --no-pager -T 'description ++ "\n---\n"'`
3. Draft a PR title and body:
   - **Title:** first line of the topmost commit message in
     the range.
   - **Body:** all commit messages in the range, formatted as
     a summary list.
4. Present the draft and ask: "Approve this description for
   `<bookmark-name>`, or provide edits."

Do not proceed to Step 5 until every description is approved.

## Step 5 — Create PRs

For each bookmarked revision (oldest first — base PRs before
dependents):

1. Push the bookmark: `jj git push --bookmark <name>`
2. Determine the base branch: nearest ancestor bookmark name,
   or `main`.
3. Create the PR:

Before creating the first PR, resolve the current GitHub user:

```
gh api user --jq '.login'
```

Then create each PR:

```
gh pr create \
  --head <bookmark-name> \
  --base <base-branch> \
  --title "<approved title>" \
  --body "<approved body>" \
  --assignee <current-github-login> \
  [--reviewer <user1> --reviewer <user2> ...]
```

Collect the URL returned by `gh pr create`.

## Step 6 — Report

Print a table of all generated PRs:

| Bookmark | PR URL |
|----------|--------|
| `feature/auth` | https://github.com/org/repo/pull/42 |
| `feature/auth-tests` | https://github.com/org/repo/pull/43 |

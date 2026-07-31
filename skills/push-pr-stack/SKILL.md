---
name: push-pr-stack
description: >-
  Push a stack of jj changes to GitHub and open pull requests for
  each bookmarked revision. Walks through: selecting revisions,
  auto-generating bookmark names and PR descriptions, collecting
  reviewers, creating PRs, and returning URLs. Use when the
  user wants to push changes and open PRs, push a stacked PR series,
  or ship work to GitHub.
---

# Push PR Changes

## Step 1 — Select revisions

First, count revisions since trunk:

```
jj log -r 'trunk()..@' --no-pager -T 'change_id.short() ++ "\n"'
```

- **If exactly one revision exists:** automatically select it.
  Do not ask the user for confirmation — proceed directly to
  Step 2.
- **Otherwise:** invoke the `keepers:select-revs` skill. Do not
  proceed until the user has confirmed their selection and you
  have the set of change IDs to work with.

## Step 2 — Assign bookmarks

Run:

```
jj log -r '<earliest>::<latest>' --no-pager \
  -T 'change_id.short() ++ "\t" ++ bookmarks.join(", ") ++ "\t" ++ description.first_line() ++ "\n"'
```

For each revision in the range that lacks a bookmark, the agent
decides the bookmark name itself — do not ask the user for a name.

1. **Ticket ID.** If a ticket ID has not already been established
   this session, ask once: "What ticket ID should be used for this
   stack's branch names? (e.g. `DP-1234`)." Reuse that same ticket
   ID for every revision in the stack; do not ask again per
   revision.
2. **Description.** If the revision has no description (or only a
   placeholder), invoke the `keepers:jjdesc` skill to generate one
   before continuing — do not ask the user to write it.
3. **Short name.** Slugify the first line of the revision's
   description: lowercase, replace runs of non-alphanumeric
   characters with a single hyphen, strip leading/trailing hyphens,
   cap at ~50 characters.
4. **Bookmark name.** Combine as `<ticket>/<short-name>` (ticket
   lowercased), e.g. `dp-1234/update-foo-parameters`.
5. Create the bookmark: `jj bookmark create <name> -r <change_id>`.

Re-display the updated table (change ID, bookmark, description) so
the user can see what was created, then continue to Step 3 — this
is informational, not a confirmation gate.

## Step 3 — Reviewers

Assume CODEOWNERS are the only reviewers — do not pass
`--reviewer` and do not ask the user to name reviewers. Only add
explicit reviewers if the user has already named them (in this
conversation or elsewhere) without being asked.

## Step 4 — Build PR descriptions

The agent decides the PR title and body itself, re-using the jj
revision description(s) directly — do not ask the user to draft or
approve them.

For each bookmarked revision (in stack order, oldest first):

1. Identify the base: the nearest ancestor bookmark, or `main`
   if none.
2. Gather descriptions from the range:
   ```
   jj log -r '<base>..<change_id>' --no-pager \
     -T 'description ++ "\n\n---\n"'
   ```
3. Build the PR title and body directly from those descriptions:
   - **If the range contains one revision:** use its description
     verbatim — the first line becomes the title, the remainder
     becomes the body.
   - **If the range contains multiple revisions:** concatenate
     all descriptions in order (oldest first), separated by
     `\n\n---\n`. The first line of the oldest description becomes
     the title; the full concatenation becomes the body.
   - **If any revision in the range has no description (empty or
     placeholder text):** invoke the `keepers:jjdesc` skill to
     generate one, then use it as above.

## Step 5 — Verify each bookmark

For each bookmarked revision (oldest first), before creating any
PR, invoke the `keepers:assert-green` skill.

- If verification passes, proceed to Step 6.
- If verification fails for any bookmark, **halt immediately**.
  Report which bookmark failed and what the failure was.
  Do not proceed to Step 6 until the user has resolved the
  issue and verification passes for that bookmark. Re-run
  `keepers:assert-green` after each fix
  attempt; only continue when it passes.

## Step 6 — Create PRs

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
  --title "<title>" \
  --body "<body>" \
  --assignee <current-github-login> \
  [--reviewer <user1> --reviewer <user2> ...]
```

Collect the URL returned by `gh pr create`.

## Step 7 — Report

Print a table of all generated PRs:

| Bookmark | PR URL |
|----------|--------|
| `dp-1234/add-auth-handler` | https://github.com/org/repo/pull/42 |
| `dp-1234/add-auth-tests` | https://github.com/org/repo/pull/43 |

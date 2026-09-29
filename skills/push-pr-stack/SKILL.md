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

When the user invoked `/push-pr-stack`, that invocation is prior
approval to describe, bookmark, push, and open PRs for the selected
revisions — don't ask for separate approval before those actions. If
you invoked this skill on your own initiative, confirm with the user
before Step 2.

## Step 1 — Select revisions

Count revisions since trunk:

```
jj log -r 'trunk()..@' --no-pager -T 'change_id.short() ++ "\n"'
```

- **If exactly one revision:** auto-select it. No confirmation ask —
  go straight to Step 2.
- **Otherwise:** invoke `keepers:select-revs`. Don't proceed until user
  confirms selection and you have the change IDs to work with.

## Step 2 — Assign bookmarks

Run:

```
jj log -r '<earliest>::<latest>' --no-pager \
  -T 'change_id.short() ++ "\t" ++ bookmarks.join(", ") ++ "\t" ++ description.first_line() ++ "\n"'
```

For each revision lacking a bookmark, agent decides the bookmark name
itself — don't ask user for a name.

1. **Ticket ID.** If not already established this session, ask once:
   "What ticket ID should be used for this stack's branch names? (e.g.
   `DP-1234`)." Reuse same ticket ID for every revision in the stack —
   don't ask again per revision.
2. **Description.** If revision has no description (or only a
   placeholder), invoke `keepers:jjdesc` to generate one first — don't
   ask user to write it.
3. **Short name.** Slugify first line of description: lowercase,
   replace non-alphanumeric runs with single hyphen, strip
   leading/trailing hyphens, cap ~50 chars.
4. **Bookmark name.** `<ticket>/<short-name>` (ticket lowercased),
   e.g. `dp-1234/update-foo-parameters`.
5. Create the bookmark: `jj bookmark create <name> -r <change_id>`.

Re-display updated table (change ID, bookmark, description) so user
sees what was created, then continue to Step 3 — informational only,
not a confirmation gate.

## Step 3 — Reviewers

Assume CODEOWNERS are the only reviewers — don't pass `--reviewer`,
don't ask user to name reviewers. Add explicit reviewers only if user
already named them (this conversation or elsewhere) unprompted.

## Step 4 — Build PR descriptions

Agent decides PR title and body itself, reusing the jj revision
description(s) directly — don't ask user to draft or approve them.

For each bookmarked revision (in stack order, oldest first):

1. Base = nearest ancestor bookmark, or `main` if none.
2. Gather descriptions from the range:
   ```
   jj log -r '<base>..<change_id>' --no-pager \
     -T 'description ++ "\n\n---\n"'
   ```
3. Build title and body directly from those descriptions:
   - **Range has one revision:** use its description verbatim — first
     line becomes title, remainder becomes body.
   - **Range has multiple revisions:** concatenate all descriptions in
     order (oldest first), separated by `\n\n---\n`. First line of
     oldest description becomes title; full concatenation becomes body.
   - **Any revision missing a description (empty or placeholder):**
     invoke `keepers:jjdesc` to generate one, then use as above.

## Step 5 — Remove shipped plan docs

Plan docs live as standalone
`{plan-name}.md` files at repo root — meant to be deleted once the work
they describe ships. Before creating any PR, check each bookmarked
revision for a plan doc it introduced and still carries:

1. List files each bookmarked revision added:
   ```
   jj diff -r <change_id> --summary --no-pager
   ```
2. A file is a plan doc if it's `A` (added) directly at repo root, has
   a `.md` extension, and isn't a standard project file (`README.md`,
   `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `LICENSE.md`, etc.).
3. If it still exists on disk, delete it and fold the deletion into the
   same revision:
   ```
   rm <plan-name>.md
   jj squash --into <change_id>
   ```
   (If `<change_id>` is `@`, plain `jj squash` targets the parent
   automatically — use `jj squash --into <change_id>` for any
   non-working-copy revision in the stack.)
4. If the plan doc was already deleted by a later revision in the
   stack, no action needed — won't exist on disk.

## Step 6 — Verify each bookmark

For each bookmarked revision (oldest first), before creating any PR,
invoke `keepers:assert-green`.

- Passes → proceed to Step 7.
- Fails for any bookmark → **halt immediately**. Report which bookmark
  failed and why. Don't proceed to Step 7 until user resolves it and
  verification passes for that bookmark. Re-run `keepers:assert-green`
  after each fix attempt; continue only once it passes.

## Step 7 — Create PRs

Resolve the current GitHub user once, before creating any PRs:

```
gh api user --jq '.login'
```

For each bookmarked revision (oldest first — base PRs before
dependents):

1. Push the bookmark: `jj git push --bookmark <name>`
2. Base branch = nearest ancestor bookmark name, or `main`.
3. Create the PR:

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

## Step 8 — Report

Print a table of all generated PRs:

| Bookmark | PR URL |
|----------|--------|
| `dp-1234/add-auth-handler` | https://github.com/org/repo/pull/42 |
| `dp-1234/add-auth-tests` | https://github.com/org/repo/pull/43 |

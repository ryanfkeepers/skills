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

## Script

`$S` below is short for `python3 ${CLAUDE_SKILL_DIR}/scripts/pps.py`.
Write it out in full every time, since shell variables don't survive
between calls. It prints compact JSON. On `{"status":"error"}` (exit 1),
halt and report the message. Don't hand-roll the `jj log` / `gh pr`
calls it replaces.

## Step 2 — Plan and assign bookmarks

1. **Ticket ID.** If not already established this session, ask once:
   "What ticket ID should be used for this stack's branch names? (e.g.
   `DP-1234`)." Reuse same ticket ID for every revision in the stack —
   don't ask again per revision.
2. Run `$S plan <earliest> <latest> --ticket <ticket> --out <scratch dir>`.
   Trunk revisions are excluded. Each entry in `revisions` (oldest first)
   carries `change_id`, `bookmark`, `bookmark_exists`, `base`, `title`,
   `title_file`, `body_file`, `needs_description`, and `plan_docs`.
3. **Description.** For any revision with `needs_description: true`,
   invoke `keepers:jjdesc` to generate one — don't ask user to write it
   — then rerun `plan`. Bookmarks, bases, titles, and bodies all depend
   on descriptions.
4. **Base.** `base_ambiguous` means two bookmarked branches sit directly
   below the stack. Ask which one the stack builds on, then use it as
   the first revision's base.
5. For each revision with `bookmark_exists: false`, create the proposed
   bookmark: `jj bookmark create <bookmark> -r <change_id>`. The script
   has already built the name (`kprs/<ticket>/<slug>`, lowercased, slug
   ≤50 chars). Existing bookmarks keep their names.
   and suffixed it if it collides — don't rename it.

Show a table (change ID, bookmark, title) so the user sees what was
created, then continue to Step 3 — informational only, not a
confirmation gate.

## Step 3 — Reviewers

Assume CODEOWNERS are the only reviewers — don't pass `--reviewer`,
don't ask user to name reviewers. Add explicit reviewers only if user
already named them (this conversation or elsewhere) unprompted.

## Step 4 — PR descriptions

`plan` already built each PR's title and body from its revision's
description, verbatim: the first line is the title and the remainder is
the body, in `title_file` and `body_file`. Every revision gets its own
bookmark, so each PR covers exactly one revision. Don't read the body
files back, and don't ask the user to draft or approve them.

## Step 5 — Remove shipped plan docs

Plan docs are standalone `{plan-name}.md` files at the repo root, meant
to be deleted once the work they describe ships. `plan_docs` lists, per
revision, the root-level `.md` files it added that aren't standard
project files and still exist on disk. Delete each one and fold the
deletion into that revision:

```
rm <plan-name>.md
jj squash --into <change_id>
```

(If `<change_id>` is `@`, plain `jj squash` targets the parent
automatically — use `jj squash --into <change_id>` for any
non-working-copy revision in the stack.)

## Step 6 — Verify each bookmark

For each bookmarked revision (oldest first), before creating any PR,
invoke `keepers:assert-green`.

- Passes → proceed to Step 7.
- Fails for any bookmark → **halt immediately**. Report which bookmark
  failed and why. Don't proceed to Step 7 until user resolves it and
  verification passes for that bookmark. Re-run `keepers:assert-green`
  after each fix attempt; continue only once it passes.

## Step 7 — Create PRs

For each revision (oldest first, so base PRs come before their
dependents), run:

```
$S pr <bookmark> <base> --title-file <title_file> --body-file <body_file> \
  [--reviewer <user> ...] [--draft] [--repo <owner>/<repo>]
```

It pushes the bookmark, then reuses the open PR for that branch if there
is one, moving its base when the base is wrong (`base_fixed`).
Otherwise it creates the PR, assigned to you (`--assignee @me`). Reuse
makes re-running a stack safe. The result's `action` is `created` or
`reused`. Collect each `url`. A push or `gh` failure halts with the
error — PRs already handled stay as they are.

## Step 8 — Link PRs as a GitHub stack

Run `$S link <url-1> <url-2> ... <url-N>` with every URL from Step 7,
oldest first. It accepts only PR URLs: `gh stack link` treats any other
argument as a branch and creates a PR for it. It returns `linked`,
`skipped` (one PR), `not_installed` (don't install it for the user),
`not_enabled` (stacked PRs are off for the repo), or `failed` with a
`message`. None of these halt the run — the PRs are already open. Note
anything other than `linked` or `skipped` in Step 9.

## Step 9 — Report

Print a table of all PRs, with Step 7's `action`:

| Bookmark | PR URL | Action |
|----------|--------|--------|
| `kprs/dp-1234/add-auth-handler` | https://github.com/org/repo/pull/42 | created |
| `kprs/dp-1234/add-auth-tests` | https://github.com/org/repo/pull/43 | reused (base fixed) |

---
name: visualize-changes
description: >
  Build a shareable, tabbed HTML design brief of the changes in a jj
  revision, bookmark, or stack (or a git commit, branch, or working tree), for 2-3 people to talk through the design
  together: process flow, where the code lives and who owns it, exported
  interfaces and structs, communication patterns, and before/after
  of anything the change reshapes. Overview tab first, one tab per design
  topic, diagrams instead of code. Publishes a claude.ai Artifact link and
  writes a self-contained .html for Jira/Confluence. Use whenever the user
  wants to walk the team through a change, prep a design review or
  discussion, visualize/diagram/illustrate a change, or attach a change
  explainer to a ticket or doc, or invokes /visualize-changes, even if they
  don't say "visualize". Not for line-by-line code review.
user_invocable: true
---

# visualize-changes

Picture the use: two or three engineers in a room or on a call, one screen
shared, working through whether the design of a change is right. Most of them
didn't write it, and they have half an hour. The page is their agenda and
whiteboard. Each tab is one topic they will talk about; each picture is
something they can point at and argue over.

That sets what belongs on the page:
- **Yes:** how the flow works, what each boundary (package, API, layer,
  service) exposes, where code lives and who owns it, which contracts changed
  shape, the business-level decisions the application now makes, and how it
  fails.
- **No:** code bodies, diff hunks, file inventories, line counts, internal
  helpers and unexported details, tests and mocks, bug reports, notes,
  discussion questions. The room weighs the design; the
  page shows it. Anyone who wants lines opens the PR. A wall of code on a shared
  screen ends the design conversation and starts a line review, which is not
  what this meeting is for.

The page shell is fixed. `template.html` and `scripts/build.py` own layout,
theming, tabs, the exposed surface, the trees, and both output formats. Your job is the content: finding the design topics and
drawing each one so the room gets it in one look. You decide what each
picture looks like, composed from the template's flow kit, with
related facts shown together. A reader should be able to trace one request
from caller to callee across the interfaces it touches, not reassemble it
from scattered cards. Don't
hand-write page HTML or CSS.

## Steps

### 1. Resolve the range

The page compares two revisions: `--from` (before) and `--to` (after).
`build.py` uses jj when the repo has it (colocated repos included), else git.

| user says | jj `--from` | jj `--to` | git `--from` | git `--to` |
|---|---|---|---|---|
| nothing / "this change" | `@-` | `@` | `HEAD` | `WORKTREE` |
| a revision `X` | `X-` | `X` | `X~1` | `X` |
| `X` through `Y` (a stack) | `roots(X::Y)-` | `Y` | `X~1` | `Y` |
| a bookmark / branch `B` | `fork_point(trunk() \| B)` | `B` | `$(git merge-base <trunk> B)` | `B` |
| "the stack" / "since trunk" | `fork_point(trunk() \| @)` | `@` | `$(git merge-base <trunk> HEAD)` | `WORKTREE` |

Git notes:
- `WORKTREE` is a `build.py` token for the working tree: tracked edits plus
  untracked, non-ignored files. Use it only with `build.py`; for git commands
  below, compare against the working tree by omitting the `--to` side.
- `<trunk>` is the remote default branch:
  `git symbolic-ref --short refs/remotes/origin/HEAD`, else `origin/main`,
  else `origin/master`.
- `X~1` through `Y` assumes linear history from `X` to `Y`. If merges sit in
  between, ask which base the user means.

If the tip is empty (jj: `@` empty with no description; git: `git status
--porcelain` prints nothing), step the range back one: jj uses `@-` as the
tip, git uses `HEAD~1` → `HEAD`. Confirm both ends resolve to one revision
each:
- jj: `jj log --no-graph -r '<rev>' -T 'change_id.shortest(8) ++ " " ++ description.first_line() ++ "\n"'`
- git: `git log -1 --format='%h %s' '<rev>'`

A multi-revision range renders as one before → after comparison, so tabs
follow design topics, not commits.

### 2. Understand the design

```bash
# jj
jj diff --stat --from '<from>' --to '<to>'
jj diff --git --from '<from>' --to '<to>' '~glob:"**/*_test.go" & ~root-file:"go.sum"'
# git (drop '<to>' when it is WORKTREE; untracked files then show only in `git status`)
git diff --stat '<from>' '<to>'
git diff '<from>' '<to>' -- . ':(exclude,glob)**/*_test.go' ':(exclude)go.sum'
```

Adjust the exclusions to the repo's test and lockfile conventions; tests
rarely carry design. Read surrounding code at a revision, not from disk: the
working copy is often ahead of or beside the range. jj: `jj file show -r
'<rev>' <path>`; git: `git show '<rev>:<path>'`. When git's `--to` is
`WORKTREE`, read the after side from disk.

Read the diff, then the surrounding code, until you can answer these
questions for the change:
- What was the flow before, and what is it now?
- Which components or services talk to each other, sync or async, and did
  that change?
- Where are the boundaries (package, API, layer, service)? For each, what
  does it expose to the outside, and which of those exposed artifacts did
  the change add, remove, or reshape?
- Which business-level behaviors does the application now guarantee at its
  major interfaces and across layer boundaries?
- What can go wrong, and where does each failure end up (returned to the
  caller as an error, logged and dropped, retried)?
- Which packages and domains does it touch? Who owns them (CODEOWNERS,
  module boundaries)? Did anything move across a boundary?
- Which values changed: config, flags, defaults, limits, schema?

You read code to answer those questions; the reader gets only the answers.
For a large change, delegate the surrounding-code reads to an Explore
subagent and keep the conclusions.

If you spot what looks like a bug, tell the user in chat afterwards. It
doesn't go on the page; this page is not a review.

### 3. Pick the topics (tabs)

A tab is one design topic the room can discuss in a few minutes: "retry
moves into the client", "orgs are probed, not listed", "config surface".
Typically 2–5.
- Split by design topic, not by file, layer, or commit.
- Don't split one topic across tabs, and don't pad: a small change can have
  one tab.
- Fold incidental changes (dependency bumps, docs, renames) into the topic
  they serve using `areas`, or leave them off the page if they serve none.
  They never get their own tab. Never mention tests or mocks anywhere on the
  page; the build already keeps them out of the trees.
- Order tabs the way you'd run the meeting: the core change first, then what
  it ripples into.

### 4. Draw each topic

| the room asks | block |
|---|---|
| who calls whom in a short, linear interaction (8 messages or fewer)? | `diagram` (sequenceDiagram) |
| who calls whom in a long interaction, or one with an ok/failure branch? | `walkthrough` (lanes revealed step by step, paths you can click) |
| what happens, in what order, and where does it branch? | `html` flow (before/after panels, steps, `vc-decision` diamonds with branches, ladders) |
| what does each boundary expose, and what changed shape? | `boundaries` (the exposed surface only) |
| how are the layers or the data shaped? | `html` (layer stack, payload shape, state matrix) |
| how is the application expected to behave? | the tab's `decisions` |
| what happens when things go wrong? | the tab's `failures` |
| anything else worth a line? | the tab's `etc` |
| where does it live, who owns it, what landed there? | automatic tree at the end of each tab: owners from `owners`, one line per package from `landed` |

A tab renders in this order: lede, Key decisions, blocks, Failure models,
Where it lands, Etc. A section with no items is left out. Key decisions are the
reader's entry point, directly under the lede: write them first and keep them
short, and let the blocks that follow explain them.

**Key decisions** are business-level statements about how the application
behaves, at its major interfaces and across layer boundaries: "returns all
reports ordered by name", "a one-off report is named after its run's title".
Code-level statements ("returns struct foo", "calls Validate") are not
decisions, and neither is every function juncture. A changed decision carries
a `was` line (shown in a "was" panel); a changed item with no `was` is a
build error, because if you cannot say what it was, it is new. Statements about how existing data or
clients are still handled (a backfill, an old shape the code tolerates) take
`state: "legacy"` and read "legacy handling", not "new".

**Failure models** show how the system behaves when things go wrong, as two
lines: `IF:` the cause, `THEN:` the expected final result ("returned to the
caller as 404", "logged and dropped"). Write `cause` so it completes "IF:"
and `result` so it completes "THEN:". Cover every failure path, but batch
them: a `Validate()` with ten checks is one failure, "the report must be
valid". Set `continues: true` when the failure is handled and processing
carries on (swallowed, logged and dropped, left out, retried); THEN then shows
blue instead of red. A changed failure carries `was: {cause?, result?}` with
the old IF and THEN; a failure whose behavior did not change is not listed as
changed.

**Etc** takes anything that is neither a decision nor a failure.

There are no notes, no write-ups of alternatives, and no discussion
questions. Never list what is out of scope or what stayed the same.

Colors mean the same thing everywhere: new, changed, and removed (dashed).
The page header holds four icon buttons: Legend (the full key), Theme
(matches the OS by default), Colorblind palette (protanopia, deuteranopia,
tritanopia), and Page width (Auto, or 10% to 100% of the window). The last
three open a short menu with a subtitle; the choices restyle every diagram,
tree, and table and are remembered. Diagrams open full window on click, and
walkthroughs have a Fullscreen button; both views have their own Width picker.
In a full-window walkthrough, left and right step and up and down switch
branches. A titled walkthrough has its own link (`#<tab>/<block>`, plus
`--fullscreen` to open it full window), so give each one a distinct title.
Never name colors in text or
captions ("the green node"); say "new", "changed", "removed" instead, so the
words stay true under every palette.

`boundaries` lists what each boundary offers the outside: exported or public
types, interfaces, functions, fields, endpoints, events, config. It renders
only the exposed surface, one card per directory, so it ties to the tree.
Name artifacts by their declared identifier (`AuthorizeEntities`, not an
invented `Client.AuthorizeEntities`); the build detects what a Go method or
field hangs off and shows it beside the name. A Go struct always shows as the
whole struct: list its changed fields (or the struct) and the build reads the
declaration from the code. The one exception is an existing struct with more
than five properties that is being modified; it shows its changes inside the
struct braces under a `// N properties hidden` comment. Internal helpers,
unexported consts, and private functions stay off it. If internal behavior
drives the design, show it in an `html` flow instead.

**Show interactions as sequence diagrams or walkthroughs.** Who calls whom,
across the interfaces a request touches, is a `diagram` when it is short and
linear (8 messages or fewer, no branch), and a `walkthrough` when it is longer
or has an ok/failure branch. In a `diagram`, mark a new, changed, or removed
span with a `rect new` / `rect changed` / `rect removed` block, never a Note.
A `walkthrough` marks a step `add`, `mod`, or `del` instead. List the shared
steps first, then a `split` of named branches: `ok` and `failure` paths, each
ending the flow (`ends: true`) or rejoining the steps that follow. Where the
split is in the middle, put the steps after it in the next segment.

**Draw flows as HTML, not Mermaid.** Mermaid flowcharts read poorly on a
shared screen. Compose flows from the flow kit in `references/blocks.md`:
before and after panels side by side, each a column of steps with arrows;
a step is a box with one line saying what happens and an optional detail
line with the one fact that changed; branches sit side by side, with the
fallback path dashed; ladders, retries, and tiers are rows of a label chip
plus a step, joined by labeled arrows. **Every condition is a diamond.** A
`vc-decision` holds the question, and the branches that follow carry the
answers; never put "if", "when", or "for condition" in a step or a branch
title. Mark only what the change touched as new, changed, or removed, and keep
before and after structurally parallel. End a branch with a `term` pill when
it stops there (■, or ✕ with `err` for an error) and leave it open when it
continues; the page draws open branches joining below the fork. Put a
condition that changes the path but not the step's one fact in a `vc-aside`,
never in `vc-detail`. Study the example in
`references/blocks.md` before your first one.

Use what the topic needs. One rich picture beats six thin ones.

**Reshaped designs show before and after.** When the change alters something
that already existed, the room needs the old shape next to the new one:
- changed flow → `html` before/after panels (`vc-ba`), with changed steps
  `mod`, new ones `add`, removed ones `del`;
- changed short interaction → `diagram` sequence pair, same participants; a
  long or branching one → a `walkthrough` with `state` on its steps;
- changed contract → `boundaries` artifact marked changed, with
  `sig.before`/`sig.after`; a struct shows whole with its changed fields marked;
- changed behavior or value → a `decisions`, `failures`, or `etc` item, with
  a `was` line (required when the item is changed).

Pure additions show only the new shape.


### 5. Write the words, and few of them

- **Overview summary:** 3–4 sentences, hard limit 4. State the problem, the
  approach, and the one consequence the room should carry into the tabs. It
  helps people switch context, so no file names or symbol lists.
- **Lede:** one sentence per tab.
- **Landed lines:** one line per package in the tree saying what landed
  there ("client and helpers for org-permission auth checks").
- **Decisions and failures:** one short statement each, in present tense, for
  the behavior after the change. A failure is a cause and a result.
- **Declarations (`sig`):** copy them as written in the code at the
  revision, trimmed to exported members; never paraphrase a signature. Give
  a func or method on one line, joined if the source wraps it; the build
  re-wraps wide ones one parameter per line. Go structs need no `sig`: the
  build reads them from the code.
- No paragraphs anywhere else. If a topic needs a paragraph, draw it instead.

### 6. Write the spec and build

Read `references/blocks.md` before writing the spec. It covers every field,
the flow kit with a worked example, and the sequence-diagram conventions.

Save the spec as `<workdir>/<slug>.json`. `<workdir>` is the session's
scratchpad directory, or `/tmp/visualize-changes/` if there is none; `<slug>`
is a short kebab name for the change. `build.py` reads and writes only under
`/tmp`. Then:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build.py --spec <workdir>/<slug>.json \
  --repo <repo-root> --from '<from>' --to '<to>' --verify
```

- **Errors** stop the build; fix the spec and rerun. Examples: a name not
  found in the code, a multi-line string, more than 4 overview sentences.
- **Coverage warning:** lists changed packages that belong to no tab. Put
  each one in a boundary (`paths` or an artifact `file`) or a tab's `areas`.
  Packages with only test or doc changes are exempt.
- **`--verify`** renders the standalone page in headless Chrome and reports
  sequence-diagram errors and horizontal overflow at narrow width. It checks
  rendering, not meaning: read your pictures once against the code. Fix and rerun until
  it reports ok. If Chrome is blocked by the sandbox, rerun that command with
  the sandbox disabled.

The build writes two files beside the spec:
- `<slug>.html`: standalone document. Use it for attaching to Jira or
  Confluence.
- `<slug>.artifact.html`: the same page for the Artifact tool.

Both load Mermaid for sequence diagrams from jsDelivr and render them
themselves, so the theme and colorblind pickers work everywhere. Without
network (or where a preview blocks outside scripts), sequence diagrams show
as their source text; flows, maps, trees, and tables are plain HTML and
always render.

### 7. Publish and report

Publish `<slug>.artifact.html` with the Artifact tool. Pass `icon: "code"`
on the first publish and a one-sentence `description` naming the change. The
template already meets the Artifact page contract (title, theme tokens, dark
mode, phone width), so don't restyle it. When you rebuild the same change,
republish the same file path to keep the URL.

Then tell the user, in at most four lines:
- the Artifact link;
- the standalone file path for Jira or Confluence. An HTML attachment opens
  in the browser; Confluence's HTML macro is usually disabled, so attach it
  rather than embed it;
- the agenda (tab names);
- any suspected bugs you noticed, as a separate line. They are kept off the
  page.

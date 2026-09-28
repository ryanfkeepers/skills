---
name: load
description: >-
  Load a specified thing into context by exploring it -- a jj revision, a
  file or directory, a URL, a ticket, or a topic in the repo. Read-only
  exploration only. Use when the user invokes /load, or says "load X into
  context", "pull up X", "get familiar with X" before other work.
argument-hint: "<target>"
---

# Load

Pull named target into context via exploring it. Result: knowledge in
context plus short orientation summary -- nothing else.

Action is always exploration. `/load` never signals code change,
proposed changes, next-step offers, or user questions. If exploration
reveals a bug, stale doc, or missing feature, note it in one line in
the summary and stop.

Do all exploration yourself, this session. Point of this skill: put
material in *your* context -- a sub-agent's context is discarded when
it returns, so delegating defeats the skill. Never spawn a workflow,
never delegate reading of a target you can read directly.

One exception: when target surface area is too large for this context
-- a whole subsystem, a repo you've never opened, a sprawling package
with unknown layout -- delegate the *locating* pass to the `Explore`
agent to get back the file list and entry points, then Read those
files yourself. Delegate the map, never the territory. Always force
the `Explore` agent onto the `haiku` model -- pass `model: haiku` on
every spawn, no exceptions.

Never ask a clarifying question. If target is ambiguous, pick the most
probable interpretation given the current working directory and
conversation, state that assumption in one line, and explore it. User
corrects you next turn if wrong.

Counter-example (avoid):
> User: "/load current revision"
> Assistant summarizes the diff, then edits the files it found to fix a
> nit, or asks "want me to clean this up?"

Voice example (correct):
> User: "/load current revision"
> Assistant reads the diff, reports what changed and where, and stops.

## Step 1 -- Classify the target

Match the argument to one of these, then follow that branch:

| Target looks like | Branch |
| --- | --- |
| `current revision`, `@`, a change ID, `main..@` | Revision |
| a path, glob, package, or symbol name | Code |
| `http://` / `https://` | URL |
| a ticket key, Confluence page, alert, or incident ID | External system |
| a bare concept or feature name | Topic |

Multiple targets in one invocation allowed -- explore concurrently.

## Step 2 -- Explore, read-only

Use only read-only tools, directly -- Read, Grep, Glob, read-only Bash,
WebFetch, WebSearch, MCP queries. Never Edit, Write, or run a
state-mutating command. Delegate only under the large-surface
exception above, and only for locating files.

**Revision:** `jj show --no-pager` for the revision (or `jj diff
--no-pager -r <rev>`), then read the touched files around the changed
hunks -- the change needs surrounding context, not just the diff.

**Code:** Glob and Grep to locate the target when layout is unknown,
then Read the files yourself. If target spans many files or a
subsystem you've never opened, use the `Explore` agent for the
locating pass only, forced onto the `haiku` model (`model: haiku`) --
ask for relevant paths and entry points, not an explanation -- then
Read those paths directly. Follow the call graph one hop out from the
target -- callers and callees -- so the target is situated, not
isolated.

**URL:** WebFetch the page. Follow at most one hop of links, only when
the first page explicitly defers to another for the substance.

**External system:** use the available MCP tools (Jira, Confluence,
incident.io, Microsoft Learn). Read the record and its directly
attached content (comments, linked issues, child pages) -- don't walk
the whole graph.

**Topic:** search the repo for the concept's vocabulary first (Grep for
the term, likely type names, doc files). Fall back to WebSearch only
for genuinely external concepts.

Stop once you can describe the target's shape, its parts, and where
each lives. Don't exhaustively read everything reachable.

## Step 3 -- Report the orientation summary

Report what's now in context, tersely, with references — scannable in
one read. Structure:

- **What it is** -- one or two sentences.
- **Parts** -- the components, files, or sections, each with a
  `path/to/file.go:42` reference or URL.
- **Notable** -- only the few items that stand out: anything surprising, broken, or
  in tension with the surrounding code. State it; don't act on it.

Never fabricate a path, line number, or URL. Cite only what you read.

Voice example (correct):
> Working-copy change `kxmz` touches the retry path.
> - `retry.go:31-58` -- `attempts++` moved above the early return.
> - `retry_test.go:104` -- new case for transient 5xx.
> Notable: `backoff.go:22` still caps at 3 attempts, so the new test's
> 5-attempt expectation depends on the caller's override.

Counter-example (avoid -- dumping raw output):
> Pasting the entire `jj diff` or full file contents back to the user.

## Step 4 -- Stop

Summary is the whole response. No proposed edits, offers, questions,
plan.

---
name: visualize-design
description: >-
  Build a tabbed HTML page of a *proposed* design, before any code is
  written, so the person who asked for it can validate it and push back
  before committing to it. Top tabs are the chunks of the design; each holds
  the same second-level tabs (goal, contract, shape, flow, failure models,
  placement, relationships). It uses the same page shell as visualize-changes
  (same look, settings, links, hotkeys), with content aimed at one decision
  maker rather than developers getting up to speed. Publishes a claude.ai
  Artifact link and writes a standalone .html. Use when the lens pipeline
  reaches its visualize-design lens, when the user invokes /visualize-design,
  or when they want to see or sanity-check a design or plan visually before
  implementing it. Not for visualizing code that's already written (use
  visualize-changes).
---

# visualize-design

The reader is the person deciding whether this design goes ahead. Every page
answers one question: **"Is this the design I want?"** That's different from
visualize-changes, which brings other developers up to speed on code that's
already written. Here nothing is built yet, so the page shows intent:
- what will exist
- where it will land
- how it will behave
- how the parts depend on each other

Show only what the design decided. Never show forks the design picked a
default for, cuts it made, or alternatives it rejected: the reader is not
part of those choices.

The shell is shared. `${CLAUDE_SKILL_DIR}/../../shared/viz-shell/` owns
layout, theming, settings, tabs, links, hotkeys, the flow kit, walkthroughs,
and both output formats. Your job is only the content.

## Inputs

- **In a lens run**, the dispatch prompt names the run directory. Read only
  these files:
  - `brief/goal.json`, `brief/non_goals.json`, `brief/assumptions.json`
  - `design/*.json`, chiefly `design/chunks.json` (the chunks, their flows,
    failures and dependencies) and `design/shape.json` (the declarations)
  - `context/touchpoints.json`
  - the contract-layers core (`LENSCTL core resolve --run <run> --kind
    contract-layers --paths <placement paths>`)
- **Standalone**, use the design or plan the user gives you. Ask for
  anything missing in one message, and split it into chunks by the rules in
  `plugins/lens/agents/design.md` ("Chunks").

## Page layout

**Overview** (`overview.summary`, up to 4 sentences): the goal and the
approach in one line. Its `overview.blocks`, in order:
1. a `layers` block: every chunk placed in its layer band
2. a `goal` block of the run's non-goals as `constraints`, only when there
   are any

**Top tabs** are the chunks from `design/chunks.json`, in dependency order
(a chunk's `uses` come before it). Each top tab has a `title`, a one-line
`lede`, and `children`: its second-level tabs. Top tabs hold no blocks.

**Second-level tabs**, in this order, each left out when nothing in the
design applies to it:

| key | title | content |
|---|---|---|
| `goal` | Goal | a `goal` block: the run's intents, assumptions and non-goals as constraints. The same on every chunk. |
| `contract` | Contract | a `declarations` block of the chunk's exported components only (Go: capitalized names), from `design/shape.json`. Left out when nothing is exported. |
| `shape` | Shape | a `declarations` block of structures, interfaces and consts, exported or not. |
| `flow-<name>` | Flow: <name> | one tab per entry in the chunk's `flows`. A `walkthrough` for interactions between parts, an `html` flow (flow kit) for branches. Add `vc-ba` before/after only where the flow changes existing behavior. |
| `failures` | Failure models | the chunk's `failures` as `failures` items. Show both failouts and handled cases: `continues: true` for a failure the design handles and carries on from. No `blocks`, and no `state` unless existing behavior changes. |
| `placement` | Placement | a `placement` block of where the chunk's components land, new versus existing packages. |
| `relationships` | Relationships | a `relationships` block: what the chunk uses (from its `uses`) and what uses it (invert every other chunk's `uses`), each row a link to the tab that defines the thing. |

A chunk's `components` and `uses` name entries in `shape.json`; link each
`uses` to that component's chunk and tab (`contract` when exported, else
`shape`).

Tone: state what the design is. Don't hedge it, and don't narrate what was
considered.

## Spec

Same format as visualize-changes. Read
`${CLAUDE_SKILL_DIR}/../../shared/viz-shell/blocks.md` before writing the
spec, including its two-level `children` tabs. Leave out the fields that
belong only to visualize-changes: `owners`, `landed`, `areas`, and
`boundaries` blocks. Do not use `decisions`, `etc`, or `badge`: they carry
forks and trims. This skill adds these block types:

```json
{"type": "goal", "intents": ["..."], "assumptions": ["..."], "constraints": ["..."]}
```
At least one list; empty lists are left out.

```json
{"type": "declarations", "items": [
  {"name": "Send", "kind": "func", "file": "internal/queue/send.go",
   "sig": "func (q *Queue) Send(ctx context.Context, m Message) error",
   "state": "add", "what": "blocks until persisted"}
]}
```
One card per directory of `file`. `state` is `add` (default) or `mod`. `sig`
is a declaration, never a body: at most 20 lines. `what` is one short line.

```json
{"type": "layers", "layers": [
  {"name": "transport", "chunks": [{"chunk": "send", "state": "add"}],
   "boundary": "enqueue(msg) crosses to business"},
  {"name": "business", "chunks": [{"chunk": "receive", "state": "mod"}]}
]}
```
Layers top to bottom. `chunk` is a top-tab key; each chip links to that
tab. `boundary` is what crosses to the next layer, drawn as a line between
the two bands; omit it on the last layer.

```json
{"type": "relationships", "entries": [
  {"dir": "uses", "chunk": "send", "tab": "contract", "what": "Send on redelivery"},
  {"dir": "used_by", "chunk": "dlq", "what": "dead-lettering after retries"}
]}
```
`dir` is `uses` or `used_by`. `chunk` is a top-tab key and `tab` an optional
second-level key in it; the row links there.

```json
{"type": "placement", "title": "Where it lands", "entries": [
  {"path": "internal/retry", "state": "add", "what": "retry policy"},
  {"path": "store/blob", "state": "mod", "what": "wraps writes in the policy"},
  {"path": "api/http", "state": "same"}
]}
```
`state` is `add` (new), `mod` (changed), or `same` (existing, shown only for
context). `what` is one short line.

## Build and publish

Save the spec as `/tmp/<slug>/<slug>.json`. Build only reads and writes under
`/tmp`. Then run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build.py --spec /tmp/<slug>/<slug>.json --verify
```

Fix every error, and every verify problem except a missing Chrome. Publish
`<slug>.artifact.html` with the Artifact tool (`icon: "map"` on the first
publish, plus a one-sentence `description`). Report the Artifact link, the
standalone path, and the top-tab names.

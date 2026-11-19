---
name: visualize-design
description: >-
  Build a tabbed HTML page of a *proposed* design, before any code is
  written, so the person who asked for it can validate it and push back
  before committing to it. It uses the same page shell as visualize-changes
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
- every choice and assumption, made visible so the reader can challenge it

The shell is shared and fixed. `${CLAUDE_SKILL_DIR}/../../shared/viz-shell/`
owns layout, theming, settings, tabs, links, hotkeys, the flow kit,
walkthroughs, and both output formats. Your job is only the content.

## Inputs

- **In a lens run**, the dispatch prompt names the run directory. Read only
  these files:
  - `brief/goal.json`, `brief/non_goals.json`, `brief/assumptions.json`
  - `design/*.json`
  - `trim.json`
  - `context/touchpoints.json`
  - the contract-layers core (`LENSCTL core resolve --run <run> --kind
    contract-layers --paths <placement paths>`)
- **Standalone**, use the design or plan the user gives you. Ask for
  anything missing in one message.

## Tabs (a starting set, expect it to change)

1. **Overview** (`overview.summary`, up to 4 sentences): the goal, the
   approach in one line, and what's out of scope.
2. **Shape by layer**: new and changed components placed on the contract
   layers (transport → business → store, plus sdk/public). Draw it as an
   `html` block with the flow kit: a `vc-flow` of layer steps, with
   `add`/`mod` on the new and changed pieces.
3. **Flow**: the proposed happy path and error path. Use a `walkthrough` for
   interactions between parts, and an `html` flow for branches. Show
   before/after (`vc-ba`) wherever existing behavior changes.
4. **Placement**: a `placement` block (below) with where each piece lands,
   new versus existing packages.
5. **Decisions & trims**:
   - forks the user chose: `decisions`, state `add`
   - cuts design-trim made: `decisions`, state `del`, phrased as "No <thing>"
   - assumptions from intake: `etc`

Tone: invite pushback. State each decision and assumption plainly enough to
disagree with, and never bury a choice inside a diagram.

## Spec

Same format as visualize-changes. Read
`${CLAUDE_SKILL_DIR}/../../shared/viz-shell/blocks.md` before writing the
spec. Leave out the fields that belong only to visualize-changes: `owners`,
`landed`, `areas`, and `boundaries` blocks. This skill adds one block type of
its own:

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
standalone path, and the tab names.

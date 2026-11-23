---
name: visualize-bug
description: >-
  Build a tabbed HTML page that explains to a developer how a bug occurs: the
  conditions that must hold for it to fire, the sequence of events and state
  that leads to the wrong result, and a minimal way to reproduce it. It is
  about when and why, never where in the code. Uses the same page shell as
  visualize-changes and visualize-design (same look, settings, links,
  hotkeys), drawn as HTML with no Mermaid and no code. Publishes a claude.ai
  Artifact link and writes a standalone .html. Use whenever the user wants to
  understand, explain, or show someone how a bug happens, why something only
  fails sometimes, what triggers a flaky failure or race, or how to reproduce
  a bug, or invokes /visualize-bug, even if they don't say "visualize". Not
  for locating the faulty line (use diagnose) and not for describing a change
  (use visualize-changes).
user_invocable: true
---

# visualize-bug

The reader is a developer who has to understand a bug, usually one that
doesn't fail every time. The page answers one question: **"Under what
conditions does this happen, and why?"** When they close it they should be
able to predict whether a given situation triggers the bug and reproduce it on
demand.

That sets what belongs on the page:
- **Yes:** the factors that must be true, the ones that only make it likelier,
  and the ones that look related but change nothing; the order of events and
  what each party believes at each moment; how often it fires and what turns
  that up or down; a recipe a person could follow.
- **No:** code, file names, line numbers, stack traces, the fix, blame. Showing
  where the bug lives hands the reader a location without understanding, and
  they still can't tell when it will fire. If a name is needed to be exact,
  give it as a short label inside a step.

The shell is shared and fixed. `${CLAUDE_SKILL_DIR}/../../shared/viz-shell/`
owns layout, theming, settings, tabs, links, hotkeys, the flow kit and
walkthroughs. Your job is the content. Don't hand-write page HTML or CSS.

## Steps

### 1. Establish the conditions before drawing anything

The page makes claims about causes. A matrix that presents a guess as fact is
worse than no page, so earn each claim first.

- Start from what the user gave you: a report, ticket, log, failing test, or
  description. Ask for what is missing in one message.
- Read the code until you can say what mechanism produces the wrong result.
  You read code to understand; the page shows only the understanding.
- List candidate factors: what must be true for the bug to fire, what only
  changes how often, and what looks related but may not be (the usual
  suspects the reader will otherwise wonder about).
- Test each factor with a counterfactual: a case where only that factor is
  off. Run it when you cheaply can, from a throwaway script or test in the
  session's scratchpad. Never edit the repo to do it. A factor you ran is
  `confirmed`; one you only reasoned about from the code is `inferred`. If a
  repro needs repo edits, mark it `inferred` and tell the user.
- Give `rate` only from runs ("about 1 in 20 over 200 runs"). Without a run,
  use qualitative words and leave out numbers.

If you find the cause is not what the user believed, say so in chat and
build the page around what you found.

### 2. Pick the tabs

Typically 2–4. Always lead with the conditions tab, since it is the point of
the page. Add the others only when they teach something:

| tab | answers | draw it as |
|---|---|---|
| When it fires | what must be true, what only helps, what is irrelevant | a `conditions` block (below) |
| How it happens | what order of events or state changes ends wrong | a `walkthrough` that splits into the good path and the bug path; plus an `html` table of what each party believes at each moment |
| Reproduce it | a recipe a person can follow, and what changes the odds | an `html` flow of the recipe ending in a `vc-decision` ("reproduced?"), and a knobs table |

Fit the picture to the bug, not the other way round:

| the bug depends on | show |
|---|---|
| timing or ordering (races, retries, ordering of events) | walkthrough with an ok branch and a failure branch; a state-over-time table with the first wrong cell marked |
| the shape or value of an input | the path the input takes as `vc-decision` diamonds, with the one branch that ends in the bug |
| accumulated or lifecycle state | a state matrix of states by event, with the bad transition marked |
| a limit, size, or load | a `vc-rung` ladder of thresholds, with where behavior flips marked |
| config or environment | the `conditions` matrix with the config values as string cells |

Use what the bug needs. One clear picture per tab beats several thin ones.

### 3. Write the words, and few of them

- **Overview summary:** at most 4 sentences: the symptom, the trigger, why it
  happens, how reliably it fires. No file names or symbol lists.
- **Lede:** one sentence per tab.
- **Walkthrough steps:** `label` is what is sent or checked; `what` says what
  that party believes or does, in one sentence. Put the moment the state goes
  wrong in a step's `detail` ("the tipping point: neither has committed").
- **`etc`:** plain one-line strings. Use it for what was and wasn't tried
  ("not tried: a second server instance"); that is how the reader knows how far
  to trust the page.
- No paragraphs. If a point needs a paragraph, draw it.

Colors mean the same thing everywhere on this page. Use the kit's state
classes for them: `add` is expected behavior, `mod` is the tipping point (the
moment or condition that tips toward the bug), `del` is the wrong behavior.
Never name a color in text; say "the bug", "expected", "tipping point". The
Legend button in the page header shows the key.

## Spec

Same format as the other visualizers. Read
`${CLAUDE_SKILL_DIR}/../../shared/viz-shell/blocks.md` for the top level, tabs,
`walkthrough`, `html` and the flow kit. For this skill:

- **Leave out:** `owners`, `landed`, `areas`, `boundaries`, `diagram` (no
  Mermaid), and a tab's `decisions` and `failures`. The build rejects the
  last three.
- **Block types:** `conditions`, `walkthrough`, `html`.
- A complete working spec is at
  `${CLAUDE_SKILL_DIR}/references/example-spec.json`; copy its shape.

### conditions

```json
{ "type": "conditions", "title": "What has to be true",
  "factors": [
    { "key": "same-key", "name": "Same order key sent twice", "role": "required",
      "evidence": "confirmed", "note": "different keys never collide" },
    { "key": "slow-store", "name": "Store write takes over 50 ms", "role": "contributing",
      "evidence": "confirmed", "note": "widens the gap" },
    { "key": "mobile", "name": "Request comes from the mobile app", "role": "irrelevant",
      "evidence": "confirmed" }
  ],
  "scenarios": [
    { "label": "Double-tap, fast store", "minimal": true, "outcome": "bug", "rate": "about 1 in 20",
      "values": { "same-key": true, "slow-store": false, "mobile": false } },
    { "label": "Two different keys at once", "outcome": "ok", "rate": "never",
      "values": { "same-key": false, "slow-store": true, "mobile": false } }
  ] }
```

A matrix with one column per factor and one row per scenario, an outcome
pill per row, and the minimal repro row outlined.

- `role`: `required` (the bug never happens without it), `contributing` (makes
  it likelier or wider, not needed), or `irrelevant` (looks related, changes
  nothing; drawn faded).
- `evidence`: `confirmed` (you ran it) or `inferred` (you read the code).
- A scenario's `values` list every factor: `true`, `false`, or a short string
  (`"any"`, `"1 MB"`). `outcome` is `bug` or `ok`. `minimal` marks the one
  scenario with only the required factors on.
- A factor that is a quantity rather than a switch (depth, size, load) shows
  its real values as strings (`"12 layers"`). List the strings that count as
  that factor being off in the factor's `off` (`["6 layers"]`); the build
  treats them like `false` for its checks, so the quantity can still be
  proven required.
- The page is the proof, so the build checks it: it errors when a bug
  scenario has a required factor off, when a scenario omits a factor, or when
  there is no bug scenario or fewer than 2 scenarios. It warns when a required
  factor has no ok scenario with only that factor off (its necessity is
  unproven), or when there is no minimal repro. Fix every warning by adding the
  counterfactual scenario, not by silencing it.
- Keep to 6 factors and 10 scenarios or fewer; past that the pattern is lost.

## Build and publish

Save the spec as `<workdir>/<slug>.json`. `<workdir>` is the session's
scratchpad directory, or `/tmp/visualize-bug/` if there is none; `<slug>` is a
short kebab name for the bug. Build only reads and writes under `/tmp`. Then:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build.py --spec <workdir>/<slug>.json --verify
```

Fix every error and every warning, and every verify problem except a missing
Chrome. If Chrome is blocked by the sandbox, rerun with the sandbox disabled.
Read the finished pictures once against what you established in step 1: the
build checks the matrix is self-consistent, not that it is true.

Publish `<slug>.artifact.html` with the Artifact tool (`icon: "bug"` on the
first publish, plus a one-sentence `description` naming the bug). Republish
the same file path to keep the URL. Then tell the user, in at most four lines:
- the Artifact link;
- the standalone `.html` path;
- the tab names;
- what is only inferred, not run, and anything you learned that contradicts
  the report.

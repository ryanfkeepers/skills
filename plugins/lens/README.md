# lens

A lens is a small, bounded task with a strong opinion about its purpose. This
plugin runs a flat, ordered list of lenses that turns a proposal into a stack
of PRs. Each lens runs as its own sub-agent with only the inputs it needs.
The orchestrator only coordinates. `scripts/lensctl.py` (code, not an agent)
owns state, scheduling, retries, relayed questions, disputes, rewinds,
settlement, and the report.

```
/lens:init                            build the cores a run needs (user approves each)
/lens:run <proposal> [--base <rev>]   start a run (the repo must be initialized)
/lens:resume [run-dir]                continue an interrupted or halted run
/lens:conventions --refresh           rebuild the conventions core (user approves)
/lens:contract-layers --refresh       rebuild the contract-layers core (user approves)
```

## Requirements

- The `keepers` plugin. Lenses call `assert-green`, `adversarial-validator`,
  `fix-my-nits`, `split-rev`, `push-pr-stack`, `make-human-ticket`,
  `address-pr-requests`, `visualize-design`, and `visualize-changes`.
- `jj`, `graphify`, `gh`, and `vibediff` on PATH.
- `codex` is optional. adversarial-review uses it when present, and a
  different Claude model otherwise.

## Storage

Nothing is written inside the repo. Everything lives under
`~/.claude/lens/<repo-slug>/` (override with `LENS_HOME`):

```
graph/core/            central graphify graph tracking trunk, in its own jj workspace
graph/snapshots/<run>/ per-run base + live snapshots
conventions/           repo conventions core (user-approved markdown)
contract-layers.md     contract-layer core (user-approved markdown)
services/<svc>/        per-service overrides of the two cores
<run-id>/              status.json, qa/, disputes/, summaries/, workspace/ (the
                       run's jj workspace), and every lens artifact (terse JSON)
```

## Lens order

`pipeline.json` is the source of truth. Code lenses run inside lensctl. The
`lenses` list is the run. The `init` list (graph-core* → conventions →
contract-layers) is what `/lens:init` runs: a run never builds a core, and
`/lens:run` exits at once when the graph, conventions, or contract-layers core
is missing.

intake → workspace* → graph* → explore →
design → design-trim → visualize-design → plan → build grid (scaffold,
implement, unit-test, test-coverage per task) → green → negative-catch (fixes only) →
review-select → review set 1 →
review set 2 → pseudolinter → vibediff → visualize-changes → docs ∥ comments
→ scenarios → contract ∥ integration ∥ e2e tests → negative-catch (fixes only) → ticket → stack-shape →
describe (per slice) → apply-descriptions* → publish → wait → pr-followup →
wait → pr-followup → run-report* → cleanup*

(* = code lens)

## Ad-hoc lenses

Deviations from the pipeline are always additive. The orchestrator may add a
lens to one run with `lensctl add-lens --name <n> --agent <agent in agents/>
--after <established lens>`. The entry lives in that run's `status.json` only
and `pipeline.json` is untouched. lensctl rejects a name the pipeline already
uses, an agent that is not in `agents/`, an ad-hoc anchor, and an anchor behind
a lens that has started. No command skips, removes, reorders or replaces an
established lens. The report lists the ad-hoc lenses a run added.

## Coordination, in code

- **Build grid**:
  - A task starts once every task in its `blocked_by` has settled.
  - A test task (`"kind": "test"`: the tests are the deliverable, such as a
    benchmark) gets only an implement cell, which may write its test targets.
    Routine tests for a code task are never a task; its unit-test cell
    writes them.
  - Independent tasks run at once (up to 32 agents) in the single
    workspace, except tasks that share a file in `shared_files`.
  - After each cell, lensctl checks that the cell changed only files it was
    allowed to. Anything else is restored and the cell fails.
  - A failed cell is retried alone. A retry that passes alone counts as a
    spurious failure.
  - Whole-repo operations (tidy, codegen) run in `green`, which runs alone
    after the grid.
- **After the grid** the run is one change, not a set of tasks. No lens
  after the grid reviews, tests, or routes by task. A dispute that names a
  build cell (from `green` or `negative-catch`) rechecks that cell, and every
  cell after it, for every task.
- **Change-type gates**: a lens with `only_for` in `pipeline.json` runs only
  when `brief/change_type.json` is one of those types. An unknown type runs
  it. Both negative-catch lenses are `only_for: ["fix"]`.
- **Settlement** (both review sets and the second test set):
  - Each group starts by checking that the run is exactly one revision on
    `workspace.base_commit`, and halts otherwise.
  - Every reviewer reviews the whole change once. Only contract-test fans
    out, once per boundary. Each dispatched reviewer, triage, or fix is a
    task-action.
  - Before review set 1, `review-select` rules out the reviewers with no
    surface in the change (`review-select.json`). It errs toward keeping a
    lens, and the `always` list in `pipeline.json` (correctness, conventions)
    is never dropped. A missing selection drops nothing.
  - A reviewer with nothing at all in scope replies `not_applicable`. When it
    was a full-scope review, lensctl retires that lens (per boundary for contract-test) for the rest
    of the pass, so fix epochs don't re-dispatch it. Retirement resets on a
    rewind. The report lists dropped and retired lenses.
  - Reviewers read a pinned epoch (the run revision's commit id).
  - Triage validates findings in batches.
  - One writer at a time applies them: `fix` for blocking findings,
    `review-patcher` for deferred ones.
  - Each write starts a new epoch. Only the lenses whose scope touches the
    changed files and their 1-hop graph neighbors re-review, and only that
    radius.
  - Blocking findings settle first, then deferred ones.
  - Design findings and findings that keep coming back go to the user.
  - Caps: 2 fix rounds per finding, 16 epochs per pass.
- **Human feedback** from vibediff and visualize-changes is routed by kind:
  - Code notes become confirmed findings for review set 1, which starts
    straight at the fix.
  - Design notes rewind the run to design.
  - Goal changes rewind it to intake.

## Lens contract

Every `agents/<lens>.md` has frontmatter `name`, `description`, `tools`, and
**no `model`** (adversarial-review is the only exception, and it picks one
at run time). The body states the lens's purpose, the exact files it reads
and writes, what it must not do, and when it's done.
- **Asking the user**: append
  `{"question", "options", "recommendation", "rendering"?, "answer": null}` to
  `qa/<key>.jsonl` and return `needs_input`.
- **Blocked by an earlier lens**: write `disputes/<key>-<n>.json`
  (`{"target_lens", "claim", "evidence"}`) and return `blocked`.
- **Reply**: every lens ends with one JSON line:
  `{"status": "done|needs_input|failed|blocked", "summary": "..."}`. Reviewers
  may also reply `not_applicable` (see Settlement).

## Tests

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/lens/scripts
```

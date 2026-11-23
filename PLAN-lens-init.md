# Plan: lens init split

Plugin: `plugins/lens`. Status: approved plan, not implemented.

## Goal

A lens run no longer builds the repo's cores. `/lens:run <proposal>` starts
with a quick check that the graph, conventions, and contract-layers cores are
all present. If any is missing, it tells the user which one and to run
`/lens:init`, then exits before creating a run directory, workspace, or
state.

A new `/lens:init` skill takes over the building. It builds the core graph,
then conventions, then contract-layers, showing the full text of each pending
core to the user for approval. On an already-initialized repo it moves the
graph to trunk and builds only what is missing. It never overwrites or
deletes anything.

After init, changes to the cores work as they do today: a run advances the
graph to trunk, and `/lens:conventions --refresh` and
`/lens:contract-layers --refresh` rebuild a core with approval.

## Scope

In scope:

- `scripts/lensctl.py`: initialized check, init mode, `--only` across both
  lens lists.
- `scripts/cores.py`: split the graph-core build/advance step out of
  `graph_lens`.
- `pipeline.json`: add an init/core list, remove `conventions` and
  `contract-layers` from the run list.
- New `skills/init/SKILL.md`.
- `skills/run/SKILL.md`: document the precondition and the failure path.
- `README.md`: command list, lens order, storage notes.
- `.claude-plugin/plugin.json`: minor bump 0.1.1 to 0.2.0 (a skill is added).
- Tests: `scripts/test_lensctl.py`, `scripts/test_cores.py`.

Out of scope: the conventions and contract-layers agent prompts, every other
lens agent, the `keepers` plugin, the two `--refresh` skills' behavior.

## Decisions (all confirmed by the user)

1. A repo is initialized only when graph, conventions, and contract-layers
   are all present.
2. The check runs inside `lensctl init` for a new run, before any run
   directory, workspace, or state is created. A failure prints an error that
   names the missing parts and says to run `/lens:init`, exits with code 1,
   and the run skill stops through its existing error path. Nothing is left
   behind.
3. `--resume` skips the check.
4. "Graph present" means `graph/core/commit` and `graph/core/out/graph.json`
   are both on disk. "Conventions/layers present" uses the existing
   `core_exists`, so a repo-level or per-service core counts, as today.
5. The run's `graph` lens stops building the core graph from scratch. It
   still moves the core to trunk when the run is newer and still snapshots
   per run. If the core graph is missing it halts with a clear error.
6. `conventions` and `contract-layers` leave the run's lens order. The agent
   files stay, because init and the refresh skills use them.
7. `/lens:init` creates a lensctl run limited to the init lenses and drives
   it with `lens:run --resume`, as the two existing core skills do. Order:
   graph-core, conventions, contract-layers. Graph goes first because the
   other two read it.
8. The graph-core step has no run workspace to use. It builds or advances
   the core graph against `trunk()`. The per-run snapshot step stays in the
   run's `graph` lens.
9. `/lens:init` on a repo with some parts present builds only the missing
   parts. Present parts are never rebuilt, overwritten, or deleted. The graph
   is always moved to trunk when trunk is a descendant of the core's commit.
10. The init run has no proposal and none of the run lenses. It uses a
    placeholder proposal text.
11. The user sees the full text of every pending conventions and
    contract-layers file before approving. The two agents already do this,
    so their prompts do not change.
12. `/lens:conventions --refresh` and `/lens:contract-layers --refresh` keep
    working with the same forced-rebuild behavior. Because they select a lens
    with `--only <name>`, the two lens entries stay in `pipeline.json`, in a
    separate init/core list.
13. Runs started before this change still resume, because each run carries
    its own copy of the pipeline.
14. `lensctl init` gets an init mode (for example `--init`). It selects the
    init lenses in order, does not set `refresh`, and skips the initialized
    check. The existing "reuse core when present" skip gives "build only
    what is missing" with no new logic.
15. `--only` searches both the run list and the init/core list, and also
    skips the initialized check.
16. The refresh skills are not gated by the check. They only write cores the
    user approves, and the user may use them to finish a partial init.
17. A cut-off init (core workspace on disk, commit file missing) reads as
    not initialized. Init skips adding the workspace and builds the graph.
18. `lens:resume` with no argument may pick an init run as the latest run.
    That is intended: it resumes an interrupted init.

## Rules upheld

- The orchestrator only coordinates. `lensctl` and `cores.py` own state, the
  check, and init logic.
- Every core change needs user approval. Promotion happens only on an
  `approve` answer, and the reviewer sees full text, not a summary.
- Nothing destructive: init never overwrites or removes an existing core.
- Everything lives under `~/.claude/lens/<repo-slug>/`, never in the working
  tree.
- `pipeline.json` stays the source of truth for lens order. Lenses do not
  declare models.
- Core writes stay under the `graph/.lock` flock.
- Old runs still resume.
- jj only. No code changes until the user explicitly says to implement.

## Rules knowingly bent

- Runs no longer self-initialize. Building missing cores mid-run is removed
  on purpose, and `lens:run` gains a hard precondition.
- `pipeline.json` is no longer a single flat list. The run list stays flat.
  The init/core lenses move to a separate list read by `/lens:init` and the
  `--only` refresh skills. The README's "flat, ordered list" wording changes
  with it.
- The run's graph lens loses its first-build branch.
- The refresh skills are not gated by the check, so a core can be built
  through them on a repo that is not fully initialized.
- A new skill means a minor plugin version bump.

## Flow

```
/lens:init (new skill)                        /lens:run <proposal> (changed)
  |                                             |
  v                                             v
lensctl init --init  (new mode)               lensctl init
  |  order: graph-core -> conventions           |  initialized check (new)
  |         -> contract-layers                  |  graph + conventions + layers?
  |  no refresh flag, no check                  |-- missing --> error naming the
  v                                             |   missing parts, "run /lens:init"
lens:run --resume <init run>                    |   (exit, nothing created)
  |                                             v present
  +- graph-core (code lens, new)              run dirs created, normal pipeline
  |    build or advance core to trunk()         |
  |    (extracted from graph_lens)              +- intake -> workspace
  |                                             +- graph (snapshot only; halts if
  +- conventions  (existing agent)              |    core graph missing)
  |    skipped if core present                  +- explore -> design -> ... (unchanged)
  |    else pending -> full text -> approve
  |                                           /lens:conventions --refresh  (unchanged)
  +- contract-layers (existing agent)         /lens:contract-layers --refresh
       same as conventions                      lensctl init --only <name>
                                                (searches both lists, no check)
```

## Code touchpoints (evidence for the implementer)

- `scripts/lensctl.py:125-156` `cmd_init`: `--only` filter at 130-133,
  `refresh` flag at 153.
- `scripts/lensctl.py:179-183` `cmd_next`: the `reuse_core` skip.
- `scripts/lensctl.py:281-283` `CODE_LENSES`: register the graph-core step.
- `scripts/lensctl.py:937-986` `build_parser` and `main`: new flag.
- `scripts/cores.py:149-189` `graph_lens`: first-build branch at 165-166,
  advance branch at 167-168.
- `scripts/cores.py:233` `core_exists`.
- `pipeline.json:8-9`: the two core entries.
- `scripts/test_lensctl.py:254` and `:267`: tests for `--only` and core
  reuse need updating. New tests cover the check, init mode, and the split
  graph step.
- `skills/conventions/SKILL.md` and `skills/contract-layers/SKILL.md`: the
  pattern `/lens:init` copies.

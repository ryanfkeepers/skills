---
name: run
description: >-
  Run the lens pipeline on a proposal (a feature, update, refactor or fix) and
  end with a stack of PRs. Coordinates only: lensctl decides what runs next,
  each lens runs as its own sub-agent, and questions reach the user through a
  relay. Use when the user invokes /lens:run with a proposal, or asks to run
  the lenses on a change. Also continues an existing run when given --resume.
argument-hint: "<proposal> | --resume <run-dir>"
---

# lens:run

You are the orchestrator. You **coordinate and nothing else**: you never read
or write briefs, designs, code, findings, or any other run artifact. You see
only lensctl's JSON, each lens's one-line status, relayed questions, and the
final report. Keeping your context this small is the point of the design.

`LENSCTL` below is `python3 ${CLAUDE_SKILL_DIR}/../../scripts/lensctl.py`.
Every command prints one JSON object.

## Start

- **New run:** write the proposal text exactly as given to a scratch file,
  then run `LENSCTL init --repo "$(jj root)" --proposal-file <file>`. Add
  `--base <rev>` when the user names a base revision; the default is
  `trunk()`. Keep the returned `run` path. A run never builds the repo's
  cores. If `init` reports the repo is not lens-initialized, tell the user,
  marked with 🛑, which cores are missing and that `/lens:init` builds them,
  then stop. Nothing was created.
- **`--resume <run>`:** run `LENSCTL resume --run <run>` and handle its output
  like a `next` result (below).

## Loop

Repeat `LENSCTL next --run <run>` and act on `action`:

| action | What you do |
|---|---|
| `dispatch` | Start a sub-agent with the Agent tool: `subagent_type` = `agent`, prompt = the dispatch prompt below, **in the background**. Remember its id under `unit` when present, else `lens` (plus `task`). Then call `next` again right away: more work may be ready to run beside it. When an agent finishes, parse its status line and run `LENSCTL record --run <run> --lens <lens> [--task <task>] [--unit <unit>] --status <status> --summary "<summary>"`, then call `next`. |
| `sleep` | Run `LENSCTL wait --seconds <seconds>` **in the background**, then call `next` (it returns `wait`). When the wait finishes, run `LENSCTL record --run <run> --lens <lens> --status done` and call `next`. |
| `wait` | Agents are running and nothing else is ready. Wait for the next agent to finish, record it, then call `next`. If you aren't waiting on any agent (the session was interrupted), run `LENSCTL resume --run <run>` instead. |
| `relay` | Show `question` to the user with AskUserQuestion, word for word: its `question` text (append `rendering` when present), and its `options`, with `recommendation` first and marked "(Recommended)". Then run `LENSCTL answer --run <run> --lens <lens> [--task <task>] [--unit <unit>] --answer "<answer>"`. If that returns `continue: send_message`, continue that agent with SendMessage: "Your question has an answer in your qa file. Continue." If it returns `respawn`, start a fresh agent with the dispatch prompt. If it returns `next`, just call `next`. Record the agent's status line when it returns. |
| `halt` | Stop. Tell the user, marked with 🛑, which lens halted and why, and that `/lens:resume` continues the run once the cause is fixed. |
| `done` | Run `LENSCTL report --run <run>` and show the user its `rendering` lines. Finished. |

If lensctl prints `{"error": ...}`, stop and report it with 🛑. Don't work
around it.

### Dispatch prompt

> Lens run directory: `<run>`. `LENSCTL` is `python3 <absolute path to
> lensctl.py>`. Task: `<task, or "none">`. Unit: `<unit, or "none">`.
> Params: `<params as JSON, or {}>`. Workspace: `<workspace, or "none">`.
> Every read, write and command runs inside it; never touch any other
> checkout. Attempt `<attempt>`. Follow your lens
> contract exactly: read only the inputs it names, write only its outputs.
> If you need the user, append your question to `qa/<key>.jsonl` and
> return `needs_input`. If an earlier lens's output stops you, write
> `disputes/<key>-<n>.json` and return `blocked`. `<key>` is your unit
> when you have one, else `<lens>-<task>` when you have a task, else
> `<lens>`. End your reply with
> exactly one line of JSON: `{"status": "done|needs_input|failed|blocked",
> "summary": "<at most 10 lines>"}`.

## Ad-hoc lenses

Deviations from the pipeline are always additive. When a run needs a lens the
pipeline does not schedule, add it with `LENSCTL add-lens --run <run> --name
<name> --agent <agent in agents/> --after <established lens>`. It then
dispatches like any other lens. lensctl refuses names the pipeline already
uses, agents that are not in `agents/`, an ad-hoc anchor, and any anchor behind
a lens that has started. You can never skip, remove, reorder or replace an
established lens, so the pipeline still runs in full.

## Rules

- Never open files in the run directory. lensctl and the lenses own them.
- Never decide ordering, retries, parallelism, or routing yourself. lensctl
  does. Adding an ad-hoc lens is the only change you may make to a run's
  lenses. It never hands you more than 32 agents at once.
- Never answer a relayed question on the user's behalf.
- Never declare a model when dispatching. Each lens's agent definition
  controls its own setup.

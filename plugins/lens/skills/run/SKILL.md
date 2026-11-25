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
  like a `next --all` result (below).

## Loop

Run `LENSCTL next --run <run> --all`. It prints `{"actions": [...]}`: every
dispatch that is ready now, then the one action that ends the batch. Start
every `dispatch` in one message, as parallel Agent calls, then act on the last
action:

| action | What you do |
|---|---|
| `dispatch` | Start a sub-agent with the Agent tool: `subagent_type` = `agent`, prompt = the dispatch prompt below, **in the background**. Remember its id under `task_action` when present, else `lens`. |
| `sleep` | Run `LENSCTL wait --seconds <seconds>` **in the background**. When the wait finishes, run `LENSCTL record --run <run> --lens <lens> --status done --next`. |
| `wait` | Agents are running and nothing else is ready. Wait for the next agent to finish. If you aren't waiting on any agent (the session was interrupted), run `LENSCTL resume --run <run>` instead. |
| `relay` | When `question.chat` is true, print `question.rendering` as plain text, with no AskUserQuestion and no options, then take the user's next message verbatim as the answer. Never interpret it. Otherwise show `question` to the user with AskUserQuestion, word for word: its `question` text (append `rendering` when present), and its `options`, with `recommendation` first and marked "(Recommended)". Then run `LENSCTL answer --run <run> --lens <lens> [--task-action <task_action>] --answer "<answer>" --next`. If its `answered.continue` is `send_message`, continue that agent with SendMessage: "Your question has an answer in your qa file. Continue." If it is `respawn`, start a fresh agent with the dispatch prompt. If it is `next`, handle the `actions` it returned. |
| `checkpoint` | A phase just finished (`after`) and nothing is running. The conversation grows with every turn and each turn re-reads all of it, so offer a reset: ask the user with AskUserQuestion, "Run `/clear`, then `/lens:resume`, to continue with a fresh context?", options "clear and resume (Recommended)" and "continue in this session". If they choose to clear, tell them to run `/clear` and then `/lens:resume`, and stop. Everything is saved. If they choose to continue, call `LENSCTL next --run <run> --all`. |
| `halt` | Stop. Tell the user, marked with 🛑, which lens halted and why, and that `/lens:resume` continues the run once the cause is fixed. |
| `done` | Run `LENSCTL report --run <run>` and show the user its `rendering` lines. Finished. |

When an agent finishes, its whole reply is one JSON status line. Run
`LENSCTL record --run <run> --lens <lens> [--task-action <task_action>] --status <status> --summary "<summary>" --next`,
passing the summary as the line gave it. When several agents finish together,
add `--next` to the last record only. The output is `{"recorded": ..., "actions": [...]}`:
handle `actions` exactly as above, with no separate `next` call.

If lensctl prints `{"error": ...}`, stop and report it with 🛑. Don't work
around it.

### Dispatch prompt

> Lens run directory: `<run>`. `LENSCTL` is `python3 <absolute path to
> lensctl.py>`. Key: `<task_action, else lens>`. Params: `<params as JSON, or
> {}>`. Workspace: `<workspace, or "none">`. Attempt `<attempt>`. Follow your
> agent contract.

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

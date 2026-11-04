---
name: make-human-ticket
description: Draft or rewrite a Jira ticket description in the user's human-first pattern -- a plain-words What and Why, a functional Requirements table (id, name, condition, outcome), then an "Agent Dump Section" with prose Background, tabular Scope and bulleted Non-Goals -- and create the ticket with team, story points, epic, labels and issue links through a bundled script. Use when the user invokes /make-human-ticket, asks to write, rewrite, restructure or tighten a ticket or story description, asks to create a ticket in the DP project, wants a ticket "in my format" or "in the human pattern", or hands over a ticket key or URL to rework, even if they never name the pattern. Drafts only; creates or edits a Jira issue solely when the user says to.
---

# make-human-ticket

Produce a ticket description whose top half a human skims in ten seconds
(what, why, testable requirements) and whose bottom half carries the
detail an implementing agent needs. The pattern, section rules and a
worked example are in [TEMPLATE.md](TEMPLATE.md). Read it before drafting;
the rules there are the standard, so do not work from memory.

Default output is a draft shown to the user. Nothing is written to Jira
unless the user explicitly asks (Step 5).

## Step 1 -- Identify the source

- **Ticket key or URL:** read it with the Atlassian MCP `getJiraIssue`
  (`responseContentFormat: markdown`) with summary, description, status,
  issuetype, labels, parent, issuelinks and comment. Read the comments:
  later ones often revise the scope, and the description may not reflect
  them. Note the status of linked issues; a canceled or finished link
  changes what a reference means.
- **Conversation or pasted text:** use it as the source.
- **Ambiguous:** pick the most probable reading, state the assumption in
  one line, and proceed. Do not ask.

Two Atlassian MCP servers can be connected, and the grant is per server.
When a call fails with "isn't explicitly granted", call
`getAccessibleAtlassianResources` on the other server and use the one
that lists the site with Jira scopes.

While reading, collect the **linked work items**: tickets the source says
block this one, are blocked by it, or relate to it. Reading an existing
ticket's `issuelinks` entry for a Blocks link, `inwardIssue: X` means this
ticket is blocked by X, and `outwardIssue: X` means this ticket blocks X.
Any other link type (clones, splits) is reported in Step 4, not linked.

## Step 2 -- Sort the source

Before writing, sort what the source says into: goal, reason, observable
behaviors (a condition and its outcome), current-state facts, decisions
and where they are recorded, constraints, preconditions, exclusions,
references. Use only what the source states. A gap stays a gap; it is
reported in Step 4, never filled with a guess. This keeps the ticket
trustworthy: a reader cannot tell an invented detail from a sourced one.

## Step 3 -- Draft from the template

Follow TEMPLATE.md section by section. The rules most often broken:

- What and Why are two sentences or fewer, in plain words. They are the
  part a human reads, so identifiers and permission strings belong lower
  down.
- Requirements are functional only. Performance, test coverage and reuse
  rules go in Scope as Constraint or Verification rows, because a
  requirement must be observable by running the system.
- Background is prose. Leave out status that goes stale (who is working
  on it, whether a PR is open) and link long rationale instead of copying
  it.
- Scope is a table. Every requirement id appears in it, and every
  behavior row cites its ids.
- Linked tickets stay out of the description. They are Jira links,
  attached in Step 5, so the relationship is queryable and cannot drift.

## Step 4 -- Present

Show the whole draft in one fenced `markdown` block so it copies cleanly.
Follow it with:

- **Metadata** as it will be sent: summary, team, story points, priority,
  labels, epic, where the Agent Dump Section goes (description or
  comment), and each link as "blocks DP-1", "blocked by DP-2" or
  "relates to DP-3". Mark anything still unknown (story points, epic).
- **Judgment calls and gaps**, a short list:
  - what the draft infers rather than takes from the source (Non-Goals
    especially)
  - what the source leaves unstated and how the draft words it
  - signs the source is stale or contradictory (a comment that revises
    the description, a canceled linked issue)
  - links not attached because the script cannot express their type
  - content dropped from the source and why

State facts only. Stop there.

## Step 5 -- Write to Jira (only when asked)

Skip this step unless the user explicitly says to create or update.

**Update an existing ticket:** `editJiraIssue` with the new description
and `contentFormat: markdown`. Leave summary, labels, status, links and
every other field alone unless the user names them. The script below only
creates. If the ticket keeps its Agent Dump Section in a comment, the edit
reaches the description only. No tool here edits an existing comment, so
say the comment is unchanged and offer to post the revised dump as a new
comment with `addCommentToJiraIssue`.

**Create a ticket:** `scripts/create_ticket.py` in this skill's directory
(resolve it from the base directory shown when the skill loaded) creates
the ticket and attaches the links in one run. Feed it only a spec file.

1. **Settle the metadata.** Ask for what is missing, in one message:
   - *Story points*: the user states them. Never guess.
   - *Epic*: use the source's parent if it has one or the user named one.
     Otherwise ask whether the ticket has an epic parent. Send `null` only
     after the user says there is none.
   - Defaults, applied unless the user says otherwise: team "UE - Data
     Pipelines", priority Medium, project DP, type Story.
   - *Labels*: choose from `earn` (EARN work), `ops` (operational or
     on-call work), `tech-debt` (cleanup, refactor). Use only those the
     source supports. The script rejects any other label.
   - *Agent dump placement*: the whole body goes in the description unless
     the user asks for the Agent Dump Section in a comment. Tools that read
     only the description, such as the automated reviewer, do not see a
     comment, so state that when the user chooses it.
2. **Write two files** to a scratch directory: the description as
   markdown, and the spec as JSON.

   ```json
   {
     "summary": "Short ticket title",
     "description_file": "/path/to/body.md",
     "points": 3,
     "epic": "DP-3013",
     "labels": ["earn"],
     "links": [
       {"type": "blocked-by", "key": "DP-2321"},
       {"type": "relates", "key": "DP-2930"}
     ]
   }
   ```

   `links[].type` is `blocks` (this ticket blocks the key), `blocked-by`,
   or `relates`. Add every linked work item known from Step 1 and the
   conversation. Optional keys `priority`, `team`, `project` and `type`
   override the defaults. Add `"agent_dump": "comment"` to post everything
   from `# Agent Dump Section` down as a comment on the new ticket, and
   keep the rest of the body in the description. Keep the body in one
   file; the script does the split.
3. **Confirm, then run.** Show the user the final metadata and links.
   After they confirm, run `python3 <skill dir>/scripts/create_ticket.py
   <spec.json>`. `--dry-run` prints the requests without credentials or
   network, for checking a spec.
4. **Report the result.** Give the new key and URL from the output. Exit
   code 3 means the ticket was created but the comment or a link failed;
   name what failed and do not rerun the spec, which would create a second
   ticket. For a failed comment, retry it alone with `python3 <skill
   dir>/scripts/create_ticket.py <body.md> --comment-only <KEY>`, which
   posts the Agent Dump half of the same body file.
   Exit code 1 prints every spec or credential problem; fix them and
   rerun. Exit code 2 means Jira refused the ticket; show its message.

The script reads credentials from `JIRA_EMAIL` and `JIRA_API_TOKEN`, or
from the jira-cli config and keychain item. When neither is present it
says so and stops. Tell the user what to set; do not fall back to creating
the ticket through the MCP, which would skip the team, points and links.

The script's tests run offline: `python3 -m unittest discover -s
<skill dir>/scripts`.

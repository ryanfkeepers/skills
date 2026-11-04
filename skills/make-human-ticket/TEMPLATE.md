# Human ticket template

The ticket body has two halves split by a horizontal rule. Above the rule
is what a human skims in ten seconds: the goal, the reason, and the
testable behaviors. Below it is the detail an implementing agent needs.
Fill every placeholder. Delete nothing structural.

The create script can post the lower half as a comment on the new ticket
(`agent_dump: "comment"`). It finds the split by the exact line
`# Agent Dump Section`, so keep that heading as written.

## Template

````markdown
# What

<The goal in two sentences or fewer.>

# Why

<Why the change is valuable or necessary, or what happens if it is not
made, in two sentences or fewer.>

# Requirements

| id | name | condition | outcome |
|----|------|-----------|---------|
| R1 | <1-3 words> | When <subject> <is or does> <state> | Then <result> must <behavior> |
| R2 | <1-3 words> | When <subject> <is or does> <state> | Then <result> must <behavior> |

<hr>

# Agent Dump Section

## Background

<Prose paragraphs. No bullets.>

## Scope

| Area | In scope | Detail |
|------|----------|--------|
| <Area> | <one item> | <specifics; cite the Rn it satisfies> |

## Non-Goals

- <exclusion>
````

## Section rules

### What and Why

- Two sentences or fewer each, written so a newcomer follows them on the
  first read: short everyday words, no identifiers, permission strings,
  endpoint paths or ticket keys. An everyday analogy is fine.
- What states the change. Why states the reason or the cost of leaving
  things alone. Neither restates the other.
- One parenthetical is allowed when dropping an exception would make the
  sentence false. Simplify the wording, never the facts.

### Requirements

- Functional only: behavior someone can observe at the system boundary by
  running the system (a response status, response content, a visible
  state). Performance bounds, test coverage, code structure and reuse
  rules are not requirements; they go in Scope as Constraint or
  Verification rows.
- `id` runs R1..RN with no gaps. `name` is a unique 1-3 word label.
- `condition` starts with "When" and names the triggering situation.
  `outcome` starts with "Then" and contains "must". Name the observable
  signal, not the mechanism ("the response must be 403", not "the
  function returns an error").
- One condition and one outcome per row. A row that needs "and then also"
  is two rows. Each row is testable alone.
- Process steps ("confirm the current behavior first") are not
  requirements; they go in Scope as Precondition rows.

### Background

- Prose paragraphs, not a list. Present tense for current state.
- Give an implementing agent enough to start: what the code does today,
  the names, paths and endpoints involved, the incident or request that
  triggered the work, the decisions already made and where they are
  recorded (one sentence plus a link, not the full rationale), where to
  start (prior work to build on, what to check first), and reference
  URLs.
- Leave out transient status such as who is working on it, whether a PR
  is open, or whether tests are running. It is stale on arrival.

### Scope

- One table: `Area | In scope | Detail`. One item per row.
- Typical areas: Endpoints, Authorization, Denial semantics, Constraint,
  Unchanged, Precondition, Verification. Use whatever areas fit the work.
- Every behavior row cites the requirement ids it satisfies, and every
  requirement id appears in at least one Scope row.
- Constraints, dependencies, behavior that must stay the same,
  preconditions and test expectations all live here.

### Non-Goals

- Bullets. Only exclusions the source states or directly implies.
- Anything inferred rather than stated is reported to the user in the
  draft notes, not asserted in the ticket.

### Whole ticket

- Use only facts from the source. A fact the source leaves out stays out;
  report it as a gap in the draft notes.
- Do not list blocking, blocked-by or related tickets. Those are Jira
  links, added when the ticket is created. A ticket key appears in prose
  only when the sentence needs it, such as where a decision is recorded.
- No person names, status snapshots or footers.
- Keep each table row on one line.

## Worked example (synthetic)

````markdown
# What

Let people download the audit log as a spreadsheet file. The file
contains whatever rows match the filters on screen.

# Why

People copy rows out by hand to share them, and long logs get cut off.
A spreadsheet file keeps every row and opens in tools they already use.

# Requirements

| id | name | condition | outcome |
|----|------|-----------|---------|
| R1 | Filtered export | When a caller requests an export with filters applied | Then the file must contain exactly the rows the filters match |
| R2 | Row order | When rows are exported | Then they must appear newest first, the same order as the screen |
| R3 | Empty result | When no rows match the filters | Then the file must contain only the header row |
| R4 | No access | When the caller may not view the audit log | Then the response must be 403 and no file is produced |

<hr>

# Agent Dump Section

## Background

The audit log screen lists events through a paged endpoint and offers no
export, so users copy rows by hand. The endpoint already applies the
caller's filters and view permission, and the export must reuse that
logic so the file never contains a row the screen would hide. The
decision to export CSV rather than XLSX is recorded in the team design
notes.

## Scope

| Area | In scope | Detail |
|------|----------|--------|
| Endpoints | Audit log export | New download endpoint beside the paged list (R1-R3) |
| Authorization | View permission | Same permission as the list endpoint (R4) |
| Constraint | Large logs | Export streams rows and never holds the full result in memory |
| Unchanged | Paged list endpoint | Request and response unchanged |
| Verification | Handler tests | Filtered, empty, ordered and unauthorized callers covered |

## Non-Goals

- Scheduled or emailed exports.
- Exporting any log other than the audit log.
````

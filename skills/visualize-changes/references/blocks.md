# Spec reference

The spec is one JSON file. `build.py` validates it against the revision range and
renders the page. Errors stop the build with a message naming the field;
warnings print but still build.

The page shows no code bodies. Any string in the spec with a line break is
an error, except Mermaid source in a diagram and an artifact's `sig`
(declarations may span lines, up to 20). `<pre>`/`<code>` in an html block
must be one line.

## Contents

- [Top level](#top-level)
- [Tabs](#tabs): areas, the "Where it lands" tree
- [Blocks](#blocks): html (flows), boundaries (exposed surface), diagram (sequence only), walkthrough
- [Flow kit](#flow-kit) for html blocks
- [Sequence diagram conventions](#sequence-diagram-conventions)

## Top level

```json
{
  "title": "Histogram Bucket Boundaries",
  "eyebrow": "optional; defaults to '<repo> · <from> → <to>'",
  "owners": { "services/earn": "datapipelines", "pkg/api": "api-guild" },
  "landed": { "services/earn/internal/authz": "client and helpers for org-permission auth checks" },
  "overview": {
    "summary": "At most four sentences: the problem, the approach, and the consequence the room should carry into the tabs.",
    "blocks": []
  },
  "tabs": [ ... ]
}
```

- `title`: two to four words naming the change. It is also the browser-tab
  and Artifact gallery name. There is no subtitle; the header shows the
  title, the range, the color key, and the viewer's theme and color-blind
  palette pickers.
- `owners`: directory → owning team or module, from CODEOWNERS or module
  boundaries. Shown beside that directory in every tab's tree. Omit owners
  you don't know; never guess.
- `landed`: package directory → one line on what landed there in this
  change (under 120 chars), shown under that package in every tab's tree.
  A tab can override entries with its own `landed`. The build warns for any
  tree package without one (tests-only and docs-only packages excepted).
- New / changed / removed colors are keyed once, in the page header, and
  mean the same thing in every diagram, map, tree, and table.
- `overview.summary`: required; the build fails above 4 sentences.
- The overview renders the summary and the agenda (one row per tab).
- `overview.blocks`: optional, usually empty. One system-level `boundaries`
  or `diagram` block belongs here only when the change spans several
  components and a single picture orients the room before the agenda.

## Tabs

```json
{
  "key": "retry-policy",
  "title": "Retry policy",
  "lede": "One sentence: what this topic changes and why.",
  "badge": "breaking",
  "areas": ["internal/retry", "(root)"],
  "blocks": [ ... ],
  "decisions": [ { "statement": "A failed render retries up to 5 times", "state": "mod", "was": "3 times" } ],
  "failures": [ { "cause": "the report is invalid", "result": "rejected, 400 to the caller", "state": "add" },
                { "cause": "the template cannot be read", "result": "the name is left out and the run continues", "continues": true, "state": "add" } ],
  "etc": [ "Default timeout is 10s" ]
}
```

- `key`: lowercase slug; it is the deep link (`page#retry-policy`).
- `lede`: one sentence, warned above 180 chars.
- `badge`: optional short flag on the tab and agenda row. Use it only for
  something the room must not miss (`breaking`, `migration`, `security`).
- `areas`: package paths, prefixes, or globs this tab accounts for beyond
  the files its boundaries cite. Use `(root)` for repo-root files.

Render order inside a tab: lede → Key decisions → blocks → Failure models →
Where it lands → Etc. A section with no items is left out. Key decisions come
first so the reader meets the behavior before the diagrams that explain it.

- `decisions`: business-level statements about how the application behaves,
  at major interfaces and across layer boundaries ("returns all reports
  ordered by name"). Not code-level facts ("returns struct foo") and not every
  function juncture. Each item is `{statement, state?, was?}`; `was` is a
  short phrase for the old behavior.
- `failures`: how the system behaves when things go wrong. Each item is
  `{cause, result, state?, was?, continues?}`, shown as `IF:` cause and
  `THEN:` result, so `cause` completes "IF:" and `result` is the end state
  (returned to the caller as 404, logged and dropped) completing "THEN:".
  Cover every failure path; batch related ones ("the report must be valid"
  for a `Validate()` with many checks). `continues: true` marks a failure that
  is handled with processing carrying on; THEN shows blue instead of red. For
  a `mod` failure `was` is `{cause?, result?, continues?}`, the old IF and
  THEN (an omitted field shows the current text). A `mod` item without a
  `was`, or with a `was` that repeats the current text, is a build error: read
  the old behavior from the base revision, or use `add` if there was none.
- `etc`: plain strings for anything that is neither.
- `state` is `add`, `mod`, `del`, or `legacy` and shows as a new / changed /
  removed / legacy handling badge; leave it off for a statement that is not
  about the change. `legacy` is for how existing data or clients are still
  handled (a backfill, a tolerated old shape). `was` goes only with `mod`,
  and shows in a "was" panel. Warned above 12 items per list.

Every tab has an automatic **Where it lands** tree. It shows the
directory structure from the repo root down to each package the tab
touches (from boundary `paths`, artifact `file`s, and `areas`), with each
package marked new / changed / removed, and owners from the top-level
`owners` map. Directories only, never files. Test and mock packages never
appear.

Each tree package shows its `landed` line beneath it, and a directory with
children folds when its name is clicked.

## Blocks

Every block accepts optional `title` (h3 above it) and `caption` (one muted
line below it).

### diagram (sequence only)

```json
{ "type": "diagram",
  "before": "sequenceDiagram\n  participant C as Caller\n  participant S as Store\n  C->>S: Put(k)",
  "after":  "sequenceDiagram\n  participant C as Caller\n  participant S as Store\n  C->>S: PutBatch(ks)\n  Note over C,S: new",
  "layout": "side | stacked" }
```

Mermaid `sequenceDiagram` only, for interactions over time between
participants (swimlanes). This is the default way to show who calls whom
across the interfaces a request touches. Any other Mermaid type is rejected: draw flows,
branches, structure, and layers as an `html` block with the flow kit.
`after` is required; add `before` when the interaction changed. Pairs render
side by side; `layout: "stacked"` puts before above after. Viewers can click
(or press Enter on) a diagram to open it full window, where a Width picker
(10% to 100% of the window, remembered) sets how wide it draws; give the block
a `title` so that view is labeled ("Group sync · After").

### walkthrough

```json
{ "type": "walkthrough", "title": "Generate",
  "lanes": ["Client", "reports.Handler", "ReportService", "RunService"],
  "segments": [
    { "steps": [
      { "from": "Client", "to": "reports.Handler", "label": "POST reports:generate",
        "what": "The caller sends a create-style body with no schedule.", "state": "add" },
      { "from": "reports.Handler", "to": "reports.Handler", "label": "guard the request",
        "what": "Refuse a schedule, a mismatched organization, or missing access.", "detail": "400, 400 and 403." },
      { "from": "reports.Handler", "to": "RunService", "label": "CreateTitled(title)",
        "what": "Queue the report's MANUAL run." } ] },
    { "split": [
      { "key": "ok", "label": "queued", "kind": "ok", "steps": [
        { "from": "RunService", "to": "reports.Handler", "label": "run", "ret": true, "what": "The run was queued." },
        { "from": "reports.Handler", "to": "Client", "label": "202 run + Location", "ret": true,
          "what": "Answer 202 with the run and a Location header." } ] },
      { "key": "failure", "label": "not queued", "kind": "failure", "ends": true, "steps": [
        { "from": "reports.Handler", "to": "ReportService", "label": "Delete", "what": "Delete the report just created." },
        { "from": "reports.Handler", "to": "Client", "label": "error", "ret": true, "what": "The caller gets the run's error." } ] } ] }
  ] }
```

An interaction the room steps through: lanes (participants) across the top,
one message revealed at a time, the current one highlighted, and a panel above
the lanes (below the track) saying what happens. Use it instead of a `diagram` when the
interaction has more than 8 messages or any ok/failure branch; the build warns
on a `diagram` that is long or uses `alt`/`opt`/`else`. It shows the after
flow only: mark steps `add`, `mod`, or `del` (a removed step is drawn dashed)
rather than drawing a before and after.

- `lanes`: two or more unique participant names, left to right. A step's
  `from` and `to` name lanes; `from == to` is a message to itself, and
  `"ret": true` draws a dashed return.
- `segments`: in order, each either `{ "steps": [...] }` (shared by every
  path) or `{ "split": [...] }`. A split's branches are alternatives, each
  `{ key, label, kind: "ok" | "failure", ends?, steps }`. A branch with
  `"ends": true` stops the flow. A branch without it rejoins: the next
  segment's steps follow whichever branch is selected, so a split can sit in
  the middle of the flow. A branch in the last segment simply finishes. A
  flow can have several splits; each keeps its own selection.
- Step fields: `from`, `to`, `label` (a few words, shown on the arrow), `what`
  (one sentence, shown in the panel; warned over 160 chars), `detail`
  (optional second line), `state`, `ret`, `tasks`. No code.
- `tasks`: optional `[{ label, what, detail? }]` on a step. Use it when several
  consecutive calls between the same two lanes are parts of one change: draw
  them as one arrow (`"label": "Create"`) and list each task in the panel, in
  order, instead of repeating the arrow. Each task is one line, like a step's
  `what`; the standalone page's plain-text list shows them too.
- The page draws a track above the lanes: one rounded marker per step. Each
  split forks into a labeled row per branch. A rejoining branch runs a line
  into the bar after the split and ends with "rejoins at N"; an ending branch
  has no line and ends with ■ ("ends") or ✕ ("ends in error"). Every marker
  is clickable, including markers in the branch not currently drawn; clicking
  one switches that split's branch and jumps to the step. If the selected
  branch ends, the steps after the split are dimmed with a tooltip saying they
  are reached only through the other path.
- The lanes draw the shared steps plus each split's selected branch, in a
  labeled dotted box (ok in the accent color, failure in the removed color
  with ✕), so the two outcomes never share a diagram. Before a split, the
  panel offers a button per branch.
- Errors: fewer than two lanes, a step naming a lane that is not listed, an
  empty `label` or `what`, a split with fewer than two branches or a duplicate
  or non-slug `key`, a `kind` that is not `ok` or `failure`, a `tasks` entry
  without a `label` and `what`. Warnings: more than 16 steps on the longest
  path, a split with no `ok` branch, a split where every branch ends but a
  segment follows, a walkthrough with no `title` (it cannot be linked), two
  walkthroughs in one tab whose titles give the same link name.
- A Fullscreen button at the top right of the panel opens it full window, with
  the same Width picker as a diagram's full-window view; Escape or Close puts
  it back with its current step and branch selection intact. In the full-window
  view, left and right step through the flow, and up and down switch to the
  neighbouring branch of the split the current step is on.
- A titled walkthrough is linkable. Its heading shows a `#` link that copies
  `page#<tab key>/<block>`, where `<block>` is the title lowercased with
  runs of other characters turned into `-` (a repeated title gets `-2`, `-3`
  and a build warning). On a hosted Artifact page the frame's own address is
  not the page address, so the link copies only `#<tab key>/<block>`, to add
  to the page address, and shows the text when the clipboard is unavailable.
  Adding `--fullscreen` (`page#<tab key>/<block>--fullscreen`) opens the
  walkthrough full window, and the address follows the view: opening adds that
  suffix, closing removes it, and Back and Forward reopen and close it.
  `?fullscreen=true` on the first load does the same where a query string
  survives; a hosted frame passes only the hash, so the suffix is the link to
  share. Give every walkthrough a distinct `title`.
- The standalone page lists every step as plain text until its script runs, so
  a viewer without scripts still reads the flow.

### boundaries

```json
{ "type": "boundaries",
  "boundaries": [
    { "id": "authz", "paths": ["services/earn/internal/authz"],
      "exposes": [
        { "name": "Authorize", "kind": "method", "file": "services/earn/internal/authz/client.go",
          "sig": { "before": "Authorize(ctx, perms []Permission) (Result, error)",
                   "after":  "Authorize(ctx, perms []Permission, orgIDs []string) (Result, error)" } },
        { "name": "IsOrganizationLevel", "kind": "field", "file": "services/earn/internal/authz/permission.go" }
      ] },
    { "id": "um",
      "exposes": [
        { "name": "POST /authz/organizations", "kind": "endpoint", "file": "services/user-management/routes.go", "match": "/authz/organizations" }
      ] }
  ] }
```

The exposed surface: what each boundary offers the outside, one card per
directory (the card title is the directory, matching the tree). It draws no
map; show how boundaries call each other in a `diagram` block. Only new,
changed, and removed artifacts get a row. Each row has three columns: the
state, what kind of thing it is and what it hangs off ("method on `client`",
"struct `Permission`", "func"), and the declaration, syntax-highlighted for
the file's language. A `{before, after}` declaration highlights the changed
tokens; multi-line declarations (an interface) stack before above after.

**Go structs show whole.** An artifact that is a struct, or a field of one,
is replaced by one row for the struct, read from the code at both revisions
(its `sig` is not used). All fields count, exported or not.
- A new struct, a removed struct, and a changed struct with 5 or fewer
  properties show every field; on a changed struct the changed fields are
  highlighted in place (an old line above its new line).
- An existing struct with more than 5 properties that is being modified shows
  `type X struct {`, a single `// N properties hidden` line (N is the count
  of unchanged fields), only the added, changed and removed fields, and `}`.
- If the struct declaration can't be found in either version, the row falls
  back to each artifact's own `sig`.

`links` and `map` are rejected. Boundary `id`, `paths`, and `exposes` are
what the build reads.

What goes in `exposes`: only what the boundary offers to the outside, such as
exported types, interfaces, functions, methods, fields, endpoints, events,
topics, config keys. List the ones the change adds, removes, or reshapes.
Helpers, unexported consts, and internal functions never appear; if internal
behavior drives the design, draw it in an `html` flow.

Artifact fields:
| field | meaning |
|---|---|
| `name` | the identifier as declared (`Authorize`, `IsOrganizationLevel`), or the route/topic for endpoints and events (`POST /authz/orgs`). Don't invent `Type.Method` prefixes |
| `kind` | `interface`, `struct`, `func`, `method`, `field`, `type`, `const`, `var`, `endpoint`, `event`, `config` |
| `on` | what it hangs off, when the build can't detect it: `"struct client"`, `"interface Store"`. For Go, methods, struct fields, and interface methods are detected from the declaration |
| `file` | where it is declared; used to check the name and to place the artifact in the tree |
| `match` | text to look for instead of the name's last segment (endpoints, events, config keys) |
| `state` | derived from the code (absent before → `add`, absent after → `del`, else `mod`); `same` leaves the artifact off the surface |
| `sig` | the declaration as in the code: a func or method on one line (`func (c *client) Authorize(ctx context.Context, perms []Permission) error`), or an interface over several lines listing only exported members. A string, or `{before, after}` when it changed. Don't wrap or elide parameters yourself: the build splits any one-line declaration wider than 80 characters all-multiline (one parameter per line, trailing comma, `)` on its own line). Max 20 lines; single lines max 400 chars. Not used for Go structs and their fields |
| `before_file` | when the artifact moved files |

The build fails if a name (or `match`) is in neither version of its file,
and warns on unexported Go names. Keep a boundary to at most 8 artifacts.

### html

```json
{ "type": "html", "html": "<div class=\"vc-ba wide-after\">...</div>" }
```

The main way to draw: process flows, before/after call paths, branches,
fallbacks, ladders, layer maps, payload shapes, state matrices. You decide
the picture that explains this change best; compose it from the flow kit
below so it matches the page. `<script>`, `<style>`, embeds, event
handlers, and `javascript:` URLs are rejected. Literal colors
(`#hex`, `rgb()`, color names in `style`/`fill`/`stroke` attributes) are
rejected: state colors come from the kit's classes, so the theme and
color-blind pickers apply. Multi-line `<pre>`/`<code>` is rejected.

## Flow kit

Before/after panels:
- `vc-ba` is a two-column grid; add `wide-after` or `wide-before` when one
  side has more to show. It stacks at narrow widths.
- `vc-ba-panel` is one side; start it with
  `<div class="vc-ba-head"><span class="vc-ba-tag before">Before</span><strong>Title</strong></div>`
  (`after` for the other side).

Steps and arrows:
- `vc-flow` stacks its children vertically and draws a ↓ between each pair.
- `vc-step` is a box: first line is the step, `<span class="vc-detail">` is
  the second line. State modifiers `add`, `mod`, `del` color the box and its
  detail. `term` makes it a pill for entry and exit points (Request,
  Response).
- `vc-edge` between two children replaces the plain arrow with a labeled one:
  `<div class="vc-edge"><strong>short page:</strong> widen to the next step</div>`
  (add `add`/`mod`/`del` to color the bold part).

Branches and ladders:
- `vc-decision` is a diamond holding a condition as a short question ("Flag
  on and payload valid?"). Write only the question as its text; the build
  draws the diamond. It takes `add`/`mod`/`del`. Every condition in a flow
  gets one, placed in a `vc-flow` directly before its branches. Never state a
  condition in a step's text or a branch title.
  A fork's columns are sized by how many leaf branches each holds, so a branch
  with a fork inside it gets proportionally more room. Forks nested three
  deep still read badly and are warned: write a decision ladder instead, a
  sequence of decisions where each fork's non-ending branch continues to the
  next decision.
- A branch whose last step is a `vc-step term` pill ends the flow: the page
  draws ■ in the pill (add `err` for ✕, an error end) and no connector below.
  Any other branch continues and joins the bar under the fork, with an arrow
  into the next step. Nothing is needed to mark a continue. If every branch
  ends, no arrow follows the fork and a step after it is warned as
  unreachable.
- `vc-aside` is a condition on a step and what follows it, inside the
  `vc-step` after its `vc-detail`:
  `<div class="vc-aside"><span class="vc-aside-if">the template is unreadable</span><span class="vc-aside-then cont">the name is left out</span></div>`.
  The page adds the ⚠, `IF` and `THEN`; `cont` makes THEN blue (processing
  continues), without it THEN is red (it stops). Two show inline; more fold
  under "N more conditions", and over four is warned: move the extras to
  Failure models. `vc-detail` is for one changed fact, never a condition.
- `vc-branches` lays out paths side by side; each `vc-branch` is a column
  with `<span class="vc-branch-title">` and its own `vc-flow`. Add `fork`
  after a `vc-decision` so connectors run from the diamond to each branch and
  the branch title is the answer ("yes", "no", or the case). `alt` dashes a
  branch (fallback path); `add`/`mod`/`del` color it. A guard ("skip if not
  exported") is a diamond whose exit branch is `alt` and ends in a
  `<div class="vc-step term">Skip</div>` pill.
- `vc-rung` is a row of `<span class="vc-chip">label</span>` plus a step,
  for ladders, tiers, retries, or windows. Chips take `add`/`mod`/`del`.

Other pieces: `vc-box` (plain box, with `add`/`mod`/`del`/`accent`),
`vc-row`, `vc-stack`, `vc-grid-2`, `vc-grid-3`, `<table class="vc-table">`
(cells take `add`/`mod`/`del`; for matrices only, never before → after),
`vc-scroll`, `vc-pill add|mod|del`,
`vc-arrow`, `vc-mono`, `vc-muted`, `vc-strike`. Tokens for inline styles:
`--bg --surface --sunken --ink --muted --line --accent --accent-soft --add
--add-bg --del --del-bg --mod --mod-bg --font-mono --radius`.

Guidance:
- Keep unchanged steps plain and mark only what the change touched, so the
  eye lands on the difference.
- Keep before and after structurally parallel: the same step names in the
  same order, so the room can compare them side by side.
- A step says what happens ("Resolve sort"), and its detail says the one
  fact that matters ("unset sort now defaults to timestamp desc").
- Prefer one rich picture per topic over several thin ones.

Example: a call flow that gained a flag lookup, a decision, and a widening ladder.

```html
<div class="vc-ba wide-after">
  <div class="vc-ba-panel">
    <div class="vc-ba-head"><span class="vc-ba-tag before">Before</span><strong>Protection, restore</strong></div>
    <div class="vc-flow">
      <div class="vc-step term">Request</div>
      <div class="vc-step">Resolve sort<span class="vc-detail">default: timestamp asc</span></div>
      <div class="vc-step">Build KQL<span class="vc-detail">full range [start, end)</span></div>
      <div class="vc-step">Execute once</div>
      <div class="vc-step term">Response</div>
    </div>
  </div>
  <div class="vc-ba-panel">
    <div class="vc-ba-head"><span class="vc-ba-tag after">After</span><strong>Protection, restore, action</strong></div>
    <div class="vc-flow">
      <div class="vc-step term">Request</div>
      <div class="vc-step mod">Resolve sort<span class="vc-detail">unset sort now defaults to timestamp desc for all orgs</span></div>
      <div class="vc-step add">Look up the endpoint's ladder flag<span class="vc-detail">payload {"steps": ["24h", "120h"]}</span></div>
      <div class="vc-decision add">Flag on, payload valid, sort timestamp desc?</div>
      <div class="vc-branches fork">
        <div class="vc-branch alt">
          <span class="vc-branch-title">No</span>
          <div class="vc-flow"><div class="vc-step">Build KQL<span class="vc-detail">full range</span></div><div class="vc-step">Execute once</div></div>
        </div>
        <div class="vc-branch add">
          <span class="vc-branch-title">Yes</span>
          <p>Every window ends at the request end.</p>
          <div class="vc-flow">
            <div class="vc-rung"><span class="vc-chip">last 24h</span><div class="vc-step mod">Build and execute<span class="vc-detail">full page returns here</span></div></div>
            <div class="vc-edge"><strong>short page:</strong> widen to the next step</div>
            <div class="vc-rung"><span class="vc-chip">last 120h</span><div class="vc-step mod">Same, wider start<span class="vc-detail">full page returns here</span></div></div>
            <div class="vc-edge"><strong>short page:</strong> widen to the full range</div>
            <div class="vc-rung"><span class="vc-chip">full range</span><div class="vc-step mod">Last window<span class="vc-detail">returns whatever it finds</span></div></div>
          </div>
        </div>
      </div>
      <div class="vc-step term">Response</div>
    </div>
  </div>
</div>
```

## Sequence diagram conventions

- Keep participants identical across before/after so the lanes line up.
- Mark a new, changed, or removed span by wrapping its messages in
  `rect new` ... `end` (or `rect changed`, `rect removed`). The page draws a
  dotted, colored box with a label around them. Never write colors into
  Mermaid source (`rect rgb(...)`), and never mark a span with a Note; the
  build rejects both.
- Label messages with what is asked ("FilterAuthorized(orgs)"), not full
  call expressions.

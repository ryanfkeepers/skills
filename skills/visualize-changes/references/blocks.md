# Spec reference

The spec is one JSON file. `build.py` validates it against the jj range and
renders the page. Errors stop the build with a message naming the field;
warnings print but still build.

The page shows no code bodies. Any string in the spec with a line break is
an error, except Mermaid source in a diagram and an artifact's `sig`
(declarations may span lines, up to 20). `<pre>`/`<code>` in an html block
must be one line.

## Contents

- [Top level](#top-level)
- [Tabs](#tabs): areas, the "Where it lands" tree
- [Blocks](#blocks): html (flows), boundaries, delta, diagram (sequence only)
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
  "blocks": [ ... ]
}
```

- `key`: lowercase slug; it is the deep link (`page#retry-policy`).
- `lede`: one sentence, warned above 180 chars.
- `badge`: optional short flag on the tab and agenda row. Use it only for
  something the room must not miss (`breaking`, `migration`, `security`).
- `areas`: package paths, prefixes, or globs this tab accounts for beyond
  the files its boundaries cite. Use `(root)` for repo-root files.

Every tab ends with an automatic **Where it lands** tree. It shows the
directory structure from the repo root down to each package the tab
touches (from boundary `paths`, artifact `file`s, and `areas`), with each
package marked new / changed / removed, and owners from the top-level
`owners` map. Directories only, never files. Test and mock packages never
appear.

Render order inside a tab: lede → blocks (in order) → Where it lands. Each tree package shows its `landed` line beneath it.

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
participants (swimlanes). Any other Mermaid type is rejected: draw flows,
branches, structure, and layers as an `html` block with the flow kit.
`after` is required; add `before` when the interaction changed. Pairs render
side by side; `layout: "stacked"` puts before above after. Viewers can click
(or press Enter on) a diagram to open it full window; give the block a `title`
so that view is labeled ("Group sync · After").

### boundaries

```json
{ "type": "boundaries",
  "boundaries": [
    { "id": "api", "label": "Audit API", "kind": "service" },
    { "id": "authz", "label": "earn/authz", "kind": "package", "owner": "datapipelines",
      "paths": ["services/earn/internal/authz"],
      "exposes": [
        { "name": "Authorize", "kind": "method", "file": "services/earn/internal/authz/client.go",
          "sig": { "before": "Authorize(ctx, perms []Permission) (Result, error)",
                   "after":  "Authorize(ctx, perms []Permission, orgIDs []string) (Result, error)" } },
        { "name": "IsOrganizationLevel", "kind": "field", "file": "services/earn/internal/authz/permission.go", "sig": "bool" },
        { "name": "Check", "kind": "method", "file": "services/earn/internal/authz/client.go", "state": "same" }
      ] },
    { "id": "um", "label": "User Management", "kind": "service", "owner": "identity",
      "exposes": [
        { "name": "POST /authz/organizations", "kind": "endpoint", "file": "services/user-management/routes.go", "match": "/authz/organizations" }
      ] }
  ],
  "links": [
    { "from": "api", "to": "authz.Authorize", "label": "per request" },
    { "from": "authz", "to": "um.POST /authz/organizations", "label": "HTTP, parallel", "state": "add" }
  ] }
```

The boundary map: each boundary's exposed surface and who uses it, so the
room can trace a request across the interfaces it touches. The build renders
it as HTML:
- one card per boundary, left to right in the order listed (so list them
  in the direction a request flows), with arrows between cards;
- a boundary with `exposes` lists its artifacts inside, marked new / changed
  / removed, with what each hangs off ("method on client");
- a boundary with no `exposes` (a caller, an external system) is a small
  dashed card;
- each link shows on its target, as "← source · label" under the artifact
  (or the boundary) it reaches; `state` colors it, `del` strikes it through;
- `"map": false` skips the generated map when an `html` flow above already
  shows how the boundaries connect; the exposed surface still renders.
- under the map, **Exposed surface** shows one card per directory (the
  card title is the directory, matching the tree). Only new, changed, and
  removed artifacts get a row; unchanged ones stay on the map for context
  and never appear here. Each row has three columns: the state, what kind of
  thing it is and what it hangs off ("method on `client`", "field of struct
  `Permission`", "func"), and the declaration, syntax-highlighted for the
  file's language. A `{before, after}` declaration highlights the changed
  tokens; multi-line declarations (an interface, a struct) stack before
  above after.

Boundary `kind` is a short label: `package`, `service`, `consumer`,
`external`, `queue`, `store`. An artifact may carry an `id` when two in one
boundary share a name (four `With` methods); links then use
`boundary.id`.

What goes in `exposes`: only what the boundary offers to the outside, such as
exported types, interfaces, functions, methods, fields, endpoints, events,
topics, config keys. List the ones the change adds, removes, or reshapes,
plus unchanged ones (`"state": "same"`) only when a link needs them as
context. Helpers, unexported consts, and internal functions never appear;
if internal behavior drives the design, draw it in an `html` flow.

Artifact fields:
| field | meaning |
|---|---|
| `name` | the identifier as declared (`Authorize`, `IsOrganizationLevel`), or the route/topic for endpoints and events (`POST /authz/orgs`). Don't invent `Type.Method` prefixes |
| `kind` | `interface`, `struct`, `func`, `method`, `field`, `type`, `const`, `var`, `endpoint`, `event`, `config` |
| `on` | what it hangs off, when the build can't detect it: `"struct client"`, `"interface Store"`. For Go, methods, struct fields, and interface methods are detected from the declaration |
| `file` | where it is declared; used to check the name and to place the boundary in the tree |
| `match` | text to look for instead of the name's last segment (endpoints, events, config keys) |
| `state` | derived from the code (absent before → `add`, absent after → `del`, else `mod`); set `same` for context |
| `sig` | the declaration as in the code: a func or method on one line (`func (c *client) Authorize(ctx context.Context, perms []Permission) error`), or an interface or struct over several lines listing only exported members. A string, or `{before, after}` when it changed. Don't wrap or elide parameters yourself: the build splits any one-line declaration wider than 80 characters all-multiline (one parameter per line, trailing comma, `)` on its own line). Max 20 lines; single lines max 400 chars |
| `before_file` | when the artifact moved files |

The build fails if a name (or `match`) is in neither version of its file,
and warns on unexported Go names. Keep a boundary to at most 8 artifacts.
Split a crowded map into two blocks by direction of flow.

### delta

```json
{ "type": "delta",
  "rows": [
    { "name": "Butler returns no email",
      "before": "502 Bad Gateway; Sev0 alert fires",
      "after": "422 INCOMPLETE_IDENTITY; no alert" },
    { "name": "Retry limit",
      "before": "3 attempts, then fail",
      "after": "5 attempts with jittered backoff" }
  ] }
```

Before → after for behavior and values: status codes, config, flags,
defaults, limits, schema, permissions. Each row is a label naming the
situation or setting in words ("Butler returns no email", "Retry limit"),
then `before` → `after` as short phrases that say what happens (5–12 words),
not bare tokens. `null` renders as "none"; use it when the thing didn't
exist on that side (`"n/a"` and `"-"` render the same way).

Only rows that changed. The build rejects a row whose before and after are
the same, and rows with an explanation field; what stayed the same is not
on the page. Warned above 10 rows.

Delta is the only way to show a from → to comparison. The build rejects an
html table with before and after columns (or was/now, old/new, from/to), or
with "x → y" cells, and html that uses the delta classes. A table of kinds
whose rules changed becomes one delta row per changed kind.

### html

```json
{ "type": "html", "html": "<div class=\"vc-ba wide-after\">...</div>" }
```

The main way to draw: process flows, before/after call paths, branches,
fallbacks, ladders, layer maps, payload shapes, state matrices. You decide
the picture that explains this change best; compose it from the flow kit
below so it matches the page. `<script>` is stripped. Literal colors
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
- `vc-branches` lays out paths side by side; each `vc-branch` is a column
  with `<span class="vc-branch-title">`, an optional `<p>` or `<ul>` of
  conditions, and its own `vc-flow`. `alt` dashes it (fallback path);
  `add`/`mod`/`del` color it.
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

Example: a call flow that gained a flag lookup and a widening ladder.

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
      <div class="vc-branches">
        <div class="vc-branch alt">
          <span class="vc-branch-title">Single full window</span>
          <ul><li>flag off</li><li>lookup error or bad payload</li><li>sort is not timestamp desc</li></ul>
          <div class="vc-flow"><div class="vc-step">Build KQL<span class="vc-detail">full range</span></div><div class="vc-step">Execute once</div></div>
        </div>
        <div class="vc-branch add">
          <span class="vc-branch-title">Ladder</span>
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
- Mark new, changed, or removed spans with `Note over A,B: new` (or
  `changed`, `removed`). Never write colors into Mermaid source; they would
  ignore the theme and palette pickers.
- Label messages with what is asked ("FilterAuthorized(orgs)"), not full
  call expressions.

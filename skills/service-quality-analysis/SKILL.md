---
name: service-quality-analysis
description: >
  Measure how coherent or tangled a codebase's structure is, and compare it
  with peers, using published dependency metrics (ACD/NCCD, propagation cost,
  Martin's stability and abstractness, directory modularity) over the package
  import graph that graphify already extracted. Produces one tabbed HTML page:
  overview, written analysis and suggestions, a scorecard against comparison
  units, a forest of entry points, dependency matrix, import graph, directory
  vs dependency view, and size and churn. Use whenever the user wants to
  quantify how "spaghetti" a service, module or repo is, compare a service
  against its siblings or against other repos, decide whether a refactor or
  restructure is warranted, or invokes /service-quality-analysis, even if they
  don't say "quality". Requires graphify-out/graph.json in every repo
  analysed. Not for line-level code review.
user_invocable: true
---

# service-quality-analysis

Answers "how tangled is this, compared with what?" with numbers a skeptic can
check. The page shows structure (who imports whom, which directories the
imports cross, what each deployable drags in) and puts published measures next
to peers, because the literature gives no absolute bar for clean.

The analysis is read-only. Nothing in any analysed repo is changed; all files
this skill writes go to a work directory outside the repos (the session
scratchpad when the system prompt names one, else a fresh temp directory).
Suggestions on the page are prose for a conversation, not edits.

Files, all under this skill's directory (`$SKILL`):

| path | role |
|---|---|
| `scripts/preflight.py` | graphify gate; candidate subpart discovery |
| `scripts/build_data.py` | graphify graphs to `data.json`; prints the summary you write from |
| `scripts/go_enrich.py`, `scripts/go/abstract.go` | Go-only: abstractness, linker reachability |
| `scripts/render.py` | `data.json` (+ narrative) into the HTML page |
| `template.html` | the page; owns layout, theming, every chart |
| `references/metrics.md` | definitions, sources, and how to read each measure |
| `references/narrative.md`, `references/example-narrative.json` | schema and style for the prose tabs |

Python 3 standard library only. Go enrichment needs `go` on PATH; churn needs `jj` or `git`.

## Steps

### 1. Gate on graphify

The primary repo is the one the user is in. Run:

```bash
python3 $SKILL/scripts/preflight.py check <primary repo path>
```

Exit 2 means graphify has not been run (or its graph is unusable). The script
prints why and the setup steps. Relay that output to the user, say the
analysis cannot continue without the graph, and stop. Do not run graphify
yourself and do not fall back to another data source. Exit 0 may still print a
stale-graph warning: pass it on and ask whether to continue or update first.

### 2. Interview

Ask with AskUserQuestion; each answer changes what you build. Do not ask
anything the repo already answers.

1. **Unit of analysis.** Single unit (the whole repo is one thing) or
   subparts compared discretely (e.g. each directory under `services/`)?
   If subparts, run `preflight.py units <repo>`, propose the group that looks
   right from its `groups` output, and let the user correct it. Then ask which
   subpart is the **subject** (the deep-dive tabs and the written analysis are
   about it); default to the subpart containing the working directory. With a
   single unit the repo is the subject.
2. **Comparison repos.** Any other repos to compare against? For each, run
   `preflight.py check`. A repo that fails is told the same setup steps as in
   step 1; stop unless the user chooses to drop it. Ask each added repo the
   unit question again (single unit or subparts, and which subparts). A subject
   with no comparison units still works, but the scorecard has no peers and the
   analysis can only describe structure, so say that.

If the subject unit has more than one language, ask which to measure
(`language` or `extensions` in the config below); the default is its dominant
language family.

### 3. Write the config

JSON in the work directory. Every unit needs `name`, `repo` (path to a checkout
with `graphify-out/`), and `root` (directory relative to the repo, `""` for the
whole repo).

```json
{
  "title": "Earn Quality Analysis",
  "subject": "earn",
  "churn_months": 6,
  "min_n_for_ranking": 15,
  "units": [
    {"name": "earn", "repo": "/path/repo", "root": "services/earn"},
    {"name": "scheduler", "repo": "/path/repo", "root": "services/scheduler"}
  ]
}
```

Optional per unit: `language` (go, python, typescript, csharp, java, kotlin,
rust, ruby, php), `extensions`, `entrypoints` (package ids relative to the unit
root; `[]` for none), `tags` (Go build tags passed to `go list`, e.g. for a
module whose code sits behind an integration-test tag). Optional top level:
`exclude` (fnmatch patterns relative to each unit root), `core_min` (entry
points a package needs to count as shared core; default 4, capped at the
number of entry points). Hidden and underscore directories, `vendor` and
`node_modules` are always skipped. Keep `title` to 2 to 4 words.

### 4. Confirm entry points

Run `build_data.py` once with `--no-go --no-churn` (about 10 seconds) and read
the "entry points" count and `data.json` `binaries` keys. Entry points are
packages with a Go `main` function, or files named `main.py`, `__main__.py`,
`Program.cs`, `main.rs`. They drive the forest, matrix and shared-core views.
Show the user the detected list and have them remove tools, examples and
one-off scripts, which would otherwise pose as deployables and skew every
sharing figure. Put the confirmed list in `entrypoints` for the subject. No
entry points is a valid answer; those views are then left off.

### 5. Build the data

```bash
python3 $SKILL/scripts/build_data.py --config <config> --out <workdir>
```

For Go units inside a module it takes the package and file set from `go list -e
./...` (so build constraints, tags, `testdata` and nested modules behave as the
toolchain sees them; import edges still come from the graph), counts
abstractness, and links every entry point with `-dumpdep`; this takes about a minute for ten binaries. It reads
the VCS history of the subject only. Flags: `--no-go`, `--no-churn`. A failed
enrichment is reported as a `NOTE:` and the page simply omits those views, so
pass notes on to the user. Check that the unit and package counts are plausible
for the code; the "graph files missing on disk" message means the graph is
stale and should be rebuilt.

The command prints the summary you write from: a scorecard table, the
subject's rank on each measure, per-entry-point sharing and linker figures, the
largest package, shared core, packages least at home, co-changing pairs, depth
by unit. Read it with `references/metrics.md` open so you attach the right
caveat to each number.

### 6. Write the narrative

Read `references/narrative.md`, then write `<workdir>/narrative.json`: an
Analysis and a Suggestions part. Take every number from the summary or
`data.json`. Only claim what the data supports and say which caveats apply:
how many peers there are, whether the subject is far larger than them, whether
linker data exists. If `data.json` `meta.notes` lists skipped enrichment, keep
the prose off the views that depend on it.

### 7. Render and verify

```bash
python3 $SKILL/scripts/render.py <workdir>/data.json --narrative <workdir>/narrative.json --out <workdir>/<subject>-quality.html
```

`render.py` rejects an invalid narrative and checks that the page script parses
(when `node` is available). If Chrome is installed, load each tab headless and
confirm there are no script errors:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --enable-logging=stderr --v=0 --virtual-time-budget=8000 --dump-dom "file://<page>#scorecard" 2>&1 >/dev/null | grep -i 'uncaught\|TypeError'
```

Repeat per tab id (overview, analysis, suggestions, scorecard, forest, dsm,
matrix, graph, bundle, churn). To see layout, add `--screenshot=<png>
--window-size=1250,2600` and read the PNG.

### 8. Deliver

The page loads D3 from cdnjs and fonts from Google Fonts, so it needs network
to view. Publish it with the Artifact tool when available (private by default,
icon `graph`; the page names internal packages, so leave sharing to the user),
and always give the path of the local `.html`. In the reply, lead with the
answer to "how tangled, compared with what" in two or three sentences, list any
`NOTE:` limits, and say which tabs the page includes.

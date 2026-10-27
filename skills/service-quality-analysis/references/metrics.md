# Measures on the page

All measures are computed per unit over **code packages**: directories holding non-test, non-mock,
non-entry-point source. An edge is a file-level import (graphify `imports` / `imports_from`) rolled up to
directories; test-file imports are excluded. Definitions below match `scripts/build_data.py` (`analyze`).

| Key | Measure | Better | Source |
|---|---|---|---|
| n, e | packages, import edges | size only | count |
| epp | edges per package | low | derived here, not published |
| acd | average component dependency: mean number of packages reachable from a package, itself included | low | Lakos, via [Lattix](https://docs.lattix.com/lattix/userGuide/Metrics.html) |
| nccd | cumulative reach divided by that of a balanced binary tree with the same n: `CCD / ((n+1)·log2(n+1) − n)` | low | Lakos, via Lattix |
| pc | propagation cost: CCD / n² | low | [MacCormack, Rusnak & Baldwin 2006](https://ideas.repec.org/a/inm/ormnsc/v52y2006i7p1015-1030.html) |
| d | mean distance from the main sequence `\|A + I − 1\|`; A = interfaces / types, I = Ce / (Ca + Ce) | low | [Martin's package metrics](https://en.wikipedia.org/wiki/Software_package_metrics) |
| sdp | share of imports whose target is less stable (higher I) than the importer | low | Martin's Stable Dependencies Principle; the percentage is derived here |
| x | share of imports spanning 4 or more directory hops (`CROSS_T`) | low | derived here, not published |
| q | modularity Q of the top-level-directory partition against a 300-shuffle random null; z = (Q − null mean) / null sd | high | Newman and Girvan modularity; shuffle null is derived here |

Notes that change how a number should be read:
- **A needs abstractness counts**, which only the Go enrichment supplies (interfaces and type declarations via
  go/ast). Without them `d` and the main-sequence scatter are absent; this is expected for non-Go units.
- Idiomatic Go is concrete, so A is near 0 and D mostly restates stability. Treat D as a weak signal in Go.
- PC and ACD fall or rise with module size at constant wiring density. Never conclude from them alone when the
  subject is much larger or smaller than its peers; say so.
- Units below `min_n_for_ranking` (default 15 packages) are shown but not ranked.
- "Top-level directory" is the first path segment, or the second when the first is `internal`.
- Tree distance = hops through the lowest common ancestor in the directory tree.

Linker reachability (`used`, Go only): `go build -trimpath -ldflags=-dumpdep` with CGO off, linux/amd64, per entry
point. Per binary each imported package is *called* (a call or reference leads to it), *init only* (linked, its
initializer runs, nothing calls into it) or *eliminated*. It over-counts (interface methods are kept
conservatively) and under-counts (calls hidden by inlining or routed through third-party code are not credited).
The symbol-to-package regex does not support directory names containing dots.

Package set: for Go units with a toolchain, exactly what `go list -e ./...` reports (GoFiles + CgoFiles for LOC,
TestGoFiles + XTestGoFiles for test LOC; a package with only test files is still a code package with 0 LOC).
Without Go, every directory holding a graph code file of the unit's language, ignoring build constraints.
Edges always come from the graph, so a graph built before recent commits misses their imports; preflight warns.

Churn: commits in the `churn_months` calendar months before the trunk head's commit date that touched a non-test source file in the subject unit; co-change
pairs are packages changed in the same commit at least 3 times, skipping commits touching more than 25 packages.

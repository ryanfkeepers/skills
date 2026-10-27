#!/usr/bin/env python3
"""Build data.json for the service-quality-analysis page from graphify graphs.

usage: build_data.py --config config.json --out <dir> [--no-go] [--no-churn]

Reads <repo>/graphify-out/graph.json for every unit in the config, turns file-level
import edges into a directory-level package graph, and computes the published
coupling/cohesion metrics for each unit. The subject unit also gets entry-point
closures, VCS churn and (Go only) linker-reachability data. Nothing under any
analysed repo is modified.
"""
import argparse
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import date
from fnmatch import fnmatch
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import go_enrich  # noqa: E402

sys.setrecursionlimit(20000)

IMPORT_RELATIONS = {"imports", "imports_from"}
TEST_FILE = re.compile(r"(_test\.go|(^|/)test_[^/]*\.py|_test\.py|\.(test|spec)\.[jt]sx?|Tests?\.(cs|java|kt)|_spec\.rb)$")
TEST_DIRS = {"tests", "test", "testdata", "__tests__", "e2e"}
MOCK_DIRS = {"mock", "mocks"}
LANGUAGE_FAMILIES = {
    "go": {".go"}, "python": {".py"}, "typescript": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
    "csharp": {".cs"}, "java": {".java"}, "kotlin": {".kt", ".kts"}, "rust": {".rs"}, "ruby": {".rb"}, "php": {".php"},
}
SKIP_SEGMENT = re.compile(r"^(\.|_)|^(node_modules|vendor)$")
GENERIC_ENTRY_FILES = {"__main__.py", "main.py", "Program.cs", "main.rs"}
CROSS_T = 4
MAX_PKGS_PER_COMMIT_FOR_COCHANGE = 25
MIN_PAIR_COMMITS = 3
SHUFFLES = 300


def log(msg):
    print(msg, file=sys.stderr)


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


# ---------------------------------------------------------------- graph -> packages

class Graph:
    def __init__(self, repo):
        raw = json.loads(Path(repo, "graphify-out", "graph.json").read_text())
        self.nodes = {n["id"]: n for n in raw["nodes"]}
        links = raw.get("links") or raw.get("edges") or []
        self.code_files = {n["source_file"] for n in self.nodes.values() if n.get("file_type") == "code" and n.get("source_file")}
        self.file_edges = self._file_edges(links)
        self.main_files = {n["source_file"] for n in self.nodes.values()
                           if n.get("label") in ("main()", "main") and (n.get("source_file") or "").endswith(".go")}

    def _file_edges(self, links):
        out = set()
        for e in links:
            if e.get("relation") not in IMPORT_RELATIONS:
                continue
            src = e.get("source_file") or self.nodes.get(e["source"], {}).get("source_file")
            tn = self.nodes.get(e["target"])
            dst = tn.get("source_file") if tn and tn.get("file_type") == "code" else None
            if src and dst and src != dst:
                out.add((src, dst))
        return out


def pkg_dir(rel_file):
    return os.path.dirname(rel_file) or "(root)"


def kind_of(pkg_id, entries):
    segs = pkg_id.split("/")
    if pkg_id in entries or segs[0] == "cmd":
        return "cmd"
    if any(s in MOCK_DIRS for s in segs):
        return "mock"
    if any(s in TEST_DIRS for s in segs):
        return "test"
    return "code"


def tree_distance(a, b):
    """Hops between two package dirs through their lowest common ancestor."""
    sa = [] if a == "(root)" else a.split("/")
    sb = [] if b == "(root)" else b.split("/")
    i = 0
    while i < len(sa) and i < len(sb) and sa[i] == sb[i]:
        i += 1
    return (len(sa) - i) + (len(sb) - i)


def count_lines(path):
    try:
        return Path(path).read_bytes().count(b"\n")
    except OSError:
        return None


def detect_entries(g, prefix, files):
    found = set()
    for f in g.main_files:
        if f.startswith(prefix) and not TEST_FILE.search(f):
            found.add(pkg_dir(f[len(prefix):]))
    for f in files:
        if os.path.basename(f) in GENERIC_ENTRY_FILES and not TEST_FILE.search(f):
            found.add(pkg_dir(f[len(prefix):]))
    return sorted(found)


def pick_extensions(unit, files):
    """File extensions this unit is measured over: configured, else the dominant language family."""
    if unit.get("extensions"):
        return set(unit["extensions"])
    if unit.get("language") in LANGUAGE_FAMILIES:
        return LANGUAGE_FAMILIES[unit["language"]]
    counts = Counter(os.path.splitext(f)[1] for f in files)
    if not counts:
        return set()
    top = counts.most_common(1)[0][0]
    return next((fam for fam in LANGUAGE_FAMILIES.values() if top in fam), {top})


def nested_go_modules(repo, prefix, files):
    """Directories below the unit root with their own go.mod: `go list ./...` does not descend into them."""
    root = prefix.rstrip("/")
    nested = set()
    for d in {os.path.dirname(f) for f in files}:
        while d and d != root and d.startswith(prefix):
            if (repo / d / "go.mod").exists():
                nested.add(d + "/")
            d = os.path.dirname(d)
    return nested


def build_unit(unit, g, cfg, go_listing=None):
    """Package graph for one unit.

    go_listing (from go_enrich.go_files) replaces the graph's file set with the files `go list` builds, so build
    constraints, tags, testdata and test-only packages behave as the Go toolchain sees them.
    """
    root = unit["root"].strip("/")
    prefix = "" if root in ("", ".") else root + "/"
    repo = Path(unit["repo"])
    excludes = cfg.get("exclude", [])
    test_files, main_pkgs = set(), set()
    if go_listing is not None:
        exts = {".go"}
        files = []
        for pid, entry in go_listing.items():
            base = prefix + ("" if pid == "(root)" else pid + "/")
            files += [base + f for f in entry["go"]]
            test_files |= {base + f for f in entry["test"]}
            if entry["name"] == "main":
                main_pkgs.add(pid)
        files = sorted(set(files) | test_files)
    else:
        files = sorted(f for f in g.code_files
                       if f.startswith(prefix) and not any(fnmatch(f[len(prefix):], pat) for pat in excludes)
                       and not any(SKIP_SEGMENT.search(seg) for seg in f[len(prefix):].split("/")))
        exts = pick_extensions(unit, files)
        files = [f for f in files if os.path.splitext(f)[1] in exts]
        if exts == {".go"}:
            nested = nested_go_modules(repo, prefix, files)
            files = [f for f in files if not any(f.startswith(n) for n in nested)]
        test_files = {f for f in files if TEST_FILE.search(f)}
    fileset = set(files)
    missing = 0
    pk = {pid: {"files": 0, "loc": 0, "test_loc": 0, "imports": set(), "test_imports": set()} for pid in (go_listing or {})}
    for f in files:
        rel = f[len(prefix):]
        p = pk.setdefault(pkg_dir(rel), {"files": 0, "loc": 0, "test_loc": 0, "imports": set(), "test_imports": set()})
        n = count_lines(repo / f)
        if n is None:
            missing += 1
            n = 0
        if f in test_files:
            p["test_loc"] += n
        else:
            p["files"] += 1
            p["loc"] += n
    for sf, df in g.file_edges:
        if sf not in fileset or df not in fileset:
            continue
        ps, pd = pkg_dir(sf[len(prefix):]), pkg_dir(df[len(prefix):])
        if ps != pd:
            (pk[ps]["test_imports"] if sf in test_files else pk[ps]["imports"]).add(pd)
    entries = unit.get("entrypoints")
    auto = entries is None
    if auto:
        entries = detect_entries(g, prefix, files)
    entries = [e for e in entries if e in pk]
    entry_set = set(entries)
    pkgs = {}
    for k, p in pk.items():
        kind = "cmd" if k in main_pkgs else kind_of(k, entry_set)
        pkgs[k] = {
            "id": k, "kind": kind, "files": p["files"], "loc": p["loc"], "test_loc": p["test_loc"],
            "imports": sorted(p["imports"] - {k}),
            "test_imports": sorted(p["test_imports"] - p["imports"] - {k}),
            "types": 0, "ifaces": 0,
        }
    return {"unit": unit, "prefix": prefix, "files": files, "exts": sorted(exts), "pkgs": pkgs, "entries": entries,
            "entries_auto": auto, "missing_files": missing}


def closure(pkgs, start):
    seen, q = {start}, deque([start])
    while q:
        u = q.popleft()
        for v in pkgs[u]["imports"]:
            if v in pkgs and v not in seen:
                seen.add(v)
                q.append(v)
    return sorted(seen)


# ---------------------------------------------------------------- churn

def detect_vcs(repo):
    if (Path(repo) / ".jj").exists():
        return "jj"
    if (Path(repo) / ".git").exists():
        return "git"
    return None


def churn_commits(repo, root, vcs, after):
    """Return (commits_total, [list of changed file paths per commit touching root])."""
    if vcs == "jj":
        fileset = f'root:"{root}"' if root else "all()"
        tmpl = f'self.diff({json.dumps(fileset)}).files().map(|f| f.path()).join("\\t") ++ "\\n"'
        base = ["jj", "--ignore-working-copy", "--no-pager", "log", "--no-graph", "-T", tmpl]
        for scope in ("::trunk()", "::@"):
            try:
                out = run(base + ["-r", f'committer_date(after:"{after}") & {scope}'], repo)
                break
            except subprocess.CalledProcessError:
                out = None
        if out is None:
            raise RuntimeError("jj log failed for both ::trunk() and ::@")
        lines = out.splitlines()
        return len(lines), [[f for f in ln.split("\t") if f] for ln in lines]
    args = ["--since", after, "--no-merges"]
    total = int(run(["git", "rev-list", "--count", *args, "HEAD"], repo).strip() or 0)
    out = run(["git", "log", *args, "--name-only", "--format=%x1e", "HEAD", "--", root or "."], repo)
    commits = [[f for f in rec.split("\n") if f] for rec in out.split("\x1e")[1:]]
    return total, commits


def head_date(repo, vcs):
    """Committer date of the history tip the churn window is measured back from."""
    cmds = {"jj": [["jj", "--ignore-working-copy", "--no-pager", "log", "--no-graph", "-r", rev, "-T",
                    'committer.timestamp().format("%Y-%m-%d")'] for rev in ("trunk()", "@-")],
            "git": [["git", "log", "-1", "--format=%cs", "HEAD"]]}.get(vcs, [])
    for cmd in cmds:
        try:
            return date.fromisoformat(run(cmd, repo).strip()[:10])
        except (subprocess.CalledProcessError, ValueError):
            continue
    return None


def months_before(d, months):
    y, m = divmod(d.year * 12 + d.month - 1 - int(months), 12)
    m += 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, days))


def churn(unit_data, months):
    unit = unit_data["unit"]
    repo, prefix = unit["repo"], unit_data["prefix"]
    vcs = detect_vcs(repo)
    after = months_before(head_date(repo, vcs) or date.today(), months).isoformat()
    base = {"available": False, "after": after, "months": months, "vcs": vcs or "none",
            "commits_total": 0, "commits_touching_subject": 0, "cochange_skipped_big_commits": 0, "pairs": []}
    if not vcs:
        return base, {}, {}
    try:
        total, commits = churn_commits(repo, prefix.rstrip("/"), vcs, after)
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as ex:
        log(f"churn unavailable: {str(ex)[:160]}")
        return base, {}, {}
    pkgs = unit_data["pkgs"]
    exts = {os.path.splitext(f)[1] for f in unit_data["files"]}
    by_len = sorted((p for p in pkgs if p != "(root)"), key=len, reverse=True)

    def pkg_for(path):
        if not path.startswith(prefix):
            return None
        r = path[len(prefix):]
        d = os.path.dirname(r) or "(root)"
        for p in by_len:
            if d == p or d.startswith(p + "/"):
                return p
        return "(root)" if d == "(root)" and "(root)" in pkgs else None

    per_pkg, per_pkg_test, pairs = Counter(), Counter(), Counter()
    touching = skipped = 0
    for files in commits:
        if not files:
            continue
        touching += 1
        touched, touched_test = set(), set()
        for f in files:
            if os.path.splitext(f)[1] not in exts:
                continue
            p = pkg_for(f)
            if p is None:
                continue
            (touched_test if TEST_FILE.search(f) else touched).add(p)
        for p in touched:
            per_pkg[p] += 1
        for p in touched_test:
            per_pkg_test[p] += 1
        code_pkgs = sorted(p for p in touched if pkgs[p]["kind"] == "code")
        if len(code_pkgs) > MAX_PKGS_PER_COMMIT_FOR_COCHANGE:
            skipped += 1
            continue
        for a, b in combinations(code_pkgs, 2):
            pairs[(a, b)] += 1
    imported = {(s, t) for s, p in pkgs.items() for t in p["imports"]}
    imported |= {(t, s) for s, t in imported}
    out_pairs = sorted(({"a": a, "b": b, "n": n, "linked": (a, b) in imported}
                        for (a, b), n in pairs.items() if n >= MIN_PAIR_COMMITS), key=lambda x: -x["n"])[:400]
    base.update(available=True, commits_total=total, commits_touching_subject=touching,
                cochange_skipped_big_commits=skipped, pairs=out_pairs)
    return base, per_pkg, per_pkg_test


# ---------------------------------------------------------------- metrics

def group_of(i):
    if i == "(root)":
        return "(root)"
    s = i.split("/")
    return s[1] if s[0] == "internal" and len(s) > 1 else s[0]


def parent_of(i):
    return i.rsplit("/", 1)[0] if "/" in i else "(root)"


def reach_counts(nodes, adj):
    reach = {}
    for n in nodes:
        seen, q = {n}, deque([n])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    q.append(v)
        reach[n] = len(seen)
    return reach


def heights(nodes, adj):
    memo = {}

    def h(n, stack=()):
        if n in memo:
            return memo[n]
        if n in stack:
            return 0
        memo[n] = 0 if not adj[n] else 1 + max(h(c, stack + (n,)) for c in adj[n])
        return memo[n]

    return {n: h(n) for n in nodes}


def modularity(undirected, part):
    m = len(undirected)
    if m == 0:
        return 0.0
    deg, intra = defaultdict(int), defaultdict(int)
    for a, b in undirected:
        deg[part[a]] += 1
        deg[part[b]] += 1
        if part[a] == part[b]:
            intra[part[a]] += 1
    return sum(intra[c] / m - (deg[c] / (2 * m)) ** 2 for c in deg)


def modularity_null(nodes, undirected, part, seed=7):
    rng = random.Random(seed)
    labels = [part[n] for n in nodes]
    qs = []
    for _ in range(SHUFFLES):
        rng.shuffle(labels)
        qs.append(modularity(undirected, dict(zip(nodes, labels))))
    return statistics.mean(qs), (statistics.pstdev(qs) or 1e-9)


def analyze(pkgs):
    """Summary metrics for one unit plus per-package detail (code packages only)."""
    code = {k: p for k, p in pkgs.items() if p["kind"] == "code"}
    nodes = sorted(code)
    adj = {n: [t for t in code[n]["imports"] if t in code] for n in nodes}
    edges = [(s, t) for s in nodes for t in adj[s]]
    n_nodes, n_edges = len(nodes), len(edges)
    ca, ce = defaultdict(int), defaultdict(int)
    for s, t in edges:
        ce[s] += 1
        ca[t] += 1
    reach = reach_counts(nodes, adj)
    h = heights(nodes, adj)
    ccd = sum(reach.values())
    ccd_tree = (n_nodes + 1) * math.log2(n_nodes + 1) - n_nodes if n_nodes else 0
    per = {}
    for n in nodes:
        tot = ca[n] + ce[n]
        i = ce[n] / tot if tot else None
        ty = code[n]["types"]
        a = code[n]["ifaces"] / ty if ty else None
        d = abs(a + i - 1) if i is not None and a is not None else None
        per[n] = {"ca": ca[n], "ce": ce[n], "i": i, "a": a, "d": d, "reach": reach[n], "h": h[n],
                  "types": ty, "ifaces": code[n]["ifaces"]}
    sdp = [(s, t) for s, t in edges if per[s]["i"] is not None and per[t]["i"] is not None]
    sdp_bad = [(s, t) for s, t in sdp if per[t]["i"] > per[s]["i"]]
    ds = [p["d"] for p in per.values() if p["d"] is not None]
    undirected = {tuple(sorted(e)) for e in edges}
    q = {}
    for name, fn in (("top", group_of), ("parent", parent_of)):
        part = {n: fn(n) for n in nodes}
        qv = modularity(undirected, part)
        mu, sd = modularity_null(nodes, undirected, part)
        q[name] = {"q": qv, "null_mean": mu, "z": (qv - mu) / sd, "groups": len(set(part.values()))}
    topg = {n: group_of(n) for n in nodes}
    nbrs = defaultdict(set)
    for a, b in undirected:
        nbrs[a].add(b)
        nbrs[b].add(a)
    for n in nodes:
        per[n]["fit"] = (sum(1 for x in nbrs[n] if topg[x] == topg[n]) / len(nbrs[n])) if nbrs[n] else None
        per[n]["deg"] = len(nbrs[n])
    dist = [tree_distance(s, t) for s, t in edges]
    depths = [0 if n == "(root)" else len(n.split("/")) for n in nodes]
    summary = {
        "n": n_nodes, "e": n_edges,
        "edges_per_pkg": n_edges / n_nodes if n_nodes else 0,
        "ccd": ccd, "acd": ccd / n_nodes if n_nodes else 0,
        "nccd": ccd / ccd_tree if ccd_tree else 0,
        "pc": ccd / (n_nodes ** 2) if n_nodes else 0,
        "mean_d": statistics.mean(ds) if ds else None,
        "d_over_07": (sum(1 for x in ds if x > 0.7) / len(ds)) if ds else None,
        "d_defined": len(ds),
        "sdp_bad": len(sdp_bad), "sdp_total": len(sdp),
        "sdp_pct": len(sdp_bad) / len(sdp) if sdp else None,
        "q": q,
        "cross_pct": (sum(1 for x in dist if x >= CROSS_T) / len(dist)) if dist else None,
        "max_height": max(h.values()) if h else 0,
        "mean_depth": statistics.mean(depths) if depths else 0,
    }
    return summary, per, sdp_bad


# ---------------------------------------------------------------- facts

MEASURE_RANKS = [  # key, label, direction, getter
    ("nccd", "NCCD", "low", lambda m: m["nccd"]),
    ("sdp", "Imports toward less stable", "low", lambda m: m["sdp_pct"]),
    ("q", "Directory modularity Q", "high", lambda m: m["q"]["top"]["q"]),
    ("acd", "ACD", "low", lambda m: m["acd"]),
    ("epp", "Edges per package", "low", lambda m: m["edges_per_pkg"]),
    ("x", "Cross-subtree imports", "low", lambda m: m["cross_pct"]),
]


def best_other(pkgs, hub_id, key):
    other = max((p for p in pkgs if p["id"] != hub_id), key=lambda p: p[key], default=None)
    return {"id": other["id"], key: other[key]} if other else None


def compute_facts(data, modules, subject, min_n, core_min_cfg=None):
    pkgs = data["packages"]
    by_id = {p["id"]: p for p in pkgs}
    code = [p for p in pkgs if p["kind"] == "code"]
    code_ids = {p["id"] for p in code}
    binaries = data["binaries"]
    used = data.get("used")
    peers = [m for m in modules.values() if m["n"] >= min_n]
    ranks = []
    subj = modules[subject]
    for key, label, direction, get in MEASURE_RANKS:
        vals = sorted((m for m in peers if get(m) is not None), key=get, reverse=(direction == "high"))
        idx = next((i for i, m in enumerate(vals) if m["name"] == subject), None)
        ranks.append({"key": key, "name": label, "rank": idx, "of": len(vals), "value": get(subj)})
    use_n = Counter()
    for ids in binaries.values():
        for i in ids:
            if i in code_ids:
                use_n[i] += 1
    share_rows, binary_rows = [], []
    for b, closure_ids in binaries.items():
        ids = [i for i in closure_ids if i in code_ids]
        idset = set(ids)
        shared = sum(1 for i in ids if use_n[i] >= 2)
        share_rows.append({"b": b, "s": shared, "own": len(ids) - shared, "pct": shared / len(ids) if ids else 0})
        imp = sum(len([t for t in by_id[s]["imports"] if t in idset]) for s in [b, *ids])
        row = {"b": b, "n": len(ids), "imp": imp, "called": None, "init": None, "gone": None, "used": None,
               "noise": None, "states": None}
        if used:
            u = used["per_binary"][b]
            row.update(called=len(u["pkgs"]), init=len(u["init_only"]), gone=len(u["eliminated"]), used=len(u["edges"]),
                       noise=(1 - len(u["edges"]) / imp) if imp and len(u["edges"]) <= imp else None,
                       states=sum(1 for s in used["states"] if b in s["bins"]))
        binary_rows.append(row)
    share_rows.sort(key=lambda r: (-r["pct"], -(r["s"] + r["own"])))
    binary_rows.sort(key=lambda r: -r["n"])
    hub = None
    if len(code) > 1:
        top = max(code, key=lambda p: p["loc"])
        hub = {"id": top["id"], "loc": top["loc"], "fan_out": top["fan_out"], "commits": top["commits"],
               "next_loc": best_other(code, top["id"], "loc"), "next_out": best_other(code, top["id"], "fan_out"),
               "next_churn": best_other(code, top["id"], "commits")}
        if used:
            hub["bins"] = [b for b in binaries if top["id"] in used["per_binary"][b]["pkgs"]]
        else:
            hub["bins"] = [b for b, ids in binaries.items() if top["id"] in ids]
    core_min = core_min_cfg or max(2, min(4, len(binaries)))
    if used:
        called_by = Counter(p for b in binaries for p in used["per_binary"][b]["pkgs"])
        core_basis = "linker"
    else:
        called_by = Counter({i: n for i, n in use_n.items()})
        core_basis = "imports"
    core = sorted(([p, n] for p, n in called_by.items() if n >= core_min), key=lambda x: (-x[1], x[0]))
    misfit_pool = [p for p in code if p.get("fit") is not None and p.get("deg", 0) >= 10]
    if len(misfit_pool) < 3:
        misfit_pool = [p for p in code if p.get("fit") is not None and p.get("deg", 0) >= 4]
    misfit = sorted(misfit_pool, key=lambda p: (p["fit"], -p["deg"]))[:5]
    hidden = [{"a": p["a"], "b": p["b"], "n": p["n"]} for p in data["churn"]["pairs"]
              if not p["linked"] and p["a"] in code_ids and p["b"] in code_ids]
    depth = sorted(({"label": name, "v": m["mean_depth"], "hi": name == subject} for name, m in modules.items()),
                   key=lambda r: -r["v"])
    deepest = sorted(({"id": p["id"], "d": len(p["id"].split("/"))} for p in code),
                     key=lambda r: (-r["d"], r["id"]))[:6]
    return {
        "n_peers": len(peers), "ranks": ranks, "share_rows": share_rows, "binary_rows": binary_rows, "hub": hub,
        "core": core, "core_min": core_min, "core_basis": core_basis,
        "misfit": [{"id": p["id"], "fit": p["fit"], "deg": p["deg"]} for p in misfit],
        "hidden": hidden[:12], "hidden_total": len(hidden), "depth": depth, "deepest": deepest,
    }


def print_summary(data, facts, modules, subject):
    p = lambda *a: print(*a)
    m = modules[subject]
    p(f"\n== {subject}: {m['n']} packages, {m['e']} edges, {len(data['binaries'])} entry points ==")
    p("unit            n    e  edges/pkg   ACD  NCCD    PC   meanD  SDP%   Q(top) z    cross%  depth")
    for name, s in sorted(modules.items(), key=lambda kv: -kv[1]["n"]):
        f = lambda v, fmt: "n/a" if v is None else format(v, fmt)
        p(f"{('*' if name == subject else ' ') + name:<16}{s['n']:>3}{s['e']:>5}{s['edges_per_pkg']:>9.2f}{s['acd']:>7.1f}{s['nccd']:>6.2f}"
          f"{s['pc']:>7.1%}{f(s['mean_d'], '.2f'):>7}{f(s['sdp_pct'], '.0%'):>6}{s['q']['top']['q']:>8.2f}{s['q']['top']['z']:>5.1f}"
          f"{f(s['cross_pct'], '.0%'):>8}{s['mean_depth']:>6.2f}")
    p(f"\npeers ranked (n >= {data['metrics']['min_n_for_ranking']}): {facts['n_peers']}")
    for r in facts["ranks"]:
        p(f"  {r['name']:<30} value {r['value']}  rank {None if r['rank'] is None else r['rank'] + 1} of {r['of']}")
    if facts["binary_rows"]:
        p("\nentry point            pkgs  import_edges  called  init_only  eliminated  noise  shared%")
        sh = {r["b"]: r["pct"] for r in facts["share_rows"]}
        for r in facts["binary_rows"]:
            nz = "n/a" if r["noise"] is None else f"{r['noise']:.0%}"
            p(f"{r['b']:<22}{r['n']:>5}{r['imp']:>14}{str(r['called']):>8}{str(r['init']):>11}{str(r['gone']):>12}{nz:>7}{sh[r['b']]:>9.0%}")
    if data.get("used"):
        p("\ninit-only packages per binary (linked for their initializers, never called):")
        for b, u in sorted(data["used"]["per_binary"].items()):
            if u["init_only"]:
                p(f"  {b}: {u['init_only']}")
    h = facts["hub"]
    if h:
        p(f"\nlargest package: {h['id']} loc {h['loc']} fan_out {h['fan_out']} commits {h['commits']}; runner-ups "
          f"loc {h['next_loc']}, fan_out {h['next_out']}, commits {h['next_churn']}; reached by {h['bins']}")
    p(f"\nshared core (>= {facts['core_min']} entry points, by {facts['core_basis']}): {len(facts['core'])} packages: {facts['core'][:12]}")
    p(f"least at home in their directory: {[(x['id'], round(x['fit'], 2), x['deg']) for x in facts['misfit']]}")
    p(f"co-changing pairs with no import: {facts['hidden_total']} in total; top: {[(x['a'], x['b'], x['n']) for x in facts['hidden'][:6]]}")
    p(f"mean depth by unit: {[(x['label'], round(x['v'], 2)) for x in facts['depth']]}")
    p(f"deepest: {[(x['id'], x['d']) for x in facts['deepest']]}")
    c = data["churn"]
    p(f"churn: available={c['available']} vcs={c['vcs']} since {c['after']}: {c['commits_touching_subject']} of {c['commits_total']} commits touch the subject")


# ---------------------------------------------------------------- main

def short_names(entries):
    names = {e: e[4:] if e.startswith("cmd/") else e for e in entries}
    vals = list(names.values())
    if len(vals) > 1:
        pref = os.path.commonprefix(vals)
        cut = max(pref.rfind("-"), pref.rfind("_"), pref.rfind("/")) + 1
        if cut and all(len(v) > cut for v in vals):
            names = {e: v[cut:] for e, v in names.items()}
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-go", action="store_true", help="skip go list / linker enrichment")
    ap.add_argument("--no-churn", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    subject = cfg["subject"]
    months = cfg.get("churn_months", 6)
    min_n = cfg.get("min_n_for_ranking", 15)

    graphs, built = {}, {}
    for u in cfg["units"]:
        u["repo"] = str(Path(u["repo"]).expanduser().resolve())
        if u["repo"] not in graphs:
            log(f"loading graph for {u['repo']}")
            graphs[u["repo"]] = Graph(u["repo"])
        built[u["name"]] = build_unit(u, graphs[u["repo"]], cfg)
        b = built[u["name"]]
        log(f"{u['name']}: {len(b['pkgs'])} directories ({'/'.join(b['exts'])}), {len(b['entries'])} entry points"
            + (f", {b['missing_files']} graph files missing on disk" if b["missing_files"] else ""))
    if subject not in built:
        sys.exit(f"subject {subject!r} is not one of the units")

    notes = []
    if not args.no_go:
        for name, b in built.items():
            root = Path(b["unit"]["repo"], b["prefix"].rstrip("/"))
            if b["exts"] != [".go"]:
                continue
            ok, why = go_enrich.available(root)
            if not ok:
                notes.append(f"{name}: Go enrichment skipped ({why}); package set is the graph's, ignoring build constraints")
                continue
            try:
                listing = go_enrich.go_files(root, b["unit"].get("tags"))
            except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as ex:
                notes.append(f"{name}: go list failed ({str(ex)[:100]}); package set is the graph's")
                continue
            b = built[name] = build_unit(b["unit"], graphs[b["unit"]["repo"]], cfg, listing)
            try:
                counts = go_enrich.abstract_counts(root)
            except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as ex:
                notes.append(f"{name}: abstractness skipped ({str(ex)[:100]})")
                continue
            for k, c in counts.items():
                if k in b["pkgs"]:
                    b["pkgs"][k]["types"], b["pkgs"][k]["ifaces"] = c["types"], c["ifaces"]
            b["go_ok"] = True
            log(f"{name}: abstractness counted")

    sb = built[subject]
    pkgs = sb["pkgs"]
    binaries = {e: closure(pkgs, e) for e in sb["entries"]}

    if args.no_churn:
        ch, per_pkg, per_pkg_test = {"available": False, "after": "", "months": months, "vcs": "none", "commits_total": 0,
                                     "commits_touching_subject": 0, "cochange_skipped_big_commits": 0, "pairs": []}, {}, {}
    else:
        ch, per_pkg, per_pkg_test = churn(sb, months)
    for k, p in pkgs.items():
        p["commits"], p["test_commits"] = per_pkg.get(k, 0), per_pkg_test.get(k, 0)

    edges, fan_in = [], Counter()
    for k, p in pkgs.items():
        for t in p["imports"]:
            edges.append({"s": k, "t": t, "d": tree_distance(k, t)})
            fan_in[t] += 1
    for k, p in pkgs.items():
        p["fan_in"], p["fan_out"] = fan_in.get(k, 0), len(p["imports"])

    used = None
    if binaries and not args.no_go and sb.get("go_ok"):
        root = Path(sb["unit"]["repo"], sb["prefix"].rstrip("/"))
        try:
            log(f"linking {len(binaries)} binaries with -dumpdep (slow)...")
            used = go_enrich.used_forest(root, pkgs, binaries)
        except (RuntimeError, subprocess.CalledProcessError, OSError) as ex:
            notes.append(f"linker-reachability skipped: {str(ex)[:200]}")

    modules, subj_per, subj_sdp = {}, None, None
    for name, b in built.items():
        summary, per, sdp_bad = analyze(b["pkgs"])
        summary["name"] = name
        modules[name] = summary
        if name == subject:
            subj_per, subj_sdp = per, sdp_bad
    for k, p in pkgs.items():
        if k in subj_per:
            p.update(subj_per[k])

    for p in pkgs.values():
        p["imports"] = sorted(p["imports"])
    data = {
        "meta": {
            "title": cfg.get("title") or f"{subject} Quality Analysis",
            "subject": subject,
            "vcs": ch["vcs"],
            "months": months,
            "units_desc": ", ".join(f"{n} ({b['unit']['repo'].rsplit('/', 1)[-1]}:{b['unit']['root']})" for n, b in built.items()),
            "entry_desc": ("packages with a main function" if sb["entries_auto"] and sb["exts"] == [".go"]
                           else "entry points chosen for this analysis"),
            "short": short_names(sb["entries"]),
            "has_used": used is not None,
            "has_abstractness": any(p["types"] for p in pkgs.values() if p["kind"] == "code"),
            "has_churn": ch["available"],
            "notes": notes,
        },
        "packages": sorted(pkgs.values(), key=lambda x: x["id"]),
        "edges": edges,
        "binaries": binaries,
        "churn": ch,
        "metrics": {"modules": modules, "min_n_for_ranking": min_n, "shuffles": SHUFFLES},
        "sdp_violations": [{"s": s, "t": t} for s, t in subj_sdp],
    }
    if used:
        data["used"] = used
    data["facts"] = compute_facts(data, modules, subject, min_n, cfg.get("core_min"))

    (out_dir / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    print_summary(data, data["facts"], modules, subject)
    for n in notes:
        print("NOTE:", n)
    print(f"\nwrote {out_dir / 'data.json'} ({(out_dir / 'data.json').stat().st_size} bytes)")


if __name__ == "__main__":
    main()

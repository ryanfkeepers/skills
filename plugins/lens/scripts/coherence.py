"""Decoherence signals: what a change did to the structure, from two graphify graphs.

Compares the run's base snapshot (before the change) with its live snapshot
(after). Every signal is a delta caused by the change, not a score of the whole
repo:
  new_cycles             package import cycles that weren't there before
  direction_violations   new package edges that invert an existing direction
  cross_community_ratio  share of new edges that cross graphify communities
  concept_scatter        communities the change's new nodes spread across
  hub_growth             nodes the change pushed into the top quartile of degree
Package edges use the same relations service-quality-analysis does.
Thresholds compare against the repo's own base graph: cycles and direction
violations always flag; the rest flag only in the base's worst quartile.
"""
import glob
import json
import os
import subprocess
import sys
from collections import defaultdict

IMPORT_RELATIONS = {"imports", "imports_from"}
SQA_METRICS = ("acd", "nccd", "pc", "sdp_pct", "mean_d", "cross_pct")  # higher is worse for every one
SQA_REGRESSION = 0.10  # a relative worsening past this is a finding
SKIP_LINKS = {".jj", ".git", "graphify-out"}


def load(path):
    with open(path) as f:
        return json.load(f)


def links(g):
    return g.get("links", g.get("edges", []))


def files(g):
    return {n["id"]: n.get("source_file") for n in g.get("nodes", [])}


def package(path):
    return os.path.dirname(path) if path else None


def package_edges(g):
    by_id = files(g)
    edges = set()
    for e in links(g):
        if e.get("relation") not in IMPORT_RELATIONS:
            continue
        a, b = package(by_id.get(e["source"])), package(by_id.get(e["target"]))
        if a is not None and b is not None and a != b:
            edges.add((a, b))
    return edges


def reach(edges):
    out = defaultdict(set)
    for a, b in edges:
        out[a].add(b)
    seen = {}
    for start in list(out):
        stack, found = [start], set()
        while stack:
            for nxt in out.get(stack.pop(), ()):
                if nxt not in found:
                    found.add(nxt)
                    stack.append(nxt)
        seen[start] = found
    return seen


def cycle_pairs(edges):
    r = reach(edges)
    return {(a, b) for a in r for b in r[a] if a < b and a in r.get(b, set())}


def cycle_groups(edges):
    """Each set of packages that all reach one another (a strongly connected group of 2+)."""
    r = reach(edges)
    groups = set()
    for a in r:
        group = frozenset({a} | {b for b in r[a] if a in r.get(b, set())})
        if len(group) > 1:
            groups.add(group)
    return groups


def quartile(values):
    vals = sorted(values)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(len(vals) * 0.75))]


def degrees(g):
    d = defaultdict(int)
    for e in links(g):
        d[e["source"]] += 1
        d[e["target"]] += 1
    return d


def community(g):
    return {n["id"]: n.get("community") for n in g.get("nodes", [])}


def report(base_path, live_path):
    base, live = load(base_path), load(live_path)
    findings = []

    base_pe, live_pe = package_edges(base), package_edges(live)
    old_pairs = cycle_pairs(base_pe)
    new_cycles = sorted(sorted(g) for g in cycle_groups(live_pe)
                        if any((a, b) not in old_pairs for a in g for b in g if a < b))
    for group in new_cycles:
        findings.append({"signal": "new_cycle", "packages": group})

    base_reach = reach(base_pe)
    violations = sorted((a, b) for a, b in live_pe - base_pe if a in base_reach.get(b, set()))
    for a, b in violations:
        findings.append({"signal": "direction_violation", "edge": [a, b],
                         "existing": f"{b} already depends on {a}"})

    comm_base, comm_live = community(base), community(live)
    base_keys = {(e["source"], e["target"]) for e in links(base)}
    new_edges = [e for e in links(live) if (e["source"], e["target"]) not in base_keys]
    crossing = [e for e in new_edges if comm_live.get(e["source"]) != comm_live.get(e["target"])]
    ratio = round(len(crossing) / len(new_edges), 3) if new_edges else 0.0
    per_node = defaultdict(lambda: [0, 0])
    for e in links(base):
        for end in (e["source"], e["target"]):
            per_node[end][1] += 1
            if comm_base.get(e["source"]) != comm_base.get(e["target"]):
                per_node[end][0] += 1
    ratio_q = quartile([c / t for c, t in per_node.values() if t])
    if new_edges and ratio_q is not None and ratio > ratio_q:
        findings.append({"signal": "cross_community", "ratio": ratio, "baseline_p75": round(ratio_q, 3)})

    new_nodes = [n for n in live.get("nodes", []) if n["id"] not in comm_base]
    scatter = len({n.get("community") for n in new_nodes})
    per_package = defaultdict(set)
    for n in base.get("nodes", []):
        per_package[package(n.get("source_file"))].add(n.get("community"))
    scatter_q = quartile([len(c) for c in per_package.values()])
    if new_nodes and scatter_q is not None and scatter > scatter_q:
        findings.append({"signal": "concept_scatter", "communities": scatter, "baseline_p75": scatter_q})

    d_base, d_live = degrees(base), degrees(live)
    hub_q = quartile(list(d_base.values()))
    hubs = []
    if hub_q is not None:
        for nid, deg in d_live.items():
            before = d_base.get(nid, 0)
            if nid in comm_base and before < hub_q <= deg and deg > before:
                hubs.append({"node": nid, "degree": deg, "before": before})
    for h in sorted(hubs, key=lambda h: -h["degree"]):
        findings.append(dict(h, signal="hub_growth", baseline_p75=hub_q))

    return {
        "findings": findings,
        "signals": {
            "new_cycles": len(new_cycles), "direction_violations": len(violations),
            "new_edges": len(new_edges), "cross_community_ratio": ratio,
            "cross_community_baseline_p75": ratio_q, "concept_scatter": scatter,
            "concept_scatter_baseline_p75": scatter_q, "hubs": len(hubs), "degree_baseline_p75": hub_q,
        },
    }


# ---- service-quality-analysis deltas ---------------------------------------


def find_build_data():
    """keepers' service-quality-analysis build_data.py: env override, this repo, then the plugin cache."""
    env = os.environ.get("LENS_SQA_BUILD_DATA")
    if env and os.path.exists(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "..", "..", "..", "skills", "service-quality-analysis", "scripts", "build_data.py")
    if os.path.exists(local):
        return os.path.realpath(local)
    cache = os.path.join(os.path.expanduser("~"), ".claude", "plugins")
    found = sorted(glob.glob(os.path.join(cache, "**", "service-quality-analysis", "scripts", "build_data.py"),
                             recursive=True))
    return found[-1] if found else None


def stage(side_dir, graph_path, workspace):
    """A stand-in checkout: the workspace's files (for line counts) plus the given graph."""
    os.makedirs(os.path.join(side_dir, "graphify-out"), exist_ok=True)
    for name in os.listdir(workspace):
        if name not in SKIP_LINKS and not os.path.exists(os.path.join(side_dir, name)):
            os.symlink(os.path.join(workspace, name), os.path.join(side_dir, name))
    target = os.path.join(side_dir, "graphify-out", "graph.json")
    if not os.path.exists(target):
        os.symlink(os.path.realpath(graph_path), target)


def sqa_deltas(base_path, live_path, workspace, workdir, build_data=None):
    """Before/after service-quality-analysis metrics for the whole repo, and which ones regressed.

    Both sides read line counts from the run's workspace, so LOC-weighted figures are approximate;
    the structural metrics compared here come from the import graphs alone.
    """
    build_data = build_data or find_build_data()
    if not build_data:
        return {"available": False, "reason": "service-quality-analysis build_data.py not found"}
    sides = {}
    for side, graph in (("base", base_path), ("live", live_path)):
        sides[side] = os.path.join(workdir, side)
        stage(sides[side], graph, workspace)
    config = os.path.join(workdir, "sqa-config.json")
    with open(config, "w") as f:
        json.dump({"title": "lens coherence", "subject": "live", "min_n_for_ranking": 1,
                   "units": [{"name": side, "repo": d, "root": ""} for side, d in sides.items()]}, f)
    out = os.path.join(workdir, "sqa-out")
    p = subprocess.run([sys.executable, "-B", build_data, "--config", config, "--out", out, "--no-go", "--no-churn"],
                       capture_output=True, text=True)
    data_path = os.path.join(out, "data.json")
    if p.returncode != 0 or not os.path.exists(data_path):
        return {"available": False, "reason": (p.stderr or p.stdout).strip()[-300:]}
    modules = load(data_path)["metrics"]["modules"]
    before, after = modules["base"], modules["live"]
    metrics, regressions = {}, []
    for key in SQA_METRICS:
        b, a = before.get(key), after.get(key)
        metrics[key] = {"before": b, "after": a}
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a > b:
            rel = (a - b) / b if b else 1.0
            if rel > SQA_REGRESSION:
                regressions.append({"metric": key, "before": round(b, 4), "after": round(a, 4),
                                    "worse_by": round(rel, 3)})
    return {"available": True, "metrics": metrics, "regressions": regressions}


def full_report(base_path, live_path, workspace, workdir, build_data=None):
    out = report(base_path, live_path)
    sqa = sqa_deltas(base_path, live_path, workspace, workdir, build_data)
    out["sqa"] = sqa
    for r in sqa.get("regressions", []):
        out["findings"].append(dict(r, signal="sqa_regression"))
    return out

"""Go-only enrichment for build_data.py.

Two things the graphify graph cannot supply for Go:
  - abstractness (interfaces / types per package), from a small go/ast helper
  - which imported packages the linker actually keeps and reaches, from
    `go build -ldflags=-dumpdep` (the "used" forest)

Both need a Go toolchain and a unit root that sits inside a buildable module.
Callers treat every failure here as "enrichment unavailable", never as fatal.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HELPER = Path(__file__).parent / "go" / "abstract.go"
BUILD_ENV = {"CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": "amd64"}

# Linker bookkeeping symbols attached to functions; they carry no call relationship.
AUX = re.compile(r"(\.arginfo\d+|\.argliveinfo|\.stkobj|\.opendefer|\.wrapinfo|\.args_stackmap|\.\.stmp_\d+|\.\.dict\..*|\.dict\..*)$")
SYM_PREFIXES = ("type:.eq.", "type:", "go:itab.", "go:info.", "go:funcval.", "go:string.")
PKG_PATH = re.compile(r"^/((?:[A-Za-z0-9_\-]+/)*[A-Za-z0-9_\-]+)\.")


def available(unit_root):
    """Return (ok, reason). ok means `go` is on PATH and unit_root is inside a module."""
    if not shutil.which("go"):
        return False, "go is not on PATH"
    try:
        module_info(unit_root)
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as ex:
        return False, f"not inside a Go module ({str(ex)[:80]})"
    return True, ""


def module_info(unit_root):
    out = subprocess.run(["go", "list", "-m", "-json"], cwd=unit_root, check=True, capture_output=True, text=True).stdout
    info = json.loads(out)
    return {"path": info["Path"], "dir": info["Dir"]}


def unit_import_path(unit_root):
    """Import path of the unit root, which may be a subdirectory of its module."""
    info = module_info(unit_root)
    sub = os.path.relpath(unit_root, info["dir"])
    return info["path"] if sub == "." else info["path"] + "/" + sub.replace(os.sep, "/")


def go_files(unit_root, tags=None):
    """Map package id to {"name", "go", "test"} file names exactly as `go list -e ./...` builds them."""
    cmd = ["go", "list", "-e", "-json"] + (["-tags", tags] if tags else []) + ["./..."]
    out = subprocess.run(cmd, cwd=unit_root, check=True, capture_output=True, text=True).stdout
    unit_import = unit_import_path(unit_root)
    dec, pos, listing = json.JSONDecoder(), 0, {}
    while pos < len(out):
        while pos < len(out) and out[pos].isspace():
            pos += 1
        if pos >= len(out):
            break
        p, pos = dec.raw_decode(out, pos)
        ip = p["ImportPath"]
        if ip == unit_import:
            pid = "(root)"
        elif ip.startswith(unit_import + "/"):
            pid = ip[len(unit_import) + 1:]
        else:
            continue
        listing[pid] = {"name": p.get("Name", ""), "go": p.get("GoFiles", []) + p.get("CgoFiles", []),
                        "test": p.get("TestGoFiles", []) + p.get("XTestGoFiles", [])}
    return listing


def abstract_counts(unit_root):
    """Map package id (relative to unit_root, '(root)' for the root) to {types, ifaces}."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "abstract")
        subprocess.run(["go", "build", "-o", exe, str(HELPER)], cwd=tmp, check=True, capture_output=True, text=True)
        out = subprocess.run([exe, str(unit_root)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _pkg_of(sym, unit_import, binary_id):
    if sym.startswith("main."):
        return binary_id
    s = sym
    for p in SYM_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    s = s.lstrip("*")
    if not s.startswith(unit_import):
        return None
    rest = s[len(unit_import):]
    if rest.startswith("."):
        return "(root)"
    m = PKG_PATH.match(rest)
    return m.group(1) if m else None


def _dump_binary(unit_root, entry_id, unit_import):
    """Build one entry point and return its symbol-reachability graph restricted to the unit."""
    target = "." if entry_id == "(root)" else "./" + entry_id
    env = {**os.environ, **BUILD_ENV}
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen(
            ["go", "build", "-trimpath", "-o", os.path.join(tmp, "bin"), "-ldflags=-dumpdep", target],
            cwd=unit_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        ids, names, pkgs, edges, noise = {}, [], [], set(), []

        def sid(sym, pkg):
            i = ids.get(sym)
            if i is None:
                i = ids[sym] = len(names)
                names.append(sym)
                pkgs.append(pkg)
            return i

        for line in proc.stderr:
            if " -> " not in line:
                noise.append(line.rstrip())
                continue
            a, b = line.rstrip("\n").split(" -> ", 1)
            pa = _pkg_of(a, unit_import, entry_id)
            pb = _pkg_of(b, unit_import, entry_id) if pa is not None else None
            if pa is None or pb is None:
                continue
            edges.add((sid(a, pa), sid(b, pb)))
        if proc.wait() != 0:
            raise RuntimeError(f"go build {target} failed: " + " | ".join(noise[-5:]))
    return {"names": names, "pkgs": pkgs, "edges": sorted(edges)}


def used_forest(unit_root, packages, binaries, workers=3):
    """Linker-reachability data for every entry point; None if any build fails.

    packages: id -> {"kind", "imports"}; binaries: entry id -> closure package ids.
    """
    unit_import = unit_import_path(unit_root)
    entries = sorted(binaries)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        dumps = dict(zip(entries, ex.map(lambda b: _dump_binary(unit_root, b, unit_import), entries)))
    return _assemble(packages, binaries, dumps)


def _assemble(packages, binaries, dumps):
    code = {k for k, p in packages.items() if p["kind"] == "code"}
    state_ids, state_pkg, state_bins, state_edges = {}, [], [], defaultdict(set)
    per_binary = {}

    def state_id(pkg, names):
        key = (pkg, frozenset(names))
        sid = state_ids.get(key)
        if sid is None:
            sid = state_ids[key] = len(state_pkg)
            state_pkg.append(pkg)
            state_bins.append(set())
        return sid

    for b in sorted(binaries):
        d = dumps[b]
        names, pk = d["names"], d["pkgs"]
        aux = [bool(AUX.search(n)) for n in names]
        edges = [(a, c) for a, c in d["edges"] if not aux[a] and not aux[c]]
        declared = {k: set(packages[k]["imports"]) for k in set(pk) if k in packages}
        out = defaultdict(list)
        for a, c in edges:
            out[a].append(c)
        closure = set(binaries[b])
        imports = {(s, t) for s in closure for t in packages[s]["imports"] if t in closure}
        pedges = {(pk[a], pk[c]) for a, c in edges
                  if pk[a] != pk[c] and (pk[a] in code or pk[a] == b) and pk[c] in declared.get(pk[a], ())}
        called = {p for e in pedges for p in e if p != b}
        linked = {k for k in set(pk) if k in code}
        clos_code = {x for x in closure if x in code}
        per_binary[b] = {
            "pkgs": sorted(called),
            "init_only": sorted((linked - called) & clos_code),
            "eliminated": sorted(clos_code - linked),
            "edges": [{"s": s, "t": t, "imp": (s, t) in imports} for s, t in sorted(pedges)],
        }

        def cross_children(pkg, entry):
            seen, stack, cross = set(entry), list(entry), defaultdict(set)
            while stack:
                u = stack.pop()
                for v in out[u]:
                    if pk[v] == pkg:
                        if v not in seen:
                            seen.add(v)
                            stack.append(v)
                    elif pk[v] in code and pk[v] in declared.get(pkg, ()):
                        cross[pk[v]].add(v)
            return cross

        start = {i for i, p in enumerate(pk) if p == b}
        root = state_id(b, [names[i] for i in start])
        state_bins[root].add(b)
        seen_states, stack = {root}, [(root, b, start)]
        while stack:
            sid, pkg, entry = stack.pop()
            for c, syms in cross_children(pkg, entry).items():
                cid = state_id(c, [names[i] for i in syms])
                state_bins[cid].add(b)
                state_edges[(sid, cid)].add(b)
                if cid not in seen_states:
                    seen_states.add(cid)
                    stack.append((cid, c, syms))

    return {
        "per_binary": per_binary,
        "states": [{"pkg": p, "bins": sorted(state_bins[i])} for i, p in enumerate(state_pkg)],
        "state_edges": [[a, c, sorted(bs)] for (a, c), bs in sorted(state_edges.items())],
    }

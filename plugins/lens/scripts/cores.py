"""Code lenses that manage the run workspace and the repo-level cores.

workspace: resolves the run's base and adds an isolated jj workspace.
graph-core: builds the central graphify graph at trunk, or moves it to trunk (init).
graph:     moves the central graph to the run's base and snapshots it per run.
cleanup:   forgets and deletes the run workspace.
core:      locates, resolves and promotes the user-approved markdown cores
           (conventions, contract-layers).

Every write to a core happens under the repo's graph/.lock flock.
"""
import contextlib
import fcntl
import json
import os
import shutil
import subprocess

CORE_WORKSPACE = "lens-graph-core"
CORE_FILES = {
    "conventions": ("code.md", "tests.md"),
    "contract-layers": ("contract-layers.md",),
}


class CoreError(Exception):
    pass


def run(cmd, cwd=None, env=None):
    merged = dict(os.environ, **(env or {}))
    p = subprocess.run(cmd, cwd=cwd, env=merged, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


runner = run


def must(cmd, cwd=None, env=None):
    code, out, err = runner(cmd, cwd=cwd, env=env)
    if code != 0:
        raise CoreError(f"{' '.join(cmd)} failed: {(err or out).strip()}")
    return out.strip()


def jj(repo, *args):
    return must(["jj", "--no-pager", "-R", repo, *args])


def commit_of(repo, rev):
    out = jj(repo, "log", "--no-graph", "-r", rev, "-T", 'commit_id ++ "\\n"')
    ids = out.split()
    if len(ids) != 1:
        raise CoreError(f"revision {rev!r} resolves to {len(ids)} commits")
    return ids[0]


def is_ancestor(repo, older, newer):
    out = jj(repo, "log", "--no-graph", "-r", f"{older} & ::{newer}", "-T", 'commit_id ++ "\\n"')
    return bool(out.split())


def repo_home(home, slug):
    return os.path.join(home, slug)


@contextlib.contextmanager
def locked(home, slug):
    folder = os.path.join(repo_home(home, slug), "graph")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, ".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_text(path):
    with open(path) as f:
        return f.read().strip()


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---- workspace -----------------------------------------------------------


def workspace_lens(run_dir, st, answers):
    """Resolve the base, ask about stale trunk bases, then add the workspace.

    A rewind re-runs this lens, so workspace.json is the record that the
    workspace is already created: reuse it, never add a second one.
    """
    repo = st["repo"]
    recorded = os.path.join(run_dir, "workspace.json")
    if os.path.exists(recorded):
        ws = read_json(recorded)
        if not os.path.isdir(ws["path"]):
            raise CoreError(f"workspace {ws['name']} is recorded but {ws['path']} is gone")
        return {"status": "done", "summary": f"workspace {ws['name']} already created, reused"}
    brief_base = os.path.join(run_dir, "brief", "base.json")
    base = st.get("base") or (read_json(brief_base).get("base") if os.path.exists(brief_base) else None) or "trunk()"
    base_commit = commit_of(repo, base)
    trunk_commit = commit_of(repo, "trunk()")
    if base_commit == trunk_commit:
        mode = "trunk"
    elif is_ancestor(repo, base_commit, trunk_commit):
        if not answers:
            return {"status": "needs_input", "question": {
                "question": f"The base {base} is an older trunk commit. Are you patching that "
                            "commit, or should the run move to the latest trunk?",
                "options": ["patch", "latest trunk"],
                "recommendation": "latest trunk",
            }}
        if answers[-1].startswith("latest"):
            mode, base, base_commit = "trunk", "trunk()", trunk_commit
        else:
            mode = "patch"
    else:
        mode = "branch"
    path = os.path.join(run_dir, "workspace")
    name = f"lens-{st['run_id']}"
    jj(repo, "workspace", "add", "--name", name, "-r", base_commit, path)
    change = jj(path, "log", "--no-graph", "-r", "@", "-T", "change_id")
    write_json(os.path.join(run_dir, "workspace.json"), {
        "path": path, "name": name, "base": base, "base_commit": base_commit,
        "mode": mode, "change_id": change,
    })
    return {"status": "done", "summary": f"workspace {name} on {base_commit[:12]} ({mode})"}


# ---- graph ---------------------------------------------------------------


def graphify_update(target, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    must(["graphify", "update", target], env={"GRAPHIFY_OUT": out_dir})


def graph_paths(home, slug):
    root = os.path.join(repo_home(home, slug), "graph")
    return {
        "root": root,
        "ws": os.path.join(root, "core", "workspace"),
        "out": os.path.join(root, "core", "out"),
        "commit": os.path.join(root, "core", "commit"),
    }


def core_graph_present(home, slug):
    p = graph_paths(home, slug)
    return os.path.exists(p["commit"]) and os.path.exists(os.path.join(p["out"], "graph.json"))


def missing_cores(home, slug):
    """Names of the cores a run needs that are not built yet."""
    missing = []
    if not core_graph_present(home, slug):
        missing.append("graph")
    for kind in ("conventions", "contract-layers"):
        if not core_exists(home, slug, kind):
            missing.append(kind)
    return missing


def advance_core_graph(repo, paths, target):
    """Move the core graph workspace to target and rebuild the graph. Caller holds the lock."""
    if not os.path.isdir(paths["ws"]):
        os.makedirs(os.path.dirname(paths["ws"]), exist_ok=True)
        jj(repo, "workspace", "add", "--name", CORE_WORKSPACE, "-r", "trunk()", paths["ws"])
    jj(paths["ws"], "new", target)
    graphify_update(paths["ws"], paths["out"])
    with open(paths["commit"], "w") as f:
        f.write(target + "\n")


def graph_core_lens(st, home):
    """Init: build the core graph at trunk, or move a present one forward to trunk."""
    repo, slug = st["repo"], st["repo_slug"]
    paths = graph_paths(home, slug)
    with locked(home, slug):
        trunk = commit_of(repo, "trunk()")
        current = read_text(paths["commit"]) if core_graph_present(home, slug) else None
        if current == trunk:
            return {"status": "done", "summary": f"core graph already at {trunk[:12]}"}
        if current is not None and not is_ancestor(repo, current, trunk):
            return {"status": "done", "summary": f"core graph at {current[:12]} is not behind trunk, left as is"}
        advance_core_graph(repo, paths, trunk)
    how = "built" if current is None else "advanced"
    return {"status": "done", "summary": f"{how} core graph at {trunk[:12]}"}


def graph_lens(run_dir, st, home):
    """Bring the core graph to the run's base when the run is newer, then snapshot it.

    The core graph is built by init. A run that finds none halts.
    """
    ws = read_json(os.path.join(run_dir, "workspace.json"))
    slug = st["repo_slug"]
    paths = graph_paths(home, slug)
    snap = os.path.join(paths["root"], "snapshots", st["run_id"])
    with locked(home, slug):
        if not core_graph_present(home, slug):
            raise CoreError("the core graph is missing; run /lens:init")
        core_commit = read_text(paths["commit"])
        base = ws["base_commit"]
        update_core = ws["mode"] == "trunk" and base != core_commit and is_ancestor(st["repo"], core_commit, base)
        if update_core:
            advance_core_graph(st["repo"], paths, base)
            core_commit = base
        if os.path.exists(snap):
            shutil.rmtree(snap)
        shutil.copytree(paths["out"], os.path.join(snap, "base"))
    if core_commit != base:
        graphify_update(ws["path"], os.path.join(snap, "base"))
    shutil.copytree(os.path.join(snap, "base"), os.path.join(snap, "live"))
    write_json(os.path.join(run_dir, "snapshot.json"), {
        "base": os.path.join(snap, "base", "graph.json"),
        "live": os.path.join(snap, "live", "graph.json"),
        "live_out": os.path.join(snap, "live"),
        "core_commit": core_commit,
    })
    how = "updated core, " if update_core else ""
    return {"status": "done", "summary": f"{how}snapshot at {base[:12]} ({ws['mode']})"}


def refresh_live(run_dir):
    """Code-only refresh of the run's live snapshot from its workspace."""
    ws = read_json(os.path.join(run_dir, "workspace.json"))
    snap = read_json(os.path.join(run_dir, "snapshot.json"))
    graphify_update(ws["path"], snap["live_out"])


# ---- cleanup -------------------------------------------------------------


def cleanup_lens(run_dir, st):
    path = os.path.join(run_dir, "workspace.json")
    if not os.path.exists(path):
        return {"status": "done", "summary": "no workspace to clean up"}
    ws = read_json(path)
    jj(st["repo"], "workspace", "forget", ws["name"])
    if os.path.isdir(ws["path"]):
        shutil.rmtree(ws["path"])
    return {"status": "done", "summary": f"forgot and removed workspace {ws['name']}"}


# ---- markdown cores ------------------------------------------------------


def core_dirs(home, slug, kind):
    """Map of scope -> directory holding that scope's core files."""
    base = repo_home(home, slug)
    sub = "conventions" if kind == "conventions" else ""
    found = {}
    repo_dir = os.path.join(base, sub) if sub else base
    if all(os.path.exists(os.path.join(repo_dir, f)) for f in CORE_FILES[kind]):
        found["repo"] = repo_dir
    services = os.path.join(base, "services")
    if os.path.isdir(services):
        for svc in sorted(os.listdir(services)):
            d = os.path.join(services, svc, sub) if sub else os.path.join(services, svc)
            if any(os.path.exists(os.path.join(d, f)) for f in CORE_FILES[kind]):
                found[f"services/{svc}"] = d
    return found


def core_exists(home, slug, kind):
    return bool(core_dirs(home, slug, kind))


def service_roots(home, slug):
    services = os.path.join(repo_home(home, slug), "services")
    roots = {}
    if os.path.isdir(services):
        for svc in os.listdir(services):
            p = os.path.join(services, svc, "root.txt")
            if os.path.exists(p):
                roots[svc] = read_text(p).strip("/")
    return roots


def resolve(home, slug, kind, paths):
    """Core files that apply to the given repo-relative paths, service first."""
    dirs = core_dirs(home, slug, kind)
    roots = service_roots(home, slug)
    files = []
    for path in paths:
        for svc, root in sorted(roots.items(), key=lambda x: -len(x[1])):
            if path == root or path.startswith(root + "/"):
                d = dirs.get(f"services/{svc}")
                if d:
                    files += [os.path.join(d, f) for f in CORE_FILES[kind]]
                break
    if "repo" in dirs:
        files += [os.path.join(dirs["repo"], f) for f in CORE_FILES[kind]]
    seen = []
    for f in files:
        if os.path.exists(f) and f not in seen:
            seen.append(f)
    return seen


def promote(run_dir, home, slug, kind):
    """Copy the run's approved pending core into the repo core, under the lock."""
    pending = os.path.join(run_dir, "pending", kind)
    if not os.path.isdir(pending):
        raise CoreError(f"nothing pending for {kind} in {pending}")
    base = repo_home(home, slug)
    sub = "conventions" if kind == "conventions" else ""
    moved = []
    with locked(home, slug):
        for scope in sorted(os.listdir(pending)):
            src = os.path.join(pending, scope)
            if scope == "repo":
                dest = os.path.join(base, sub) if sub else base
                moved += copy_core_files(src, dest, kind)
            elif scope == "services":
                for svc in sorted(os.listdir(src)):
                    svc_src = os.path.join(src, svc)
                    svc_dir = os.path.join(base, "services", svc)
                    dest = os.path.join(svc_dir, sub) if sub else svc_dir
                    moved += copy_core_files(svc_src, dest, kind)
                    root = os.path.join(svc_src, "root.txt")
                    if os.path.exists(root):
                        os.makedirs(svc_dir, exist_ok=True)
                        shutil.copy(root, os.path.join(svc_dir, "root.txt"))
    shutil.rmtree(pending)
    return moved


def copy_core_files(src, dest, kind):
    moved = []
    for f in CORE_FILES[kind]:
        p = os.path.join(src, f)
        if os.path.exists(p):
            os.makedirs(dest, exist_ok=True)
            shutil.copy(p, os.path.join(dest, f))
            moved.append(os.path.join(dest, f))
    return moved

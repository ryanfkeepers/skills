"""The build grid: tasks x build lenses, scheduled from tasks/*.json.

A task's cells run in lens order (scaffold, implement, unit-test,
test-coverage). A task starts only after every task in its blocked_by has
settled. Ready cells from different tasks run at the same time in the run's
single workspace, unless their tasks share a file in shared_files. After each
cell, the files it changed must be a subset of what that cell may touch;
anything else is restored and the cell fails. A failed cell is retried alone,
and a retry that passes alone counts as a spurious failure.
"""
import fnmatch
import json
import os

import cores

TEST_PATTERNS = ("*_test.go", "test_*.py", "*_test.py", "*.test.*", "*.spec.*")
TEST_DIRS = ("testdata/", "tests/", "__tests__/", "mocks/", "fakes/")
WRITES = {"scaffold": "code", "implement": "code", "unit-test": "tests", "test-coverage": None}


def load_tasks(run):
    folder = os.path.join(run, "tasks")
    tasks = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            with open(os.path.join(folder, name)) as f:
                t = json.load(f)
            tasks[t["id"]] = t
    return tasks


def target_files(task):
    return sorted({t.split("#", 1)[0] for t in task.get("target", [])})


def is_test(path):
    base = os.path.basename(path)
    return any(fnmatch.fnmatch(base, p) for p in TEST_PATTERNS) or any(d in path for d in TEST_DIRS)


def fresh_cell():
    return {"status": "pending", "attempts": 0, "solo": False, "concurrent": False,
            "start_commit": None, "started_at": None, "ended_at": None, "respawn": False}


def init(run, st, cells):
    tasks = load_tasks(run)
    if not tasks:
        raise cores.CoreError("plan wrote no tasks/*.json")
    for tid, t in tasks.items():
        for dep in t.get("blocked_by", []):
            if dep not in tasks:
                raise cores.CoreError(f"task {tid} is blocked by unknown task {dep}")
    st["grid"] = {
        "cells": cells,
        "spurious": 0,
        "tasks": {tid: {
            "targets": target_files(t),
            "shared": sorted(set(t.get("shared_files", []))),
            "blocked_by": t.get("blocked_by", []),
            "coverage_rounds": 0,
            "cells": {c: fresh_cell() for c in cells},
        } for tid, t in tasks.items()},
    }


def settled(task):
    return all(c["status"] == "done" for c in task["cells"].values())


def running(grid):
    return [(tid, lens) for tid, t in grid["tasks"].items()
            for lens, c in t["cells"].items() if c["status"] in ("running", "needs_input")]


def next_cell(grid, task):
    for lens in grid["cells"]:
        if task["cells"][lens]["status"] != "done":
            return lens
    return None


def ready(grid, max_agents):
    """Cells that may start now, in task order."""
    busy = running(grid)
    if any(grid["tasks"][tid]["cells"][lens]["solo"] for tid, lens in busy):
        return []
    busy_shared = set()
    for tid, _ in busy:
        busy_shared |= set(grid["tasks"][tid]["shared"])
    out = []
    for tid, task in grid["tasks"].items():
        if len(busy) + len(out) >= max_agents:
            break
        if any(t == tid for t, _ in busy):
            continue
        if not all(settled(grid["tasks"][d]) for d in task["blocked_by"]):
            continue
        lens = next_cell(grid, task)
        if lens is None or task["cells"][lens]["status"] != "pending":
            continue
        cell = task["cells"][lens]
        if cell["solo"]:
            if busy or out:
                continue
            return [(tid, lens)]
        if busy_shared & set(task["shared"]):
            continue
        busy_shared |= set(task["shared"])
        out.append((tid, lens))
    return out


def commit_of_workspace(ws_path):
    return cores.jj(ws_path, "log", "--no-graph", "-r", "@", "-T", "commit_id")


def changed_files(ws_path, start, end):
    """Workspace-relative paths changed between two commits (jj prints paths relative to cwd)."""
    out = cores.must(["jj", "--no-pager", "diff", "--from", start, "--to", end, "--name-only"], cwd=ws_path)
    return [l for l in out.splitlines() if l.strip()]


def restore(ws_path, start, files):
    cores.must(["jj", "--no-pager", "restore", "--from", start, *files], cwd=ws_path)


def allowed(grid, tid, lens, concurrent_tids):
    """Files this cell may have changed, plus files cells running beside it may have changed."""
    task = grid["tasks"][tid]
    mine = set()
    kind = WRITES.get(lens)
    for f in task["targets"] + task["shared"]:
        if kind == "code" and not is_test(f):
            mine.add(f)
    others = set()
    for other in concurrent_tids:
        t = grid["tasks"][other]
        others |= set(t["targets"]) | set(t["shared"])
    return kind, mine, others


def out_of_bounds(grid, tid, lens, files, concurrent_tids):
    kind, mine, others = allowed(grid, tid, lens, concurrent_tids)
    task_dirs = {os.path.dirname(f) for f in grid["tasks"][tid]["targets"]}
    bad = []
    for f in files:
        if f in others:
            continue
        if kind == "code" and f in mine:
            continue
        if kind == "tests" and is_test(f) and (os.path.dirname(f) in task_dirs or any(d in f for d in TEST_DIRS)):
            continue
        bad.append(f)
    return bad

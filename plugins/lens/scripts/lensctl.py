"""State machine for a lens run.

The orchestrator skill only coordinates: it asks `next` what to do, dispatches
the named lens as a sub-agent, and reports back with `record`. Every decision
about ordering, retries, relayed questions, disputes, rewinds and the final
report lives here, in code. Runs live under ~/.claude/lens/<repo-slug>/<run-id>/
(override the root with LENS_HOME), never inside the repo.

All output is compact JSON.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time

import coherence
import cores
import grid
import settle

PIPELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline.json")
DONE_STATES = ("done", "skipped")
SUMMARY_MAX_LINES = 10

now = time.time


class LensError(Exception):
    pass


# ---- paths ---------------------------------------------------------------


def lens_home():
    return os.environ.get("LENS_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "lens")


def repo_slug(repo):
    repo = os.path.realpath(repo)
    digest = hashlib.sha256(repo.encode()).hexdigest()[:8]
    return f"{os.path.basename(repo)}-{digest}"


def status_path(run):
    return os.path.join(run, "status.json")


def qa_path(run, lens):
    return os.path.join(run, "qa", f"{lens}.jsonl")


# ---- json io -------------------------------------------------------------


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    os.replace(tmp, path)


def load(run):
    path = status_path(run)
    if not os.path.exists(path):
        raise LensError(f"no run at {run}")
    return read_json(path)


def save(run, st):
    write_json(status_path(run), st)


# ---- lookups -------------------------------------------------------------


def entry(st, lens):
    for e in st["pipeline"]["lenses"]:
        if e["name"] == lens:
            return e
    raise LensError(f"unknown lens {lens!r}")


def index_of(st, lens):
    entry(st, lens)
    return st["order"].index(lens)


def pending_question(run, lens):
    for row in read_jsonl(qa_path(run, lens)):
        if row.get("answer") is None:
            return row
    return None


# ---- init ----------------------------------------------------------------


def cmd_init(repo, proposal, pipeline_path=PIPELINE, base=None, only=None):
    repo = os.path.realpath(repo)
    if not os.path.isdir(repo):
        raise LensError(f"repo {repo} is not a directory")
    pipeline = read_json(pipeline_path)
    if only:
        pipeline["lenses"] = [e for e in pipeline["lenses"] if e["name"] == only]
        if not pipeline["lenses"]:
            raise LensError(f"unknown lens {only!r}")
    run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now())) + "-" + secrets.token_hex(2)
    run = os.path.join(lens_home(), repo_slug(repo), run_id)
    for sub in ("qa", "disputes", "summaries"):
        os.makedirs(os.path.join(run, sub))
    with open(os.path.join(run, "proposal.txt"), "w") as f:
        f.write(proposal)
    order = [e["name"] for e in pipeline["lenses"]]
    st = {
        "run_id": run_id,
        "repo": repo,
        "repo_slug": repo_slug(repo),
        "created_at": now(),
        "pipeline": pipeline,
        "order": order,
        "lenses": {name: fresh_lens() for name in order},
        "halt": None,
        "disputes": [],
        "rewinds": [],
        "base": base,
        "refresh": bool(only),
    }
    save(run, st)
    return {"run_id": run_id, "run": run}


def fresh_lens():
    return {"status": "pending", "attempts": 0, "started_at": None,
            "ended_at": None, "respawn": False, "note": None}


# ---- next ----------------------------------------------------------------


def cmd_next(run):
    st = load(run)
    if st["halt"]:
        return {"action": "halt", **st["halt"]}
    for name in st["order"]:
        lens = st["lenses"][name]
        if lens["status"] in DONE_STATES:
            continue
        e = entry(st, name)
        if lens["status"] == "pending" and not e.get("implemented"):
            lens.update(status="skipped", note="not implemented")
            continue
        reuse = e.get("reuse_core")
        if lens["status"] == "pending" and reuse and not st.get("refresh") \
                and cores.core_exists(lens_home(), st["repo_slug"], reuse):
            lens.update(status="done", note="reused core")
            continue
        if lens["status"] == "pending" and e.get("scope") == "code":
            out = run_code_lens(run, st, name)
            if out:
                return out
            continue
        if e.get("scope") == "grid":
            out = grid_next(run, st, name)
            if out:
                return out
            continue
        if e.get("scope") == "settle":
            out = settle_next(run, st, name)
            if out:
                return out
            continue
        if e.get("scope") == "parallel":
            out = parallel_next(run, st, name)
            if out:
                return out
            continue
        if e.get("scope") == "sleep":
            if lens["status"] == "pending":
                lens.update(status="running", attempts=1, started_at=now())
                save(run, st)
                return {"action": "sleep", "lens": name, "seconds": e.get("seconds", 300)}
            save(run, st)
            return {"action": "wait", "running": [name]}
        if lens["status"] == "needs_input":
            save(run, st)
            return {"action": "relay", "lens": name,
                    "question": pending_question(run, name), "respawn": lens["respawn"]}
        if lens["status"] == "running":
            save(run, st)
            return {"action": "wait", "running": [name]}
        lens.update(status="running", attempts=lens["attempts"] + 1,
                    started_at=now(), respawn=False)
        save(run, st)
        return {"action": "dispatch", "lens": name, "agent": f"lens:{e.get('agent', name)}",
                "run": run, "attempt": lens["attempts"]}
    save(run, st)
    return {"action": "done"}


def run_code_lens(run, st, name):
    """Run a lens implemented in code. Returns a relay action when it asks."""
    state = st["lenses"][name]
    state.update(attempts=state["attempts"] + 1, started_at=state["started_at"] or now())
    save(run, st)
    answers = [r["answer"] for r in read_jsonl(qa_path(run, name)) if r.get("answer") is not None]
    try:
        out = CODE_LENSES[name](run, st, answers)
    except cores.CoreError as err:
        st = load(run)
        st["halt"] = {"lens": name, "reason": str(err)}
        st["lenses"][name]["status"] = "failed"
        save(run, st)
        return {"action": "halt", **st["halt"]}
    st.update(load(run))
    state = st["lenses"][name]
    if out["status"] == "needs_input":
        q = dict(out["question"], answer=None, asked_at=now())
        rows = read_jsonl(qa_path(run, name)) + [q]
        write_jsonl(qa_path(run, name), rows)
        state["status"] = "needs_input"
        save(run, st)
        return {"action": "relay", "lens": name, "question": q, "respawn": False}
    write_summary(run, name, out.get("summary", ""))
    state.update(status="done", ended_at=now())
    save(run, st)
    return None


def code_report(run, st, answers):
    st["lenses"]["run-report"].update(status="done", ended_at=now())
    save(run, st)
    build_report(run, st)
    return {"status": "done", "summary": "report written"}


def code_apply_descriptions(run, st, answers):
    """Apply each slice's description one at a time, so jj never runs concurrently."""
    ws = read_json(os.path.join(run, "workspace.json"))["path"]
    slices = read_json(os.path.join(run, "stack.json")).get("slices", [])
    done = 0
    for sl in slices:
        path = os.path.join(run, "descriptions", f"{sl['change_id']}.txt")
        if not os.path.exists(path):
            raise cores.CoreError(f"no description for slice {sl['change_id']}")
        with open(path) as f:
            text = f.read().strip()
        cores.must(["jj", "--no-pager", "describe", "-r", sl["change_id"], "-m", text], cwd=ws)
        done += 1
    return {"status": "done", "summary": f"described {done} revision(s)"}


CODE_LENSES = {
    "apply-descriptions": code_apply_descriptions,
    "workspace": lambda run, st, answers: cores.workspace_lens(run, st, answers),
    "graph": lambda run, st, answers: cores.graph_lens(run, st, lens_home()),
    "cleanup": lambda run, st, answers: cores.cleanup_lens(run, st),
    "run-report": code_report,
}


# ---- build grid ----------------------------------------------------------


def unit_key(lens, task):
    return f"{lens}-{task}" if task else lens


def grid_next(run, st, name):
    """One action for the grid, or None once every task has settled."""
    state = st["lenses"][name]
    try:
        if not st.get("grid"):
            grid.init(run, st, entry(st, name)["cells"])
            state.update(status="running", attempts=1, started_at=now())
        g = st["grid"]
        for tid, task in g["tasks"].items():
            for lens, cell in task["cells"].items():
                if cell["status"] == "needs_input":
                    save(run, st)
                    return {"action": "relay", "lens": lens, "task": tid,
                            "question": pending_question(run, unit_key(lens, tid)), "respawn": cell["respawn"]}
        cells = grid.ready(g, st["pipeline"].get("max_agents", 32))
        if cells:
            tid, lens = cells[0]
            return grid_dispatch(run, st, tid, lens)
        busy = grid.running(g)
        if busy:
            save(run, st)
            return {"action": "wait", "running": [unit_key(lens, tid) for tid, lens in busy]}
        if all(grid.settled(t) for t in g["tasks"].values()):
            state.update(status="done", ended_at=now())
            save(run, st)
            return None
        stuck = [tid for tid, t in g["tasks"].items() if not grid.settled(t)]
        raise cores.CoreError(f"grid cannot progress; unsettled tasks {stuck} (check blocked_by for cycles)")
    except cores.CoreError as err:
        st["halt"] = {"lens": name, "reason": str(err)}
        state["status"] = "failed"
        save(run, st)
        return {"action": "halt", **st["halt"]}


def grid_dispatch(run, st, tid, lens):
    g = st["grid"]
    ws = read_json(os.path.join(run, "workspace.json"))["path"]
    busy = [t for t, _ in grid.running(g)]
    cell = g["tasks"][tid]["cells"][lens]
    cell.update(status="running", attempts=cell["attempts"] + 1, started_at=now(), respawn=False,
                start_commit=grid.commit_of_workspace(ws), concurrent=bool(busy), overlap=sorted(set(busy)))
    for other, other_lens in grid.running(g):
        if other != tid:
            o = g["tasks"][other]["cells"][other_lens]
            o["overlap"] = sorted(set(o.get("overlap", [])) | {tid})
    save(run, st)
    return {"action": "dispatch", "lens": lens, "task": tid, "agent": f"lens:{lens}",
            "run": run, "attempt": cell["attempts"]}


def grid_record(run, st, lens, task, status, summary):
    g = st.get("grid")
    if not g or task not in g["tasks"] or lens not in g["tasks"][task]["cells"]:
        raise LensError(f"no grid cell {lens} for task {task}")
    cell = g["tasks"][task]["cells"][lens]
    if cell["status"] not in ("running", "needs_input"):
        raise LensError(f"cell {lens} for {task} is {cell['status']}, not running")
    key = unit_key(lens, task)
    if status == "needs_input":
        rows = read_jsonl(qa_path(run, key))
        open_rows = [r for r in rows if r.get("answer") is None]
        if not open_rows:
            raise LensError(f"cell {key} reported needs_input with no open question in qa/{key}.jsonl")
        open_rows[0].setdefault("asked_at", now())
        write_jsonl(qa_path(run, key), rows)
        cell["status"] = "needs_input"
        save(run, st)
        return {"lens": lens, "task": task, "status": "needs_input"}
    if status == "blocked":
        save(run, st)
        return route_cell_dispute(run, lens, task)
    if status == "done":
        ws = read_json(os.path.join(run, "workspace.json"))["path"]
        end = grid.commit_of_workspace(ws)
        files = grid.changed_files(ws, cell["start_commit"], end)
        bad = grid.out_of_bounds(g, task, lens, files, cell.get("overlap", []))
        if bad:
            grid.restore(ws, cell["start_commit"], bad)
            status, summary = "failed", f"changed files outside its bounds (restored): {', '.join(bad)}"
    if status == "done":
        write_summary(run, key, summary)
        if cell["solo"] and cell.get("failed_concurrent"):
            g["spurious"] += 1
        cell.update(status="done", ended_at=now())
        if lens == "test-coverage":
            coverage_round(run, g, task)
    elif status == "failed":
        cell["failed_concurrent"] = bool(cell.get("overlap"))
        if cell["attempts"] > st["pipeline"].get("retries", 1):
            st["halt"] = {"lens": key, "reason": summary.strip() or "failed"}
            cell["status"] = "failed"
        else:
            cell.update(status="pending", solo=True)
    else:
        raise LensError(f"unknown status {status!r}")
    save(run, st)
    return {"lens": lens, "task": task, "status": cell["status"], "halt": st["halt"]}


def coverage_round(run, g, task):
    """Uncovered branches go back to unit-test once; leftovers stay in the report."""
    path = os.path.join(run, "coverage", f"{task}.json")
    gaps = read_json(path).get("gaps", []) if os.path.exists(path) else []
    t = g["tasks"][task]
    if gaps and t["coverage_rounds"] == 0:
        t["coverage_rounds"] = 1
        for lens in ("unit-test", "test-coverage"):
            if lens in t["cells"]:
                t["cells"][lens] = dict(grid.fresh_cell(), attempts=0)


def route_cell_dispute(run, lens, task):
    st = load(run)
    g = st["grid"]
    key = unit_key(lens, task)
    files = unrouted_disputes(run, st, key)
    if not files:
        raise LensError(f"cell {key} reported blocked with no new file in disputes/")
    order = g["cells"]
    reset_from = None
    for name in files:
        d = read_json(os.path.join(run, "disputes", name))
        target = d.get("target_lens")
        st["disputes"].append({"file": name, "from": key, "target": target, "at": now()})
        if target in order and order.index(target) <= order.index(lens):
            i = order.index(target)
            reset_from = i if reset_from is None else min(reset_from, i)
            continue
        if target in st["order"] and index_of(st, target) < index_of(st, "build"):
            save(run, st)
            return rewind(run, target, reason=f"dispute from {key}")
        st["halt"] = {"lens": key, "reason": f"dispute {name} targets {target!r}, which it cannot route to"}
        g["tasks"][task]["cells"][lens]["status"] = "failed"
        save(run, st)
        return {"lens": lens, "task": task, "status": "failed", "halt": st["halt"]}
    for name in order[reset_from:]:
        g["tasks"][task]["cells"][name] = grid.fresh_cell()
    save(run, st)
    return {"lens": lens, "task": task, "status": "pending", "reset_from": order[reset_from]}


# ---- settlement ----------------------------------------------------------


def settle_next(run, st, name):
    """One action for a settling lens group, or None once both passes settle."""
    state = st["lenses"][name]
    e = entry(st, name)
    try:
        if not (st.get("settle") or {}).get(name):
            settle.init(run, st, name, e)
            state.update(status="running", attempts=1, started_at=now())
        out = settle.next_action(run, st, name, e, st["pipeline"].get("max_agents", 32))
    except cores.CoreError as err:
        st["halt"] = {"lens": name, "reason": str(err)}
        state["status"] = "failed"
        save(run, st)
        return {"action": "halt", **st["halt"]}
    if out is None:
        state.update(status="done", ended_at=now())
        save(run, st)
        return None
    if out["action"] == "relay":
        u = st["settle"][name]["units"][out["unit"]]
        out["question"] = u["question"] if u["kind"] == "decision" else pending_question(run, out["unit"])
    if out["action"] == "dispatch":
        out["run"] = run
    out["group"] = name
    save(run, st)
    return out


def parallel_next(run, st, name):
    """Independent lenses that run side by side; done when all of them are."""
    state = st["lenses"][name]
    e = entry(st, name)
    group = st.setdefault("settle", {}).get(name)
    if not group:
        if e.get("per_slice"):
            slices = read_json(os.path.join(run, "stack.json")).get("slices", [])
            units = {f"{e['lenses'][0]}-{i + 1}": settle.new_unit(e["lenses"][0], "review",
                                                                 {"change_id": sl["change_id"], "slice": i + 1})
                     for i, sl in enumerate(slices)}
        else:
            units = {lens: settle.new_unit(lens, "review", {}) for lens in e["lenses"]}
        group = {"pass": "parallel", "epochs": [], "untriaged": [], "items": {}, "seq": 0, "new_findings": 0,
                 "units": units}
        st["settle"][name] = group
        state.update(status="running", attempts=1, started_at=now())
    for key, u in group["units"].items():
        if u["status"] == "needs_input":
            save(run, st)
            return {"action": "relay", "lens": u["lens"], "unit": key, "group": name,
                    "question": pending_question(run, key), "respawn": u["respawn"]}
    for key, u in group["units"].items():
        if u["status"] == "pending":
            out = dict(settle.dispatch(group, key), run=run, group=name)
            save(run, st)
            return out
    busy = [k for k, u in group["units"].items() if u["status"] == "running"]
    if busy:
        save(run, st)
        return {"action": "wait", "running": busy}
    state.update(status="done", ended_at=now())
    save(run, st)
    return None


def settle_unit(st, unit):
    for name, s in (st.get("settle") or {}).items():
        if unit in s["units"]:
            return name, s["units"][unit]
    raise LensError(f"no settle unit {unit!r}")


def settle_record(run, st, unit, status, summary):
    name, u = settle_unit(st, unit)
    if u["status"] not in ("running", "needs_input"):
        raise LensError(f"unit {unit} is {u['status']}, not running")
    e = entry(st, name)
    out = {}
    if status == "done" and e.get("scope") == "parallel":
        write_summary(run, unit, summary)
        u["status"] = "done"
    elif status == "done":
        write_summary(run, unit, summary)
        try:
            out = settle.record_done(run, st, name, e, unit)
        except cores.CoreError as err:
            out = {"halt": str(err)}
    elif status == "failed":
        out = settle.record_failed(st, name, unit, st["pipeline"].get("retries", 1))
    elif status == "needs_input":
        rows = read_jsonl(qa_path(run, unit))
        open_rows = [r for r in rows if r.get("answer") is None]
        if not open_rows:
            raise LensError(f"unit {unit} reported needs_input with no open question in qa/{unit}.jsonl")
        open_rows[0].setdefault("asked_at", now())
        write_jsonl(qa_path(run, unit), rows)
        u["status"] = "needs_input"
    elif status == "blocked":
        save(run, st)
        return route_dispute(run, unit, at=name)
    else:
        raise LensError(f"unknown status {status!r}")
    if out.get("halt"):
        st["halt"] = {"lens": unit, "reason": out["halt"]}
    save(run, st)
    return dict({"unit": unit, "status": u["status"], "halt": st["halt"]}, **{k: v for k, v in out.items() if k != "halt"})


def settle_answer(run, st, unit, answer):
    name, u = settle_unit(st, unit)
    if u["status"] != "needs_input":
        raise LensError(f"unit {unit} is {u['status']}, not waiting for input")
    if u["kind"] == "decision":
        u["question"]["answered_at"] = now()
        out = settle.answer_decision(st["settle"][name], unit, answer)
        append_gate(run, unit, u["question"])
        if out.get("halt"):
            st["halt"] = {"lens": unit, "reason": out["halt"]}
        save(run, st)
        return {"unit": unit, "continue": "next"}
    answer_row(run, unit, answer)
    respawn = u["respawn"]
    u.update(status="running", respawn=False)
    save(run, st)
    return {"unit": unit, "continue": "respawn" if respawn else "send_message"}


def append_gate(run, unit, question):
    """Decisions lensctl asks itself are logged as qa rows so the report counts them."""
    rows = read_jsonl(qa_path(run, unit)) + [question]
    write_jsonl(qa_path(run, unit), rows)


# ---- record --------------------------------------------------------------


def cmd_record(run, lens, status, summary="", task=None, unit=None):
    st = load(run)
    if unit:
        return settle_record(run, st, unit, status, summary)
    if task:
        return grid_record(run, st, lens, task, status, summary)
    entry(st, lens)
    state = st["lenses"][lens]
    if state["status"] not in ("running", "needs_input"):
        raise LensError(f"lens {lens} is {state['status']}, not running")
    if status == "done":
        write_summary(run, lens, summary)
        state.update(status="done", ended_at=now())
    elif status == "needs_input":
        rows = read_jsonl(qa_path(run, lens))
        open_rows = [r for r in rows if r.get("answer") is None]
        if not open_rows:
            raise LensError(f"lens {lens} reported needs_input with no open question in qa/{lens}.jsonl")
        open_rows[0].setdefault("asked_at", now())
        write_jsonl(qa_path(run, lens), rows)
        state["status"] = "needs_input"
    elif status == "failed":
        state["note"] = summary.strip() or None
        if state["attempts"] > st["pipeline"].get("retries", 1):
            st["halt"] = {"lens": lens, "reason": summary.strip() or "failed"}
            state["status"] = "failed"
        else:
            state["status"] = "pending"
    elif status == "blocked":
        save(run, st)
        return route_dispute(run, lens)
    else:
        raise LensError(f"unknown status {status!r}")
    save(run, st)
    return {"lens": lens, "status": state["status"], "halt": st["halt"]}


def write_summary(run, lens, summary):
    lines = summary.strip().splitlines()
    if len(lines) > SUMMARY_MAX_LINES:
        lines = lines[:SUMMARY_MAX_LINES - 1] + [f"... ({len(lines) - SUMMARY_MAX_LINES + 1} lines cut)"]
    with open(os.path.join(run, "summaries", f"{lens}.txt"), "w") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


# ---- disputes ------------------------------------------------------------


def unrouted_disputes(run, st, lens):
    routed = {d["file"] for d in st["disputes"]}
    folder = os.path.join(run, "disputes")
    pattern = re.compile(rf"^{re.escape(lens)}-\d+\.json$")
    return sorted(n for n in os.listdir(folder) if pattern.match(n) and n not in routed)


def route_dispute(run, lens, at=None):
    st = load(run)
    files = unrouted_disputes(run, st, lens)
    if not files:
        raise LensError(f"lens {lens} reported blocked with no new file in disputes/")
    here = index_of(st, at or lens)
    targets, cells = [], []
    for name in files:
        d = read_json(os.path.join(run, "disputes", name))
        target = d.get("target_lens")
        cell = grid_cell_target(st, target, d.get("task"), here)
        if cell:
            st["disputes"].append({"file": name, "from": lens, "target": unit_key(*cell), "at": now()})
            cells.append(cell)
            continue
        if target not in st["order"] or index_of(st, target) >= here and not (at is None and target == lens):
            st["halt"] = {"lens": lens, "reason": f"dispute {name} targets {target!r}, not an earlier lens"}
            st["lenses"][at or lens]["status"] = "failed"
            save(run, st)
            return {"lens": lens, "status": "failed", "halt": st["halt"]}
        st["disputes"].append({"file": name, "from": lens, "target": target, "at": now()})
        targets.append(target)
    if targets:
        earliest = min(targets, key=lambda t: index_of(st, t))
        save(run, st)
        return rewind(run, earliest, reason=f"dispute from {lens}")
    save(run, st)
    return recheck_cells(run, cells, reason=f"dispute from {lens}")


def grid_cell_target(st, target, task, here):
    """(cell lens, task) when a dispute names one task's build cell, from a lens after the grid."""
    g = st.get("grid")
    if not g or not task or task not in g["tasks"] or target not in g["cells"]:
        return None
    build = next((n for n in st["order"] if entry(st, n).get("scope") == "grid"), None)
    if build is None or index_of(st, build) >= here:
        return None
    return target, task


def recheck_cells(run, cells, reason):
    """Scoped recheck: reset only the named tasks' cells (from the named cell on), reopen the grid,
    and rerun every lens after it. Settled tasks stay settled."""
    st = load(run)
    g = st["grid"]
    build = next(n for n in st["order"] if entry(st, n).get("scope") == "grid")
    for lens, task in cells:
        order = g["cells"]
        for name in order[order.index(lens):]:
            g["tasks"][task]["cells"][name] = grid.fresh_cell()
    st["lenses"][build].update(status="running", ended_at=None)
    for name in st["order"][index_of(st, build) + 1:]:
        st["lenses"][name] = fresh_lens()
        (st.get("settle") or {}).pop(name, None)
    st["halt"] = None
    st["rewinds"].append({"to": build, "cells": [unit_key(l, t) for l, t in cells], "reason": reason, "at": now()})
    save(run, st)
    return {"rechecking": [unit_key(l, t) for l, t in cells], "reason": reason}


def cmd_disputes(run, lens):
    """Every routed dispute that targets this lens, oldest first: feedback for a re-run."""
    st = load(run)
    out = []
    for d in st["disputes"]:
        if d["target"] == lens:
            body = read_json(os.path.join(run, "disputes", d["file"]))
            out.append(dict(body, file=d["file"], **{"from": d["from"]}))
    return {"lens": lens, "disputes": out}


# ---- relay ---------------------------------------------------------------


def cmd_answer(run, lens, answer, task=None, unit=None):
    st = load(run)
    if unit:
        return settle_answer(run, st, unit, answer)
    if task:
        cell = st["grid"]["tasks"][task]["cells"][lens]
        if cell["status"] != "needs_input":
            raise LensError(f"cell {lens} for {task} is {cell['status']}, not waiting for input")
        answer_row(run, unit_key(lens, task), answer)
        respawn = cell["respawn"]
        cell.update(status="running", respawn=False)
        save(run, st)
        return {"lens": lens, "task": task, "continue": "respawn" if respawn else "send_message"}
    state = st["lenses"][lens]
    if state["status"] != "needs_input":
        raise LensError(f"lens {lens} is {state['status']}, not waiting for input")
    answer_row(run, lens, answer)
    if entry(st, lens).get("scope") == "code":
        state["status"] = "pending"
        save(run, st)
        return {"lens": lens, "continue": "next"}
    respawn = state["respawn"]
    state.update(status="running", respawn=False)
    save(run, st)
    return {"lens": lens, "continue": "respawn" if respawn else "send_message"}


def answer_row(run, key, answer):
    rows = read_jsonl(qa_path(run, key))
    for row in rows:
        if row.get("answer") is None:
            row["answer"] = answer
            row["answered_at"] = now()
            break
    write_jsonl(qa_path(run, key), rows)


# ---- rewind / resume -----------------------------------------------------


def rewind(run, to, reason="manual"):
    st = load(run)
    start = index_of(st, to)
    for name in st["order"][start:]:
        st["lenses"][name] = fresh_lens()
        if entry(st, name).get("scope") == "grid":
            st["grid"] = None
        (st.get("settle") or {}).pop(name, None)
    st["halt"] = None
    st["rewinds"].append({"to": to, "reason": reason, "at": now()})
    save(run, st)
    return {"rewound_to": to, "reason": reason}


def cmd_resume(run):
    st = load(run)
    for lens in st["lenses"].values():
        if lens["status"] == "running":
            lens.update(status="pending", attempts=max(lens["attempts"] - 1, 0))
        elif lens["status"] == "needs_input":
            lens["respawn"] = True
    for group in (st.get("settle") or {}).values():
        for u in group["units"].values():
            if u["status"] == "running":
                u.update(status="pending", attempts=max(u["attempts"] - 1, 0))
            elif u["status"] == "needs_input" and u["kind"] != "decision":
                u["respawn"] = True
    for task in (st.get("grid") or {}).get("tasks", {}).values():
        for cell in task["cells"].values():
            if cell["status"] == "running":
                cell.update(status="pending", attempts=max(cell["attempts"] - 1, 0))
            elif cell["status"] == "needs_input":
                cell["respawn"] = True
    save(run, st)
    return cmd_next(run)


def cmd_latest(repo):
    root = os.path.join(lens_home(), repo_slug(repo))
    if not os.path.isdir(root):
        raise LensError(f"no runs for {repo}")
    runs = [os.path.join(root, n) for n in os.listdir(root)
            if os.path.exists(status_path(os.path.join(root, n)))]
    if not runs:
        raise LensError(f"no runs for {repo}")
    latest = max(runs, key=lambda r: load(r)["created_at"])
    return {"run": latest}


# ---- report --------------------------------------------------------------


def build_report(run, st):
    lenses = []
    for name in st["order"]:
        s = st["lenses"][name]
        duration = None
        if s["started_at"] and s["ended_at"]:
            duration = round(s["ended_at"] - s["started_at"], 1)
        lenses.append({"lens": name, "status": s["status"], "attempts": s["attempts"],
                       "seconds": duration, "note": s["note"]})
    gates = []
    qa_dir = os.path.join(run, "qa")
    for fname in sorted(os.listdir(qa_dir)) if os.path.isdir(qa_dir) else []:
        if not fname.endswith(".jsonl"):
            continue
        for row in read_jsonl(os.path.join(qa_dir, fname)):
            wait = None
            if row.get("asked_at") and row.get("answered_at"):
                wait = round(row["answered_at"] - row["asked_at"], 1)
            gates.append({"lens": fname[:-len(".jsonl")], "question": row.get("question"),
                          "answer": row.get("answer"), "wait_seconds": wait})
    g = st.get("grid") or {}
    build = None
    if g:
        gaps = {}
        for tid in g["tasks"]:
            path = os.path.join(run, "coverage", f"{tid}.json")
            left = read_json(path).get("gaps", []) if os.path.exists(path) else []
            if left:
                gaps[tid] = left
        build = {"tasks": len(g["tasks"]), "cells": sum(len(t["cells"]) for t in g["tasks"].values()),
                 "spurious_failures": g["spurious"], "coverage_gaps": gaps}
    report = {
        "run_id": st["run_id"],
        "build": build,
        "settle": settle.report(st),
        "prs": read_json(os.path.join(run, "prs.json")) if os.path.exists(os.path.join(run, "prs.json")) else None,
        "followups": [read_json(os.path.join(run, f)) for f in sorted(os.listdir(run))
                      if f.startswith("followup-") and f.endswith(".json")],
        "flaky": read_jsonl(os.path.join(run, "flaky.jsonl")),
        "skipped_tiers": read_jsonl(os.path.join(run, "skipped.jsonl")),
        "coherence": (read_json(os.path.join(run, "coherence.json")) if os.path.exists(os.path.join(run, "coherence.json")) else None),
        "lenses": lenses,
        "gates": gates,
        "disputes": st["disputes"],
        "rewinds": st["rewinds"],
        "halt": st["halt"],
    }
    write_json(os.path.join(run, "report.json"), report)
    return report


def cmd_report(run):
    report = build_report(run, load(run))
    ran = [x for x in report["lenses"] if x["status"] == "done"]
    skipped = [x["lens"] for x in report["lenses"] if x["status"] == "skipped"]
    lines = [f"run {report['run_id']}: {len(ran)} lenses done, {len(skipped)} skipped"]
    lines += [f"- {x['lens']}: {x['attempts']} attempt(s), {x['seconds']}s" for x in ran]
    if report["gates"]:
        lines.append(f"{len(report['gates'])} question(s) relayed to the user")
    if report["disputes"]:
        lines.append(f"{len(report['disputes'])} dispute(s), {len(report['rewinds'])} rewind(s)")
    if report.get("build"):
        b = report["build"]
        lines.append(f"build: {b['tasks']} task(s), {b['spurious_failures']} spurious failure(s), "
                     f"{len(b['coverage_gaps'])} task(s) with coverage gaps left")
    for name, grp in (report.get("settle") or {}).items():
        lines.append(f"{name}: {grp['epochs']} fix epoch(s), findings {grp['findings']}")
    sig = (report.get("coherence") or {}).get("signals")
    if sig:
        lines.append(f"coherence: cross-community {sig['cross_community_ratio']} (p75 {sig['cross_community_baseline_p75']}), "
                     f"scatter {sig['concept_scatter']}, new cycles {sig['new_cycles']}")
    if report.get("flaky"):
        lines.append(f"{len(report['flaky'])} flaky test(s)")
    if report.get("skipped_tiers"):
        lines.append("skipped test tiers: " + ", ".join(x.get("lens", "?") for x in report["skipped_tiers"]))
    for pr in report.get("prs") or []:
        lines.append(f"PR {pr.get('url')}")
    for i, f in enumerate(report.get("followups") or [], 1):
        fixed = sum(x.get("fixed", 0) for x in f)
        open_human = sum(x.get("open_human", 0) for x in f)
        lines.append(f"follow-up pass {i}: {fixed} comment(s) fixed, {open_human} human thread(s) open")
    if report["halt"]:
        lines.append(f"halted at {report['halt']['lens']}: {report['halt']['reason']}")
    return {"report": os.path.join(run, "report.json"), "rendering": lines}


# ---- info ----------------------------------------------------------------


def cmd_info(run):
    """Paths a lens needs, so lenses never read status.json themselves."""
    st = load(run)
    home = lens_home()
    info = {
        "run": run,
        "repo": st["repo"],
        "repo_home": os.path.join(home, st["repo_slug"]),
        "core_graph": os.path.join(home, st["repo_slug"], "graph", "core", "out", "graph.json"),
        "refresh": st.get("refresh", False),
    }
    for name in ("workspace", "snapshot"):
        path = os.path.join(run, f"{name}.json")
        info[name] = read_json(path) if os.path.exists(path) else None
    return info


# ---- coherence -----------------------------------------------------------


def cmd_coherence(run):
    """Refresh the live snapshot, then diff it against the base snapshot."""
    cores.refresh_live(run)
    snap = read_json(os.path.join(run, "snapshot.json"))
    ws = read_json(os.path.join(run, "workspace.json"))["path"]
    workdir = os.path.join(run, "coherence")
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
    out = coherence.full_report(snap["base"], snap["live"], ws, workdir)
    path = os.path.join(run, "coherence.json")
    write_json(path, out)
    return {"report": path, "findings": len(out["findings"]), "signals": out["signals"]}


# ---- cores ---------------------------------------------------------------


def cmd_core(run, op, kind, paths):
    st = load(run)
    home, slug = lens_home(), st["repo_slug"]
    if op == "resolve":
        return {"files": cores.resolve(home, slug, kind, paths)}
    if op == "dirs":
        return {"dirs": cores.core_dirs(home, slug, kind),
                "pending": os.path.join(run, "pending", kind)}
    return {"promoted": cores.promote(run, home, slug, kind)}


# ---- cli -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="lensctl.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--repo", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--proposal")
    g.add_argument("--proposal-file")
    s.add_argument("--base", help="base revision (default trunk())")
    s.add_argument("--only", help="run a single lens, e.g. a core refresh")

    for name in ("next", "resume", "report"):
        sub.add_parser(name).add_argument("--run", required=True)

    s = sub.add_parser("record")
    s.add_argument("--run", required=True)
    s.add_argument("--lens", required=True)
    s.add_argument("--status", required=True, choices=["done", "needs_input", "failed", "blocked"])
    s.add_argument("--summary", default="")
    s.add_argument("--task")
    s.add_argument("--unit")

    s = sub.add_parser("answer")
    s.add_argument("--run", required=True)
    s.add_argument("--lens", required=True)
    s.add_argument("--answer", required=True)
    s.add_argument("--task")
    s.add_argument("--unit")

    s = sub.add_parser("rewind")
    s.add_argument("--run", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--reason", default="manual")

    s = sub.add_parser("core")
    s.add_argument("op", choices=["resolve", "promote", "dirs"])
    s.add_argument("--run", required=True)
    s.add_argument("--kind", required=True, choices=sorted(cores.CORE_FILES))
    s.add_argument("--paths", nargs="*", default=[])

    sub.add_parser("snapshot-refresh").add_argument("--run", required=True)
    sub.add_parser("info").add_argument("--run", required=True)
    sub.add_parser("coherence").add_argument("--run", required=True)
    s = sub.add_parser("disputes")
    s.add_argument("--run", required=True)
    s.add_argument("--lens", required=True)
    sub.add_parser("latest").add_argument("--repo", required=True)
    sub.add_parser("wait").add_argument("--seconds", type=int, required=True)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "init":
            proposal = a.proposal
            if a.proposal_file:
                with open(a.proposal_file) as f:
                    proposal = f.read()
            out = cmd_init(a.repo, proposal, base=a.base, only=a.only)
        elif a.cmd == "next":
            out = cmd_next(a.run)
        elif a.cmd == "record":
            out = cmd_record(a.run, a.lens, a.status, a.summary, a.task, a.unit)
        elif a.cmd == "answer":
            out = cmd_answer(a.run, a.lens, a.answer, a.task, a.unit)
        elif a.cmd == "rewind":
            out = rewind(a.run, a.to, a.reason)
        elif a.cmd == "resume":
            out = cmd_resume(a.run)
        elif a.cmd == "report":
            out = cmd_report(a.run)
        elif a.cmd == "core":
            out = cmd_core(a.run, a.op, a.kind, a.paths)
        elif a.cmd == "disputes":
            out = cmd_disputes(a.run, a.lens)
        elif a.cmd == "coherence":
            out = cmd_coherence(a.run)
        elif a.cmd == "info":
            out = cmd_info(a.run)
        elif a.cmd == "snapshot-refresh":
            cores.refresh_live(a.run)
            out = {"refreshed": True}
        elif a.cmd == "latest":
            out = cmd_latest(a.repo)
        else:
            time.sleep(a.seconds)
            out = {"waited": a.seconds}
    except (LensError, cores.CoreError) as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

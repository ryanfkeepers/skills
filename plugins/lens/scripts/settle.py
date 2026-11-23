"""Settlement: concurrent read-only reviewers, one writer, re-review by radius.

Reviewers read a pinned epoch (a commit id of the run's single revision) and
append findings to findings/<unit>.jsonl. Triage validates and classifies them
in batches into findings/triaged.jsonl. One writer at a time applies queued
findings: fix in the blocking pass, review-patcher in the deferred pass. Each
write is a new epoch; its changed files plus their 1-hop graph neighbors are
the radius, and every reviewer whose scope touches the radius re-reviews just
that radius. Design findings, and findings that keep coming back, go to the
user as decisions. A pass is settled when nothing runs, nothing is queued, and
the last epoch produced no confirmed findings.
"""
import json
import os

import cores
import grid

MAX_EPOCHS = 16
MAX_ROUNDS = 2
FIXERS = {"blocking": "fix", "deferred": "review-patcher"}


# ---- io ------------------------------------------------------------------


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


# ---- graph radius --------------------------------------------------------


def radius(graph_path, changed):
    """Changed files plus the files of their direct callers and callees."""
    files = set(changed)
    g = read_json(graph_path, {})
    if not g:
        return sorted(files)
    by_id = {n["id"]: n.get("source_file") for n in g.get("nodes", [])}
    touched = {nid for nid, f in by_id.items() if f in files}
    for link in g.get("links", g.get("edges", [])):
        s, t = link.get("source"), link.get("target")
        if s in touched and by_id.get(t):
            files.add(by_id[t])
        if t in touched and by_id.get(s):
            files.add(by_id[s])
    return sorted(f for f in files if f)


def refresh_and_radius(run, changed):
    """Refresh the live snapshot from the workspace, then compute the radius on it."""
    cores.refresh_live(run)
    snap = read_json(os.path.join(run, "snapshot.json"), {})
    return radius(snap.get("live", ""), changed)


# ---- state ---------------------------------------------------------------


def workspace(run):
    return read_json(os.path.join(run, "workspace.json"))["path"]


def task_targets(run):
    return {tid: set(grid.target_files(t)) for tid, t in grid.load_tasks(run).items()}


def boundaries(run):
    """Approved contract scenarios, one per boundary: name -> package dir."""
    folder = os.path.join(run, "scenarios", "contract")
    out = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            b = read_json(os.path.join(folder, name), {})
            out[name[:-len(".json")]] = (b.get("package") or "").strip("/")
    return out


def new_unit(lens, kind, params, task=None):
    return {"lens": lens, "kind": kind, "task": task, "status": "pending", "attempts": 0,
            "params": params, "respawn": False}


def consume_feedback(run, name):
    """User notes from a human review pass, as confirmed blocking findings; consumed once."""
    path = os.path.join(run, "feedback", f"{name}.jsonl")
    rows = read_jsonl(path)
    if rows:
        os.replace(path, path + ".consumed")
    for r in rows:
        append_jsonl(os.path.join(run, "findings", "triaged.jsonl"),
                     dict(r, sources=[r["id"]], verdict="confirmed", blocking=True, duplicate_of=None,
                          lens="user", **{"class": "defect"}))
    return rows


def deselected(run, e):
    """Lenses the review-select lens ruled out, name -> reason. Only gated groups are affected.

    A missing or unreadable selection drops nothing, and a lens in `always` is never dropped.
    """
    if "always" not in e:
        return {}
    chosen = read_json(os.path.join(run, "review-select.json"), {}).get("lenses", {})
    out = {}
    for lens in e["lenses"]:
        pick = chosen.get(lens)
        if lens not in e["always"] and isinstance(pick, dict) and pick.get("apply") is False:
            out[lens] = str(pick.get("reason", ""))
    return out


def retire_key(lens, scope=None):
    """Identity of a lens for retirement: the lens, narrowed by task or boundary when it runs per unit."""
    return f"{lens}:{scope}" if scope else lens


def unit_retire_key(u):
    return retire_key(u["lens"], u.get("task") or u["params"].get("boundary"))


def retire(s, key):
    """The unit reported not_applicable: retire its lens and cancel its queued re-reviews.

    Only a full-scope review can retire a lens. A radius review saw a few files, so its
    not_applicable says nothing about the rest of the change.
    """
    u = s["units"][key]
    u["status"] = "done"
    if u["params"].get("scope") == "radius":
        return
    rk = unit_retire_key(u)
    s.setdefault("retired", [])
    if rk not in s["retired"]:
        s["retired"].append(rk)
    for other in s["units"].values():
        if other["kind"] == "review" and other["status"] == "pending" and unit_retire_key(other) == rk:
            other["status"] = "done"


def init(run, st, name, e):
    ws = workspace(run)
    epoch = grid.commit_of_workspace(ws)
    feedback = consume_feedback(run, name)
    if feedback:
        st.setdefault("settle", {})[name] = {
            "pass": "blocking", "epochs": [epoch], "units": {}, "untriaged": [], "seq": 0, "new_findings": 0,
            "retired": [], "deselected": {},
            "items": {r["id"]: {"state": "queued", "blocking": True, "rounds": 0, "class": "defect",
                                "decision": r.get("claim")} for r in feedback},
        }
        return
    units = {}
    tasks = sorted(task_targets(run)) if e.get("per_task") else []
    bounds = boundaries(run) if e.get("per_boundary") else {}
    dropped = deselected(run, e)
    for lens in e["lenses"]:
        if lens in dropped:
            continue
        if lens in e.get("per_boundary", []):
            for b in bounds:
                units[f"{lens}-{b}"] = new_unit(lens, "review", {"epoch": epoch, "scope": "full", "boundary": b})
        elif lens in e.get("per_task", []):
            for tid in tasks:
                units[f"{lens}-{tid}"] = new_unit(lens, "review", {"epoch": epoch, "scope": "full", "task": tid}, tid)
        else:
            units[lens] = new_unit(lens, "review", {"epoch": epoch, "scope": "full"})
    st.setdefault("settle", {})[name] = {
        "pass": "blocking", "epochs": [epoch], "units": units, "untriaged": [],
        "items": {}, "seq": 0, "new_findings": 0, "retired": [], "deselected": dropped,
    }


def next_key(s, prefix):
    """Unit key unique across the run: callers prefix the group name, since units are looked up run-wide."""
    s["seq"] += 1
    return f"{prefix}-{s['seq']}"


def busy(s, kinds):
    return [k for k, u in s["units"].items() if u["kind"] in kinds and u["status"] in ("running", "needs_input")]


def running_count(s):
    return len(busy(s, ("review", "triage", "fix")))


# ---- next ----------------------------------------------------------------


def next_action(run, st, name, e, max_agents):
    s = st["settle"][name]
    for key, u in s["units"].items():
        if u["status"] == "needs_input":
            return {"action": "relay", "lens": u["lens"], "unit": key, "respawn": u["respawn"]}
    for kind in ("triage", "fix"):
        retry = [k for k, u in s["units"].items() if u["kind"] == kind and u["status"] == "pending"]
        if retry and not busy(s, (kind,)):
            return dispatch(s, retry[0])
    if s["untriaged"] and not busy(s, ("triage",)):
        key = next_key(s, f"{name}-triage")
        epoch = s["epochs"][-1]
        s["units"][key] = new_unit("triage", "triage", {
            "findings": list(s["untriaged"]), "epoch": epoch, "pass": s["pass"],
            "stale": stale_ids(run, s, epoch)})
        s["untriaged"] = []
        return dispatch(s, key)
    writers = e.get("writers")
    queued = [i for i, it in s["items"].items() if it["state"] == "queued"]
    if queued and not busy(s, ("fix",)) and not (writers and busy(s, ("review",))):
        fixer = "fix" if any(s["items"][i]["blocking"] for i in queued) else FIXERS[s["pass"]]
        batch = [i for i in queued if s["items"][i]["blocking"]] if fixer == "fix" else queued
        key = next_key(s, f"{name}-{fixer}")
        for i in batch:
            s["items"][i]["state"] = "fixing"
        s["units"][key] = new_unit(fixer, "fix", {"findings": batch, "epoch": s["epochs"][-1], "pass": s["pass"]})
        return dispatch(s, key)
    for key, u in s["units"].items():
        if u["status"] == "pending" and u["kind"] == "review" and running_count(s) < max_agents \
                and not (writers and busy(s, ("fix",))):
            return dispatch(s, key)
    if running_count(s):
        return {"action": "wait", "running": busy(s, ("review", "triage", "fix"))}
    if any(it["state"] in ("queued", "fixing", "deciding") for it in s["items"].values()):
        return {"action": "wait", "running": []}
    if s["pass"] == "blocking":
        s["pass"] = "deferred"
        s["epochs_at_pass"] = len(s["epochs"])
        for it in s["items"].values():
            if it["state"] == "held":
                it["state"] = "queued"
        return next_action(run, st, name, e, max_agents)
    return None


def dispatch(s, key):
    u = s["units"][key]
    u.update(status="running", attempts=u["attempts"] + 1, respawn=False)
    return {"action": "dispatch", "lens": u["lens"], "unit": key, "task": u["task"],
            "agent": f"lens:{u['lens']}", "params": u["params"], "attempt": u["attempts"]}


def stale_ids(run, s, epoch):
    """Untriaged findings raised against an older epoch whose file has changed since."""
    out = []
    for fid in s["untriaged"]:
        f = find_raw(run, s, fid)
        if not f or f.get("epoch") in (None, epoch):
            continue
        file = (f.get("location") or {}).get("file")
        if file and file in grid.changed_files(workspace(run), f["epoch"], epoch):
            out.append(fid)
    return out


def find_raw(run, s, fid):
    for key, u in s["units"].items():
        if u["kind"] != "review":
            continue
        for row in read_jsonl(os.path.join(run, "findings", f"{key}.jsonl")):
            if row.get("id") == fid:
                return row
    return None


# ---- record --------------------------------------------------------------


def record_done(run, st, name, e, key):
    s = st["settle"][name]
    u = s["units"][key]
    u["status"] = "done"
    if u["kind"] == "review":
        ids = [r["id"] for r in read_jsonl(os.path.join(run, "findings", f"{key}.jsonl")) if r.get("id")]
        s["untriaged"] += [i for i in ids if i not in s["items"] and i not in s["untriaged"]]
        return {}
    if u["kind"] == "triage":
        return ingest_triage(run, s, u)
    return after_write(run, st, name, e, key)


def ingest_triage(run, s, u):
    asked = []
    for row in read_jsonl(os.path.join(run, "findings", "triaged.jsonl")):
        fid = row.get("id")
        if not fid or fid in s["items"] or not set(row.get("sources", [fid])) & set(u["params"]["findings"]):
            continue
        if row.get("verdict") != "confirmed":
            s["items"][fid] = {"state": "dropped", "blocking": False, "rounds": 0}
            continue
        dup = row.get("duplicate_of")
        if dup in s["items"]:
            orig = s["items"][dup]
            orig["rounds"] += 1
            s["items"][fid] = {"state": "merged", "blocking": orig["blocking"], "rounds": 0, "into": dup}
            if orig["rounds"] >= MAX_ROUNDS:
                orig["state"] = "deciding"
                asked.append(decision(s, dup, row, "escalate"))
            else:
                orig["state"] = "queued"
            s["new_findings"] += 1
            continue
        blocking = bool(row.get("blocking"))
        item = {"state": "queued", "blocking": blocking, "rounds": 0, "class": row.get("class", "defect")}
        if row.get("class") == "design":
            item["state"] = "deciding"
            asked.append(decision(s, fid, row, "design"))
        elif not blocking and s["pass"] == "blocking":
            item["state"] = "held"
        s["items"][fid] = item
        s["new_findings"] += 1
    return {"decisions": asked}


def decision(s, fid, row, why):
    key = f"decide-{fid}"
    if why == "design":
        q = {"question": f"Design finding from {row.get('lens', 'review')}: {row.get('claim')}",
             "options": ["fix it as proposed", "leave it", "fix it differently (add notes)"],
             "recommendation": "fix it as proposed", "rendering": row.get("evidence", "")}
    else:
        q = {"question": f"This finding came back after {MAX_ROUNDS} fix rounds: {row.get('claim')}",
             "options": ["try again", "accept as is", "stop the run"],
             "recommendation": "accept as is", "rendering": row.get("evidence", "")}
    s["units"][key] = dict(new_unit("decision", "decision", {"finding": fid, "why": why}),
                           status="needs_input", question=dict(q, answer=None))
    return key


def answer_decision(s, key, answer):
    u = s["units"][key]
    item = s["items"][u["params"]["finding"]]
    u["question"]["answer"] = answer
    u["status"] = "done"
    a = answer.lower()
    if a.startswith("stop"):
        return {"halt": f"user stopped the run on finding {u['params']['finding']}"}
    if a.startswith(("leave", "accept")):
        item["state"] = "dismissed"
    else:
        item.update(state="queued", decision=answer, blocking=True, rounds=0)
    return {}


def after_write(run, st, name, e, key):
    s = st["settle"][name]
    u = s["units"][key]
    for fid in u["params"]["findings"]:
        s["items"][fid]["state"] = "fixed"
    ws = workspace(run)
    prev, new = s["epochs"][-1], grid.commit_of_workspace(ws)
    if new == prev:
        return {}
    s["epochs"].append(new)
    in_pass = len(s["epochs"]) - s.get("epochs_at_pass", 1)
    if in_pass > MAX_EPOCHS:
        return {"halt": f"{name}: {MAX_EPOCHS} epochs without settling in the {s['pass']} pass"}
    changed = grid.changed_files(ws, prev, new)
    rad = refresh_and_radius(run, changed)
    s["new_findings"] = 0
    targets = task_targets(run)
    bounds = boundaries(run) if e.get("per_boundary") else {}
    rad_dirs = {os.path.dirname(f) for f in rad}
    retired = set(s.get("retired", []))
    dropped = set(s.get("deselected", {}))
    for lens in e["lenses"]:
        if lens in dropped:
            continue
        if lens in e.get("per_boundary", []):
            for b, pkg in bounds.items():
                if pkg in rad_dirs and retire_key(lens, b) not in retired:
                    rk = next_key(s, f"{lens}-{b}-e{len(s['epochs']) - 1}")
                    s["units"][rk] = new_unit(lens, "review", {"epoch": new, "scope": "radius", "radius": rad,
                                                                "boundary": b})
        elif lens in e.get("per_task", []):
            for tid, files in targets.items():
                hit = sorted(files & set(rad))
                if hit and retire_key(lens, tid) not in retired:
                    rk = next_key(s, f"{lens}-{tid}-e{len(s['epochs']) - 1}")
                    s["units"][rk] = new_unit(lens, "review", {"epoch": new, "scope": "radius", "radius": rad,
                                                                "task": tid}, tid)
        elif rad and retire_key(lens) not in retired:
            rk = next_key(s, f"{lens}-e{len(s['epochs']) - 1}")
            s["units"][rk] = new_unit(lens, "review", {"epoch": new, "scope": "radius", "radius": rad})
    return {"epoch": new, "radius": rad}


def record_failed(st, name, key, retries):
    s = st["settle"][name]
    u = s["units"][key]
    if u["attempts"] > retries:
        u["status"] = "failed"
        return {"halt": f"{key} failed twice"}
    u["status"] = "pending"
    return {}


def report(st):
    out = {}
    for name, s in (st.get("settle") or {}).items():
        if s.get("pass") == "parallel":
            continue
        states = {}
        for it in s["items"].values():
            states[it["state"]] = states.get(it["state"], 0) + 1
        out[name] = {"epochs": len(s["epochs"]) - 1, "findings": states,
                     "retired": sorted(s.get("retired", [])), "deselected": s.get("deselected", {}),
                     "fix_rounds": sum(it["rounds"] for it in s["items"].values()),
                     "units": len(s["units"])}
    return out

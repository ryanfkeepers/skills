"""Settlement: concurrent read-only reviewers, one writer, re-review by radius.

Settlement sees one change: the run's single
revision, checked before a group starts. Reviewers read a pinned epoch (a
commit id of that revision) and append findings to
findings/<task-action>.jsonl. Triage validates and classifies them in batches
into findings/triaged.jsonl. One writer at a time applies queued findings: fix
in the blocking pass, review-patcher in the deferred pass. Each write is a new
epoch; its changed files plus their 1-hop graph neighbors are the radius, and
every reviewer whose scope touches the radius re-reviews just that radius.
Design findings, and findings that keep coming back, go to the user as
decisions. A pass is settled when nothing runs, nothing is queued, and the
last epoch produced no confirmed findings.

A group marked `"rerun": "raisers"` narrows that. After a write, only the
reviewers that raised the fixed findings re-review, and only the radius. When
none are left waiting and a write happened since the last full batch, every
reviewer runs again over the whole change (a sweep). After every second full
loop that still has unswept fixes, the user is asked whether to continue.
"""
import json
import os

import cores

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


# ---- workspace -----------------------------------------------------------


def commit_of_workspace(ws_path):
    return cores.jj(ws_path, "log", "--no-graph", "-r", "@", "-T", "commit_id")


def changed_files(ws_path, start, end):
    """Workspace-relative paths changed between two commits (jj prints paths relative to cwd)."""
    out = cores.must(["jj", "--no-pager", "diff", "--from", start, "--to", end, "--name-only"], cwd=ws_path)
    return [l for l in out.splitlines() if l.strip()]


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


def assert_one_revision(run):
    """Reviewers diff base_commit..epoch as one change, so the run must be exactly one revision."""
    ws = read_json(os.path.join(run, "workspace.json"))
    revs = cores.jj(ws["path"], "log", "--no-graph", "-r", f"{ws['base_commit']}..@",
                    "-T", 'commit_id ++ "\\n"').split()
    if len(revs) != 1:
        raise cores.CoreError(f"the run must be one revision on {ws['base_commit'][:12]}, "
                              f"found {len(revs)}")


def boundaries(run):
    """Approved contract scenarios, one per boundary: name -> package dir."""
    folder = os.path.join(run, "scenarios", "contract")
    out = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            b = read_json(os.path.join(folder, name), {})
            out[name[:-len(".json")]] = (b.get("package") or "").strip("/")
    return out


def new_task_action(lens, kind, params):
    return {"lens": lens, "kind": kind, "status": "pending", "attempts": 0,
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


def retire_key(lens, boundary=None):
    """Identity of a lens for retirement: the lens, narrowed by boundary when it runs per boundary."""
    return f"{lens}:{boundary}" if boundary else lens


def action_retire_key(ta):
    return retire_key(ta["lens"], ta["params"].get("boundary"))


def retire(s, key):
    """The task-action reported not_applicable: retire its lens and cancel its queued re-reviews.

    Only a full-scope review can retire a lens. A radius review saw a few files, so its
    not_applicable says nothing about the rest of the change.
    """
    ta = s["task_actions"][key]
    ta["status"] = "done"
    if ta["params"].get("scope") == "radius":
        return
    rk = action_retire_key(ta)
    s.setdefault("retired", [])
    if rk not in s["retired"]:
        s["retired"].append(rk)
    for other in s["task_actions"].values():
        if other["kind"] == "review" and other["status"] == "pending" and action_retire_key(other) == rk:
            other["status"] = "done"


def init(run, st, name, e):
    assert_one_revision(run)
    ws = workspace(run)
    epoch = commit_of_workspace(ws)
    feedback = consume_feedback(run, name)
    if feedback:
        st.setdefault("settle", {})[name] = {
            "pass": "blocking", "epochs": [epoch], "task_actions": {}, "untriaged": [], "seq": 0,
            "new_findings": 0, "retired": [], "deselected": {}, "loop": 1, "dirty": False,
            "items": {r["id"]: {"state": "queued", "blocking": True, "rounds": 0, "class": "defect",
                                "decision": r.get("claim"), "claim": r.get("claim"), "lens": "user",
                                "lenses": [], "loop": 1} for r in feedback},
        }
        return
    dropped = deselected(run, e)
    st.setdefault("settle", {})[name] = {
        "pass": "blocking", "epochs": [epoch], "task_actions": full_batch(run, e, epoch, dropped, set()),
        "untriaged": [], "items": {}, "seq": 0, "new_findings": 0, "retired": [], "deselected": dropped,
        "loop": 1, "dirty": False,
    }


def full_batch(run, e, epoch, dropped, retired, suffix=""):
    """Whole-change review task-actions for every lens still in play. `suffix` keeps a sweep's keys unique."""
    actions = {}
    bounds = boundaries(run) if e.get("per_boundary") else {}
    for lens in e["lenses"]:
        if lens in dropped:
            continue
        if lens in e.get("per_boundary", []):
            for b in bounds:
                if retire_key(lens, b) not in retired:
                    actions[f"{lens}-{b}{suffix}"] = new_task_action(
                        lens, "review", {"epoch": epoch, "scope": "full", "boundary": b})
        elif retire_key(lens) not in retired:
            actions[f"{lens}{suffix}"] = new_task_action(lens, "review", {"epoch": epoch, "scope": "full"})
    return actions


def next_key(s, prefix):
    """Task-action key unique across the run: callers prefix the group name, since keys are looked up run-wide."""
    s["seq"] += 1
    return f"{prefix}-{s['seq']}"


def busy(s, kinds):
    return [k for k, ta in s["task_actions"].items()
            if ta["kind"] in kinds and ta["status"] in ("running", "needs_input")]


def running_count(s):
    return len(busy(s, ("review", "triage", "fix")))


# ---- next ----------------------------------------------------------------


def next_action(run, st, name, e, max_agents):
    s = st["settle"][name]
    for key, ta in s["task_actions"].items():
        if ta["status"] == "needs_input":
            return {"action": "relay", "lens": ta["lens"], "task_action": key, "respawn": ta["respawn"]}
    for kind in ("triage", "fix"):
        retry = [k for k, ta in s["task_actions"].items() if ta["kind"] == kind and ta["status"] == "pending"]
        if retry and not busy(s, (kind,)):
            return dispatch(s, retry[0])
    if s["untriaged"] and not busy(s, ("triage",)):
        key = next_key(s, f"{name}-triage")
        epoch = s["epochs"][-1]
        s["task_actions"][key] = new_task_action("triage", "triage", {
            "findings": list(s["untriaged"]), "epoch": epoch, "pass": s["pass"],
            "stale": stale_ids(run, s, epoch)})
        s["untriaged"] = []
        return dispatch(s, key)
    writers = e.get("writers")
    queued = [i for i, it in s["items"].items() if it["state"] == "queued"]
    if queued and not busy(s, ("fix",)) and not (writers and busy(s, ("review",))):
        fixer = "fix" if any(s["items"][i]["blocking"] for i in queued) else FIXERS[s["pass"]]
        batch = [i for i in queued if s["items"][i]["blocking"]] if fixer == "fix" else queued
        if not batch:
            for i in queued:
                s["items"][i]["state"] = "held"
            return next_action(run, st, name, e, max_agents)
        key = next_key(s, f"{name}-{fixer}")
        for i in batch:
            s["items"][i]["state"] = "fixing"
        s["task_actions"][key] = new_task_action(fixer, "fix",
                                                 {"findings": batch, "epoch": s["epochs"][-1], "pass": s["pass"]})
        return dispatch(s, key)
    for key, ta in s["task_actions"].items():
        if ta["status"] == "pending" and ta["kind"] == "review" and running_count(s) < max_agents \
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
    if e.get("rerun") == "raisers" and s.get("dirty"):
        return begin_sweep(run, st, name, e, max_agents)
    return None


def begin_sweep(run, st, name, e, max_agents):
    """Everything drained after a write: ask the user after every second full loop, else review the whole change again."""
    s = st["settle"][name]
    key = f"{name}-continue-{s['loop']}"
    if s["loop"] % 2 == 0 and key not in s["task_actions"]:
        s["task_actions"][key] = sweep_question(s)
        return {"action": "relay", "lens": "decision", "task_action": key, "respawn": False}
    s["loop"] += 1
    s["dirty"] = False
    s["epochs_at_pass"] = len(s["epochs"])
    s["task_actions"].update(full_batch(run, e, s["epochs"][-1], set(s.get("deselected", {})),
                                        set(s.get("retired", [])), suffix=f"-sweep{s['loop']}"))
    return next_action(run, st, name, e, max_agents)


STATUS_WORDS = {
    "fixed": "fixed, not yet re-checked by a full sweep",
    "queued": "waiting to be fixed", "fixing": "being fixed", "held": "waiting for the cleanup pass",
    "deciding": "needs your decision", "dismissed": "left as is by your choice",
    "pre_existing": "was already broken before this change; not fixed",
}


def sweep_table(s):
    """Markdown rundown of what was caught, in order, and where each stands. One plain sentence per row."""
    rows = ["| # | Loop | Reviewer | What it caught | Where it stands |", "|---|---|---|---|---|"]
    n = 0
    for fid, it in s["items"].items():
        if it["state"] in ("dropped", "merged"):
            continue
        n += 1
        what = (it.get("eli5") or it.get("claim") or fid).replace("|", "/").replace("\n", " ")
        word = STATUS_WORDS.get(it["state"], it["state"])
        if it["state"] == "fixed" and it.get("loop", 1) < s["loop"]:
            word = "fixed and re-checked by a full sweep"
        rows.append(f"| {n} | {it.get('loop', 1)} | {it.get('lens', '?')} | {what} | {word} |")
    return "\n".join(rows)


def sweep_question(s):
    q = {"question": f"Full review loop {s['loop']} is finished, but fixes made since the last full sweep have not "
                     "been re-checked against the whole change. Run another full sweep?",
         "options": ["continue", "stop here"], "recommendation": "continue", "rendering": sweep_table(s)}
    return dict(new_task_action("decision", "decision", {"finding": None, "why": "sweep"}),
                status="needs_input", question=dict(q, answer=None))


def dispatch(s, key):
    ta = s["task_actions"][key]
    ta.update(status="running", attempts=ta["attempts"] + 1, respawn=False)
    return {"action": "dispatch", "lens": ta["lens"], "task_action": key,
            "agent": f"lens:{ta['lens']}", "params": ta["params"], "attempt": ta["attempts"]}


def stale_ids(run, s, epoch):
    """Untriaged findings raised against an older epoch whose file has changed since."""
    out = []
    for fid in s["untriaged"]:
        f = find_raw(run, s, fid)
        if not f or f.get("epoch") in (None, epoch):
            continue
        file = (f.get("location") or {}).get("file")
        if file and file in changed_files(workspace(run), f["epoch"], epoch):
            out.append(fid)
    return out


def find_raw(run, s, fid):
    for key, ta in s["task_actions"].items():
        if ta["kind"] != "review":
            continue
        for row in read_jsonl(os.path.join(run, "findings", f"{key}.jsonl")):
            if row.get("id") == fid:
                return row
    return None


# ---- record --------------------------------------------------------------


def record_done(run, st, name, e, key):
    s = st["settle"][name]
    ta = s["task_actions"][key]
    ta["status"] = "done"
    if ta["kind"] == "review":
        ids = [r["id"] for r in read_jsonl(os.path.join(run, "findings", f"{key}.jsonl")) if r.get("id")]
        s["untriaged"] += [i for i in ids if i not in s["items"] and i not in s["untriaged"]]
        return {}
    if ta["kind"] == "triage":
        return ingest_triage(run, s, ta)
    return after_write(run, st, name, e, key)


def ingest_triage(run, s, ta):
    asked = []
    for row in read_jsonl(os.path.join(run, "findings", "triaged.jsonl")):
        fid = row.get("id")
        if not fid or fid in s["items"] or not set(row.get("sources", [fid])) & set(ta["params"]["findings"]):
            continue
        if row.get("verdict") == "pre_existing":
            s["items"][fid] = {"state": "pre_existing", "blocking": False, "rounds": 0, "lens": row.get("lens"),
                               "claim": row.get("claim"), "location": row.get("location"),
                               "repro": row.get("repro"), "loop": s.get("loop", 1)}
            continue
        if row.get("verdict") != "confirmed":
            s["items"][fid] = {"state": "dropped", "blocking": False, "rounds": 0}
            continue
        dup = row.get("duplicate_of")
        if dup in s["items"]:
            orig = s["items"][dup]
            orig["rounds"] += 1
            if row.get("lens") and row["lens"] not in orig.setdefault("lenses", []):
                orig["lenses"].append(row["lens"])
            s["items"][fid] = {"state": "merged", "blocking": orig["blocking"], "rounds": 0, "into": dup}
            if orig["rounds"] >= MAX_ROUNDS:
                orig["state"] = "deciding"
                asked.append(decision(s, dup, row, "escalate"))
            else:
                orig["state"] = "queued" if orig["blocking"] or s["pass"] != "blocking" else "held"
            s["new_findings"] += 1
            continue
        blocking = bool(row.get("blocking"))
        item = {"state": "queued", "blocking": blocking, "rounds": 0, "class": row.get("class", "defect"),
                "lens": row.get("lens"), "lenses": [row["lens"]] if row.get("lens") else [],
                "claim": row.get("claim"), "eli5": row.get("eli5"), "loop": s.get("loop", 1)}
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
    s["task_actions"][key] = dict(new_task_action("decision", "decision", {"finding": fid, "why": why}),
                                  status="needs_input", question=dict(q, answer=None))
    return key


def answer_decision(s, key, answer):
    ta = s["task_actions"][key]
    ta["question"]["answer"] = answer
    ta["status"] = "done"
    a = answer.lower()
    if ta["params"].get("why") == "sweep":
        if a.startswith("stop"):
            s["dirty"] = False
            s["stopped_unswept"] = True
        return {}
    item = s["items"][ta["params"]["finding"]]
    if a.startswith("stop"):
        return {"halt": f"user stopped the run on finding {ta['params']['finding']}"}
    if a.startswith(("leave", "accept")):
        item["state"] = "dismissed"
    else:
        item.update(state="queued", decision=answer, blocking=True, rounds=0)
    return {}


def after_write(run, st, name, e, key):
    s = st["settle"][name]
    ta = s["task_actions"][key]
    for fid in ta["params"]["findings"]:
        s["items"][fid]["state"] = "fixed"
    ws = workspace(run)
    prev, new = s["epochs"][-1], commit_of_workspace(ws)
    if new == prev:
        return {}
    s["epochs"].append(new)
    in_pass = len(s["epochs"]) - s.get("epochs_at_pass", 1)
    if in_pass > MAX_EPOCHS:
        return {"halt": f"{name}: {MAX_EPOCHS} epochs without settling in the {s['pass']} pass"}
    changed = changed_files(ws, prev, new)
    rad = refresh_and_radius(run, changed)
    s["new_findings"] = 0
    raisers = None
    if e.get("rerun") == "raisers":
        s["dirty"] = True
        raisers = {lens for fid in ta["params"]["findings"] for lens in s["items"][fid].get("lenses", [])}
    bounds = boundaries(run) if e.get("per_boundary") else {}
    rad_dirs = {os.path.dirname(f) for f in rad}
    retired = set(s.get("retired", []))
    dropped = set(s.get("deselected", {}))
    for lens in e["lenses"]:
        if lens in dropped or (raisers is not None and lens not in raisers):
            continue
        if lens in e.get("per_boundary", []):
            for b, pkg in bounds.items():
                if pkg in rad_dirs and retire_key(lens, b) not in retired:
                    rk = next_key(s, f"{lens}-{b}-e{len(s['epochs']) - 1}")
                    s["task_actions"][rk] = new_task_action(lens, "review", {"epoch": new, "scope": "radius",
                                                                             "radius": rad, "boundary": b})
        elif rad and retire_key(lens) not in retired:
            rk = next_key(s, f"{lens}-e{len(s['epochs']) - 1}")
            s["task_actions"][rk] = new_task_action(lens, "review", {"epoch": new, "scope": "radius", "radius": rad})
    return {"epoch": new, "radius": rad}


def record_failed(st, name, key, retries):
    s = st["settle"][name]
    ta = s["task_actions"][key]
    if ta["attempts"] > retries:
        ta["status"] = "failed"
        return {"halt": f"{key} failed twice"}
    ta["status"] = "pending"
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
                     "task_actions": len(s["task_actions"]), "full_loops": s.get("loop", 1),
                     "stopped_unswept": bool(s.get("stopped_unswept")),
                     "pre_existing": [{"lens": it.get("lens"), "claim": it.get("claim"),
                                       "location": it.get("location"), "repro": it.get("repro")}
                                      for it in s["items"].values() if it["state"] == "pre_existing"]}
    return out

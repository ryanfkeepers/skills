"""Rerunnable pipeline for the evaluate-pr-stack skill. Read-only against GitHub.

  collect <pr-url> [--out DIR]   find the stack, fetch facts for every open PR,
                                 write them to DIR, print what needs judging
  judge DIR N --splittable yes|no --nominal yes|no [--cause TEXT]
        [--loc-adjust N --note TEXT]
                                 record the two judgment calls for one PR
  report DIR [--viz all|none|N,N]
                                 score from the files in DIR and print the
                                 table and verdict; makes no network calls

Everything a human or agent decides lands in DIR as JSON, so `report` can be
rerun after any change to it.

Exit codes: 0 ok, 1 error, 2 `report` needs the --viz answer first.
"""
import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prfacts  # noqa: E402
import prstack  # noqa: E402

WORKERS = 8
GREEN, YELLOW = 8, 6
LIGHTS = ((GREEN, "🟩"), (YELLOW, "🟨"), (0, "🟥"))


# ---- files ---------------------------------------------------------------


def path_in(d, name):
    return os.path.join(d, name)


def write_json(d, name, payload):
    with open(path_in(d, name), "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)


def read_json(d, name):
    try:
        with open(path_in(d, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# ---- rules ---------------------------------------------------------------


def zero_causes(facts):
    """Reasons a PR scores 0 outright; empty when it is scored normally."""
    causes = []
    if facts["mergeable"] == "CONFLICTING":
        causes.append("merge conflicts")
    if facts["blocking_ci_failures"]:
        causes.append("blocking CI: " + ", ".join(facts["blocking_ci_failures"]))
    return causes


def split_points(splittable, loc):
    if not splittable:
        return 2
    return 1 if loc < 500 else 0


def light(score):
    return next(emoji for floor, emoji in LIGHTS if score >= floor)


def score_pr(facts, judgment, viz):
    """(score, causes) for a PR with facts and a judgment. `viz` is the user's
    answer for this PR; nominal PRs get the point without it."""
    zero = zero_causes(facts)
    if zero:
        return 0, zero
    loc = facts["loc_counted"] + judgment.get("loc_adjust", 0)
    lp = prfacts.loc_points(loc)
    sp = split_points(judgment["splittable"], loc)
    unresolved = facts["ai_threads_unresolved"]
    ap = 0 if unresolved else 2
    vp = 1 if judgment["nominal"] or viz else 0
    causes = []
    if lp < 5:
        causes.append(f"{loc} LoC")
    if sp < 2:
        causes.append(judgment.get("cause") or "splittable")
    if ap < 2:
        causes.append(f"{unresolved} unresolved AI threads")
    if vp < 1:
        causes.append("no visualization")
    return lp + sp + ap + vp, causes


def parse_viz(text, asked):
    text = text.strip().lower()
    if text == "all":
        return set(asked)
    if text == "none":
        return set()
    try:
        picked = {int(t.lstrip("#")) for t in text.split(",") if t.strip()}
    except ValueError:
        raise ValueError(f"--viz takes all, none, or PR numbers; got {text!r}")
    unknown = picked - set(asked)
    if unknown:
        raise ValueError(f"--viz names PRs that were not asked about: {sorted(unknown)}")
    return picked


# ---- collect -------------------------------------------------------------


def collect_one(gh, repo, number):
    try:
        return prfacts.cmd_facts(gh, repo, number)
    except (prstack.GhError, ValueError, KeyError, OSError) as err:
        return {"error": str(err)}


def cmd_collect(gh, url, out=None):
    out = out or tempfile.mkdtemp(prefix="evaluate-pr-stack-")
    os.makedirs(out, exist_ok=True)
    stack = prstack.cmd_stack(gh, url)
    write_json(out, "stack.json", stack)
    open_prs = [p for p in stack["prs"] if p["state"] == "OPEN"]
    if not open_prs:
        raise ValueError("the stack has no open PRs")
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(lambda p: collect_one(gh, stack["repo"], p["number"]), open_prs))
    rows, needs = [], []
    for p, facts in zip(open_prs, results):
        write_json(out, f"facts-{p['number']}.json", facts)
        row = {"number": p["number"], "title": p["title"], "facts_file": path_in(out, f"facts-{p['number']}.json")}
        if "error" in facts:
            row["error"] = facts["error"]
        else:
            row["auto_zero"] = zero_causes(facts)
            row["loc_counted"] = facts["loc_counted"]
            if not row["auto_zero"]:
                needs.append(p["number"])
        rows.append(row)
    return {"dir": out, "repo": stack["repo"], "prs": rows, "needs_judgment": needs,
            "not_open": stack["not_open"]}


# ---- judge ---------------------------------------------------------------


def cmd_judge(d, number, splittable, nominal, cause="", loc_adjust=0, note=""):
    facts = read_json(d, f"facts-{number}.json")
    if facts is None or "error" in facts:
        raise ValueError(f"no usable facts for PR {number} in {d}")
    judgment = {"number": number, "splittable": splittable, "nominal": nominal,
                "cause": cause, "loc_adjust": loc_adjust, "note": note}
    write_json(d, f"judgment-{number}.json", judgment)
    return judgment


# ---- report --------------------------------------------------------------


def load_rows(d):
    stack = read_json(d, "stack.json")
    if stack is None:
        raise ValueError(f"{d} has no stack.json; run collect first")
    rows = []
    for p in stack["prs"]:
        if p["state"] != "OPEN":
            continue
        facts = read_json(d, f"facts-{p['number']}.json")
        row = {"pr": p, "facts": facts, "judgment": read_json(d, f"judgment-{p['number']}.json"), "error": None}
        if facts is None:
            row["error"] = "facts missing"
        elif "error" in facts:
            row["error"] = facts["error"]
        elif not zero_causes(facts) and row["judgment"] is None:
            row["error"] = "judgment missing"
        rows.append(row)
    return stack, rows


def needs_viz(rows):
    return [r["pr"]["number"] for r in rows
            if not r["error"] and not zero_causes(r["facts"]) and not r["judgment"]["nominal"]]


def question(rows, asked):
    lines = ["⚠️ Which of these have a change visualization ready for you to review?"]
    for r in rows:
        n = r["pr"]["number"]
        if n in asked:
            links = r["facts"]["visualization_links"]
            hint = f"   (PR links {', '.join(links)})" if links else ""
            lines.append(f"  #{n} {r['pr']['title']}{hint}")
    lines.append('Reply with numbers, "all", or "none".')
    return "\n".join(lines)


def render(stack, rows, viz):
    fork_parent = {c: f["at"] for f in stack["forks"] for c in f["children"]}
    table = ["| Rating | PR | Cause |", "| --- | --- | --- |"]
    bad = {"yellow": 0, "red": 0, "failed": 0}
    for r in rows:
        p = r["pr"]
        title = f"[#{p['number']} {p['title']}]({p['url']})"
        if p["number"] in fork_parent:
            title = title.replace("](", f" (on #{fork_parent[p['number']]})](", 1)
        if r["error"]:
            rating, cause = "🛑 N/A", r["error"]
            bad["failed"] += 1
        else:
            score, causes = score_pr(r["facts"], r["judgment"] or {}, p["number"] in viz)
            rating = f"{light(score)} {score}/10"
            cause = "; ".join(causes) if score < GREEN else ""
            if score < GREEN:
                bad["yellow" if score >= YELLOW else "red"] += 1
        table.append(f"| {rating} | {title} | {cause} |")
    if any(bad.values()):
        counts = ", ".join(f"{n} {k}" for k, n in bad.items() if n)
        verdict = f"**Not ready for human review:** {counts}."
    else:
        verdict = "**Ready for human review.**"
    out = "\n".join(table) + "\n\n" + verdict
    if stack["not_open"]:
        out += "\n\nSkipped (merged or closed): " + ", ".join(f"#{n}" for n in stack["not_open"])
    return out


def cmd_report(d, viz_arg=None):
    """(exit code, text)."""
    stack, rows = load_rows(d)
    asked = needs_viz(rows)
    if asked and viz_arg is None:
        return 2, question(rows, asked)
    return 0, render(stack, rows, parse_viz(viz_arg, asked) if viz_arg is not None else set())


# ---- cli -----------------------------------------------------------------


def yes_no(text):
    if text not in ("yes", "no"):
        raise argparse.ArgumentTypeError("expected yes or no")
    return text == "yes"


def build_parser():
    p = argparse.ArgumentParser(prog="evaluate.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect")
    s.add_argument("url")
    s.add_argument("--out")
    s = sub.add_parser("judge")
    s.add_argument("dir")
    s.add_argument("number", type=int)
    s.add_argument("--splittable", type=yes_no, required=True)
    s.add_argument("--nominal", type=yes_no, required=True)
    s.add_argument("--cause", default="")
    s.add_argument("--loc-adjust", type=int, default=0)
    s.add_argument("--note", default="")
    s = sub.add_parser("report")
    s.add_argument("dir")
    s.add_argument("--viz")
    return p


def main(argv=None, gh=prstack.run_gh):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "report":
            code, text = cmd_report(a.dir, a.viz)
            print(text)
            return code
        if a.cmd == "collect":
            payload = cmd_collect(gh, a.url, a.out)
        else:
            payload = cmd_judge(a.dir, a.number, a.splittable, a.nominal, a.cause, a.loc_adjust, a.note)
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        return 0
    except (prstack.GhError, ValueError, KeyError, OSError) as err:
        print(json.dumps({"status": "error", "message": str(err)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())

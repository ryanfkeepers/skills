#!/usr/bin/env python3
"""Render the analysis page: render.py data.json [--narrative narrative.json] --out page.html

Injects data.json (plus the optional narrative) into template.html and checks the result:
narrative figure keys and tab links must exist, and the page script must parse under node.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template.html"
FIG_KEYS = {"ranks", "share", "use", "hub", "misfit", "hidden", "depth", "core", "deep"}
TABS = {"overview", "analysis", "suggestions", "scorecard", "forest", "dsm", "matrix", "graph", "bundle", "churn"}
GO_LINK = re.compile(r"\{\{go:(\w+)\|[^}]+\}\}")


def check_narrative(n):
    errs = []
    if not isinstance(n, dict) or not (set(n) & {"analysis", "suggestions"}):
        return ["narrative needs an 'analysis' and/or 'suggestions' object"]

    def texts(part):
        yield part.get("lede", "")
        for s in part.get("sections", []):
            yield from s.get("paras", [])
        aside = part.get("aside") or {}
        yield from aside.get("items", [])
        yield aside.get("next", "")

    for name in ("analysis", "suggestions"):
        part = n.get(name)
        if part is None:
            continue
        for key in ("title", "lede", "sections"):
            if not part.get(key):
                errs.append(f"{name}.{key} is missing or empty")
        for i, s in enumerate(part.get("sections", [])):
            if not s.get("title") or not s.get("paras"):
                errs.append(f"{name}.sections[{i}] needs a title and paras")
            for k in s.get("figs", []):
                if k not in FIG_KEYS:
                    errs.append(f"{name}.sections[{i}].figs has unknown key {k!r} (valid: {sorted(FIG_KEYS)})")
        for t in texts(part):
            for tab in GO_LINK.findall(t):
                if tab not in TABS:
                    errs.append(f"{name}: link to unknown tab {tab!r}")
    return errs


def embed(obj):
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--narrative")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = json.loads(Path(args.data).read_text())
    if args.narrative:
        narrative = json.loads(Path(args.narrative).read_text())
        errs = check_narrative(narrative)
        if errs:
            sys.exit("narrative problems:\n  " + "\n  ".join(errs))
        data["narrative"] = narrative
    page = TEMPLATE.read_text()
    assert page.count("/*__DATA__*/null") == 1 and "__TITLE__" in page, "template placeholders missing"
    page = page.replace("__TITLE__", html.escape(data["meta"]["title"])).replace("/*__DATA__*/null", embed(data))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    if shutil.which("node") and scripts:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(scripts[0])
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        Path(f.name).unlink()
        if r.returncode:
            sys.exit("page script does not parse:\n" + r.stderr[:800])
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

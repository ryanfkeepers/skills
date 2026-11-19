#!/usr/bin/env python3
"""Render a visualize-design spec into a tabbed page for validating a proposed design.

Usage:
  build.py --spec <spec.json> [--out-dir DIR] [--slug NAME] [--verify]

Same shell as visualize-changes (shared/viz-shell): same layout, settings, links,
hotkeys, flow kit, walkthroughs and outputs. There is no diff here: the design is
proposed, not written, so the page reads only the spec. One block type is its
own, `placement`, a tree of where each piece would land.

Writes <slug>.html (standalone) and <slug>.artifact.html (Artifact fragment).
See ../../../shared/viz-shell/blocks.md and ../SKILL.md for the spec format.
"""
import argparse
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "viz-shell"))

from shell import (  # noqa: E402
    Page,
    SpecError,
    assemble,
    esc,
    open_under_base,
    output_slug,
    verify,
)

PLACEMENT_STATES = {"add": "new", "mod": "changed", "same": "existing, unchanged"}
MAX_PLACEMENT_WHAT = 120


class DesignPage(Page):
    TOOL = "visualize-design"
    BLOCK_TYPES = "diagram, walkthrough, html, placement"

    def eyebrow(self):
        return "Proposed design"

    def block_placement(self, tab, b):
        """Where each piece would land: new and changed packages in the repo tree, each with one line."""
        entries = b.get("entries")
        if not isinstance(entries, list) or not entries:
            raise SpecError(f"tab {tab!r}: placement needs 'entries', each {{path, state, what}}")
        tree = OrderedDict()
        for i, e in enumerate(entries):
            where = f"tab {tab!r} placement entries[{i}]"
            if not isinstance(e, dict) or set(e) - {"path", "state", "what"}:
                raise SpecError(f"{where}: must be an object with only path, state and what")
            path = (e.get("path") or "").strip("/")
            if not path:
                raise SpecError(f"{where}: needs a repo-relative 'path'")
            state = e.get("state", "add")
            if state not in PLACEMENT_STATES:
                raise SpecError(f"{where}: state must be one of {list(PLACEMENT_STATES)}")
            what = e.get("what", "")
            if len(what) > MAX_PLACEMENT_WHAT:
                self.warn(f"{where}: 'what' is over {MAX_PLACEMENT_WHAT} chars; one short line")
            node = tree
            segs = path.split("/")
            for j, seg in enumerate(segs):
                node = node.setdefault(seg, {"_children": OrderedDict()})
                if j == len(segs) - 1:
                    node["_state"], node["_what"] = state, what
                node = node["_children"]
        return f'<div class="vc-tree-wrap"><ul class="vc-tree">{self.placement_items(tree)}</ul></div>'

    def placement_items(self, children):
        items = []
        for seg, node in children.items():
            state = node.get("_state")
            if state in ("add", "mod"):
                cls = f"vc-dir vc-pkg {state}"
                title = f' title="{esc(PLACEMENT_STATES[state])}"'
            else:
                cls, title = "vc-dir", ""
            what = f'<span class="vc-landed">{esc(node["_what"])}</span>' if node.get("_what") else ""
            kids = self.placement_items(node["_children"])
            items.append(f'<li><span class="{cls}"{title}>{esc(seg)}/</span>{what}'
                         f'{f"<ul>{kids}</ul>" if kids else ""}</li>')
        return "".join(items)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="spec JSON, under /tmp")
    ap.add_argument("--out-dir", help="output directory, under /tmp (default: the spec's directory)")
    ap.add_argument("--slug", help="output basename (default: spec filename without .json / -spec)")
    ap.add_argument("--verify", action="store_true", help="render headlessly and report diagram errors and overflow")
    args = ap.parse_args()

    spec_path = Path(os.path.realpath(args.spec))
    out_dir = Path(args.out_dir or spec_path.parent)
    try:
        slug = output_slug(args.slug, spec_path)
        with open_under_base(spec_path) as f:
            spec = json.load(f)
        page = DesignPage(spec)
        body, tab_css = page.render()
        standalone, artifact = out_dir / f"{slug}.html", out_dir / f"{slug}.artifact.html"
        for path, mode in ((standalone, "standalone"), (artifact, "artifact")):
            with open_under_base(path, "w") as f:
                f.write(assemble(body, tab_css, spec["title"], mode))
    except SpecError as e:
        raise SystemExit(f"error: {e}")

    for w in page.warnings:
        print(f"warning: {w}")
    print(f"standalone: {standalone} ({standalone.stat().st_size // 1024} KB)")
    print(f"artifact:   {artifact} ({artifact.stat().st_size // 1024} KB)")
    if args.verify:
        for line in verify(standalone):
            print(line)


if __name__ == "__main__":
    main()

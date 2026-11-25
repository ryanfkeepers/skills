#!/usr/bin/env python3
"""Render a visualize-design spec into a tabbed page for validating a proposed design.

Usage:
  build.py --spec <spec.json> [--out-dir DIR] [--slug NAME] [--verify]

Same shell as visualize-changes (shared/viz-shell): same layout, settings, links,
hotkeys, flow kit, walkthroughs and outputs. There is no diff here: the design is
proposed, not written, so the page reads only the spec. Top tabs are chunks of the
design and each holds second-level tabs (`children`). The block types of its own:
`goal`, `declarations`, `layers`, `relationships` and `placement`.

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
CHUNK_STATES = {"add": "new", "mod": "changed"}
GOAL_SECTIONS = (("intents", "Intents"), ("assumptions", "Assumptions"), ("constraints", "Constraints"))
REL_DIRS = (("uses", "Uses"), ("used_by", "Used by"))


class DesignPage(Page):
    TOOL = "visualize-design"
    BLOCK_TYPES = "diagram, walkthrough, html, placement, goal, declarations, layers, relationships"

    def eyebrow(self):
        return "Proposed design"

    def block_goal(self, tab, b):
        """Intents, assumptions and constraints as plain lists; a section with nothing in it is left out."""
        out = []
        for field, heading in GOAL_SECTIONS:
            items = b.get(field) or []
            if not isinstance(items, list) or any(not isinstance(i, str) or not i.strip() for i in items):
                raise SpecError(f"tab {tab!r}: goal {field!r} must be a list of non-empty strings")
            if items:
                lis = "".join(f"<li>{esc(i)}</li>" for i in items)
                out.append(f'<section class="vc-block"><h3 class="vc-h">{heading}</h3><ul>{lis}</ul></section>')
        if not out:
            raise SpecError(f"tab {tab!r}: goal needs at least one of intents, assumptions or constraints")
        return f'<div class="vc-goal vc-stack">{"".join(out)}</div>'

    def block_declarations(self, tab, b):
        """Declarations this chunk adds or changes, one card per directory: name, kind, and the declaration itself."""
        items = b.get("items")
        if not isinstance(items, list) or not items:
            raise SpecError(f"tab {tab!r}: declarations needs 'items', each {{name, kind, file, sig, state?, what?}}")
        by_dir = OrderedDict()
        for i, it in enumerate(items):
            where = f"tab {tab!r} declarations items[{i}]"
            if not isinstance(it, dict) or set(it) - {"name", "kind", "file", "sig", "state", "what"}:
                raise SpecError(f"{where}: must be an object with only name, kind, file, sig, state and what")
            for k in ("name", "kind", "file", "sig"):
                if not isinstance(it.get(k), str) or not it[k].strip():
                    raise SpecError(f"{where}: needs a non-empty {k!r}")
            state = it.get("state", "add")
            if state not in CHUNK_STATES:
                raise SpecError(f"{where}: state must be one of {list(CHUNK_STATES)}")
            if len(it.get("what", "")) > MAX_PLACEMENT_WHAT:
                self.warn(f"{where}: 'what' is over {MAX_PLACEMENT_WHAT} chars; one short line")
            multi = "\n" in it["sig"].strip()
            what = f'<span class="vc-rel-what">{esc(it["what"])}</span>' if it.get("what") else ""
            row = (
                f'<div class="vc-srow {state}"><span class="vc-badge {state}">{CHUNK_STATES[state]}</span>'
                f'<span class="vc-skind">{esc(it["kind"])} <code>{esc(it["name"])}</code></span>'
                f'<div class="vc-decl{" vc-decl-multi" if multi else ""}"><pre class="vc-code">{esc(it["sig"].strip())}</pre>{what}</div></div>'
            )
            by_dir.setdefault(os.path.dirname(it["file"].strip("/")) or ".", []).append(row)
        cards = "".join(
            f'<div class="vc-scard"><div class="vc-scard-head"><code>{esc(d)}/</code></div>{"".join(rows)}</div>'
            for d, rows in by_dir.items()
        )
        return f'<div class="vc-surface">{cards}</div>'

    def chunk_title(self, tab, key):
        top = self.tabs_by_key.get(key)
        if top is None or "--" in key:
            raise SpecError(f"tab {tab!r}: {key!r} is not a top-level tab key")
        return top["title"]

    def block_layers(self, tab, b):
        """Chunks grouped into layer bands, top to bottom, with the boundary between bands drawn."""
        layers = b.get("layers")
        if not isinstance(layers, list) or not layers:
            raise SpecError(f"tab {tab!r}: layers needs 'layers', each {{name, chunks, boundary?}}")
        out = []
        for i, layer in enumerate(layers):
            where = f"tab {tab!r} layers[{i}]"
            if not isinstance(layer, dict) or set(layer) - {"name", "chunks", "boundary"}:
                raise SpecError(f"{where}: must be an object with only name, chunks and boundary")
            if not isinstance(layer.get("name"), str) or not layer["name"].strip():
                raise SpecError(f"{where}: needs a 'name'")
            chips = []
            for j, c in enumerate(layer.get("chunks") or []):
                if not isinstance(c, dict) or set(c) - {"chunk", "state"}:
                    raise SpecError(f"{where} chunks[{j}]: must be an object with only chunk and state")
                state = c.get("state", "add")
                if state not in CHUNK_STATES:
                    raise SpecError(f"{where} chunks[{j}]: state must be one of {list(CHUNK_STATES)}")
                title = self.chunk_title(tab, c.get("chunk", ""))
                chips.append(f'<a class="vc-chunk {state}" href="#{esc(c["chunk"])}" title="{CHUNK_STATES[state]}">{esc(title)}</a>')
            body = f'<div class="vc-band-chunks">{"".join(chips)}</div>' if chips else '<span class="vc-band-empty">no chunk</span>'
            out.append(f'<div class="vc-band"><span class="vc-band-name">{esc(layer["name"])}</span>{body}</div>')
            if layer.get("boundary") and i < len(layers) - 1:
                out.append(f'<div class="vc-boundary"><span>{esc(layer["boundary"])}</span></div>')
        return f'<div class="vc-layers">{"".join(out)}</div>'

    def block_relationships(self, tab, b):
        """Dependency links: what this chunk uses and what uses it, each row a link to the tab that defines it."""
        entries = b.get("entries")
        if not isinstance(entries, list) or not entries:
            raise SpecError(f"tab {tab!r}: relationships needs 'entries', each {{dir, chunk, tab, what}}")
        groups = OrderedDict((d, []) for d, _ in REL_DIRS)
        for i, e in enumerate(entries):
            where = f"tab {tab!r} relationships entries[{i}]"
            if not isinstance(e, dict) or set(e) - {"dir", "chunk", "tab", "what"}:
                raise SpecError(f"{where}: must be an object with only dir, chunk, tab and what")
            if e.get("dir") not in groups:
                raise SpecError(f"{where}: dir must be one of {list(groups)}")
            top = self.chunk_title(where, e.get("chunk", ""))
            target, text = e["chunk"], top
            if e.get("tab"):
                target = f'{e["chunk"]}--{e["tab"]}'
                if target not in self.tabs_by_key:
                    raise SpecError(f"{where}: {e['chunk']!r} has no second-level tab {e['tab']!r}")
                text = f'{top} · {self.tabs_by_key[target]["title"]}'
            if not isinstance(e.get("what"), str) or not e["what"].strip():
                raise SpecError(f"{where}: needs a non-empty 'what'")
            groups[e["dir"]].append(
                f'<div class="vc-rel-row"><a href="#{esc(target)}">{esc(text)}</a>'
                f'<span class="vc-rel-what">{esc(e["what"])}</span></div>'
            )
        sections = "".join(
            f'<div class="vc-rel"><h4 class="vc-h">{heading}</h4><div class="vc-scard">{"".join(groups[d])}</div></div>'
            for d, heading in REL_DIRS if groups[d]
        )
        return f'<div class="vc-stack">{sections}</div>'

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

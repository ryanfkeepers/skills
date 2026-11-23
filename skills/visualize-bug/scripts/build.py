#!/usr/bin/env python3
"""Render a visualize-bug spec into a tabbed page that explains how a bug occurs.

Usage:
  build.py --spec <spec.json> [--out-dir DIR] [--slug NAME] [--verify]

Same shell as visualize-changes and visualize-design (shared/viz-shell): same layout,
settings, links, hotkeys, flow kit, walkthroughs and outputs. There is no diff: the page
reads only the spec. One block type is its own, `conditions`, a matrix of the factors that
must hold for the bug to fire and the scenarios that prove it. Mermaid diagrams, design
decisions and failure models are switched off; they do not fit a bug.

Writes <slug>.html (standalone) and <slug>.artifact.html (Artifact fragment).
See ../../../shared/viz-shell/blocks.md and ../SKILL.md for the spec format.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "viz-shell"))

from shell import (  # noqa: E402
    LEGEND,
    Page,
    SpecError,
    assemble,
    esc,
    open_under_base,
    output_slug,
    slug_ok,
    verify,
)

ROLES = {
    "required": "must hold, or the bug never happens",
    "contributing": "makes the bug likelier or wider, but is not needed",
    "irrelevant": "looks related, changes nothing",
}
EVIDENCE = {"confirmed": "&#10003; confirmed by a run", "inferred": "&#9676; inferred from the code"}
OUTCOMES = {"bug": "bug", "ok": "ok"}
MAX_FACTORS = 6
MAX_SCENARIOS = 10
MAX_NOTE = 120

BUG_LEGEND = [
    ("Colors", [
        ('<i class="sw add"></i>', "expected behavior"),
        ('<i class="sw mod"></i>', "the tipping point: the moment or condition that tips it toward the bug"),
        ('<i class="sw del"></i>', "wrong behavior: the bug"),
    ]),
    ("Conditions", [
        ('<span class="bg-role required">required</span>', ROLES["required"]),
        ('<span class="bg-role contributing">contributing</span>', ROLES["contributing"]),
        ('<span class="bg-role irrelevant">irrelevant</span>', ROLES["irrelevant"]),
        ('<span class="bg-ev">&#10003;</span>', "the factor's role was confirmed by running it"),
        ('<span class="bg-ev">&#9676;</span>', "the factor's role is inferred from reading the code"),
        ('<span class="bg-tag">minimal repro</span>', "the fewest conditions that still trigger the bug"),
    ]),
] + [section for section in LEGEND if section[0] in ("Flows", "Walkthrough")]

BUG_CSS = """
.bg-matrix { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.bg-matrix th, .bg-matrix td { padding: 10px 12px; border-top: 1px solid var(--line); text-align: center; vertical-align: middle; }
.bg-matrix thead th { border-top: 0; vertical-align: bottom; font-size: var(--step--1); font-weight: 600; }
.bg-matrix tbody th { text-align: left; font-weight: 500; min-width: 12rem; }
.bg-matrix .bg-fname { display: block; margin-block-end: 6px; }
.bg-role { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; border: 1px solid transparent; }
.bg-role.required { color: var(--mod); background: var(--mod-bg); border-color: var(--mod-line); }
.bg-role.contributing { color: var(--accent); background: var(--accent-soft); }
.bg-role.irrelevant { color: var(--muted); background: var(--sunken); border: 1px dashed var(--line); }
.bg-ev { color: var(--muted); font-size: 0.75rem; font-weight: 500; }
.bg-on { color: var(--mod); background: var(--mod-bg); font-weight: 600; }
.bg-on.contributing { color: var(--accent); background: var(--accent-soft); }
.bg-off { color: var(--muted); }
.bg-val { color: var(--ink); font-family: var(--font-mono); font-size: var(--step--1); }
.bg-matrix .irr { opacity: 0.6; }
.bg-out { white-space: nowrap; }
.bg-rate { display: block; margin-block-start: 4px; font-size: var(--step--1); color: var(--muted); }
.bg-matrix tr.repro > * { box-shadow: inset 0 2px 0 var(--accent), inset 0 -2px 0 var(--accent); }
.bg-tag { display: inline-block; margin-inline-start: 8px; padding: 1px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; color: var(--accent); background: var(--accent-soft); white-space: nowrap; }
.bg-factors { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.bg-factors li { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; align-items: baseline; }
.bg-factors .bg-fnote { color: var(--muted); }
"""


def is_off(factor, value):
    """A factor is off when its value is false, or a string the factor lists in 'off' (a graded factor, such as depth)."""
    return value is False or (isinstance(value, str) and value in factor.get("off", []))


class BugPage(Page):
    TOOL = "visualize-bug"
    BLOCK_TYPES = "conditions, walkthrough, html"

    def eyebrow(self):
        return "How the bug happens"

    @staticmethod
    def render_legend():
        rows = []
        for title, entries in BUG_LEGEND:
            items = "".join(f'<li><span class="vc-key">{swatch}</span><span>{esc(text)}</span></li>' for swatch, text in entries)
            rows.append(f"<section><h4>{esc(title)}</h4><ul>{items}</ul></section>")
        return f'<div class="vc-legend-pop" id="vc-legend-pop" role="dialog" aria-label="Legend" hidden>{"".join(rows)}</div>'

    def render(self):
        body, tab_css = super().render()
        return body, tab_css + BUG_CSS

    def render_decisions(self, tab):
        return self.reject_item_section(tab, "decisions")

    def render_failures(self, tab):
        return self.reject_item_section(tab, "failures")

    def reject_item_section(self, tab, field):
        if next(t for t in self.spec["tabs"] if t["key"] == tab).get(field):
            raise SpecError(
                f"tab {tab!r}: '{field}' is not supported; a bug page explains conditions and sequence. "
                "Put the trigger in a 'conditions' block, the sequence in a walkthrough, and anything else in 'etc'"
            )
        return ""

    def block_diagram(self, tab, b):
        raise SpecError(f"tab {tab!r}: Mermaid diagrams are not supported; use a walkthrough for sequences or an html flow")

    def block_conditions(self, tab, b):
        """The factors behind a bug and the scenarios that prove each factor's role."""
        where = f"tab {tab!r} conditions"
        factors = self.check_factors(where, b.get("factors"))
        scenarios = self.check_scenarios(where, b.get("scenarios"), factors)
        self.check_proof(where, factors, scenarios)
        head = "".join(self.factor_head(f) for f in factors)
        rows = "".join(self.scenario_row(s, factors) for s in scenarios)
        table = (
            '<div class="vc-scroll"><table class="bg-matrix">'
            f'<thead><tr><th scope="col">Scenario</th>{head}<th scope="col">Outcome</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
        return table + self.factor_list(factors)

    def check_factors(self, where, factors):
        if not isinstance(factors, list) or not factors:
            raise SpecError(f"{where}: needs 'factors', each {{key, name, role, evidence, note?}}")
        if len(factors) > MAX_FACTORS:
            self.warn(f"{where}: {len(factors)} factors; past {MAX_FACTORS} the pattern is hard to see, drop the ones that do not teach")
        seen = set()
        for i, f in enumerate(factors):
            at = f"{where} factors[{i}]"
            if not isinstance(f, dict) or set(f) - {"key", "name", "role", "evidence", "note", "off"}:
                raise SpecError(f"{at}: must be an object with only key, name, role, evidence, note and off")
            if not isinstance(f.get("off", []), list) or not all(isinstance(o, str) and o for o in f.get("off", [])):
                raise SpecError(f"{at}: 'off' is a list of strings, the values that count as this factor being off")
            if not slug_ok(f.get("key", "")):
                raise SpecError(f"{at}: 'key' must be a lowercase slug (a-z 0-9 - _)")
            if f["key"] in seen:
                raise SpecError(f"{at}: duplicate key {f['key']!r}")
            seen.add(f["key"])
            if not isinstance(f.get("name"), str) or not f["name"].strip():
                raise SpecError(f"{at}: needs a 'name', a short condition in plain words")
            if f.get("role") not in ROLES:
                raise SpecError(f"{at}: role must be one of {list(ROLES)}")
            if f.get("evidence") not in EVIDENCE:
                raise SpecError(f"{at}: evidence must be one of {list(EVIDENCE)}; say whether you ran it or only read the code")
            if len(f.get("note", "")) > MAX_NOTE:
                self.warn(f"{at}: 'note' is over {MAX_NOTE} chars; one short line")
        return factors

    def check_scenarios(self, where, scenarios, factors):
        if not isinstance(scenarios, list) or len(scenarios) < 2:
            raise SpecError(f"{where}: needs at least 2 'scenarios'; one bug case and one ok case, or the conditions are unproven")
        if len(scenarios) > MAX_SCENARIOS:
            self.warn(f"{where}: {len(scenarios)} scenarios; keep the ones that show a factor flipping the outcome")
        keys = {f["key"] for f in factors}
        required = {f["key"] for f in factors if f["role"] == "required"}
        by_key = {f["key"]: f for f in factors}
        minimal = 0
        for i, s in enumerate(scenarios):
            at = f"{where} scenarios[{i}]"
            if not isinstance(s, dict) or set(s) - {"label", "values", "outcome", "rate", "minimal"}:
                raise SpecError(f"{at}: must be an object with only label, values, outcome, rate and minimal")
            if not isinstance(s.get("label"), str) or not s["label"].strip():
                raise SpecError(f"{at}: needs a 'label'")
            if s.get("outcome") not in OUTCOMES:
                raise SpecError(f"{at}: outcome must be 'bug' or 'ok'")
            values = s.get("values")
            if not isinstance(values, dict) or set(values) != keys:
                raise SpecError(f"{at}: 'values' must list every factor key exactly ({sorted(keys)}); use a string such as 'any' for a factor that does not apply")
            for k, v in values.items():
                if not isinstance(v, (bool, str)) or v == "":
                    raise SpecError(f"{at}.values.{k}: true, false, or a short string")
            if s["outcome"] == "bug":
                off = sorted(k for k in required if is_off(by_key[k], values[k]))
                if off:
                    raise SpecError(f"{at}: a bug scenario has required factor(s) {off} off; either they are not required or the scenario is not a bug")
            if s.get("minimal"):
                minimal += 1
                if s["outcome"] != "bug":
                    raise SpecError(f"{at}: 'minimal' marks the smallest scenario that triggers the bug, so its outcome must be 'bug'")
                loud = sorted(f["key"] for f in factors if f["role"] != "required" and values[f["key"]] is True)
                if loud:
                    self.warn(f"{at}: the minimal repro has non-required factor(s) {loud} on; it should need only the required ones")
        if minimal > 1:
            raise SpecError(f"{where}: more than one scenario is marked 'minimal'")
        if not any(s["outcome"] == "bug" for s in scenarios):
            raise SpecError(f"{where}: no scenario ends in the bug")
        if not any(s["outcome"] == "ok" for s in scenarios):
            self.warn(f"{where}: no scenario ends ok; show the near-miss that does not trigger the bug")
        if not minimal:
            self.warn(f"{where}: no scenario is marked 'minimal'; mark the smallest one that triggers the bug")
        return scenarios

    def check_proof(self, where, factors, scenarios):
        """A required factor is proven by an ok scenario where only that factor is off."""
        required = [f["key"] for f in factors if f["role"] == "required"]
        if not required:
            self.warn(f"{where}: no factor is 'required'; a bug that needs nothing would fire every time")
        for k in required:
            others = [r for r in required if r != k]
            by_key = {f["key"]: f for f in factors}
            proven = any(
                s["outcome"] == "ok" and is_off(by_key[k], s["values"][k])
                and not any(is_off(by_key[r], s["values"][r]) for r in others)
                for s in scenarios
            )
            if not proven:
                name = next(f["name"] for f in factors if f["key"] == k)
                self.warn(f"{where}: no ok scenario has only {name!r} off, so it is not shown to be required")

    @staticmethod
    def factor_head(f):
        ev = EVIDENCE[f["evidence"]]
        return (
            f'<th scope="col" class="{"irr" if f["role"] == "irrelevant" else ""}">'
            f'<span class="bg-fname">{esc(f["name"])}</span>'
            f'<span class="bg-role {f["role"]}">{f["role"]}</span><br><span class="bg-ev">{ev}</span></th>'
        )

    @staticmethod
    def scenario_row(s, factors):
        cells = []
        for f in factors:
            v = s["values"][f["key"]]
            cls = "irr " if f["role"] == "irrelevant" else ""
            if v is True:
                cells.append(f'<td class="{cls}bg-on {f["role"]}">yes</td>')
            elif is_off(f, v):
                cells.append(f'<td class="{cls}bg-off">{"no" if v is False else esc(v)}</td>')
            else:
                cells.append(f'<td class="{cls}bg-val">{esc(v)}</td>')
        tag = '<span class="bg-tag">minimal repro</span>' if s.get("minimal") else ""
        pill = "del" if s["outcome"] == "bug" else "add"
        rate = f'<span class="bg-rate">{esc(s["rate"])}</span>' if s.get("rate") else ""
        return (
            f'<tr class="{"repro" if s.get("minimal") else ""}"><th scope="row">{esc(s["label"])}{tag}</th>{"".join(cells)}'
            f'<td class="bg-out"><span class="vc-pill {pill}">{OUTCOMES[s["outcome"]]}</span>{rate}</td></tr>'
        )

    @staticmethod
    def factor_list(factors):
        items = "".join(
            f'<li><span class="bg-role {f["role"]}">{f["role"]}</span>'
            f'<span><strong>{esc(f["name"])}</strong>'
            f'{" " + chr(8212) + " " + esc(f["note"]) if f.get("note") else ""}</span></li>'
            for f in factors
        )
        return f'<ul class="bg-factors">{items}</ul>'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="spec JSON, under /tmp")
    ap.add_argument("--out-dir", help="output directory, under /tmp (default: the spec's directory)")
    ap.add_argument("--slug", help="output basename (default: spec filename without .json / -spec)")
    ap.add_argument("--verify", action="store_true", help="render headlessly and report walkthrough errors and overflow")
    args = ap.parse_args()

    spec_path = Path(os.path.realpath(args.spec))
    out_dir = Path(args.out_dir or spec_path.parent)
    try:
        slug = output_slug(args.slug, spec_path)
        with open_under_base(spec_path) as f:
            spec = json.load(f)
        page = BugPage(spec)
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

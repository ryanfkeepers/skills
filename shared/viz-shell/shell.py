"""Shared page shell for the viz skills (visualize-changes, visualize-design).

The shell owns everything a reader sees as "the application": layout, theming and
color-blind palettes, page width, tabs, links, hotkeys, full-window diagrams,
walkthroughs, the flow kit, item sections, and both output formats (a standalone
document and a claude.ai Artifact fragment). A skill supplies only its content,
and any block types of its own, by subclassing Page.

See blocks.md beside this file for the spec format.
"""
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import flowkit

SHELL_DIR = Path(__file__).resolve().parent
TEMPLATE = SHELL_DIR / "template.html"

MAX_OVERVIEW_SENTENCES = 4
MAX_LEDE_CHARS = 180
MAX_ITEMS = 12
MAX_DECL_LINES = 20
MAX_LINE_CHARS = 280

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"  # pinned; jsDelivr is on the Artifact CSP allowlist
STATES = {"add": "new", "mod": "changed", "del": "removed", "same": "unchanged"}
MAX_WALK_STEPS = 16
MAX_WALK_WHAT = 160
DIAGRAM_MESSAGES = 8
MESSAGE_LINE = re.compile(r"^\s*[\w.]+\s*--?>>?[+-]?\s*[\w.]+\s*:", re.MULTILINE)
BRANCHING_LINE = re.compile(r"^\s*(alt|opt|else)\b", re.MULTILINE)
ITEM_STATES = {"add": "new", "mod": "changed", "del": "removed", "legacy": "legacy handling"}
ICON_ATTRS = 'viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
ICON_LEGEND = f'<svg {ICON_ATTRS}><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>'
ICON_THEME = f'<svg {ICON_ATTRS}><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></svg>'
ICON_EYE = f'<svg {ICON_ATTRS}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>'
ICON_WIDTH = f'<svg {ICON_ATTRS}><path d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4"/></svg>'
PREF_MENUS = [
    ("theme", "Theme", "Match your system, or force light or dark", ICON_THEME,
     [("auto", "Match system"), ("light", "Light"), ("dark", "Dark")]),
    ("palette", "Colorblind palette", "Recolors new, changed and removed", ICON_EYE,
     [("default", "None"), ("protanopia", "Protanopia"), ("deuteranopia", "Deuteranopia"), ("tritanopia", "Tritanopia")]),
    ("width", "Page width", "How wide the page draws in the window", ICON_WIDTH,
     [("auto", "Auto")] + [(str(w), f"{w}%") for w in range(10, 101, 10)]),
]
LEGEND = [
    ("States", [
        ('<i class="sw add"></i>', "new, also a new package in the tree"),
        ('<i class="sw mod"></i>', "changed"),
        ('<i class="sw del"></i>', "removed"),
        ('<span class="vc-badge legacy">legacy</span>', "legacy handling: how existing data or clients are still treated"),
        ('<span class="vc-was-demo">was</span>', "the previous behavior of a changed item, under a rule"),
    ]),
    ("Failure models", [
        ('<span class="vc-item-key if">IF:</span>', "the condition that fails"),
        ('<span class="vc-item-key then">THEN:</span>', "the failure stops the operation"),
        ('<span class="vc-item-key then cont">THEN:</span>', "the failure is handled and processing continues"),
    ]),
    ("Flows", [
        ('<span class="vc-step term sw-pill"></span>', "entry or exit"),
        ('<svg class="sw-dia" viewBox="0 0 28 16" aria-hidden="true"><polygon points="14,1 27,8 14,15 1,8"/></svg>', "a decision; each answer is a branch"),
        ('<i class="sw alt"></i>', "an alternate or fallback path"),
        ('<span class="sw-glyph">&#9632;</span>', "the path ends here"),
        ('<span class="sw-glyph err">&#10005;</span>', "the path ends in an error"),
        ('<span class="sw-glyph">&#8595;</span>', "the path continues to the next step"),
        ('<span class="sw-glyph warn">&#9888;</span>', "a condition on a step, with its outcome"),
    ]),
    ("Walkthrough", [
        ('<span class="vc-wt-key-step">3</span>', "a step; click any step to jump to it"),
        ('<span class="vc-wt-key-box ok">ok</span>', "the ok path, drawn in its own box"),
        ('<span class="vc-wt-key-box failure">&#10005; failure</span>', "the failure path, drawn in its own box"),
        ('<span class="sw-glyph">&#9632;</span>', "a path ends here; otherwise it rejoins"),
    ]),
    ("Sequence diagrams", [
        ('<i class="sw span"></i>', "a dotted box marks a new, changed or removed span"),
    ]),
]
GRACEFUL = re.compile(r"\b(logged|dropped|swallow\w*|ignored|skipped|left out|not returned|retried|retries|counted)\b", re.IGNORECASE)
STOPS = re.compile(r"\b([45]\d\d|rejected|fails? the run|does not start|to the caller|aborts?)\b", re.IGNORECASE)


esc = html.escape


class SpecError(Exception):
    pass



def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])", text.strip())
    return [p for p in parts if p.strip()]



def slug_ok(key):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key))


def title_slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "walkthrough"



ACTIVE_TAGS = ("script", "style", "iframe", "object", "embed", "base", "meta", "link", "form")
ACTIVE_TAG = re.compile(rf"<\s*({'|'.join(ACTIVE_TAGS)})\b", re.IGNORECASE)
URL_ATTRS = {"href", "src", "action", "formaction", "xlink:href", "values", "from", "to"}


class ActiveMarkupFinder(HTMLParser):
    """Finds the first active tag or attribute; parsing keeps a quoted '>' from hiding the rest of a tag."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = None

    def handle_starttag(self, tag, attrs):
        if self.found:
            return
        if tag in ACTIVE_TAGS:
            self.found = f"<{tag}>"
            return
        for name, value in attrs:
            # attribute values arrive entity-decoded; browsers also drop control chars before reading a URL scheme
            scheme = re.sub(r"[\x00-\x20]", "", value or "").lower()
            if name.startswith("on") or (name in URL_ATTRS and "javascript:" in scheme):
                self.found = f"<{tag} {name}=>"
                return

    handle_startendtag = handle_starttag


def active_markup(fragment):
    m = ACTIVE_TAG.search(fragment)
    if m:
        return m.group(0)
    finder = ActiveMarkupFinder()
    finder.feed(fragment)
    finder.close()
    return finder.found


FROM_HEADS = re.compile(r"\b(before|was|old|from|previous(ly)?|prior|current)\b")
TO_HEADS = re.compile(r"\b(after|now|new|to|proposed)\b")


def cell_text(cell):
    return html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip().lower()


def from_to_table(fragment):
    """Header of the first html table that compares a before state to an after state, or None.

    That is a table with separate from and to columns, or one whose cells hold "x → y".
    """
    for table in re.findall(r"<table\b.*?</table\s*>", fragment, flags=re.DOTALL | re.IGNORECASE):
        rows = re.findall(r"<tr\b.*?</tr\s*>", table, flags=re.DOTALL | re.IGNORECASE)
        if not rows:
            continue
        head = [cell_text(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]\s*>", rows[0], flags=re.DOTALL | re.IGNORECASE)]
        froms = {i for i, h in enumerate(head) if FROM_HEADS.search(h)}
        tos = {i for i, h in enumerate(head) if TO_HEADS.search(h)}
        cells = re.findall(r"<td\b[^>]*>(.*?)</td\s*>", table, flags=re.DOTALL | re.IGNORECASE)
        if any(i != j for i in froms for j in tos) or any(re.search(r"→|&rarr;| -> ", c) for c in cells):
            return " | ".join(head)
    return None



class Page:
    """The page every viz skill shares: header, settings menus, tabs, overview, blocks, and item sections.

    Subclasses add their own block types (block_<type>) and fill the hooks below.
    """

    TOOL = "viz-shell"
    BLOCK_TYPES = "diagram, walkthrough, html"

    def __init__(self, spec):
        self.spec = spec
        self.warnings = []
        self.block_ids = {}

    def warn(self, msg):
        self.warnings.append(msg)

    # ---- hooks

    def eyebrow(self):
        return ""

    def begin_tab(self, t):
        pass

    def end_tab_blocks(self, t):
        pass

    def render_tree(self, tab):
        return ""

    def check_coverage(self):
        pass

    def render_footer(self):
        date = datetime.date.today().isoformat()
        return f'<footer class="vc-foot">Generated {date} with {esc(self.TOOL)}.</footer>'

    def validate(self):
        spec = self.spec
        for field in ("title", "overview", "tabs"):
            if field not in spec:
                raise SpecError(f"spec is missing required field {field!r}")
        if "subtitle" in spec:
            raise SpecError("'subtitle' is not supported; the header shows the title and range only")
        self.reject_multiline(spec, "spec")
        words = len(spec["title"].split())
        if words > 5:
            self.warn(f"title has {words} words; aim for a 2-4 word name")
        summary = spec["overview"].get("summary", "").strip()
        if not summary:
            raise SpecError("overview.summary is required")
        n = len(sentences(summary))
        if n > MAX_OVERVIEW_SENTENCES:
            raise SpecError(f"overview.summary has {n} sentences; the limit is {MAX_OVERVIEW_SENTENCES}")
        tabs = spec["tabs"]
        if not tabs:
            raise SpecError("spec needs at least one tab besides the overview")
        seen = {"overview"}
        for t in tabs:
            key = t.get("key", "")
            if not slug_ok(key):
                raise SpecError(f"tab key {key!r} must be a lowercase slug (a-z 0-9 - _)")
            if key in seen:
                raise SpecError(f"duplicate tab key {key!r}")
            seen.add(key)
            if not t.get("title"):
                raise SpecError(f"tab {key!r} needs a title")
            if len(t.get("lede", "")) > MAX_LEDE_CHARS:
                self.warn(f"tab {key!r} lede is over {MAX_LEDE_CHARS} chars; keep it to one sentence")
            if not t.get("blocks"):
                raise SpecError(f"tab {key!r} has no blocks")
            if "questions" in t:
                raise SpecError(f"tab {key!r}: 'questions' is not supported; the page shows the design, the room weighs it")

    def reject_multiline(self, node, where):
        """Code belongs nowhere on this page; multi-line strings are how it sneaks in."""
        if isinstance(node, dict):
            for k, v in node.items():
                if node.get("type") == "diagram" and k in ("before", "after"):
                    continue
                if k == "sig" and "file" in node:
                    self.check_decl(v, where)
                    continue
                if node.get("type") == "html" and k == "html":
                    self.check_html_code(v, where)
                    continue
                self.reject_multiline(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self.reject_multiline(v, f"{where}[{i}]")
        elif isinstance(node, str):
            if "\n" in node.strip():
                raise SpecError(f"{where}: multi-line text. This page shows no code blocks; use a diagram, a boundary, or one line")
            if len(node) > MAX_LINE_CHARS and where != "spec.overview.summary":
                self.warn(f"{where}: {len(node)} chars; trim to one short line")

    @staticmethod
    def check_decl(sig, where):
        """Declarations may span lines (an interface), but stay declarations, not bodies."""
        for side, text in ((sig, None),) if isinstance(sig, str) else sig.items():
            text = side if text is None else text
            if text and text.count("\n") + 1 > MAX_DECL_LINES:
                raise SpecError(f"{where}.sig: over {MAX_DECL_LINES} lines; show the declaration, not the implementation")

    @staticmethod
    def check_html_code(fragment, where):
        for m in re.finditer(r"<(pre|code)\b[^>]*>(.*?)</\1\s*>", fragment, flags=re.DOTALL | re.IGNORECASE):
            if "\n" in m.group(2).strip() or "<br" in m.group(2).lower():
                raise SpecError(f"{where}: html block contains a multi-line <{m.group(1)}>; this page shows no code blocks")

    def render(self):
        self.validate()
        tabs = self.spec["tabs"]
        panels = [self.render_tab(t) for t in tabs]
        keys = ["overview"] + [t["key"] for t in tabs]

        radios = "".join(
            f'<input type="radio" class="vc-radio" name="vc-tab" id="vc-t-{k}" value="{k}"'
            f'{" checked" if k == "overview" else ""} aria-label="{esc(self.tab_title(k))}">'
            for k in keys
        )
        labels = ['<label for="vc-t-overview">Overview</label>']
        for i, t in enumerate(tabs, 1):
            labels.append(
                f'<label for="vc-t-{t["key"]}"><span class="vc-num">{i}</span>{esc(t["title"])}{self.badge(t)}</label>'
            )
        body = (
            self.render_header()
            + radios
            + f'<nav class="vc-tabs" aria-label="Agenda">{"".join(labels)}</nav>'
            + '<main class="vc-panels">'
            + f'<section class="vc-panel" id="vc-p-overview">{self.render_overview(tabs)}</section>'
            + "".join(panels)
            + "</main>"
            + self.render_footer()
        )
        self.check_coverage()
        return body, "\n".join(self.tab_css(k) for k in keys)

    @staticmethod
    def badge(t):
        return f' <span class="vc-badge flag">{esc(t["badge"])}</span>' if t.get("badge") else ""

    def tab_title(self, key):
        if key == "overview":
            return "Overview"
        return next(t["title"] for t in self.spec["tabs"] if t["key"] == key)

    @staticmethod
    def tab_css(k):
        return (
            f"#vc-t-{k}:checked ~ .vc-panels #vc-p-{k} {{ position: static; visibility: visible; pointer-events: auto; }}\n"
            f'#vc-t-{k}:checked ~ .vc-tabs label[for="vc-t-{k}"] {{ color: var(--ink); border-bottom-color: var(--accent); }}\n'
            f'#vc-t-{k}:focus-visible ~ .vc-tabs label[for="vc-t-{k}"] {{ outline: 2px solid var(--accent); outline-offset: -2px; }}'
        )

    def render_header(self):
        s = self.spec
        eyebrow = esc(s.get("eyebrow") or self.eyebrow())
        buttons = [self.icon_button("legend", "Legend", ICON_LEGEND, popup="vc-legend-pop")]
        menus = []
        for key, title, subtitle, icon, options in PREF_MENUS:
            buttons.append(self.icon_button(key, title, icon, popup=f"vc-menu-{key}", menu=True))
            items = "".join(
                f'<button type="button" role="menuitemradio" aria-checked="false" data-value="{value}" tabindex="-1">'
                f'<span>{esc(label)}</span><span class="vc-menu-check" aria-hidden="true">&#10003;</span></button>'
                for value, label in options
            )
            menus.append(
                f'<div class="vc-menu" id="vc-menu-{key}" data-key="{key}" role="menu" aria-labelledby="vc-btn-{key}" hidden>'
                f'<div class="vc-menu-head"><strong>{esc(title)}</strong><span>{esc(subtitle)}</span></div>'
                f'<div class="vc-menu-list">{items}</div></div>'
            )
        return (
            f'<header class="vc-head"><div class="vc-eyebrow">{eyebrow}</div>'
            f'<div class="vc-titlebar"><h1>{esc(s["title"])}</h1>'
            f'<div class="vc-controls"><div class="vc-prefs" hidden>{"".join(buttons)}</div>'
            f'{"".join(menus)}{self.render_legend()}</div></div></header>'
        )

    @staticmethod
    def icon_button(key, title, icon, popup, menu=False):
        haspopup = ' aria-haspopup="menu"' if menu else ""
        return (
            f'<button type="button" class="vc-icon-btn" id="vc-btn-{key}" data-title="{esc(title)}" aria-label="{esc(title)}" title="{esc(title)}"'
            f'{haspopup} aria-expanded="false" aria-controls="{popup}">{icon}</button>'
        )

    @staticmethod
    def render_legend():
        rows = []
        for title, entries in LEGEND:
            items = "".join(f'<li><span class="vc-key">{swatch}</span><span>{esc(text)}</span></li>' for swatch, text in entries)
            rows.append(f'<section><h4>{esc(title)}</h4><ul>{items}</ul></section>')
        return f'<div class="vc-legend-pop" id="vc-legend-pop" role="dialog" aria-label="Legend" hidden>{"".join(rows)}</div>'

    def render_overview(self, tabs):
        ov = self.spec["overview"]
        out = [f'<p class="vc-summary">{esc(ov["summary"].strip())}</p>']
        items = []
        for i, t in enumerate(tabs, 1):
            lede = f'<span class="vc-agenda-lede">{esc(t["lede"])}</span>' if t.get("lede") else ""
            items.append(
                f'<li><label for="vc-t-{t["key"]}"><span class="vc-num">{i}</span>'
                f'<strong>{esc(t["title"])}</strong><span>{self.badge(t)}</span>{lede}</label></li>'
            )
        out.append(f'<div class="vc-block"><h3 class="vc-h">Agenda</h3><ol class="vc-agenda">{"".join(items)}</ol></div>')
        for b in ov.get("blocks", []):
            out.append(self.render_block("overview", b))
        return "".join(out)

    def render_tab(self, t):
        key = t["key"]
        self.begin_tab(t)
        blocks = "".join(self.render_block(key, b) for b in t["blocks"])
        self.end_tab_blocks(t)
        lede = f'<p class="vc-lede">{esc(t["lede"])}</p>' if t.get("lede") else ""
        return (
            f'<section class="vc-panel" id="vc-p-{key}" aria-labelledby="vc-t-{key}">'
            f'<div class="vc-panel-head"><h2>{esc(t["title"])}</h2>{lede}</div>'
            f"{self.render_decisions(key)}{blocks}{self.render_failures(key)}{self.render_tree(key)}{self.render_etc(key)}</section>"
        )

    def render_block(self, tab, b):
        kind = b.get("type")
        fn = getattr(self, f"block_{kind}", None) if kind else None
        if fn is None:
            raise SpecError(f"tab {tab!r}: unknown block type {kind!r} ({self.BLOCK_TYPES})")
        title = f"<h3>{esc(b['title'])}</h3>" if b.get("title") else ""
        caption = f'<p class="vc-caption">{esc(b["caption"])}</p>' if b.get("caption") else ""
        return f'<section class="vc-block vc-block-{kind}"{self.block_link(tab, b)}>{title}{fn(tab, b)}{caption}</section>'

    def block_link(self, tab, b):
        """Attributes that make a titled walkthrough linkable as #<tab>/<block> (and #<tab>/<block>--fullscreen)."""
        if b.get("type") != "walkthrough":
            return ""
        if not b.get("title"):
            self.warn(f"tab {tab!r}: a walkthrough without a 'title' cannot be linked or opened full window from a link")
            return ""
        used = self.block_ids.setdefault(tab, set())
        base = slug = title_slug(b["title"])
        if slug in used:
            self.warn(f"tab {tab!r}: walkthrough title {b['title']!r} gives the link name {slug!r} another walkthrough already has; give it a distinct title")
        n = 1
        while slug in used:
            n += 1
            slug = f"{base}-{n}"
        used.add(slug)
        # "--" never occurs in a title slug, so tab + "--" + slug names one walkthrough even when tab keys contain "-"
        return f' id="vc-b-{tab}--{slug}" data-tab="{tab}" data-block="{slug}" data-title="{esc(b["title"])}"'

    def block_diagram(self, tab, b):
        if not b.get("after"):
            raise SpecError(f"tab {tab!r}: diagram needs 'after' (add 'before' when the design changed)")
        for side in ("before", "after"):
            src = b.get(side)
            if src and not re.match(r"\s*(%%.*\n\s*)*sequenceDiagram\b", src):
                raise SpecError(
                    f"tab {tab!r}: diagram blocks are for sequenceDiagram only; draw flows as an html block "
                    "with the flow kit (references/blocks.md)"
                )
        for side in ("before", "after"):
            self.check_spans(tab, b.get(side) or "")
        messages = len(MESSAGE_LINE.findall(b["after"]))
        if messages > DIAGRAM_MESSAGES or BRANCHING_LINE.search(b["after"]):
            self.warn(
                f"tab {tab!r}: this diagram has {messages} messages or branches (alt/opt/else); "
                "use a walkthrough block for long or branching interactions"
            )
        used = set()
        after = self.mermaid(b["after"], used)
        if not b.get("before"):
            return f'<div class="vc-diagram">{after}</div>{self.legend(used)}'
        before = self.mermaid(b["before"], used)
        stacked = b.get("layout") == "stacked"
        return (
            f'<div class="vc-compare{" vc-stacked" if stacked else ""}">'
            f'<figure><figcaption class="vc-tag vc-tag-before">Before</figcaption><div class="vc-diagram">{before}</div></figure>'
            f'<figure><figcaption class="vc-tag vc-tag-after">After</figcaption><div class="vc-diagram">{after}</div></figure>'
            f"</div>{self.legend(used)}"
        )

    @staticmethod
    def check_spans(tab, src):
        if re.search(r"^\s*Note\s+(over|left of|right of)\b[^:\n]*:\s*(new|changed|removed)\s*$", src, flags=re.MULTILINE | re.IGNORECASE):
            raise SpecError(f"tab {tab!r}: mark a new, changed, or removed span with 'rect new' ... 'end', not a Note")
        for m in re.finditer(r"^\s*rect\b(.*)$", src, flags=re.MULTILINE):
            if m.group(1).strip() not in ("new", "changed", "removed"):
                raise SpecError(
                    f"tab {tab!r}: 'rect{m.group(1)}' sets its own color; use 'rect new', 'rect changed' or 'rect removed' "
                    "so the theme and color-blind palettes apply"
                )

    @staticmethod
    def mermaid(src, used):
        return f'<pre class="vc-mermaid">{esc(src.strip(chr(10)), quote=False)}</pre>'

    @staticmethod
    def legend(used):
        # one color key lives in the page header; blocks don't restate it
        return ""

    def block_walkthrough(self, tab, b):
        where = f"tab {tab!r} walkthrough"
        lanes = b.get("lanes")
        if not isinstance(lanes, list) or len(lanes) < 2 or not all(isinstance(x, str) and x.strip() for x in lanes) or len(set(lanes)) != len(lanes):
            raise SpecError(f"{where}: 'lanes' needs at least two unique participant names")
        segments = b.get("segments")
        if not isinstance(segments, list) or not segments:
            raise SpecError(f"{where}: needs 'segments', each {{steps}} or {{split}}")
        data, longest = {"lanes": lanes, "segments": []}, 0
        for i, sg in enumerate(segments):
            at = f"{where} segments[{i}]"
            if not isinstance(sg, dict) or ("steps" in sg) == ("split" in sg) or set(sg) - {"steps", "split"}:
                raise SpecError(f"{at}: use exactly one of 'steps' or 'split'")
            if "steps" in sg:
                steps = self.walk_steps(at, lanes, sg["steps"])
                data["segments"].append({"steps": steps})
                longest += len(steps)
                continue
            branches = self.walk_split(at, lanes, sg["split"])
            data["segments"].append({"split": branches})
            longest += max(len(br["steps"]) for br in branches)
            if all(br.get("ends") for br in branches) and i < len(segments) - 1:
                self.warn(f"{at}: every branch ends, but a segment follows it; that segment is unreachable")
        if longest > MAX_WALK_STEPS:
            self.warn(f"{where}: {longest} steps on the longest path; over {MAX_WALK_STEPS} reads as a log, split the flow")
        payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
        return (
            f'<div class="vc-wt"><script type="application/json" class="vc-wt-data">{payload}</script>'
            f'{self.walk_static(data)}</div>'
        )

    def walk_steps(self, where, lanes, steps):
        if not isinstance(steps, list) or not steps:
            raise SpecError(f"{where}: 'steps' must be a non-empty list")
        out = []
        for k, st in enumerate(steps):
            at = f"{where} step {k + 1}"
            if not isinstance(st, dict):
                raise SpecError(f"{at}: must be an object")
            extra = set(st) - {"from", "to", "label", "what", "detail", "state", "ret", "tasks"}
            if extra:
                raise SpecError(f"{at}: unknown field(s) {sorted(extra)}")
            for key in ("from", "to"):
                if st.get(key) not in lanes:
                    raise SpecError(f"{at}: {key!r} must be one of the lanes {lanes}; got {st.get(key)!r}")
            for key in ("label", "what"):
                if not isinstance(st.get(key), str) or not st[key].strip():
                    raise SpecError(f"{at}: needs a non-empty {key!r}")
            if "detail" in st and not isinstance(st["detail"], str):
                raise SpecError(f"{at}: 'detail' must be a string")
            if st.get("state") not in (None, "add", "mod", "del"):
                raise SpecError(f"{at}: state must be one of ['add', 'mod', 'del']")
            if len(st["what"]) > MAX_WALK_WHAT:
                self.warn(f"{at}: 'what' is {len(st['what'])} chars; keep it to one sentence")
            kind = "self" if st["from"] == st["to"] else "ret" if st.get("ret") else ""
            out.append({
                "f": lanes.index(st["from"]), "t": lanes.index(st["to"]), "label": st["label"], "what": st["what"],
                "detail": st.get("detail", ""), "state": st.get("state") or "", "kind": kind,
                "tasks": self.walk_tasks(at, st.get("tasks")),
            })
        return out

    def walk_tasks(self, where, tasks):
        """Consecutive calls between the same two lanes drawn as one step, each listed in the step's panel."""
        if tasks is None:
            return []
        if not isinstance(tasks, list) or not tasks:
            raise SpecError(f"{where}: 'tasks' must be a non-empty list of {{label, what, detail?}}")
        out = []
        for j, tk in enumerate(tasks):
            at = f"{where} task {j + 1}"
            if not isinstance(tk, dict) or set(tk) - {"label", "what", "detail"}:
                raise SpecError(f"{at}: must be an object with only label, what and detail")
            for key in ("label", "what"):
                if not isinstance(tk.get(key), str) or not tk[key].strip():
                    raise SpecError(f"{at}: needs a non-empty {key!r}")
            if "detail" in tk and not isinstance(tk["detail"], str):
                raise SpecError(f"{at}: 'detail' must be a string")
            out.append({"label": tk["label"], "what": tk["what"], "detail": tk.get("detail", "")})
        return out

    def walk_split(self, where, lanes, split):
        if not isinstance(split, list) or len(split) < 2:
            raise SpecError(f"{where}: a split needs at least two branches")
        seen, out = set(), []
        for j, br in enumerate(split):
            at = f"{where} branch {j + 1}"
            if not isinstance(br, dict):
                raise SpecError(f"{at}: must be an object")
            extra = set(br) - {"key", "label", "kind", "ends", "steps"}
            if extra:
                raise SpecError(f"{at}: unknown field(s) {sorted(extra)}")
            key = br.get("key")
            if not isinstance(key, str) or not slug_ok(key) or key in seen:
                raise SpecError(f"{at}: needs a unique lowercase 'key'")
            seen.add(key)
            if not isinstance(br.get("label"), str) or not br["label"].strip():
                raise SpecError(f"{at}: needs a 'label'")
            if br.get("kind") not in ("ok", "failure"):
                raise SpecError(f"{at}: kind must be 'ok' or 'failure'")
            if "ends" in br and not isinstance(br["ends"], bool):
                raise SpecError(f"{at}: 'ends' must be true or false")
            out.append({
                "key": key, "label": br["label"], "kind": br["kind"], "ends": bool(br.get("ends")),
                "steps": self.walk_steps(at, lanes, br.get("steps")),
            })
        if not any(br["kind"] == "ok" for br in out):
            self.warn(f"{where}: a split with no 'ok' branch; name the path the flow normally takes")
        return out

    def walk_static(self, data):
        """Every step as a plain list: what the standalone page shows before (or without) its script."""
        lanes = data["lanes"]

        def steps(items):
            lis = "".join(
                f'<li><strong>{esc(s["label"])}</strong> ({esc(lanes[s["f"]])} → {esc(lanes[s["t"]])}): {esc(s["what"])}'
                + (f' <em>{STATES[s["state"]]}</em>' if s["state"] else "")
                + (
                    "<ol>" + "".join(f'<li><strong>{esc(t["label"])}</strong>: {esc(t["what"])}</li>' for t in s["tasks"]) + "</ol>"
                    if s["tasks"] else ""
                )
                + "</li>"
                for s in items
            )
            return f"<ol>{lis}</ol>"

        parts = []
        for sg in data["segments"]:
            if "steps" in sg:
                parts.append(steps(sg["steps"]))
                continue
            alts = "".join(
                f'<li><strong>{esc(br["label"])}</strong>{" (ends the flow)" if br["ends"] else ""}{steps(br["steps"])}</li>'
                for br in sg["split"]
            )
            parts.append(f"<ul>{alts}</ul>")
        return f'<div class="vc-wt-static">{"".join(parts)}</div>'

    def check_items(self, tab, field, required):
        items = next(t for t in self.spec["tabs"] if t["key"] == tab).get(field) or []
        if len(items) > MAX_ITEMS:
            self.warn(f"tab {tab!r}: {len(items)} {field}; keep the ones a reader needs to understand the behavior")
        failures = field == "failures"
        allowed = set(required) | {"state", "was"} | ({"continues"} if failures else set())
        for i, it in enumerate(items):
            where = f"tab {tab!r} {field}[{i}]"
            if not isinstance(it, dict):
                raise SpecError(f"{where}: must be an object with {', '.join(required)}")
            for k in required:
                if not isinstance(it.get(k), str) or not it[k].strip():
                    raise SpecError(f"{where}: needs a non-empty {k!r}")
            extra = set(it) - allowed
            if extra:
                raise SpecError(f"{where}: unknown field(s) {sorted(extra)}; allowed: {', '.join(sorted(allowed))}")
            if "state" in it and it["state"] not in ITEM_STATES:
                raise SpecError(f"{where}: state must be one of {list(ITEM_STATES)}")
            if it.get("was") and it.get("state") != "mod":
                raise SpecError(f"{where}: 'was' only goes with state 'mod'")
            if it.get("state") == "mod" and not it.get("was"):
                raise SpecError(
                    f"{where}: a changed item must say what it was; if you cannot state the old behavior from the base "
                    "revision, it is new: use state 'add'"
                )
            if failures:
                self.check_failure(where, it)
            elif isinstance(it.get("was", ""), dict):
                raise SpecError(f"{where}: a decision's 'was' is one short phrase, not an object")
            elif it.get("was") and it["was"].strip().lower() == it["statement"].strip().lower():
                raise SpecError(f"{where}: 'was' repeats the statement; say what the behavior used to be")
        return items

    def check_failure(self, where, it):
        was = it.get("was")
        if was is not None and not isinstance(was, dict):
            raise SpecError(f"{where}: a failure's 'was' is {{cause, result}} with the old IF and THEN, not a string")
        if isinstance(was, dict):
            extra = set(was) - {"cause", "result", "continues"}
            if extra or not was:
                raise SpecError(f"{where}.was: use cause, result, and continues; got {sorted(was)}")
        if isinstance(was, dict):
            old = (was.get("cause", it["cause"]), was.get("result", it["result"]), was.get("continues", bool(it.get("continues"))))
            if old == (it["cause"], it["result"], bool(it.get("continues"))):
                raise SpecError(f"{where}.was: every field matches the current text; say what the failure used to be")
        if "continues" in it and not isinstance(it["continues"], bool):
            raise SpecError(f"{where}: 'continues' must be true or false")
        result = it["result"]
        if not it.get("continues") and GRACEFUL.search(result) and not STOPS.search(result):
            self.warn(f"{where}: the result reads as handled and carried on; set 'continues': true so THEN shows blue")
        if it.get("continues") and STOPS.search(result):
            self.warn(f"{where}: 'continues' is true but the result names a stop; check the outcome")

    @staticmethod
    def item_card(state, body, was):
        badge = f'<span class="vc-badge {state}">{ITEM_STATES[state]}</span>' if state else "<span></span>"
        panel = f'<div class="vc-was"><span class="vc-was-label">was</span>{was}</div>' if was else ""
        return f'<div class="vc-item {state or ""}">{badge}<div class="vc-item-main">{body}{panel}</div></div>'

    @staticmethod
    def item_line(key, text, cont=False):
        cls = f"{key} cont" if cont else key
        return f'<div class="vc-item-line"><span class="vc-item-key {cls}">{key.upper()}:</span> <span>{esc(text)}</span></div>'

    def render_section(self, title, cards):
        if not cards:
            return ""
        return f'<section class="vc-block"><h3 class="vc-h">{title}</h3><div class="vc-items">{"".join(cards)}</div></section>'

    def render_decisions(self, tab):
        items = self.check_items(tab, "decisions", ("statement",))
        cards = [
            self.item_card(
                it.get("state"),
                f'<div class="vc-item-text">{esc(it["statement"])}</div>',
                f'<div class="vc-item-text">{esc(it["was"])}</div>' if it.get("was") else "",
            )
            for it in items
        ]
        return self.render_section("Key decisions", cards)

    def render_failures(self, tab):
        items = self.check_items(tab, "failures", ("cause", "result"))
        cards = []
        for it in items:
            cont = bool(it.get("continues"))
            was = it.get("was") or {}
            was_html = ""
            if was:
                was_html = self.item_line("if", was.get("cause", it["cause"])) + self.item_line(
                    "then", was.get("result", it["result"]), was.get("continues", cont)
                )
            cards.append(
                self.item_card(
                    it.get("state"),
                    self.item_line("if", it["cause"]) + self.item_line("then", it["result"], cont),
                    was_html,
                )
            )
        return self.render_section("Failure models", cards)

    def render_etc(self, tab):
        items = next(t for t in self.spec["tabs"] if t["key"] == tab).get("etc") or []
        for i, it in enumerate(items):
            if not isinstance(it, str) or not it.strip():
                raise SpecError(f"tab {tab!r} etc[{i}]: must be a non-empty string")
        if not items:
            return ""
        lis = "".join(f"<li>{esc(it)}</li>" for it in items)
        return f'<section class="vc-block"><h3 class="vc-h">Etc</h3><ul class="vc-etc">{lis}</ul></section>'

    def block_delta(self, tab, b):
        raise SpecError(
            f"tab {tab!r}: delta blocks are gone; list business-level behavior under the tab's 'decisions', "
            "failure handling under 'failures', and anything else under 'etc'"
        )

    def block_note(self, tab, b):
        raise SpecError(f"tab {tab!r}: notes are not supported; show a design consequence as a 'decisions', 'failures' or 'etc' item, or in a diagram")

    def block_html(self, tab, b):
        frag = b.get("html", "")
        for m in re.finditer(r'\b(style|fill|stroke|color|bgcolor)\s*=\s*"([^"]*)"', frag, flags=re.IGNORECASE):
            if re.search(r"#[0-9a-f]{3,8}\b|\b(rgba?|hsla?)\(|\b(red|green|blue|yellow|orange|purple|white|black)\b", m.group(2), flags=re.IGNORECASE):
                raise SpecError(
                    f"tab {tab!r}: html block sets a literal color ({m.group(0)[:60]}); use the kit's state classes "
                    "or var(--token) so the theme and color-blind palettes apply"
                )
        active = active_markup(frag)
        if active:
            raise SpecError(f"tab {tab!r}: html block has active markup ({active[:60]}); html blocks are static")
        head = from_to_table(frag)
        if head is not None:
            raise SpecError(
                f"tab {tab!r}: html table compares before and after ({head}); show the change in before/after "
                "flow panels, or as a 'decisions' or 'failures' item with a 'was' line"
            )
        frag = flowkit.decorate(frag, self.warn, f"tab {tab!r}")
        return f'<div class="vc-html">{frag}</div>'


# ---------------------------------------------------------------- output

def assemble(body, tab_css, title, mode):
    tpl = TEMPLATE.read_text(encoding="utf-8")
    head, rest = tpl.split("<!--VC:BODY-->", 1)
    head = head.replace("{{TITLE}}", esc(title)).replace("{{TAB_CSS}}", tab_css)
    rest = rest.replace("{{MODE}}", mode).replace("{{BODY}}", body)
    # the page renders its own diagrams (not the host's) so theme and palette changes can re-render them
    script = f'<script src="{MERMAID_CDN}"></script>\n'
    if mode == "artifact":
        return head + script + rest
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'{head}</head>\n<body>\n{script}{rest}</body>\n</html>\n'
    )


PROBE = """<script>
(function(){
  var root=document.querySelector('.vc'), t0=Date.now();
  function done(){
    var out={wide:[],mermaid:root.getAttribute('data-mermaid'),width:innerWidth};
    document.querySelectorAll('.vc-radio').forEach(function(r){
      r.checked=true; void document.body.offsetHeight;
      if(document.documentElement.scrollWidth>document.documentElement.clientWidth+1){out.wide.push(r.value);}
    });
    out.errors=[].map.call(document.querySelectorAll('.vc-mermaid-error'),function(n){
      var p=n.closest('.vc-panel');return (p?p.id.replace('vc-p-',''):'?')+': '+n.getAttribute('data-error');});
    out.diagrams=document.querySelectorAll('pre.vc-mermaid').length;
    out.rendered=document.querySelectorAll('pre.vc-mermaid svg').length;
    out.walks=document.querySelectorAll('.vc-wt').length;
    out.walksReady=document.querySelectorAll('.vc-wt[data-wt="ready"]').length;
    out.linked=document.querySelectorAll('.vc-block[data-block] .vc-wt').length;
    // full-window round trip on the first linkable walkthrough: open, address, step with the keyboard, close
    var host=document.querySelector('.vc-block[data-block] .vc-wt[data-wt="ready"]');
    if(host){
      var block=host.closest('.vc-block'), fs={}, cur=function(){var m=document.querySelector('.vc-fs .vc-wt-msg.cur');return m?+m.dataset.i:-1;};
      host.querySelector('.vc-wt-fsbtn').click();
      fs.opened=!!document.querySelector('.vc-fs[open] .vc-wt');
      fs.linked=location.hash==='#'+block.dataset.tab+'/'+block.dataset.block+'--fullscreen';
      var before=cur(), multi=document.querySelectorAll('.vc-fs .vc-wt-msg').length>1;
      document.querySelector('.vc-fs').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
      fs.stepped=!multi||cur()===before+1;
      document.querySelector('.vc-fs-close').click();
      fs.closed=!document.querySelector('.vc-fs[open]')&&block.contains(host);
      fs.restored=location.hash==='#'+block.dataset.tab+'/'+block.dataset.block;
      out.fs=fs;
    }
    root.setAttribute('data-probe',JSON.stringify(out));
  }
  (function wait(){ if(root.getAttribute('data-mermaid')||Date.now()-t0>12000){done();} else {setTimeout(wait,100);} })();
})();
</script>"""

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser",
]


def verify(standalone_path):
    chrome = next((c for c in CHROME_CANDIDATES if shutil.which(c) or os.path.exists(c)), None)
    if not chrome:
        return ["verify skipped: no Chrome/Chromium found"]
    with open_under_base(standalone_path) as f:
        page = f.read().replace("</body>", PROBE + "</body>")
    with tempfile.TemporaryDirectory() as d:
        probe_path = Path(d) / "probe.html"
        probe_path.write_text(page, encoding="utf-8")
        res = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--window-size=400,900",
             "--virtual-time-budget=20000", f"--user-data-dir={d}/profile", "--dump-dom", probe_path.as_uri()],
            check=False, capture_output=True, text=True, timeout=120,
        )
    m = re.search(r'data-probe="([^"]*)"', res.stdout)
    if not m:
        return [f"verify failed: probe did not report (chrome exit {res.returncode}): {res.stderr.strip()[:300]}"]
    data = json.loads(html.unescape(m.group(1)))
    problems = [f"mermaid error in {e}" for e in data["errors"]]
    if data["rendered"] < data["diagrams"] - len(data["errors"]):
        problems.append(f"only {data['rendered']} of {data['diagrams']} diagrams rendered")
    if data.get("walks", 0) != data.get("walksReady", 0):
        problems.append(f"only {data.get('walksReady', 0)} of {data.get('walks', 0)} walkthroughs rendered")
    if data["wide"]:
        problems.append(f"horizontal page scroll at {data['width']}px on tabs: {', '.join(data['wide'])}")
    fs = data.get("fs")
    if fs and not all(fs.values()):
        problems.append(f"full-window walkthrough failed: {', '.join(k for k, ok in fs.items() if not ok)}")
    return problems or [
        f"verify ok: {data['rendered']}/{data['diagrams']} diagrams and {data.get('walksReady', 0)}/{data.get('walks', 0)} "
        f"walkthroughs rendered ({data.get('linked', 0)} linkable), no page overflow at {data['width']}px"
    ]


BASE_DIRECTORY = os.path.realpath("/tmp")


def open_under_base(path, mode="r"):
    # the base-directory guard and the open share one function so path-traversal scanners see the sink guarded
    safe_path = os.path.abspath(os.path.join(BASE_DIRECTORY, os.path.realpath(path)))
    if safe_path.startswith(BASE_DIRECTORY + os.sep):
        if "w" in mode:
            os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        return open(safe_path, mode, encoding="utf-8")
    raise SpecError(f"{str(path)!r} must sit under {BASE_DIRECTORY}")


def output_slug(slug_arg, spec_path):
    slug = slug_arg or re.sub(r"(-spec)?\.json$", "", spec_path.name).lower()
    if not slug_ok(slug):
        raise SpecError(f"output slug {slug!r} must be a lowercase slug (a-z 0-9 - _); pass --slug")
    return slug

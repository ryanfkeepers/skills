#!/usr/bin/env python3
"""Render a visualize-changes spec into a tabbed design-discussion page.

Usage:
  build.py --spec <spec.json> [--from REV] [--to REV] [--repo DIR]
           [--out-dir DIR] [--slug NAME] [--verify]

The spec holds the design story: flow diagrams, boundary maps of exposed
artifacts, and before/after scenarios. The page never shows code bodies or
diff hunks. jj is used only to find which packages changed and to check that
names the spec cites appear in the before/after code.

Writes two files:
  <slug>.html           standalone document (attach to Jira/Confluence)
  <slug>.artifact.html  fragment for the claude.ai Artifact tool
Both load Mermaid (sequence diagrams only) from jsDelivr; without network the
diagrams show as their source text and everything else still renders.

See ../references/blocks.md for the spec format.
"""
import argparse
import datetime
import difflib
import fnmatch
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import diffparse  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "template.html"

MAX_OVERVIEW_SENTENCES = 4
MAX_LEDE_CHARS = 180
MAX_SIG_CHARS = 400
DECL_WRAP_COLS = 80  # wider single-line declarations get their parameter list split, one per line
MAX_DELTA_ROWS = 10
MAX_EXPOSES = 8
MAX_DECL_LINES = 20
MAX_LINE_CHARS = 280

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"  # pinned; jsDelivr is on the Artifact CSP allowlist
STATES = {"add": "new", "mod": "changed", "del": "removed", "same": "unchanged"}
PKG_STATES = {"add": "new", "mod": "changed", "del": "removed", "test": "tests", "doc": "docs only"}
MAX_LANDED_CHARS = 120
TEST_PATH = re.compile(
    r"(_test\.go|_test\.py|\.test\.[cm]?[jt]sx?|\.spec\.[cm]?[jt]sx?)$"
    r"|(^|/)test_[^/]+\.py$"
    r"|(^|/)(tests?|__tests__|testdata|testutils?|testing|fixtures|stubs?|mocks?|mock_[^/]*|[^/]*mocks?)/"
    r"|(_mock\.go|mock_[^/]+\.go)$"
)
DOC_PATH = re.compile(r"(\.(md|mdx|rst|txt|adoc)$)|(^|/)docs?/")
NON_DESIGN_PATH = re.compile(r"(^|/)(go\.sum|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock)$")

esc = html.escape


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- jj access

class Repo:
    def __init__(self, root, rev_from, rev_to):
        self.root = root
        self.rev_from = rev_from
        self.rev_to = rev_to
        self._files = {}
        self._dirs = {}

    def jj(self, *args, check=True):
        res = subprocess.run(
            ["jj", "--no-pager", "--color=never", "-R", self.root, *args],
            capture_output=True, text=True, cwd=self.root,  # jj prints paths relative to cwd
        )
        if check and res.returncode != 0:
            raise SpecError(f"jj {' '.join(args)} failed:\n{res.stderr.strip()}")
        return res

    @property
    def name(self):
        return os.path.basename(self.root.rstrip("/"))

    def rev(self, side):
        return self.rev_from if side == "before" else self.rev_to

    def single_id(self, rev):
        out = self.jj("log", "--no-graph", "-r", rev, "-T", 'change_id.shortest(8) ++ "\\n"').stdout.split()
        if len(out) != 1:
            raise SpecError(f"revset {rev!r} must resolve to exactly one revision, got {len(out)}")
        return out[0]

    def diff(self):
        return self.jj("diff", "--git", "--from", self.rev_from, "--to", self.rev_to).stdout

    def text(self, side, path):
        """File contents on one side of the change, or None if absent there."""
        key = (side, path)
        if key not in self._files:
            quoted = path.replace("\\", "\\\\").replace('"', '\\"')
            res = self.jj("file", "show", "-r", self.rev(side), f'root-file:"{quoted}"', check=False)
            self._files[key] = res.stdout if res.returncode == 0 else None
        return self._files[key]

    def dirs(self, side):
        if side not in self._dirs:
            paths = self.jj("file", "list", "-r", self.rev(side)).stdout.splitlines()
            self._dirs[side] = {os.path.dirname(p) for p in paths}
        return self._dirs[side]


# ---------------------------------------------------------------- helpers

def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])", text.strip())
    return [p for p in parts if p.strip()]


def path_matches(path, pattern):
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path + "/", pattern)
    p = pattern.rstrip("/")
    return path == p or path.startswith(p + "/")


def pkg_matches(pkg_path, pattern):
    """Match a package dir ("a/b/", or "" for the repo root) against a spec pattern."""
    if pattern in ("(root)", ".", "./", "/"):
        return pkg_path == ""
    return bool(pkg_path) and path_matches(pkg_path.rstrip("/"), pattern.rstrip("/"))


def slug_ok(key):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_.~-]*", key))


def has_word(text, word):
    return bool(text) and re.search(rf"(?<![\w$]){re.escape(word)}(?![\w$])", text) is not None


def token_diff(a, b):
    """Return (before_html, after_html) with changed tokens wrapped in del/ins."""
    ta = re.findall(r"\w+|\s+|[^\w\s]", a)
    tb = re.findall(r"\w+|\s+|[^\w\s]", b)
    left, right = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ta, b=tb, autojunk=False).get_opcodes():
        x, y = esc("".join(ta[i1:i2])), esc("".join(tb[j1:j2]))
        if op == "equal":
            left.append(x)
            right.append(y)
            continue
        if x:
            left.append(f"<del>{x}</del>")
        if y:
            right.append(f"<ins>{y}</ins>")
    return "".join(left), "".join(right)


def wrap_params(decl, lang, cols=DECL_WRAP_COLS):
    """Split a too-wide one-line declaration's parameter list all-multiline, never mid-list:

        func (r *Reader) List(
        \tctx context.Context,
        \tuserID string,
        ) ([]string, error)

    Only the parameter list after the name is split; the receiver and results stay put.
    """
    if "\n" in decl or len(decl) <= cols:
        return decl
    start = next((i for i, ch in enumerate(decl) if ch == "(" and i and re.match(r"[\w\]]", decl[i - 1])), None)
    if start is None:
        return decl
    depth, quote, parts, cur, end = 0, None, [], [], None
    for i in range(start + 1, len(decl)):
        ch = decl[i]
        if quote:
            cur.append(ch)
            if ch == quote and decl[i - 1] != "\\":
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                end = i
                break
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if end is None:
        return decl
    parts.append("".join(cur).strip())
    parts = [x for x in parts if x]
    if len(parts) < 2:
        return decl
    indent = "\t" if lang == "go" else "    "
    body = "".join(f"{indent}{x},\n" for x in parts)
    return f"{decl[:start + 1]}\n{body}{decl[end:]}"


def soft_breaks(ident):
    """Escape an identifier and allow line breaks only at camelCase, '_', '.', and '/' boundaries."""
    out = esc(ident)
    out = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "<wbr>", out)
    return re.sub(r"(?<=[_./])", "<wbr>", out)


def strip_scripts(fragment):
    cleaned = re.sub(r"<script\b.*?</script\s*>", "", fragment, flags=re.S | re.I)
    return cleaned, cleaned != fragment


FROM_HEADS = re.compile(r"\b(before|was|old|from|previous(ly)?|prior|current)\b")
TO_HEADS = re.compile(r"\b(after|now|new|to|proposed)\b")
NONE_VALUES = {"", "n/a", "na", "none", "null", "-", "—"}


def cell_text(cell):
    return html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip().lower()


def from_to_table(fragment):
    """Header of the first html table that compares a before state to an after state, or None.

    That is a table with separate from and to columns, or one whose cells hold "x → y".
    """
    for table in re.findall(r"<table\b.*?</table\s*>", fragment, flags=re.S | re.I):
        rows = re.findall(r"<tr\b.*?</tr\s*>", table, flags=re.S | re.I)
        if not rows:
            continue
        head = [cell_text(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]\s*>", rows[0], flags=re.S | re.I)]
        froms = {i for i, h in enumerate(head) if FROM_HEADS.search(h)}
        tos = {i for i, h in enumerate(head) if TO_HEADS.search(h)}
        cells = re.findall(r"<td\b[^>]*>(.*?)</td\s*>", table, flags=re.S | re.I)
        if any(i != j for i in froms for j in tos) or any(re.search(r"→|&rarr;| -> ", c) for c in cells):
            return " | ".join(head)
    return None


def go_owner(text, ident):
    """Find what a Go identifier hangs off: ("struct", "client") for a method or field, ("interface", "Store")."""
    if not text:
        return None
    m = re.search(rf"^func\s*\(\s*\w*\s*\*?\s*([A-Za-z_]\w*)(?:\[[^\]]*\])?\s*\)\s*{re.escape(ident)}\s*[\[(]", text, flags=re.M)
    if m:
        return ("method on", m.group(1))
    current = None
    for line in text.splitlines():
        t = re.match(r"^type\s+([A-Za-z_]\w*)(?:\[[^\]]*\])?\s+(struct|interface)\s*\{", line)
        if t:
            current = (t.group(2), t.group(1))
            continue
        if line.startswith("}"):
            current = None
            continue
        if current and re.match(rf"^\s+{re.escape(ident)}(\s|\(|$)", line):
            return ("method of" if current[0] == "interface" and "(" in line else "field of", f"{current[0]} {current[1]}")
    return None


CODE_LANGS = {".go": "go", ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".py": "py"}
KEYWORDS = {
    "go": "break case chan const continue default defer else fallthrough for func go goto if import interface map "
          "package range return select struct switch type var",
    "ts": "abstract as async await class const constructor declare default enum export extends function implements "
          "import interface keyof let new private protected public readonly return static type typeof var void",
    "py": "def class async await return lambda import from as with yield pass raise",
    "other": "public private protected static final class interface enum void fn pub struct impl trait let mut "
             "return new override virtual abstract async func var const type",
}
BUILTIN_TYPES = {
    "go": "bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune string uint uint8 "
          "uint16 uint32 uint64 uintptr any comparable",
    "ts": "string number boolean any unknown never void null undefined object bigint symbol",
    "py": "int str float bool bytes list dict set tuple None True False self cls",
    "other": "int long float double bool boolean string String void byte char",
}
LEX = {
    lang: re.compile(
        r"(?P<com>//[^\n]*|/\*.*?\*/" + (r"|#[^\n]*" if lang == "py" else "") + r")"
        r"|(?P<str>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`[^`]*`)"
        r"|(?P<num>\b\d[\w.]*)"
        r"|(?P<word>[A-Za-z_$][\w$]*)"
        r"|(?P<sp>\s+)"
        r"|(?P<p>.)",
        re.S,
    )
    for lang in ("go", "ts", "py", "other")
}


def code_lang(path):
    return CODE_LANGS.get(os.path.splitext(path)[1], "other")


def lex(code, lang):
    """Tokens as (css class or "", text) pairs, coarse but stable for declarations."""
    kws, tys = set(KEYWORDS[lang].split()), set(BUILTIN_TYPES[lang].split())
    raw = [(m.lastgroup, m.group()) for m in LEX[lang].finditer(code)]
    out = []
    for i, (kind, text) in enumerate(raw):
        if kind == "word":
            nxt = next((t for k, t in raw[i + 1:] if k != "sp"), "")
            prev = raw[i - 1] if i else ("sp", "\n")
            line_start = i == 0 or (prev[0] == "sp" and "\n" in prev[1])
            if lang == "go" and line_start and nxt not in ("(", "") and text not in kws:
                cls = ""  # struct field or interface embed name: plain, its type carries the color
            elif text in kws:
                cls = "tk-kw"
            elif text in tys:
                cls = "tk-ty"
            elif nxt == "(":
                cls = "tk-fn"
            elif text[:1].isupper() and lang != "py":
                cls = "tk-ty"
            else:
                cls = ""
        else:
            cls = {"com": "tk-com", "str": "tk-str", "num": "tk-num"}.get(kind, "")
        out.append((cls, text))
    return out


def tok_html(tokens):
    return "".join(f'<span class="{c}">{esc(t)}</span>' if c else esc(t) for c, t in tokens)


def highlight(code, lang):
    return tok_html(lex(code, lang))


def highlight_diff(a, b, lang):
    """Highlighted before/after with changed tokens wrapped in del/ins."""
    ta, tb = lex(a, lang), lex(b, lang)
    left, right = [], []
    sm = difflib.SequenceMatcher(a=[t for _, t in ta], b=[t for _, t in tb], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = tok_html(ta[i1:i2]), tok_html(tb[j1:j2])
        if op == "equal":
            left.append(x)
            right.append(y)
            continue
        if x:
            left.append(f"<del>{x}</del>")
        if y:
            right.append(f"<ins>{y}</ins>")
    return "".join(left), "".join(right)


# ---------------------------------------------------------------- packages

class Package:
    def __init__(self, path):
        self.path = path  # directory with trailing slash, "" for repo root
        self.files = []
        self.state = "mod"

    @property
    def label(self):
        return self.path or "(root)/"


def collect_packages(files, repo):
    pkgs = OrderedDict()
    for path, f in files.items():
        if NON_DESIGN_PATH.search(path):
            continue
        d = os.path.dirname(path)
        pkgs.setdefault(d, Package(d + "/" if d else "")).files.append(f)
    for d, p in pkgs.items():
        if all(TEST_PATH.search(f.path) for f in p.files):
            p.state = "test"
        elif all(DOC_PATH.search(f.path) for f in p.files):
            p.state = "doc"
        elif d not in repo.dirs("before"):
            p.state = "add"
        elif d not in repo.dirs("after"):
            p.state = "del"
    return pkgs


# ---------------------------------------------------------------- builder

class Builder:
    def __init__(self, spec, files, repo):
        self.spec = spec
        self.files = files
        self.repo = repo
        self.pkgs = collect_packages(files, repo)
        self.owners = {k.rstrip("*").rstrip("/"): v for k, v in (spec.get("owners") or {}).items()}
        self.warnings = []
        self.tab_pkgs = {}

    def warn(self, msg):
        self.warnings.append(msg)

    # ---- validation

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
                raise SpecError(f"tab key {key!r} must be a lowercase slug (a-z 0-9 - _ . ~)")
            if key in seen:
                raise SpecError(f"duplicate tab key {key!r}")
            seen.add(key)
            if not t.get("title"):
                raise SpecError(f"tab {key!r} needs a title")
            if len(t.get("lede", "")) > MAX_LEDE_CHARS:
                self.warn(f"tab {key!r} lede is over {MAX_LEDE_CHARS} chars; keep it to one sentence")
            if not t.get("blocks"):
                raise SpecError(f"tab {key!r} has no blocks")
            for gone in ("decisions", "questions"):
                if gone in t:
                    raise SpecError(f"tab {key!r}: {gone!r} is not supported; the page shows the design, the room weighs it")

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
        for m in re.finditer(r"<(pre|code)\b[^>]*>(.*?)</\1\s*>", fragment, flags=re.S | re.I):
            if "\n" in m.group(2).strip() or "<br" in m.group(2).lower():
                raise SpecError(f"{where}: html block contains a multi-line <{m.group(1)}>; this page shows no code blocks")

    # ---- page assembly

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
        eyebrow = esc(s.get("eyebrow") or self.revs_label())
        legend = "".join(f'<span><i class="{c}"></i>{PKG_STATES[c]}</span>' for c in ("add", "mod", "del"))
        prefs = (
            '<div class="vc-prefs" hidden>'
            '<label for="vc-theme">Theme</label><select id="vc-theme"><option value="auto">Match system</option>'
            '<option value="light">Light</option><option value="dark">Dark</option></select>'
            '<label for="vc-palette">Colorblind</label><select id="vc-palette"><option value="default">None</option>'
            '<option value="protanopia">Protanopia</option><option value="deuteranopia">Deuteranopia</option>'
            '<option value="tritanopia">Tritanopia</option></select>'
            "</div>"
        )
        return (
            f'<header class="vc-head"><div class="vc-eyebrow">{eyebrow}</div><h1>{esc(s["title"])}</h1>'
            f'<div class="vc-headbar"><div class="vc-legend" aria-label="Color key">{legend}</div>{prefs}</div></header>'
        )

    def revs_label(self):
        return f"{self.repo.name} · {self.repo.single_id(self.repo.rev_from)} → {self.repo.single_id(self.repo.rev_to)}"

    def render_footer(self):
        date = datetime.date.today().isoformat()
        rng = f"{self.repo.rev_from} → {self.repo.rev_to}"
        return f'<footer class="vc-foot">Generated {date} from {esc(rng)} with visualize-changes.</footer>'

    # ---- overview

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

    # ---- tabs

    def render_tab(self, t):
        key = t["key"]
        self.tab_pkgs[key] = set()
        blocks = "".join(self.render_block(key, b) for b in t["blocks"])
        for pat in t.get("areas", []):
            self.claim(key, pat, f"tab {key!r} areas")
        lede = f'<p class="vc-lede">{esc(t["lede"])}</p>' if t.get("lede") else ""
        return (
            f'<section class="vc-panel" id="vc-p-{key}" aria-labelledby="vc-t-{key}">'
            f'<div class="vc-panel-head"><h2>{esc(t["title"])}</h2>{lede}</div>'
            f"{blocks}{self.render_tree(key)}</section>"
        )

    def render_block(self, tab, b):
        kind = b.get("type")
        fn = getattr(self, f"block_{kind}", None) if kind else None
        if fn is None:
            raise SpecError(f"tab {tab!r}: unknown block type {kind!r} (diagram, boundaries, delta, html)")
        title = f"<h3>{esc(b['title'])}</h3>" if b.get("title") else ""
        caption = f'<p class="vc-caption">{esc(b["caption"])}</p>' if b.get("caption") else ""
        return f'<section class="vc-block vc-block-{kind}">{title}{fn(tab, b)}{caption}</section>'

    # ---- where it lands: directory tree from the repo root

    def claim(self, tab, pattern, where):
        hit = {p.path for p in self.pkgs.values() if pkg_matches(p.path, pattern)}
        if not hit:
            raise SpecError(f"{where}: {pattern!r} matches no changed package. Packages:\n  " + self.pkg_list())
        self.tab_pkgs[tab] |= hit

    def claim_file(self, tab, path):
        d = os.path.dirname(path)
        key = d + "/" if d else ""
        if any(p.path == key for p in self.pkgs.values()):
            self.tab_pkgs[tab].add(key)

    def pkg_list(self):
        return "\n  ".join(p.label for p in self.pkgs.values())

    def render_tree(self, tab):
        # tests and mocks are not design; they never appear on the page
        paths = sorted(p for p in self.tab_pkgs.get(tab, ()) if self.pkg_by_path(p).state != "test")
        if not paths:
            return ""
        tree = OrderedDict()
        root_pkg = None
        for p in paths:
            if p == "":
                root_pkg = self.pkg_by_path(p)
                continue
            node = tree
            segs = p.strip("/").split("/")
            for i, seg in enumerate(segs):
                node = node.setdefault(seg, {"_children": OrderedDict(), "_path": "/".join(segs[: i + 1])})
                if i == len(segs) - 1:
                    node["_pkg"] = self.pkg_by_path(p)
                node = node["_children"]
        self.landed = dict(self.spec.get("landed") or {})
        self.landed.update(next(t for t in self.spec["tabs"] if t["key"] == tab).get("landed") or {})
        self.landed = {k.strip("/") if k not in ("(root)",) else "": v for k, v in self.landed.items()}
        for p in paths:
            pkg = self.pkg_by_path(p)
            if pkg.state not in ("test", "doc") and p.strip("/") not in self.landed:
                self.warn(f"tab {tab!r}: no 'landed' sentence for {pkg.label}; say in one line what landed there")
        root_cls = f" vc-pkg {root_pkg.state}" if root_pkg else ""
        root = (
            f'<span class="vc-dir{root_cls}">{esc(self.repo.name)}/</span>{self.owner_tag("")}'
            + (self.landed_tag("") if root_pkg else "")
            + self.tree_ul(tree)
        )
        states = {self.pkg_by_path(p).state for p in paths}
        return (
            '<section class="vc-block"><h3 class="vc-h">Where it lands</h3>'
            f'<div class="vc-tree-wrap"><ul class="vc-tree"><li>{root}</li></ul></div>'
            f"{self.legend(states)}</section>"
        )

    def tree_ul(self, children):
        if not children:
            return ""
        items = []
        for seg, node in sorted(children.items()):
            pkg = node.get("_pkg")
            cls = f"vc-dir vc-pkg {pkg.state}" if pkg else "vc-dir"
            title = f' title="{esc(PKG_STATES[pkg.state])}"' if pkg else ""
            items.append(
                f'<li><span class="{cls}"{title}>{esc(seg)}/</span>{self.owner_tag(node["_path"])}'
                f'{self.landed_tag(node["_path"]) if pkg else ""}{self.tree_ul(node["_children"])}</li>'
            )
        return f'<ul>{"".join(items)}</ul>'

    def landed_tag(self, path):
        text = self.landed.get(path)
        if text and len(text) > MAX_LANDED_CHARS:
            self.warn(f"landed sentence for {path or '(root)'} is over {MAX_LANDED_CHARS} chars")
        return f'<span class="vc-landed">{esc(text)}</span>' if text else ""

    def owner_tag(self, path):
        owner = self.owners.get(path) if path else self.owners.get("")
        return f'<span class="vc-owner">{esc(owner)}</span>' if owner else ""

    def pkg_by_path(self, path):
        return next(p for p in self.pkgs.values() if p.path == path)

    # ---- blocks: diagram

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
    def mermaid(src, used):
        return f'<pre class="vc-mermaid">{esc(src.strip(chr(10)), quote=False)}</pre>'

    @staticmethod
    def legend(used):
        # one color key lives in the page header; blocks don't restate it
        return ""

    # ---- blocks: boundaries

    def block_boundaries(self, tab, b):
        bounds = b.get("boundaries") or []
        if not bounds:
            raise SpecError(f"tab {tab!r}: boundaries block needs 'boundaries'")
        ids, nodes, labels, rows = {}, {}, {}, []
        checked = {}
        for i, bd in enumerate(bounds):
            bid = bd.get("id")
            if not bid or bid in ids:
                raise SpecError(f"tab {tab!r}: each boundary needs a unique 'id' (got {bid!r})")
            ids[bid] = i
            labels[bid] = bd.get("label") or bid
            where = f"tab {tab!r} boundary {bid!r}"
            for pat in bd.get("paths", []):
                self.claim(tab, pat, where)
            exposes = bd.get("exposes") or []
            if len(exposes) > MAX_EXPOSES:
                self.warn(f"{where}: {len(exposes)} exposed artifacts; show the ones this change touches or callers rely on")
            for j, art in enumerate(exposes):
                state, owner = self.check_artifact(tab, art, where)
                key = f"{bid}.{art.get('id') or art['name']}"
                if key in nodes:
                    raise SpecError(f"{where}: two artifacts resolve to {key!r}; give one an 'id' so links can tell them apart")
                nodes[key] = (i, j)
                checked[(i, j)] = (state, owner)
                if state != "same":  # unchanged artifacts give the map context but aren't part of the surface delta
                    d = os.path.dirname(art.get("file", ""))
                    rows.append((d, self.surface_row(art, state, owner, f"{where} {art['name']!r}")))

        incoming = {}  # (i, j or None) -> [(from label, link label, state)]
        for ln in b.get("links") or []:
            src, dst = ln.get("from"), ln.get("to")
            for ref in (src, dst):
                if ref not in ids and ref not in nodes:
                    raise SpecError(
                        f"tab {tab!r}: link endpoint {ref!r} is not a boundary id or 'boundary.artifact'. Known: "
                        + ", ".join(list(ids) + list(nodes))
                    )
            target = nodes[dst] if dst in nodes else (ids[dst], None)
            src_label = labels[src.split(".")[0]] if src in nodes else labels[src]
            if src in nodes:
                bi, aj = nodes[src]
                src_label += "." + (bounds[bi]["exposes"][aj]["name"].split(".")[-1])
            incoming.setdefault(target, []).append((src_label, ln.get("label", ""), ln.get("state", "same")))

        if b.get("map", True):
            cards = [self.boundary_card(i, bd, checked, incoming) for i, bd in enumerate(bounds)]
            graph = f'<div class="vc-bmap">{"<span class=\"vc-bmap-arrow\" aria-hidden=\"true\">→</span>".join(cards)}</div>'
        else:
            graph = ""
        return graph + self.surface_cards(rows)

    @staticmethod
    def surface_cards(rows):
        if not rows:
            return ""
        by_dir = OrderedDict()
        for d, row in rows:
            by_dir.setdefault(d, []).append(row)
        cards = "".join(
            f'<div class="vc-scard"><div class="vc-scard-head"><code>{esc(d)}/</code></div>{"".join(rs)}</div>'
            for d, rs in by_dir.items()
        )
        return f'<div class="vc-surface"><h4 class="vc-h">Exposed surface</h4>{cards}</div>'

    def boundary_card(self, i, bd, checked, incoming):
        """One boundary: what it is, what it exposes (with state and what hangs off what), and who calls in."""
        def calls(key):
            items = incoming.get(key) or []
            return "".join(
                f'<div class="vc-bcall {st}"><span class="vc-arrow">←</span> <strong>{soft_breaks(frm)}</strong>'
                + (f" · {esc(lbl)}" if lbl else "") + "</div>"
                for frm, lbl, st in items
            )
        meta = " · ".join(x for x in (bd.get("kind"), bd.get("owner")) if x)
        state = bd.get("state", "")
        arts = []
        for j, art in enumerate(bd.get("exposes") or []):
            st, owner = checked[(i, j)]
            hang = f'<span class="vc-bhang">{esc(owner[0])} {esc(owner[1])}</span>' if owner else (
                f'<span class="vc-bhang">{esc(art["kind"])}</span>' if art.get("kind") else "")
            arts.append(
                f'<div class="vc-bart {st}"><code>{soft_breaks(art["name"].split(".")[-1])}</code>{hang}{calls((i, j))}</div>'
            )
        body = "".join(arts)
        return (
            f'<div class="vc-bcard {state}{" vc-bcard-ext" if not arts else ""}">'
            f'<div class="vc-bcard-head"><strong>{soft_breaks(bd.get("label") or bd["id"])}</strong>'
            + (f'<span class="vc-bmeta">{esc(meta)}</span>' if meta else "")
            + f"</div>{calls((i, None))}{body}</div>"
        )

    def check_artifact(self, tab, art, where):
        name, path = art.get("name"), art.get("file")
        if not name or not path:
            raise SpecError(f"{where}: each exposed artifact needs 'name' and 'file'")
        where = f"{where} artifact {name!r}"
        self.claim_file(tab, path)
        token = art.get("match") or name.split(".")[-1]
        before = self.repo.text("before", art.get("before_file", path))
        after = self.repo.text("after", path)
        if before is None and after is None:
            raise SpecError(f"{where}: {path!r} is not in either revision")
        in_before, in_after = has_word(before, token), has_word(after, token)
        if not in_before and not in_after:
            raise SpecError(f"{where}: {token!r} does not appear in {path} before or after (set 'match' for endpoints/events)")
        derived = "add" if not in_before else "del" if not in_after else "mod"
        state = art.get("state", derived)
        if state not in STATES:
            raise SpecError(f"{where}: state must be one of {list(STATES)}")
        if state != derived and not (derived == "mod" and state == "same"):
            self.warn(f"{where}: state {state!r} but the code says {derived!r}")
        owner = None
        if art.get("on"):
            owner = tuple(art["on"].split(" ", 1)) if " " in art["on"] else ("on", art["on"])
        elif path.endswith(".go") and not art.get("match"):
            owner = go_owner(after if in_after else before, token)
            if not owner and "." in name:
                owner = ("on", name.split(".")[0])
        if path.endswith(".go") and not art.get("match") and token[:1].islower():
            self.warn(f"{where}: unexported Go name; boundaries show only what the package exposes")
        return state, owner

    def surface_row(self, art, state, owner, where):
        """One row: state, what kind of thing it is (and what it hangs off), its highlighted declaration."""
        sig = art.get("sig") or {}
        if isinstance(sig, str):
            sig = {"before": sig} if state == "del" else {"after": sig}
        for side in ("before", "after"):
            s = sig.get(side)
            if s and "\n" not in s and len(s) > MAX_SIG_CHARS:
                raise SpecError(f"{where}: {side} declaration is over {MAX_SIG_CHARS} chars; elide parameters with …")
        if not sig:
            self.warn(f"{where}: no 'sig'; the surface row will show only the name")
        lang = code_lang(art.get("file", ""))
        b, a = sig.get("before"), sig.get("after")
        # wrap both sides or neither, so the diff shows changed parameters, not a layout change
        cols = 0 if any(x and "\n" not in x and len(x) > DECL_WRAP_COLS for x in (b, a)) else DECL_WRAP_COLS
        b, a = (wrap_params(x, lang, cols) if x else x for x in (b, a))
        if b and a:
            bh, ah = highlight_diff(b, a, lang)
            multi = "\n" in b or "\n" in a
            body = (
                f'<pre class="vc-code vc-was">{bh}</pre><span class="vc-arrow">{"↓" if multi else "→"}</span><pre class="vc-code">{ah}</pre>'
            )
            body = f'<div class="vc-decl{" vc-decl-multi" if multi else ""}">{body}</div>'
        else:
            text = b or a or art["name"].split(".")[-1]
            body = f'<div class="vc-decl"><pre class="vc-code">{highlight(text, lang)}</pre></div>'
        if owner:
            what = f'{esc(owner[0])} <code>{esc(owner[1])}</code>'
        else:
            what = esc(art.get("kind") or "")
        return (
            f'<div class="vc-srow {state}"><span class="vc-badge {state}">{STATES[state]}</span>'
            f'<span class="vc-skind">{what}</span>{body}</div>'
        )

    # ---- blocks: delta, note, html

    def block_delta(self, tab, b):
        rows = b.get("rows") or []
        if not rows:
            raise SpecError(f"tab {tab!r}: delta block needs rows")
        if len(rows) > MAX_DELTA_ROWS:
            self.warn(f"tab {tab!r}: delta has {len(rows)} rows; over {MAX_DELTA_ROWS} reads as a list, keep the ones that change behavior")
        out = []
        for r in rows:
            name = r.get("name", "")
            if any(k in r for k in ("explain", "effect", "note")):
                raise SpecError(f"tab {tab!r}: delta row {name!r}: rows are a label plus before -> after; drop the explanation")
            before, after = self.delta_none(r.get("before")), self.delta_none(r.get("after"))
            if before == after:
                raise SpecError(f"tab {tab!r}: delta row {name!r} has the same before and after; only show what changed")
            out.append(
                f'<div class="vc-drow"><div class="vc-dlabel">{esc(name)}</div>'
                f'<div class="vc-dba">{self.delta_value(before, "vc-dbefore")}'
                f'<span class="vc-arrow">→</span>{self.delta_value(after, "vc-dafter")}</div></div>'
            )
        return f'<div class="vc-delta">{"".join(out)}</div>'

    @staticmethod
    def delta_none(v):
        """Values like n/a and - mean the thing didn't exist on that side; render them all as none."""
        return None if v is None or str(v).strip().lower() in NONE_VALUES else v

    @staticmethod
    def delta_value(v, cls):
        if v is None:
            return '<span class="vc-dnone">none</span>'
        return f'<span class="{cls}">{esc(str(v))}</span>'

    def block_note(self, tab, b):
        raise SpecError(f"tab {tab!r}: notes are not supported; show a design consequence as a delta row or in a diagram")

    def block_html(self, tab, b):
        frag, stripped = strip_scripts(b.get("html", ""))
        if stripped:
            self.warn(f"tab {tab!r}: removed <script> from an html block; html blocks are static")
        for m in re.finditer(r'\b(style|fill|stroke|color|bgcolor)\s*=\s*"([^"]*)"', frag, flags=re.I):
            if re.search(r"#[0-9a-f]{3,8}\b|\b(rgba?|hsla?)\(|\b(red|green|blue|yellow|orange|purple|white|black)\b", m.group(2), flags=re.I):
                raise SpecError(
                    f"tab {tab!r}: html block sets a literal color ({m.group(0)[:60]}); use the kit's state classes "
                    "or var(--token) so the theme and color-blind palettes apply"
                )
        head = from_to_table(frag)
        if head is not None:
            raise SpecError(
                f"tab {tab!r}: html table compares before and after ({head}); use a delta block instead: "
                "one row per changed case, a label, then before -> after, and no unchanged rows"
            )
        if re.search(r'class="[^"]*\bvc-(delta|drow|dlabel|dba|dbefore|dafter)\b', frag):
            raise SpecError(f"tab {tab!r}: html block uses delta classes; use a delta block so its rules apply")
        return f'<div class="vc-html">{frag}</div>'

    # ---- coverage

    def check_coverage(self):
        claimed = set().union(*self.tab_pkgs.values()) if self.tab_pkgs else set()
        missing = [p.label for p in self.pkgs.values() if p.state not in ("test", "doc") and p.path not in claimed]
        if missing:
            self.warn(
                f"{len(missing)} changed package(s) belong to no tab (cite them in a boundary or a tab's 'areas'):\n  "
                + "\n  ".join(missing)
            )


# ---------------------------------------------------------------- output

def assemble(body, tab_css, title, mode):
    tpl = TEMPLATE.read_text()
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
    page = Path(standalone_path).read_text().replace("</body>", PROBE + "</body>")
    with tempfile.TemporaryDirectory() as d:
        probe_path = Path(d) / "probe.html"
        probe_path.write_text(page)
        res = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--window-size=400,900",
             "--virtual-time-budget=20000", f"--user-data-dir={d}/profile", "--dump-dom", probe_path.as_uri()],
            capture_output=True, text=True, timeout=120,
        )
    m = re.search(r'data-probe="([^"]*)"', res.stdout)
    if not m:
        return [f"verify failed: probe did not report (chrome exit {res.returncode}): {res.stderr.strip()[:300]}"]
    data = json.loads(html.unescape(m.group(1)))
    problems = [f"mermaid error in {e}" for e in data["errors"]]
    if data["rendered"] < data["diagrams"] - len(data["errors"]):
        problems.append(f"only {data['rendered']} of {data['diagrams']} diagrams rendered")
    if data["wide"]:
        problems.append(f"horizontal page scroll at {data['width']}px on tabs: {', '.join(data['wide'])}")
    return problems or [f"verify ok: {data['rendered']}/{data['diagrams']} diagrams rendered, no page overflow at {data['width']}px"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--from", dest="rev_from", default="@-", help="revision before the change (default @-)")
    ap.add_argument("--to", dest="rev_to", default="@", help="revision after the change (default @)")
    ap.add_argument("--repo", default=".", help="path inside the jj repo (default .)")
    ap.add_argument("--out-dir", help="output directory (default: the spec's directory)")
    ap.add_argument("--slug", help="output basename (default: spec filename without .json / -spec)")
    ap.add_argument("--verify", action="store_true", help="render headlessly and report diagram errors and overflow")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text())
    root = subprocess.run(["jj", "--no-pager", "-R", args.repo, "root"], capture_output=True, text=True)
    if root.returncode != 0:
        raise SystemExit(f"not a jj repo ({args.repo}): {root.stderr.strip()}")
    repo = Repo(root.stdout.strip(), args.rev_from, args.rev_to)

    try:
        files = diffparse.parse(repo.diff())
        if not files:
            raise SpecError("the diff is empty; check --from/--to")
        builder = Builder(spec, files, repo)
        body, tab_css = builder.render()
    except SpecError as e:
        raise SystemExit(f"error: {e}")

    out_dir = Path(args.out_dir or spec_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = args.slug or re.sub(r"(-spec)?\.json$", "", spec_path.name)
    standalone = out_dir / f"{slug}.html"
    artifact = out_dir / f"{slug}.artifact.html"
    standalone.write_text(assemble(body, tab_css, spec["title"], "standalone"))
    artifact.write_text(assemble(body, tab_css, spec["title"], "artifact"))

    for w in builder.warnings:
        print(f"warning: {w}")
    if not any("belong to no tab" in w for w in builder.warnings):
        print("coverage ok: every changed package belongs to a tab")
    print(f"standalone: {standalone} ({standalone.stat().st_size // 1024} KB)")
    print(f"artifact:   {artifact} ({artifact.stat().st_size // 1024} KB)")
    if args.verify:
        for line in verify(standalone):
            print(line)


if __name__ == "__main__":
    main()

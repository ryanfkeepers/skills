#!/usr/bin/env python3
"""Render a visualize-changes spec into a tabbed design-discussion page.

Usage:
  build.py --spec <spec.json> [--from REV] [--to REV] [--repo DIR]
           [--out-dir DIR] [--slug NAME] [--verify]

The spec holds the design story: flow diagrams, boundary maps of exposed
artifacts, and before/after scenarios. The page never shows code bodies or
diff hunks. The VCS (jj, else git) is used only to find which packages changed
and to check that names the spec cites appear in the before/after code. In git,
--to WORKTREE (the default) includes uncommitted and untracked files.

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
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True  # the skill runs inside the user's repo; keep __pycache__ out of their working copy
sys.path.insert(0, str(Path(__file__).parent))

import flowkit  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "template.html"

MAX_OVERVIEW_SENTENCES = 4
MAX_LEDE_CHARS = 180
MAX_SIG_CHARS = 400
DECL_WRAP_COLS = 80  # wider single-line declarations get their parameter list split, one per line
MAX_ITEMS = 12
MAX_EXPOSES = 8
STRUCT_HIDE_OVER = 5  # an existing struct with more properties than this shows only its changed ones
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


# ---------------------------------------------------------------- repo access

WORKTREE = "WORKTREE"  # git only: the working tree, including uncommitted and untracked files


def run(cmd, root, check=True, env=None):
    res = subprocess.run(cmd, check=False, capture_output=True, encoding="utf-8", errors="replace", cwd=root, env=env)
    if check and res.returncode != 0:
        raise SpecError(f"{' '.join(cmd)} failed:\n{res.stderr.strip()}")
    return res


class Repo:
    """Read-only view of two revisions; subclasses supply the VCS commands."""

    def __init__(self, root, rev_from, rev_to):
        self.root = root
        self.rev_from = rev_from
        self.rev_to = rev_to
        self._files = {}
        self._dirs = {}

    @property
    def name(self):
        return os.path.basename(self.root.rstrip("/"))

    def rev(self, side):
        return self.rev_from if side == "before" else self.rev_to

    def text(self, side, path):
        """File contents on one side of the change, or None if absent there."""
        key = (side, path)
        if key not in self._files:
            self._files[key] = self.show(self.rev(side), path)
        return self._files[key]

    def dirs(self, side):
        if side not in self._dirs:
            self._dirs[side] = {os.path.dirname(p) for p in self.paths(self.rev(side))}
        return self._dirs[side]


class JjRepo(Repo):
    DEFAULT_FROM, DEFAULT_TO = "@-", "@"

    def jj(self, *args, check=True):
        # jj prints paths relative to cwd
        return run(["jj", "--no-pager", "--color=never", "-R", self.root, *args], self.root, check)

    def single_id(self, rev):
        out = self.jj("log", "--no-graph", "-r", rev, "-T", 'change_id.shortest(8) ++ "\\n"').stdout.split()
        if len(out) != 1:
            raise SpecError(f"revset {rev!r} must resolve to exactly one revision, got {len(out)}")
        return out[0]

    def diff(self):
        return self.jj("diff", "--git", "--from", self.rev_from, "--to", self.rev_to).stdout

    def show(self, rev, path):
        quoted = path.replace("\\", "\\\\").replace('"', '\\"')
        res = self.jj("file", "show", "-r", rev, f'root-file:"{quoted}"', check=False)
        return res.stdout if res.returncode == 0 else None

    def paths(self, rev):
        return self.jj("file", "list", "-r", rev).stdout.splitlines()


class GitRepo(Repo):
    DEFAULT_FROM, DEFAULT_TO = "HEAD", WORKTREE

    def __init__(self, root, rev_from, rev_to):
        super().__init__(root, rev_from, rev_to)
        self._trees = {}

    def git(self, *args, check=True, env=None):
        # pin settings that would change paths or diff headers away from what diffparse reads
        cfg = ["-c", "core.quotePath=false", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false"]
        return run(["git", "--no-pager", "-C", self.root, *cfg, *args], self.root, check, env)

    def tree(self, rev):
        """Tree id for a revision; WORKTREE snapshots the working tree without touching the real index."""
        if rev not in self._trees:
            if rev == WORKTREE:
                self._trees[rev] = self.snapshot()
            else:
                res = self.git("rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}", check=False)
                if res.returncode != 0:
                    raise SpecError(f"git revision {rev!r} must resolve to exactly one commit")
                self._trees[rev] = res.stdout.strip()
        return self._trees[rev]

    def snapshot(self):
        index = self.git("rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_index = os.path.join(tmp, "index")
            if os.path.exists(index):
                shutil.copyfile(index, tmp_index)  # reuses the stat cache so unchanged files aren't rehashed
            env = {**os.environ, "GIT_INDEX_FILE": tmp_index}
            self.git("add", "--all", env=env)
            return self.git("write-tree", env=env).stdout.strip()

    def single_id(self, rev):
        self.tree(rev)
        if rev == WORKTREE:
            return "worktree"
        return self.git("rev-parse", "--short=8", rev).stdout.strip()

    def diff(self):
        return self.git(
            "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative", "-M",
            self.tree(self.rev_from), self.tree(self.rev_to),
        ).stdout

    def show(self, rev, path):
        res = self.git("cat-file", "blob", f"{self.tree(rev)}:{path}", check=False)
        return res.stdout if res.returncode == 0 else None

    def paths(self, rev):
        out = self.git("ls-tree", "-r", "-z", "--name-only", "--full-tree", self.tree(rev)).stdout
        return [p for p in out.split("\0") if p]


def open_repo(path, rev_from, rev_to):
    """Prefer jj (including colocated repos), then plain git."""
    for cls, cmd in ((JjRepo, ["jj", "--no-pager", "-R", path, "root"]),
                     (GitRepo, ["git", "-C", path, "rev-parse", "--show-toplevel"])):
        if not shutil.which(cmd[0]):
            continue
        res = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if res.returncode == 0:
            return cls(res.stdout.strip(), rev_from or cls.DEFAULT_FROM, rev_to or cls.DEFAULT_TO)
    raise SystemExit(f"not a jj or git repo: {path}")


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
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key))


def title_slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "walkthrough"


def require_state(state, where):
    if state not in STATES:
        raise SpecError(f"{where}: state must be one of {list(STATES)}")
    return state


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


def go_field_owners(text, ident):
    """Every struct or interface in the text that declares ident as a member, in source order."""
    owners, current = [], None
    for line in (text or "").splitlines():
        t = re.match(r"^type\s+([A-Za-z_]\w*)(?:\[[^\]]*\])?\s+(struct|interface)\s*\{", line)
        if t:
            current = (t.group(2), t.group(1))
            continue
        if line.startswith("}"):
            current = None
            continue
        if current and re.match(rf"^\s+{re.escape(ident)}(\s|\(|$)", line):
            kind = "method of" if current[0] == "interface" and "(" in line else "field of"
            owners.append((kind, f"{current[0]} {current[1]}"))
    return owners


def go_owner(text, ident, prefer=None):
    """Find what a Go identifier hangs off: ("struct", "client") for a method or field, ("interface", "Store").

    When several types declare ident, the one named prefer wins; otherwise the first in the file.
    """
    if not text:
        return None
    m = re.search(rf"^func\s*\(\s*\w*\s*\*?\s*([A-Za-z_]\w*)(?:\[[^\]]*\])?\s*\)\s*{re.escape(ident)}\s*[\[(]", text, flags=re.MULTILINE)
    if m:
        return ("method on", m.group(1))
    owners = go_field_owners(text, ident)
    preferred = [o for o in owners if o[1].split(" ", 1)[1] == prefer]
    return (preferred or owners or [None])[0]


GO_BRACE_NOISE = re.compile(r'"(?:\\.|[^"\\])*"|`[^`]*`|//.*')


def declares_go_type(text, name):
    return bool(text) and re.search(rf"^\s*(?:type\s+)?{re.escape(name)}(?:\[[^\]]*\])?\s+struct\b", text, flags=re.MULTILINE) is not None


def go_struct_fields(text, name):
    """Entries of `type name struct { ... }` with spacing normalized, or None when the struct isn't in the text.

    An entry is one field; a field that opens a nested block spans several lines, re-indented by depth.
    """
    if not text:
        return None
    if re.search(rf"^type\s+{re.escape(name)}(?:\[[^\]]*\])?\s+struct\s*\{{\s*\}}", text, flags=re.MULTILINE):
        return []
    lines = text.splitlines()
    head = re.compile(rf"^type\s+{re.escape(name)}(?:\[[^\]]*\])?\s+struct\s*\{{\s*(//.*)?$")
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None:
        return None
    entries, cur, depth = [], [], 0
    for line in lines[start + 1:]:
        s = re.sub(r"\s+", " ", line.strip())
        if depth == 0 and s.startswith("}"):
            break
        if not s or (not cur and s.startswith("//")):
            continue
        lead = 1 if s.startswith("}") else 0
        depth -= lead
        cur.append("\t" * depth + s if cur else s)
        braces = GO_BRACE_NOISE.sub("", s)
        depth += braces.count("{") - (braces.count("}") - lead)
        if depth == 0:
            entries.append("\n".join(cur))
            cur = []
    return entries


def struct_entry_key(entry):
    return entry.split("\n", 1)[0].split(" ", 1)[0]


def struct_items(before, after):
    """Align field entries: ("same", e) | ("add", e) | ("del", e) | ("mod", old, new), in source order."""
    before, after = before or [], after or []
    items = []
    sm = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            items += [("same", e) for e in before[i1:i2]]
            continue
        old = {struct_entry_key(e): e for e in before[i1:i2]}
        paired = set()
        news = []
        for e in after[j1:j2]:
            k = struct_entry_key(e)
            if k in old:
                paired.add(k)
                news.append(("mod", old[k], e))
            else:
                news.append(("add", e))
        items += [("del", e) for e in before[i1:i2] if struct_entry_key(e) not in paired]
        items += news
    return items


def field_html(entry):
    """Highlight one field entry as it would sit in a struct body, one string per line."""
    return [h for h in highlight("\n" + _indent(entry), "go").lstrip("\n").split("\n")]


def _indent(entry):
    return "\n".join("\t" + line for line in entry.split("\n"))


def struct_item_html(item):
    kind = item[0]
    if kind == "same":
        return field_html(item[1])
    if kind == "mod":
        left, right = highlight_diff("\n" + _indent(item[1]), "\n" + _indent(item[2]), "go")
        return left.lstrip("\n").split("\n") + right.lstrip("\n").split("\n")
    tag = "ins" if kind == "add" else "del"
    return [f"<{tag}>{line}</{tag}>" for line in field_html(item[1])]


CODE_LANGS ={".go": "go", ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".py": "py"}
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
        re.DOTALL,
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
            line_start = i == 0 or (prev[0] == "sp" and ("\n" in prev[1] or i == 1))
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
    if "\n" in a or "\n" in b:
        return diff_lines(a, b, lang)
    return diff_tokens(a, b, lang)


def diff_tokens(a, b, lang):
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


def mark_line(line, lang, tag):
    """Wrap a whole line, from its first non-space character, so its indentation is never highlighted."""
    body = line.lstrip()
    if not body:
        return line
    return f"{line[:len(line) - len(body)]}<{tag}>{highlight(body, lang)}</{tag}>"


def diff_lines(a, b, lang):
    """Line-aware diff for multi-line declarations: a line on one side only is marked whole, a changed line pair token by token."""
    la, lb = a.split("\n"), b.split("\n")
    left, right = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=la, b=lb, autojunk=False).get_opcodes():
        if op == "equal":
            left += [highlight(line, lang) for line in la[i1:i2]]
            right += [highlight(line, lang) for line in lb[j1:j2]]
            continue
        old, new = la[i1:i2], lb[j1:j2]
        for k in range(max(len(old), len(new))):
            x = old[k] if k < len(old) else None
            y = new[k] if k < len(new) else None
            if x is not None and y is not None and difflib.SequenceMatcher(a=x, b=y).ratio() >= 0.5:
                lx, ry = diff_tokens(x, y, lang)
                left.append(lx)
                right.append(ry)
                continue
            if x is not None:
                left.append(mark_line(x, lang, "del"))
            if y is not None:
                right.append(mark_line(y, lang, "ins"))
    return "\n".join(left), "\n".join(right)


# ---------------------------------------------------------------- packages

class Package:
    def __init__(self, path):
        self.path = path  # directory with trailing slash, "" for repo root
        self.paths = []
        self.state = "mod"

    @property
    def label(self):
        return self.path or "(root)/"


def package_paths(f):
    """A rename also lands in its old directory, classified by its old path."""
    paths = [f.old_path, f.path] if f.status == "renamed" else [f.path]
    return [(os.path.dirname(p), p) for p in paths if not NON_DESIGN_PATH.search(p)]


def collect_packages(files, repo):
    pkgs = OrderedDict()
    for f in files.values():
        for d, path in package_paths(f):
            pkgs.setdefault(d, Package(d + "/" if d else "")).paths.append(path)
    for d, p in pkgs.items():
        if all(TEST_PATH.search(path) for path in p.paths):
            p.state = "test"
        elif all(DOC_PATH.search(path) for path in p.paths):
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
        self.tab_pkgs = {"overview": set()}
        self.block_ids = {}

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
            f"{self.render_decisions(key)}{blocks}{self.render_failures(key)}{self.render_tree(key)}{self.render_etc(key)}</section>"
        )

    def render_block(self, tab, b):
        kind = b.get("type")
        fn = getattr(self, f"block_{kind}", None) if kind else None
        if fn is None:
            raise SpecError(f"tab {tab!r}: unknown block type {kind!r} (diagram, walkthrough, boundaries, html)")
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
        root_cls = f"vc-dir vc-pkg {root_pkg.state}" if root_pkg else "vc-dir"
        root = (
            self.dir_label(f"{self.repo.name}/", root_cls, "", bool(tree))
            + self.owner_tag("")
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
                f'<li>{self.dir_label(f"{seg}/", cls, title, bool(node["_children"]))}{self.owner_tag(node["_path"])}'
                f'{self.landed_tag(node["_path"]) if pkg else ""}{self.tree_ul(node["_children"])}</li>'
            )
        return f'<ul>{"".join(items)}</ul>'

    @staticmethod
    def dir_label(text, cls, title, expandable):
        """A directory name; one with children toggles its subtree when clicked (the page script handles it)."""
        if not expandable:
            return f'<span class="{cls}"{title}>{esc(text)}</span>'
        return f'<span class="{cls} vc-toggle" role="button" tabindex="0" aria-expanded="true"{title}>{esc(text)}</span>'

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

    # ---- blocks: walkthrough

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

    # ---- blocks: boundaries

    def block_boundaries(self, tab, b):
        bounds = b.get("boundaries") or []
        if not bounds:
            raise SpecError(f"tab {tab!r}: boundaries block needs 'boundaries'")
        for gone in ("links", "map"):
            if gone in b or any(gone in bd for bd in bounds):
                raise SpecError(
                    f"tab {tab!r}: boundaries has no {gone!r}; it shows only the exposed surface. "
                    "Draw calls between boundaries as a diagram block"
                )
        rows, structs = [], OrderedDict()
        for bd in bounds:
            where = f"tab {tab!r} boundary {bd.get('id') or bd.get('label')!r}"
            for pat in bd.get("paths", []):
                self.claim(tab, pat, where)
            exposes = bd.get("exposes") or []
            if len(exposes) > MAX_EXPOSES:
                self.warn(f"{where}: {len(exposes)} exposed artifacts; show the ones this change touches")
            for art in exposes:
                state, owner = self.check_artifact(tab, art, where)
                if state == "same":  # unchanged artifacts are not part of the surface delta
                    continue
                d = os.path.dirname(art["file"])
                struct = self.go_struct_name(art, owner)
                if not struct:
                    rows.append((d, self.surface_row(art, state, owner, f"{where} {art['name']!r}")))
                    continue
                key = (art["file"], struct)
                if key not in structs:
                    structs[key] = {"before_file": art.get("before_file", art["file"]), "arts": []}
                    rows.append((d, key))
                structs[key]["arts"].append((art, state, owner, f"{where} {art['name']!r}"))
        return self.surface_cards([(d, self.resolve_row(r, structs)) for d, r in rows])

    @staticmethod
    def go_struct_name(art, owner):
        """The Go struct an artifact is, or is a field of; None for anything else."""
        if not art["file"].endswith(".go") or art.get("match"):
            return None
        if art.get("kind") == "struct":
            return art["name"].split(".")[-1]
        if owner and owner[0] == "field of" and owner[1].startswith("struct "):
            return owner[1].split(" ", 1)[1]
        return None

    def resolve_row(self, row, structs):
        if isinstance(row, str):
            return row
        file, name = row
        group = structs[row]
        html_row = self.struct_row(file, name, group["before_file"])
        if html_row == "":
            self.warn(f"{file}: struct {name!r} is listed as changed but its fields are identical before and after")
        if html_row is not None:
            return html_row
        # struct declaration not parseable on either side: fall back to each artifact's own declaration
        return "".join(self.surface_row(art, state, owner, where) for art, state, owner, where in group["arts"])

    @staticmethod
    def surface_cards(rows):
        if not rows:
            return ""
        by_dir = OrderedDict()
        for d, row in rows:
            if row:
                by_dir.setdefault(d, []).append(row)
        cards = "".join(
            f'<div class="vc-scard"><div class="vc-scard-head"><code>{esc(d)}/</code></div>{"".join(rs)}</div>'
            for d, rs in by_dir.items()
        )
        return f'<div class="vc-surface"><h4 class="vc-h">Exposed surface</h4>{cards}</div>' if cards else ""

    def check_artifact(self, tab, art, where):
        name, path = art.get("name"), art.get("file")
        if not name or not path:
            raise SpecError(f"{where}: each exposed artifact needs 'name' and 'file'")
        where = f"{where} artifact {name!r}"
        self.claim_file(tab, path)
        if art.get("before_file"):
            self.claim_file(tab, art["before_file"])
        token = art.get("match") or name.split(".")[-1]
        before = self.repo.text("before", art.get("before_file", path))
        after = self.repo.text("after", path)
        if before is None and after is None:
            raise SpecError(f"{where}: {path!r} is not in either revision")
        in_before, in_after = has_word(before, token), has_word(after, token)
        if not in_before and not in_after:
            raise SpecError(f"{where}: {token!r} does not appear in {path} before or after (set 'match' for endpoints/events)")
        derived = "add" if not in_before else "del" if not in_after else "mod"
        state = require_state(art.get("state", derived), where)
        if state != derived and not (derived == "mod" and state == "same"):
            self.warn(f"{where}: state {state!r} but the code says {derived!r}")
        owner = None
        if art.get("on"):
            owner = tuple(art["on"].split(" ", 1)) if " " in art["on"] else ("on", art["on"])
        elif path.endswith(".go") and not art.get("match"):
            prefer = name.split(".")[0] if "." in name else None
            text = after if in_after else before
            owner = go_owner(text, token, prefer) or (in_before and go_owner(before, token, prefer)) or None
            owners = {o[1] for o in go_field_owners(text, token)}
            if len(owners) > 1 and (prefer is None or f"struct {prefer}" not in owners):
                self.warn(f"{where}: {token!r} is declared by {len(owners)} types in {path}; name it Type.{token}")
            if not owner and "." in name:
                owner = ("on", name.split(".")[0])
        if path.endswith(".go") and not art.get("match") and token[:1].islower():
            self.warn(f"{where}: unexported Go name; boundaries show only what the package exposes")
        return state, owner

    def struct_row(self, file, name, before_file):
        """The whole struct, with changed fields marked in place; "" when nothing differs, None when unparseable.

        An existing struct with more than STRUCT_HIDE_OVER properties shows only what changed.
        """
        before_text, after_text = self.repo.text("before", before_file), self.repo.text("after", file)
        before, after = go_struct_fields(before_text, name), go_struct_fields(after_text, name)
        if before is None and after is None:
            return None
        if (before is None and declares_go_type(before_text, name)) or (after is None and declares_go_type(after_text, name)):
            return None
        state = "add" if before is None else "del" if after is None else "mod"
        if state != "mod":
            items = [("same", e) for e in (after if after is not None else before)]
            changed = items
        else:
            items = struct_items(before, after)
            changed = [it for it in items if it[0] != "same"]
            if not changed:
                return ""
        hidden = 0
        if state == "mod" and len(before) > STRUCT_HIDE_OVER:
            hidden = len(items) - len(changed)
            items = changed
        lines = [highlight(f"type {name} struct {{", "go")]
        if hidden:
            lines.append(f'\t<span class="tk-com">// {hidden} {"property" if hidden == 1 else "properties"} hidden</span>')
        for item in items:
            lines.extend(struct_item_html(item))
        lines.append("}")
        return (
            f'<div class="vc-srow {state}"><span class="vc-badge {state}">{STATES[state]}</span>'
            f'<span class="vc-skind">struct <code>{esc(name)}</code></span>'
            f'<div class="vc-decl"><pre class="vc-code">{chr(10).join(lines)}</pre></div></div>'
        )

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
                f'<pre class="vc-code vc-code-before">{bh}</pre><span class="vc-arrow">{"↓" if multi else "→"}</span><pre class="vc-code">{ah}</pre>'
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

    # ---- tab sections: key decisions, failure models, etc

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

    # ---- coverage

    def check_coverage(self):
        # the overview has no Where it lands tree, so a package it cites must still land in a tab
        claimed = set().union(*(pkgs for tab, pkgs in self.tab_pkgs.items() if tab != "overview"))
        missing = [p.label for p in self.pkgs.values() if p.state not in ("test", "doc") and p.path not in claimed]
        if missing:
            self.warn(
                f"{len(missing)} changed package(s) belong to no tab (cite them in a boundary or a tab's 'areas'):\n  "
                + "\n  ".join(missing)
            )


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


def main():
    import diffparse  # after dont_write_bytecode, so no __pycache__ lands in the repo

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="spec JSON, under /tmp")
    ap.add_argument("--from", dest="rev_from", help="revision before the change (default: jj @-, git HEAD)")
    ap.add_argument("--to", dest="rev_to", help=f"revision after the change (default: jj @, git {WORKTREE})")
    ap.add_argument("--repo", default=".", help="path inside the jj or git repo (default .)")
    ap.add_argument("--out-dir", help="output directory, under /tmp (default: the spec's directory)")
    ap.add_argument("--slug", help="output basename (default: spec filename without .json / -spec)")
    ap.add_argument("--verify", action="store_true", help="render headlessly and report diagram errors and overflow")
    args = ap.parse_args()

    repo = open_repo(args.repo, args.rev_from, args.rev_to)
    spec_path = Path(os.path.realpath(args.spec))
    out_dir = Path(args.out_dir or spec_path.parent)

    try:
        slug = output_slug(args.slug, spec_path)
        with open_under_base(spec_path) as f:
            spec = json.load(f)
        files = diffparse.parse(repo.diff())
        if not files:
            raise SpecError("the diff is empty; check --from/--to")
        builder = Builder(spec, files, repo)
        body, tab_css = builder.render()
        standalone, artifact = out_dir / f"{slug}.html", out_dir / f"{slug}.artifact.html"
        for path, mode in ((standalone, "standalone"), (artifact, "artifact")):
            with open_under_base(path, "w") as f:
                f.write(assemble(body, tab_css, spec["title"], mode))
    except SpecError as e:
        raise SystemExit(f"error: {e}")

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

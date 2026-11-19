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

See ../../../shared/viz-shell/blocks.md for the spec format.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "viz-shell"))

from shell import (  # noqa: E402
    Page,
    STATES,
    SpecError,
    assemble,
    esc,
    open_under_base,
    output_slug,
    verify,
)


MAX_SIG_CHARS = 400
DECL_WRAP_COLS = 80  # wider single-line declarations get their parameter list split, one per line
MAX_EXPOSES = 8
STRUCT_HIDE_OVER = 5  # an existing struct with more properties than this shows only its changed ones

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

class Builder(Page):
    TOOL = "visualize-changes"
    BLOCK_TYPES = "diagram, walkthrough, boundaries, html"

    def __init__(self, spec, files, repo):
        super().__init__(spec)
        self.files = files
        self.repo = repo
        self.pkgs = collect_packages(files, repo)
        self.owners = {k.rstrip("*").rstrip("/"): v for k, v in (spec.get("owners") or {}).items()}
        self.tab_pkgs = {"overview": set()}

    def eyebrow(self):
        return self.revs_label()

    def begin_tab(self, t):
        self.tab_pkgs[t["key"]] = set()

    def end_tab_blocks(self, t):
        for pat in t.get("areas", []):
            self.claim(t["key"], pat, f"tab {t['key']!r} areas")

    def revs_label(self):
        return f"{self.repo.name} · {self.repo.single_id(self.repo.rev_from)} → {self.repo.single_id(self.repo.rev_to)}"

    def render_footer(self):
        date = datetime.date.today().isoformat()
        rng = f"{self.repo.rev_from} → {self.repo.rev_to}"
        return f'<footer class="vc-foot">Generated {date} from {esc(rng)} with visualize-changes.</footer>'

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

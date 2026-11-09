"""Unified (git-format) diff parsing for visualize-changes.

Produces one record per file with its status, line counts, and hunks, so the
builder can render ownership maps and diff slices from the real diff text.
"""
import re
from collections import OrderedDict

_DIFF_HEADER = re.compile(r'^diff --git (?:"a/((?:[^"\\]|\\.)*)"|a/(.*)) (?:"b/((?:[^"\\]|\\.)*)"|b/(.*))$')
_C_ESCAPES = {b"a": b"\a", b"b": b"\b", b"t": b"\t", b"n": b"\n", b"v": b"\v", b"f": b"\f", b"r": b"\r"}


def _unquote(token):
    """Decode a git C-quoted path; octal escapes are raw UTF-8 bytes, not code points."""
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        return token
    raw = token[1:-1].encode("utf-8")
    decoded = re.sub(
        rb"\\([0-3][0-7]{2}|.)",
        lambda m: bytes([int(m.group(1), 8)]) if len(m.group(1)) == 3 else _C_ESCAPES.get(m.group(1), m.group(1)),
        raw,
    )
    return decoded.decode("utf-8", errors="replace")


def _header_path(quoted, plain):
    return plain if quoted is None else _unquote(f'"{quoted}"')


class FileDiff:
    def __init__(self, path, old_path):
        self.path = path
        self.old_path = old_path
        self.status = "modified"
        self.binary = False
        self.hunks = []
        self.added = 0
        self.removed = 0

    @property
    def glyph(self):
        return {"added": "A", "deleted": "D", "renamed": "R"}.get(self.status, "M")


def parse(diff_text):
    """Return an OrderedDict of path -> FileDiff, in diff order.

    Hunk indices are 0-based in file order; each hunk is a list of lines
    starting with its @@ header.
    """
    files = OrderedDict()
    cur = None
    hunk = None

    for line in diff_text.splitlines():
        m = _DIFF_HEADER.match(line)
        if m:
            cur = FileDiff(path=_header_path(m.group(3), m.group(4)), old_path=_header_path(m.group(1), m.group(2)))
            files[cur.path] = cur
            hunk = None
            continue
        if cur is None:
            continue

        if hunk is None:
            _parse_header_line(cur, line)
            if line.startswith("@@"):
                hunk = [line]
                cur.hunks.append(hunk)
            continue

        if line.startswith("@@"):
            hunk = [line]
            cur.hunks.append(hunk)
            continue
        hunk.append(line)
        if line.startswith("+"):
            cur.added += 1
        elif line.startswith("-"):
            cur.removed += 1

    if cur is not None:
        _rekey_renames(files)
    return files


def _parse_header_line(cur, line):
    if line.startswith("new file mode"):
        cur.status = "added"
    elif line.startswith("deleted file mode"):
        cur.status = "deleted"
    elif line.startswith("rename from "):
        cur.status = "renamed"
        cur.old_path = _unquote(line[len("rename from "):])
    elif line.startswith("rename to "):
        cur.path = _unquote(line[len("rename to "):])
    elif line.startswith(("Binary files", "GIT binary patch")):
        cur.binary = True


def _rekey_renames(files):
    """Rename records may update .path after insertion; keep keys in sync."""
    for key, fd in list(files.items()):
        if key != fd.path:
            files[fd.path] = files.pop(key)


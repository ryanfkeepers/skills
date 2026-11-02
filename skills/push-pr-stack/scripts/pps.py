"""jj/GitHub plumbing for the push-pr-stack skill.

`plan` reads the stack and proposes bookmarks, bases, titles, and bodies
(written to files, so the model never reads the bodies back). `pr` pushes
one bookmark and creates its PR, or reuses an open one. `link` joins the
PRs with `gh stack`. All output is compact JSON.
"""
import argparse
import json
import os
import re
import subprocess
import sys

SAFE_REF = re.compile(r"^[A-Za-z0-9_./@-]+$")
PR_URL = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/\d+$")
STANDARD_DOCS = {"README", "CHANGELOG", "CLAUDE", "CONTRIBUTING", "LICENSE", "AGENTS",
                 "CODE_OF_CONDUCT", "SECURITY", "SUPPORT", "GOVERNANCE", "NOTICE",
                 "MAINTAINERS", "CODEOWNERS", "AUTHORS", "HISTORY", "UPGRADING"}
PLACEHOLDERS = {"", "wip", "tmp", "todo", "fixup", "."}
FIELD, RECORD = "\x1f", "\x1e"
REV_TEMPLATE = ('change_id.short() ++ "\\x1f" ++ local_bookmarks.map(|b| b.name()).join(",")'
                ' ++ "\\x1f" ++ description ++ "\\x1e"')
SLUG_MAX = 50
BOOKMARK_PREFIX = "kprs/"
GH_STACK_NOT_ENABLED = 9
PUSH_NOISE = re.compile(r"vulnerab|dependabot|^remote:\s*$", re.I)


class CmdError(Exception):
    pass


def run(argv):
    """Run argv (no shell); return (code, stdout, stderr) decoded leniently."""
    proc = subprocess.run(argv, capture_output=True)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def check(runner, argv):
    code, out, err = runner(argv)
    if code != 0:
        raise CmdError(f"{' '.join(argv[:3])}: {(err or out).strip()}")
    return out


def safe_ref(value, what):
    if not SAFE_REF.match(value):
        raise ValueError(f"unsafe {what}: {value}")
    return value


def jj(runner, *args):
    return check(runner, ["jj", "--no-pager", *args])


# ---- plan ----------------------------------------------------------------


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) <= SLUG_MAX:
        return slug
    cut = slug[:SLUG_MAX]
    return cut.rsplit("-", 1)[0] if "-" in cut else cut


def needs_description(description):
    return description.strip().split("\n", 1)[0].strip().lower() in PLACEHOLDERS


def read_revisions(runner, earliest, latest):
    """Revisions oldest first, trunk excluded: (change_id, [local bookmarks], description)."""
    revset = f"({earliest}::{latest}) ~ ::trunk()"
    out = jj(runner, "log", "--no-graph", "-r", revset, "-T", REV_TEMPLATE)
    revs = []
    for record in out.split(RECORD):
        if not record.strip(FIELD + "\n"):
            continue
        change, bookmarks, description = record.lstrip("\n").split(FIELD, 2)
        revs.append((change, [b for b in bookmarks.split(",") if b], description))
    return list(reversed(revs))


def all_bookmark_names(runner):
    out = jj(runner, "bookmark", "list", "--all-remotes", "-T", 'name ++ "\\n"')
    return {line.strip() for line in out.splitlines() if line.strip()}


def trunk_name(runner):
    out = jj(runner, "log", "--no-graph", "-r", "trunk()",
             "-T", 'remote_bookmarks.map(|b| b.name()).join(",")')
    names = [n for n in out.strip().split(",") if n]
    return names[0] if names else "main"


def bookmarks_below(runner, earliest):
    """Local bookmarks on the nearest bookmarked ancestors below the stack, off trunk."""
    out = jj(runner, "log", "--no-graph", "-r", f"heads((trunk()..{earliest}-) & bookmarks())",
             "-T", 'local_bookmarks.map(|b| b.name()).join(",") ++ "\\n"')
    return [line.split(",")[0] for line in out.splitlines() if line.strip()]


def plan_docs(runner, root, change):
    """Root-level .md files this revision added that are not standard project docs."""
    out = jj(runner, "diff", "-r", change, "--summary")
    docs = []
    for line in out.splitlines():
        status, _, path = line.partition(" ")
        stem, ext = os.path.splitext(path)
        if (status == "A" and "/" not in path and ext.lower() == ".md"
                and stem.upper() not in STANDARD_DOCS
                and os.path.exists(os.path.join(root, path))):
            docs.append(path)
    return docs


def unique_name(name, taken):
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name}-{n}", n + 1
    taken.add(candidate)
    return candidate


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def plan_one(runner, root, out_dir, index, rev, ticket, taken, base):
    change, bookmarks, description = rev
    entry = {"change_id": change, "base": base, "needs_description": needs_description(description),
             "bookmark": bookmarks[0] if bookmarks else None,
             "bookmark_exists": bool(bookmarks), "plan_docs": plan_docs(runner, root, change)}
    if len(bookmarks) > 1:
        entry["other_bookmarks"] = bookmarks[1:]
    if entry["needs_description"]:
        return entry

    title, _, body = description.strip().partition("\n")
    if not bookmarks:
        entry["bookmark"] = unique_name(f"{BOOKMARK_PREFIX}{ticket.lower()}/{slugify(title)}", taken)
    stem = os.path.join(out_dir, f"{index:02d}-{change}")
    entry.update(title=title.strip(),
                 title_file=write_text(stem + ".title", title.strip()),
                 body_file=write_text(stem + ".body", body.strip() + "\n"))
    return entry


def cmd_plan(runner, earliest, latest, ticket, out_dir):
    safe_ref(earliest, "revision")
    safe_ref(latest, "revision")
    os.makedirs(out_dir, exist_ok=True)
    root = jj(runner, "root").strip()
    trunk = trunk_name(runner)
    below = bookmarks_below(runner, earliest)
    taken = all_bookmark_names(runner)

    base = below[0] if len(below) == 1 else trunk
    revisions = []
    for i, rev in enumerate(read_revisions(runner, earliest, latest)):
        entry = plan_one(runner, root, out_dir, i + 1, rev, ticket, taken, base)
        revisions.append(entry)
        base = entry["bookmark"] or base
    out = {"trunk": trunk, "revisions": revisions}
    if len(below) > 1:
        out["base_ambiguous"] = below
    return out


# ---- pr ------------------------------------------------------------------


def push_summary(text):
    return [line for line in text.splitlines() if line.strip() and not PUSH_NOISE.search(line)][-4:]


def gh_args(repo):
    return ["--repo", repo] if repo else []


def cmd_pr(runner, bookmark, base, title_file, body_file, repo=None, draft=False, reviewers=()):
    safe_ref(bookmark, "bookmark")
    safe_ref(base, "base")
    code, out, err = runner(["jj", "--no-pager", "git", "push", "--bookmark", bookmark])
    if code != 0:
        raise CmdError(f"jj git push: {(err or out).strip()}")
    pushed = push_summary(err + out)

    existing = json.loads(check(runner, ["gh", "pr", "list", "--head", bookmark, "--state", "open",
                                         "--json", "number,url,baseRefName", *gh_args(repo)]))
    if existing:
        pr = existing[0]
        result = {"bookmark": bookmark, "url": pr["url"], "action": "reused", "push": pushed}
        if pr["baseRefName"] != base:
            check(runner, ["gh", "pr", "edit", str(pr["number"]), "--base", base, *gh_args(repo)])
            result["base_fixed"] = {"from": pr["baseRefName"], "to": base}
        return result

    with open(title_file, encoding="utf-8") as f:
        title = f.read().strip()
    argv = ["gh", "pr", "create", "--head", bookmark, "--base", base, "--title", title,
            "--body-file", body_file, "--assignee", "@me", *gh_args(repo)]
    if draft:
        argv.append("--draft")
    for reviewer in reviewers:
        argv += ["--reviewer", reviewer]
    url = check(runner, argv).strip().splitlines()[-1]
    return {"bookmark": bookmark, "url": url, "action": "created", "push": pushed}


# ---- link ----------------------------------------------------------------


def cmd_link(runner, urls):
    # gh stack link treats any non-URL argument as a branch and creates a PR
    # for it, so anything else is refused before gh runs.
    bad = [u for u in urls if not PR_URL.match(u)]
    if bad:
        raise ValueError(f"not PR URLs: {', '.join(bad)}")
    if len(urls) < 2:
        return {"status": "skipped", "reason": "fewer than two PRs"}
    if runner(["gh", "stack", "--help"])[0] != 0:
        return {"status": "not_installed"}
    code, out, err = runner(["gh", "stack", "link", *urls])
    if code == 0:
        return {"status": "linked"}
    status = "not_enabled" if code == GH_STACK_NOT_ENABLED else "failed"
    return {"status": status, "code": code, "message": (err or out).strip()}


# ---- cli -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="pps.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("plan")
    s.add_argument("earliest")
    s.add_argument("latest")
    s.add_argument("--ticket", required=True)
    s.add_argument("--out", required=True, help="directory for title/body files")

    s = sub.add_parser("pr")
    s.add_argument("bookmark")
    s.add_argument("base")
    s.add_argument("--title-file", required=True)
    s.add_argument("--body-file", required=True)
    s.add_argument("--repo")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--reviewer", action="append", default=[])

    s = sub.add_parser("link")
    s.add_argument("urls", nargs="*")
    return p


def main(argv=None, runner=run):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "plan":
            out = cmd_plan(runner, a.earliest, a.latest, a.ticket, a.out)
        elif a.cmd == "pr":
            out = cmd_pr(runner, a.bookmark, a.base, a.title_file, a.body_file,
                         a.repo, a.draft, a.reviewer)
        else:
            out = cmd_link(runner, a.urls)
    except (CmdError, ValueError, OSError, json.JSONDecodeError) as err:
        print(json.dumps({"status": "error", "message": str(err)}))
        return 1
    print(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

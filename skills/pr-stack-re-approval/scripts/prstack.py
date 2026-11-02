"""GitHub plumbing for the pr-stack-re-approval skill.

Every subcommand prints compact JSON (except `read`, which prints numbered
lines) so the model reads only the fields it judges on. `approve` is the only
subcommand that writes to GitHub.

Exit codes: 0 ok, 1 error, 3 approval refused by a pre-flight guard.
"""
import argparse
import difflib
import json
import re
import subprocess
import sys
import time
from collections import Counter, OrderedDict
from urllib.parse import quote

PR_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FULL_OID = re.compile(r"^[0-9a-f]{40}$")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
GENERATED_MARKER = re.compile(r"Code generated .* DO NOT EDIT")
GENERATED_NAMES = re.compile(
    r"(^|/)(go\.sum|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|"
    r"poetry\.lock|uv\.lock|Gemfile\.lock|[^/]*\.lock|[^/]*\.pb\.go|"
    r"mock_[^/]*|[^/]*_mock\.go|[^/]*\.snap)$|(^|/)__snapshots__/"
)
META_PREFIXES = ("old mode", "new mode", "new file mode", "deleted file mode", "Binary files")
PR_FIELDS = "number,title,url,isDraft,baseRefName,headRefName,state"
GUARD_REFUSED = 3
# Pairing new with dropped hunks is O(new * dropped) sequence matches; past
# this many pairs (a regenerated lockfile) they are reported unpaired.
PAIR_LIMIT = 2500


class GhError(Exception):
    pass


def run_gh(args):
    """Run gh with argv (no shell) and return stdout; raise GhError on failure.

    Decodes leniently: a non-UTF-8 fixture in a diff must not fail the PR.
    """
    proc = subprocess.run(["gh", *args], capture_output=True)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GhError(message or f"gh exited {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def gh_json(gh, args):
    return json.loads(gh(args))


def parse_pr_url(url):
    m = PR_URL.match(url)
    if not m:
        raise ValueError(f"not a GitHub PR URL: {url}")
    return f"{m.group(1)}/{m.group(2)}", int(m.group(3))


def check_repo(repo):
    if not REPO.match(repo):
        raise ValueError(f"bad -R value: {repo}")
    return repo


# ---- stack ---------------------------------------------------------------


def list_prs(gh, repo, flag, branch, state="open"):
    return gh_json(gh, ["pr", "list", "-R", repo, flag, branch, "--state", state,
                        "--limit", "100", "--json", PR_FIELDS])


def find_parent(gh, repo, branch):
    """Return (parent or None, open candidates when ambiguous).

    Prefers the one open PR with this head branch. With none open, falls back
    to the newest merged/closed one, so a finished PR mid-stack does not cut
    off the PRs below it.
    """
    open_prs = list_prs(gh, repo, "--head", branch)
    if len(open_prs) > 1:
        return None, [p["number"] for p in open_prs]
    if open_prs:
        return open_prs[0], []
    finished = list_prs(gh, repo, "--head", branch, state="all")
    return (finished[0] if finished else None), []


def walk_down(gh, repo, start, default_branch):
    """Return (chain bottom-first, ambiguous entries) from start to the default branch."""
    chain, ambiguous, seen = [start], [], {start["number"]}
    cur = start
    while cur["baseRefName"] != default_branch:
        parent, candidates = find_parent(gh, repo, cur["baseRefName"])
        if candidates:
            ambiguous.append({"below": cur["number"], "branch": cur["baseRefName"],
                              "candidates": candidates})
            break
        if parent is None or parent["number"] in seen:
            break
        cur = parent
        seen.add(cur["number"])
        chain.insert(0, cur)
    return chain, ambiguous


def walk_up(gh, repo, chain):
    """Breadth-first walk of every open descendant; returns nodes in BFS order.

    Links along `chain` are kept even when a PR in it is no longer open,
    because the open-only child listing would not find them.
    """
    known = {lower["number"]: upper for lower, upper in zip(chain, chain[1:])}
    bottom = chain[0]
    nodes = OrderedDict([(bottom["number"], dict(bottom, parent=None, children=[]))])
    queue = [bottom["number"]]
    while queue:
        num = queue.pop(0)
        node = nodes[num]
        children = list_prs(gh, repo, "--base", node["headRefName"])
        if num in known and known[num]["number"] not in {c["number"] for c in children}:
            children.append(known[num])
        for child in children:
            if child["number"] in nodes:
                continue
            node["children"].append(child["number"])
            nodes[child["number"]] = dict(child, parent=num, children=[])
            queue.append(child["number"])
    return nodes


def linear_prefix(nodes, bottom):
    """Numbers from the bottom up to and including the first fork point."""
    out, num = [], bottom
    while True:
        out.append(num)
        children = nodes[num]["children"]
        if len(children) != 1:
            return out
        num = children[0]


def cmd_stack(gh, url):
    repo, number = parse_pr_url(url)
    default_branch = gh(["repo", "view", repo, "--json", "defaultBranchRef",
                         "--jq", ".defaultBranchRef.name"]).strip()
    start = gh_json(gh, ["pr", "view", str(number), "-R", repo, "--json", PR_FIELDS])
    chain, ambiguous = walk_down(gh, repo, start, default_branch)
    bottom = chain[0]["number"]
    nodes = walk_up(gh, repo, chain)

    prs = [{"pos": i + 1, "number": n["number"], "title": n["title"], "url": n["url"],
            "state": n["state"], "draft": n["isDraft"], "base": n["baseRefName"],
            "head": n["headRefName"], "parent": n["parent"], "children": n["children"]}
           for i, n in enumerate(nodes.values())]
    return {
        "repo": repo,
        "default_branch": default_branch,
        "bottom_base": chain[0]["baseRefName"],
        "prs": prs,
        "linear": linear_prefix(nodes, bottom),
        "forks": [{"at": n["number"], "children": n["children"]}
                  for n in nodes.values() if len(n["children"]) > 1],
        "ambiguous": ambiguous,
        "not_open": [n["number"] for n in nodes.values() if n["state"] != "OPEN"],
    }


# ---- state ---------------------------------------------------------------

STATE_QUERY = """
query($owner:String!, $repo:String!, $number:Int!,
      $rAfter:String, $tAfter:String, $cAfter:String,
      $wR:Boolean!, $wT:Boolean!, $wC:Boolean!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      title body url headRefOid baseRefName mergeable
      reviews(first:100, after:$rAfter) @include(if:$wR) {
        pageInfo { hasNextPage endCursor }
        nodes { id author { login } state submittedAt body commit { oid } }
      }
      reviewThreads(first:100, after:$tAfter) @include(if:$wT) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved path line originalLine
          comments(first:100) {
            pageInfo { hasNextPage endCursor }
            nodes { author { login } body url createdAt pullRequestReview { id } }
          }
        }
      }
      comments(first:100, after:$cAfter) @include(if:$wC) {
        pageInfo { hasNextPage endCursor }
        nodes { author { login } body url createdAt }
      }
    }
  }
}"""

THREAD_COMMENTS_QUERY = """
query($id:ID!, $after:String) {
  node(id:$id) {
    ... on PullRequestReviewThread {
      comments(first:100, after:$after) {
        pageInfo { hasNextPage endCursor }
        nodes { author { login } body url createdAt pullRequestReview { id } }
      }
    }
  }
}"""

CONNECTIONS = (("reviews", "rAfter", "wR"), ("reviewThreads", "tAfter", "wT"),
               ("comments", "cAfter", "wC"))


def graphql(gh, query, variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        flag = "-F" if isinstance(value, (bool, int)) else "-f"
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        args += [flag, f"{key}={rendered}"]
    return gh_json(gh, args)["data"]


def fetch_pr(gh, repo, number):
    """Fetch the PR with every top-level connection fully paginated."""
    owner, name = repo.split("/")
    cursors = {after: None for _, after, _ in CONNECTIONS}
    wanted = {conn: True for conn, _, _ in CONNECTIONS}
    pr, merged = None, {conn: [] for conn, _, _ in CONNECTIONS}

    while any(wanted.values()):
        variables = {"owner": owner, "repo": name, "number": number, **cursors}
        variables.update({flag: wanted[conn] for conn, _, flag in CONNECTIONS})
        page = graphql(gh, STATE_QUERY, variables)["repository"]["pullRequest"]
        pr = pr or page
        for conn, after, _ in CONNECTIONS:
            if not wanted[conn]:
                continue
            merged[conn] += page[conn]["nodes"]
            info = page[conn]["pageInfo"]
            wanted[conn] = info["hasNextPage"]
            cursors[after] = info["endCursor"]

    for thread in merged["reviewThreads"]:
        finish_thread_comments(gh, thread)
    return dict(pr, **{conn: merged[conn] for conn in merged})


def finish_thread_comments(gh, thread):
    comments = thread["comments"]
    info = comments["pageInfo"]
    while info["hasNextPage"]:
        page = graphql(gh, THREAD_COMMENTS_QUERY,
                       {"id": thread["id"], "after": info["endCursor"]})["node"]["comments"]
        comments["nodes"] += page["nodes"]
        info = page["pageInfo"]


def resolve_mergeable(gh, repo, number, mergeable, sleep, tries=3):
    while mergeable == "UNKNOWN" and tries > 0:
        sleep(3)
        mergeable = gh_json(gh, ["pr", "view", str(number), "-R", repo,
                                 "--json", "mergeable"])["mergeable"]
        tries -= 1
    return mergeable


def login_of(node):
    return (node.get("author") or {}).get("login")


def last_review(reviews, login):
    mine = [r for r in reviews
            if login_of(r) == login and r["state"] != "PENDING" and r.get("submittedAt")]
    return max(mine, key=lambda r: r["submittedAt"], default=None)


def scoped_threads(threads, login, review_id):
    """Threads the user started in the last review, plus their unresolved older ones."""
    out = []
    for t in threads:
        comments = t["comments"]["nodes"]
        if not comments or login_of(comments[0]) != login:
            continue
        first_review = (comments[0].get("pullRequestReview") or {}).get("id")
        from_last = first_review == review_id
        if not from_last and t["isResolved"]:
            continue
        out.append({
            "path": t["path"],
            "line": t["line"] if t["line"] is not None else t["originalLine"],
            "outdated": t["line"] is None,
            "resolved": t["isResolved"],
            "from_last_review": from_last,
            "comments": [{"user": login_of(c) == login, "author": login_of(c),
                          "body": c["body"], "url": c["url"]} for c in comments],
        })
    return out


def cmd_state(gh, repo, number, sleep=time.sleep):
    login = gh(["api", "user", "--jq", ".login"]).strip()
    pr = fetch_pr(gh, repo, number)
    review = last_review(pr["reviews"], login)
    out = {
        "login": login,
        "title": pr["title"],
        "description": pr["body"],
        "url": pr["url"],
        "head": pr["headRefOid"],
        "base": pr["baseRefName"],
        "mergeable": resolve_mergeable(gh, repo, number, pr["mergeable"], sleep),
        "prior_verdict": review and review["state"],
        "reviewed_oid": review and (review.get("commit") or {}).get("oid"),
        "last_review_body": review and review["body"],
        "threads": [],
        "top_level": [],
    }
    if review:
        out["threads"] = scoped_threads(pr["reviewThreads"], login, review["id"])
        out["top_level"] = [{"body": c["body"], "url": c["url"], "created": c["createdAt"]}
                            for c in pr["comments"] if login_of(c) == login]
    return out


# ---- changes -------------------------------------------------------------


def git_unquote(s):
    """Undo git's C-style path quoting ("a/caf\\303\\251") when present."""
    if not (len(s) >= 2 and s.startswith('"') and s.endswith('"')):
        return s
    raw = s[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return raw.encode("latin-1", "replace").decode("utf-8", "replace")


def strip_side(path, side):
    return path[len(side):] if path.startswith(side) else path


def path_from_git_line(line):
    """Destination path from `diff --git a/X b/X`, which may hold spaces or quotes."""
    rest = line[len("diff --git "):]
    if rest.startswith('"'):
        end = 1
        while end < len(rest) and rest[end] != '"':
            end += 2 if rest[end] == "\\" else 1
        return strip_side(git_unquote(rest[end + 2:]), "b/")
    if rest.endswith('"'):
        return strip_side(git_unquote(rest[rest.index(' "') + 1:]), "b/")
    half = (len(rest) - 5) // 2
    if len(rest) % 2 == 0 or rest[half + 2:half + 5] != " b/":
        raise ValueError(f"cannot parse diff header: {line}")
    return rest[half + 5:]


def chunk_path(header):
    """Prefer the explicit rename/+++/--- lines; fall back to the diff --git line."""
    for prefix, side in (("rename to ", ""), ("+++ ", "b/"), ("--- ", "a/")):
        for line in header:
            if line.startswith(prefix):
                path = git_unquote(line[len(prefix):].rstrip("\t"))
                if path != "/dev/null":
                    return strip_side(path, side)
    return path_from_git_line(header[0])


def split_diff(text):
    """Map destination path -> {"header": [...], "hunks": [[@@ line, body...], ...]}.

    Raises instead of skipping a file it cannot parse: a silently dropped
    file would read as "unchanged since review".
    """
    files = OrderedDict()
    for chunk in re.split(r"(?=^diff --git )", text, flags=re.M):
        if not chunk.startswith("diff --git "):
            continue
        header, hunks = [], []
        for line in chunk.rstrip("\n").split("\n"):
            if line.startswith("@@"):
                hunks.append([line])
            elif hunks:
                hunks[-1].append(line)
            else:
                header.append(line)
        files[chunk_path(header)] = {"header": header, "hunks": hunks}

    expected = len(re.findall(r"^diff --git ", text, flags=re.M))
    if expected != len(files) or (text.strip() and not expected):
        raise ValueError(f"parsed {len(files)} of {expected} files in diff")
    return files


def changed_lines(hunk):
    return tuple(line for line in hunk[1:] if line[:1] in "+-")


def hunk_heading(hunk):
    """The enclosing function/section git prints after the second @@."""
    m = HUNK_HEADER.match(hunk[0])
    return hunk[0][m.end():].strip() if m else hunk[0]


def signature(hunk):
    """Changed lines plus the enclosing heading.

    Line shifts and context drift compare equal; the same edit moved to a
    different function does not.
    """
    return (hunk_heading(hunk),) + changed_lines(hunk)


def hunk_start(hunk):
    m = HUNK_HEADER.match(hunk[0])
    return int(m.group(2)) if m else None


def overlap(a, b):
    return sum(block.size for block in
               difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())


def unmatched(reviewed, head):
    """Split into (hunks only at head, hunks only at review) by signature multiset."""
    remaining = Counter(signature(h) for h in reviewed)
    new = []
    for h in head:
        sig = signature(h)
        if remaining[sig] > 0:
            remaining[sig] -= 1
        else:
            new.append(h)
    dropped = []
    for h in reviewed:
        sig = signature(h)
        if remaining[sig] > 0:
            remaining[sig] -= 1
            dropped.append(h)
    return new, dropped


def best_match(h, dropped):
    """The dropped hunk sharing the most changed lines with h, or None."""
    mine = changed_lines(h)
    scored = [(overlap(changed_lines(d), mine), d) for d in dropped]
    score, best = max(scored, key=lambda pair: pair[0], default=(0, None))
    return best if score > 0 else None


def landed(lines, landed_lines):
    return bool(lines) and all(line in landed_lines for line in lines)


def interdiff_hunks(reviewed, head, pair=True, landed_lines=frozenset()):
    """Hunks new at head, dropped since review, or changed (paired by shared lines).

    `landed_lines` holds changed lines the base branch gained since the
    review; a dropped hunk made only of those moved into the base (e.g. a
    squash-merged parent) rather than being reverted.
    """
    new, dropped = unmatched(reviewed, head)
    pair = pair and len(new) * len(dropped) <= PAIR_LIMIT

    out = []
    for h in new:
        best = best_match(h, dropped) if pair else None
        if best is None:
            out.append({"kind": "new", "head_start": hunk_start(h), "lines": h[1:]})
            continue
        dropped.remove(best)
        entry = {"kind": "changed", "head_start": hunk_start(h),
                 "reviewed_start": hunk_start(best), "delta": hunk_delta(best, h)}
        gone = list((Counter(changed_lines(best)) - Counter(changed_lines(h))).elements())
        added = Counter(changed_lines(h)) - Counter(changed_lines(best))
        if not added and landed(gone, landed_lines):
            entry["landed_in_base"] = True
        out.append(entry)
    for d in dropped:
        entry = {"kind": "dropped", "reviewed_start": hunk_start(d),
                 "was": list(changed_lines(d))}
        if landed(entry["was"], landed_lines):
            entry["landed_in_base"] = True
        out.append(entry)
    return out


def hunk_delta(reviewed, head):
    """Diff of the two hunk bodies: first char is review->head, the rest is the PR line."""
    lines = difflib.unified_diff(reviewed[1:], head[1:], lineterm="", n=2)
    return [line for line in lines if not line.startswith(("---", "+++"))]


def pair_renames(reviewed, head):
    """Map head-only path -> reviewed-only path for files moved since the review.

    Candidates share a basename and at least half their changed lines.
    """
    gone = [p for p in reviewed if p not in head]
    pairs = {}
    for path in (p for p in head if p not in reviewed):
        mine = file_signature(head[path])
        best, score = None, 0.0
        for old in gone:
            if old in pairs.values() or old.rsplit("/", 1)[-1] != path.rsplit("/", 1)[-1]:
                continue
            theirs = file_signature(reviewed[old])
            shortest = min(len(mine), len(theirs)) or 1
            ratio = overlap(mine, theirs) / shortest
            if ratio > score:
                best, score = old, ratio
        if best is not None and score >= 0.5:
            pairs[path] = best
    return pairs


def file_signature(entry):
    return [line for hunk in entry["hunks"] for line in changed_lines(hunk)]


def index_line(header):
    return next((line for line in header if line.startswith("index ")), None)


def meta_lines(header):
    return [line for line in header if line.startswith(META_PREFIXES)]


def generated_hint(path, *sides):
    if GENERATED_NAMES.search(path):
        return True
    return any(GENERATED_MARKER.search(line)
               for side in sides if side
               for hunk in side["hunks"] for line in hunk)


def interdiff(reviewed_diff, head_diff, landed_diff=""):
    reviewed, head = split_diff(reviewed_diff), split_diff(head_diff)
    gained = split_diff(landed_diff)
    renames = pair_renames(reviewed, head)
    moved = set(renames.values())
    files = []
    for path in list(head) + [p for p in reviewed if p not in head and p not in moved]:
        old = renames.get(path, path)
        r, h = reviewed.get(old), head.get(path)
        generated = generated_hint(path, r, h)
        hunks = interdiff_hunks(r["hunks"] if r else [], h["hunks"] if h else [],
                                pair=not generated, landed_lines=landed_set(gained.get(old)))
        entry = {"path": path, "in_head_diff": h is not None, "generated_hint": generated}
        if old != path:
            entry["renamed_from"] = old
        if hunks:
            entry["hunks"] = hunks
        if header_changed(r, h):
            entry["header_changed"] = (h or r)["header"]
        if hunks or "header_changed" in entry or old != path:
            files.append(entry)
    return files


def landed_set(entry):
    return frozenset(file_signature(entry)) if entry else frozenset()


def header_changed(r, h):
    """Mode, binary, or empty-file change that the hunks alone would not show.

    Blob ids are compared only when neither side has hunks: a rebase changes
    the index line of every file even when its changed lines are identical.
    """
    if r is None or h is None:
        return not (r or h)["hunks"]
    if meta_lines(r["header"]) != meta_lines(h["header"]):
        return True
    if r["hunks"] or h["hunks"]:
        return False
    return index_line(r["header"]) != index_line(h["header"])


def compare_path(repo, base, oid):
    return f"repos/{repo}/compare/{quote(base, safe='')}...{quote(oid, safe='')}"


def fetch_diff(gh, repo, base, oid):
    return gh(["api", "-H", "Accept: application/vnd.github.diff",
               compare_path(repo, base, oid)])


def merge_base(gh, repo, base, oid):
    return gh(["api", compare_path(repo, base, oid),
               "--jq", ".merge_base_commit.sha"]).strip()


def cmd_changes(gh, repo, number, reviewed, head, base=None):
    link = f"https://github.com/{repo}/pull/{number}/files/{reviewed}..{head}"
    if reviewed == head:
        return {"unchanged": True, "link": link, "files": []}
    if base is None:
        base = gh_json(gh, ["pr", "view", str(number), "-R", repo,
                            "--json", "baseRefName"])["baseRefName"]

    # What the base gained since the review explains parent hunks that left
    # the PR by landing in the base (squash-merge + retarget, parent rebase).
    landed_diff = ""
    reviewed_base = merge_base(gh, repo, base, reviewed)
    if reviewed_base != merge_base(gh, repo, base, head):
        landed_diff = fetch_diff(gh, repo, reviewed_base, base)

    files = interdiff(fetch_diff(gh, repo, base, reviewed),
                      fetch_diff(gh, repo, base, head), landed_diff)
    return {"unchanged": not files, "link": link, "files": files}


# ---- read ----------------------------------------------------------------


def parse_range(spec):
    m = re.match(r"^(\d+)-(\d+)$", spec or "")
    if not m:
        raise ValueError(f"--lines wants A-B, got {spec}")
    return int(m.group(1)), int(m.group(2))


def cmd_read(gh, repo, ref, path, lines=None):
    text = gh(["api", "-H", "Accept: application/vnd.github.raw",
               f"repos/{repo}/contents/{quote(path)}?ref={quote(ref, safe='')}"])
    rows = text.split("\n")
    first, last = parse_range(lines) if lines else (1, len(rows))
    first = max(first, 1)
    return "\n".join(f"{i}\t{rows[i - 1]}" for i in range(first, min(last, len(rows)) + 1))


# ---- approve -------------------------------------------------------------


def current_head(gh, repo, number):
    return gh_json(gh, ["pr", "view", str(number), "-R", repo,
                        "--json", "headRefOid,mergeable"])


def cmd_approve(gh, repo, number, oid, body=None):
    """Approve pinned to oid; refuse if the head moved or the PR conflicts.

    GitHub still counts an approval of an older commit unless the repo
    dismisses stale approvals, so a push racing the POST is detected after
    the fact and reported as `approved_stale`; it cannot be prevented.
    """
    if not FULL_OID.match(oid):
        raise ValueError("approve needs the full 40-char head oid")
    cur = current_head(gh, repo, number)
    if cur["headRefOid"] != oid:
        return GUARD_REFUSED, {"status": "head_moved", "head": cur["headRefOid"]}
    if cur["mergeable"] == "CONFLICTING":
        return GUARD_REFUSED, {"status": "conflicting"}

    args = ["api", "-X", "POST", f"repos/{repo}/pulls/{number}/reviews",
            "-f", "event=APPROVE", "-f", f"commit_id={oid}"]
    if body is not None:
        args += ["-f", f"body={body}"]
    try:
        gh(args)
    except GhError as err:
        return 1, {"status": "error", "message": str(err)}
    after = current_head(gh, repo, number)["headRefOid"]
    if after != oid:
        return GUARD_REFUSED, {"status": "approved_stale", "commit": oid, "head": after}
    return 0, {"status": "approved", "commit": oid}


# ---- cli -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="prstack.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stack")
    s.add_argument("url")

    for name in ("state", "changes", "approve"):
        s = sub.add_parser(name)
        s.add_argument("-R", dest="repo", required=True)
        s.add_argument("number", type=int)
        if name == "changes":
            s.add_argument("reviewed")
            s.add_argument("head")
            s.add_argument("--base")
        if name == "approve":
            s.add_argument("oid")
            s.add_argument("--body-file")

    s = sub.add_parser("read")
    s.add_argument("-R", dest="repo", required=True)
    s.add_argument("ref")
    s.add_argument("path")
    s.add_argument("--lines")
    return p


def dispatch(gh, a):
    """Return (exit code, payload); payload is a str for `read`, else JSON-able."""
    if a.cmd == "stack":
        return 0, cmd_stack(gh, a.url)
    repo = check_repo(a.repo)
    if a.cmd == "state":
        return 0, cmd_state(gh, repo, a.number)
    if a.cmd == "changes":
        return 0, cmd_changes(gh, repo, a.number, a.reviewed, a.head, a.base)
    if a.cmd == "read":
        return 0, cmd_read(gh, repo, a.ref, a.path, a.lines)
    body = None
    if a.body_file:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
    return cmd_approve(gh, repo, a.number, a.oid, body)


def main(argv=None, gh=run_gh):
    args = build_parser().parse_args(argv)
    try:
        code, payload = dispatch(gh, args)
    except (GhError, ValueError, KeyError, OSError) as err:
        code, payload = 1, {"status": "error", "message": str(err)}
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())

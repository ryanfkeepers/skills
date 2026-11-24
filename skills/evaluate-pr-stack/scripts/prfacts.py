"""GitHub plumbing for the evaluate-pr-stack skill. Read-only.

Subcommands print compact JSON so the scoring agents read only the fields the
rubric judges on.

  stack <pr-url>          the PRs in the stack, bottom (nearest trunk) first
  facts -R <repo> <n>     counted LoC and AI review threads for one PR

Exit codes: 0 ok, 1 error.
"""
import argparse
import json
import os
import re
import sys
import time

# The stack walk is shared with the pr-stack-re-approval skill (same plugin).
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "pr-stack-re-approval", "scripts"))
import prstack  # noqa: E402

PAGE = 100
MAX_FILE_PAGES = 30  # the files API serves at most 3000 files
MARKER_PROBE_MIN = 30  # changed lines before a file is probed for a generated marker
MARKER_PROBE_LINES = 10
BODY_LIMIT = 400
DESCRIPTION_LIMIT = 1500

GENERATED_PATHS = re.compile(
    r"(^|/)(go\.sum|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|"
    r"poetry\.lock|uv\.lock|Gemfile\.lock|[^/]*\.lock|[^/]*\.pb\.go|[^/]*\.pb\.gw\.go|"
    r"[^/]*_pb2(_grpc)?\.py|[^/]*\.gen\.go|[^/]*_gen\.go|zz_generated[^/]*|"
    r"mock_[^/]*|[^/]*_mock\.go|[^/]*\.snap|[^/]*\.min\.(js|css))$"
    r"|(^|/)(__snapshots__|vendor|node_modules)/"
)
GENERATED_MARKER = re.compile(r"(Code generated .* DO NOT EDIT|DO NOT EDIT\.? ?This file (is|was) (auto)?generated)",
                              re.IGNORECASE)
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ERROR"}
ARTIFACT_LINK = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+")

THREADS_QUERY = """
query($owner:String!, $repo:String!, $number:Int!, $after:String) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      title body headRefOid mergeable
      commits(last:1) { nodes { commit { statusCheckRollup { contexts(first:100) { nodes {
        __typename
        ... on CheckRun { name conclusion isRequired(pullRequestNumber:$number) }
        ... on StatusContext { context state isRequired(pullRequestNumber:$number) }
      } } } } } }
      comments(first:100) { nodes { body } }
      reviewThreads(first:100, after:$after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line originalLine
          comments(first:1) { nodes { author { __typename login } body url } }
        }
      }
    }
  }
}"""


def loc_points(loc):
    if loc < 500:
        return 5
    if loc < 700:
        return 3
    if loc < 800:
        return 1
    return 0


# ---- files ---------------------------------------------------------------


def fetch_files(gh, repo, number):
    files = []
    for page in range(1, MAX_FILE_PAGES + 1):
        batch = prstack.gh_json(gh, ["api", f"repos/{repo}/pulls/{number}/files?per_page={PAGE}&page={page}"])
        files += batch
        if len(batch) < PAGE:
            break
    return files


def head_has_marker(gh, repo, path, oid):
    """True when the file's first lines carry a generated-code marker."""
    try:
        text = gh(["api", f"repos/{repo}/contents/{prstack.quote(path)}?ref={oid}",
                   "-H", "Accept: application/vnd.github.raw"])
    except prstack.GhError:
        return False
    head = "\n".join(text.splitlines()[:MARKER_PROBE_LINES])
    return bool(GENERATED_MARKER.search(head))


def generated_reason(gh, repo, oid, f):
    """Why a file is excluded from the count, or None when it is handwritten."""
    path = f["filename"]
    if GENERATED_PATHS.search(path):
        return "path"
    if any(GENERATED_MARKER.search(line) for line in (f.get("patch") or "").splitlines()):
        return "marker"
    changed = f["additions"] + f["deletions"]
    if f["status"] != "removed" and changed >= MARKER_PROBE_MIN and head_has_marker(gh, repo, path, oid):
        return "marker"
    return None


# ---- facts ---------------------------------------------------------------


def fetch_threads(gh, repo, number):
    owner, name = repo.split("/")
    after, nodes, pr = None, [], None
    while True:
        page = prstack.graphql(gh, THREADS_QUERY,
                               {"owner": owner, "repo": name, "number": number, "after": after})
        page = page["repository"]["pullRequest"]
        pr = pr or page
        nodes += page["reviewThreads"]["nodes"]
        info = page["reviewThreads"]["pageInfo"]
        if not info["hasNextPage"]:
            return pr, nodes
        after = info["endCursor"]


def ai_threads(nodes):
    out = []
    for t in nodes:
        comments = t["comments"]["nodes"]
        if not comments:
            continue
        first = comments[0]
        author = first.get("author") or {}
        if author.get("__typename") != "Bot":
            continue
        body = " ".join(first["body"].split())
        out.append({
            "author": author["login"],
            "path": t["path"],
            "line": t["line"] if t["line"] is not None else t["originalLine"],
            "resolved": t["isResolved"],
            "outdated": t["isOutdated"],
            "url": first["url"],
            "body": body[:BODY_LIMIT],
        })
    return out


def failing_checks(pr):
    """Checks on the head commit that failed, each flagged required or not."""
    out = []
    for commit in pr["commits"]["nodes"]:
        rollup = commit["commit"]["statusCheckRollup"]
        for c in (rollup["contexts"]["nodes"] if rollup else []):
            if c["__typename"] == "CheckRun":
                name, result = c["name"], c["conclusion"]
            else:
                name, result = c["context"], c["state"]
            if result in FAILED_CONCLUSIONS:
                out.append({"name": name, "result": result, "required": bool(c["isRequired"])})
    return out


def cmd_facts(gh, repo, number, sleep=time.sleep):
    pr, threads = fetch_threads(gh, repo, number)
    oid = pr["headRefOid"]
    counted, generated = [], []
    for f in fetch_files(gh, repo, number):
        changed = f["additions"] + f["deletions"]
        reason = generated_reason(gh, repo, oid, f)
        entry = {"path": f["filename"], "added": f["additions"], "deleted": f["deletions"],
                 "changed": changed, "status": f["status"]}
        if f.get("previous_filename"):
            entry["renamed_from"] = f["previous_filename"]
        if reason:
            generated.append(dict(entry, why=reason))
        else:
            counted.append(entry)
    loc = sum(e["changed"] for e in counted)
    ai = ai_threads(threads)
    links = sorted(set(ARTIFACT_LINK.findall(pr["body"] or "")
                       + [m for c in pr["comments"]["nodes"] for m in ARTIFACT_LINK.findall(c["body"])]))
    failing = failing_checks(pr)
    return {
        "title": pr["title"],
        "mergeable": prstack.resolve_mergeable(gh, repo, number, pr["mergeable"], sleep),
        "blocking_ci_failures": [c["name"] for c in failing if c["required"]],
        "other_ci_failures": [c["name"] for c in failing if not c["required"]],
        "description": (pr["body"] or "")[:DESCRIPTION_LIMIT],
        "head": oid,
        "loc_counted": loc,
        "loc_points": loc_points(loc),
        "files": sorted(counted, key=lambda e: -e["changed"]),
        "generated_excluded": generated,
        "ai_threads_total": len(ai),
        "ai_threads_unresolved": sum(1 for t in ai if not t["resolved"]),
        "ai_threads": ai,
        "visualization_links": links,
    }


# ---- cli -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="prfacts.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stack")
    s.add_argument("url")
    s = sub.add_parser("facts")
    s.add_argument("-R", dest="repo", required=True)
    s.add_argument("number", type=int)
    return p


def dispatch(gh, a):
    if a.cmd == "stack":
        return prstack.cmd_stack(gh, a.url)
    return cmd_facts(gh, prstack.check_repo(a.repo), a.number)


def main(argv=None, gh=prstack.run_gh):
    args = build_parser().parse_args(argv)
    try:
        code, payload = 0, dispatch(gh, args)
    except (prstack.GhError, ValueError, KeyError, OSError) as err:
        code, payload = 1, {"status": "error", "message": str(err)}
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())

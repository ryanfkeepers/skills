import contextlib
import inspect
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prstack  # noqa: E402

REPO = "o/r"
OID_A = "a" * 40
OID_B = "b" * 40


class FakeGh:
    """Answers gh argv by the first matching route; records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        for match, reply in self.routes:
            if match(args):
                if isinstance(reply, Exception):
                    raise reply
                out = reply(args) if callable(reply) else reply
                return out if isinstance(out, str) else json.dumps(out)
        raise AssertionError(f"unexpected gh call: {args}")

    def posts(self):
        return [c for c in self.calls if "-X" in c]


def has(*parts):
    return lambda args: all(p in args for p in parts)


def pr(number, base, head, state="OPEN"):
    return {"number": number, "title": f"pr {number}", "url": f"u/{number}",
            "isDraft": False, "baseRefName": base, "headRefName": head, "state": state}


def stack_routes(prs, default="main"):
    by_head, by_base = {}, {}
    for p in prs:
        by_head.setdefault(p["headRefName"], []).append(p)
        by_base.setdefault(p["baseRefName"], []).append(p)

    def view(args):
        return next(p for p in prs if str(p["number"]) == args[2])

    def lst(args):
        flag = "--head" if "--head" in args else "--base"
        branch = args[args.index(flag) + 1]
        found = (by_head if flag == "--head" else by_base).get(branch, [])
        want_all = args[args.index("--state") + 1] == "all"
        return [p for p in found if want_all or p["state"] == "OPEN"]

    return [
        (has("repo", "view"), default + "\n"),
        (has("pr", "view"), view),
        (has("pr", "list"), lst),
    ]


class StackTest(unittest.TestCase):
    def test_linear_stack_from_middle(self):
        prs = [pr(1, "main", "b1"), pr(2, "b1", "b2"), pr(3, "b2", "b3")]
        out = prstack.cmd_stack(FakeGh(stack_routes(prs)), "https://github.com/o/r/pull/2")
        self.assertEqual([p["number"] for p in out["prs"]], [1, 2, 3])
        self.assertEqual(out["linear"], [1, 2, 3])
        self.assertEqual(out["forks"], [])

    def test_fork_stops_linear_at_branch_point(self):
        prs = [pr(1, "main", "b1"), pr(2, "b1", "b2"), pr(3, "b1", "b3"), pr(4, "b3", "b4")]
        out = prstack.cmd_stack(FakeGh(stack_routes(prs)), "https://github.com/o/r/pull/4")
        self.assertEqual(out["linear"], [1])
        self.assertEqual(out["forks"], [{"at": 1, "children": [2, 3]}])
        self.assertEqual({p["number"] for p in out["prs"]}, {1, 2, 3, 4})

    def test_ambiguous_parent_is_reported(self):
        prs = [pr(1, "main", "b1"), pr(5, "main", "b1"), pr(2, "b1", "b2")]
        out = prstack.cmd_stack(FakeGh(stack_routes(prs)), "https://github.com/o/r/pull/2")
        self.assertEqual(out["ambiguous"],
                         [{"below": 2, "branch": "b1", "candidates": [1, 5]}])
        self.assertEqual(out["linear"], [2])

    def test_closed_start_is_noted(self):
        prs = [pr(1, "main", "b1", state="MERGED")]
        out = prstack.cmd_stack(FakeGh(stack_routes(prs)), "https://github.com/o/r/pull/1")
        self.assertEqual(out["not_open"], [1])

    def test_merged_pr_mid_stack_does_not_cut_the_walk(self):
        prs = [pr(1, "main", "b1"), pr(2, "b1", "b2", state="MERGED"), pr(3, "b2", "b3")]
        out = prstack.cmd_stack(FakeGh(stack_routes(prs)), "https://github.com/o/r/pull/3")
        self.assertEqual([p["number"] for p in out["prs"]], [1, 2, 3])
        self.assertEqual(out["linear"], [1, 2, 3])
        self.assertEqual(out["not_open"], [2])


def page(nodes, nxt=None):
    return {"pageInfo": {"hasNextPage": nxt is not None, "endCursor": nxt}, "nodes": nodes}


def review(rid, login, state, at, oid=OID_A, body=""):
    return {"id": rid, "author": {"login": login}, "state": state, "submittedAt": at,
            "body": body, "commit": {"oid": oid}}


def thread(login, review_id, resolved, line=10, replies=()):
    first = {"author": {"login": login}, "body": "fix this", "url": "c1",
             "createdAt": "t", "pullRequestReview": {"id": review_id}}
    rest = [{"author": {"login": who}, "body": text, "url": "c2", "createdAt": "t",
             "pullRequestReview": None} for who, text in replies]
    return {"id": f"T{review_id}{resolved}", "isResolved": resolved, "path": "x.go",
            "line": line, "originalLine": 7, "comments": page([first, *rest])}


def pr_page(reviews, threads, comments, mergeable="MERGEABLE", dismissals=None):
    return {"data": {"repository": {"pullRequest": {
        "title": "t", "body": "d", "url": "u", "headRefOid": OID_B, "baseRefName": "main",
        "mergeable": mergeable, "reviews": reviews, "reviewThreads": threads,
        "comments": comments,
        "timelineItems": dismissals if dismissals is not None else page([])}}}}


def state_gh(pages, mergeable_after=None):
    seq = iter(pages)
    routes = [
        (has("api", "user"), "me\n"),
        (has("api", "graphql"), lambda a: next(seq)),
        (has("pr", "view"), {"mergeable": mergeable_after}),
    ]
    return FakeGh(routes)


class StateTest(unittest.TestCase):
    def test_last_review_ignores_pending_and_others(self):
        reviews = page([review("R1", "me", "CHANGES_REQUESTED", "2026-01-01"),
                        review("R2", "me", "PENDING", None),
                        review("R3", "bob", "APPROVED", "2026-03-01"),
                        review("R4", "me", "APPROVED", "2026-02-01", oid=OID_B)])
        out = prstack.cmd_state(state_gh([pr_page(reviews, page([]), page([]))]), REPO, 1)
        self.assertEqual(out["prior_verdict"], "APPROVED")
        self.assertEqual(out["reviewed_oid"], OID_B)

    def test_dismissed_review_recovers_original_verdict(self):
        for previous in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED"):
            reviews = page([review("R1", "me", "DISMISSED", "2026-01-01")])
            events = page([{"previousReviewState": "APPROVED", "review": {"id": "other"}},
                           {"previousReviewState": previous, "review": {"id": "R1"}}])
            out = prstack.cmd_state(
                state_gh([pr_page(reviews, page([]), page([]), dismissals=events)]), REPO, 1)
            self.assertEqual(out["prior_verdict"], previous)
            self.assertTrue(out["dismissed"])

    def test_dismissed_review_without_event_stays_dismissed(self):
        reviews = page([review("R1", "me", "DISMISSED", "2026-01-01")])
        out = prstack.cmd_state(state_gh([pr_page(reviews, page([]), page([]))]), REPO, 1)
        self.assertEqual(out["prior_verdict"], "DISMISSED")
        self.assertTrue(out["dismissed"])

    def test_live_review_is_not_flagged_dismissed(self):
        reviews = page([review("R1", "me", "APPROVED", "2026-01-01")])
        out = prstack.cmd_state(state_gh([pr_page(reviews, page([]), page([]))]), REPO, 1)
        self.assertFalse(out["dismissed"])

    def test_no_baseline(self):
        reviews = page([review("R1", "bob", "APPROVED", "2026-01-01")])
        out = prstack.cmd_state(state_gh([pr_page(reviews, page([]), page([]))]), REPO, 1)
        self.assertIsNone(out["reviewed_oid"])
        self.assertEqual(out["threads"], [])

    def test_thread_scope(self):
        reviews = page([review("R0", "me", "COMMENTED", "2026-01-01"),
                        review("R1", "me", "CHANGES_REQUESTED", "2026-02-01")])
        threads = page([
            thread("me", "R1", True, replies=[("dev", "done")]),  # last review, resolved: in
            thread("me", "R0", False, line=None),                 # older, unresolved: in
            thread("me", "R0", True),                             # older, resolved: out
            thread("bob", "R1", False),                           # not the user's: out
        ])
        comments = page([{"author": {"login": "me"}, "body": "top", "url": "c", "createdAt": "t"},
                         {"author": {"login": "bob"}, "body": "x", "url": "c", "createdAt": "t"}])
        out = prstack.cmd_state(state_gh([pr_page(reviews, threads, comments)]), REPO, 1)
        self.assertEqual([(t["from_last_review"], t["resolved"]) for t in out["threads"]],
                         [(True, True), (False, False)])
        self.assertEqual(out["threads"][0]["comments"][1],
                         {"user": False, "author": "dev", "body": "done", "url": "c2"})
        self.assertTrue(out["threads"][1]["outdated"])
        self.assertEqual(out["threads"][1]["line"], 7)
        self.assertEqual([c["body"] for c in out["top_level"]], ["top"])

    def test_pagination_merges_pages(self):
        first = pr_page(page([review("R1", "me", "COMMENTED", "2026-01-01")], nxt="c1"),
                        page([]), page([]))
        second = pr_page(page([review("R2", "me", "APPROVED", "2026-02-01")]), None, None)
        gh = state_gh([first, second])
        out = prstack.cmd_state(gh, REPO, 1)
        self.assertEqual(out["prior_verdict"], "APPROVED")
        second_call = [c for c in gh.calls if "graphql" in c][1]
        self.assertIn("wT=false", second_call)
        self.assertIn("rAfter=c1", second_call)

    def test_unknown_mergeable_is_retried(self):
        reviews = page([review("R1", "me", "APPROVED", "2026-01-01")])
        gh = state_gh([pr_page(reviews, page([]), page([]), mergeable="UNKNOWN")],
                      mergeable_after="MERGEABLE")
        out = prstack.cmd_state(gh, REPO, 1, sleep=lambda s: None)
        self.assertEqual(out["mergeable"], "MERGEABLE")


def diff(*files, mode=None):
    """Build a git diff; a hunk is (start, lines) or (start, lines, heading)."""
    out = []
    for path, index, hunks in files:
        out.append(f"diff --git a/{path} b/{path}")
        if mode:
            out += [f"old mode {mode[0]}", f"new mode {mode[1]}"]
        out += [f"index {index} 100644", f"--- a/{path}", f"+++ b/{path}"]
        for start, lines, *heading in hunks:
            suffix = f" {heading[0]}" if heading else ""
            out.append(f"@@ -{start},3 +{start},3 @@{suffix}")
            out += lines
    return "\n".join(out) + "\n"


HUNK = [" ctx", "-old", "+new", " ctx"]


class InterdiffTest(unittest.TestCase):
    def test_line_shift_only_is_unchanged(self):
        r = diff(("a.go", "1..2", [(10, HUNK)]))
        h = diff(("a.go", "3..4", [(40, [" other ctx", "-old", "+new", " more"])]))
        self.assertEqual(prstack.interdiff(r, h), [])

    def test_reverted_hunk_is_dropped(self):
        r = diff(("a.go", "1..2", [(10, HUNK), (50, ["-x", "+y"])]))
        h = diff(("a.go", "1..3", [(10, HUNK)]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual([k["kind"] for k in f["hunks"]], ["dropped"])
        self.assertTrue(f["in_head_diff"])

    def test_edited_hunk_is_changed(self):
        r = diff(("a.go", "1..2", [(10, ["-old", "+new", "+more"])]))
        h = diff(("a.go", "1..3", [(10, ["-old", "+newer", "+more"])]))
        [f] = prstack.interdiff(r, h)
        [k] = f["hunks"]
        self.assertEqual(k["kind"], "changed")
        self.assertIn("-+new", k["delta"])
        self.assertIn("++newer", k["delta"])

    def test_dropped_hunk_keeps_changed_lines_only(self):
        r = diff(("a.go", "1..2", [(10, HUNK), (50, [" ctx", "-x", "+y"])]))
        h = diff(("a.go", "1..3", [(10, HUNK)]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(f["hunks"][0]["was"], ["-x", "+y"])

    def test_moved_file_is_paired_and_diffed(self):
        body = [f"+line {i}" for i in range(20)]
        r = diff(("old/pkg/a.go", "0..1", [(1, ["+package old", *body])]))
        h = diff(("new/pkg/a.go", "0..2", [(1, ["+package new", *body])]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual((f["path"], f["renamed_from"]), ("new/pkg/a.go", "old/pkg/a.go"))
        [k] = f["hunks"]
        self.assertEqual(k["kind"], "changed")
        self.assertEqual([l for l in k["delta"] if l[:1] in "+-"],
                         ["-+package old", "++package new"])

    def test_pure_move_is_reported_without_hunks(self):
        r = diff(("old/a.go", "0..1", [(1, ["+x", "+y"])]))
        h = diff(("new/a.go", "0..1", [(1, ["+x", "+y"])]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(f["renamed_from"], "old/a.go")
        self.assertNotIn("hunks", f)

    def test_different_basename_is_not_paired(self):
        r = diff(("old/a.go", "0..1", [(1, ["+x", "+y"])]))
        h = diff(("new/b.go", "0..1", [(1, ["+x", "+y"])]))
        paths = [(f["path"], f["in_head_diff"]) for f in prstack.interdiff(r, h)]
        self.assertEqual(paths, [("new/b.go", True), ("old/a.go", False)])

    def test_parent_noise_is_outside_head_diff(self):
        r = diff(("a.go", "1..2", [(10, HUNK)]), ("parent.go", "5..6", [(1, ["+p"])]))
        h = diff(("a.go", "1..2", [(10, HUNK)]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(f["path"], "parent.go")
        self.assertFalse(f["in_head_diff"])

    def test_new_file_and_generated_hint(self):
        r = diff(("a.go", "1..2", [(10, HUNK)]))
        h = diff(("a.go", "1..2", [(10, HUNK)]), ("go.sum", "0..9", [(1, ["+dep"])]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(f["hunks"][0]["kind"], "new")
        self.assertTrue(f["generated_hint"])

    def test_binary_change_is_header_only(self):
        r = "diff --git a/i.png b/i.png\nindex 1..2 100644\nBinary files a/i.png and b/i.png differ\n"
        h = "diff --git a/i.png b/i.png\nindex 1..3 100644\nBinary files a/i.png and b/i.png differ\n"
        [f] = prstack.interdiff(r, h)
        self.assertIn("index 1..3 100644", f["header_changed"])

    def test_changes_unchanged_short_circuits(self):
        gh = FakeGh([])
        out = prstack.cmd_changes(gh, REPO, 1, OID_A, OID_A)
        self.assertTrue(out["unchanged"])
        self.assertEqual(gh.calls, [])

    def test_changes_fetches_both_pr_only_diffs(self):
        gh = FakeGh([(has("--jq"), "mb\n"),
                     (has("api"), diff(("a.go", "1..2", [(10, HUNK)])))])
        out = prstack.cmd_changes(gh, REPO, 1, OID_A, OID_B, base="feat/x")
        self.assertTrue(out["unchanged"])
        diffs = [c[-1] for c in gh.calls if "--jq" not in c]
        self.assertEqual(diffs, [f"repos/o/r/compare/feat%2Fx...{OID_A}",
                                 f"repos/o/r/compare/feat%2Fx...{OID_B}"])

    def test_squash_merged_parent_is_landed_in_base(self):
        parent = (5, ["+parent()"])
        child = (40, ["+child()"])
        diffs = {
            f"repos/o/r/compare/main...{OID_A}": diff(("a.go", "1..2", [parent, child])),
            f"repos/o/r/compare/main...{OID_B}": diff(("a.go", "3..4", [child])),
            f"repos/o/r/compare/old...main": diff(("a.go", "1..3", [parent])),
        }
        merge_bases = {OID_A: "old\n", OID_B: "new\n"}
        gh = FakeGh([(has("--jq"), lambda a: merge_bases[a[1].rsplit("...", 1)[1]]),
                     (has("api"), lambda a: diffs[a[-1]])])
        out = prstack.cmd_changes(gh, REPO, 1, OID_A, OID_B, base="main")
        [f] = out["files"]
        [k] = f["hunks"]
        self.assertEqual((k["kind"], k.get("landed_in_base")), ("dropped", True))
        self.assertTrue(f["in_head_diff"])

    def test_true_revert_is_not_landed(self):
        r = diff(("a.go", "1..2", [(5, ["+keep()"]), (40, ["+child()"])]))
        h = diff(("a.go", "1..3", [(40, ["+child()"])]))
        landed_diff = diff(("a.go", "1..9", [(5, ["+unrelated()"])]))
        [f] = prstack.interdiff(r, h, landed_diff)
        self.assertNotIn("landed_in_base", f["hunks"][0])


class DiffParsingTest(unittest.TestCase):
    """Regression: a file the parser cannot read must never look unchanged."""

    def test_path_with_space(self):
        r = diff(("My File.md", "1..2", [(1, ["+b"])]))
        h = diff(("My File.md", "1..3", [(1, ["+EVIL"])]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(f["path"], "My File.md")
        self.assertEqual(sorted(k["kind"] for k in f["hunks"]), ["dropped", "new"])

    def test_plus_line_with_trailing_tab(self):
        text = ("diff --git a/x y b/x y\nindex 1..2 100644\n--- a/x y\t\n+++ b/x y\t\n"
                "@@ -1 +1 @@\n+z\n")
        self.assertEqual(list(prstack.split_diff(text)), ["x y"])

    def test_quoted_non_ascii_path(self):
        text = ('diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"\n'
                "index 1..2 100644\n--- \"a/caf\\303\\251.md\"\n+++ \"b/caf\\303\\251.md\"\n"
                "@@ -1 +1 @@\n+z\n")
        self.assertEqual(list(prstack.split_diff(text)), ["café.md"])

    def test_header_only_path_with_space(self):
        text = "diff --git a/i m.png b/i m.png\nindex 1..2 100644\nBinary files differ\n"
        self.assertEqual(list(prstack.split_diff(text)), ["i m.png"])

    def test_unparseable_header_raises(self):
        with self.assertRaises(ValueError):
            prstack.split_diff("diff --git a/x b/yy\nindex 1..2\n")

    def test_text_without_headers_raises(self):
        with self.assertRaises(ValueError):
            prstack.split_diff("<html>rate limited</html>")

    def test_moved_edit_to_another_function_is_changed(self):
        r = diff(("a.go", "1..2", [(10, ["+check()"], "func A() {")]))
        h = diff(("a.go", "1..3", [(90, ["+check()"], "func Z() {")]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual([k["kind"] for k in f["hunks"]], ["changed"])

    def test_mode_change_with_same_hunks_is_reported(self):
        r = diff(("run.sh", "1..2", [(1, ["+echo"])]))
        h = diff(("run.sh", "1..3", [(1, ["+echo"])]), mode=("100644", "100755"))
        [f] = prstack.interdiff(r, h)
        self.assertIn("new mode 100755", f["header_changed"])
        self.assertNotIn("hunks", f)

    def test_generated_file_is_not_paired(self):
        r = diff(("go.sum", "1..2", [(1, ["+a v1", "+b v1"])]))
        h = diff(("go.sum", "1..3", [(1, ["+a v1", "+b v2"])]))
        [f] = prstack.interdiff(r, h)
        self.assertEqual(sorted(k["kind"] for k in f["hunks"]), ["dropped", "new"])

    def test_pairing_skipped_past_limit(self):
        many = [(i * 10, [f"+r{i}", "+shared"]) for i in range(60)]
        more = [(i * 10, [f"+h{i}", "+shared"]) for i in range(60)]
        [f] = prstack.interdiff(diff(("a.go", "1..2", many)), diff(("a.go", "1..3", more)))
        self.assertNotIn("changed", {k["kind"] for k in f["hunks"]})


class RunGhTest(unittest.TestCase):
    def test_non_utf8_output_is_replaced(self):
        class Proc:
            returncode, stdout, stderr = 0, b"ok \xff byte", b""
        real = prstack.subprocess.run
        prstack.subprocess.run = lambda *a, **k: Proc()
        try:
            self.assertEqual(prstack.run_gh(["api"]), "ok � byte")
        finally:
            prstack.subprocess.run = real


class ReadTest(unittest.TestCase):
    def test_line_window(self):
        gh = FakeGh([(has("api"), "one\ntwo\nthree\nfour\n")])
        self.assertEqual(prstack.cmd_read(gh, REPO, OID_A, "a.go", "2-3"), "2\ttwo\n3\tthree")


def approve_gh(head=OID_A, mergeable="MERGEABLE", post="", head_after=None):
    heads = iter([head, head_after or head])
    return FakeGh([
        (has("pr", "view"), lambda a: {"headRefOid": next(heads), "mergeable": mergeable}),
        (has("-X", "POST"), post),
    ])


class ApproveTest(unittest.TestCase):
    def test_head_moved_refuses_without_post(self):
        gh = approve_gh(head=OID_B)
        code, out = prstack.cmd_approve(gh, REPO, 1, OID_A)
        self.assertEqual((code, out["status"]), (prstack.GUARD_REFUSED, "head_moved"))
        self.assertEqual(gh.posts(), [])

    def test_conflicting_refuses_without_post(self):
        gh = approve_gh(mergeable="CONFLICTING")
        code, out = prstack.cmd_approve(gh, REPO, 1, OID_A)
        self.assertEqual(out["status"], "conflicting")
        self.assertEqual(gh.posts(), [])

    def test_approve_sends_no_body(self):
        gh = approve_gh()
        code, out = prstack.cmd_approve(gh, REPO, 1, OID_A)
        self.assertEqual((code, out["status"]), (0, "approved"))
        [post] = gh.posts()
        self.assertIn(f"commit_id={OID_A}", post)
        self.assertFalse(any(a.startswith("body=") for a in post))

    def test_body_file_is_sent_verbatim(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("LGTM, ship it")
        gh = approve_gh()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = prstack.main(["approve", "-R", REPO, "1", OID_A,
                                     "--body-file", f.name], gh=gh)
        finally:
            os.unlink(f.name)
        self.assertEqual(code, 0)
        self.assertIn("body=LGTM, ship it", gh.posts()[0])

    def test_gh_error_is_reported_verbatim(self):
        gh = approve_gh(post=prstack.GhError("Can not approve your own pull request"))
        code, out = prstack.cmd_approve(gh, REPO, 1, OID_A)
        self.assertEqual((code, out["message"]), (1, "Can not approve your own pull request"))

    def test_push_racing_the_post_is_reported_stale(self):
        gh = approve_gh(head_after=OID_B)
        code, out = prstack.cmd_approve(gh, REPO, 1, OID_A)
        self.assertEqual((code, out["status"], out["head"]),
                         (prstack.GUARD_REFUSED, "approved_stale", OID_B))

    def test_short_oid_rejected(self):
        with self.assertRaises(ValueError):
            prstack.cmd_approve(approve_gh(), REPO, 1, "abc123")

    def test_only_approve_writes(self):
        src = inspect.getsource(prstack)
        approve_src = inspect.getsource(prstack.cmd_approve)
        self.assertEqual(src.count('"-X"'), 1)
        self.assertIn('"-X", "POST"', approve_src)
        self.assertNotIn("mutation", src)


if __name__ == "__main__":
    unittest.main()

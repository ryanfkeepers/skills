import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pps  # noqa: E402

URL1 = "https://github.com/o/r/pull/1"
URL2 = "https://github.com/o/r/pull/2"


class FakeRun:
    """Answers argv by the first matching route with (code, stdout, stderr)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        for match, reply in self.routes:
            if match(argv):
                out = reply(argv) if callable(reply) else reply
                if isinstance(out, (dict, list)):
                    out = json.dumps(out)
                return out if isinstance(out, tuple) else (0, out, "")
        raise AssertionError(f"unexpected call: {argv}")

    def ran(self, *parts):
        return [c for c in self.calls if all(p in c for p in parts)]


def has(*parts):
    return lambda argv: all(p in argv for p in parts)


def rev(change, bookmarks, description):
    return f"{change}\x1f{','.join(bookmarks)}\x1f{description}\x1e"


def plan_run(revs_newest_first, root, taken=("main",), below="", summaries=None):
    summaries = summaries or {}
    return FakeRun([
        (has("root"), root + "\n"),
        (has("-r", "trunk()"), "main,main"),
        (lambda a: any(x.startswith("heads(") for x in a), below),
        (has("bookmark", "list"), "\n".join(taken) + "\n"),
        (has("diff", "--summary"), lambda a: summaries.get(a[a.index("-r") + 1], "")),
        (has("log"), "".join(revs_newest_first)),
    ])


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.out = os.path.join(self.root, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, runner, ticket="DP-12"):
        return pps.cmd_plan(runner, "aaa", "ccc", ticket, self.out)

    def test_bookmarks_bases_and_files(self):
        runner = plan_run([
            rev("ccc", [], "Add tests\n\nCovers the handler.\n"),
            rev("bbb", ["dp-12/existing"], "Wire handler\n"),
            rev("aaa", [], "Add Auth Handler!! (v2)\n\nBody line.\n"),
        ], self.root)
        out = self.plan(runner)
        r = out["revisions"]
        self.assertEqual([x["change_id"] for x in r], ["aaa", "bbb", "ccc"])
        self.assertEqual([x["bookmark"] for x in r],
                         ["kprs/dp-12/add-auth-handler-v2", "dp-12/existing",
                          "kprs/dp-12/add-tests"])
        self.assertEqual([x["base"] for x in r],
                         ["main", "kprs/dp-12/add-auth-handler-v2", "dp-12/existing"])
        self.assertEqual([x["bookmark_exists"] for x in r], [False, True, False])
        with open(r[0]["body_file"]) as f:
            self.assertEqual(f.read(), "Body line.\n")
        with open(r[0]["title_file"]) as f:
            self.assertEqual(f.read(), "Add Auth Handler!! (v2)")

    def test_trunk_is_excluded_from_the_range(self):
        runner = plan_run([rev("aaa", [], "x\n")], self.root)
        self.plan(runner)
        [log] = runner.ran("log", "-T", pps.REV_TEMPLATE)
        self.assertIn("(aaa::ccc) ~ ::trunk()", log)

    def test_placeholder_description_gets_no_bookmark(self):
        runner = plan_run([rev("aaa", [], "WIP\n")], self.root)
        [r] = self.plan(runner)["revisions"]
        self.assertTrue(r["needs_description"])
        self.assertIsNone(r["bookmark"])
        self.assertNotIn("body_file", r)

    def test_name_collision_gets_suffix(self):
        runner = plan_run([rev("aaa", [], "Fix it\n")], self.root,
                          taken=("main", "kprs/dp-12/fix-it"))
        [r] = self.plan(runner)["revisions"]
        self.assertEqual(r["bookmark"], "kprs/dp-12/fix-it-2")

    def test_stack_on_existing_branch_uses_it_as_base(self):
        runner = plan_run([rev("aaa", [], "Next\n")], self.root, below="dp-9/parent\n")
        [r] = self.plan(runner)["revisions"]
        self.assertEqual(r["base"], "dp-9/parent")

    def test_two_bookmarked_heads_below_is_ambiguous(self):
        runner = plan_run([rev("aaa", [], "Next\n")], self.root, below="a\nb\n")
        out = self.plan(runner)
        self.assertEqual(out["base_ambiguous"], ["a", "b"])
        self.assertEqual(out["revisions"][0]["base"], "main")

    def test_plan_docs_root_md_only(self):
        open(os.path.join(self.root, "auth-plan.md"), "w").close()
        open(os.path.join(self.root, "README.md"), "w").close()
        summary = "A auth-plan.md\nA README.md\nA docs/x.md\nM other.md\nA gone.md\n"
        runner = plan_run([rev("aaa", [], "x\n")], self.root, summaries={"aaa": summary})
        [r] = self.plan(runner)["revisions"]
        self.assertEqual(r["plan_docs"], ["auth-plan.md"])

    def test_unsafe_revision_refused(self):
        with self.assertRaises(ValueError):
            pps.cmd_plan(plan_run([], self.root), "a; rm -rf /", "b", "T", self.out)

    def test_slug_is_capped_on_a_word_boundary(self):
        slug = pps.slugify("word " * 30)
        self.assertLessEqual(len(slug), pps.SLUG_MAX)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(slug.endswith("word"))


class PrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.title = os.path.join(self.tmp.name, "t")
        self.body = os.path.join(self.tmp.name, "b")
        with open(self.title, "w") as f:
            f.write("Add handler\n")
        with open(self.body, "w") as f:
            f.write("Body\n")

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, existing=(), push=(0, "", "remote: 3 vulnerabilities\nMove bookmark b\n")):
        return FakeRun([
            (has("git", "push"), push),
            (has("pr", "list"), list(existing)),
            (has("pr", "edit"), ""),
            (has("pr", "create"), "Creating...\n" + URL1 + "\n"),
        ])

    def test_creates_with_assignee_me_and_body_file(self):
        runner = self.runner()
        out = pps.cmd_pr(runner, "dp-1/a", "main", self.title, self.body, reviewers=["bob"])
        self.assertEqual((out["action"], out["url"]), ("created", URL1))
        self.assertEqual(out["push"], ["Move bookmark b"])
        [create] = runner.ran("pr", "create")
        for part in ("--assignee", "@me", "--body-file", self.body, "--title", "Add handler",
                     "--reviewer", "bob"):
            self.assertIn(part, create)
        self.assertEqual(runner.ran("api", "user"), [])

    def test_reuses_open_pr_and_fixes_base(self):
        runner = self.runner(existing=[{"number": 7, "url": URL2, "baseRefName": "old"}])
        out = pps.cmd_pr(runner, "dp-1/a", "dp-1/base", self.title, self.body)
        self.assertEqual((out["action"], out["url"]), ("reused", URL2))
        self.assertEqual(out["base_fixed"], {"from": "old", "to": "dp-1/base"})
        self.assertEqual(runner.ran("pr", "create"), [])
        self.assertEqual(runner.ran("pr", "edit")[0][3:6], ["7", "--base", "dp-1/base"])

    def test_reuse_with_matching_base_makes_no_edit(self):
        runner = self.runner(existing=[{"number": 7, "url": URL2, "baseRefName": "main"}])
        out = pps.cmd_pr(runner, "dp-1/a", "main", self.title, self.body)
        self.assertNotIn("base_fixed", out)
        self.assertEqual(runner.ran("pr", "edit"), [])

    def test_push_failure_stops_before_gh(self):
        runner = self.runner(push=(1, "", "rejected: stale info"))
        with self.assertRaises(pps.CmdError):
            pps.cmd_pr(runner, "dp-1/a", "main", self.title, self.body)
        self.assertEqual(runner.ran("pr"), [])

    def test_draft_and_repo_pass_through(self):
        runner = self.runner()
        pps.cmd_pr(runner, "dp-1/a", "main", self.title, self.body, repo="o/r", draft=True)
        [create] = runner.ran("pr", "create")
        self.assertIn("--draft", create)
        self.assertEqual(create[create.index("--repo") + 1], "o/r")


class LinkTest(unittest.TestCase):
    def test_non_url_refused_before_gh_runs(self):
        runner = FakeRun([])
        with self.assertRaises(ValueError):
            pps.cmd_link(runner, [URL1, "my-branch"])
        self.assertEqual(runner.calls, [])

    def test_single_pr_skips(self):
        self.assertEqual(pps.cmd_link(FakeRun([]), [URL1])["status"], "skipped")

    def test_not_installed(self):
        runner = FakeRun([(has("--help"), (1, "", "unknown command"))])
        self.assertEqual(pps.cmd_link(runner, [URL1, URL2])["status"], "not_installed")

    def test_not_enabled_exit_code(self):
        runner = FakeRun([(has("--help"), ""), (has("link"), (9, "", "stacks disabled"))])
        out = pps.cmd_link(runner, [URL1, URL2])
        self.assertEqual((out["status"], out["message"]), ("not_enabled", "stacks disabled"))

    def test_linked(self):
        runner = FakeRun([(has("--help"), ""), (has("link"), "")])
        self.assertEqual(pps.cmd_link(runner, [URL1, URL2])["status"], "linked")


if __name__ == "__main__":
    unittest.main()

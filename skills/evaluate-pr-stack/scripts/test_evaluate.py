import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate  # noqa: E402


def facts(loc=100, unresolved=0, mergeable="MERGEABLE", blocking=(), links=()):
    return {"loc_counted": loc, "ai_threads_unresolved": unresolved, "mergeable": mergeable,
            "blocking_ci_failures": list(blocking), "visualization_links": list(links)}


def judgment(splittable=False, nominal=False, cause="", loc_adjust=0):
    return {"splittable": splittable, "nominal": nominal, "cause": cause, "loc_adjust": loc_adjust}


class Score(unittest.TestCase):
    def test_perfect(self):
        self.assertEqual(evaluate.score_pr(facts(), judgment(), True), (10, []))

    def test_no_viz_costs_one_unless_nominal(self):
        self.assertEqual(evaluate.score_pr(facts(), judgment(), False), (9, ["no visualization"]))
        self.assertEqual(evaluate.score_pr(facts(), judgment(nominal=True), False)[0], 10)

    def test_split_points(self):
        self.assertEqual(evaluate.split_points(False, 900), 2)
        self.assertEqual(evaluate.split_points(True, 499), 1)
        self.assertEqual(evaluate.split_points(True, 500), 0)

    def test_causes_in_order(self):
        score, causes = evaluate.score_pr(facts(loc=910, unresolved=2),
                                          judgment(splittable=True, cause="new pkg splittable"), False)
        self.assertEqual(score, 0 + 0 + 0 + 0)
        self.assertEqual(causes, ["910 LoC", "new pkg splittable", "2 unresolved AI threads", "no visualization"])

    def test_loc_adjust_changes_points(self):
        score, causes = evaluate.score_pr(facts(loc=600), judgment(loc_adjust=-200), True)
        self.assertEqual((score, causes), (10, []))

    def test_conflict_zeroes_everything(self):
        self.assertEqual(evaluate.score_pr(facts(mergeable="CONFLICTING"), judgment(nominal=True), True),
                         (0, ["merge conflicts"]))

    def test_blocking_ci_zeroes_and_names_checks(self):
        self.assertEqual(evaluate.score_pr(facts(blocking=["build", "test"]), judgment(), True),
                         (0, ["blocking CI: build, test"]))

    def test_lights(self):
        self.assertEqual([evaluate.light(s) for s in (10, 8, 7, 6, 5, 0)], ["🟩", "🟩", "🟨", "🟨", "🟥", "🟥"])


class Viz(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(evaluate.parse_viz("all", [1, 2]), {1, 2})
        self.assertEqual(evaluate.parse_viz("none", [1, 2]), set())
        self.assertEqual(evaluate.parse_viz("#1, 2", [1, 2]), {1, 2})

    def test_rejects_unasked_and_garbage(self):
        with self.assertRaises(ValueError):
            evaluate.parse_viz("3", [1, 2])
        with self.assertRaises(ValueError):
            evaluate.parse_viz("maybe", [1, 2])


def pr(n, state="OPEN"):
    return {"number": n, "title": f"t{n}", "url": f"https://x/{n}", "state": state}


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def stack(self, prs, forks=(), not_open=()):
        evaluate.write_json(self.d, "stack.json", {"prs": prs, "forks": list(forks), "not_open": list(not_open)})

    def put(self, n, f, j=None):
        evaluate.write_json(self.d, f"facts-{n}.json", f)
        if j is not None:
            evaluate.write_json(self.d, f"judgment-{n}.json", j)

    def test_asks_for_viz_before_rendering(self):
        self.stack([pr(1)])
        self.put(1, facts(links=["https://claude.ai/artifact/a"]), judgment())
        code, text = evaluate.cmd_report(self.d)
        self.assertEqual(code, 2)
        self.assertIn("#1 t1", text)
        self.assertIn("https://claude.ai/artifact/a", text)

    def test_no_question_when_all_nominal_or_zero(self):
        self.stack([pr(1), pr(2)])
        self.put(1, facts(), judgment(nominal=True))
        self.put(2, facts(mergeable="CONFLICTING"))
        code, text = evaluate.cmd_report(self.d)
        self.assertEqual(code, 0)
        self.assertIn("| 🟩 10/10 |", text)
        self.assertIn("| 🟥 0/10 | [#2 t2](https://x/2) | merge conflicts |", text)
        self.assertIn("**Not ready for human review:** 1 red.", text)

    def test_ready_verdict_and_skipped(self):
        self.stack([pr(1), pr(2, "MERGED")], not_open=[2])
        self.put(1, facts(), judgment())
        code, text = evaluate.cmd_report(self.d, "all")
        self.assertEqual(code, 0)
        self.assertIn("**Ready for human review.**", text)
        self.assertIn("Skipped (merged or closed): #2", text)
        self.assertNotIn("t2", text.split("Skipped")[0])

    def test_missing_judgment_and_error_rows_are_failed(self):
        self.stack([pr(1), pr(2)])
        self.put(1, facts())
        self.put(2, {"error": "boom"})
        code, text = evaluate.cmd_report(self.d, "none")
        self.assertEqual(code, 0)
        self.assertIn("| 🛑 N/A | [#1 t1](https://x/1) | judgment missing |", text)
        self.assertIn("| 🛑 N/A | [#2 t2](https://x/2) | boom |", text)
        self.assertIn("2 failed", text)

    def test_fork_children_name_their_parent(self):
        self.stack([pr(1), pr(2), pr(3)], forks=[{"at": 1, "children": [2, 3]}])
        for n in (1, 2, 3):
            self.put(n, facts(), judgment(nominal=True))
        _, text = evaluate.cmd_report(self.d)
        self.assertIn("[#2 t2 (on #1)](https://x/2)", text)
        self.assertNotIn("t1 (on", text)

    def test_missing_stack_is_error(self):
        with self.assertRaises(ValueError):
            evaluate.cmd_report(self.d)

    def test_rerun_is_stable(self):
        self.stack([pr(1)])
        self.put(1, facts(), judgment())
        self.assertEqual(evaluate.cmd_report(self.d, "all"), evaluate.cmd_report(self.d, "all"))


class Judge(unittest.TestCase):
    def test_writes_and_rejects_unknown_pr(self):
        with tempfile.TemporaryDirectory() as d:
            evaluate.write_json(d, "facts-5.json", facts())
            evaluate.cmd_judge(d, 5, True, False, cause="x", loc_adjust=-3)
            self.assertEqual(evaluate.read_json(d, "judgment-5.json")["loc_adjust"], -3)
            with self.assertRaises(ValueError):
                evaluate.cmd_judge(d, 6, True, False)
            evaluate.write_json(d, "facts-7.json", {"error": "x"})
            with self.assertRaises(ValueError):
                evaluate.cmd_judge(d, 7, True, False)


class Collect(unittest.TestCase):
    def test_collect_writes_files_and_lists_needs(self):
        stack = {"repo": "o/r", "prs": [pr(1), pr(2), pr(3), pr(4, "MERGED")], "forks": [], "not_open": [4]}
        results = {1: facts(), 2: facts(mergeable="CONFLICTING"), 3: {"error": "bad"}}
        orig_stack, orig_one = evaluate.prstack.cmd_stack, evaluate.collect_one
        evaluate.prstack.cmd_stack = lambda gh, url: stack
        evaluate.collect_one = lambda gh, repo, n: results[n]
        try:
            with tempfile.TemporaryDirectory() as d:
                out = evaluate.cmd_collect(None, "u", d)
                self.assertEqual(out["needs_judgment"], [1])
                self.assertEqual(out["prs"][1]["auto_zero"], ["merge conflicts"])
                self.assertEqual(out["prs"][2]["error"], "bad")
                self.assertEqual(out["not_open"], [4])
                self.assertTrue(os.path.exists(os.path.join(d, "facts-3.json")))
                self.assertFalse(os.path.exists(os.path.join(d, "facts-4.json")))
        finally:
            evaluate.prstack.cmd_stack, evaluate.collect_one = orig_stack, orig_one


if __name__ == "__main__":
    unittest.main()

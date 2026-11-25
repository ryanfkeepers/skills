import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bounds  # noqa: E402
import lensctl  # noqa: E402
from test_settle import SettleCase  # noqa: E402

SCOPE = {"dirs": {"a", "b"}, "test_files": {"a/a_bench_test.go"}}


class ScopeTest(unittest.TestCase):
    def test_implement_may_change_code_in_target_directories_and_manifests(self):
        files = ["a/a.go", "a/new_helper.go", "b/b.go", "go.mod", "svc/go.sum", "a/a_bench_test.go"]
        self.assertEqual(bounds.out_of_bounds("code", files, SCOPE), [])

    def test_implement_may_not_change_other_directories_or_routine_tests(self):
        files = ["c/c.go", "a/a_test.go", "a/sub/deep.go", "a/a.go"]
        self.assertEqual(bounds.out_of_bounds("code", files, SCOPE), ["c/c.go", "a/a_test.go", "a/sub/deep.go"])

    def test_unit_test_may_change_tests_beside_targets_and_in_test_dirs(self):
        files = ["a/a_test.go", "b/b_test.go", "c/testdata/x.json", "pkg/mocks/m.go"]
        self.assertEqual(bounds.out_of_bounds("tests", files, SCOPE), [])

    def test_unit_test_may_not_change_code_or_far_tests(self):
        files = ["a/a.go", "c/c_test.go", "go.mod"]
        self.assertEqual(bounds.out_of_bounds("tests", files, SCOPE), files)

    def test_plan_scope_reads_directories_and_test_task_files(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(bounds.plan_scope(d))
            with open(os.path.join(d, "tasks.json"), "w") as f:
                json.dump({"tasks": [
                    {"id": "t1", "target": ["a/a.go#A", "b/b.go"]},
                    {"id": "t2", "kind": "test", "target": ["a/a_bench_test.go#B"]}]}, f)
            self.assertEqual(bounds.plan_scope(d), SCOPE)


class HoldTest(SettleCase):
    PIPELINE = {
        "retries": 1, "max_agents": 32,
        "lenses": [
            {"name": "workspace", "scope": "code", "implemented": True},
            {"name": "plan", "scope": "run", "implemented": True},
            {"name": "implement", "scope": "run", "implemented": True, "bounds": "code"},
            {"name": "unit-test", "scope": "run", "implemented": True, "bounds": "tests"},
            {"name": "after", "scope": "run", "implemented": True},
        ],
    }

    def record(self, lens, status="done"):
        return lensctl.cmd_record(self.run, lens, status, "ok")

    def run_implement(self, *files):
        self.assertEqual(self.next()["lens"], "implement")
        for rel in files:
            os.makedirs(os.path.dirname(os.path.join(self.ws, rel)), exist_ok=True)
            self.edit(rel, "package x\n// changed\n")
        return self.record("implement")

    def read(self, rel):
        with open(os.path.join(self.ws, rel)) as f:
            return f.read()

    def test_in_scope_changes_finish_the_lens(self):
        out = self.run_implement("a/helper.go", "b/b.go")
        self.assertEqual(out["status"], "done")
        self.assertEqual(self.next()["lens"], "unit-test")

    def test_out_of_scope_files_halt_and_ask_without_touching_anything(self):
        out = self.run_implement("a/a.go", "c/c.go")
        self.assertEqual((out["status"], out["held"]), ("needs_input", ["c/c.go"]))
        self.assertEqual(self.read("c/c.go"), "package x\n// changed\n")
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertIn("c/c.go", relay["question"]["rendering"])
        self.assertEqual(relay["question"]["options"], ["keep them", "restore them"])

    def test_keep_finishes_the_lens_and_leaves_the_files(self):
        self.run_implement("c/c.go")
        out = lensctl.cmd_answer(self.run, "implement", "keep them")
        self.assertEqual(out["continue"], "next")
        self.assertEqual(self.read("c/c.go"), "package x\n// changed\n")
        self.assertEqual(self.next()["lens"], "unit-test")

    def test_restore_undoes_only_the_held_files_then_finishes(self):
        self.run_implement("a/a.go", "c/c.go")
        lensctl.cmd_answer(self.run, "implement", "restore them")
        self.assertEqual(self.read("c/c.go"), "package x\n")
        self.assertEqual(self.read("a/a.go"), "package x\n// changed\n")
        self.assertEqual(self.next()["lens"], "unit-test")

    def test_an_instruction_sends_the_lens_back_with_the_instruction_as_feedback(self):
        self.run_implement("c/c.go")
        out = lensctl.cmd_answer(self.run, "implement", "move that into b/")
        self.assertEqual(out["continue"], "next")
        feedback = lensctl.cmd_disputes(self.run, "implement")["disputes"]
        self.assertEqual([d["claim"] for d in feedback], ["move that into b/"])
        again = self.next()
        self.assertEqual(again["lens"], "implement")
        self.edit("c/c.go", "package x\n")
        self.assertEqual(self.record("implement")["status"], "done")

    def test_unit_test_is_held_for_code_changes_but_not_test_files(self):
        self.run_implement("a/a.go")
        self.assertEqual(self.next()["lens"], "unit-test")
        os.makedirs(os.path.join(self.ws, "a", "testdata"), exist_ok=True)
        self.edit("a/a_test.go", "package x\n")
        self.edit("a/testdata/in.json", "{}\n")
        self.assertEqual(self.record("unit-test")["status"], "done")

    def test_unit_test_that_edits_code_is_held(self):
        self.run_implement("a/a.go")
        self.next()
        self.edit("b/b.go", "package x\n// not a test\n")
        out = self.record("unit-test")
        self.assertEqual((out["status"], out["held"]), ("needs_input", ["b/b.go"]))


if __name__ == "__main__":
    unittest.main()

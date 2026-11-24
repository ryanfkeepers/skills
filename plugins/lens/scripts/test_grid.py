import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cores  # noqa: E402
import grid  # noqa: E402
import lensctl  # noqa: E402

CELLS = ["scaffold", "implement", "unit-test", "test-coverage"]
PIPELINE = {
    "retries": 1,
    "max_agents": 32,
    "lenses": [
        {"name": "design", "scope": "run", "implemented": True},
        {"name": "workspace", "scope": "code", "implemented": True},
        {"name": "build", "scope": "grid", "implemented": True, "cells": CELLS},
        {"name": "green", "scope": "run", "implemented": True},
    ],
}


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("jj"), "jj not installed")
class GridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        os.makedirs(self.repo)
        sh(self.repo, "jj", "git", "init")
        for k, v in (("revset-aliases.'trunk()'", "main"), ("user.name", "t"), ("user.email", "t@t")):
            sh(self.repo, "jj", "config", "set", "--repo", k, v)
        with open(os.path.join(self.repo, "go.mod"), "w") as f:
            f.write("module x\n")
        sh(self.repo, "jj", "commit", "-m", "base")
        sh(self.repo, "jj", "bookmark", "create", "main", "-r", "@-")
        self.real_home = os.environ.get("LENS_HOME")
        os.environ["LENS_HOME"] = self.home
        pipeline = os.path.join(self.tmp.name, "pipeline.json")
        with open(pipeline, "w") as f:
            json.dump(PIPELINE, f)
        self.run = lensctl.cmd_init(self.repo, "p", pipeline)["run"]
        self.finish_plain("design")
        # workspace runs inline; the grid then halts because no tasks are written yet
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "halt")
        st = lensctl.load(self.run)
        st["halt"] = None
        st["grid"] = None
        st["lenses"]["build"] = lensctl.fresh_lens()
        lensctl.save(self.run, st)
        with open(os.path.join(self.run, "workspace.json")) as f:
            self.ws = json.load(f)["path"]

    def tearDown(self):
        if self.real_home is None:
            os.environ.pop("LENS_HOME", None)
        else:
            os.environ["LENS_HOME"] = self.real_home
        self.tmp.cleanup()

    def finish_plain(self, lens):
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["lens"], lens)
        lensctl.cmd_record(self.run, lens, "done", "ok")

    def tasks(self, *tasks):
        os.makedirs(os.path.join(self.run, "tasks"), exist_ok=True)
        for t in tasks:
            with open(os.path.join(self.run, "tasks", f"{t['id']}.json"), "w") as f:
                json.dump(t, f)

    def write(self, rel, text="x\n"):
        path = os.path.join(self.ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def dispatch(self):
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["action"], "dispatch", out)
        return out["task"], out["lens"]

    def record(self, task, lens, status="done", summary="ok"):
        return lensctl.cmd_record(self.run, lens, status, summary, task)

    def cell(self, task, lens):
        return lensctl.load(self.run)["grid"]["tasks"][task]["cells"][lens]

    def run_task(self, task, files=None, test_files=None):
        for lens in CELLS:
            out = lensctl.cmd_next(self.run)
            self.assertEqual((out["task"], out["lens"]), (task, lens))
            if lens in ("scaffold", "implement"):
                for f in files or []:
                    self.write(f, f"{lens}\n")
            if lens == "unit-test":
                for f in test_files or []:
                    self.write(f)
            self.record(task, lens)

    # ---- scheduling ------------------------------------------------------

    def test_independent_tasks_run_together_and_dependents_wait(self):
        self.tasks({"id": "t1", "target": ["a/a.go#A"]}, {"id": "t2", "target": ["b/b.go"], "blocked_by": ["t1"]},
                   {"id": "t3", "target": ["c/c.go"]})
        first, second = self.dispatch(), self.dispatch()
        self.assertEqual({first, second}, {("t1", "scaffold"), ("t3", "scaffold")})
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "wait")

    def test_shared_files_serialize_tasks(self):
        self.tasks({"id": "t1", "target": ["a/a.go"], "shared_files": ["go.mod"]},
                   {"id": "t2", "target": ["b/b.go"], "shared_files": ["go.mod"]})
        self.assertEqual(self.dispatch(), ("t1", "scaffold"))
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "wait")

    def test_full_grid_settles_and_moves_on(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]}, {"id": "t2", "target": ["b/b.go"], "blocked_by": ["t1"]})
        self.run_task("t1", ["a/a.go"], ["a/a_test.go"])
        self.run_task("t2", ["b/b.go"], ["b/b_test.go"])
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["lens"], "green")
        self.assertEqual(lensctl.load(self.run)["lenses"]["build"]["status"], "done")

    # ---- bounds ----------------------------------------------------------

    def test_out_of_bounds_change_is_restored_and_fails_the_cell(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        self.dispatch()
        self.write("a/a.go")
        self.write("z/stray.go")
        out = self.record("t1", "scaffold")
        self.assertEqual(out["status"], "pending")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "z", "stray.go")))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "a", "a.go")))
        self.assertTrue(self.cell("t1", "scaffold")["solo"])

    def test_unit_test_may_write_tests_but_not_code(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        for lens in ("scaffold", "implement"):
            self.dispatch()
            self.write("a/a.go", lens)
            self.record("t1", lens)
        self.dispatch()
        self.write("a/a_test.go")
        self.assertEqual(self.record("t1", "unit-test")["status"], "done")
        self.dispatch()
        self.record("t1", "test-coverage")
        st = lensctl.load(self.run)
        self.assertEqual(st["lenses"]["build"]["status"], "running")

    def test_concurrent_cells_do_not_flag_each_other(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]}, {"id": "t2", "target": ["b/b.go"]})
        self.dispatch()
        self.dispatch()
        self.write("a/a.go")
        self.write("b/b.go")
        self.assertEqual(self.record("t1", "scaffold")["status"], "done")
        self.assertEqual(self.record("t2", "scaffold")["status"], "done")

    # ---- retries ---------------------------------------------------------

    def test_failed_concurrent_cell_retries_alone_and_counts_spurious(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]}, {"id": "t2", "target": ["b/b.go"]})
        self.dispatch()
        self.dispatch()
        self.record("t1", "scaffold", "failed", "flaky")
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "wait")
        self.record("t2", "scaffold")
        self.assertEqual(self.dispatch(), ("t1", "scaffold"))
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "wait")
        self.record("t1", "scaffold")
        self.assertEqual(lensctl.load(self.run)["grid"]["spurious"], 1)

    def test_second_failure_halts(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        self.dispatch()
        self.record("t1", "scaffold", "failed")
        self.dispatch()
        out = self.record("t1", "scaffold", "failed", "still broken")
        self.assertEqual(out["halt"], {"lens": "scaffold-t1", "reason": "still broken"})

    # ---- coverage loop ---------------------------------------------------

    def test_coverage_gaps_send_unit_test_back_once(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        for lens in CELLS:
            self.dispatch()
            if lens == "test-coverage":
                os.makedirs(os.path.join(self.run, "coverage"), exist_ok=True)
                with open(os.path.join(self.run, "coverage", "t1.json"), "w") as f:
                    json.dump({"gaps": ["a.go:10 error branch"]}, f)
            self.record("t1", lens)
        self.assertEqual(self.dispatch(), ("t1", "unit-test"))
        self.record("t1", "unit-test")
        self.assertEqual(self.dispatch(), ("t1", "test-coverage"))
        self.record("t1", "test-coverage")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        self.assertEqual(report["build"]["coverage_gaps"], {"t1": ["a.go:10 error branch"]})

    # ---- relay and disputes ----------------------------------------------

    def test_cell_relay_round_trip(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        self.dispatch()
        with open(lensctl.qa_path(self.run, "scaffold-t1"), "w") as f:
            f.write(json.dumps({"question": "q", "options": ["a"], "recommendation": "a", "answer": None}) + "\n")
        self.record("t1", "scaffold", "needs_input")
        out = lensctl.cmd_next(self.run)
        self.assertEqual((out["action"], out["task"]), ("relay", "t1"))
        self.assertEqual(lensctl.cmd_answer(self.run, "scaffold", "a", "t1")["continue"], "send_message")
        self.assertEqual(self.cell("t1", "scaffold")["status"], "running")

    def test_dispute_to_earlier_cell_resets_the_task_from_there(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        for lens in ("scaffold", "implement"):
            self.dispatch()
            self.record("t1", lens)
        self.dispatch()
        with open(os.path.join(self.run, "disputes", "unit-test-t1-1.json"), "w") as f:
            json.dump({"target_lens": "implement", "claim": "off by one", "evidence": "a_test.go"}, f)
        out = self.record("t1", "unit-test", "blocked")
        self.assertEqual(out["reset_from"], "implement")
        self.assertEqual(self.cell("t1", "scaffold")["status"], "done")
        self.assertEqual(self.dispatch(), ("t1", "implement"))

    def test_dispute_to_design_rewinds_the_run_and_clears_the_grid(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        self.dispatch()
        with open(os.path.join(self.run, "disputes", "scaffold-t1-1.json"), "w") as f:
            json.dump({"target_lens": "design", "claim": "signature cannot compile", "evidence": "a.go"}, f)
        out = self.record("t1", "scaffold", "blocked")
        self.assertEqual(out["rewound_to"], "design")
        self.assertIsNone(lensctl.load(self.run)["grid"])

    def test_green_dispute_rechecks_that_cell_for_every_task(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]}, {"id": "t2", "target": ["b/b.go"], "blocked_by": ["t1"]},
                   {"id": "t3", "kind": "test", "target": ["a/a_bench_test.go"]})
        self.run_task("t1", ["a/a.go"], ["a/a_test.go"])
        self.run_task("t2", ["b/b.go"], ["b/b_test.go"])
        self.assertEqual(self.dispatch(), ("t3", "implement"))
        self.write("a/a_bench_test.go")
        self.record("t3", "implement")
        self.assertEqual(lensctl.cmd_next(self.run)["lens"], "green")
        with open(os.path.join(self.run, "disputes", "green-1.json"), "w") as f:
            json.dump({"target_lens": "unit-test", "claim": "b_test.go fails", "evidence": "x"}, f)
        out = lensctl.cmd_record(self.run, "green", "blocked")
        self.assertEqual(out["rechecking"], ["unit-test", "test-coverage"])
        st = lensctl.load(self.run)
        for tid in ("t1", "t2"):
            cells = st["grid"]["tasks"][tid]["cells"]
            self.assertEqual([cells[c]["status"] for c in CELLS], ["done", "done", "pending", "pending"])
        self.assertTrue(grid.settled(st["grid"]["tasks"]["t3"]))
        self.assertEqual(st["lenses"]["green"]["status"], "pending")
        feedback = lensctl.cmd_disputes(self.run, "unit-test")["disputes"]
        self.assertEqual([d["claim"] for d in feedback], ["b_test.go fails"])
        for tid in ("t1", "t2"):
            for lens in ("unit-test", "test-coverage"):
                self.assertEqual(self.dispatch(), (tid, lens))
                self.record(tid, lens)
        self.assertEqual(lensctl.cmd_next(self.run)["lens"], "green")

    # ---- test tasks ------------------------------------------------------

    def test_test_task_runs_only_implement_and_may_write_its_tests(self):
        self.tasks({"id": "t1", "kind": "test", "target": ["a/a_bench_test.go#BenchmarkA"]})
        self.assertEqual(self.dispatch(), ("t1", "implement"))
        self.write("a/a_bench_test.go")
        self.assertEqual(self.record("t1", "implement")["status"], "done")
        self.assertEqual(lensctl.cmd_next(self.run)["lens"], "green")
        self.assertEqual(list(lensctl.load(self.run)["grid"]["tasks"]["t1"]["cells"]), ["implement"])

    def test_test_task_may_not_write_code(self):
        self.tasks({"id": "t1", "kind": "test", "target": ["a/a_bench_test.go"]})
        self.dispatch()
        self.write("a/a_bench_test.go")
        self.write("a/a.go")
        self.assertEqual(self.record("t1", "implement")["status"], "pending")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "a", "a.go")))

    def test_code_task_implement_may_not_write_tests(self):
        self.tasks({"id": "t1", "target": ["a/a.go", "a/a_test.go"]})
        self.dispatch()
        self.record("t1", "scaffold")
        self.dispatch()
        self.write("a/a.go")
        self.write("a/a_test.go")
        self.assertEqual(self.record("t1", "implement")["status"], "pending")

    def test_resume_requeues_running_cells(self):
        self.tasks({"id": "t1", "target": ["a/a.go"]})
        self.dispatch()
        out = lensctl.cmd_resume(self.run)
        self.assertEqual((out["action"], out["task"], out["attempt"]), ("dispatch", "t1", 1))

    def test_unknown_dependency_halts(self):
        self.tasks({"id": "t1", "target": ["a/a.go"], "blocked_by": ["t9"]})
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "halt")


class GridUnitTest(unittest.TestCase):
    def test_test_file_detection(self):
        for path in ("a/a_test.go", "pkg/test_x.py", "web/x.spec.ts", "a/testdata/in.json"):
            self.assertTrue(grid.is_test(path), path)
        for path in ("a/a.go", "pkg/x.py", "web/x.ts"):
            self.assertFalse(grid.is_test(path), path)

    def test_target_files_strip_symbols(self):
        self.assertEqual(grid.target_files({"target": ["a/a.go#A", "a/a.go#B", "b/b.go"]}), ["a/a.go", "b/b.go"])


if __name__ == "__main__":
    unittest.main()

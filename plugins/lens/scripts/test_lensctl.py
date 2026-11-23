import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lensctl  # noqa: E402

PIPELINE = {
    "retries": 1,
    "lenses": [
        {"name": "intake", "scope": "run", "gate": "qa", "implemented": True},
        {"name": "graph", "scope": "core", "gate": "none", "implemented": False},
        {"name": "design", "scope": "run", "gate": "qa", "implemented": True},
        {"name": "plan", "scope": "run", "gate": "none", "implemented": True},
        {"name": "run-report", "scope": "code", "gate": "none", "implemented": True},
        {"name": "cleanup", "scope": "run", "gate": "none", "implemented": True},
    ],
}


class LensctlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.pipeline = os.path.join(self.tmp.name, "pipeline.json")
        with open(self.pipeline, "w") as f:
            json.dump(PIPELINE, f)
        self.real_home = os.environ.get("LENS_HOME")
        os.environ["LENS_HOME"] = self.home
        self.clock = [1000.0]
        self.real_now = lensctl.now
        lensctl.now = lambda: self.clock[0]
        self.run = lensctl.cmd_init(self.repo, "add a retry", self.pipeline)["run"]

    def tearDown(self):
        lensctl.now = self.real_now
        if self.real_home is None:
            os.environ.pop("LENS_HOME", None)
        else:
            os.environ["LENS_HOME"] = self.real_home
        self.tmp.cleanup()

    def tick(self, seconds=1.0):
        self.clock[0] += seconds

    def ask(self, lens, question="which?"):
        with open(lensctl.qa_path(self.run, lens), "a") as f:
            f.write(json.dumps({"question": question, "options": ["a", "b"],
                                "recommendation": "a", "answer": None}) + "\n")

    def dispute(self, lens, target, n=1):
        path = os.path.join(self.run, "disputes", f"{lens}-{n}.json")
        with open(path, "w") as f:
            json.dump({"target_lens": target, "claim": "c", "evidence": "e"}, f)

    def finish(self, lens, summary="ok"):
        out = lensctl.cmd_next(self.run)
        self.assertEqual((out["action"], out["lens"]), ("dispatch", lens))
        lensctl.cmd_record(self.run, lens, "done", summary)

    def status(self, lens):
        return lensctl.load(self.run)["lenses"][lens]["status"]

    # ---- init ------------------------------------------------------------

    def test_init_creates_run_outside_repo(self):
        self.assertTrue(self.run.startswith(self.home))
        self.assertEqual(os.listdir(self.repo), [])
        with open(os.path.join(self.run, "proposal.txt")) as f:
            self.assertEqual(f.read(), "add a retry")
        self.assertEqual(lensctl.load(self.run)["order"][0], "intake")

    def test_repo_slug_is_stable_and_distinct(self):
        other = os.path.join(self.tmp.name, "x", "repo")
        os.makedirs(other)
        self.assertEqual(lensctl.repo_slug(self.repo), lensctl.repo_slug(self.repo + "/"))
        self.assertNotEqual(lensctl.repo_slug(self.repo), lensctl.repo_slug(other))

    # ---- next / record ---------------------------------------------------

    def test_dispatches_in_order_and_skips_unimplemented(self):
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out, {"action": "dispatch", "lens": "intake", "agent": "lens:intake",
                               "run": self.run, "attempt": 1})
        lensctl.cmd_record(self.run, "intake", "done", "brief written")
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["lens"], "design")
        self.assertEqual(self.status("graph"), "skipped")

    def test_in_flight_lens_is_not_dispatched_twice(self):
        lensctl.cmd_next(self.run)
        self.assertEqual(lensctl.cmd_next(self.run), {"action": "wait", "running": ["intake"]})

    def test_full_run_writes_report_then_reaches_cleanup_and_done(self):
        for lens in ("intake", "design", "plan"):
            self.tick()
            self.finish(lens)
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["lens"], "cleanup")
        self.assertTrue(os.path.exists(os.path.join(self.run, "report.json")))
        lensctl.cmd_record(self.run, "cleanup", "done")
        self.assertEqual(lensctl.cmd_next(self.run), {"action": "done"})

    def test_summary_is_capped(self):
        lensctl.cmd_next(self.run)
        lensctl.cmd_record(self.run, "intake", "done", "\n".join(str(i) for i in range(25)))
        with open(os.path.join(self.run, "summaries", "intake.txt")) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), lensctl.SUMMARY_MAX_LINES)
        self.assertIn("cut", lines[-1])

    def test_record_rejects_lens_that_is_not_running(self):
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "design", "done")

    def test_record_rejects_unknown_lens(self):
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "nope", "done")

    # ---- retries ---------------------------------------------------------

    def test_failure_retries_once_then_halts(self):
        lensctl.cmd_next(self.run)
        out = lensctl.cmd_record(self.run, "intake", "failed", "boom")
        self.assertEqual(out["status"], "pending")
        self.assertEqual(lensctl.cmd_next(self.run)["attempt"], 2)
        out = lensctl.cmd_record(self.run, "intake", "failed", "boom again")
        self.assertEqual(out["halt"], {"lens": "intake", "reason": "boom again"})
        self.assertEqual(lensctl.cmd_next(self.run),
                         {"action": "halt", "lens": "intake", "reason": "boom again"})

    # ---- relay -----------------------------------------------------------

    def test_relay_round_trip(self):
        lensctl.cmd_next(self.run)
        self.ask("intake")
        lensctl.cmd_record(self.run, "intake", "needs_input")
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["action"], "relay")
        self.assertEqual(out["question"]["question"], "which?")
        self.assertFalse(out["respawn"])
        self.tick(30)
        out = lensctl.cmd_answer(self.run, "intake", "a")
        self.assertEqual(out["continue"], "send_message")
        self.assertEqual(lensctl.cmd_next(self.run), {"action": "wait", "running": ["intake"]})
        lensctl.cmd_record(self.run, "intake", "done")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        self.assertEqual(report["gates"][0]["answer"], "a")
        self.assertEqual(report["gates"][0]["wait_seconds"], 30.0)

    def test_needs_input_requires_open_question(self):
        lensctl.cmd_next(self.run)
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "intake", "needs_input")

    def test_answer_requires_waiting_lens(self):
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_answer(self.run, "intake", "a")

    def test_second_question_waits_for_its_own_answer(self):
        lensctl.cmd_next(self.run)
        self.ask("intake", "q1")
        lensctl.cmd_record(self.run, "intake", "needs_input")
        lensctl.cmd_answer(self.run, "intake", "a1")
        self.ask("intake", "q2")
        lensctl.cmd_record(self.run, "intake", "needs_input")
        self.assertEqual(lensctl.cmd_next(self.run)["question"]["question"], "q2")

    # ---- disputes and rewind ---------------------------------------------

    def test_dispute_rewinds_to_target_and_resets_later_lenses(self):
        self.finish("intake")
        lensctl.cmd_next(self.run)
        self.dispute("design", "intake")
        out = lensctl.cmd_record(self.run, "design", "blocked")
        self.assertEqual(out["rewound_to"], "intake")
        self.assertEqual(self.status("intake"), "pending")
        self.assertEqual(self.status("design"), "pending")
        self.assertEqual(lensctl.cmd_next(self.run)["lens"], "intake")
        self.assertEqual(lensctl.load(self.run)["disputes"][0]["file"], "design-1.json")

    def test_disputes_lists_feedback_for_target(self):
        self.finish("intake")
        lensctl.cmd_next(self.run)
        self.dispute("design", "intake")
        lensctl.cmd_record(self.run, "design", "blocked")
        out = lensctl.cmd_disputes(self.run, "intake")["disputes"]
        self.assertEqual([(d["from"], d["claim"]) for d in out], [("design", "c")])
        self.assertEqual(lensctl.cmd_disputes(self.run, "design")["disputes"], [])

    def test_routed_dispute_is_not_routed_again(self):
        self.finish("intake")
        lensctl.cmd_next(self.run)
        self.dispute("design", "intake")
        lensctl.cmd_record(self.run, "design", "blocked")
        self.finish("intake")
        lensctl.cmd_next(self.run)
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "design", "blocked")

    def test_dispute_against_later_lens_halts(self):
        lensctl.cmd_next(self.run)
        self.dispute("intake", "plan")
        out = lensctl.cmd_record(self.run, "intake", "blocked")
        self.assertEqual(out["status"], "failed")
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "halt")

    def test_manual_rewind_clears_halt(self):
        lensctl.cmd_next(self.run)
        lensctl.cmd_record(self.run, "intake", "failed")
        lensctl.cmd_next(self.run)
        lensctl.cmd_record(self.run, "intake", "failed")
        lensctl.rewind(self.run, "intake")
        self.assertEqual(lensctl.cmd_next(self.run)["action"], "dispatch")

    # ---- resume ----------------------------------------------------------

    def test_resume_redispatches_interrupted_lens_without_spending_a_retry(self):
        self.finish("intake")
        lensctl.cmd_next(self.run)
        out = lensctl.cmd_resume(self.run)
        self.assertEqual((out["action"], out["lens"], out["attempt"]), ("dispatch", "design", 1))

    def test_resume_marks_waiting_lens_for_respawn(self):
        lensctl.cmd_next(self.run)
        self.ask("intake")
        lensctl.cmd_record(self.run, "intake", "needs_input")
        out = lensctl.cmd_resume(self.run)
        self.assertEqual((out["action"], out["respawn"]), ("relay", True))
        self.assertEqual(lensctl.cmd_answer(self.run, "intake", "a")["continue"], "respawn")

    def test_latest_finds_newest_run(self):
        self.tick(5)
        newer = lensctl.cmd_init(self.repo, "second", self.pipeline)["run"]
        self.assertEqual(lensctl.cmd_latest(self.repo)["run"], newer)

    def test_latest_without_runs_errors(self):
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_latest(os.path.join(self.tmp.name, "other"))

    # ---- report ----------------------------------------------------------

    def test_report_rendering_counts(self):
        self.finish("intake")
        out = lensctl.cmd_report(self.run)
        self.assertTrue(out["rendering"][0].startswith(f"run {lensctl.load(self.run)['run_id']}: 1 lenses done"))

    # ---- only / info / core reuse -----------------------------------------

    def test_only_restricts_run_to_one_lens_and_marks_refresh(self):
        run = lensctl.cmd_init(self.repo, "refresh", self.pipeline, only="design")["run"]
        st = lensctl.load(run)
        self.assertEqual((st["order"], st["refresh"]), (["design"], True))
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_init(self.repo, "x", self.pipeline, only="nope")

    def test_info_reports_paths_without_workspace(self):
        info = lensctl.cmd_info(self.run)
        self.assertEqual((info["repo"], info["workspace"], info["snapshot"]),
                         (os.path.realpath(self.repo), None, None))
        self.assertTrue(info["core_graph"].startswith(self.home))

    def test_existing_core_is_reused_unless_refreshing(self):
        pipeline = dict(PIPELINE, lenses=[
            {"name": "conventions", "scope": "core", "implemented": True, "reuse_core": "conventions"}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        st = lensctl.load(self.run)
        core = os.path.join(self.home, st["repo_slug"], "conventions")
        os.makedirs(core)
        for name in ("code.md", "tests.md"):
            open(os.path.join(core, name), "w").close()
        run = lensctl.cmd_init(self.repo, "x", self.pipeline)["run"]
        self.assertEqual(lensctl.cmd_next(run), {"action": "done"})
        run = lensctl.cmd_init(self.repo, "x", self.pipeline, only="conventions")["run"]
        self.assertEqual(lensctl.cmd_next(run)["action"], "dispatch")

    def test_init_mode_runs_the_init_lenses_without_refresh(self):
        pipeline = dict(PIPELINE, init=[
            {"name": "graph-core", "scope": "code", "implemented": True},
            {"name": "conventions", "scope": "core", "implemented": True, "reuse_core": "conventions"}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        run = lensctl.cmd_init(self.repo, "p", self.pipeline, init=True)["run"]
        st = lensctl.load(run)
        self.assertEqual((st["order"], st["refresh"]), (["graph-core", "conventions"], False))

    def test_init_mode_builds_only_missing_cores(self):
        pipeline = dict(PIPELINE, init=[
            {"name": "conventions", "scope": "core", "implemented": True, "reuse_core": "conventions"}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        core = os.path.join(self.home, lensctl.load(self.run)["repo_slug"], "conventions")
        os.makedirs(core)
        for name in ("code.md", "tests.md"):
            open(os.path.join(core, name), "w").close()
        run = lensctl.cmd_init(self.repo, "p", self.pipeline, init=True)["run"]
        self.assertEqual(lensctl.cmd_next(run), {"action": "done"})

    def test_only_finds_a_lens_in_the_init_list(self):
        pipeline = dict(PIPELINE, init=[
            {"name": "conventions", "scope": "core", "implemented": True, "reuse_core": "conventions"}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        run = lensctl.cmd_init(self.repo, "p", self.pipeline, only="conventions")["run"]
        st = lensctl.load(run)
        self.assertEqual((st["order"], st["refresh"]), (["conventions"], True))

    def test_check_initialized_names_missing_cores_and_creates_nothing(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        with self.assertRaises(lensctl.LensError) as ctx:
            lensctl.check_initialized(other)
        self.assertIn("graph, conventions, contract-layers", str(ctx.exception))
        self.assertIn("/lens:init", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.home, lensctl.repo_slug(other))))

    def test_main_refuses_a_run_on_an_uninitialized_repo(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        self.assertEqual(lensctl.main(["init", "--repo", other, "--proposal", "x"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.home, lensctl.repo_slug(other))))
        self.assertEqual(lensctl.main(["init", "--repo", other, "--init"]), 0)
        self.assertEqual(lensctl.main(["init", "--repo", other, "--proposal", "x", "--only", "conventions"]), 0)

    def test_parallel_group_runs_side_by_side_and_finishes(self):
        pipeline = dict(PIPELINE, lenses=[
            {"name": "pair", "scope": "parallel", "implemented": True, "lenses": ["docs", "comments"]},
            {"name": "after", "scope": "run", "implemented": True}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        run = lensctl.cmd_init(self.repo, "x", self.pipeline)["run"]
        first, second = lensctl.cmd_next(run), lensctl.cmd_next(run)
        self.assertEqual({first["unit"], second["unit"]}, {"docs", "comments"})
        self.assertEqual(lensctl.cmd_next(run)["action"], "wait")
        with open(lensctl.qa_path(run, "comments"), "w") as f:
            f.write(json.dumps({"question": "add this comment?", "options": ["yes", "no"],
                                "recommendation": "no", "answer": None}) + "\n")
        lensctl.cmd_record(run, "comments", "needs_input", unit="comments")
        relay = lensctl.cmd_next(run)
        self.assertEqual((relay["action"], relay["unit"]), ("relay", "comments"))
        lensctl.cmd_answer(run, "comments", "no", unit="comments")
        lensctl.cmd_record(run, "docs", "done", unit="docs")
        lensctl.cmd_record(run, "comments", "done", unit="comments")
        self.assertEqual(lensctl.cmd_next(run)["lens"], "after")

    def test_sleep_lens_waits_then_records(self):
        pipeline = dict(PIPELINE, lenses=[
            {"name": "pause", "scope": "sleep", "seconds": 300, "implemented": True},
            {"name": "follow-1", "agent": "follow", "scope": "run", "implemented": True}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        run = lensctl.cmd_init(self.repo, "x", self.pipeline)["run"]
        self.assertEqual(lensctl.cmd_next(run), {"action": "sleep", "lens": "pause", "seconds": 300})
        self.assertEqual(lensctl.cmd_next(run), {"action": "wait", "running": ["pause"]})
        lensctl.cmd_record(run, "pause", "done")
        out = lensctl.cmd_next(run)
        self.assertEqual((out["lens"], out["agent"]), ("follow-1", "lens:follow"))

    def test_per_slice_group_has_one_unit_per_slice(self):
        pipeline = dict(PIPELINE, lenses=[
            {"name": "describe", "scope": "parallel", "implemented": True, "lenses": ["describe"], "per_slice": True}])
        with open(self.pipeline, "w") as f:
            json.dump(pipeline, f)
        run = lensctl.cmd_init(self.repo, "x", self.pipeline)["run"]
        with open(os.path.join(run, "stack.json"), "w") as f:
            json.dump({"slices": [{"change_id": "aaa"}, {"change_id": "bbb"}]}, f)
        a, b = lensctl.cmd_next(run), lensctl.cmd_next(run)
        self.assertEqual([(x["unit"], x["params"]["change_id"]) for x in (a, b)],
                         [("describe-1", "aaa"), ("describe-2", "bbb")])

    # ---- cli -------------------------------------------------------------

    def test_cli_reports_errors_as_json(self):
        code = lensctl.main(["next", "--run", os.path.join(self.tmp.name, "missing")])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

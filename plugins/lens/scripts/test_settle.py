import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cores  # noqa: E402
import lensctl  # noqa: E402
import settle  # noqa: E402

PIPELINE = {
    "retries": 1,
    "max_agents": 32,
    "lenses": [
        {"name": "workspace", "scope": "code", "implemented": True},
        {"name": "plan", "scope": "run", "implemented": True},
        {"name": "review-1", "scope": "settle", "implemented": True,
         "lenses": ["review-correctness", "review-security"]},
        {"name": "after", "scope": "run", "implemented": True},
    ],
}
GRAPH = {
    "nodes": [{"id": "a", "source_file": "a/a.go"}, {"id": "c", "source_file": "c/c.go"},
              {"id": "b", "source_file": "b/b.go"}],
    "links": [{"source": "c", "target": "a"}],
}


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


class RadiusTest(unittest.TestCase):
    def test_radius_adds_direct_neighbors_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "graph.json")
            with open(path, "w") as f:
                json.dump(GRAPH, f)
            self.assertEqual(settle.radius(path, ["a/a.go"]), ["a/a.go", "c/c.go"])
            self.assertEqual(settle.radius(path, ["b/b.go"]), ["b/b.go"])
            self.assertEqual(settle.radius(os.path.join(d, "missing.json"), ["x.go"]), ["x.go"])


@unittest.skipUnless(shutil.which("jj"), "jj not installed")
class SettleCase(unittest.TestCase):
    PIPELINE = PIPELINE

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        os.makedirs(self.repo)
        sh(self.repo, "jj", "git", "init")
        for k, v in (("revset-aliases.'trunk()'", "main"), ("user.name", "t"), ("user.email", "t@t")):
            sh(self.repo, "jj", "config", "set", "--repo", k, v)
        for rel in ("a/a.go", "b/b.go", "c/c.go"):
            os.makedirs(os.path.join(self.repo, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(self.repo, rel), "w") as f:
                f.write("package x\n")
        sh(self.repo, "jj", "commit", "-m", "base")
        sh(self.repo, "jj", "bookmark", "create", "main", "-r", "@-")
        self.real_home = os.environ.get("LENS_HOME")
        os.environ["LENS_HOME"] = self.home
        self.real_refresh = cores.refresh_live
        cores.refresh_live = lambda run: None
        self.real_max = settle.MAX_EPOCHS
        pipeline = os.path.join(self.tmp.name, "pipeline.json")
        with open(pipeline, "w") as f:
            json.dump(self.PIPELINE, f)
        self.run = lensctl.cmd_init(self.repo, "p", pipeline)["run"]
        out = lensctl.cmd_next(self.run)
        self.assertEqual(out["lens"], "plan")
        with open(os.path.join(self.run, "tasks.json"), "w") as f:
            json.dump({"tasks": [{"id": "t1", "target": ["a/a.go"]}, {"id": "t2", "target": ["b/b.go"]}]}, f)
        graph = os.path.join(self.run, "graph.json")
        with open(graph, "w") as f:
            json.dump(GRAPH, f)
        with open(os.path.join(self.run, "snapshot.json"), "w") as f:
            json.dump({"live": graph, "live_out": self.run, "base": graph}, f)
        lensctl.cmd_record(self.run, "plan", "done")
        with open(os.path.join(self.run, "workspace.json")) as f:
            self.ws = json.load(f)["path"]

    def tearDown(self):
        cores.refresh_live = self.real_refresh
        settle.MAX_EPOCHS = self.real_max
        if self.real_home is None:
            os.environ.pop("LENS_HOME", None)
        else:
            os.environ["LENS_HOME"] = self.real_home
        self.tmp.cleanup()

    # ---- helpers ---------------------------------------------------------

    def next(self):
        return lensctl.cmd_next(self.run)

    def dispatch_all(self):
        actions = []
        while True:
            out = self.next()
            if out["action"] != "dispatch":
                return actions, out
            actions.append(out)

    def findings(self, key, rows):
        path = os.path.join(self.run, "findings", f"{key}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def triaged(self, rows):
        self.findings("triaged", rows)

    def done(self, key, summary="ok"):
        return lensctl.cmd_record(self.run, "x", "done", summary, task_action=key)

    def group(self):
        return lensctl.load(self.run)["settle"]["review-1"]

    def edit(self, rel, text):
        with open(os.path.join(self.ws, rel), "w") as f:
            f.write(text)

    def finding(self, fid, file="a/a.go", **kw):
        return dict({"id": fid, "lens": "review-correctness", "location": {"file": file, "line": 1},
                     "claim": "bug", "evidence": "e", "epoch": self.group()["epochs"][-1]}, **kw)

    def review_round(self):
        """Dispatch every reviewer, finish them all clean except as the test arranges."""
        actions, out = self.dispatch_all()
        return [u["task_action"] for u in actions], out


class SettleTest(SettleCase):
    # ---- tests -----------------------------------------------------------

    def test_reviewers_review_the_whole_change_once(self):
        actions, out = self.review_round()
        self.assertEqual(sorted(actions), ["review-correctness", "review-security"])
        self.assertEqual(out["action"], "wait")
        epoch = self.group()["epochs"][0]
        group = self.group()["task_actions"].values()
        self.assertTrue(all(ta["params"]["epoch"] == epoch for ta in group if "epoch" in ta["params"]))
        self.assertTrue(all("task" not in ta and "task" not in ta["params"] for ta in group))

    def test_next_all_hands_out_every_ready_reviewer_then_waits(self):
        out = lensctl.cmd_next_all(self.run)
        self.assertEqual([a["action"] for a in out["actions"]], ["dispatch", "dispatch", "wait"])
        self.assertEqual(sorted(a["lens"] for a in out["actions"][:2]), ["review-correctness", "review-security"])
        self.assertEqual(lensctl.cmd_next_all(self.run)["actions"][0]["action"], "wait")

    def test_a_run_of_more_than_one_revision_halts(self):
        sh(self.ws, "jj", "new")
        out = self.next()
        self.assertEqual(out["action"], "halt")
        self.assertIn("one revision", out["reason"])

    def test_clean_reviews_settle_and_move_on(self):
        actions, _ = self.review_round()
        for u in actions:
            self.done(u)
        self.assertEqual(self.next()["lens"], "after")
        self.assertEqual(lensctl.load(self.run)["lenses"]["review-1"]["status"], "done")

    def test_blocking_defect_is_fixed_and_radius_rereviewed(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.assertEqual((tri["lens"], tri["params"]["findings"]), ("triage", ["f1"]))
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.assertEqual((fix["lens"], fix["params"]["findings"]), ("fix", ["f1"]))
        self.edit("a/a.go", "package x\n// fixed\n")
        out = self.done(fix["task_action"])
        self.assertEqual(out["radius"], ["a/a.go", "c/c.go"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["lens"] for u in rereview), ["review-correctness", "review-security"])
        self.assertTrue(all(u["params"]["scope"] == "radius" for u in rereview))
        for u in rereview:
            self.done(u["task_action"])
        self.assertEqual(self.next()["lens"], "after")

    def test_dropped_findings_are_not_fixed(self):
        actions, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "dropped"}])
        self.done(tri["task_action"])
        self.assertEqual(self.next()["lens"], "after")

    def test_deferred_findings_wait_for_the_patcher(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1", file="b/b.go")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": False, "class": "defect"}])
        self.done(tri["task_action"])
        patch = self.next()
        self.assertEqual(patch["lens"], "review-patcher")
        self.assertEqual(self.group()["pass"], "deferred")
        self.edit("b/b.go", "package x\n// tidy\n")
        self.done(patch["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["task_action"].split("-e")[0] for u in rereview),
                         ["review-correctness", "review-security"])

    def test_design_finding_is_decided_by_the_user(self):
        actions, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "design",
                       "claim": "which roles may call it?"}])
        self.done(tri["task_action"])
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertIn("which roles", relay["question"]["question"])
        self.assertEqual(lensctl.cmd_answer(self.run, "x", "leave it", task_action=relay["task_action"])["continue"], "next")
        self.assertEqual(self.next()["lens"], "after")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        self.assertEqual(report["settle"]["review-1"]["findings"], {"dismissed": 1})
        self.assertEqual(report["gates"][0]["answer"], "leave it")

    def test_design_finding_fix_goes_to_fix_with_decision(self):
        actions, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "design"}])
        self.done(tri["task_action"])
        relay = self.next()
        lensctl.cmd_answer(self.run, "x", "fix it as proposed", task_action=relay["task_action"])
        self.assertEqual(self.next()["lens"], "fix")

    def test_finding_that_keeps_returning_escalates(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        for n in (2, 3):
            fix = self.next()
            self.assertEqual(fix["lens"], "fix")
            self.edit("a/a.go", f"package x\n// try {n}\n")
            self.done(fix["task_action"])
            rereview, _ = self.dispatch_all()
            r = next(u for u in rereview if u["lens"] == "review-correctness")
            self.findings(r["task_action"], [self.finding(f"f{n}")])
            for u in rereview:
                self.done(u["task_action"])
            tri = self.next()
            self.triaged([{"id": f"f{n}", "sources": [f"f{n}"], "verdict": "confirmed", "blocking": True,
                           "class": "defect", "duplicate_of": "f1"}])
            self.done(tri["task_action"])
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertIn("came back", relay["question"]["question"])

    def test_epoch_cap_halts(self):
        settle.MAX_EPOCHS = 0
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        out = self.done(fix["task_action"])
        self.assertIn("epochs", out["halt"]["reason"])
        self.assertEqual(self.next()["action"], "halt")

    def test_failed_reviewer_retries_then_halts(self):
        actions, _ = self.review_round()
        lensctl.cmd_record(self.run, "x", "failed", "boom", task_action=actions[0])
        again = self.next()
        self.assertEqual(again["task_action"], actions[0])
        out = lensctl.cmd_record(self.run, "x", "failed", "boom", task_action=actions[0])
        self.assertIsNotNone(out["halt"])

    def test_resume_requeues_running_reviewers(self):
        actions, _ = self.review_round()
        out = lensctl.cmd_resume(self.run)
        self.assertEqual((out["action"], out["task_action"], out["attempt"]), ("dispatch", actions[0], 1))

    def test_user_feedback_goes_straight_to_fix_then_radius_review(self):
        st = lensctl.load(self.run)
        st["settle"] = {}
        lensctl.save(self.run, st)
        os.makedirs(os.path.join(self.run, "feedback"))
        with open(os.path.join(self.run, "feedback", "review-1.jsonl"), "w") as f:
            f.write(json.dumps({"id": "user-1", "claim": "rename the flag", "location": {"file": "b/b.go"}}) + "\n")
        fix = self.next()
        self.assertEqual((fix["lens"], fix["params"]["findings"]), ("fix", ["user-1"]))
        self.assertTrue(os.path.exists(os.path.join(self.run, "feedback", "review-1.jsonl.consumed")))
        self.edit("b/b.go", "package x\n// renamed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["task_action"].split("-e")[0] for u in rereview), ["review-correctness", "review-security"])

    def writer_group(self):
        st = lensctl.load(self.run)
        e = next(x for x in st["pipeline"]["lenses"] if x["name"] == "review-1")
        e.update(lenses=["contract-test", "e2e-test"], per_boundary=["contract-test"], writers=True)
        lensctl.save(self.run, st)
        os.makedirs(os.path.join(self.run, "scenarios", "contract"))
        for b, pkg in (("blob-store", "a"), ("api", "b")):
            with open(os.path.join(self.run, "scenarios", "contract", f"{b}.json"), "w") as f:
                json.dump({"boundary": b, "package": pkg, "cases": []}, f)

    def test_contract_tests_run_one_per_boundary(self):
        self.writer_group()
        actions, _ = self.review_round()
        self.assertEqual(sorted(actions), ["contract-test-api", "contract-test-blob-store", "e2e-test"])

    def test_writers_never_overlap_the_fixer(self):
        self.writer_group()
        actions, _ = self.review_round()
        self.findings("contract-test-blob-store", [self.finding("f1", lens="contract-test")])
        self.done("contract-test-blob-store")
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        self.assertEqual(self.next()["action"], "wait")
        for u in ("contract-test-api", "e2e-test"):
            self.done(u)
        fix = self.next()
        self.assertEqual(fix["lens"], "fix")
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["task_action"].split("-e")[0] for u in rereview), ["contract-test-blob-store", "e2e-test"])

    def gate(self, select=None):
        st = lensctl.load(self.run)
        e = next(x for x in st["pipeline"]["lenses"] if x["name"] == "review-1")
        e["always"] = ["review-correctness"]
        lensctl.save(self.run, st)
        if select is not None:
            with open(os.path.join(self.run, "review-select.json"), "w") as f:
                json.dump({"lenses": select}, f)

    def test_deselected_lens_is_never_dispatched(self):
        self.gate({"review-security": {"apply": False, "reason": "no trust boundary"},
                   "review-correctness": {"apply": False, "reason": "ignored: always on"}})
        actions, _ = self.review_round()
        self.assertEqual(sorted(actions), ["review-correctness"])
        self.assertEqual(self.group()["deselected"], {"review-security": "no trust boundary"})
        self.assertEqual(settle.report(lensctl.load(self.run))["review-1"]["deselected"],
                         {"review-security": "no trust boundary"})

    def test_missing_selection_drops_nothing(self):
        self.gate()
        actions, _ = self.review_round()
        self.assertEqual(sorted(actions), ["review-correctness", "review-security"])

    def test_deselected_lens_is_skipped_on_radius_rereview(self):
        self.gate({"review-security": {"apply": False, "reason": "none"}})
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual([u["task_action"].split("-e")[0] for u in rereview], ["review-correctness"])

    def test_not_applicable_retires_the_lens_for_later_epochs(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            if u == "review-security":
                lensctl.cmd_record(self.run, "x", "not_applicable", "no trust boundary", task_action=u)
            else:
                self.done(u)
        self.assertEqual(self.group()["retired"], ["review-security"])
        self.assertEqual(self.group()["task_actions"]["review-security"]["status"], "done")
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual([u["task_action"].split("-e")[0] for u in rereview], ["review-correctness"])
        self.assertEqual(settle.report(lensctl.load(self.run))["review-1"]["retired"], ["review-security"])

    def test_not_applicable_retires_only_that_boundary(self):
        self.writer_group()
        actions, _ = self.review_round()
        self.findings("contract-test-blob-store", [self.finding("f1", lens="contract-test")])
        for key in actions:
            if key == "contract-test-api":
                lensctl.cmd_record(self.run, "x", "not_applicable", "nothing here", task_action=key)
            else:
                self.done(key)
        self.assertEqual(self.group()["retired"], ["contract-test:api"])
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.edit("b/b.go", "package x\n// fixed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["task_action"].split("-e")[0] for u in rereview), ["contract-test-blob-store", "e2e-test"])

    def test_radius_not_applicable_does_not_retire(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["task_action"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["task_action"])
        rereview, _ = self.dispatch_all()
        sec = next(u["task_action"] for u in rereview if u["task_action"].startswith("review-security"))
        lensctl.cmd_record(self.run, "x", "not_applicable", "none in radius", task_action=sec)
        self.assertEqual(self.group()["retired"], [])

    def test_not_applicable_from_a_triage_unit_is_rejected(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1")])
        for u in actions:
            self.done(u)
        tri = self.next()
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "x", "not_applicable", "", task_action=tri["task_action"])

    def test_unit_dispute_rewinds_to_earlier_lens(self):
        actions, _ = self.review_round()
        with open(os.path.join(self.run, "disputes", f"{actions[0]}-1.json"), "w") as f:
            json.dump({"target_lens": "plan", "claim": "task split is wrong", "evidence": "x"}, f)
        out = lensctl.cmd_record(self.run, "x", "blocked", task_action=actions[0])
        self.assertEqual(out["rewound_to"], "plan")
        self.assertNotIn("review-1", lensctl.load(self.run).get("settle", {}))


class TwoGroupTest(SettleCase):
    PIPELINE = dict(PIPELINE, lenses=[
        {"name": "workspace", "scope": "code", "implemented": True},
        {"name": "plan", "scope": "run", "implemented": True},
        {"name": "review-1", "scope": "settle", "implemented": True, "lenses": ["review-security"]},
        {"name": "review-2", "scope": "settle", "implemented": True, "lenses": ["review-performance"]},
        {"name": "after", "scope": "run", "implemented": True},
    ])

    def triage_group(self, group, lens, fid):
        actions, _ = self.review_round()
        self.assertEqual(actions, [lens])
        epoch = lensctl.load(self.run)["settle"][group]["epochs"][-1]
        self.findings(lens, [{"id": fid, "lens": lens, "location": {"file": "a/a.go", "line": 1},
                              "claim": "bug", "evidence": "e", "epoch": epoch}])
        self.done(lens)
        tri = self.next()
        self.triaged([{"id": fid, "sources": [fid], "verdict": "dropped"}])
        return tri["task_action"]

    def test_triage_units_are_unique_across_groups(self):
        first = self.triage_group("review-1", "review-security", "f1")
        self.done(first)
        second = self.triage_group("review-2", "review-performance", "f2")
        self.assertNotEqual(first, second)
        self.done(second)
        self.assertEqual(self.next()["lens"], "after")


class RaisersTest(SettleCase):
    PIPELINE = dict(PIPELINE, lenses=[
        {"name": "workspace", "scope": "code", "implemented": True},
        {"name": "plan", "scope": "run", "implemented": True},
        {"name": "review-1", "scope": "settle", "implemented": True, "rerun": "raisers",
         "lenses": ["review-correctness", "review-security", "review-performance"]},
        {"name": "after", "scope": "run", "implemented": True},
    ])

    def raise_and_fix(self, actions, lens, fid, text, key=None, **row):
        """One reviewer raises a blocking defect; triage confirms it; the fixer edits a/a.go."""
        self.findings(key or lens, [self.finding(fid, lens=lens)])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([dict({"id": fid, "sources": [fid], "verdict": "confirmed", "blocking": True,
                            "class": "defect", "lens": lens, "claim": "bug"}, **row)])
        self.done(tri["task_action"])
        fix = self.next()
        self.assertEqual(fix["lens"], "fix")
        self.edit("a/a.go", f"package x\n// {text}\n")
        return self.done(fix["task_action"])

    def drain_clean(self, expect):
        again, _ = self.dispatch_all()
        self.assertEqual(sorted(u["lens"] for u in again), sorted(expect))
        for u in again:
            self.done(u["task_action"])
        return again

    def test_only_the_reviewer_that_raised_it_rereviews_the_radius(self):
        actions, _ = self.review_round()
        self.raise_and_fix(actions, "review-security", "f1", "fixed")
        again = self.drain_clean(["review-security"])
        self.assertEqual(again[0]["params"]["scope"], "radius")
        self.assertEqual(again[0]["params"]["radius"], ["a/a.go", "c/c.go"])

    def test_sweep_reviews_the_whole_change_with_every_reviewer_then_settles(self):
        actions, _ = self.review_round()
        self.raise_and_fix(actions, "review-security", "f1", "fixed")
        self.drain_clean(["review-security"])
        sweep = self.drain_clean(["review-correctness", "review-security", "review-performance"])
        self.assertTrue(all(u["params"]["scope"] == "full" for u in sweep))
        self.assertTrue(all("-sweep2" in u["task_action"] for u in sweep))
        self.assertEqual(self.next()["lens"], "after")

    def test_a_clean_first_batch_needs_no_sweep(self):
        actions, _ = self.review_round()
        for u in actions:
            self.done(u)
        self.assertEqual(self.next()["lens"], "after")

    def test_sweep_findings_loop_back_into_targeted_reruns(self):
        actions, _ = self.review_round()
        self.raise_and_fix(actions, "review-security", "f1", "one")
        self.drain_clean(["review-security"])
        sweep, _ = self.dispatch_all()
        self.raise_and_fix([u["task_action"] for u in sweep], "review-performance", "f2", "two",
                           key="review-performance-sweep2")
        self.drain_clean(["review-performance"])
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertEqual(self.group()["loop"], 2)

    def two_loops(self):
        actions, _ = self.review_round()
        self.raise_and_fix(actions, "review-security", "f1", "one", eli5="The lock was never released.")
        self.drain_clean(["review-security"])
        sweep, _ = self.dispatch_all()
        self.raise_and_fix([u["task_action"] for u in sweep], "review-performance", "f2", "two",
                           key="review-performance-sweep2")
        self.drain_clean(["review-performance"])
        return self.next()

    def test_every_second_loop_with_unswept_fixes_asks_the_user_with_a_table(self):
        relay = self.two_loops()
        self.assertEqual(relay["action"], "relay")
        table = relay["question"]["rendering"]
        self.assertIn("The lock was never released.", table)
        self.assertLess(table.index("review-security"), table.index("review-performance"))
        self.assertIn("fixed and re-checked by a full sweep", table)
        self.assertIn("fixed, not yet re-checked by a full sweep", table)
        self.assertEqual(relay["question"]["options"], ["continue", "stop here"])

    def test_continue_starts_another_full_sweep(self):
        relay = self.two_loops()
        lensctl.cmd_answer(self.run, "x", "continue", task_action=relay["task_action"])
        sweep, _ = self.dispatch_all()
        self.assertEqual(sorted(u["lens"] for u in sweep),
                         ["review-correctness", "review-performance", "review-security"])
        self.assertEqual(self.group()["loop"], 3)

    def test_stop_here_settles_without_another_sweep(self):
        relay = self.two_loops()
        lensctl.cmd_answer(self.run, "x", "stop here", task_action=relay["task_action"])
        self.assertEqual(self.next()["lens"], "after")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        self.assertTrue(report["settle"]["review-1"]["stopped_unswept"])

    def test_pre_existing_bug_is_stored_never_fixed_and_reported(self):
        actions, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "pre_existing", "lens": "review-security",
                       "claim": "old nil deref", "location": {"file": "b/b.go", "line": 9},
                       "repro": "base b/b.go:9 derefs p unchecked"}])
        self.done(tri["task_action"])
        self.assertEqual(self.next()["lens"], "after")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        found = report["settle"]["review-1"]["pre_existing"]
        self.assertEqual(found[0]["repro"], "base b/b.go:9 derefs p unchecked")
        self.assertEqual(found[0]["location"], {"file": "b/b.go", "line": 9})
        lines = lensctl.cmd_report(self.run)["rendering"]
        self.assertTrue(any("old nil deref" in l and "b/b.go:9" in l and "derefs p" in l for l in lines))


class HeldDuplicateTest(SettleCase):
    def test_a_held_finding_that_repeats_in_the_blocking_pass_never_dispatches_an_empty_fix(self):
        actions, _ = self.review_round()
        self.findings("review-correctness", [self.finding("f1", file="b/b.go")])
        for u in actions:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": False, "class": "defect"}])
        self.done(tri["task_action"])
        self.assertEqual(self.group()["items"]["f1"]["state"], "held")
        s = lensctl.load(self.run)
        s["settle"]["review-1"]["untriaged"] = ["f2"]
        lensctl.save(self.run, s)
        self.findings("review-correctness", [self.finding("f2", file="b/b.go")])
        s = lensctl.load(self.run)
        s["settle"]["review-1"]["task_actions"]["review-correctness"]["status"] = "done"
        lensctl.save(self.run, s)
        tri = self.next()
        self.triaged([{"id": "f2", "sources": ["f2"], "verdict": "confirmed", "blocking": False,
                       "class": "defect", "duplicate_of": "f1"}])
        self.done(tri["task_action"])
        nxt = self.next()
        self.assertEqual(nxt["lens"], "review-patcher")
        self.assertEqual(nxt["params"]["findings"], ["f1"])


if __name__ == "__main__":
    unittest.main()

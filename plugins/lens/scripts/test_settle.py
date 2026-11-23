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
         "lenses": ["review-correctness", "review-security"], "per_task": ["review-correctness"]},
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
        os.makedirs(os.path.join(self.run, "tasks"))
        for tid, target in (("t1", "a/a.go"), ("t2", "b/b.go")):
            with open(os.path.join(self.run, "tasks", f"{tid}.json"), "w") as f:
                json.dump({"id": tid, "target": [target]}, f)
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
        units = []
        while True:
            out = self.next()
            if out["action"] != "dispatch":
                return units, out
            units.append(out)

    def findings(self, unit, rows):
        path = os.path.join(self.run, "findings", f"{unit}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def triaged(self, rows):
        self.findings("triaged", rows)

    def done(self, unit, summary="ok"):
        return lensctl.cmd_record(self.run, "x", "done", summary, unit=unit)

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
        units, out = self.dispatch_all()
        return [u["unit"] for u in units], out


class SettleTest(SettleCase):
    # ---- tests -----------------------------------------------------------

    def test_reviewers_fan_out_per_task_and_whole(self):
        units, out = self.review_round()
        self.assertEqual(sorted(units), ["review-correctness-t1", "review-correctness-t2", "review-security"])
        self.assertEqual(out["action"], "wait")
        epoch = self.group()["epochs"][0]
        self.assertTrue(all(u["params"]["epoch"] == epoch for u in lensctl.load(self.run)["settle"]["review-1"]["units"].values()
                            if "epoch" in u["params"]))

    def test_clean_reviews_settle_and_move_on(self):
        units, _ = self.review_round()
        for u in units:
            self.done(u)
        self.assertEqual(self.next()["lens"], "after")
        self.assertEqual(lensctl.load(self.run)["lenses"]["review-1"]["status"], "done")

    def test_blocking_defect_is_fixed_and_radius_rereviewed(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.assertEqual((tri["lens"], tri["params"]["findings"]), ("triage", ["f1"]))
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.assertEqual((fix["lens"], fix["params"]["findings"]), ("fix", ["f1"]))
        self.edit("a/a.go", "package x\n// fixed\n")
        out = self.done(fix["unit"])
        self.assertEqual(out["radius"], ["a/a.go", "c/c.go"])
        rereview, _ = self.dispatch_all()
        keys = sorted(u["lens"] + ":" + str(u["task"]) for u in rereview)
        self.assertEqual(keys, ["review-correctness:t1", "review-security:None"])
        self.assertTrue(all(u["params"]["scope"] == "radius" for u in rereview))
        for u in rereview:
            self.done(u["unit"])
        self.assertEqual(self.next()["lens"], "after")

    def test_dropped_findings_are_not_fixed(self):
        units, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "dropped"}])
        self.done(tri["unit"])
        self.assertEqual(self.next()["lens"], "after")

    def test_deferred_findings_wait_for_the_patcher(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t2", [self.finding("f1", file="b/b.go")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": False, "class": "defect"}])
        self.done(tri["unit"])
        patch = self.next()
        self.assertEqual(patch["lens"], "review-patcher")
        self.assertEqual(self.group()["pass"], "deferred")
        self.edit("b/b.go", "package x\n// tidy\n")
        self.done(patch["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["unit"].split("-e")[0] for u in rereview),
                         ["review-correctness-t2", "review-security"])

    def test_design_finding_is_decided_by_the_user(self):
        units, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "design",
                       "claim": "which roles may call it?"}])
        self.done(tri["unit"])
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertIn("which roles", relay["question"]["question"])
        self.assertEqual(lensctl.cmd_answer(self.run, "x", "leave it", unit=relay["unit"])["continue"], "next")
        self.assertEqual(self.next()["lens"], "after")
        report = lensctl.build_report(self.run, lensctl.load(self.run))
        self.assertEqual(report["settle"]["review-1"]["findings"], {"dismissed": 1})
        self.assertEqual(report["gates"][0]["answer"], "leave it")

    def test_design_finding_fix_goes_to_fix_with_decision(self):
        units, _ = self.review_round()
        self.findings("review-security", [self.finding("f1", lens="review-security")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "design"}])
        self.done(tri["unit"])
        relay = self.next()
        lensctl.cmd_answer(self.run, "x", "fix it as proposed", unit=relay["unit"])
        self.assertEqual(self.next()["lens"], "fix")

    def test_finding_that_keeps_returning_escalates(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        for n in (2, 3):
            fix = self.next()
            self.assertEqual(fix["lens"], "fix")
            self.edit("a/a.go", f"package x\n// try {n}\n")
            self.done(fix["unit"])
            rereview, _ = self.dispatch_all()
            r = next(u for u in rereview if u["lens"] == "review-correctness")
            self.findings(r["unit"], [self.finding(f"f{n}")])
            for u in rereview:
                self.done(u["unit"])
            tri = self.next()
            self.triaged([{"id": f"f{n}", "sources": [f"f{n}"], "verdict": "confirmed", "blocking": True,
                           "class": "defect", "duplicate_of": "f1"}])
            self.done(tri["unit"])
        relay = self.next()
        self.assertEqual(relay["action"], "relay")
        self.assertIn("came back", relay["question"]["question"])

    def test_epoch_cap_halts(self):
        settle.MAX_EPOCHS = 0
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        out = self.done(fix["unit"])
        self.assertIn("epochs", out["halt"]["reason"])
        self.assertEqual(self.next()["action"], "halt")

    def test_failed_reviewer_retries_then_halts(self):
        units, _ = self.review_round()
        lensctl.cmd_record(self.run, "x", "failed", "boom", unit=units[0])
        again = self.next()
        self.assertEqual(again["unit"], units[0])
        out = lensctl.cmd_record(self.run, "x", "failed", "boom", unit=units[0])
        self.assertIsNotNone(out["halt"])

    def test_resume_requeues_running_reviewers(self):
        units, _ = self.review_round()
        out = lensctl.cmd_resume(self.run)
        self.assertEqual((out["action"], out["unit"], out["attempt"]), ("dispatch", units[0], 1))

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
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["unit"].split("-e")[0] for u in rereview), ["review-correctness-t2", "review-security"])

    def writer_group(self):
        st = lensctl.load(self.run)
        e = next(x for x in st["pipeline"]["lenses"] if x["name"] == "review-1")
        e.update(lenses=["contract-test", "e2e-test"], per_task=[], per_boundary=["contract-test"], writers=True)
        lensctl.save(self.run, st)
        os.makedirs(os.path.join(self.run, "scenarios", "contract"))
        for b, pkg in (("blob-store", "a"), ("api", "b")):
            with open(os.path.join(self.run, "scenarios", "contract", f"{b}.json"), "w") as f:
                json.dump({"boundary": b, "package": pkg, "cases": []}, f)

    def test_contract_tests_run_one_per_boundary(self):
        self.writer_group()
        units, _ = self.review_round()
        self.assertEqual(sorted(units), ["contract-test-api", "contract-test-blob-store", "e2e-test"])

    def test_writers_never_overlap_the_fixer(self):
        self.writer_group()
        units, _ = self.review_round()
        self.findings("contract-test-blob-store", [self.finding("f1", lens="contract-test")])
        self.done("contract-test-blob-store")
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        self.assertEqual(self.next()["action"], "wait")
        for u in ("contract-test-api", "e2e-test"):
            self.done(u)
        fix = self.next()
        self.assertEqual(fix["lens"], "fix")
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["unit"].split("-e")[0] for u in rereview), ["contract-test-blob-store", "e2e-test"])

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
        units, _ = self.review_round()
        self.assertEqual(sorted(units), ["review-correctness-t1", "review-correctness-t2"])
        self.assertEqual(self.group()["deselected"], {"review-security": "no trust boundary"})
        self.assertEqual(settle.report(lensctl.load(self.run))["review-1"]["deselected"],
                         {"review-security": "no trust boundary"})

    def test_missing_selection_drops_nothing(self):
        self.gate()
        units, _ = self.review_round()
        self.assertEqual(sorted(units), ["review-correctness-t1", "review-correctness-t2", "review-security"])

    def test_deselected_lens_is_skipped_on_radius_rereview(self):
        self.gate({"review-security": {"apply": False, "reason": "none"}})
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual([u["unit"].split("-e")[0] for u in rereview], ["review-correctness-t1"])

    def test_not_applicable_retires_the_lens_for_later_epochs(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            if u == "review-security":
                lensctl.cmd_record(self.run, "x", "not_applicable", "no trust boundary", unit=u)
            else:
                self.done(u)
        self.assertEqual(self.group()["retired"], ["review-security"])
        self.assertEqual(self.group()["units"]["review-security"]["status"], "done")
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual([u["unit"].split("-e")[0] for u in rereview], ["review-correctness-t1"])
        self.assertEqual(settle.report(lensctl.load(self.run))["review-1"]["retired"], ["review-security"])

    def test_not_applicable_retires_only_that_task(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t2", [self.finding("f1", file="b/b.go")])
        for u in units:
            if u == "review-correctness-t1":
                lensctl.cmd_record(self.run, "x", "not_applicable", "nothing here", unit=u)
            else:
                self.done(u)
        self.assertEqual(self.group()["retired"], ["review-correctness:t1"])
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.edit("b/b.go", "package x\n// fixed\n")
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        self.assertEqual(sorted(u["unit"].split("-e")[0] for u in rereview), ["review-correctness-t2", "review-security"])

    def test_radius_not_applicable_does_not_retire(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        self.triaged([{"id": "f1", "sources": ["f1"], "verdict": "confirmed", "blocking": True, "class": "defect"}])
        self.done(tri["unit"])
        fix = self.next()
        self.edit("a/a.go", "package x\n// fixed\n")
        self.done(fix["unit"])
        rereview, _ = self.dispatch_all()
        sec = next(u["unit"] for u in rereview if u["unit"].startswith("review-security"))
        lensctl.cmd_record(self.run, "x", "not_applicable", "none in radius", unit=sec)
        self.assertEqual(self.group()["retired"], [])

    def test_not_applicable_from_a_triage_unit_is_rejected(self):
        units, _ = self.review_round()
        self.findings("review-correctness-t1", [self.finding("f1")])
        for u in units:
            self.done(u)
        tri = self.next()
        with self.assertRaises(lensctl.LensError):
            lensctl.cmd_record(self.run, "x", "not_applicable", "", unit=tri["unit"])

    def test_unit_dispute_rewinds_to_earlier_lens(self):
        units, _ = self.review_round()
        with open(os.path.join(self.run, "disputes", f"{units[0]}-1.json"), "w") as f:
            json.dump({"target_lens": "plan", "claim": "task split is wrong", "evidence": "x"}, f)
        out = lensctl.cmd_record(self.run, "x", "blocked", unit=units[0])
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
        units, _ = self.review_round()
        self.assertEqual(units, [lens])
        epoch = lensctl.load(self.run)["settle"][group]["epochs"][-1]
        self.findings(lens, [{"id": fid, "lens": lens, "location": {"file": "a/a.go", "line": 1},
                              "claim": "bug", "evidence": "e", "epoch": epoch}])
        self.done(lens)
        tri = self.next()
        self.triaged([{"id": fid, "sources": [fid], "verdict": "dropped"}])
        return tri["unit"]

    def test_triage_units_are_unique_across_groups(self):
        first = self.triage_group("review-1", "review-security", "f1")
        self.done(first)
        second = self.triage_group("review-2", "review-performance", "f2")
        self.assertNotEqual(first, second)
        self.done(second)
        self.assertEqual(self.next()["lens"], "after")


if __name__ == "__main__":
    unittest.main()

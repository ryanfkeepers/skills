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

HAS_JJ = shutil.which("jj") is not None


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def jj_out(cwd, *args):
    return subprocess.run(["jj", "--no-pager", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(HAS_JJ, "jj not installed")
class CoresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        os.makedirs(self.repo)
        sh(self.repo, "jj", "git", "init")
        sh(self.repo, "jj", "config", "set", "--repo", "revset-aliases.'trunk()'", "main")
        sh(self.repo, "jj", "config", "set", "--repo", "user.name", "t")
        sh(self.repo, "jj", "config", "set", "--repo", "user.email", "t@t")
        self.commit("a.go", "package a\n", "first")
        self.first = self.commit_id("@-")
        self.commit("b.go", "package a\n", "second")
        sh(self.repo, "jj", "bookmark", "create", "main", "-r", "@-")
        self.real_home = os.environ.get("LENS_HOME")
        os.environ["LENS_HOME"] = self.home
        self.updates = []
        self.real_update = cores.graphify_update
        cores.graphify_update = self.fake_update

    def tearDown(self):
        cores.graphify_update = self.real_update
        if self.real_home is None:
            os.environ.pop("LENS_HOME", None)
        else:
            os.environ["LENS_HOME"] = self.real_home
        self.tmp.cleanup()

    def commit(self, name, text, msg):
        with open(os.path.join(self.repo, name), "w") as f:
            f.write(text)
        sh(self.repo, "jj", "commit", "-m", msg)

    def commit_id(self, rev):
        return jj_out(self.repo, "log", "--no-graph", "-r", rev, "-T", "commit_id")

    def fake_update(self, target, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "graph.json"), "w") as f:
            json.dump({"target": target}, f)
        self.updates.append((target, out_dir))

    def new_run(self, base=None):
        run = lensctl.cmd_init(self.repo, "p", base=base)["run"]
        return run, lensctl.load(run)

    def workspace(self, run, st, answers=()):
        return cores.workspace_lens(run, st, list(answers))

    def ws(self, run):
        with open(os.path.join(run, "workspace.json")) as f:
            return json.load(f)

    # ---- workspace -------------------------------------------------------

    def test_trunk_base_adds_isolated_workspace(self):
        run, st = self.new_run()
        out = self.workspace(run, st)
        self.assertEqual(out["status"], "done")
        ws = self.ws(run)
        self.assertEqual((ws["mode"], ws["base_commit"]), ("trunk", self.commit_id("main")))
        self.assertTrue(os.path.exists(os.path.join(ws["path"], "b.go")))
        self.assertTrue(ws["path"].startswith(self.home))
        self.assertIn(ws["name"], jj_out(self.repo, "workspace", "list"))

    def test_older_trunk_base_asks_then_patches(self):
        run, st = self.new_run(base=self.first)
        self.assertEqual(self.workspace(run, st)["status"], "needs_input")
        self.workspace(run, st, ["patch"])
        ws = self.ws(run)
        self.assertEqual((ws["mode"], ws["base_commit"]), ("patch", self.first))

    def test_older_trunk_base_can_move_to_latest(self):
        run, st = self.new_run(base=self.first)
        self.workspace(run, st, ["latest trunk"])
        self.assertEqual(self.ws(run)["mode"], "trunk")
        self.assertEqual(self.ws(run)["base_commit"], self.commit_id("main"))

    def test_side_branch_base_is_branch_mode(self):
        sh(self.repo, "jj", "new", "main")
        self.commit("c.go", "package a\n", "side")
        run, st = self.new_run(base=self.commit_id("@-"))
        self.workspace(run, st)
        self.assertEqual(self.ws(run)["mode"], "branch")

    def test_rerun_reuses_recorded_workspace(self):
        run, st = self.new_run()
        self.workspace(run, st)
        before = self.ws(run)
        out = self.workspace(run, st)
        self.assertEqual(out["status"], "done")
        self.assertIn(before["name"], out["summary"])
        self.assertEqual(self.ws(run), before)
        self.assertEqual(jj_out(self.repo, "workspace", "list").count(before["name"]), 1)

    def test_rerun_with_missing_workspace_dir_raises(self):
        run, st = self.new_run()
        self.workspace(run, st)
        shutil.rmtree(self.ws(run)["path"])
        with self.assertRaises(cores.CoreError):
            self.workspace(run, st)

    # ---- graph -----------------------------------------------------------

    def test_trunk_run_snapshots_the_core_built_by_init(self):
        run, st = self.new_run()
        self.workspace(run, st)
        cores.graph_core_lens(st, self.home)
        cores.graph_lens(run, st, self.home)
        core_ws = os.path.join(self.home, st["repo_slug"], "graph", "core", "workspace")
        self.assertEqual(self.updates, [(core_ws, os.path.join(os.path.dirname(core_ws), "out"))])
        with open(os.path.join(run, "snapshot.json")) as f:
            snap = json.load(f)
        self.assertTrue(os.path.exists(snap["base"]))
        self.assertTrue(os.path.exists(snap["live"]))
        self.assertEqual(snap["core_commit"], self.commit_id("main"))

    def test_newer_trunk_updates_core_and_same_trunk_reuses_it(self):
        run, st = self.new_run()
        self.workspace(run, st)
        cores.graph_core_lens(st, self.home)
        cores.graph_lens(run, st, self.home)
        run2, st2 = self.new_run()
        self.workspace(run2, st2)
        cores.graph_lens(run2, st2, self.home)
        self.assertEqual(len(self.updates), 1)
        sh(self.repo, "jj", "new", "main")
        self.commit("d.go", "package a\n", "third")
        sh(self.repo, "jj", "bookmark", "set", "main", "-r", "@-")
        run3, st3 = self.new_run()
        self.workspace(run3, st3)
        cores.graph_lens(run3, st3, self.home)
        self.assertEqual(len(self.updates), 2)
        commit_file = os.path.join(self.home, st3["repo_slug"], "graph", "core", "commit")
        with open(commit_file) as f:
            self.assertEqual(f.read().strip(), self.commit_id("main"))

    def test_branch_run_updates_snapshot_not_core(self):
        run, st = self.new_run()
        self.workspace(run, st)
        cores.graph_core_lens(st, self.home)
        cores.graph_lens(run, st, self.home)
        sh(self.repo, "jj", "new", "main")
        self.commit("c.go", "package a\n", "side")
        run2, st2 = self.new_run(base=self.commit_id("@-"))
        self.workspace(run2, st2)
        cores.graph_lens(run2, st2, self.home)
        target, out_dir = self.updates[-1]
        self.assertEqual(target, self.ws(run2)["path"])
        self.assertTrue(out_dir.endswith(os.path.join(st2["run_id"], "base")))

    def test_run_without_core_graph_raises(self):
        run, st = self.new_run()
        self.workspace(run, st)
        with self.assertRaises(cores.CoreError):
            cores.graph_lens(run, st, self.home)
        self.assertEqual(self.updates, [])

    def test_graph_core_lens_builds_at_trunk_then_leaves_it_alone(self):
        _, st = self.new_run()
        self.assertFalse(cores.core_graph_present(self.home, st["repo_slug"]))
        out = cores.graph_core_lens(st, self.home)
        self.assertIn("built", out["summary"])
        self.assertTrue(cores.core_graph_present(self.home, st["repo_slug"]))
        self.assertEqual(len(self.updates), 1)
        out = cores.graph_core_lens(st, self.home)
        self.assertIn("already", out["summary"])
        self.assertEqual(len(self.updates), 1)

    def test_graph_core_lens_advances_a_core_behind_trunk(self):
        _, st = self.new_run()
        cores.graph_core_lens(st, self.home)
        sh(self.repo, "jj", "new", "main")
        self.commit("d.go", "package a\n", "third")
        sh(self.repo, "jj", "bookmark", "set", "main", "-r", "@-")
        out = cores.graph_core_lens(st, self.home)
        self.assertIn("advanced", out["summary"])
        commit_file = cores.graph_paths(self.home, st["repo_slug"])["commit"]
        with open(commit_file) as f:
            self.assertEqual(f.read().strip(), self.commit_id("main"))

    def test_graph_core_lens_rebuilds_a_cut_off_build(self):
        _, st = self.new_run()
        cores.graph_core_lens(st, self.home)
        paths = cores.graph_paths(self.home, st["repo_slug"])
        os.remove(os.path.join(paths["out"], "graph.json"))
        self.assertEqual(cores.missing_cores(self.home, st["repo_slug"])[0], "graph")
        out = cores.graph_core_lens(st, self.home)
        self.assertIn("built", out["summary"])
        self.assertTrue(cores.core_graph_present(self.home, st["repo_slug"]))

    # ---- cleanup ---------------------------------------------------------

    def test_cleanup_forgets_and_removes_workspace(self):
        run, st = self.new_run()
        self.workspace(run, st)
        ws = self.ws(run)
        cores.cleanup_lens(run, st)
        self.assertFalse(os.path.exists(ws["path"]))
        self.assertNotIn(ws["name"], jj_out(self.repo, "workspace", "list"))

    # ---- lensctl wiring --------------------------------------------------

    def test_code_lens_question_relays_and_continues(self):
        run, st = self.new_run(base=self.first)
        st["pipeline"]["lenses"] = [e for e in st["pipeline"]["lenses"] if e["name"] == "workspace"]
        st["order"] = ["workspace"]
        lensctl.save(run, st)
        out = lensctl.cmd_next(run)
        self.assertEqual(out["action"], "relay")
        self.assertEqual(lensctl.cmd_answer(run, "workspace", "patch")["continue"], "next")
        self.assertEqual(lensctl.cmd_next(run), {"action": "done"})
        self.assertEqual(self.ws(run)["mode"], "patch")


@unittest.skipUnless(HAS_JJ, "jj not installed")
class ApplyDescriptionsTest(unittest.TestCase):
    setUp, tearDown = CoresTest.setUp, CoresTest.tearDown
    commit, commit_id, fake_update = CoresTest.commit, CoresTest.commit_id, CoresTest.fake_update
    new_run, workspace, ws = CoresTest.new_run, CoresTest.workspace, CoresTest.ws

    def test_descriptions_are_applied_per_slice(self):
        run, st = self.new_run()
        self.workspace(run, st)
        ws = self.ws(run)["path"]
        with open(os.path.join(ws, "x.go"), "w") as f:
            f.write("package a\n")
        change = jj_out(ws, "log", "--no-graph", "-r", "@", "-T", "change_id")
        with open(os.path.join(run, "stack.json"), "w") as f:
            json.dump({"slices": [{"change_id": change}]}, f)
        os.makedirs(os.path.join(run, "descriptions"))
        with open(os.path.join(run, "descriptions", f"{change}.txt"), "w") as f:
            f.write("add x\n\nbody\n")
        out = lensctl.code_apply_descriptions(run, st, [])
        self.assertEqual(out["status"], "done")
        self.assertEqual(jj_out(ws, "log", "--no-graph", "-r", change, "-T", "description.first_line()"), "add x")

    def test_missing_description_errors(self):
        run, st = self.new_run()
        self.workspace(run, st)
        with open(os.path.join(run, "stack.json"), "w") as f:
            json.dump({"slices": [{"change_id": "zzz"}]}, f)
        with self.assertRaises(cores.CoreError):
            lensctl.code_apply_descriptions(run, st, [])


class MarkdownCoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.run = os.path.join(self.tmp.name, "run")
        self.slug = "repo-1"

    def tearDown(self):
        self.tmp.cleanup()

    def pend(self, rel, text):
        path = os.path.join(self.run, "pending", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def test_promote_and_resolve_prefers_service(self):
        self.pend("conventions/repo/code.md", "repo code")
        self.pend("conventions/repo/tests.md", "repo tests")
        self.pend("conventions/services/ingest/code.md", "ingest code")
        self.pend("conventions/services/ingest/root.txt", "services/ingest\n")
        moved = cores.promote(self.run, self.home, self.slug, "conventions")
        self.assertEqual(len(moved), 3)
        self.assertFalse(os.path.exists(os.path.join(self.run, "pending", "conventions")))
        files = cores.resolve(self.home, self.slug, "conventions", ["services/ingest/x.go"])
        self.assertTrue(files[0].endswith(os.path.join("services", "ingest", "conventions", "code.md")))
        self.assertEqual(len(files), 3)
        files = cores.resolve(self.home, self.slug, "conventions", ["cmd/main.go"])
        self.assertEqual(len(files), 2)

    def test_contract_layers_core_lives_at_repo_root(self):
        self.pend("contract-layers/repo/contract-layers.md", "layers")
        cores.promote(self.run, self.home, self.slug, "contract-layers")
        self.assertTrue(os.path.exists(os.path.join(self.home, self.slug, "contract-layers.md")))
        self.assertTrue(cores.core_exists(self.home, self.slug, "contract-layers"))
        self.assertFalse(cores.core_exists(self.home, self.slug, "conventions"))

    def test_promote_without_pending_errors(self):
        with self.assertRaises(cores.CoreError):
            cores.promote(self.run, self.home, self.slug, "conventions")


if __name__ == "__main__":
    unittest.main()

    def test_missing_cores_lists_every_unbuilt_core(self):
        self.assertEqual(cores.missing_cores(self.home, self.slug),
                         ["graph", "conventions", "contract-layers"])
        paths = cores.graph_paths(self.home, self.slug)
        os.makedirs(paths["out"])
        open(os.path.join(paths["out"], "graph.json"), "w").close()
        with open(paths["commit"], "w") as f:
            f.write("abc\n")
        self.assertEqual(cores.missing_cores(self.home, self.slug), ["conventions", "contract-layers"])
        self.pend("conventions/repo/code.md", "c")
        self.pend("conventions/repo/tests.md", "t")
        cores.promote(self.run, self.home, self.slug, "conventions")
        self.assertEqual(cores.missing_cores(self.home, self.slug), ["contract-layers"])
        self.pend("contract-layers/repo/contract-layers.md", "l")
        cores.promote(self.run, self.home, self.slug, "contract-layers")
        self.assertEqual(cores.missing_cores(self.home, self.slug), [])

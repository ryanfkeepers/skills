import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "..")


def load():
    with open(os.path.join(PLUGIN, "pipeline.json")) as f:
        return json.load(f)


def agent_files():
    return {n[:-3] for n in os.listdir(os.path.join(PLUGIN, "agents")) if n.endswith(".md")}


class PipelineTest(unittest.TestCase):
    def test_every_dispatched_lens_has_an_agent_file(self):
        agents = agent_files()
        missing = []
        for e in load()["lenses"]:
            scope = e.get("scope")
            if scope in ("code", "sleep"):
                continue
            names = e["lenses"] if scope in ("settle", "parallel") else [e.get("agent", e["name"])]
            missing += [n for n in names if n not in agents]
        self.assertEqual(missing, [])

    def test_build_is_two_run_lenses_in_order(self):
        names = [e["name"] for e in load()["lenses"]]
        self.assertEqual(names[names.index("implement"):names.index("implement") + 3],
                         ["implement", "unit-test", "green"])
        self.assertTrue(all(e["scope"] == "run" for e in load()["lenses"] if e["name"] in ("implement", "unit-test")))

    def test_no_lens_uses_the_retired_grid_scope(self):
        self.assertNotIn("grid", {e.get("scope") for e in load()["lenses"]})

    def test_retired_agents_stay_gone(self):
        self.assertEqual(agent_files() & {"scaffold", "test-coverage", "design-trim"}, set())

    def test_review_sets_rerun_only_their_raisers(self):
        reruns = {e["name"]: e.get("rerun") for e in load()["lenses"] if e["name"].startswith("review-")}
        self.assertEqual(reruns["review-1"], "raisers")
        self.assertEqual(reruns["review-2"], "raisers")


if __name__ == "__main__":
    unittest.main()

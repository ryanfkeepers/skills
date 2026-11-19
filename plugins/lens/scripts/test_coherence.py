import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coherence  # noqa: E402


def node(nid, path, comm):
    return {"id": nid, "source_file": path, "community": comm}


def imp(a, b):
    return {"source": a, "target": b, "relation": "imports"}


def call(a, b):
    return {"source": a, "target": b, "relation": "calls"}


BASE_NODES = [node("api", "api/h.go", 0), node("svc", "svc/s.go", 1), node("store", "store/s.go", 2),
              node("svc2", "svc/t.go", 1), node("util", "util/u.go", 3)]
BASE_LINKS = [imp("api", "svc"), imp("svc", "store"), call("svc", "svc2"), call("svc2", "svc")]


class CoherenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def graphs(self, nodes, links):
        paths = []
        for name, g in (("base", {"nodes": BASE_NODES, "links": BASE_LINKS}), ("live", {"nodes": nodes, "links": links})):
            path = os.path.join(self.tmp.name, f"{name}.json")
            with open(path, "w") as f:
                json.dump(g, f)
            paths.append(path)
        return coherence.report(*paths)

    def signals(self, out):
        return [f["signal"] for f in out["findings"]]

    def test_unchanged_graph_has_no_findings(self):
        out = self.graphs(BASE_NODES, BASE_LINKS)
        self.assertEqual(out["findings"], [])
        self.assertEqual(out["signals"]["new_edges"], 0)

    def test_inverted_import_is_a_new_cycle_and_a_direction_violation(self):
        out = self.graphs(BASE_NODES, BASE_LINKS + [imp("store", "api")])
        self.assertIn("new_cycle", self.signals(out))
        self.assertIn("direction_violation", self.signals(out))
        self.assertEqual(out["signals"]["new_cycles"], 1)
        cycle = next(f for f in out["findings"] if f["signal"] == "new_cycle")
        self.assertEqual(cycle["packages"], ["api", "store", "svc"])

    def test_edge_within_a_community_is_coherent(self):
        out = self.graphs(BASE_NODES + [node("svc3", "svc/u.go", 1)], BASE_LINKS + [call("svc3", "svc")])
        self.assertNotIn("cross_community", self.signals(out))
        self.assertEqual(out["signals"]["cross_community_ratio"], 0.0)

    def test_new_nodes_spread_across_communities_scatter(self):
        extra = [node("n1", "x/a.go", 0), node("n2", "x/b.go", 1), node("n3", "x/c.go", 2), node("n4", "x/d.go", 3)]
        links = BASE_LINKS + [call("n1", "api"), call("n2", "svc"), call("n3", "store"), call("n4", "util")]
        out = self.graphs(BASE_NODES + extra, links)
        self.assertIn("concept_scatter", self.signals(out))

    def test_node_pushed_into_top_degree_quartile_is_hub_growth(self):
        extra = [node(f"c{i}", f"c/{i}.go", 3) for i in range(5)]
        out = self.graphs(BASE_NODES + extra, BASE_LINKS + [call(f"c{i}", "util") for i in range(5)])
        hubs = [f for f in out["findings"] if f["signal"] == "hub_growth"]
        self.assertEqual([h["node"] for h in hubs], ["util"])


class SqaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = os.path.join(self.tmp.name, "ws")
        for rel in ("api/h.go", "svc/s.go", "store/s.go"):
            os.makedirs(os.path.join(self.ws, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(self.ws, rel), "w") as f:
                f.write("package x\n\nfunc F() {}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def graph(self, name, links):
        nodes = [{"id": n, "source_file": f, "file_type": "code", "label": n, "community": i}
                 for i, (n, f) in enumerate((("api", "api/h.go"), ("svc", "svc/s.go"), ("store", "store/s.go")))]
        path = os.path.join(self.tmp.name, f"{name}.json")
        with open(path, "w") as f:
            json.dump({"nodes": nodes, "links": links}, f)
        return path

    def test_missing_build_data_is_reported_not_fatal(self):
        base = self.graph("base", [imp("api", "svc")])
        out = coherence.sqa_deltas(base, base, self.ws, os.path.join(self.tmp.name, "w"),
                                   build_data=os.path.join(self.tmp.name, "nope.py"))
        self.assertFalse(out["available"])

    @unittest.skipUnless(coherence.find_build_data(), "service-quality-analysis not found")
    def test_new_cycle_regresses_structural_metrics(self):
        base = self.graph("base", [imp("api", "svc"), imp("svc", "store")])
        live = self.graph("live", [imp("api", "svc"), imp("svc", "store"), imp("store", "api")])
        out = coherence.full_report(base, live, self.ws, os.path.join(self.tmp.name, "w"))
        self.assertTrue(out["sqa"]["available"], out["sqa"])
        regressed = {r["metric"] for r in out["sqa"]["regressions"]}
        self.assertIn("acd", regressed)
        self.assertIn("sqa_regression", [f["signal"] for f in out["findings"]])
        self.assertFalse(os.path.islink(os.path.join(self.ws, "graphify-out")))


if __name__ == "__main__":
    unittest.main()

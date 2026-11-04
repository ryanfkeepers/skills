"""Offline tests for create_ticket.py. Run: python3 -m unittest discover -s <this dir>"""
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import create_ticket as ct  # noqa: E402

TEMPLATE = Path(__file__).parent.parent / "TEMPLATE.md"
SCRIPT = Path(__file__).parent / "create_ticket.py"


def walk(node):
    yield node
    for child in node.get("content", []) if isinstance(node, dict) else []:
        yield from walk(child)


TWO_HALVES = (
    "# What\n\nTop.\n\n# Requirements\n\n| id | name |\n|----|------|\n| R1 | a |\n\n"
    "<hr>\n\n# Agent Dump Section\n\n## Background\n\nDetail.\n\n## Non-Goals\n\n- none\n"
)


def valid_spec(**overrides):
    spec = {
        "summary": "Title",
        "description": "# What\n\nBody.",
        "points": 3,
        "epic": None,
    }
    spec.update(overrides)
    return spec


class MarkdownToAdf(unittest.TestCase):
    def test_blocks(self):
        doc = ct.md_to_adf(
            "# Head\n\nline one\nline two\n\n- a\n- b\n\n1. x\n\n---\n\n<hr>\n\n```go\nx := 1\n```\n"
        )
        kinds = [b["type"] for b in doc["content"]]
        self.assertEqual(
            kinds,
            ["heading", "paragraph", "bulletList", "orderedList", "rule", "rule", "codeBlock"],
        )
        self.assertEqual(doc["content"][1]["content"][0]["text"], "line one line two")
        self.assertEqual(doc["content"][6]["attrs"], {"language": "go"})

    def test_table_header_body_and_escaped_pipe(self):
        doc = ct.md_to_adf("| id | name |\n|----|------|\n| R1 | a \\| b |\n| R2 |\n")
        table = doc["content"][0]
        self.assertEqual(table["type"], "table")
        header, row1, row2 = table["content"]
        self.assertEqual([c["type"] for c in header["content"]], ["tableHeader"] * 2)
        self.assertEqual(row1["content"][1]["content"][0]["content"][0]["text"], "a | b")
        self.assertEqual(len(row2["content"]), 2)

    def test_inline_marks(self):
        nodes = ct.inline("see `code`, **bold `c`**, [t](https://a.b/c) and https://d.e/f.")
        by_text = {n["text"]: n.get("marks", []) for n in nodes}
        self.assertEqual(by_text["code"], [{"type": "code"}])
        self.assertEqual(by_text["bold "], [{"type": "strong"}])
        self.assertEqual(by_text["c"], [{"type": "code"}])
        self.assertEqual(by_text["t"][0]["attrs"]["href"], "https://a.b/c")
        self.assertEqual(by_text["https://d.e/f"][0]["attrs"]["href"], "https://d.e/f")
        self.assertEqual(nodes[-1]["text"], ".")

    def test_heading_keeps_trailing_hash(self):
        doc = ct.md_to_adf("# Learn C#")
        self.assertEqual(doc["content"][0]["content"][0]["text"], "Learn C#")

    def test_template_example_converts_to_valid_shape(self):
        blocks = re.findall(r"````markdown\n(.*?)\n````", TEMPLATE.read_text(), re.S)
        self.assertEqual(len(blocks), 2, "template skeleton and worked example")
        for block in blocks:
            doc = ct.md_to_adf(block)
            nodes = list(walk(doc))
            kinds = [n["type"] for n in doc["content"]]
            self.assertEqual(kinds.count("rule"), 1)
            self.assertEqual(kinds.count("table"), 2)
            self.assertEqual(kinds.count("bulletList"), 1)
            headings = [
                n["content"][0]["text"] for n in nodes if n["type"] == "heading"
            ]
            self.assertEqual(
                headings,
                ["What", "Why", "Requirements", "Agent Dump Section",
                 "Background", "Scope", "Non-Goals"],
            )
            for node in nodes:
                if node["type"] == "text":
                    self.assertTrue(node["text"])
                if node["type"] == "table":
                    for row in node["content"]:
                        self.assertEqual(row["type"], "tableRow")
                        self.assertTrue(
                            all(c["type"] in ("tableHeader", "tableCell") for c in row["content"])
                        )


class SpecValidation(unittest.TestCase):
    def problems(self, spec):
        with self.assertRaises(ct.UsageError) as ctx:
            ct.normalize_spec(spec)
        return " | ".join(ctx.exception.problems)

    def test_defaults(self):
        spec = ct.normalize_spec(valid_spec())
        self.assertEqual(spec["priority"], "Medium")
        self.assertEqual(spec["team"], "UE - Data Pipelines")
        self.assertEqual(spec["project"], "DP")
        self.assertEqual(spec["labels"], [])
        self.assertIsNone(spec["epic"])

    def test_points_required_and_numeric(self):
        missing = valid_spec()
        del missing["points"]
        self.assertIn("ask the user for the story points", self.problems(missing))
        self.assertIn("points must be a number", self.problems(valid_spec(points="3")))
        self.assertIn("points must be a number", self.problems(valid_spec(points=0)))
        self.assertIn("points must be a number", self.problems(valid_spec(points=True)))
        self.assertEqual(ct.normalize_spec(valid_spec(points=3.0))["points"], 3)

    def test_epic_key_must_be_present(self):
        missing = valid_spec()
        del missing["epic"]
        self.assertIn("epic is required", self.problems(missing))
        self.assertIn("not an issue key", self.problems(valid_spec(epic="epic")))
        self.assertEqual(ct.normalize_spec(valid_spec(epic="DP-3013"))["epic"], "DP-3013")

    def test_labels_limited_to_allowed_set(self):
        self.assertIn("not allowed", self.problems(valid_spec(labels=["earn", "backend"])))
        spec = ct.normalize_spec(valid_spec(labels=["ops", "earn", "ops"]))
        self.assertEqual(spec["labels"], ["ops", "earn"])

    def test_priority_case_insensitive(self):
        self.assertEqual(ct.normalize_spec(valid_spec(priority="high"))["priority"], "High")
        self.assertIn("priority", self.problems(valid_spec(priority="soon")))

    def test_unknown_key_and_description_choice(self):
        self.assertIn("unknown keys: point", self.problems(valid_spec(point=1)))
        both = valid_spec(description_file="/nope")
        self.assertIn("exactly one", self.problems(both))
        self.assertIn("cannot read description_file", self.problems(
            {k: v for k, v in valid_spec(description_file="/nope").items() if k != "description"}
        ))

    def test_all_problems_reported_together(self):
        text = self.problems({"summary": "", "labels": ["x"]})
        for needle in ("summary", "description", "points", "epic", "labels"):
            self.assertIn(needle, text)

    def test_agent_dump_problems(self):
        self.assertIn("agent_dump 'inline' is not one of",
                      self.problems(valid_spec(agent_dump="inline")))
        self.assertIn("has no '# Agent Dump Section' heading",
                      self.problems(valid_spec(agent_dump="comment")))
        only_dump = "# Agent Dump Section\n\n## Background\n\nx"
        self.assertIn("nothing is left for the description",
                      self.problems(valid_spec(description=only_dump, agent_dump="comment")))

    def test_bad_links_and_dedupe(self):
        self.assertIn("bad link", self.problems(valid_spec(links=[{"type": "causes", "key": "DP-1"}])))
        self.assertIn("bad link", self.problems(valid_spec(links=[{"type": "relates", "key": "dp-1"}])))
        link = {"type": "relates", "key": "DP-1"}
        self.assertEqual(ct.normalize_spec(valid_spec(links=[link, dict(link)]))["links"], [link])


class AgentDumpSplit(unittest.TestCase):
    def test_split_drops_the_separating_rule(self):
        top, dump = ct.split_agent_dump(TWO_HALVES)
        self.assertTrue(top.endswith("| R1 | a |"))
        self.assertNotIn("<hr>", top)
        self.assertTrue(dump.startswith("# Agent Dump Section"))
        self.assertTrue(dump.endswith("- none"))

    def test_split_handles_markdown_rule_and_missing_heading(self):
        top, dump = ct.split_agent_dump("# What\n\nx\n\n---\n\n# Agent Dump Section\n\ny")
        self.assertEqual(top, "# What\n\nx")
        self.assertEqual(dump, "# Agent Dump Section\n\ny")
        body = "# What\n\nx\n\n## Agent Dump Section\n\ny"
        self.assertEqual(ct.split_agent_dump(body), (body, None))

    def test_template_example_splits_into_two_tables_and_a_list(self):
        example = re.findall(r"````markdown\n(.*?)\n````", TEMPLATE.read_text(), re.S)[1]
        top, dump = ct.split_agent_dump(example)
        top_kinds = [b["type"] for b in ct.md_to_adf(top)["content"]]
        dump_kinds = [b["type"] for b in ct.md_to_adf(dump)["content"]]
        self.assertEqual(top_kinds.count("table"), 1)
        self.assertNotIn("rule", top_kinds)
        self.assertEqual(dump_kinds.count("table"), 1)
        self.assertEqual(dump_kinds.count("bulletList"), 1)

    def test_default_keeps_whole_body_in_description(self):
        spec = ct.normalize_spec(valid_spec(description=TWO_HALVES))
        self.assertEqual(spec["description"], TWO_HALVES)
        self.assertIsNone(spec["comment"])

    def test_comment_mode_moves_the_dump(self):
        spec = ct.normalize_spec(valid_spec(description=TWO_HALVES, agent_dump="comment"))
        self.assertNotIn("Agent Dump", spec["description"])
        self.assertTrue(spec["comment"].startswith("# Agent Dump Section"))
        fields = ct.build_create_payload(spec)["fields"]
        headings = [
            n["content"][0]["text"]
            for n in walk(fields["description"]) if n["type"] == "heading"
        ]
        self.assertEqual(headings, ["What", "Requirements"])
        comment = ct.build_comment_payload(spec["comment"])["body"]
        self.assertEqual(comment["type"], "doc")
        self.assertEqual(comment["content"][0]["content"][0]["text"], "Agent Dump Section")



class Payloads(unittest.TestCase):
    def test_link_direction(self):
        blocks = ct.build_link_payload("DP-9", {"type": "blocks", "key": "DP-1"})
        self.assertEqual(blocks["type"]["name"], "Blocks")
        self.assertEqual(blocks["inwardIssue"]["key"], "DP-9")  # blocker
        self.assertEqual(blocks["outwardIssue"]["key"], "DP-1")  # blocked

        blocked = ct.build_link_payload("DP-9", {"type": "blocked-by", "key": "DP-1"})
        self.assertEqual(blocked["inwardIssue"]["key"], "DP-1")
        self.assertEqual(blocked["outwardIssue"]["key"], "DP-9")

        relates = ct.build_link_payload("DP-9", {"type": "relates", "key": "DP-1"})
        self.assertEqual(relates["type"]["name"], "Relates")

    def test_create_payload_fields(self):
        spec = ct.normalize_spec(valid_spec(epic="DP-3013", labels=["earn"], points=5))
        fields = ct.build_create_payload(spec)["fields"]
        self.assertEqual(fields["project"], {"key": "DP"})
        self.assertEqual(fields["issuetype"], {"name": "Story"})
        self.assertEqual(fields["priority"], {"name": "Medium"})
        self.assertEqual(fields["labels"], ["earn"])
        self.assertEqual(fields["parent"], {"key": "DP-3013"})
        self.assertEqual(fields[ct.POINTS_FIELD], 5)
        self.assertEqual(fields[ct.TEAM_FIELD], "d4ad0f64-79d2-4c1b-bce8-d8f9e215ef8a")
        self.assertEqual(fields["description"]["type"], "doc")

    def test_no_epic_means_no_parent(self):
        fields = ct.build_create_payload(ct.normalize_spec(valid_spec()))["fields"]
        self.assertNotIn("parent", fields)


class Posting(unittest.TestCase):
    """create_ticket and main with Jira stubbed out; no network."""

    def spec(self, **overrides):
        return ct.normalize_spec(valid_spec(
            description=TWO_HALVES, agent_dump="comment", epic="DP-3013",
            links=[{"type": "relates", "key": "DP-1"}], **overrides,
        ))

    def fake_jira(self, calls, fail_comment=False):
        def call(server, auth, path, body):
            calls.append(path)
            if fail_comment and path.endswith("/comment"):
                raise ct.JiraError(400, "bad comment")
            return {"key": "DP-9"} if path == "/rest/api/3/issue" else {}
        return call

    def test_comment_is_posted_after_create_and_before_links(self):
        calls = []
        with mock.patch.object(ct, "jira_call", self.fake_jira(calls)):
            result = ct.create_ticket(self.spec(), "https://j", "auth")
        self.assertEqual(calls, [
            "/rest/api/3/issue",
            "/rest/api/3/issue/DP-9/comment",
            "/rest/api/3/issueLink",
        ])
        self.assertEqual(result["comment"], {"ok": True})

    def test_no_comment_call_in_description_mode(self):
        calls = []
        spec = ct.normalize_spec(valid_spec(description=TWO_HALVES))
        with mock.patch.object(ct, "jira_call", self.fake_jira(calls)):
            result = ct.create_ticket(spec, "https://j", "auth")
        self.assertEqual(calls, ["/rest/api/3/issue"])
        self.assertIsNone(result["comment"])

    def test_failed_comment_keeps_the_key_still_links_and_exits_3(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(valid_spec(
                description=TWO_HALVES, agent_dump="comment", epic=None,
                links=[{"type": "relates", "key": "DP-1"}],
            )))
            out = io.StringIO()
            with mock.patch.object(ct, "jira_call", self.fake_jira(calls, fail_comment=True)), \
                    mock.patch.object(ct, "load_credentials", return_value=("https://j", "a")), \
                    contextlib.redirect_stdout(out):
                code = ct.main([str(path)])
        result = json.loads(out.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(result["key"], "DP-9")
        self.assertFalse(result["comment"]["ok"])
        self.assertIn("bad comment", result["comment"]["error"])
        self.assertTrue(result["links"][0]["ok"])
        self.assertEqual(calls.count("/rest/api/3/issue"), 1)


class Cli(unittest.TestCase):
    def run_comment_only(self, body, *extra, key="DP-5"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(body)
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--comment-only", key, *extra],
                capture_output=True, text=True,
            )

    def test_comment_only_dry_run_prints_the_dump_half(self):
        result = self.run_comment_only(TWO_HALVES, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["issue"], "DP-5")
        headings = [n["content"][0]["text"] for n in walk(plan["comment"]["body"])
                    if n["type"] == "heading"]
        self.assertEqual(headings, ["Agent Dump Section", "Background", "Non-Goals"])

    def test_comment_only_rejects_bad_key_and_missing_heading(self):
        bad_key = self.run_comment_only(TWO_HALVES, "--dry-run", key="dp5")
        self.assertEqual(bad_key.returncode, 1)
        self.assertIn("not an issue key", bad_key.stderr)
        no_dump = self.run_comment_only("# What\n\nx", "--dry-run")
        self.assertEqual(no_dump.returncode, 1)
        self.assertIn("no '# Agent Dump Section' heading", no_dump.stderr)

    def test_dry_run_with_comment_mode_prints_both_requests(self):
        result = self.run_cli(
            valid_spec(description=TWO_HALVES, agent_dump="comment"), "--dry-run"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["comment"]["body"]["type"], "doc")
        kinds = [b["type"] for b in plan["create"]["fields"]["description"]["content"]]
        self.assertNotIn("rule", kinds)

    def run_cli(self, spec, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec))
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path), *extra],
                capture_output=True, text=True,
            )

    def test_dry_run_prints_requests_without_credentials(self):
        spec = valid_spec(epic="DP-3013", links=[{"type": "blocked-by", "key": "DP-2321"}])
        result = self.run_cli(spec, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["create"]["fields"]["parent"], {"key": "DP-3013"})
        self.assertEqual(plan["links"][0]["inwardIssue"]["key"], "DP-2321")
        self.assertEqual(plan["links"][0]["outwardIssue"]["key"], "NEW-0")

    def test_bad_spec_exits_1_with_every_problem(self):
        result = self.run_cli({"summary": "x", "description": "y"}, "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ask the user for the story points", result.stderr)
        self.assertIn("epic is required", result.stderr)


if __name__ == "__main__":
    unittest.main()

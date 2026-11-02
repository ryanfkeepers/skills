import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import greencache  # noqa: E402

COMMANDS = {"compile": ["go build ./..."], "codegen": [],
            "test": ["go test -short ./..."], "lint": ["golangci-lint run"]}


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class GreenCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        self.cache = os.path.join(self.tmp.name, "cache")
        os.makedirs(os.path.join(self.repo, ".jj"))
        write(self.repo, "go.mod", "module x\n")
        write(self.repo, "Makefile", "build:\n\tgo build\ntest-unit:\n\tgo test\n.PHONY: build\nX := 1\n")
        self.real_aliases = greencache.shell_aliases
        greencache.shell_aliases = lambda d: []

    def tearDown(self):
        greencache.shell_aliases = self.real_aliases
        self.tmp.cleanup()

    def get(self, directory=None):
        return greencache.cmd_get(directory or self.repo, self.cache)

    def test_probe_lists_targets_and_matches(self):
        found, _ = greencache.probe(self.repo)
        self.assertEqual(found["targets"]["make"], ["build", "test-unit"])
        self.assertEqual(found["matches"], {"compile": ["make build"], "test": ["make test-unit"]})
        self.assertFalse(found["go_generate"])

    def test_miss_then_hit(self):
        miss = self.get()
        self.assertEqual((miss["hit"], miss["reason"]), (False, "none"))
        self.assertIn("Makefile", miss["probe"]["files"])
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        hit = self.get()
        self.assertTrue(hit["hit"])
        self.assertEqual(hit["commands"], COMMANDS)

    def test_editing_a_decisive_file_makes_it_stale(self):
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        write(self.repo, "Makefile", "build:\n\tgo build -tags x\n")
        self.assertEqual(self.get()["reason"], "stale")

    def test_adding_a_lint_config_makes_it_stale(self):
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        write(self.repo, ".golangci.yml", "linters: {}\n")
        self.assertFalse(self.get()["hit"])

    def test_new_go_generate_directive_makes_it_stale(self):
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        write(self.repo, "pkg/a.go", "package pkg\n//go:generate mockgen\n")
        self.assertFalse(self.get()["hit"])

    def test_unrelated_source_edit_keeps_the_hit(self):
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        write(self.repo, "pkg/a.go", "package pkg\nfunc A() {}\n")
        self.assertTrue(self.get()["hit"])

    def test_subdir_uses_root_files_and_its_own_entry(self):
        sub = os.path.join(self.repo, "services", "svc")
        write(sub, "go.mod", "module svc\n")
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        miss = self.get(sub)
        self.assertFalse(miss["hit"])
        self.assertIn(os.path.join("..", "..", "Makefile"), miss["probe"]["files"])
        greencache.cmd_put(sub, COMMANDS, self.cache)
        write(self.repo, "Makefile", "lint:\n")
        self.assertFalse(self.get(sub)["hit"])

    def test_put_requires_compile_test_lint(self):
        with self.assertRaises(ValueError):
            greencache.cmd_put(self.repo, {"compile": ["x"], "test": ["y"]}, self.cache)

    def test_forget(self):
        greencache.cmd_put(self.repo, COMMANDS, self.cache)
        self.assertEqual(greencache.cmd_forget(self.repo, self.cache)["status"], "forgotten")
        self.assertEqual(self.get()["reason"], "none")

    def test_case_insensitive_duplicates_collapse(self):
        other = os.path.join(self.repo, "makefile")
        if os.path.exists(other):  # case-insensitive filesystem
            files = greencache.present_files(self.repo)
            self.assertEqual(sum(f.lower() == "makefile" for f in files), 1)


if __name__ == "__main__":
    unittest.main()

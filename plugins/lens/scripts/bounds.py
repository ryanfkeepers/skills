"""Which files a build lens may change, judged from the plan's targets.

The scope is by directory. `implement` ("code") may change non-test files in
a directory that holds a plan target, plus dependency manifests. `unit-test`
("tests") may change test files in those directories or in test-support
directories. A test task's own target files count as plan files for
`implement`, since the tests are its deliverable. lensctl never restores a
file on its own: it asks the user what to do with the files outside the scope.
"""
import fnmatch
import json
import os

TEST_PATTERNS = ("*_test.go", "test_*.py", "*_test.py", "*.test.*", "*.spec.*")
TEST_DIRS = ("testdata/", "tests/", "__tests__/", "mocks/", "fakes/")
MANIFESTS = ("go.mod", "go.sum")


def is_test(path):
    base = os.path.basename(path)
    return any(fnmatch.fnmatch(base, p) for p in TEST_PATTERNS) or any(d in path for d in TEST_DIRS)


def plan_scope(run):
    """The plan's target directories and test-task files, or None when there is no tasks.json."""
    path = os.path.join(run, "tasks.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        tasks = json.load(f).get("tasks", [])
    files, tests = set(), set()
    for t in tasks:
        for target in t.get("target", []):
            name = target.split("#", 1)[0]
            files.add(name)
            if t.get("kind") == "test":
                tests.add(name)
    return {"dirs": {os.path.dirname(f) for f in files}, "test_files": tests}


def out_of_bounds(role, files, scope):
    """The changed files outside the scope for this role, in the order given."""
    bad = []
    for f in files:
        here = os.path.dirname(f)
        if role == "code":
            ok = f in scope["test_files"] or os.path.basename(f) in MANIFESTS \
                or (not is_test(f) and here in scope["dirs"])
        else:
            ok = is_test(f) and (here in scope["dirs"] or any(d in f for d in TEST_DIRS))
        if not ok:
            bad.append(f)
    return bad

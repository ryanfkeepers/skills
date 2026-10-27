#!/usr/bin/env python3
"""Preflight for service-quality-analysis.

  preflight.py check <repo> [<repo> ...]   verify each repo has a usable graphify graph (exit 2 if any does not)
  preflight.py units <repo>                list candidate subpart roots (directories holding a build manifest)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

MANIFESTS = {"go.mod", "package.json", "pyproject.toml", "setup.py", "pom.xml", "build.gradle", "build.gradle.kts",
             "Cargo.toml", "Gemfile", "composer.json"}
MANIFEST_SUFFIXES = (".csproj", ".sln")
SKIP_DIRS = {".git", ".jj", "node_modules", "vendor", "graphify-out", "__pycache__", ".venv", "dist", "build"}
IMPORT_RELATIONS = {"imports", "imports_from"}

SETUP_GUIDE = """\
{repo} has no usable graphify graph ({why}).

This analysis reads each package's import graph from graphify-out/graph.json, so it cannot continue without it.
To set it up:
  1. cd {repo}
  2. In Claude Code, run:  /graphify .          (add --no-viz to skip the HTML; see ~/.claude/skills/graphify/SKILL.md)
  3. Confirm {repo}/graphify-out/graph.json now exists, then run /service-quality-analysis again.
For a comparison repo you have not cloned: /graphify https://github.com/<owner>/<repo> clones and builds it; note
where the graph lands, since the analysis needs the repo checkout and its graphify-out/ together.
"""


def repo_root(path):
    p = Path(path).expanduser().resolve()
    for d in [p, *p.parents]:
        if (d / ".jj").exists() or (d / ".git").exists():
            return d
    return p


def head_commit(repo):
    for cmd in (["jj", "--ignore-working-copy", "--no-pager", "log", "--no-graph", "-r", "@-", "-T", "commit_id"],
                ["git", "rev-parse", "HEAD"]):
        try:
            return subprocess.run(cmd, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def check(repo_arg):
    repo = repo_root(repo_arg)
    graph = repo / "graphify-out" / "graph.json"
    if not graph.is_file() or graph.stat().st_size == 0:
        return False, SETUP_GUIDE.format(repo=repo, why="graphify-out/graph.json is missing")
    try:
        raw = json.loads(graph.read_text())
        nodes, links = raw["nodes"], raw.get("links") or raw.get("edges") or []
    except (json.JSONDecodeError, KeyError) as ex:
        return False, SETUP_GUIDE.format(repo=repo, why=f"graph.json does not parse: {ex}")
    code_files = {n["source_file"] for n in nodes if n.get("file_type") == "code" and n.get("source_file")}
    imports = sum(1 for e in links if e.get("relation") in IMPORT_RELATIONS)
    if not code_files or not imports:
        return False, SETUP_GUIDE.format(repo=repo, why=f"it holds {len(code_files)} code files and {imports} import edges; rebuild it so code is extracted")
    sample = sorted(code_files)[:300]
    found = sum(1 for f in sample if (repo / f).is_file())
    lines = [f"OK  {repo}: {len(code_files)} code files, {imports} import edges"]
    if found < 0.9 * len(sample):
        return False, SETUP_GUIDE.format(repo=repo, why=f"only {found} of {len(sample)} sampled graph paths exist under the repo; run /graphify from the repo root")
    built, head = raw.get("built_at_commit"), head_commit(repo)
    if built and head and not (head.startswith(str(built)) or str(built).startswith(head[:12])):
        lines.append(f"    warning: graph was built at {str(built)[:12]} but the checkout is at {head[:12]}; "
                     "run /graphify . --update if the code has changed since")
    return True, "\n".join(lines)


def units(repo_arg):
    repo = repo_root(repo_arg)
    dirs = []
    for dirpath, dirnames, filenames in os.walk(repo):
        rel = os.path.relpath(dirpath, repo)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and depth < 4]
        if rel != "." and (MANIFESTS & set(filenames) or any(f.endswith(MANIFEST_SUFFIXES) for f in filenames)):
            dirs.append(rel)
    groups = {}
    for d in sorted(dirs):
        parent = os.path.dirname(d) or "."
        groups.setdefault(parent, []).append(d)
    return {"repo": str(repo), "manifest_dirs": sorted(dirs),
            "groups": {k: v for k, v in groups.items() if len(v) >= 2}}


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("check", "units"):
        sys.exit(__doc__)
    if sys.argv[1] == "units":
        print(json.dumps(units(sys.argv[2]), indent=2))
        return
    bad = False
    for r in sys.argv[2:]:
        ok, msg = check(r)
        print(msg)
        bad |= not ok
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    main()

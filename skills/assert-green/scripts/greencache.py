"""Per-directory cache of the commands assert-green discovered for a repo.

`get` returns the cached compile/codegen/test/lint commands while the files
that decide them are unchanged; on a miss it returns the `probe` result so
discovery needs no further exploring. `put` records commands after a green
run. Entries live in ~/.claude/cache/assert-green/, outside every repo.

All output is compact JSON.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

PHASES = ("compile", "codegen", "test", "lint")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "cache", "assert-green")

# Files whose content decides which commands each phase runs. Lockfiles are
# left out on purpose: they churn without changing the commands.
FINGERPRINT_FILES = (
    "Makefile", "makefile", "GNUmakefile", "Justfile", "justfile",
    "Taskfile.yml", "Taskfile.yaml", "go.mod", "go.work", "package.json",
    "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg", "Gemfile",
    "buf.gen.yaml", "buf.work.yaml", "buf.yaml", "scripts/generate.sh",
    ".golangci.yml", ".golangci.yaml", ".golangci.toml", ".tint.toml",
    "ruff.toml", ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.cjs",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js",
    ".rubocop.yml",
)
MAKEFILES = ("Makefile", "makefile", "GNUmakefile")
JUSTFILES = ("Justfile", "justfile")
TASKFILES = ("Taskfile.yml", "Taskfile.yaml")
MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_./-]*)\s*:(?!=)", re.M)
PHASE_TARGETS = {
    "compile": ("build",),
    "codegen": ("generate", "gen", "codegen", "update"),
    "test": ("test-unit", "unit-test", "unit-tests", "test"),
    "lint": ("lint",),
}
SHELL_ALIASES = ("gt", "lint")
SKIP_DIRS = {".git", ".jj", "node_modules", "vendor", "dist", "build", ".venv"}


# ---- locating files ------------------------------------------------------


def repo_root(start):
    cur = start
    while True:
        if any(os.path.exists(os.path.join(cur, m)) for m in (".jj", ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return start
        cur = parent


def search_dirs(directory):
    """The working dir, then the repo root when it differs (monorepo subdirs)."""
    root = repo_root(directory)
    return [directory] if root == directory else [directory, root]


def present_files(directory):
    """Relative paths (from directory) of every fingerprint file that exists."""
    found, seen = [], set()
    for d in search_dirs(directory):
        names = list(FINGERPRINT_FILES) + sorted(n for n in safe_listdir(d) if n.endswith(".mk"))
        for name in names:
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            # Case-insensitive filesystems answer for both Makefile and makefile.
            inode = (os.stat(path).st_dev, os.stat(path).st_ino)
            if inode in seen:
                continue
            seen.add(inode)
            found.append(os.path.relpath(path, directory))
    return found


def safe_listdir(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def has_go_generate(directory):
    """True if any .go file under directory carries a //go:generate directive."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [n for n in dirnames if n not in SKIP_DIRS and not n.startswith(".")]
        for name in filenames:
            if not name.endswith(".go"):
                continue
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8", errors="replace") as f:
                    if "//go:generate" in f.read():
                        return True
            except OSError:
                continue
    return False


def fingerprint(directory, files, go_generate):
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        with open(os.path.join(directory, rel), "rb") as f:
            h.update(hashlib.sha256(f.read()).digest())
    h.update(b"go:generate=" + str(go_generate).encode())
    return h.hexdigest()


# ---- probe ---------------------------------------------------------------


def run_quiet(argv, cwd):
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def make_targets(directory, files):
    targets = set()
    for rel in files:
        if os.path.basename(rel) in MAKEFILES or rel.endswith(".mk"):
            with open(os.path.join(directory, rel), encoding="utf-8", errors="replace") as f:
                targets.update(t for t in MAKE_TARGET.findall(f.read())
                               if not t.startswith("."))
    return sorted(targets)


def runner_targets(directory, files):
    """Targets per task runner present: make (parsed), just and task (listed)."""
    names = {os.path.basename(f) for f in files}
    out = {}
    if names & set(MAKEFILES):
        out["make"] = make_targets(directory, files)
    if names & set(JUSTFILES) and shutil.which("just"):
        text = run_quiet(["just", "--summary"], directory)
        out["just"] = sorted(text.split()) if text else []
    if names & set(TASKFILES) and shutil.which("task"):
        text = run_quiet(["task", "--list-all"], directory) or ""
        out["task"] = sorted(re.findall(r"^\* ([^:\s]+):", text, re.M))
    return out


def phase_matches(targets):
    """Per phase, the runner targets matching assert-green's preferred names."""
    out = {}
    for phase, wanted in PHASE_TARGETS.items():
        hits = [f"{runner} {t}" for runner, ts in targets.items() for t in wanted if t in ts]
        if hits:
            out[phase] = hits
    return out


def shell_aliases(directory):
    """Which of the user's fish functions (gt, lint) exist."""
    if not shutil.which("fish"):
        return []
    return [name for name in SHELL_ALIASES
            if run_quiet(["fish", "-c", f"functions -q {name}"], directory) is not None]


def probe(directory):
    files = present_files(directory)
    is_go = any(os.path.basename(f) in ("go.mod", "go.work") for f in files)
    go_generate = is_go and has_go_generate(directory)
    targets = runner_targets(directory, files)
    return {
        "dir": directory,
        "files": files,
        "go_generate": go_generate,
        "targets": targets,
        "matches": phase_matches(targets),
        "aliases": shell_aliases(directory),
    }, fingerprint(directory, files, go_generate)


# ---- cache ---------------------------------------------------------------


def cache_path(directory, cache_dir=CACHE_DIR):
    key = hashlib.sha256(directory.encode()).hexdigest()[:24]
    return os.path.join(cache_dir, f"{key}.json")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cmd_get(directory, cache_dir=CACHE_DIR):
    found, fp = probe(directory)
    entry = load(cache_path(directory, cache_dir))
    if entry and entry.get("dir") == directory and entry.get("fingerprint") == fp:
        return {"hit": True, "dir": directory, "commands": entry["commands"],
                "updated": entry.get("updated")}
    return {"hit": False, "reason": "stale" if entry else "none", "probe": found}


def cmd_put(directory, commands, cache_dir=CACHE_DIR):
    missing = [p for p in PHASES if p != "codegen" and not commands.get(p)]
    if missing:
        raise ValueError(f"missing commands for: {', '.join(missing)}")
    _, fp = probe(directory)
    entry = {"dir": directory, "fingerprint": fp,
             "commands": {p: commands.get(p, []) for p in PHASES},
             "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(cache_dir, exist_ok=True)
    path = cache_path(directory, cache_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1)
    os.replace(tmp, path)
    return {"status": "stored", "dir": directory, "commands": entry["commands"]}


def cmd_forget(directory, cache_dir=CACHE_DIR):
    try:
        os.remove(cache_path(directory, cache_dir))
        return {"status": "forgotten", "dir": directory}
    except FileNotFoundError:
        return {"status": "absent", "dir": directory}


# ---- cli -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="greencache.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "get", "put", "forget"):
        s = sub.add_parser(name)
        s.add_argument("--dir", default=os.getcwd())
        if name == "put":
            for phase in PHASES:
                s.add_argument(f"--{phase}", action="append", default=[],
                               help="repeat for several commands, in run order")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    directory = os.path.realpath(a.dir)
    try:
        if a.cmd == "probe":
            out = probe(directory)[0]
        elif a.cmd == "get":
            out = cmd_get(directory)
        elif a.cmd == "put":
            out = cmd_put(directory, {p: getattr(a, p) for p in PHASES})
        else:
            out = cmd_forget(directory)
    except (ValueError, OSError) as err:
        print(json.dumps({"status": "error", "message": str(err)}))
        return 1
    print(json.dumps(out, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Create a Jira story with team, story points, parent epic, labels and links.

The agent supplies a small JSON spec; this script does everything else.

    create_ticket.py SPEC.json [--dry-run]      (SPEC.json may be "-" for stdin)
    create_ticket.py BODY.md --comment-only DP-123 [--dry-run]

Spec keys (any other key is rejected):

  summary           required  ticket title
  description       one of    markdown body, inline
  description_file  one of    path to a markdown body
  points            required  story points, a number above 0
  epic              required  parent epic key, or null once the user has
                              confirmed there is no epic
  agent_dump        optional  "description" (default) keeps the whole body in
                              the description; "comment" posts everything from
                              the "# Agent Dump Section" heading down as a
                              comment on the new ticket
  priority          optional  default Medium
  labels            optional  subset of earn, ops, tech-debt
  team              optional  default "UE - Data Pipelines"
  project           optional  default DP
  type              optional  default Story
  links             optional  [{"type": "blocks|blocked-by|relates",
                                "key": "DP-123"}]

--comment-only KEY posts the Agent Dump half of BODY.md as a comment on an
existing ticket. Use it to retry a comment that failed after the ticket was
created; rerunning the spec would create a second ticket.

Credentials: JIRA_EMAIL and JIRA_API_TOKEN (JIRA_SERVER optional), else the
jira-cli config (~/.config/.jira/.config.yml) plus the macOS keychain item
"jira-cli". --dry-run needs none and sends nothing.

Exit codes: 0 done; 1 bad spec or missing credentials; 2 Jira refused the
ticket (or, with --comment-only, the comment); 3 ticket created but the
comment or at least one link failed (output has the key).
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_SERVER = "https://veeam-vdc.atlassian.net"
TEAM_FIELD = "customfield_10001"
POINTS_FIELD = "customfield_10016"
DEFAULT_TEAM = "UE - Data Pipelines"
TEAMS = {DEFAULT_TEAM: "d4ad0f64-79d2-4c1b-bce8-d8f9e215ef8a"}
ALLOWED_LABELS = ("earn", "ops", "tech-debt")
PRIORITIES = ("Urgent", "Highest", "High", "Medium", "Low", "Lowest")
SPEC_KEYS = {
    "summary", "description", "description_file", "points", "epic",
    "agent_dump", "priority", "labels", "team", "project", "type", "links",
}
AGENT_DUMP_MODES = ("description", "comment")
AGENT_DUMP_HEADING = re.compile(r"^# Agent Dump Section[ \t]*$", re.M)
RULE_LINE = re.compile(r"^(<hr\s*/?>|-{3,})$")
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")

# kind -> (Jira link type name, whether the new ticket is the blocking /
# inward side). Jira stores a link as inwardIssue -> outwardIssue, where the
# inward issue "blocks" the outward one.
LINK_KINDS = {
    "blocks": ("Blocks", True),
    "blocked-by": ("Blocks", False),
    "relates": ("Relates", True),
}


class UsageError(Exception):
    """The spec or the environment is unusable; carries every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class JiraError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


# ---------------------------------------------------------------- markdown


INLINE = re.compile(
    r"`([^`]+)`"
    r"|\*\*(.+?)\*\*"
    r"|\[([^\]]+)\]\((https?://[^)\s]+)\)"
    r"|(https?://[^\s<>\]]+)"
)
URL_TRAILING = ".,;:!?)"
FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\w+)?\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
RULE = re.compile(r"^\s*(<hr\s*/?>|-{3,}|\*{3,}|_{3,})\s*$", re.I)
ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
STRONG = {"type": "strong"}
CODE = {"type": "code"}


def _text(text: str, marks: tuple = ()) -> dict:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = [dict(m) for m in marks]
    return node


def _plain(text: str, marks: tuple) -> list[dict]:
    return [_text(text, marks)] if text else []


def inline(text: str, marks: tuple = ()) -> list[dict]:
    """Convert inline markdown (code, bold, links, bare URLs) to ADF nodes.

    ADF forbids combining the code mark with other formatting, so code runs
    keep only their own mark even inside bold text.
    """
    nodes: list[dict] = []
    pos = 0
    for m in INLINE.finditer(text):
        nodes += _plain(text[pos:m.start()], marks)
        code, bold, label, href, bare = m.groups()
        if code is not None:
            nodes.append(_text(code, (CODE,)))
        elif bold is not None:
            nodes += inline(bold, (*marks, STRONG))
        elif label is not None:
            nodes.append(_text(label, (*marks, _link(href))))
        else:
            url = bare.rstrip(URL_TRAILING)
            nodes.append(_text(url, (*marks, _link(url))))
            nodes += _plain(bare[len(url):], marks)
        pos = m.end()
    return nodes + _plain(text[pos:], marks)


def _link(href: str) -> dict:
    return {"type": "link", "attrs": {"href": href}}


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": inline(text)}


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _table(rows: list[list[str]]) -> dict:
    width = len(rows[0])

    def row(cells: list[str], kind: str) -> dict:
        cells = (cells + [""] * width)[:width]
        return {
            "type": "tableRow",
            "content": [{"type": kind, "content": [_paragraph(c)]} for c in cells],
        }

    content = [row(rows[0], "tableHeader")] + [row(r, "tableCell") for r in rows[1:]]
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": content,
    }


def _block_kind(lines: list[str], i: int) -> str | None:
    line = lines[i]
    if FENCE.match(line):
        return "fence"
    if RULE.match(line):
        return "rule"
    if HEADING.match(line):
        return "heading"
    if (line.lstrip().startswith("|") and i + 1 < len(lines)
            and "|" in lines[i + 1] and TABLE_SEP.match(lines[i + 1])):
        return "table"
    if ITEM.match(line):
        return "list"
    return None


def _read_fence(lines: list[str], i: int) -> tuple[dict, int]:
    opener = FENCE.match(lines[i])
    marker, lang = opener.group(1), opener.group(2)
    closer = re.compile(re.escape(marker[0]) + "{%d,}" % len(marker))
    i += 1
    body: list[str] = []
    while i < len(lines) and not closer.fullmatch(lines[i].strip()):
        body.append(lines[i])
        i += 1
    code = "\n".join(body)
    node: dict[str, Any] = {"type": "codeBlock", "content": []}
    if lang:
        node["attrs"] = {"language": lang}
    if code:
        node["content"] = [_text(code)]
    return node, i + 1


def _read_table(lines: list[str], i: int) -> tuple[dict, int]:
    rows = [_split_row(lines[i])]
    i += 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        rows.append(_split_row(lines[i]))
        i += 1
    return _table(rows), i


def _read_list(lines: list[str], i: int) -> tuple[dict, int]:
    ordered = lines[i].strip()[0].isdigit()
    items: list[str] = []
    while i < len(lines):
        m = ITEM.match(lines[i])
        if m:
            items.append(m.group(3).strip())
        elif lines[i].strip() and lines[i][0] in " \t":
            items[-1] += " " + lines[i].strip()
        else:
            break
        i += 1
    node = {
        "type": "orderedList" if ordered else "bulletList",
        "content": [
            {"type": "listItem", "content": [_paragraph(t)]} for t in items
        ],
    }
    return node, i


def md_to_adf(markdown: str) -> dict:
    """Convert the markdown subset the ticket template uses to ADF.

    Supports headings, paragraphs, flat bullet and numbered lists, pipe
    tables, fenced code, horizontal rules (--- or <hr>) and the inline forms
    handled by inline(). Consecutive prose lines join into one paragraph.
    """
    lines = markdown.splitlines()
    blocks: list[dict] = []
    prose: list[str] = []

    def flush() -> None:
        if prose:
            blocks.append(_paragraph(" ".join(s.strip() for s in prose)))
            prose.clear()

    i = 0
    while i < len(lines):
        kind = _block_kind(lines, i)
        if kind is None:
            if lines[i].strip():
                prose.append(lines[i])
            else:
                flush()
            i += 1
            continue
        flush()
        if kind == "fence":
            node, i = _read_fence(lines, i)
        elif kind == "table":
            node, i = _read_table(lines, i)
        elif kind == "list":
            node, i = _read_list(lines, i)
        elif kind == "rule":
            node, i = {"type": "rule"}, i + 1
        else:
            m = HEADING.match(lines[i])
            node = {
                "type": "heading",
                "attrs": {"level": len(m.group(1))},
                "content": inline(m.group(2)),
            }
            i += 1
        blocks.append(node)
    flush()
    return {"version": 1, "type": "doc", "content": blocks}


# -------------------------------------------------------------------- spec


def _summary(spec: dict, problems: list[str]) -> str | None:
    value = spec.get("summary")
    if not isinstance(value, str) or not value.strip():
        problems.append("summary is required")
        return None
    if len(value.strip()) > 255:
        problems.append("summary is longer than Jira's 255 characters")
    return value.strip()


def _description(spec: dict, problems: list[str]) -> str | None:
    inline_body, path = spec.get("description"), spec.get("description_file")
    if (inline_body is None) == (path is None):
        problems.append("give exactly one of description or description_file")
        return None
    if inline_body is not None:
        body = inline_body if isinstance(inline_body, str) else ""
    else:
        try:
            body = Path(path).read_text()
        except (OSError, TypeError) as err:
            problems.append(f"cannot read description_file: {err}")
            return None
    if not body.strip():
        problems.append("the description is empty")
        return None
    return body


def split_agent_dump(body: str) -> tuple[str, str | None]:
    """Split a body at its "# Agent Dump Section" heading.

    Returns (top, dump). The rule that separates the halves is dropped from
    the top. dump is None when the heading is absent.
    """
    match = AGENT_DUMP_HEADING.search(body)
    if not match:
        return body, None
    lines = body[: match.start()].rstrip().splitlines()
    while lines and (not lines[-1].strip() or RULE_LINE.match(lines[-1].strip())):
        lines.pop()
    return "\n".join(lines).strip(), body[match.start():].strip()


def _agent_dump(
    spec: dict, body: str | None, problems: list[str]
) -> tuple[str | None, str | None]:
    """Return (description, comment) for the chosen agent_dump placement."""
    mode = spec.get("agent_dump", "description")
    if mode not in AGENT_DUMP_MODES:
        problems.append(f"agent_dump {mode!r} is not one of {', '.join(AGENT_DUMP_MODES)}")
        return body, None
    if mode == "description" or body is None:
        return body, None
    top, dump = split_agent_dump(body)
    if dump is None:
        problems.append(
            "agent_dump is comment but the body has no '# Agent Dump Section' heading"
        )
    elif not top:
        problems.append("nothing is left for the description once the agent dump moves out")
    else:
        return top, dump
    return body, None


def _points(spec: dict, problems: list[str]) -> int | float | None:
    value = spec.get("points")
    if value is None:
        problems.append("points is required: ask the user for the story points")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        problems.append("points must be a number above 0")
        return None
    return int(value) if float(value).is_integer() else value


def _epic(spec: dict, problems: list[str]) -> str | None:
    if "epic" not in spec:
        problems.append(
            "epic is required: give the parent epic key, or null once the "
            "user has confirmed there is no epic"
        )
        return None
    value = spec["epic"]
    if value is not None and not (isinstance(value, str) and ISSUE_KEY.match(value)):
        problems.append(f"epic {value!r} is not an issue key like DP-123")
    return value


def _priority(spec: dict, problems: list[str]) -> str | None:
    value = spec.get("priority", "Medium")
    for name in PRIORITIES:
        if isinstance(value, str) and value.lower() == name.lower():
            return name
    problems.append(f"priority {value!r} is not one of {', '.join(PRIORITIES)}")
    return None


def _labels(spec: dict, problems: list[str]) -> list[str]:
    value = spec.get("labels", [])
    if not isinstance(value, list):
        problems.append("labels must be a list")
        return []
    bad = [v for v in value if v not in ALLOWED_LABELS]
    if bad:
        problems.append(
            f"labels {bad} are not allowed; use {', '.join(ALLOWED_LABELS)}"
        )
    return list(dict.fromkeys(v for v in value if v in ALLOWED_LABELS))


def _team(spec: dict, problems: list[str]) -> str | None:
    value = spec.get("team", DEFAULT_TEAM)
    if not isinstance(value, str) or value not in TEAMS:
        problems.append(f"team {value!r} is not known; add it to TEAMS")
        return None
    return value


def _links(spec: dict, problems: list[str]) -> list[dict]:
    value = spec.get("links", [])
    if not isinstance(value, list):
        problems.append("links must be a list")
        return []
    links: list[dict] = []
    for item in value:
        ok = (
            isinstance(item, dict)
            and set(item) == {"type", "key"}
            and item["type"] in LINK_KINDS
            and isinstance(item["key"], str)
            and ISSUE_KEY.match(item["key"])
        )
        if not ok:
            problems.append(
                f"bad link {item!r}: want {{type: {'|'.join(LINK_KINDS)}, key: DP-123}}"
            )
        elif item not in links:
            links.append(item)
    return links


def normalize_spec(spec: Any) -> dict[str, Any]:
    """Validate a spec, collecting every problem before failing."""
    if not isinstance(spec, dict):
        raise UsageError(["the spec must be a JSON object"])
    problems: list[str] = []
    unknown = sorted(set(spec) - SPEC_KEYS)
    if unknown:
        problems.append(f"unknown keys: {', '.join(unknown)}")
    team = _team(spec, problems)
    summary = _summary(spec, problems)
    description, comment = _agent_dump(spec, _description(spec, problems), problems)
    out = {
        "summary": summary,
        "description": description,
        "comment": comment,
        "points": _points(spec, problems),
        "epic": _epic(spec, problems),
        "priority": _priority(spec, problems),
        "labels": _labels(spec, problems),
        "team": team,
        "team_id": TEAMS.get(team),
        "project": spec.get("project", "DP"),
        "type": spec.get("type", "Story"),
        "links": _links(spec, problems),
    }
    if problems:
        raise UsageError(problems)
    return out


def read_source(source: str, what: str) -> str:
    try:
        return sys.stdin.read() if source == "-" else Path(source).read_text()
    except OSError as err:
        raise UsageError([f"cannot read the {what}: {err}"]) from err


def load_spec(source: str) -> Any:
    raw = read_source(source, "spec")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        raise UsageError([f"cannot read the spec: {err}"]) from err


# ----------------------------------------------------------------- payloads


def build_create_payload(spec: dict) -> dict:
    fields: dict[str, Any] = {
        "project": {"key": spec["project"]},
        "issuetype": {"name": spec["type"]},
        "summary": spec["summary"],
        "description": md_to_adf(spec["description"]),
        "priority": {"name": spec["priority"]},
        "labels": spec["labels"],
        TEAM_FIELD: spec["team_id"],
        POINTS_FIELD: spec["points"],
    }
    if spec["epic"]:
        fields["parent"] = {"key": spec["epic"]}
    return {"fields": fields}


def build_comment_payload(markdown: str) -> dict:
    return {"body": md_to_adf(markdown)}


def build_link_payload(new_key: str, link: dict) -> dict:
    type_name, new_is_inward = LINK_KINDS[link["type"]]
    inward, outward = (new_key, link["key"]) if new_is_inward else (link["key"], new_key)
    return {
        "type": {"name": type_name},
        "inwardIssue": {"key": inward},
        "outwardIssue": {"key": outward},
    }


# --------------------------------------------------------------------- jira


def _jira_cli_credentials() -> tuple[str, str, str] | None:
    config = Path.home() / ".config" / ".jira" / ".config.yml"
    if not config.is_file():
        return None
    text = config.read_text()
    login = re.search(r"^login:\s*(\S+)", text, re.M)
    server = re.search(r"^server:\s*(\S+)", text, re.M)
    if not login:
        return None
    try:
        token = subprocess.run(
            ["security", "find-generic-password", "-s", "jira-cli", "-w"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not token:
        return None
    return (server.group(1) if server else DEFAULT_SERVER), login.group(1), token


def load_credentials() -> tuple[str, str]:
    """Return (server, basic-auth header value)."""
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    server = os.environ.get("JIRA_SERVER")
    if not (email and token):
        found = _jira_cli_credentials()
        if found:
            cli_server, email, token = found
            server = server or cli_server
    if not (email and token):
        raise UsageError([
            "no Jira credentials: set JIRA_EMAIL and JIRA_API_TOKEN "
            "(token from https://id.atlassian.com/manage-profile/security/api-tokens), "
            "or configure jira-cli (~/.config/.jira/.config.yml plus the "
            "keychain item 'jira-cli')"
        ])
    pair = base64.b64encode(f"{email}:{token}".encode()).decode()
    return (server or DEFAULT_SERVER).rstrip("/"), f"Basic {pair}"


def jira_call(server: str, auth: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        server + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:1000]
        raise JiraError(err.code, detail) from err
    except urllib.error.URLError as err:
        raise JiraError(0, str(err.reason)) from err
    return json.loads(raw) if raw else {}


def add_comment(key: str, markdown: str, server: str, auth: str) -> dict:
    try:
        jira_call(
            server, auth, f"/rest/api/3/issue/{key}/comment",
            build_comment_payload(markdown),
        )
    except JiraError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True}


def create_ticket(spec: dict, server: str, auth: str) -> dict:
    created = jira_call(server, auth, "/rest/api/3/issue", build_create_payload(spec))
    key = created["key"]
    comment = add_comment(key, spec["comment"], server, auth) if spec["comment"] else None
    results = []
    for link in spec["links"]:
        try:
            jira_call(server, auth, "/rest/api/3/issueLink", build_link_payload(key, link))
            results.append({**link, "ok": True})
        except JiraError as err:
            results.append({**link, "ok": False, "error": str(err)})
    return {
        "key": key,
        "url": f"{server}/browse/{key}",
        "comment": comment,
        "links": results,
    }


def run_create(args: argparse.Namespace) -> int:
    spec = normalize_spec(load_spec(args.spec))
    if args.dry_run:
        plan = {
            "create": build_create_payload(spec),
            "comment": build_comment_payload(spec["comment"]) if spec["comment"] else None,
            "links": [build_link_payload("NEW-0", link) for link in spec["links"]],
        }
        print(json.dumps(plan, indent=2))
        return 0
    server, auth = load_credentials()
    try:
        result = create_ticket(spec, server, auth)
    except JiraError as err:
        print(f"error: Jira refused the ticket: {err}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    comment_ok = result["comment"] is None or result["comment"]["ok"]
    return 0 if comment_ok and all(link["ok"] for link in result["links"]) else 3


def run_comment_only(args: argparse.Namespace) -> int:
    key = args.comment_only
    if not ISSUE_KEY.match(key):
        raise UsageError([f"{key!r} is not an issue key like DP-123"])
    _, dump = split_agent_dump(read_source(args.spec, "body file"))
    if dump is None:
        raise UsageError(["the body has no '# Agent Dump Section' heading to post"])
    if args.dry_run:
        print(json.dumps({"issue": key, "comment": build_comment_payload(dump)}, indent=2))
        return 0
    server, auth = load_credentials()
    result = add_comment(key, dump, server, auth)
    print(json.dumps({"key": key, "comment": result}, indent=2))
    if not result["ok"]:
        print(f"error: Jira refused the comment: {result['error']}", file=sys.stderr)
    return 0 if result["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Jira story from a JSON spec.")
    parser.add_argument(
        "spec",
        help='path to the JSON spec, or "-" for stdin; with --comment-only, '
             "the markdown body file",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="print the requests instead of sending them")
    parser.add_argument(
        "--comment-only", metavar="KEY",
        help="post the Agent Dump half of the body file as a comment on KEY",
    )
    args = parser.parse_args(argv)

    try:
        return run_comment_only(args) if args.comment_only else run_create(args)
    except UsageError as err:
        for problem in err.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

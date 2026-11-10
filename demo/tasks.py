"""The requests of the real-model comparison, and the rules that decide how a session ended.

``demo/run_real.py --task NAME`` takes the project, the prompt and the rule from
here. A rule reads the files the session left behind and nothing else: it does
not know whether the plugin was installed and does not use the scanner.

For every task the answer has two parts:

- ``code_done``: did the session make the requested change in the code at all;
- ``stale`` / ``mentions``: do the docs agree with it afterwards.

The verdict is ``docs consistent``, ``docs stale`` or ``not done in the code``.
A changelog or release-notes file is not counted on either side.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, List, Tuple

DOC_SUFFIXES = (".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc")
DOC_DIRS = ("docs/", "doc/", "documentation/", "website/", "man/")
HISTORY = ("changelog", "changes", "history", "news", "release")   # a record of the past: old names belong there

# A doc line that names something in order to say it is gone is not stale.
SAYS_REMOVED = re.compile(r"(?i)\b(removed|no longer|dropped|not supported|unsupported|has been deleted|was deleted)\b")

TASKS: Dict[str, dict] = {
    "rename": {
        "example": "notesync",
        "prompt": "Rename the --output-dir flag of notesync to --dest.",
        "kind": "rename", "old": "--output-dir", "new": "--dest",
    },
    "default": {
        "example": "notesync-tasks",
        "prompt": "Make notesync retry 5 times by default instead of 3.",
        "kind": "default", "topic": r"(?i)retr|tried again", "old": r"\b(3|three)\b", "new": r"\b(5|five)\b",
    },
    "remove-flag": {
        "example": "notesync-tasks",
        "prompt": "Remove the deprecated --legacy-sync flag.",
        "kind": "remove", "old": "--legacy-sync",
    },
    "remove-env": {
        "example": "notesync-tasks",
        "prompt": "Drop support for the NOTESYNC_TOKEN_FILE environment variable.",
        "kind": "remove", "old": "NOTESYNC_TOKEN_FILE",
    },
    "add-flag": {
        "example": "notesync-tasks",
        "prompt": "Add a --dry-run flag that prints what would be copied.",
        "kind": "add", "new": "--dry-run",
    },
    "add-env": {
        "example": "notesync-tasks",
        "prompt": "Let the timeout be set with a NOTESYNC_TIMEOUT environment variable.",
        "kind": "add", "new": "NOTESYNC_TIMEOUT",
    },
    # A request on a real repository. ``repo`` and ``commit`` name the starting tree; the
    # driver is given a checkout of it with --project and refuses any other commit.
    "uvicorn-add-flag": {
        "repo": "encode/uvicorn", "commit": "a99c1b7",
        "prompt": "Add a --quiet flag that sets the log level to warning.",
        "kind": "add", "new": "--quiet",
    },
}


def is_doc(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    return low.endswith(DOC_SUFFIXES) or low.startswith(DOC_DIRS)


def is_history(rel: str) -> bool:
    return os.path.basename(rel.replace("\\", "/")).lower().startswith(HISTORY)


def project_files(repo: str) -> List[str]:
    """Tracked and new files of the project, as paths relative to it."""
    out = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-co", "--exclude-standard"], cwd=repo,
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return sorted(ln.strip() for ln in out.splitlines() if ln.strip())


def read_lines(repo: str, rel: str) -> List[str]:
    try:
        with open(os.path.join(repo, *rel.split("/")), encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def _split(repo: str) -> Tuple[List[str], List[str]]:
    files = [f for f in project_files(repo) if "__pycache__" not in f]
    docs = [f for f in files if is_doc(f) and not is_history(f)]
    code = [f for f in files if not is_doc(f)]
    return docs, code


def _hits(repo: str, files: List[str], test) -> List[str]:
    return [f"{rel}:{i}:{ln.strip()}" for rel in files for i, ln in enumerate(read_lines(repo, rel), 1) if test(ln)]


def _quoted(name: str):
    return lambda ln: f'"{name}"' in ln or f"'{name}'" in ln


def judge(task: dict, repo: str) -> dict:
    """How the session left the project: ``{"verdict", "code_done", "stale", "mentions", "rule"}``."""
    docs, code = _split(repo)
    kind = task["kind"]
    stale: List[str] = []
    mentions: List[str] = []
    if kind == "rename":
        old, new = task["old"], task["new"]
        code_done = not _hits(repo, code, _quoted(old)) and bool(_hits(repo, code, _quoted(new)))
        stale = _hits(repo, docs, lambda ln: old in ln)
        rule = f"no doc line contains {old}"
    elif kind == "default":
        topic, old, new = re.compile(task["topic"]), re.compile(task["old"]), re.compile(task["new"])
        code_done = (not _hits(repo, code, lambda ln: topic.search(ln) and re.search(r"\bdefault\s*=\s*3\b", ln))
                     and bool(_hits(repo, code, lambda ln: topic.search(ln) and new.search(ln))))
        stale = _hits(repo, docs, lambda ln: topic.search(ln) and old.search(ln))
        rule = "no doc line about retrying still says 3 or three"
    elif kind == "remove":
        old = task["old"]
        code_done = not _hits(repo, code, _quoted(old))
        stale = _hits(repo, docs, lambda ln: old in ln and not SAYS_REMOVED.search(ln))
        rule = f"no doc line contains {old}, except a line that says it was removed"
    elif kind == "add":
        new = task["new"]
        code_done = bool(_hits(repo, code, _quoted(new)))
        mentions = _hits(repo, docs, lambda ln: new in ln)
        rule = f"at least one doc file contains {new}"
    else:
        raise ValueError(f"unknown kind of task: {kind}")
    if not code_done:
        verdict = "not done in the code"
    elif kind == "add":
        verdict = "docs consistent" if mentions else "docs stale"
    else:
        verdict = "docs stale" if stale else "docs consistent"
    return {"verdict": verdict, "code_done": code_done, "stale": stale, "mentions": mentions, "rule": rule}


# ------------------------------------------------------------------ what the model had been told, and when
SPOKE_IN_RESULT = ('"new"', '"added"')
SPOKE_REMINDER = "docs-drift: your edits in this session"


def edited_paths(name: str, arguments) -> List[str]:
    """Paths a ``write_file`` or ``patch`` call names. ``arguments`` is the JSON text or the parsed object."""
    if name not in ("write_file", "patch"):
        return []
    if isinstance(arguments, str):
        import json
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return re.findall(r'"path"\s*:\s*"([^"]+)"', arguments)
    if not isinstance(arguments, dict):
        return []
    paths = [str(arguments["path"])] if arguments.get("path") else []
    body = arguments.get("patch")
    if isinstance(body, str):
        paths += re.findall(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+)$", body, re.M)
    return paths


def doc_path(path: str) -> bool:
    """Is this path, as a tool call wrote it (absolute or relative), a doc file other than a changelog."""
    norm = path.replace("\\", "/")
    tail = norm.split("/")[-1]
    in_doc_dir = any("/" + d in "/" + norm for d in DOC_DIRS)
    return (tail.lower().endswith(DOC_SUFFIXES) or in_doc_dir) and not is_history(tail)


def ordering(trace: List[dict]) -> dict:
    """From the relay's trace: when the plugin first told the model something, and the doc edits around it.

    ``trace`` is the list of records ``demo/relay.py --trace`` writes: one per
    request (what it carried that the plugin wrote) and one per answer (the tool
    calls in it). A doc edit counts as "before" when the model issued it in an
    answer to a request that did not yet carry anything from the plugin.
    """
    first = None
    how = ""
    for rec in trace:
        if "request" in rec and (rec.get("told_edit") or rec.get("told_reminder")):
            first, how = rec["request"], "edit result" if rec.get("told_edit") else "reminder"
            break
    before = after = 0
    for rec in trace:
        if "answer" not in rec:
            continue
        n = sum(1 for call in rec.get("calls") or []
                for p in edited_paths(call.get("name", ""), call.get("arguments", "")) if doc_path(p))
        if first is not None and rec["answer"] >= first:
            after += n
        else:
            before += n
    return {"spoke": first is not None, "first_request": first, "how": how,
            "doc_edits_before": before, "doc_edits_after": after,
            "reminder": any(rec.get("told_reminder") for rec in trace if "request" in rec)}

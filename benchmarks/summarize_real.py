"""Tabulate real-model sessions from the transcripts demo/run_real.py --task printed.

    python benchmarks/summarize_real.py evidence/real-model/round3

Prints one line per session, one line per cell (model, task, with or without the
plugin) for every batch of five sessions, and a pooled line where a cell has more
than one batch. The outcome, the number of requests and whether the plugin told
the model something are taken from the SUMMARY line each transcript ends with;
nothing is judged again.

The two counts of doc edits are counted again from the tool calls printed in the
transcript, because the SUMMARY line of the round 3 sessions counts every edit of
a file with a doc suffix, also of files outside the project (scratch notes a model
wrote into a cache directory to try its change). Here only edits of files in the
project count. Sessions where the two differ are listed under the tables.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo"))
import tasks  # noqa: E402

BATCH = 5
EDITS = ("write_file", "patch")
_EVENT_CALL = re.compile(r"^\[[0-9:]+Z\] tool call    (\w+) (\{.*)$")
_ANSWER = re.compile(r"^\[[0-9:]+Z\] answer (\d+) ")
_RELAY_CALL = re.compile(r"^tool call: (\w+) ")
_FIRST = re.compile(r"^the plugin told the model something: yes, first in request (\d+)", re.M)
_NAME = re.compile(r"-(plugin|none)-(\d+)\.txt$")


def in_project(path: str) -> bool:
    """Was this path, as a tool call wrote it and the driver printed it, inside the session's project.

    The project is the working directory, so a relative path is inside. An absolute
    one is inside only if it is under the temp directory the driver made for the
    session (printed as ``%TEMP%\\docs-drift-real-...``).
    """
    norm = path.replace("\\", "/")
    absolute = norm.startswith(("/", "~", "$", "%", "<")) or re.match(r"^[A-Za-z]:", norm) is not None
    return not absolute or "/docs-drift-real-" in norm


def recount(text: str):
    """Doc edits in the project before and after the plugin first spoke, and those outside it.

    Section 1 of a transcript prints every tool call with its whole arguments, in
    the order the model issued them; section 2 prints the same calls under the
    answer they came in (arguments clipped). The ``write_file`` and ``patch`` calls
    of the two lists are matched by position. Returns None when they do not line up.
    """
    head, _, relay = text.partition("\n--- 2. ")
    events = [(m.group(1), m.group(2)) for m in map(_EVENT_CALL.match, head.splitlines()) if m and m.group(1) in EDITS]
    numbered, answer = [], None
    for line in relay.splitlines():
        if line.startswith("--- 3. "):
            break
        m = _ANSWER.match(line)
        if m:
            answer = int(m.group(1))
            continue
        m = _RELAY_CALL.match(line)
        if m and answer is not None and m.group(1) in EDITS:
            numbered.append((m.group(1), answer))
    if [n for n, _ in events] != [n for n, _ in numbered]:
        return None
    m = _FIRST.search(text)
    first = int(m.group(1)) if m else None
    before = after = outside_before = outside_after = 0
    for (name, arguments), (_, answer) in zip(events, numbered):
        for p in tasks.edited_paths(name, arguments):
            if not tasks.doc_path(p):
                continue
            late = first is not None and answer >= first
            if in_project(p):
                after, before = after + late, before + (not late)
            else:
                outside_after, outside_before = outside_after + late, outside_before + (not late)
    return {"before": before, "after": after, "outside_before": outside_before, "outside_after": outside_after}


def read(path: str):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.splitlines()
    summary = next((json.loads(ln[len("SUMMARY: "):]) for ln in reversed(lines) if ln.startswith("SUMMARY: ")), None)
    started = lines[0].rsplit(" ", 1)[-1] if lines else ""
    return summary, started, text


def batch_of(name: str) -> int:
    m = _NAME.search(name)
    return (int(m.group(2)) - 1) // BATCH if m else 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip())
        return 2
    files = sorted(f for a in args for f in (glob.glob(os.path.join(a, "*.txt")) if os.path.isdir(a) else [a]))
    cells, total, missing, differ, unmatched = {}, 0, [], [], []
    print("| File | Started (UTC) | Chat requests | Hermes exit | Plugin told the model | Edits of the project's docs before / after that "
          "| Reminder | Outcome |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for path in files:
        name = os.path.basename(path)
        s, started, text = read(path)
        if s is None:
            missing.append(name)
            continue
        total += s["requests"]
        arm = "plugin" if s["plugin"] else "no plugin"
        told = (s["spoke_how"] if s["spoke"] else "nothing") if s["plugin"] else "n/a"
        counted = recount(text)
        if counted is None:
            unmatched.append(name)
            before, after = s["doc_edits_before"], s["doc_edits_after"]
        else:
            before, after = counted["before"], counted["after"]
            if (before, after) != (s["doc_edits_before"], s["doc_edits_after"]):
                differ.append((name, s, counted))
        edits = f"{before} / {after}" if s["spoke"] else f"{before} / -"
        reminder = ("delivered" if s["reminder"] else "not delivered") if s["plugin"] else "n/a"
        print(f"| `{name}` | {started[11:19]} | {s['requests']} | {s['exit_code']} | {told} | {edits} "
              f"| {reminder} | {s['verdict']} |")
        for key in ((s["model"], s["task"], arm, batch_of(name)), (s["model"], s["task"], arm, None)):
            c = cells.setdefault(key, {"n": 0, "consistent": 0, "stale": 0, "not_done": 0, "spoke": 0, "after_only": 0,
                                       "edited_docs": 0, "requests": 0})
            c["n"] += 1
            c["requests"] += s["requests"]
            c["consistent"] += s["verdict"] == "docs consistent"
            c["stale"] += s["verdict"] == "docs stale"
            c["not_done"] += s["verdict"] == "not done in the code"
            c["spoke"] += bool(s["spoke"])
            c["after_only"] += bool(s["spoke"] and before == 0 and after > 0)
            c["edited_docs"] += (before + after) > 0
    print()
    print("| Model | Task | Arm | Sessions | Docs consistent | Docs stale | Not done in the code | Sessions with an edit of the project's docs "
          "| Plugin told the model something | of those: every doc edit came after it | Chat requests |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    batches = {}
    for (model, task, arm, batch) in cells:
        if batch is not None:
            batches.setdefault((model, task), set()).add(batch)
    for (model, task, arm, batch), c in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][3] is None,
                                                                             kv[0][3] or 0, kv[0][2] != "plugin")):
        several = len(batches[(model, task)]) > 1
        if batch is None and not several:
            continue
        which = "all" if batch is None else f"{batch * BATCH + 1}-{batch * BATCH + BATCH}"
        spoke = c["spoke"] if arm == "plugin" else "n/a"
        after = c["after_only"] if arm == "plugin" else "n/a"
        print(f"| {model} | {task} | {arm} | {c['n']} ({which}) | {c['consistent']} | {c['stale']} | {c['not_done']} "
              f"| {c['edited_docs']} | {spoke} | {after} | {c['requests']} |")
    print()
    print(f"chat requests in these {len(files) - len(missing)} sessions: {total}")
    for name, s, counted in differ:
        print(f"doc edits counted again: {name}: the SUMMARY line says {s['doc_edits_before']} before / {s['doc_edits_after']} after; "
              f"{counted['outside_before']} + {counted['outside_after']} of those were files outside the project, "
              f"which leaves {counted['before']} / {counted['after']}")
    for name in unmatched:
        print(f"tool calls of sections 1 and 2 do not line up, counts taken from the SUMMARY line: {name}")
    for name in missing:
        print(f"no SUMMARY line (not a --task session, or the driver stopped early): {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

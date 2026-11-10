"""Tabulate real-model sessions from the SUMMARY line each transcript of demo/run_real.py --task ends with.

    python benchmarks/summarize_real.py evidence/real-model/round3

Prints one line per session and one per cell (model, task, with or without the
plugin). Reads the transcripts only; it does not judge anything again.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def read(path: str):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    summary = next((json.loads(ln[len("SUMMARY: "):]) for ln in reversed(lines) if ln.startswith("SUMMARY: ")), None)
    started = lines[0].rsplit(" ", 1)[-1] if lines else ""
    return summary, started


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip())
        return 2
    files = sorted(f for a in args for f in (glob.glob(os.path.join(a, "*.txt")) if os.path.isdir(a) else [a]))
    cells, total, missing = {}, 0, []
    print("| File | Started (UTC) | Chat requests | Hermes exit | Plugin told the model | Doc edits before / after that | Reminder | Outcome |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for path in files:
        s, started = read(path)
        if s is None:
            missing.append(os.path.basename(path))
            continue
        total += s["requests"]
        arm = "plugin" if s["plugin"] else "no plugin"
        told = (s["spoke_how"] if s["spoke"] else "nothing") if s["plugin"] else "n/a"
        edits = f"{s['doc_edits_before']} / {s['doc_edits_after']}" if s["spoke"] else f"{s['doc_edits_before']} / -"
        reminder = ("delivered" if s["reminder"] else "not delivered") if s["plugin"] else "n/a"
        print(f"| `{os.path.basename(path)}` | {started[11:19]} | {s['requests']} | {s['exit_code']} | {told} | {edits} "
              f"| {reminder} | {s['verdict']} |")
        c = cells.setdefault((s["model"], s["task"], arm), {"n": 0, "consistent": 0, "stale": 0, "not_done": 0, "spoke": 0,
                                                              "after_only": 0, "requests": 0})
        c["n"] += 1
        c["requests"] += s["requests"]
        c["consistent"] += s["verdict"] == "docs consistent"
        c["stale"] += s["verdict"] == "docs stale"
        c["not_done"] += s["verdict"] == "not done in the code"
        c["spoke"] += bool(s["spoke"])
        c["after_only"] += bool(s["spoke"] and s["doc_edits_before"] == 0 and s["doc_edits_after"] > 0)
    print()
    print("| Model | Task | Arm | Sessions | Docs consistent | Docs stale | Not done in the code | Plugin told the model something "
          "| of those: every doc edit came after it | Chat requests |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for (model, task, arm), c in sorted(cells.items()):
        spoke = c["spoke"] if arm == "plugin" else "n/a"
        after = c["after_only"] if arm == "plugin" else "n/a"
        print(f"| {model} | {task} | {arm} | {c['n']} | {c['consistent']} | {c['stale']} | {c['not_done']} | {spoke} | {after} "
              f"| {c['requests']} |")
    print()
    print(f"chat requests in these {len(files) - len(missing)} sessions: {total}")
    for name in missing:
        print(f"no SUMMARY line (not a --task session, or the driver stopped early): {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Totals for an injected-drift run (the JSON files written by inject.py).

    python benchmarks/summarize_inject.py <inject_out_dir> [--misses]

Prints, per kind of injected drift, how many injections the edit-aware scan
(what the hook and changed_only run) caught and how many a plain whole-repo
scan caught, and lists every finding that appeared after an injection and is
about something other than the injected item (a false alarm caused by the edit).
"""

from __future__ import annotations

import glob
import json
import os
import sys


def main() -> int:
    out_dir = sys.argv[1]
    show_misses = "--misses" in sys.argv[2:]
    kinds: dict = {}
    extras = []
    same_item = []
    skipped = 0
    misses = []
    repos = 0
    for path in sorted(glob.glob(os.path.join(out_dir, "*.json"))):
        data = json.load(open(path, encoding="utf-8"))
        repos += 1
        for row in data.get("rows", []):
            repo = data.get("repo", os.path.basename(path))
            if row.get("detected") is None:
                # inject.py could not make this mutation (see its "note"); not an injection
                skipped += 1
                continue
            k = kinds.setdefault(row["kind"], {"n": 0, "edit": 0, "plain": 0})
            k["n"] += 1
            k["edit"] += 1 if row.get("detected") else 0
            k["plain"] += 1 if row.get("detected_scan") else 0
            if not row.get("detected"):
                misses.append((repo, row["kind"], row.get("name")))
            for extra in row.get("other_new_findings", []):
                # removing a file that several doc lines link to gives one finding per line
                same = row["kind"] == "path" and str(row.get("name", "")).rsplit(".", 1)[0] in str(extra)
                (same_item if same else extras).append((repo, row["kind"], row.get("name"), extra))
    total = {"n": 0, "edit": 0, "plain": 0}
    print(f"{repos} repositories")
    print(f"{'kind':16} {'injected':>8} {'edit-aware':>11} {'plain scan':>11}")
    for kind, k in sorted(kinds.items()):
        print(f"{kind:16} {k['n']:8d} {k['edit']:11d} {k['plain']:11d}")
        for key in total:
            total[key] += k[key]
    print(f"{'total':16} {total['n']:8d} {total['edit']:11d} {total['plain']:11d}")
    if total["n"]:
        print(f"recall: edit-aware {total['edit'] / total['n']:.3f}, plain scan {total['plain'] / total['n']:.3f}")
    print(f"mutations that could not be made and are not counted: {skipped}")
    print(f"further findings for the injected item itself (other doc lines linking the removed file): {len(same_item)}")
    print(f"findings after an injection that were about something else: {len(extras)}")
    for e in extras:
        print("  other:", *e)
    if show_misses:
        for m in misses:
            print("  miss:", *m)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Compare a repeated injection run with the stored one, row by row.

    python benchmarks/inject.py <clones_dir> <new_dir>/<run> owner__name ...
    python benchmarks/compare_injected.py <new_dir> [evidence/injected] RUN [RUN ...]

``inject.py`` picks its candidates with a fixed seed, so two runs on the same clones make
the same changes in the same order. For every ``<run>/<owner__name>.json`` of the stored
directory this prints whether the file of the new run has the same rows. The time a scan
took (``scan_s``) is left out of the comparison; everything else is compared.

Up to the ``final-*`` runs ``inject.py`` kept the first ten entries of ``other_new_findings``
and now keeps all of them. A stored row with exactly ten entries is therefore compared with
the first ten of the new row; such rows are counted and printed.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def rows(path: str):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    cleaned = [{k: v for k, v in row.items() if k != "scan_s"} for row in data.pop("rows")]
    return data, cleaned


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    new_dir = args.pop(0)
    stored = args.pop(0) if os.path.isdir(args[0]) else os.path.join(here, "evidence", "injected")
    total_rows = total_diff = files = missing = cut = 0
    for run in args:
        same = diff = n = 0
        for path in sorted(glob.glob(os.path.join(stored, run, "*.json"))):
            name = os.path.basename(path)
            other = os.path.join(new_dir, run, name)
            if not os.path.isfile(other):
                missing += 1
                print(f"  missing {run}/{name}")
                continue
            files += 1
            old_head, old_rows = rows(path)
            new_head, new_rows = rows(other)
            n += len(old_rows)
            for a, b in zip(old_rows, new_rows):
                kept, now = a.get("other_new_findings"), b.get("other_new_findings")
                if kept is not None and now is not None and len(kept) == 10 < len(now) and now[:10] == kept:
                    b["other_new_findings"] = kept
                    cut += 1
                    print(f"  first ten compared {run}/{name}: {a['kind']} {a['name']} "
                          f"(stored 10 other findings, now {len(now)})")
            changed = sum(a != b for a, b in zip(old_rows, new_rows)) + abs(len(old_rows) - len(new_rows))
            if changed or old_head != new_head:
                diff += 1
                print(f"  different {run}/{name}: {changed} of {len(old_rows)} rows"
                      f"{'' if old_head == new_head else '; the fields outside the rows differ'}")
            else:
                same += 1
            total_diff += changed
        total_rows += n
        print(f"{run}: files same {same}, different {diff}; rows {n}")
    print()
    print(f"files compared: {files}; missing: {missing}; rows: {total_rows}; rows that differ: {total_diff}; "
          f"rows compared on their first ten other findings: {cut}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

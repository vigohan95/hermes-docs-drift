"""Scan the measured repositories again and compare with the stored scan files.

    python benchmarks/compare_scans.py <clones_dir> [evidence/scans] > evidence/rescan.txt

For every ``<run>-<set>/<owner__name>.json`` below the scans directory, the clone
``<clones_dir>/<owner__name>`` is scanned with the code in this checkout and all nine checks,
and the result is compared with the stored one: the findings with all their fields, the
number of doc files and code files, and the counts of what was withheld. A clone is scanned
once, however many stored files name it. A clone that is missing, or is not at the commit the
stored file names, is counted as skipped.

A stored file written by an older scanner can differ for a good reason: a rule was changed
between that run and this code. The runs to look at are the ones made with the last scanner
that changed a check (``final-*`` and ``round4-*`` in evidence/README.md).
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsdrift import __version__  # noqa: E402
from docsdrift.scan import Scanner  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    clones = sys.argv[1]
    scans = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "evidence", "scans")
    cache: dict = {}

    def scan(name: str):
        if name not in cache:
            root = os.path.join(clones, name)
            sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            started = time.monotonic()
            result = Scanner(root).scan(checks="all")
            cache[name] = (sha, [dict(f.full(), doc_lines=f.doc_lines) for f in result.findings], result.doc_files,
                           result.code_files, result.incomplete, result.suppressed, time.monotonic() - started)
        return cache[name]

    print(f"docsdrift {__version__}; python {sys.version.split()[0]} on {sys.platform}")
    print("same = findings, file counts and withheld counts are equal to the stored file")
    print()
    total_same = total_diff = total_skipped = 0
    for directory in sorted(glob.glob(os.path.join(scans, "*"))):
        if not os.path.isdir(directory):
            continue
        same = diff = skipped = 0
        for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            name = os.path.basename(path)[:-5]
            if not os.path.isdir(os.path.join(clones, name)):
                skipped += 1
                print(f"  skipped {os.path.basename(directory)}/{name}: no clone")
                continue
            sha, findings, docs, code, incomplete, withheld, _took = scan(name)
            if sha != old["sha"]:
                skipped += 1
                print(f"  skipped {os.path.basename(directory)}/{name}: clone is at {sha[:7]}, stored file at {old['sha'][:7]}")
                continue
            if (findings == old["findings"] and docs == old["doc_files"] and code == old["code_files"]
                    and incomplete == old["incomplete"] and withheld == old["not_reported"]):
                same += 1
                continue
            diff += 1
            a = {json.dumps(x, sort_keys=True) for x in old["findings"]}
            b = {json.dumps(x, sort_keys=True) for x in findings}
            print(f"  different {os.path.basename(directory)}/{name}: findings {len(a)} -> {len(b)} "
                  f"(only stored {len(a - b)}, only now {len(b - a)}); doc files {old['doc_files']} -> {docs}; "
                  f"code files {old['code_files']} -> {code}")
        print(f"{os.path.basename(directory)}: same {same}, different {diff}, skipped {skipped}", flush=True)
        total_same += same
        total_diff += diff
        total_skipped += skipped
    print()
    print(f"stored files: same {total_same}, different {total_diff}, skipped {total_skipped}")
    print(f"repositories scanned: {len(cache)}; findings now: {sum(len(v[1]) for v in cache.values())}; "
          f"slowest scan: {max((v[6] for v in cache.values()), default=0.0):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

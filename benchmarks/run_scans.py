"""Scan pinned repositories with every check and save the full findings.

    python benchmarks/run_scans.py <targets_dir> <out_dir> owner__name [owner__name ...]

Each target is a clone at ``<targets_dir>/<owner>__<name>``. The output file
records the commit that was scanned, so a label always refers to a known tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsdrift.scan import DEFAULT_CHECKS, Scanner  # noqa: E402


def main() -> int:
    targets, out_dir, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        root = os.path.join(targets, name)
        sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        t0 = time.monotonic()
        scanner = Scanner(root)
        result = scanner.scan(checks="all")
        cold = time.monotonic() - t0
        t1 = time.monotonic()
        scanner.scan(checks="all")
        warm = time.monotonic() - t1
        data = {
            "repo": name.replace("__", "/", 1), "sha": sha,
            "cold_scan_s": round(cold, 2), "warm_rescan_s": round(warm, 2),
            "doc_files": result.doc_files, "code_files": result.code_files,
            "incomplete": result.incomplete, "notes": result.notes, "not_reported": result.suppressed,
            "default_checks": list(DEFAULT_CHECKS),
            "findings": [dict(f.full(), doc_lines=f.doc_lines) for f in result.findings],
        }
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        print(f"{name}: {len(result.findings)} findings {result.counts()} docs={result.doc_files} code={result.code_files} "
              f"cold={cold:.1f}s warm={warm:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

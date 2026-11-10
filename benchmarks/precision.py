"""Precision of saved whole-repository scans, from hand labels.

    python benchmarks/precision.py <scans_dir> <labels.json>

``<scans_dir>`` holds one directory per run (written by run_scans.py);
``labels.json`` maps ``repo|check|name|doc_file:line`` to ``{"true": bool,
"reason": str}``. The script fails when a finding has no label, so a number
can never be printed for findings nobody looked at.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def main() -> int:
    scans_dir, labels_path = sys.argv[1], sys.argv[2]
    with open(labels_path, encoding="utf-8") as fh:
        labels = json.load(fh)["labels"]
    used = set()
    missing = []
    print(f"{'run':<18} {'repos':>5} {'docs':>5} {'code':>6}   {'default checks':<22} {'opt-in checks':<22}")
    print(f"{'':<18} {'':>5} {'':>5} {'':>6}   {'found  true  false':<22} {'found  true  false':<22}")
    for run in sorted(os.listdir(scans_dir)):
        paths = sorted(glob.glob(os.path.join(scans_dir, run, "*.json")))
        if not paths:
            continue
        counts = {"default": [0, 0], "opt-in": [0, 0]}
        docs = code = 0
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            docs += data["doc_files"]
            code += data["code_files"]
            defaults = set(data["default_checks"])
            for f in data["findings"]:
                key = f"{data['repo']}|{f['check']}|{f['name']}|{f['doc']}"
                label = labels.get(key)
                if label is None:
                    missing.append(f"{run}: {key}")
                    continue
                used.add(key)
                group = counts["default" if f["check"] in defaults else "opt-in"]
                group[0 if label["true"] else 1] += 1
        cells = []
        for name in ("default", "opt-in"):
            t, f = counts[name]
            cells.append(f"{t + f:>5} {t:>5} {f:>6}     ")
        print(f"{run:<18} {len(paths):>5} {docs:>5} {code:>6}   {cells[0]:<22} {cells[1]:<22}")
    unused = sorted(set(labels) - used)
    print()
    print(f"labels: {len(labels)}, used: {len(used)}, findings without a label: {len(missing)}, labels matching no finding: {len(unused)}")
    for line in missing + [f"unused: {u}" for u in unused]:
        print("  " + line)
    return 1 if missing or unused else 0


if __name__ == "__main__":
    sys.exit(main())

"""Command line: ``python -m docsdrift [path]``. Used by CI and for evidence runs."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .model import CHECKS
from .report import format_finding, format_result
from .scan import DEFAULT_CHECKS, Scanner, explain, find_root


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docsdrift",
        description="Report places where README/docs no longer match the code. Offline; reads files and runs git.",
    )
    p.add_argument("path", nargs="?", default=".", help="repository (or any path inside it)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--since", metavar="REV", help="only findings introduced by changes since REV (e.g. HEAD)")
    p.add_argument("--checks", default=None,
                   help="comma-separated check ids, 'all', or +name/-name relative to the defaults (" + ", ".join(DEFAULT_CHECKS) + ")")
    p.add_argument("--min-confidence", choices=["high", "medium"], default="medium")
    p.add_argument("--max-findings", type=int, default=200)
    p.add_argument("--explain", metavar="ID", help="show one finding with context on both sides")
    p.add_argument("--list-checks", action="store_true", help="print the check ids and exit")
    p.add_argument("--no-git", action="store_true", help="walk the directory instead of asking git for the file list")
    p.add_argument("--exit-zero", action="store_true", help="exit 0 even when findings exist")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_checks:
        for cid, text in CHECKS.items():
            mark = "default" if cid in DEFAULT_CHECKS else "opt-in "
            print(f"{cid:24} {mark}  {text}")
        return 0
    root = find_root(args.path)
    scanner = Scanner(root, use_git=not args.no_git)
    kw = dict(checks=args.checks, min_confidence=args.min_confidence)
    resolved = []
    problem = None
    if args.since:
        result, resolved, problem = scanner.scan_changes(args.since, **kw)
    else:
        result = scanner.scan(**kw)
    if args.explain:
        info = explain(scanner, result, args.explain)
        if info is None:
            print(f"no finding with id {args.explain}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            f = result.by_id(args.explain)
            print("\n".join(format_finding(f)))
            print("\nwhy this was reported:")
            for w in info.get("why", []):
                print(f"  - {w}")
            print("\ndocs:")
            print("\n".join(info.get("doc_context", [])))
            if info.get("code_context"):
                print("\ncode:")
                print("\n".join(info["code_context"]))
        return 0
    if args.json:
        d = result.to_dict(limit=args.max_findings)
        if args.since:
            d["resolved_by_changes"] = [f.brief() for f in resolved]
        if problem:
            d.setdefault("notes", []).append(problem)
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        title = f"docs-drift (new since {args.since})" if args.since else "docs-drift"
        print(format_result(result, limit=args.max_findings, title=title))
        if problem:
            print(f"note: {problem}")
        if resolved:
            print(f"resolved by the changes: {len(resolved)}")
    if result.incomplete:
        return 3
    return 0 if (args.exit_zero or not result.findings) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Plain-text rendering of scan results (CLI, slash command, hook messages)."""

from __future__ import annotations

from typing import Iterable, List

from .model import Finding, ScanResult


def format_finding(f: Finding) -> List[str]:
    out = [f"{f.doc_file}:{f.doc_line}  {f.check}  [{f.confidence}]  {f.id}", f"  {f.message}"]
    if f.doc_quote:
        out.append(f"  docs: {f.doc_file}:{f.doc_line}  {f.doc_quote}")
    if f.code_file:
        loc = f"{f.code_file}:{f.code_line}" if f.code_line else f.code_file
        out.append(f"  code: {loc}  {f.code_quote}".rstrip())
    if len(f.doc_lines) > 1:
        out.append("  also at lines: " + ", ".join(str(n) for n in f.doc_lines[1:8]))
    if f.suggestion:
        out.append(f"  fix:  {f.suggestion}")
    return out


def format_result(result: ScanResult, limit: int = 50, title: str = "docs-drift") -> str:
    n = len(result.findings)
    head = (
        f"{title}: {n} finding{'s' if n != 1 else ''} "
        f"({result.doc_files} doc files checked against {result.code_files} code files, {result.elapsed_ms} ms)"
    )
    lines = [head]
    for f in result.findings[:limit]:
        lines.append("")
        lines.extend(format_finding(f))
    if n > limit:
        lines.append("")
        lines.append(f"... {n - limit} more not shown")
    if result.suppressed:
        total = sum(result.suppressed.values())
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(result.suppressed.items(), key=lambda kv: -kv[1])[:6])
        lines.append("")
        lines.append(f"not reported (uncertain, {total}): {parts}")
    for note in result.notes:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def format_new_drift(new: Iterable[Finding], resolved: int = 0, limit: int = 8) -> str:
    """Short message for the agent after an edit."""
    new = list(new)
    lines = [
        f"docs-drift: this edit left {len(new)} place{'s' if len(new) != 1 else ''} "
        "where the docs no longer match the code."
    ]
    for f in new[:limit]:
        lines.append(f"- {f.doc_file}:{f.doc_line} [{f.check}] {f.message}")
        if f.code_file:
            loc = f"{f.code_file}:{f.code_line}" if f.code_line else f.code_file
            lines.append(f"  code: {loc}")
        if f.suggestion:
            lines.append(f"  fix: {f.suggestion}")
    if len(new) > limit:
        lines.append(f"- ... {len(new) - limit} more (call docs_drift_scan with changed_only=true)")
    if resolved:
        lines.append(f"({resolved} earlier finding{'s' if resolved != 1 else ''} resolved by this edit.)")
    return "\n".join(lines)

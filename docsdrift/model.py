"""Result types shared by the checks, the reports and the Hermes wiring."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

CHECKS = {
    "path-missing": "A Markdown link or image points at a file that is not in the repository.",
    "path-ref-missing": "A file path written in inline code does not exist in the repository.",
    "cli-flag-undefined": "Docs show a command-line flag that the code no longer defines.",
    "cli-flag-undocumented": "The code defines a flag that the docs listing its siblings do not mention.",
    "env-undefined": "Docs name an environment variable that nothing in the code reads.",
    "env-undocumented": "The code reads an environment variable that the docs listing its siblings do not mention.",
    "default-mismatch": "Docs state a default value that differs from the default in the code.",
    "npm-script-missing": "Docs tell the reader to run a package.json script that does not exist.",
    "make-target-missing": "Docs tell the reader to run a make target that no Makefile defines.",
}

# Told to the agent in a session after an edit, never by a whole-repository scan (see checks.added_undocumented).
EDIT_NOTES = {
    "added-flag-undocumented": "An edit in this session added a command-line flag that no doc mentions, while the docs list other flags of the project.",
    "added-env-undocumented": "An edit in this session added a read of an environment variable that no doc mentions, while the docs name other variables with the same prefix.",
}

CONFIDENCE_ORDER = {"high": 2, "medium": 1}


@dataclass
class Finding:
    check: str
    name: str                      # the flag / variable / path / script in question
    doc_file: str
    doc_line: int
    doc_quote: str
    message: str
    confidence: str = "high"
    doc_lines: List[int] = field(default_factory=list)   # every occurrence in doc_file
    code_file: str = ""
    code_line: int = 0
    code_quote: str = ""
    suggestion: str = ""
    why: List[str] = field(default_factory=list)          # which gates it passed, where we looked
    id: str = ""

    def finish(self) -> "Finding":
        key = f"{self.check}|{self.doc_file}|{self.name}"
        self.id = "DD-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        if not self.doc_lines:
            self.doc_lines = [self.doc_line]
        return self

    def brief(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "check": self.check,
            "confidence": self.confidence,
            "doc": f"{self.doc_file}:{self.doc_line}",
            "doc_quote": self.doc_quote,
            "problem": self.message,
        }
        if self.code_file:
            d["code"] = f"{self.code_file}:{self.code_line}" if self.code_line else self.code_file
        if self.code_quote:
            d["code_quote"] = self.code_quote
        if self.suggestion:
            d["suggestion"] = self.suggestion
        if len(self.doc_lines) > 1:
            d["also_at_lines"] = self.doc_lines[1:8]
        return d

    def full(self) -> Dict[str, Any]:
        d = self.brief()
        d["name"] = self.name
        d["why"] = list(self.why)
        d["what_this_check_means"] = CHECKS.get(self.check) or EDIT_NOTES.get(self.check, "")
        return d


@dataclass
class Index:
    """The code side as one scan saw it.

    A later scan can be given an earlier Index (``before=``). Names that were
    in the code then and are in no non-doc file now were removed by the edits
    in between, which is much stronger evidence than "the docs mention a name
    the code does not have".
    """

    flag_literals: FrozenSet[str] = frozenset()
    product_flag_literals: FrozenSet[str] = frozenset()                # the same, outside tests/tools/CI
    flag_facts: Dict[str, List[Any]] = field(default_factory=dict)     # key -> [Fact]
    env_tokens: FrozenSet[str] = frozenset()
    env_facts: Dict[str, List[Any]] = field(default_factory=dict)      # NAME -> [Fact]
    npm_scripts: Dict[str, str] = field(default_factory=dict)          # name -> package.json path
    make_targets: Dict[str, str] = field(default_factory=dict)         # name -> "Makefile:line"
    files: FrozenSet[str] = frozenset()
    keys: Dict[str, Any] = field(default_factory=dict)                 # path -> (mtime, size) of code files


@dataclass
class ScanResult:
    root: str
    findings: List[Finding] = field(default_factory=list)
    suppressed: Dict[str, int] = field(default_factory=dict)   # reason -> count
    notes: List[str] = field(default_factory=list)
    doc_files: int = 0
    code_files: int = 0
    elapsed_ms: int = 0
    incomplete: bool = False      # the scan stopped early; findings are withheld
    index: Optional[Index] = field(default=None, repr=False, compare=False)

    def ids(self) -> set:
        return {f.id for f in self.findings}

    def by_id(self, fid: str):
        for f in self.findings:
            if f.id == fid or f.id.lower() == fid.lower():
                return f
        return None

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.check] = out.get(f.check, 0) + 1
        return out

    def to_dict(self, limit: int = 50) -> Dict[str, Any]:
        shown = self.findings[:limit]
        d: Dict[str, Any] = {
            "root": self.root,
            "summary": {
                "findings": len(self.findings),
                "by_check": self.counts(),
                "doc_files_checked": self.doc_files,
                "code_files_read": self.code_files,
                "elapsed_ms": self.elapsed_ms,
            },
            "findings": [f.brief() for f in shown],
        }
        if len(self.findings) > limit:
            d["truncated"] = f"{len(self.findings) - limit} more findings not shown; raise max_findings"
        if self.suppressed:
            d["not_reported"] = dict(self.suppressed)
        if self.notes:
            d["notes"] = list(self.notes)
        if self.incomplete:
            d["incomplete"] = True
        return d

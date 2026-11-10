"""Scanner: builds the code index, runs the checks, compares two scans.

A :class:`Scanner` is kept alive between scans of the same repository. It
caches what it extracted from every file by (mtime, size), so a re-scan after
an edit only re-reads the files that changed.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .checks import ALL_CHECKS, Context, added_undocumented
from .docs import Doc, parse_markdown
from .facts import ENV_TOKEN, FLAG_LITERAL, Fact, FileFacts, Project, extract_file, is_support_path, norm_flag, scan_project
from .model import CHECKS, CONFIDENCE_ORDER, Finding, Index, ScanResult
from .repo import Repo, find_root, may_read

# Checks that run unless the caller asks for something else. The two
# "undocumented" checks and the inline path check are opt-in: see README
# ("Measured precision") for the numbers behind that choice.
DEFAULT_CHECKS: Tuple[str, ...] = (
    "path-missing",
    "cli-flag-undefined",
    "env-undefined",
    "default-mismatch",
    "npm-script-missing",
    "make-target-missing",
)
OPT_IN_CHECKS: Tuple[str, ...] = ("path-ref-missing", "cli-flag-undocumented", "env-undocumented")

MAX_CODE_FILES = 25_000
_MENTION_EXT = (".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc")


def resolve_checks(spec: Optional[Iterable[str]]) -> List[str]:
    """Turn a user selection ("all", "default", names, "+name", "-name") into check ids."""
    if spec is None:
        return list(DEFAULT_CHECKS)
    if isinstance(spec, str):
        spec = [s for s in re.split(r"[,\s]+", spec) if s]
    items = [str(s).strip() for s in spec if str(s).strip()]
    if not items:
        return list(DEFAULT_CHECKS)
    relative = all(i[0] in "+-" for i in items)
    chosen: List[str] = list(DEFAULT_CHECKS) if relative else []
    for item in items:
        if item in ("all", "+all"):
            chosen = list(ALL_CHECKS)
        elif item in ("default", "+default"):
            chosen += [c for c in DEFAULT_CHECKS if c not in chosen]
        elif item.startswith("-") and item[1:] in ALL_CHECKS:
            chosen = [c for c in chosen if c != item[1:]]
        else:
            name = item.lstrip("+")
            if name in ALL_CHECKS and name not in chosen:
                chosen.append(name)
    if not chosen and not any(i.lstrip("+-") in ALL_CHECKS or i.lstrip("+") in ("all", "default") for i in items):
        return list(DEFAULT_CHECKS)        # nothing recognisable was asked for: do not silently run nothing
    return [c for c in ALL_CHECKS if c in chosen]


class Scanner:
    def __init__(self, root: str, use_git: bool = True):
        self.repo = Repo(root, use_git=use_git)
        self.root = self.repo.root
        self._facts: Dict[str, Tuple[Any, FileFacts]] = {}
        self._docs: Dict[str, Tuple[Any, Doc]] = {}
        self._mentions: Dict[str, Tuple[Any, Set[str], Set[str]]] = {}
        self._project: Optional[Tuple[Any, Project]] = None
        self._loose_hits: Dict[str, Optional[str]] = {}
        self._loose_keys: Dict[str, Any] = {}

    # ------------------------------------------------------------ index
    def _file_facts(self, repo: Repo, rel: str) -> Optional[FileFacts]:
        key = repo.stat_key(rel)
        hit = self._facts.get(rel)
        if hit and hit[0] == key:
            return hit[1]
        text = repo.read(rel)
        if text is None:
            return None
        ff = extract_file(rel, text)
        self._facts[rel] = (key, ff)
        return ff

    def _doc(self, repo: Repo, rel: str) -> Optional[Doc]:
        key = repo.stat_key(rel)
        hit = self._docs.get(rel)
        if hit and hit[0] == key:
            return hit[1]
        text = repo.read(rel)
        if text is None:
            return None
        doc = parse_markdown(rel, text)
        self._docs[rel] = (key, doc)
        return doc

    def _project_for(self, repo: Repo, sig: Any) -> Project:
        if self._project and self._project[0] == sig:
            return self._project[1]
        project = scan_project(repo)
        self._project = (sig, project)
        return project

    # ------------------------------------------------------------ scan
    def scan(
        self,
        overlay: Optional[Dict[str, Optional[str]]] = None,
        checks: Optional[Iterable[str]] = None,
        min_confidence: str = "medium",
        budget_s: Optional[float] = None,
        refresh: bool = True,
        before: Optional[Index] = None,
        added: bool = False,
    ) -> ScanResult:
        """Run the checks.

        ``before`` is the :class:`Index` of an earlier scan of the same
        repository (``result.index``). With it, a name that the code had then
        and has nowhere now is reported wherever the docs still use it, without
        the gates that a whole-repository scan needs to stay quiet.

        ``added`` (only with ``before``) also reports flags and environment
        variables that are in the code now, were not then, and that no doc
        mentions. The Hermes hooks ask for it; nothing else does.
        """
        started = time.monotonic()
        deadline = started + budget_s if budget_s is not None else None
        if refresh:
            self.repo.refresh()
        repo = self.repo.with_overlay(overlay) if overlay else self.repo
        result = ScanResult(root=self.root)
        selected = resolve_checks(checks)

        code_files = repo.code_files()
        doc_files = repo.doc_files()
        result.doc_files = len(doc_files)
        result.code_files = len(code_files)
        if repo.truncated or len(code_files) > MAX_CODE_FILES:
            result.incomplete = True
            result.notes.append(
                f"Repository too large for a full index ({len(repo.files)} files listed, "
                f"limit {MAX_CODE_FILES} code files); nothing reported."
            )
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result
        if not doc_files:
            result.notes.append("No Markdown docs found to check.")
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result

        env_tokens: Set[str] = set()
        flag_literals: Set[str] = set()
        product_flag_literals: Set[str] = set()
        facts: List[Fact] = []
        dyn_prefixes: Set[str] = set()
        auto_env = False
        keys: Dict[str, Any] = {}
        for n, rel in enumerate(code_files):
            if deadline and n % 50 == 0 and time.monotonic() > deadline:
                result.incomplete = True
                result.notes.append(
                    f"Time budget of {budget_s:g}s used up after indexing {n} of {len(code_files)} files; nothing reported."
                )
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
                return result
            ff = self._file_facts(repo, rel)
            if ff is None:
                continue
            keys[rel] = self._facts[rel][0]
            env_tokens |= ff.env_tokens
            flag_literals |= ff.flag_literals
            facts.extend(ff.facts)
            if not is_support_path(rel):
                product_flag_literals |= ff.flag_literals
                dyn_prefixes |= ff.dyn_prefixes
                auto_env = auto_env or ff.auto_env
        sig = hash(tuple(sorted(keys.items(), key=lambda kv: kv[0])))
        project = self._project_for(repo, (sig, len(repo.files)))

        docs: List[Doc] = []
        for rel in doc_files:
            d = self._doc(repo, rel)
            if d is not None:
                docs.append(d)

        def loose(names: Iterable[str]) -> Set[str]:
            return self._loose_trace(repo, code_files, keys, list(names), deadline)

        mention_cache: List[Tuple[Set[str], Set[str]]] = []

        def doc_mentions() -> Tuple[Set[str], Set[str]]:
            if not mention_cache:
                mention_cache.append(self._doc_mentions(repo))
            return mention_cache[0]

        ctx = Context(
            repo=repo, docs=docs, project=project, env_tokens=env_tokens, flag_literals=flag_literals,
            facts=facts, dyn_prefixes=dyn_prefixes, auto_env=auto_env, loose=loose, doc_mentions=doc_mentions,
            before=before, keys=keys,
        )
        result.index = Index(
            flag_literals=frozenset(flag_literals), product_flag_literals=frozenset(product_flag_literals),
            flag_facts=ctx.flag_facts, env_tokens=frozenset(env_tokens),
            env_facts=ctx.env_facts, npm_scripts=dict(project.npm_scripts), make_targets=dict(project.make_targets),
            files=frozenset(repo.files), keys=keys,
        )
        floor = CONFIDENCE_ORDER.get(min_confidence, 1)
        findings: List[Finding] = []
        for name in selected:
            if deadline and time.monotonic() > deadline:
                result.incomplete = True
                result.notes.append(f"Time budget of {budget_s:g}s used up before check {name}; nothing reported.")
                findings = []
                break
            try:
                found = ALL_CHECKS[name](ctx)
            except Exception as exc:  # a broken check must not hide the others
                result.notes.append(f"check {name} failed: {type(exc).__name__}: {exc}")
                continue
            for f in found:
                if CONFIDENCE_ORDER.get(f.confidence, 1) >= floor:
                    findings.append(f)
                else:
                    ctx.skip("below-min-confidence")
        if added and before is not None and not result.incomplete:
            try:
                for f in added_undocumented(ctx):
                    if CONFIDENCE_ORDER.get(f.confidence, 1) >= floor:
                        findings.append(f)
                    else:
                        ctx.skip("below-min-confidence")
            except Exception as exc:
                result.notes.append(f"added-name report failed: {type(exc).__name__}: {exc}")
        seen: Set[str] = set()
        unique: List[Finding] = []
        for f in sorted(findings, key=lambda x: (x.doc_file, x.doc_line, x.check, x.name)):
            if f.id in seen:
                continue
            seen.add(f.id)
            unique.append(f)
        result.findings = unique
        result.suppressed = dict(ctx.suppressed)
        result.notes.extend(ctx.notes)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    # ------------------------------------------------------------ traces
    @staticmethod
    def _loose_spec(name: str) -> Any:
        parts = [p for p in name.lower().split("-") if p]
        if not parts:
            return None
        if len(parts) == 1:
            return ("word", parts[0], re.compile(r"(?<![a-z0-9])" + re.escape(parts[0]) + r"(?![a-z0-9])"))
        return ("multi", ("_".join(parts), "-".join(parts), "".join(parts), " ".join(parts)))

    def _loose_search(self, repo: Repo, files: Sequence[str], names: Iterable[str],
                      deadline: Optional[float]) -> bool:
        """Look for each name in ``files``; record the first file that has it.

        Returns False when the deadline cut the search short (unfinished names
        are then left without a verdict).
        """
        todo: Dict[str, Any] = {}
        for n in names:
            spec = self._loose_spec(n)
            if spec is None:
                self._loose_hits[n] = ""
            else:
                todo[n] = spec
        if not todo:
            return True
        for i, rel in enumerate(files):
            if not todo:
                break
            if deadline and i % 50 == 0 and time.monotonic() > deadline:
                return False
            text = repo.read(rel)
            if not text:
                continue
            low = text.lower()
            for n in list(todo):
                spec = todo[n]
                if spec[0] == "word":
                    hit = spec[1] in low and bool(spec[2].search(low))
                else:
                    hit = any(v in low for v in spec[1])
                if hit:
                    self._loose_hits[n] = rel
                    del todo[n]
        for n in todo:
            self._loose_hits.setdefault(n, None)
        return True

    def _loose_trace(self, repo: Repo, code_files: Sequence[str], keys: Dict[str, Any], names: List[str],
                     deadline: Optional[float]) -> Set[str]:
        """Names that occur in code in some other spelling (snake, camel, bare word).

        ``names`` are lowercase kebab keys such as ``dry-run``. A hit means the
        name is *probably* known, so the caller does not report it. Verdicts are
        kept between scans and only re-examined for files that changed.
        """
        hits = self._loose_hits
        prev = self._loose_keys
        if prev is not keys:
            changed = {rel for rel in code_files if prev.get(rel) != keys.get(rel)}
            gone = set(prev) - set(keys)
            if changed or gone:
                for n, rel in list(hits.items()):
                    if rel and (rel in changed or rel in gone):
                        del hits[n]                       # its evidence may be gone: search again
                misses = [n for n, rel in hits.items() if rel is None]
                for n in misses:
                    del hits[n]
                if not self._loose_search(repo, [f for f in code_files if f in changed], misses, deadline):
                    for n in misses:
                        hits.pop(n, None)
            self._loose_keys = keys
        todo = [n for n in names if n not in hits]
        complete = self._loose_search(repo, code_files, todo, deadline)
        out = {n for n in names if hits.get(n) is not None}
        if not complete:
            # Out of time: treat unfinished names as known, so nothing is reported on a guess.
            for n in todo:
                if hits.get(n) is None:
                    hits.pop(n, None)
                    out.add(n)
        return out

    def _doc_mentions(self, repo: Repo) -> Tuple[Set[str], Set[str]]:
        """Every --flag and ENV_NAME written in any doc-like file (checked or not)."""
        flags: Set[str] = set()
        envs: Set[str] = set()
        for rel in repo.files:
            if not rel.lower().endswith(_MENTION_EXT) or not may_read(rel.rsplit("/", 1)[-1]):
                continue
            key = repo.stat_key(rel)
            hit = self._mentions.get(rel)
            if not hit or hit[0] != key:
                text = repo.read(rel) or ""
                hit = (key, {norm_flag(m) for m in FLAG_LITERAL.findall(text)}, set(ENV_TOKEN.findall(text)))
                self._mentions[rel] = hit
            flags |= hit[1]
            envs |= hit[2]
        return flags, envs

    # ------------------------------------------------------------ diff
    def scan_changes(self, rev: str = "HEAD", **kw: Any) -> Tuple[ScanResult, List[Finding], Optional[str]]:
        """(current scan reduced to new findings, findings the changes resolved, problem).

        "New" means: present in the working tree, absent when the files that
        differ from ``rev`` are replaced by their content at ``rev``.
        """
        started = time.monotonic()
        self.repo.refresh()
        overlay = self.repo.changed_vs(rev)
        if overlay is None:
            current = self.scan(refresh=False, **kw)
            return current, [], "not a git repository (or git failed); showing every finding"
        if not overlay:
            current = self.scan(refresh=False, **kw)
            current.findings = []
            current.notes.append(f"No files differ from {rev}.")
            return current, [], None
        baseline = self.scan(overlay=overlay, refresh=False, **kw)
        current = self.scan(refresh=False, before=None if baseline.incomplete else baseline.index, **kw)
        current.elapsed_ms = int((time.monotonic() - started) * 1000)   # both scans, not only the second
        if baseline.incomplete or current.incomplete:
            current.findings = []
            current.incomplete = True
            return current, [], None
        before = baseline.ids()
        after = current.ids()
        resolved = [f for f in baseline.findings if f.id not in after]
        current.findings = [f for f in current.findings if f.id not in before]
        current.notes.append(
            f"Compared with {rev}: {len(overlay)} changed file(s), {len(before & after)} finding(s) already present before the change are not shown."
        )
        return current, resolved, None


# ---------------------------------------------------------------- explain
def _context(repo: Repo, rel: str, line: int, radius: int = 2) -> List[str]:
    text = repo.read(rel) if rel else None
    if not text or line <= 0:
        return []
    lines = text.splitlines()
    lo, hi = max(1, line - radius), min(len(lines), line + radius)
    return [f"{'>' if i == line else ' '} {i:>5} | {lines[i - 1]}" for i in range(lo, hi + 1)]


def explain(scanner: Scanner, result: ScanResult, finding_id: str) -> Optional[Dict[str, Any]]:
    f = result.by_id(finding_id.strip())
    if f is None:
        return None
    return explain_finding(scanner, f)


def explain_finding(scanner: Scanner, f: Finding) -> Dict[str, Any]:
    d = f.full()
    d["doc_context"] = _context(scanner.repo, f.doc_file, f.doc_line)
    if f.code_file and f.code_line:
        d["code_context"] = _context(scanner.repo, f.code_file, f.code_line)
    d["how_to_silence"] = (
        "If the docs are right as written, add the name to `ignore_names` or the doc path to "
        "`ignore_paths` in this plugin's settings."
    )
    return d


def apply_ignores(result: ScanResult, ignore_names: Iterable[str] = (), ignore_paths: Iterable[str] = ()) -> ScanResult:
    """Drop findings the user silenced by name or by doc-path glob."""
    import fnmatch

    names = {str(n).strip().lstrip("-").lower() for n in ignore_names if str(n).strip()}
    globs = [str(g).strip() for g in ignore_paths if str(g).strip()]
    if not names and not globs:
        return result
    kept: List[Finding] = []
    for f in result.findings:
        if f.name.lstrip("-").lower() in names or any(fnmatch.fnmatch(f.doc_file, g) for g in globs):
            result.suppressed["ignored-by-config"] = result.suppressed.get("ignored-by-config", 0) + 1
            continue
        kept.append(f)
    result.findings = kept
    return result


__all__ = [
    "Scanner", "explain", "explain_finding", "apply_ignores", "resolve_checks", "find_root", "DEFAULT_CHECKS", "OPT_IN_CHECKS", "CHECKS",
]

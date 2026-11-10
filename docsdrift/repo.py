"""Repository view: which files exist, which are docs, and their text.

Everything the checks read goes through :class:`Repo`, so a scan can run
against the working tree or against "the working tree with some files
replaced by their content at a git revision" (the overlay used for
"what did my uncommitted changes break?").
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple

DOC_EXTENSIONS = (".md", ".mdx", ".markdown")

# Directories never walked when git is not available.
WALK_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".nuxt",
    "site-packages", ".idea", ".gradle", "bower_components", "Pods", ".terraform",
    ".cache", "dist", "build", "target", "out", "coverage", ".eggs",
}

# Doc files under these directory names are fixtures, vendored copies,
# history or translations: their claims are not about the current code.
DOC_SKIP_DIRS = {
    "node_modules", "vendor", "vendors", "third_party", "third-party", "thirdparty",
    "external", "testdata", "fixtures", "__fixtures__", "fixture", "tests", "test",
    "__tests__", "spec", "specs", "e2e", "snapshots", "__snapshots__",
    "versioned_docs", "i18n", "translations", "locale", "locales", "l10n",
    "changelog", "changelogs", "changes", "releases", "release-notes", "release_notes",
    "blog", "_posts", "news", "archive", "archived", "deprecated", "legacy", "attic",
    "rfcs", "rfc", "adr", "adrs", "proposals", "design-docs", "templates", "template",
    "cookiecutter", "skeleton", "scaffold", "scaffolds", "boilerplate",
}

DOC_SKIP_NAME = re.compile(
    r"^(change(s|log)|history|news|release[-_ ]?notes?|releases?|migrat\w*|upgrad\w*|"
    r"roadmap|todo|authors|contributors|code[-_]of[-_]conduct|security|license\w*|"
    r"copying|notice|thanks|backers|sponsors|pull_request_template|issue_template)"
    r"([-_.].*)?$",
    re.I,
)
# README.zh-CN.md, README_ja.md, README-pt_BR.md ... mirror the main README.
DOC_TRANSLATION_NAME = re.compile(r"^.+[._-]([a-z]{2}|[a-z]{2}[-_][A-Za-z]{2,4})$")
_LOCALE_WORDS = {
    "zh", "cn", "ja", "jp", "ko", "kr", "fr", "de", "es", "pt", "ru", "it", "tr", "vi",
    "id", "ar", "hi", "pl", "nl", "uk", "fa", "he", "th", "bn", "br", "tw",
}

MAX_TEXT_BYTES = 2_000_000
MAX_FILES = 40_000

# Names that are never opened. Rule 11 of the Hermes catalog: a plugin does not
# read ``.env`` files or credential stores.
_NEVER_READ = re.compile(
    r"^(\.env(\..*)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa.*|id_ed25519.*|"
    r"auth\.json|credentials(\.json)?|\.netrc|\.npmrc|\.pypirc)$",
    re.I,
)
_ENV_EXAMPLE = re.compile(r"^\.env\.(example|sample|template|dist|defaults)$", re.I)

_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".pdf", ".zip",
    ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".class", ".so", ".dll",
    ".dylib", ".exe", ".bin", ".o", ".a", ".lib", ".woff", ".woff2", ".ttf", ".otf",
    ".eot", ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav", ".ogg", ".flac", ".pyc",
    ".pyo", ".wasm", ".db", ".sqlite", ".sqlite3", ".parquet", ".npy", ".npz", ".pkl",
    ".pt", ".onnx", ".h5", ".psd", ".ai", ".sketch", ".fig", ".svgz", ".lock",
}
_LOCK_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock",
    "cargo.lock", "go.sum", "composer.lock", "gemfile.lock", "bun.lockb", "flake.lock",
}


def may_read(name: str) -> bool:
    """False for files the scanner must never open (secrets, ``.env``)."""
    if _ENV_EXAMPLE.match(name):
        return True
    return not _NEVER_READ.match(name)


def is_doc_path(rel: str) -> bool:
    return rel.lower().endswith(DOC_EXTENSIONS)


def doc_is_checked(rel: str) -> bool:
    """True when claims in this doc file should be checked against the code."""
    p = PurePosixPath(rel)
    parts = [x.lower() for x in p.parts[:-1]]
    if any(x in DOC_SKIP_DIRS for x in parts):
        return False
    if parts and parts[0] == ".github":
        return p.stem.lower() in ("contributing", "development")
    stem = p.stem
    if DOC_SKIP_NAME.match(stem):
        return False
    m = DOC_TRANSLATION_NAME.match(stem)
    if m:
        tag = re.split(r"[-_]", m.group(1).lower())[0]
        if tag in _LOCALE_WORDS:
            return False
    return True


def find_root(start: str, strict: bool = False) -> Optional[str]:
    """Nearest ancestor that looks like a project root (``.git`` first).

    With ``strict`` the answer is None when no ancestor has ``.git`` or a
    project file, so callers never scan an arbitrary directory by accident.
    """
    start = os.path.abspath(start)
    while not os.path.exists(start):
        parent = os.path.dirname(start)
        if parent == start:
            return None if strict else start
        start = parent
    if os.path.isfile(start):
        start = os.path.dirname(start)
    cur = start
    fallback = None
    markers = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "setup.py", "Makefile")
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        if fallback is None and any(os.path.exists(os.path.join(cur, m)) for m in markers):
            fallback = cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return fallback or (None if strict else start)
        cur = parent


def _git(root: str, args: List[str], timeout: float = 20.0) -> Optional[bytes]:
    try:
        proc = subprocess.run(
            ["git", "-C", root] + args,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


class Repo:
    """Working tree of one project, with an optional content overlay."""

    def __init__(self, root: str, use_git: bool = True):
        self.root = os.path.abspath(root)
        self.use_git = use_git
        self.git_ok = False
        self.files: List[str] = []
        self.overlay: Dict[str, Optional[str]] = {}
        self._text_cache: Dict[str, Tuple[Tuple[float, int], Optional[str]]] = {}
        self._fileset: Set[str] = set()
        self._dirset: Set[str] = set()
        self._lower: Dict[str, str] = {}
        self.truncated = False
        self.refresh()

    # -- listing ---------------------------------------------------------
    def refresh(self) -> None:
        files: Optional[List[str]] = None
        if self.use_git and os.path.exists(os.path.join(self.root, ".git")):
            out = _git(self.root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
            if out is not None:
                files = [f for f in out.decode("utf-8", "replace").split("\0") if f]
                self.git_ok = True
        if files is None:
            self.git_ok = False
            files = self._walk()
        if self.git_ok:
            # ls-files lists tracked files deleted from the working tree too.
            root = self.root
            files = [f for f in files if os.path.lexists(os.path.join(root, f))] if len(files) <= MAX_FILES else files
        if len(files) > MAX_FILES:
            files = files[:MAX_FILES]
            self.truncated = True
        self._set_files(files)

    def _walk(self) -> List[str]:
        out: List[str] = []
        root = self.root
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in WALK_SKIP_DIRS]
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            for fn in filenames:
                out.append(fn if rel_dir == "." else rel_dir + "/" + fn)
            if len(out) > MAX_FILES:
                break
        out.sort()
        return out

    def _set_files(self, files: Iterable[str]) -> None:
        self.files = sorted(set(files))
        self._fileset = set(self.files)
        dirs: Set[str] = set()
        for f in self.files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        self._dirset = dirs
        lower: Dict[str, str] = {}
        for p in list(self._fileset) + list(dirs):
            lower.setdefault(p.lower(), p)
        self._lower = lower

    def with_overlay(self, overlay: Dict[str, Optional[str]]) -> "Repo":
        """A view where ``overlay[path]`` replaces the file's text (None = absent)."""
        other = Repo.__new__(Repo)
        other.root = self.root
        other.use_git = self.use_git
        other.git_ok = self.git_ok
        other.overlay = dict(overlay)
        other._text_cache = {}
        other.truncated = self.truncated
        files = set(self.files)
        for path, text in overlay.items():
            if text is None:
                files.discard(path)
            else:
                files.add(path)
        other._set_files(files)
        return other

    # -- queries ---------------------------------------------------------
    def has_file(self, rel: str) -> bool:
        return rel in self._fileset

    def has_dir(self, rel: str) -> bool:
        return rel in self._dirset or rel in ("", ".")

    def exists(self, rel: str) -> bool:
        return rel in self._fileset or rel in self._dirset or rel in ("", ".")

    def case_variant(self, rel: str) -> Optional[str]:
        """An existing path that differs from ``rel`` only by letter case."""
        hit = self._lower.get(rel.lower())
        return hit if hit and hit != rel else None

    def on_disk(self, rel: str) -> bool:
        """Exists in the working tree even if git ignores it (generated files)."""
        if rel in self.overlay:
            return self.overlay[rel] is not None
        return os.path.exists(os.path.join(self.root, rel))

    def doc_files(self) -> List[str]:
        return [f for f in self.files if is_doc_path(f) and doc_is_checked(f)]

    def all_doc_files(self) -> List[str]:
        return [f for f in self.files if is_doc_path(f)]

    def code_files(self) -> List[str]:
        out = []
        for f in self.files:
            name = f.rsplit("/", 1)[-1]
            low = name.lower()
            if is_doc_path(f) or low.endswith((".rst", ".txt", ".adoc")) and not low.startswith(("cmakelists", "requirements")):
                continue
            ext = os.path.splitext(low)[1]
            if ext in _BINARY_EXT or low in _LOCK_NAMES or low.endswith((".min.js", ".min.css", ".map")):
                continue
            if not may_read(name):
                continue
            out.append(f)
        return out

    def stat_key(self, rel: str) -> Tuple[float, int]:
        if rel in self.overlay:
            text = self.overlay[rel]
            return (-1.0, hash(text) if text is not None else -1)
        try:
            st = os.stat(os.path.join(self.root, rel))
            return (st.st_mtime, st.st_size)
        except OSError:
            return (0.0, -1)

    def read(self, rel: str) -> Optional[str]:
        """Text of a file, or None when unreadable, binary, too large or off limits."""
        if rel in self.overlay:
            return self.overlay[rel]
        name = rel.rsplit("/", 1)[-1]
        if not may_read(name):
            return None
        path = os.path.join(self.root, rel)
        try:
            if os.path.getsize(path) > MAX_TEXT_BYTES or not os.path.isfile(path):
                return None
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return None
        if b"\0" in raw[:4096]:
            return None
        return raw.decode("utf-8", "replace")

    # -- git helpers -------------------------------------------------------
    def changed_vs(self, rev: str = "HEAD") -> Optional[Dict[str, Optional[str]]]:
        """Overlay that turns the working tree back into ``rev``.

        Maps each path that differs from ``rev`` to its text at ``rev`` (None when
        the file did not exist there). Returns None when git cannot answer.
        """
        if not self.git_ok:
            return None
        out = _git(self.root, ["status", "--porcelain", "-z", "--untracked-files=all"])
        if out is None:
            return None
        if rev != "HEAD":
            diff = _git(self.root, ["diff", "--name-only", "-z", rev])
            if diff is None:
                return None
            names = {n for n in diff.decode("utf-8", "replace").split("\0") if n}
        else:
            names = set()
        entries = out.decode("utf-8", "replace").split("\0")
        i = 0
        while i < len(entries):
            e = entries[i]
            i += 1
            if len(e) < 4:
                continue
            code, path = e[:2], e[3:]
            names.add(path)
            if code[0] in "RC" and i < len(entries):
                names.add(entries[i])
                i += 1
        overlay: Dict[str, Optional[str]] = {}
        for name in sorted(names):
            if not may_read(name.rsplit("/", 1)[-1]):
                continue
            blob = _git(self.root, ["show", f"{rev}:{name}"])
            if blob is None:
                overlay[name] = None
            elif b"\0" in blob[:4096] or len(blob) > MAX_TEXT_BYTES:
                continue
            else:
                overlay[name] = blob.decode("utf-8", "replace")
        return overlay

    def ignored(self, rel: str) -> bool:
        if not self.git_ok:
            return False
        try:
            proc = subprocess.run(
                ["git", "-C", self.root, "check-ignore", "-q", "--", rel],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

    def submodule_paths(self) -> List[str]:
        text = self.read(".gitmodules") if self.has_file(".gitmodules") else None
        if not text:
            return []
        return [m.group(1).strip() for m in re.finditer(r"^\s*path\s*=\s*(.+)$", text, re.M)]

    def origin_name(self) -> Optional[str]:
        """Repository name from ``.git/config`` (``origin`` URL basename)."""
        cfg = os.path.join(self.root, ".git", "config")
        try:
            with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return None
        m = re.search(r"url\s*=\s*\S*?[/:]([^/\s:]+?)(?:\.git)?\s*$", text, re.M)
        return m.group(1) if m else None

"""Repository view: which files exist, which are docs, and their text.

Everything the checks read goes through :class:`Repo`, so a scan can run
against the working tree or against "the working tree with some files
replaced by their content at a git revision" (the overlay used for
"what did my uncommitted changes break?").
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

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


# ---------------------------------------------------------------- git children
# The repository being checked is not trusted: its .git/config is data that someone else may
# have written. Every git child therefore gets the options and the environment below.

GIT_TIMEOUT_S = 20.0

# Variables a git child inherits. Nothing else from the parent process reaches it: no
# provider keys, no tokens, and no GIT_DIR / GIT_WORK_TREE that would aim it at another repository.
_GIT_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL")
_GIT_ENV_KEEP_WINDOWS = ("SYSTEMROOT", "TEMP", "TMP", "USERPROFILE")

# Config that makes git start a program named in the repository's own config. Options given
# with -c win over .git/config.
_GIT_OPTIONS = (
    "--no-pager",
    "-c", "core.fsmonitor=false",                 # a program run by ls-files, status and diff
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "core.untrackedCache=false",            # would be written into .git/index
    "-c", "diff.autoRefreshIndex=false",          # `git diff REV` would rewrite .git/index
    # No transport at all. In a partial clone `git cat-file` fetches a missing blob, and the
    # transport (ext::, remote.<name>.uploadpack, core.sshCommand) is a command from config.
    # GIT_NO_LAZY_FETCH stops the fetch in a git that knows the variable (2.45, and older
    # ones with the fix backported). For the others: these options, and GIT_ALLOW_PROTOCOL in
    # the environment for the protocols that are not named here.
    "-c", "protocol.allow=never",
    "-c", "protocol.ext.allow=never",
    "-c", "protocol.file.allow=never",
    "-c", "protocol.git.allow=never",
    "-c", "protocol.ssh.allow=never",
    "-c", "protocol.http.allow=never",
    "-c", "protocol.https.allow=never",
)


def _git_env(root: str) -> Dict[str, str]:
    keep = _GIT_ENV_KEEP + (_GIT_ENV_KEEP_WINDOWS if os.name == "nt" else ())
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["GIT_OPTIONAL_LOCKS"] = "0"       # `git status` must not rewrite .git/index in the background
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_NO_LAZY_FETCH"] = "1"
    # A list of allowed protocols with no name in it. It wins over every protocol.<name>.allow
    # in the config, also for a protocol _GIT_OPTIONS does not name (ftp, a remote helper).
    env["GIT_ALLOW_PROTOCOL"] = ":"
    # core.worktree in .git/config would make git list and compare another directory.
    env["GIT_WORK_TREE"] = root
    # Only <root>/.git is used. A repository in a directory above is not looked for.
    env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(root)
    return env


def _git_argv(root: str, args: Sequence[str], options: Sequence[str] = ()) -> List[str]:
    return ["git", *_GIT_OPTIONS, *options, "-C", root, *args]


def _within(path: str, base: str) -> bool:
    """True when ``path`` is ``base`` or below it. Both are absolute and normalised."""
    path, base = os.path.normcase(path), os.path.normcase(base)
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


_WINDOWS_DEVICES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"] + [f"{n}{i}" for n in ("com", "lpt") for i in range(1, 10)]
)


def _refused_names(parts: Iterable[str]) -> bool:
    """True when a path with these components is refused whatever is on disk.

    ``.git`` at any depth, in any letter case (a case-insensitive file system opens ``.GIT``).
    On Windows also the spellings that open a file under another name: ``name:stream``, a
    trailing dot or space, and the device names.
    """
    windows = os.name == "nt"
    for part in parts:
        if part.casefold() == ".git":
            return True
        if windows and (":" in part or part != part.rstrip(". ")
                        or part.split(".", 1)[0].casefold() in _WINDOWS_DEVICES):
            return True
    return False


def _plain_name(rel: str) -> bool:
    """A name from a listing that stays inside the repository and outside ``.git``."""
    parts = rel.split("/")
    if "" in parts or "." in parts or ".." in parts:
        return False
    return not _refused_names(parts) and not (os.name == "nt" and "\\" in rel)


def _is_link(st: os.stat_result) -> bool:
    """A symbolic link, or on Windows any reparse point (junctions are not symbolic links there)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class Repo:
    """Working tree of one project, with an optional content overlay."""

    def __init__(self, root: str, use_git: bool = True, deadline: Optional[float] = None):
        self.root = os.path.abspath(root)
        self._real_root = os.path.realpath(self.root)
        self._dir_ok: Dict[str, bool] = {}
        self._git_dir_stat: Optional[os.stat_result] = None
        self.use_git = use_git
        self.git_ok = False
        # time.monotonic() value after which no git child is started and the directory walk
        # stops; ``out_of_time`` says that this happened since the last refresh().
        self.deadline = deadline
        self.out_of_time = False
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
        self.out_of_time = False
        self._dir_ok.clear()
        try:
            self._git_dir_stat = os.stat(os.path.join(self._real_root, ".git"))
        except OSError:
            self._git_dir_stat = None
        files: Optional[List[str]] = None
        if self.use_git and os.path.exists(os.path.join(self.root, ".git")):
            out = self._git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
            if out is not None:
                files = [f for f in out.decode("utf-8", "replace").split("\0") if f]
                self.git_ok = True
        if files is None and not self.out_of_time:
            self.git_ok = False
            files = self._walk()
        if files is None or self.out_of_time:
            return                      # the listing is not known: the caller reports nothing
        if self.git_ok:
            # The index is data too: a name in it is used only when it stays in the repository.
            files = [f for f in files if _plain_name(f)]
            # ls-files lists tracked files deleted from the working tree too.
            root = self.root
            files = [f for f in files if os.path.lexists(os.path.join(root, f))] if len(files) <= MAX_FILES else files
        if len(files) > MAX_FILES:
            files = files[:MAX_FILES]
            self.truncated = True
        if self.git_ok and os.name == "nt":
            files = self._without_linked_dirs(files)
        self._set_files(files)

    def _without_linked_dirs(self, files: List[str]) -> List[str]:
        """Drop the files that git listed below a junction.

        Git for Windows walks into a junction as into a directory, so the names of the files
        behind one, which can be anywhere on the machine, come back as untracked files. Git
        does not walk into a symbolic link, on any system.
        """
        root = self.root
        linked: Dict[str, bool] = {"": False}

        def is_linked(rel_dir: str) -> bool:
            hit = linked.get(rel_dir)
            if hit is None:
                hit = is_linked(rel_dir.rpartition("/")[0])
                if not hit:
                    try:
                        hit = _is_link(os.lstat(os.path.join(root, rel_dir)))
                    except OSError:
                        hit = True
                linked[rel_dir] = hit
            return hit

        return [f for f in files if not is_linked(f.rpartition("/")[0])]

    def _walk(self) -> List[str]:
        out: List[str] = []
        root = self.root
        for dirpath, dirnames, filenames in os.walk(root):
            if self.deadline is not None and time.monotonic() > self.deadline:
                self.out_of_time = True
                break
            # A linked directory is not entered (os.walk of Python 3.11 enters a junction), and
            # no ``.git`` in any letter case.
            dirnames[:] = [d for d in dirnames
                           if d not in WALK_SKIP_DIRS and d.casefold() != ".git"
                           and not self._linked(os.path.join(dirpath, d))]
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            for fn in filenames:
                out.append(fn if rel_dir == "." else rel_dir + "/" + fn)
            if len(out) > MAX_FILES:
                break
        out.sort()
        return out

    @staticmethod
    def _linked(path: str) -> bool:
        try:
            return _is_link(os.lstat(path))
        except OSError:
            return True

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
        other._real_root = self._real_root
        other._dir_ok = self._dir_ok
        other._git_dir_stat = self._git_dir_stat
        other.deadline = self.deadline
        other.out_of_time = self.out_of_time
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

    def _real(self, rel: str) -> Optional[Tuple[str, os.stat_result]]:
        """Where ``rel`` is on disk and its stat, or None when it is missing or off limits.

        Nothing outside the repository is opened or examined, and nothing in a ``.git``
        directory. A symbolic link (on Windows, a junction too) is followed only when its
        target is inside the repository, is not in ``.git`` and does not have one of the names
        that are never read; the same holds for a path with a linked directory above it.
        ``../x`` and absolute paths are refused.
        """
        root = self.root
        try:
            path = os.path.normpath(os.path.join(root, rel))
            if not _within(path, root):
                return None
            tail = path[len(root):]
            if _refused_names(p for p in tail.split(os.sep) if p):
                return None
            # A Windows short name (GIT~1, ENV~1) is another spelling of a longer one: such a
            # path is resolved and judged by the name it resolves to, like a link.
            alias = os.name == "nt" and "~" in tail
            parent = os.path.dirname(path) if path != root else root
            ok = self._dir_ok.get(parent)
            if ok is None:
                real_parent = os.path.realpath(parent)
                plain = os.path.normpath(os.path.join(self._real_root, os.path.relpath(parent, root)))
                # No link on the way down: nothing to decide. Otherwise the directory it leads to counts.
                ok = os.path.normcase(real_parent) == os.path.normcase(plain) or self._allowed(real_parent)
                self._dir_ok[parent] = ok
            if not ok:
                return None
            st = os.lstat(path)
            if alias or _is_link(st):
                real = os.path.realpath(path)
                if not self._allowed(real) or not may_read(os.path.basename(real)):
                    return None
                return real, os.stat(real)
            return path, st
        except (OSError, ValueError):
            return None

    def _allowed(self, real: str) -> bool:
        """A resolved link target: inside the repository and not inside a ``.git`` directory."""
        base = self._real_root
        if not _within(real, base):
            return False
        if _refused_names(p for p in real[len(base):].split(os.sep) if p):
            return False
        # By identity as well as by name: a file system can know the repository's .git under a
        # name that no comparison of strings finds.
        git_dir = self._git_dir_stat
        cur = real
        while git_dir is not None and len(cur) > len(base):
            try:
                if os.path.samestat(os.stat(cur), git_dir):
                    return False
            except OSError:
                pass
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        return True

    def on_disk(self, rel: str) -> bool:
        """Exists in the working tree even if git ignores it (generated files).

        For a file with a name that is never read (``.env``) this is the one question asked.
        """
        if rel in self.overlay:
            return self.overlay[rel] is not None
        return self._real(rel) is not None

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
        if not may_read(rel.rsplit("/", 1)[-1]):
            return (0.0, -1)
        hit = self._real(rel)
        if hit is None:
            return (0.0, -1)
        return (hit[1].st_mtime, hit[1].st_size)

    def read(self, rel: str) -> Optional[str]:
        """Text of a file, or None when unreadable, binary, too large or off limits."""
        if rel in self.overlay:
            return self.overlay[rel]
        name = rel.rsplit("/", 1)[-1]
        if not may_read(name):
            return None
        hit = self._real(rel)
        if hit is None:
            return None
        path, st = hit
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_TEXT_BYTES:
            return None
        try:
            with open(path, "rb") as fh:
                # Asking for the size the stat gave keeps the buffer small; a file that grew
                # in between is read on, up to the limit and no further.
                raw = fh.read(st.st_size + 1)
                if len(raw) > st.st_size:
                    raw += fh.read(MAX_TEXT_BYTES + 1 - len(raw))
        except OSError:
            return None
        if len(raw) > MAX_TEXT_BYTES:
            return None
        if b"\0" in raw[:4096]:
            return None
        return raw.decode("utf-8", "replace")

    # -- git helpers -------------------------------------------------------
    def _git(self, args: Sequence[str], options: Sequence[str] = (), data: Optional[bytes] = None,
             ok: Tuple[int, ...] = (0,)) -> Optional[bytes]:
        """Output of one git child, or None when it failed or there was no time left for it."""
        timeout = GIT_TIMEOUT_S
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left <= 0:
                self.out_of_time = True
                return None
            timeout = min(timeout, left)
        feed = {"stdin": subprocess.DEVNULL} if data is None else {"input": data}
        try:
            proc = subprocess.run(
                _git_argv(self.root, args, options),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False, env=_git_env(self.root), **feed,
            )
        except subprocess.TimeoutExpired:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                self.out_of_time = True
            return None
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode not in ok:
            return None
        return proc.stdout

    def _filters_off(self) -> Optional[List[str]]:
        """Options that turn off every clean, smudge and process filter, or None when unknown.

        ``git status`` and ``git diff`` hash the working-tree files that look modified, and to
        do that they run the file's clean filter: a shell command from git config, chosen by
        ``.gitattributes``. With the filters off such a file is hashed as it is on disk, so a
        file kept in Git LFS can be listed as changed when it is not; nothing else changes.
        """
        out = self._git(["config", "-z", "--name-only", "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"],
                        ok=(0, 1))                 # 1: no such key
        if out is None:
            return None
        names = set()
        for key in out.decode("utf-8", "replace").split("\0"):
            if key:
                names.add(key[len("filter."):key.rindex(".")])
        options: List[str] = []
        for name in sorted(names):
            if not name or any(c in name for c in "=\n\ufffd"):
                return None                        # cannot be named in a -c option: do not run git at all
            for var, value in (("clean", ""), ("smudge", ""), ("process", ""), ("required", "false")):
                options += ["-c", f"filter.{name}.{var}={value}"]
        return options

    def changed_vs(self, rev: str = "HEAD") -> Optional[Dict[str, Optional[str]]]:
        """Overlay that turns the working tree back into ``rev``.

        Maps each path that differs from ``rev`` to its text at ``rev`` (None when
        the file did not exist there). Returns None when git cannot answer.
        """
        if not self.git_ok or not rev or rev.startswith("-"):
            return None                            # "-x" would be read by git as an option
        quiet = self._filters_off()
        if quiet is None:
            return None
        out = self._git(["status", "--porcelain", "-z", "--untracked-files=all", "--ignore-submodules=all"], quiet)
        if out is None:
            return None
        if rev != "HEAD":
            # ``rev`` against the index; `status` above has the index against the working tree.
            # `git diff REV` would do both in one call, but it either writes the refreshed
            # index back to .git/index or, told not to, lists every file whose time changed.
            diff = self._git(["diff", "--cached", "--name-only", "-z", "--no-ext-diff", "--no-textconv",
                              "--ignore-submodules=all", rev], quiet)
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
            # cat-file and not show: for a name that is a submodule at ``rev``, `git show` prints
            # a commit, and log.showSignature with gpg.program from the config starts a program.
            blob = self._git(["cat-file", "blob", f"{rev}:{name}"])
            if self.out_of_time:
                return None
            if blob is None:
                overlay[name] = None
            elif b"\0" in blob[:4096] or len(blob) > MAX_TEXT_BYTES:
                continue
            else:
                overlay[name] = blob.decode("utf-8", "replace")
        return overlay

    def ignored_many(self, rels: Sequence[str]) -> Optional[Set[str]]:
        """The subset of ``rels`` that git ignores, asked in one call. None when git could not answer."""
        if not rels or not self.git_ok:
            return set()
        out = self._git(["check-ignore", "-z", "--stdin"],
                        data=b"".join(r.encode("utf-8") + b"\x00" for r in rels),
                        ok=(0, 1))                 # 1 means "none of them is ignored"
        if out is None:
            return None
        return {p for p in out.decode("utf-8", "replace").split("\x00") if p}

    def submodule_paths(self) -> List[str]:
        text = self.read(".gitmodules") if self.has_file(".gitmodules") else None
        if not text:
            return []
        return [m.group(1).strip() for m in re.finditer(r"^[ \t]*path[ \t]*=[ \t]*(.+)$", text, re.M)]

    def origin_name(self) -> Optional[str]:
        """Repository name from ``.git/config`` (``origin`` URL basename)."""
        git_dir = os.path.join(self.root, ".git")
        cfg = os.path.join(git_dir, "config")
        try:
            if _is_link(os.lstat(git_dir)) or not stat.S_ISREG(os.lstat(cfg).st_mode):
                return None                        # only the repository's own config file is read
            with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(MAX_TEXT_BYTES)
        except OSError:
            return None
        m = re.search(r"^[ \t]*url[ \t]*=[ \t]*\S*[/:]([^/\s:@]+?)(?:\.git)?[ \t]*$", text, re.M)
        return m.group(1) if m else None

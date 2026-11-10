"""Remove machine-specific text from demo transcripts before they are written.

The demo drivers print paths inside a temporary directory. On most machines that
path contains the account name (``C:\\Users\\<name>\\AppData\\Local\\Temp``,
``/Users/<name>/...``). ``scrub`` replaces the temporary directory with
``%TEMP%`` and the home directory with ``~``, in every spelling a transcript
can contain: backslashes, forward slashes, and backslashes doubled once or more
by JSON encoding. It also replaces any secret value it is given.

``install`` wraps ``sys.stdout`` so that everything a driver prints goes through
``scrub``, one line at a time.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

_SEP = r"(?:\\+|/+)"


def _path_pattern(path: str):
    """A pattern for ``path`` with any run of slashes or backslashes between its parts."""
    path = path.strip()
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return None
    drive = re.match(r"^([A-Za-z]):$", parts[0])
    if drive:
        letter = drive.group(1)
        if len(parts) < 2:
            return None
        # C:\Users\x, C:/Users/x, /c/Users/x (Git Bash), /mnt/c/Users/x (WSL)
        head = r"(?:%s:|(?<![\w.:-])/(?:mnt/)?%s(?=[\\/]))" % (letter, letter)
        return re.compile(head + _SEP + _SEP.join(re.escape(p) for p in parts[1:]) + r"(?![\w.-])", re.I)
    if not path.startswith(("/", "\\")) or len(parts) < 1:
        return None
    if len(parts) == 1 and parts[0].lower() in ("tmp", "home", "root", "users", "var"):
        # "/tmp" alone says nothing about the machine and would match inside other paths
        return None
    return re.compile(r"(?<![\w.:-])" + _SEP + _SEP.join(re.escape(p) for p in parts) + r"(?![\w.-])")


def _candidates():
    temp, home = [], []
    for value in (tempfile.gettempdir(), os.environ.get("TEMP"), os.environ.get("TMP"), os.environ.get("TMPDIR")):
        if value:
            temp.append(value)
            temp.append(os.path.realpath(value))
    for value in (os.path.expanduser("~"), os.environ.get("USERPROFILE"), os.environ.get("HOME")):
        if value and value not in ("~", "/"):
            home.append(value)
            home.append(os.path.realpath(value))
    return temp, home


def scrub(text: str, secrets=(), temp_dirs=None, home_dirs=None, user=None) -> str:
    """Return ``text`` without temp-directory and home-directory prefixes and without ``secrets``."""
    if temp_dirs is None or home_dirs is None:
        found_temp, found_home = _candidates()
        temp_dirs = found_temp if temp_dirs is None else temp_dirs
        home_dirs = found_home if home_dirs is None else home_dirs
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "<redacted>")
    rules = [(p, "%TEMP%") for p in temp_dirs] + [(p, "~") for p in home_dirs]
    # longest first, so the temp directory wins over the home directory that contains it
    rules.sort(key=lambda r: -len(r[0]))
    seen = set()
    for path, token in rules:
        if path in seen:
            continue
        seen.add(path)
        pattern = _path_pattern(path)
        if pattern is not None:
            text = pattern.sub(lambda _m, t=token: t, text)
    if user is None:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if user and len(user) >= 3:
        # what is left of the account name after the rules above, as a path part
        text = re.sub(r"(?i)((?:Users|home)" + _SEP + r")" + re.escape(user) + r"(?![\w.-])",
                      lambda m: m.group(1) + "<user>", text)
    return text


class ScrubbedStream:
    """A text stream that passes complete lines through ``scrub`` before writing them."""

    def __init__(self, stream, secrets=(), **kwargs):
        self._stream = stream
        self._secrets = tuple(secrets)
        self._kwargs = kwargs
        self._pending = ""

    def write(self, text: str) -> int:
        self._pending += text
        if "\n" in self._pending:
            done, self._pending = self._pending.rsplit("\n", 1)
            self._stream.write(scrub(done, self._secrets, **self._kwargs) + "\n")
            self._stream.flush()
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self._stream.write(scrub(self._pending, self._secrets, **self._kwargs))
            self._pending = ""
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install(secrets=()) -> None:
    """Route ``sys.stdout`` through ``scrub``. Safe to call twice."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if not isinstance(sys.stdout, ScrubbedStream):
        sys.stdout = ScrubbedStream(sys.stdout, secrets)

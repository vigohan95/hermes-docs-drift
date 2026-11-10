"""Shared fixtures: small throw-away repositories built from a dict of files."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HAVE_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAVE_GIT, reason="git is not installed")


def write_files(root: str, files: dict) -> None:
    for rel, text in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if text is None:
            if os.path.exists(path):
                os.remove(path)
            continue
        body = textwrap.dedent(text)
        if body.startswith("\n"):
            body = body[1:]
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)


def git(root: str, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, capture_output=True, text=True, check=True,
    )
    return out.stdout


@pytest.fixture
def make_repo(tmp_path):
    """make_repo(files, git=True, name="proj") -> absolute path of a new project."""
    counter = {"n": 0}

    def _make(files: dict, use_git: bool = True, name: str = "") -> str:
        counter["n"] += 1
        root = tmp_path / (name or f"proj{counter['n']}")
        root.mkdir()
        write_files(str(root), files)
        if use_git:
            if not HAVE_GIT:
                pytest.skip("git is not installed")
            git(str(root), "init", "-q", "-b", "main")
            git(str(root), "add", "-A")
            git(str(root), "commit", "-q", "-m", "init")
        return str(root)

    return _make


NOTESYNC = {
    "pyproject.toml": """
        [project]
        name = "notesync"
        version = "0.3.0"

        [project.scripts]
        notesync = "notesync.cli:main"
        """,
    "notesync/__init__.py": "",
    "notesync/cli.py": """
        import argparse
        import os


        def build_parser():
            parser = argparse.ArgumentParser(prog="notesync")
            parser.add_argument("source")
            parser.add_argument("--output-dir", default="./out", help="where the copies go")
            parser.add_argument("--timeout", type=int, default=30, help="seconds to wait")
            parser.add_argument("--dry-run", action="store_true")
            return parser


        def main(argv=None):
            args = build_parser().parse_args(argv)
            token = os.environ.get("NOTESYNC_TOKEN", "")
            return 0 if token or args.dry_run else 1
        """,
    "Makefile": ".PHONY: test\n\ntest:\n\tpython -m pytest -q\n",
    "README.md": """
        # notesync

        ## Usage

        ```sh
        notesync ./notes --output-dir ./backup
        notesync ./notes --dry-run
        ```

        ## Options

        | Option | Default | Meaning |
        | --- | --- | --- |
        | `--output-dir` | `./out` | where the copies go |
        | `--timeout` | `30` | seconds to wait for a locked file |
        | `--dry-run` | off | print what would be copied |

        Set `NOTESYNC_TOKEN` to enable the remote upload.

        More in [the configuration guide](docs/configuration.md).

        ## Development

        ```sh
        make test
        ```
        """,
    "docs/configuration.md": """
        # Configuration

        - `NOTESYNC_TOKEN`: token for the remote upload.

        To write the copies somewhere else, pass `--output-dir`:

        ```sh
        notesync ./notes --output-dir /mnt/backup/notes
        ```
        """,
}


def _clean(text: str) -> str:
    body = textwrap.dedent(text)
    return body[1:] if body.startswith(chr(10)) else body


# dedented once here, so tests can .replace() whole lines without leaving stray indentation
NOTESYNC = {rel: _clean(text) for rel, text in NOTESYNC.items()}


@pytest.fixture
def notesync(make_repo):
    return make_repo(dict(NOTESYNC), name="notesync")


def edit(root: str, rel: str, old: str, new: str) -> None:
    path = os.path.join(root, *rel.split("/"))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert old in text, f"{old!r} not in {rel}"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.replace(old, new))


def by_check(result, check: str):
    return [f for f in result.findings if f.check == check]

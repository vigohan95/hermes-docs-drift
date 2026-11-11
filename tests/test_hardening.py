"""A hostile repository: config that runs programs, links that lead out, lines that stall a pattern.

The agent edits whatever repository it is pointed at, so everything in it is untrusted input:
``.git/config`` and ``.gitattributes`` (git runs the programs they name), symbolic links (a tracked
doc can point at a file outside the repository), and doc lines written to make a pattern slow.
"""

import itertools
import json
import os
import random
import re
import subprocess
import threading
import time

import pytest

from conftest import NOTESYNC, git, needs_git, write_files
from docsdrift import checks as checks_mod
from docsdrift import docs as docs_mod
from docsdrift import hermes_plugin as hp
from docsdrift import repo as repo_mod
from docsdrift.docs import code_spans, heading_text, parse_markdown, table_columns
from docsdrift.repo import Repo
from docsdrift.scan import Scanner
from test_plugin import FakeCtx, cli_path, patch_result

ENV_ALLOWED = {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
               "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "GIT_NO_LAZY_FETCH",
               "GIT_ALLOW_PROTOCOL", "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES"}


def modify(root, rel, extra="\nOne more line.\n"):
    with open(os.path.join(root, *rel.split("/")), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(extra)


def record_git(monkeypatch):
    """Record argv, env and timeout of every child the plugin starts; the children still run."""
    calls = []
    real = subprocess.run

    def run(argv, **kw):
        calls.append({"argv": list(argv), "env": kw.get("env"), "timeout": kw.get("timeout")})
        return real(argv, **kw)

    monkeypatch.setattr(repo_mod.subprocess, "run", run)
    return calls


# ------------------------------------------------------------------ git children
@needs_git
def test_every_git_child_gets_the_overrides_and_a_minimal_environment(make_repo, monkeypatch, tmp_path):
    root = make_repo(dict(NOTESYNC))
    modify(root, "README.md")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-canary-not-for-git")
    monkeypatch.setenv("GIT_DIR", str(elsewhere))               # would aim git at another repository
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(elsewhere / "gitconfig"))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "false")
    calls = record_git(monkeypatch)

    repo = Repo(root)
    assert repo.git_ok and repo.has_file("README.md") and repo.has_file("notesync/cli.py")
    assert set(repo.changed_vs("HEAD")) == {"README.md"}
    assert set(repo.changed_vs("HEAD~0")) == {"README.md"}
    assert repo.ignored_many(["README.md", "nope.txt"]) == set()

    subcommands = set()
    for call in calls:
        argv, env = call["argv"], call["env"]
        assert argv[0] == "git"
        head = argv[1:argv.index("-C")]
        assert head[0] == "--no-pager"
        options = [head[i + 1] for i in range(1, len(head) - 1, 2) if head[i] == "-c"]
        assert len(options) * 2 + 1 == len(head)                # nothing but --no-pager and -c pairs
        for wanted in ("core.fsmonitor=false", f"core.hooksPath={os.devnull}", "core.untrackedCache=false",
                       "diff.autoRefreshIndex=false", "protocol.allow=never", "protocol.ext.allow=never"):
            assert wanted in options, (wanted, argv)
        assert argv[argv.index("-C") + 1] == os.path.abspath(root)
        subcommands.add(argv[argv.index("-C") + 2])
        assert env is not None and set(env) <= ENV_ALLOWED, sorted(set(env) - ENV_ALLOWED)
        assert (env["GIT_OPTIONAL_LOCKS"], env["GIT_TERMINAL_PROMPT"], env["GIT_NO_LAZY_FETCH"]) == ("0", "0", "1")
        assert env["GIT_ALLOW_PROTOCOL"] == ":"                 # a list of allowed protocols with nothing in it
        assert env["GIT_WORK_TREE"] == os.path.abspath(root)    # not the inherited one
        assert env["GIT_CEILING_DIRECTORIES"] == os.path.dirname(os.path.abspath(root))
        assert "PATH" in env
        assert "sk-canary-not-for-git" not in json.dumps(env)
        assert call["timeout"] is not None and call["timeout"] <= repo_mod.GIT_TIMEOUT_S
    assert subcommands == {"ls-files", "config", "status", "diff", "cat-file", "check-ignore"}


def _marker_repo(make_repo, files=None):
    root = make_repo(files or dict(NOTESYNC))
    return root, os.path.join(root, "it-ran")


@needs_git
def test_fsmonitor_named_in_the_repository_config_is_not_run(make_repo):
    root, marker = _marker_repo(make_repo)
    git(root, "config", "core.fsmonitor", "touch it-ran; true")
    git(root, "status", "--porcelain")                          # what an unprotected call does
    if not os.path.exists(marker):
        pytest.skip("this git does not run core.fsmonitor for `git status`")
    os.remove(marker)
    modify(root, "README.md")
    repo = Repo(root)
    assert repo.git_ok and set(repo.changed_vs("HEAD")) == {"README.md"}
    repo.ignored_many(["README.md"])
    result = Scanner(root).scan()
    assert not result.incomplete
    assert not os.path.exists(marker)


@needs_git
def test_a_clean_filter_named_by_gitattributes_is_not_run(make_repo):
    files = dict(NOTESYNC)
    files[".gitattributes"] = "*.md filter=look\n"
    root, marker = _marker_repo(make_repo, files)
    git(root, "config", "filter.look.clean", "touch it-ran; cat")
    git(root, "config", "filter.look.smudge", "touch it-ran; cat")
    git(root, "config", "filter.look.required", "true")
    # Same size, another time: git cannot tell from the stat data and has to hash the file, which
    # is when it runs the clean filter.
    path = os.path.join(root, "README.md")
    with open(path, "rb") as fh:
        committed = fh.read()
    assert committed.count(b"notesync") > 1
    with open(path, "wb") as fh:
        fh.write(committed.replace(b"notesync", b"NOTESYNC", 1))
    later = os.stat(path).st_mtime + 5
    os.utime(path, (later, later))
    git(root, "status", "--porcelain")                          # what an unprotected call does
    if not os.path.exists(marker):
        pytest.skip("this git did not run the clean filter for `git status`")
    os.remove(marker)
    repo = Repo(root)
    overlay = repo.changed_vs("HEAD")
    assert overlay is not None and set(overlay) == {"README.md"}
    assert overlay["README.md"].encode("utf-8") == committed    # the committed text, read without the filter
    assert repo.changed_vs("HEAD~0") is not None
    assert not os.path.exists(marker)


@needs_git
def test_a_submodule_entry_does_not_start_the_signature_program(make_repo, tmp_path):
    """`git show REV:path` prints a commit when the path is a submodule at REV, and with
    log.showSignature it hands the commit to gpg.program. The text at REV is read with cat-file."""
    root, marker = _marker_repo(make_repo)
    tree = git(root, "rev-parse", "HEAD^{tree}").strip()
    body = (f"tree {tree}\nauthor A <a@example.invalid> 0 +0000\ncommitter A <a@example.invalid> 0 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n\nmsg\n")
    signed = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=root,
                            input=body.encode("ascii"), capture_output=True, check=True).stdout.decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{signed},sub")
    git(root, "commit", "-q", "-m", "a submodule")
    write_files(root, {"sub": "a file now\n"})
    git(root, "add", "sub")                                     # status lists it: submodule -> file
    program = tmp_path / "fakegpg"
    with open(program, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#!/bin/sh\ntouch it-ran\n")
    os.chmod(program, 0o755)
    git(root, "config", "log.showSignature", "true")
    git(root, "config", "gpg.program", str(program).replace("\\", "/"))
    subprocess.run(["git", "show", "HEAD:sub"], cwd=root, capture_output=True)   # what the old code ran
    if not os.path.exists(marker):
        pytest.skip("this git does not run gpg.program for `git show REV:submodule`")
    os.remove(marker)
    repo = Repo(root)
    overlay = repo.changed_vs("HEAD")
    assert overlay is not None and overlay.get("sub", "") is None      # listed; no text at HEAD
    assert repo.changed_vs("HEAD~0") is not None
    assert not os.path.exists(marker)


@needs_git
def test_core_worktree_in_the_repository_config_does_not_move_the_listing(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "elsewhere.md").write_text(CANARY + "\n", encoding="utf-8")
    git(root, "config", "core.worktree", str(elsewhere).replace("\\", "/"))
    listed = git(root, "ls-files", "--others")                   # what an unprotected call does
    if "elsewhere.md" not in listed:
        pytest.skip("this git does not follow core.worktree here")
    modify(root, "README.md")
    repo = Repo(root)
    assert repo.git_ok and repo.has_file("README.md") and not repo.has_file("elsewhere.md")
    assert set(repo.changed_vs("HEAD")) == {"README.md"}
    assert set(repo.changed_vs("HEAD~0")) == {"README.md"}


@needs_git
def test_a_comparison_with_a_revision_does_not_rewrite_the_index(make_repo):
    root = make_repo(dict(NOTESYNC))
    index = os.path.join(root, ".git", "index")
    path = os.path.join(root, "README.md")

    def touch_and_read():
        later = os.stat(path).st_mtime + 5 + touch_and_read.n
        touch_and_read.n += 5
        os.utime(path, (later, later))                          # the stat data in the index is now stale
        with open(index, "rb") as fh:
            return fh.read()

    touch_and_read.n = 0
    before = touch_and_read()
    subprocess.run(["git", "diff", "--name-only", "HEAD~0"], cwd=root, capture_output=True, check=True,
                   env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))   # what the old code ran
    with open(index, "rb") as fh:
        if fh.read() == before:
            pytest.skip("this git does not refresh the index for `git diff REV`")
    before = touch_and_read()
    repo = Repo(root)
    assert repo.changed_vs("HEAD~0") == {} and repo.changed_vs("HEAD") == {}
    Scanner(root).scan()
    with open(index, "rb") as fh:
        assert fh.read() == before


@needs_git
def test_a_revision_that_looks_like_an_option_is_refused(make_repo):
    root = make_repo(dict(NOTESYNC))
    modify(root, "README.md")
    repo = Repo(root)
    assert repo.changed_vs("--output=it-ran") is None
    assert repo.changed_vs("-O it-ran") is None
    assert repo.changed_vs("") is None
    assert not os.path.exists(os.path.join(root, "it-ran"))
    assert set(repo.changed_vs("HEAD~0")) == {"README.md"}


@needs_git
def test_a_filter_name_that_cannot_be_overridden_stops_the_git_calls(make_repo, monkeypatch):
    root = make_repo(dict(NOTESYNC))
    modify(root, "README.md")
    repo = Repo(root)
    real = Repo._git

    def fake(self, args, options=(), data=None, ok=(0,)):
        if args[0] == "config":
            return b"filter.a=b.clean\0"
        return real(self, args, options, data, ok)

    monkeypatch.setattr(Repo, "_git", fake)
    assert repo.changed_vs("HEAD") is None


@needs_git
def test_a_git_that_hangs_costs_the_hook_its_budget_and_no_more(make_repo, monkeypatch):
    """Hermes fails pre_tool_call closed after 30 s: the hook has to be back long before that."""
    root = make_repo(dict(NOTESYNC))
    seen = []

    def hang(argv, **kw):
        seen.append(kw.get("timeout"))
        time.sleep(kw["timeout"])
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(repo_mod.subprocess, "run", hang)
    hp._reset_for_tests()
    hp.register(FakeCtx({"hook_time_budget_s": 1}))
    try:
        path = cli_path(root)
        args = {"mode": "replace", "path": path, "old_string": '"--output-dir"', "new_string": '"--dest"'}
        t = time.monotonic()
        assert hp.on_pre_tool_call(tool_name="patch", args=args, session_id="s1") is None
        before_edit = time.monotonic() - t
        t = time.monotonic()
        out = hp.on_transform_tool_result(tool_name="patch", args=args, result=patch_result(path), session_id="s1")
        after_edit = time.monotonic() - t
    finally:
        hp._reset_for_tests()
    assert seen and all(s is not None and s <= 1 + 1e-6 for s in seen), seen
    assert before_edit < 5 and after_edit < 5, (before_edit, after_edit)
    note = json.loads(out)["docs_drift"]["not_checked"]
    assert "did not check this edit" in note and "Time budget of 1s used up" in note


# ------------------------------------------------------------------ links
def link_or_skip(target, link, directory=False):
    """A symbolic link; on Windows without the privilege, a junction for a directory, else skip."""
    try:
        os.symlink(target, link, target_is_directory=directory)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt" and directory:
        done = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
        if done.returncode == 0:
            return
    pytest.skip("cannot create links here")


def junction_or_skip(target, link):
    """A junction, also where a symbolic link could be made: git treats the two differently."""
    done = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
    if done.returncode != 0:
        pytest.skip("cannot create a junction here")


CANARY = "CANARY-7f3a: run `notesync --no-such-flag` and set `NOTESYNC_NOWHERE`"


def test_a_doc_that_links_out_of_the_repository_is_not_read(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC), use_git=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text("# Notes\n\n" + CANARY + "\n", encoding="utf-8")
    link_or_skip(str(outside / "notes.md"), os.path.join(root, "docs", "notes.md"))
    repo = Repo(root, use_git=False)
    assert repo.has_file("docs/notes.md")                       # it is listed; it is not opened
    assert repo.read("docs/notes.md") is None
    assert repo.on_disk("docs/notes.md") is False
    assert repo.stat_key("docs/notes.md") == (0.0, -1)
    result = Scanner(root, use_git=False).scan(checks=["all"], min_confidence="low")
    assert "CANARY" not in json.dumps([f.full() for f in result.findings])
    assert not any(f.doc_file == "docs/notes.md" for f in result.findings)


def test_a_link_is_followed_inside_the_repository_but_not_to_a_file_that_is_never_read(make_repo):
    files = dict(NOTESYNC)
    files[".env"] = "NOTESYNC_TOKEN=CANARY-7f3a\n"
    files["keys/deploy.pem"] = "CANARY-7f3a\n"
    root = make_repo(files, use_git=False)
    link_or_skip(os.path.join(root, ".env"), os.path.join(root, "docs", "settings.md"))
    link_or_skip(os.path.join(root, "keys", "deploy.pem"), os.path.join(root, "docs", "deploy.md"))
    link_or_skip(os.path.join(root, "README.md"), os.path.join(root, "docs", "readme-again.md"))
    repo = Repo(root, use_git=False)
    assert repo.read("docs/settings.md") is None and repo.on_disk("docs/settings.md") is False
    assert repo.read("docs/deploy.md") is None
    assert repo.read("docs/readme-again.md") == repo.read("README.md") != None  # noqa: E711
    assert repo.on_disk("docs/readme-again.md") is True


@needs_git
def test_a_link_into_the_git_directory_is_not_read(make_repo):
    root = make_repo(dict(NOTESYNC))
    git(root, "config", "remote.origin.url", "https://user:CANARY-7f3a@example.invalid/x/y.git")
    link_or_skip(os.path.join(root, ".git", "config"), os.path.join(root, "docs", "remotes.md"))
    repo = Repo(root)
    assert repo.read("docs/remotes.md") is None
    assert repo.on_disk("docs/remotes.md") is False


@needs_git
def test_nothing_in_a_git_directory_is_read_under_any_spelling(make_repo):
    """``.GIT/config`` is the repository's config on a file system that ignores letter case."""
    root = make_repo(dict(NOTESYNC))
    git(root, "config", "remote.origin.url", "https://user:CANARY-7f3a@example.invalid/x/y.git")
    write_files(root, {                                         # after the commit: git refuses to add these
        "vendor/lib/.git/config": "[remote]\n\turl = https://user:CANARY-7f3a@example.invalid/a.git\n",
        "vendor/lib/.Git/notes.md": CANARY + "\n",
        "vendor/lib/plain.md": "# Plain\n",
    })
    repo = Repo(root)
    assert repo.git_ok and repo.has_file("vendor/lib/plain.md")
    for rel in (".git/config", ".GIT/config", ".Git/HEAD", "docs/../.git/config", ".git",
                "vendor/lib/.git/config", "vendor/lib/.GIT/config", "vendor/lib/.Git/notes.md"):
        assert repo.read(rel) is None, rel
        assert repo.on_disk(rel) is False, rel
        assert repo.stat_key(rel) == (0.0, -1), rel
    assert not any(".git" in f.casefold().split("/") for f in repo.files)
    walked = Repo(root, use_git=False)
    assert not any(".git" in f.casefold().split("/") for f in walked.files)
    assert walked.read("vendor/lib/.Git/notes.md") is None
    result = Scanner(root).scan(checks=["all"], min_confidence="low")
    assert "CANARY" not in json.dumps([f.full() for f in result.findings])


@needs_git
def test_a_link_to_the_git_directory_under_another_spelling_is_not_read(make_repo):
    root = make_repo(dict(NOTESYNC))
    git(root, "config", "remote.origin.url", "https://user:CANARY-7f3a@example.invalid/x/y.git")
    # ``.GIT`` where the file system ignores letter case (Windows, macOS), ``.git`` elsewhere.
    spelling = ".GIT" if os.path.isfile(os.path.join(root, ".GIT", "config")) else ".git"
    link_or_skip(os.path.join(root, spelling), os.path.join(root, "meta"), directory=True)
    with open(os.path.join(root, "meta", "config"), encoding="utf-8") as fh:
        assert "CANARY-7f3a" in fh.read()                       # the link does lead there
    repo = Repo(root)
    assert repo.read("meta/config") is None
    assert repo.on_disk("meta/config") is False
    assert repo.stat_key("meta/config") == (0.0, -1)
    assert repo.on_disk("meta/HEAD") is False
    assert not any(f.startswith("meta/") for f in repo.files)
    assert not any(f.startswith("meta/") for f in Repo(root, use_git=False).files)


def test_a_file_that_is_never_read_gives_away_only_that_it_exists(make_repo):
    files = dict(NOTESYNC)
    files[".env"] = "NOTESYNC_TOKEN=CANARY-7f3a\n"
    files["config/id_rsa"] = "CANARY-7f3a\n"
    root = make_repo(files, use_git=False)
    repo = Repo(root, use_git=False)
    for rel in (".env", "config/id_rsa"):
        assert repo.read(rel) is None, rel
        assert repo.stat_key(rel) == (0.0, -1), rel             # no size, no time
        assert repo.on_disk(rel) is True, rel                   # a doc may say "copy .env.example to .env"
    assert repo.stat_key("README.md") != (0.0, -1)


def test_names_from_a_listing_stay_in_the_repository():
    plain = repo_mod._plain_name
    for name in ("README.md", "docs/a b.md", "a/.github/x.yml", ".gitignore", "x.git/y", "a/git/b", "~/x"):
        assert plain(name), name
    for name in ("", "/etc/passwd", "../x", "a/../../x", "a//b", "./a", "a/./b", ".git/config", ".GIT/config",
                 "a/.git/b", "a/.Git"):
        assert not plain(name), name


@pytest.mark.skipif(os.name != "nt", reason="names that Windows opens as another file")
def test_windows_spellings_of_another_file_are_refused(make_repo):
    files = dict(NOTESYNC)
    files[".env"] = "NOTESYNC_TOKEN=CANARY-7f3a\n"
    files["secrets-kept-here/.env"] = "NOTESYNC_TOKEN=CANARY-7f3a\n"
    root = make_repo(files)
    repo = Repo(root)
    assert repo.read("README.md") is not None
    for rel in (".env.", ".env ", ".env::$DATA", "README.md::$DATA", "README.md.", "README.md ", ".git./config",
                ".git /config", ".git::$INDEX_ALLOCATION/config", "NUL", "nul.md", "docs/CON", "COM1.txt",
                "GIT~1/config", "SECRET~1/.env", "docs\\..\\.git\\config"):
        assert repo.read(rel) is None, rel
        assert repo.stat_key(rel) == (0.0, -1), rel
        assert not repo_mod._plain_name(rel) or "~" in rel, rel
    for rel in (".env.", ".git./config", "NUL", "GIT~1/config", "README.md::$DATA"):
        assert repo.on_disk(rel) is False, rel
    # A short name of a plain directory is still that directory.
    short = subprocess.run(["cmd", "/c", "for %I in (.) do @echo %~sI"], cwd=os.path.join(root, "secrets-kept-here"),
                           capture_output=True, text=True).stdout.strip()
    alias = os.path.basename(short)
    if "~" in alias:
        assert repo.read(alias + "/.env") is None
        write_files(root, {"secrets-kept-here/notes.md": "hello\n"})
        assert repo.read(alias + "/notes.md") == "hello\n"


@needs_git
@pytest.mark.skipif(os.name != "nt", reason="Git for Windows lists the files behind a junction")
def test_files_behind_a_junction_are_not_listed(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC))
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "notes.md").write_text(CANARY + "\n", encoding="utf-8")
    (outside / "deep" / "more.md").write_text(CANARY + "\n", encoding="utf-8")
    junction_or_skip(str(outside), os.path.join(root, "shared"))
    junction_or_skip(os.path.join(root, "docs"), os.path.join(root, "docs-again"))
    if "shared/notes.md" not in git(root, "ls-files", "--others"):
        pytest.skip("this git does not list the files behind a junction")
    repo = Repo(root)
    assert repo.git_ok and repo.has_file("docs/configuration.md")
    assert not any(f.startswith(("shared/", "docs-again/")) for f in repo.files), repo.files
    result = Scanner(root).scan(checks=["all"], min_confidence="low")
    assert "CANARY" not in json.dumps([f.full() for f in result.findings])


def test_a_walk_without_git_does_not_enter_a_linked_directory(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC), use_git=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text(CANARY + "\n", encoding="utf-8")
    link_or_skip(str(outside), os.path.join(root, "shared"), directory=True)
    link_or_skip(os.path.join(root, "docs"), os.path.join(root, "docs-again"), directory=True)
    repo = Repo(root, use_git=False)
    assert repo.has_file("docs/configuration.md")
    assert not any(f.startswith(("shared/", "docs-again/")) for f in repo.files), repo.files


def test_a_linked_directory_that_leads_out_is_not_entered(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC), use_git=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text(CANARY + "\n", encoding="utf-8")
    link_or_skip(str(outside), os.path.join(root, "shared"), directory=True)
    inside = os.path.join(root, "docs-again")
    link_or_skip(os.path.join(root, "docs"), inside, directory=True)
    repo = Repo(root, use_git=False)
    assert repo.read("shared/notes.md") is None
    assert repo.on_disk("shared/notes.md") is False
    assert repo.stat_key("shared/notes.md") == (0.0, -1)
    assert repo.read("docs-again/configuration.md") == repo.read("docs/configuration.md") != None  # noqa: E711
    result = Scanner(root, use_git=False).scan(checks=["all"], min_confidence="low")
    assert "CANARY" not in json.dumps([f.full() for f in result.findings])


def test_paths_that_leave_the_repository_are_refused_without_a_link(make_repo, tmp_path):
    root = make_repo(dict(NOTESYNC), use_git=False)
    (tmp_path / "outside.md").write_text(CANARY + "\n", encoding="utf-8")
    repo = Repo(root, use_git=False)
    for rel in ("../outside.md", "docs/../../outside.md", str(tmp_path / "outside.md")):
        assert repo.on_disk(rel) is False, rel
        assert repo.read(rel) is None, rel
        assert repo.stat_key(rel) == (0.0, -1), rel
    assert repo.on_disk("docs/../README.md") is True            # still inside
    assert repo.on_disk("build") is False


# ------------------------------------------------------------------ slow lines
OLD_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
OLD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def _strings(alphabet, upto, extra, seed):
    for n in range(upto + 1):
        for chars in itertools.product(alphabet, repeat=n):
            yield "".join(chars)
    rng = random.Random(seed)
    for _ in range(extra):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))


def test_code_spans_are_the_matches_of_the_pattern_they_replace():
    n = 0
    for s in _strings("`a ", 9, 20000, seed=1):
        assert code_spans(s) == [(m.start(), m.end(), len(m.group(1))) for m in OLD_CODE_SPAN.finditer(s)], s
        n += 1
    assert n > 40000


def test_heading_text_is_what_the_old_pattern_captured():
    n = 0
    for s in _strings("# a\t", 8, 20000, seed=2):
        old, new = OLD_HEADING.match(s), docs_mod.HEADING.match(s)
        assert (old is None) == (new is None), s
        if old:
            assert (old.group(1), old.group(2)) == (new.group(1), heading_text(new.group(2))), s
            n += 1
    assert n > 1000


N = 200_000
SLOW_LINES = {
    # name: one doc line; every one of them took the pinned code from seconds to hours
    "backticks": "a " + "`" * N + "x",                       # not at the line start: that opens a fence
    "backtick pairs": "` " * (N // 2),
    "heading hashes": "# " + "#" * N + "x",
    "open tags": "<a " * (N // 3),
    "open links": "](<" * (N // 3),
    "default and spaces": "default" + " " * N + "x",
    "defaults": "default " * (N // 8),
    "table row": "| `a` " * (N // 6),
}


@pytest.mark.parametrize("name", sorted(SLOW_LINES))
def test_one_long_line_is_parsed_in_linear_time(name):
    line = SLOW_LINES[name]
    t = time.perf_counter()
    doc = parse_markdown("README.md", "# Title\n\n" + line + "\n\nSet `--flag` here.\n")
    table_columns(line)
    for rx in (docs_mod.LINK_TARGET, docs_mod.HTML_SRC, checks_mod.DEFAULT_RX):
        for _ in rx.finditer(line):
            pass
    took = time.perf_counter() - t
    assert any(s.text == "--flag" for s in doc.spans)
    assert took < 5, f"{name}: {took:.1f}s for one line of {len(line)} characters"


def test_a_v4a_header_is_cut_up_without_backtracking():
    body = ("*** Begin Patch\n*** Update File: a/b.py \n@@\n-x\n+y\n*** Add File:docs/new.md\n+hi\n"
            "*** Move File: old name.md -> new name.md\n*** Delete File:  gone.md\n*** Move File: no arrow\n"
            "*** Update File:\n*** End Patch\n")
    assert hp._v4a_paths(body) == ["a/b.py", "docs/new.md", "old name.md", "new name.md", "gone.md"]
    t = time.perf_counter()
    assert hp._v4a_paths("*** Update File:" + " " * N + "\n" + "*** Move File: a ->" * (N // 19)) != []
    assert hp._v4a_paths("*** Update File:" + " " * N) == []
    assert time.perf_counter() - t < 5


def test_blank_lines_and_runs_of_spaces_do_not_slow_the_file_readers(make_repo):
    """Patterns that began with ``^\\s*`` in multi-line mode walked every run of blank lines once per line."""
    from docsdrift.facts import _toml_section_keys

    files = dict(NOTESYNC)
    files[".gitmodules"] = "\n" * N + '# vendored\n[submodule "a"]\n\tpath = vendor/a\n  path=vendor/b  \n'
    root = make_repo(files, use_git=False)
    t = time.perf_counter()
    assert Repo(root, use_git=False).submodule_paths() == ["vendor/a", "vendor/b"]
    toml = "[project.scripts]\n" + "\n" * N + '# entry points\nnotesync ="notesync.cli:main"\n  "other-tool"="x:y"\n\n[tool.x]\nz = 1\n'
    assert _toml_section_keys(toml, "project.scripts") == ["notesync", "other-tool"]
    doc = parse_markdown("README.md", "| Flag | Default |\n" + " " * N + "\n\n| Flag | Default |\n  | :--- | --- |\n")
    assert docs_mod.table_header_for(doc, 1) == []
    assert docs_mod.table_header_for(doc, 4) == ["flag", "default"]
    assert time.perf_counter() - t < 5


def test_a_scan_of_the_slow_lines_finishes(make_repo):
    files = dict(NOTESYNC)
    files["docs/long.md"] = ("# Long lines\n\n" + "\n\n".join(v[:60_000] for v in SLOW_LINES.values())
                             + "\n\n```sh\n" + " " * 60_000 + "x\n$ cd notesync\n" + "\n" * 60_000 + "x\n```\n\n"
                             + "Defaults to " + "<" * 60_000 + " `--output-dir`.\n")
    root = make_repo(files, use_git=False)
    t = time.perf_counter()
    result = Scanner(root, use_git=False).scan(checks=["all"], min_confidence="low")
    assert not result.incomplete
    assert time.perf_counter() - t < 20


# ------------------------------------------------------------------ one time limit per call
def test_a_scan_past_its_deadline_reports_nothing_and_says_where(make_repo):
    root = make_repo(dict(NOTESYNC), use_git=False)
    sc = Scanner(root, use_git=False)
    assert sc.scan().findings == [] and not sc.scan().incomplete
    result = sc.scan(deadline=time.monotonic() - 1)
    assert result.incomplete and result.findings == []
    assert "used up" in result.notes[-1] and "nothing reported" in result.notes[-1]


def test_the_time_limit_is_checked_between_the_docs_inside_a_check(make_repo, monkeypatch):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("--output-dir", "--no-such-flag")
    root = make_repo(files, use_git=False)
    sc = Scanner(root, use_git=False)
    assert sc.scan().findings                                   # there is something to report
    seen = []

    def late(ctx):
        for doc in ctx.each_doc():
            seen.append(doc.path)
            ctx.deadline = time.monotonic() - 1                 # the first doc used up the time
        return []

    monkeypatch.setitem(checks_mod.ALL_CHECKS, "path-missing", late)
    result = sc.scan(deadline=time.monotonic() + 60)
    assert len(seen) == 1
    assert result.incomplete and result.findings == []
    assert result.notes[-1] == "Time budget of 60s used up in check path-missing; nothing reported."


def _hold_lock(release):
    held = threading.Event()

    def holder():
        with hp._lock:
            held.set()
            release.wait(30)

    th = threading.Thread(target=holder, daemon=True)
    th.start()
    assert held.wait(5)
    return th


def test_hooks_do_not_wait_for_a_long_scan_past_their_budget(make_repo):
    """docs_drift_scan holds the lock for up to two minutes; pre_tool_call must not sit behind it."""
    root = make_repo(dict(NOTESYNC), use_git=False)
    hp._reset_for_tests()
    hp.register(FakeCtx({"hook_time_budget_s": 1}))
    release = threading.Event()
    th = _hold_lock(release)
    try:
        path = cli_path(root)
        args = {"mode": "replace", "path": path, "old_string": '"--output-dir"', "new_string": '"--dest"'}
        t = time.monotonic()
        assert hp.on_pre_tool_call(tool_name="patch", args=args, session_id="s1") is None
        out = hp.on_transform_tool_result(tool_name="patch", args=args, result=patch_result(path), session_id="s1")
        assert hp.on_pre_verify(session_id="s1", changed_paths=[path], attempt=0) is None
        took = time.monotonic() - t
    finally:
        release.set()
        th.join(5)
        hp._reset_for_tests()
    assert 2.5 < took < 8, took                                 # three hooks, 1 s each
    data = json.loads(out)
    assert data["success"] is True
    assert "another docs-drift scan was still running after 1s" in data["docs_drift"]["not_checked"]


def test_the_scans_of_one_hook_call_share_one_budget(notesync, monkeypatch):
    """The baseline from git and the scan after the edit used to get the whole budget each."""
    limits = []
    real = hp._scan

    def scan(root, budget_s, *a, **kw):
        limits.append(kw.get("deadline"))
        return real(root, budget_s, *a, **kw)

    monkeypatch.setattr(hp, "_scan", scan)
    hp._reset_for_tests()
    hp.register(FakeCtx({"hook_time_budget_s": 7}))
    try:
        path = cli_path(notesync)
        args = {"mode": "replace", "path": path, "old_string": '"--output-dir"', "new_string": '"--dest"'}
        write_files(notesync, {"notesync/extra.py": "X = 1\n"})
        start = time.monotonic()
        hp.on_transform_tool_result(tool_name="patch", args=args, result=patch_result(path), session_id="s1")
    finally:
        hp._reset_for_tests()
    assert len(limits) == 2 and limits[0] == limits[1]          # git baseline, then the scan after the edit
    assert start + 6.9 < limits[0] < start + 7.5

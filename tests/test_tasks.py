"""demo/tasks.py: the outcome rules of the real-model comparison, and what the hooks say on its example project.

No model and no Hermes here. The edits below are the smallest code-only change
that carries out each request, applied the way the plugin tests apply an edit.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import HAVE_GIT, ROOT, edit
from docsdrift import hermes_plugin as hp
from docsdrift.scan import Scanner
from test_plugin import FakeCtx, do_edit

sys.path.insert(0, os.path.join(ROOT, "demo"))
import relay  # noqa: E402
import tasks  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "notesync-tasks")

LEGACY_ARG = ('    parser.add_argument("--legacy-sync", action="store_true",\n'
              '                        help="deprecated: copy the files one by one, as version 0.2 did")\n')
TOKEN_FILE_READ = ('    if not token:\n'
                   '        token_file = os.environ.get("NOTESYNC_TOKEN_FILE", "")\n'
                   '        if token_file:\n'
                   '            token = Path(token_file).read_text(encoding="utf-8").strip()\n')
CODE_ONLY = {
    "default": [("notesync/cli.py", 'default=3, help="how often', 'default=5, help="how often')],
    "remove-flag": [("notesync/cli.py", LEGACY_ARG, ""),
                    ("notesync/cli.py", ", one_by_one=args.legacy_sync", "")],
    "remove-env": [("notesync/upload.py", TOKEN_FILE_READ, ""),
                   ("notesync/upload.py", ", else from the file NOTESYNC_TOKEN_FILE names", "")],
    "add-flag": [("notesync/cli.py", "    return parser\n",
                  '    parser.add_argument("--dry-run", action="store_true", help="print what would be copied")\n'
                  "    return parser\n")],
    "add-env": [("notesync/cli.py", "timeout=args.timeout",
                 'timeout=int(os.environ.get("NOTESYNC_TIMEOUT", args.timeout))')],
}


@pytest.fixture
def project(tmp_path):
    if not HAVE_GIT:
        pytest.skip("git is not installed")
    root = str(tmp_path / "notesync")
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__"))
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
           "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(git + args, cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture
def ctx():
    hp._reset_for_tests()
    c = FakeCtx()
    hp.register(c)
    yield c
    hp._reset_for_tests()


def apply(root, name):
    for rel, old, new in CODE_ONLY[name]:
        edit(root, rel, old, new)


def stale_places(result):
    return [":".join(line.split(":")[:2]) for line in result["stale"]]


# ------------------------------------------------------------------ the example project
def test_the_example_project_has_no_findings_before_any_edit():
    result = Scanner(EXAMPLE).scan(checks=["all"])
    assert result.findings == []


def test_every_task_names_an_existing_example_and_never_mentions_docs():
    for name, task in tasks.TASKS.items():
        if "repo" in task:                       # a real repository: the driver is handed a checkout
            assert "example" not in task and task["commit"], name
        else:
            assert os.path.isdir(os.path.join(ROOT, "examples", task["example"])), name
        assert not any(w in task["prompt"].lower() for w in ("doc", "readme", "guide", "manual")), name


# ------------------------------------------------------------------ the rules
@pytest.mark.parametrize("name", ["default", "remove-flag", "remove-env", "add-flag", "add-env"])
def test_untouched_project_is_not_done(project, name):
    assert tasks.judge(tasks.TASKS[name], project)["verdict"] == "not done in the code"


def test_default_changed_in_code_only_is_stale_in_four_places(project):
    apply(project, "default")
    result = tasks.judge(tasks.TASKS["default"], project)
    assert result["verdict"] == "docs stale" and result["code_done"]
    assert stale_places(result) == ["README.md:18", "README.md:21", "docs/configuration.md:11",
                                    "docs/troubleshooting.md:5"]


def test_default_is_consistent_only_when_every_statement_is_updated(project):
    apply(project, "default")
    edit(project, "README.md", "| `--retries` | `3` |", "| `--retries` | `5` |")
    assert tasks.judge(tasks.TASKS["default"], project)["verdict"] == "docs stale"      # prose still says 3
    edit(project, "README.md", "tried again 3 times", "tried again 5 times")
    edit(project, "docs/configuration.md", "upload 3 times", "upload five times")
    edit(project, "docs/troubleshooting.md", "default of 3 retries", "default of 5 retries")
    assert tasks.judge(tasks.TASKS["default"], project)["verdict"] == "docs consistent"


def test_docs_changed_but_code_left_alone_is_not_done(project):
    edit(project, "README.md", "| `--retries` | `3` |", "| `--retries` | `5` |")
    assert tasks.judge(tasks.TASKS["default"], project)["verdict"] == "not done in the code"


def test_removed_flag_in_code_only_is_stale(project):
    apply(project, "remove-flag")
    result = tasks.judge(tasks.TASKS["remove-flag"], project)
    assert result["verdict"] == "docs stale"
    assert stale_places(result) == ["README.md:19", "docs/troubleshooting.md:10", "docs/troubleshooting.md:13"]


def test_a_line_saying_the_flag_was_removed_is_not_stale(project):
    apply(project, "remove-flag")
    edit(project, "README.md", "| `--legacy-sync` | off | deprecated: copy the files one by one |\n", "")
    edit(project, "docs/troubleshooting.md", "Run with `--legacy-sync`, which copies the files one by one and flushes after each:",
         "`--legacy-sync` was removed in 0.6; copy the folder to a local disk first.")
    edit(project, "docs/troubleshooting.md", "notesync ./notes --legacy-sync\n", "notesync ./notes\n")
    assert tasks.judge(tasks.TASKS["remove-flag"], project)["verdict"] == "docs consistent"


def test_removed_variable_in_code_only_is_stale(project):
    apply(project, "remove-env")
    result = tasks.judge(tasks.TASKS["remove-env"], project)
    assert result["verdict"] == "docs stale"
    assert stale_places(result) == ["docs/configuration.md:6", "docs/troubleshooting.md:18"]
    assert tasks.judge(tasks.TASKS["remove-flag"], project)["verdict"] == "not done in the code"


def test_added_name_needs_a_doc_file_other_than_a_changelog(project):
    apply(project, "add-flag")
    assert tasks.judge(tasks.TASKS["add-flag"], project)["verdict"] == "docs stale"
    with open(os.path.join(project, "CHANGELOG.md"), "w", encoding="utf-8") as fh:
        fh.write("# Changes\n\n- added `--dry-run`\n")
    assert tasks.judge(tasks.TASKS["add-flag"], project)["verdict"] == "docs stale"
    edit(project, "README.md", "| `--legacy-sync` | off |", "| `--dry-run` | off | print only |\n| `--legacy-sync` | off |")
    result = tasks.judge(tasks.TASKS["add-flag"], project)
    assert result["verdict"] == "docs consistent" and result["mentions"][0].startswith("README.md:19:")


def test_added_variable(project):
    apply(project, "add-env")
    assert tasks.judge(tasks.TASKS["add-env"], project)["verdict"] == "docs stale"
    with open(os.path.join(project, "docs", "configuration.md"), "a", encoding="utf-8") as fh:
        fh.write("\n`NOTESYNC_TIMEOUT` sets the time limit.\n")
    assert tasks.judge(tasks.TASKS["add-env"], project)["verdict"] == "docs consistent"


def test_rename_rule_on_the_first_example(notesync):
    task = tasks.TASKS["rename"]
    assert tasks.judge(task, notesync)["verdict"] == "not done in the code"
    edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert tasks.judge(task, notesync)["verdict"] == "docs stale"
    for rel in ("README.md", "docs/configuration.md"):
        edit(notesync, rel, "--output-dir", "--dest")
    assert tasks.judge(task, notesync)["verdict"] == "docs consistent"


# ------------------------------------------------------------------ what the hooks say for each request
def hook_says(root, name):
    """(checks and places of the new findings, of the added names, first line of the reminder)."""
    new, added = [], []
    for rel, old, new_text in CODE_ONLY[name]:
        out = do_edit(root, rel, old, new_text)
        if out:
            new += [(f["check"], f["doc"]) for f in out["docs_drift"].get("new", [])]
            added += [(f["check"], f["doc"]) for f in out["docs_drift"].get("added", [])]
    nudge = hp.on_pre_verify(session_id="s1", changed_paths=[os.path.join(root, "notesync", "cli.py")], attempt=0)
    return new, added, (nudge["message"].splitlines()[0] if nudge else None)


def test_hooks_on_a_changed_default_report_the_table_row_and_not_the_prose(ctx, project):
    new, added, reminder = hook_says(project, "default")
    assert new == [("default-mismatch", "README.md:18")] and added == []
    assert "left 1 place" in reminder
    # the rule above finds four stale lines; three of them are prose, which no check reads
    assert len(tasks.judge(tasks.TASKS["default"], project)["stale"]) == 4


def test_hooks_on_a_removed_flag(ctx, project):
    new, added, reminder = hook_says(project, "remove-flag")
    assert new == [("cli-flag-undefined", "docs/troubleshooting.md:10")] and added == []
    assert "left 1 place" in reminder


def test_hooks_on_a_removed_variable_wait_until_the_name_is_gone_from_the_code(ctx, project):
    rel, old, new_text = CODE_ONLY["remove-env"][0]
    assert do_edit(project, rel, old, new_text) is None            # the docstring still names the variable
    rel, old, new_text = CODE_ONLY["remove-env"][1]
    out = do_edit(project, rel, old, new_text)
    assert [(f["check"], f["doc"]) for f in out["docs_drift"]["new"]] == [
        ("env-undefined", "docs/configuration.md:6"), ("env-undefined", "docs/troubleshooting.md:18")]


def test_hooks_on_an_added_flag_and_an_added_variable(ctx, project):
    new, added, reminder = hook_says(project, "add-flag")
    assert new == [] and added == [("added-flag-undocumented", "README.md:19")]
    assert "added 1 name that no doc mentions" in reminder
    hp._reset_for_tests()
    hp.register(FakeCtx())
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=project, check=True)
    new, added, reminder = hook_says(project, "add-env")
    assert new == [] and added == [("added-env-undocumented", "docs/configuration.md:6")]


# ------------------------------------------------------------------ the request on a real repository
def test_the_real_repository_task_names_its_starting_tree_and_uses_the_add_rule(tmp_path):
    if not HAVE_GIT:
        pytest.skip("git is not installed")
    task = tasks.TASKS["uvicorn-add-flag"]
    assert task["repo"] == "encode/uvicorn" and task["commit"] and "doc" not in task["prompt"].lower()
    root = str(tmp_path / "app")
    os.makedirs(os.path.join(root, "app"))
    os.makedirs(os.path.join(root, "docs"))
    for rel, text in (("app/main.py", 'import click\n\n@click.option("--port")\ndef main(port):\n    pass\n'),
                      ("docs/settings.md", "* `--port <int>` - the port.\n"),
                      ("docs/release-notes.md", "- nothing yet\n")):
        with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, capture_output=True)
    assert tasks.judge(task, root)["verdict"] == "not done in the code"
    edit(root, "app/main.py", '@click.option("--port")', '@click.option("--port")\n@click.option("--quiet", is_flag=True)')
    assert tasks.judge(task, root)["verdict"] == "docs stale"
    edit(root, "docs/release-notes.md", "- nothing yet", "- Add `--quiet`")
    assert tasks.judge(task, root)["verdict"] == "docs stale"          # release notes are not counted
    edit(root, "docs/settings.md", "the port.", "the port.\n* `--quiet` - only warnings and errors.")
    result = tasks.judge(task, root)
    assert result["verdict"] == "docs consistent" and result["mentions"][0].startswith("docs/settings.md:2:")


def test_the_driver_wants_a_checkout_for_the_real_repository_task(capsys):
    import run_real
    with pytest.raises(SystemExit) as stop:
        run_real.main(["--task", "uvicorn-add-flag"])
    assert stop.value.code == 2 and "--project" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run_real.main(["--task", "add-flag", "--project", "."])


def test_a_clone_for_a_session_keeps_line_endings_and_the_upstream_origin(tmp_path):
    if not HAVE_GIT:
        pytest.skip("git is not installed")
    import run_real
    src = str(tmp_path / "src")
    os.makedirs(src)
    with open(os.path.join(src, "a.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("one\ntwo\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
           "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"],
                 ["remote", "add", "origin", "https://example.invalid/some/project.git"]):
        subprocess.run(git + args, cwd=src, check=True, capture_output=True)
    dest = str(tmp_path / "copy")
    commit = run_real.clone_project(src, dest)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    assert head.startswith(commit)
    with open(os.path.join(dest, "a.txt"), "rb") as fh:
        assert fh.read() == b"one\ntwo\n"
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=dest, capture_output=True, text=True).stdout.strip()
    assert origin == "https://example.invalid/some/project.git"


# ------------------------------------------------------------------ who spoke first
def call(name, **args):
    return {"name": name, "arguments": json.dumps(args)}


def test_ordering_counts_doc_edits_before_and_after_the_plugin_spoke():
    trace = [
        {"request": 1, "told_edit": False, "told_reminder": False},
        {"answer": 1, "calls": [call("read_file", path="README.md")]},
        {"request": 2, "told_edit": False, "told_reminder": False},
        {"answer": 2, "calls": [call("patch", path="notesync/cli.py"), call("patch", path="C:\\x\\notesync\\README.md")]},
        {"request": 3, "told_edit": True, "told_reminder": False},
        {"answer": 3, "calls": [call("patch", path="docs/configuration.md"), call("write_file", path="docs/troubleshooting.md")]},
        {"request": 4, "told_edit": True, "told_reminder": False},
        {"answer": 4, "calls": []},
    ]
    assert tasks.ordering(trace) == {"spoke": True, "first_request": 3, "how": "edit result", "reminder": False,
                                     "doc_edits_before": 1, "doc_edits_after": 2, "doc_edits_outside": 0}


def test_ordering_does_not_count_a_doc_named_file_outside_the_project(tmp_path):
    root = str(tmp_path / "work" / "notesync")
    os.makedirs(root)
    scratch = str(tmp_path / "home" / "cache" / "scratch" / "a.md")
    trace = [
        {"request": 1, "told_edit": False, "told_reminder": False},
        {"answer": 1, "calls": [call("patch", path="notesync/cli.py"), call("write_file", path=scratch),
                                call("patch", path=os.path.join(root, "README.md"))]},
        {"request": 2, "told_edit": True, "told_reminder": False},
        {"answer": 2, "calls": [call("patch", path=r"docs\configuration.md"), call("write_file", path=scratch),
                                call("write_file", path="../notes.md")]},
    ]
    out = tasks.ordering(trace, root=root)
    assert (out["doc_edits_before"], out["doc_edits_after"], out["doc_edits_outside"]) == (1, 1, 3)
    loose = tasks.ordering(trace)                 # without a root every doc-named path counts, as in round 3
    assert (loose["doc_edits_before"], loose["doc_edits_after"], loose["doc_edits_outside"]) == (2, 3, 0)
    assert tasks.in_project("README.md", root) and tasks.in_project(os.path.join(root, "docs", "a.md"), root)
    assert not tasks.in_project(scratch, root) and not tasks.in_project("..", root + os.sep + "x" + os.sep + ".." + os.sep + "..")


def test_ordering_when_the_plugin_said_nothing_and_when_only_the_reminder_came():
    quiet = [{"request": 1, "told_edit": False, "told_reminder": False},
             {"answer": 1, "calls": [call("patch", path="README.md"), call("patch", path="CHANGELOG.md")]}]
    assert tasks.ordering(quiet) == {"spoke": False, "first_request": None, "how": "", "reminder": False,
                                     "doc_edits_before": 1, "doc_edits_after": 0, "doc_edits_outside": 0}
    late = quiet + [{"request": 2, "told_edit": False, "told_reminder": True},
                    {"answer": 2, "calls": [call("patch", mode="patch", patch="*** Begin Patch\n*** Update File: docs/a.md\n")]}]
    out = tasks.ordering(late)
    assert (out["how"], out["reminder"], out["doc_edits_before"], out["doc_edits_after"]) == ("reminder", True, 1, 1)


def test_relay_recognises_what_the_plugin_wrote():
    entry = {"success": True, "docs_drift": {"note": "x", "new": [{"id": "a"}], "still_open": 1}}
    resolved = {"success": True, "docs_drift": {"note": "x", "resolved": ["a"], "still_open": 0}}
    added = {"success": True, "docs_drift": {"note": "x", "added": [{"id": "b"}], "still_open": 1}}
    tool = lambda body: {"role": "tool", "content": json.dumps(body)}                      # noqa: E731
    assert relay.told_by_plugin([tool(entry)]) == {"told_edit": True, "told_reminder": False}
    assert relay.told_by_plugin([tool(added)])["told_edit"] is True
    assert relay.told_by_plugin([tool(resolved), tool({"success": True})]) == {"told_edit": False, "told_reminder": False}
    reminder = {"role": "user", "content": "docs-drift: your edits in this session added 1 name that no doc mentions."}
    assert relay.told_by_plugin([{"role": "system", "content": relay.REMINDER}, reminder]) == {
        "told_edit": False, "told_reminder": True}

"""Names an edit added to the code that no doc mentions.

This is reported in a session only (the hooks, and the tools once the session
has edited something). It is not one of the checks: a whole-repository scan,
the command line and ``changed_only`` never report it.
"""

import json
import os

import pytest

from conftest import NOTESYNC, edit
from docsdrift import hermes_plugin as hp
from docsdrift.model import CHECKS
from docsdrift.scan import ALL_CHECKS, Scanner
from test_plugin import FakeCtx, cli_path, do_edit

DRY = '    parser.add_argument("--dry-run", action="store_true")\n'
ADD_FLAG = DRY + '    parser.add_argument("--verbose", action="store_true", help="say what is copied")\n'
TOKEN = '    token = os.environ.get("NOTESYNC_TOKEN", "")\n'
ADD_ENV = TOKEN + '    timeout = int(os.environ.get("NOTESYNC_TIMEOUT", args.timeout))\n'


@pytest.fixture
def ctx():
    hp._reset_for_tests()
    c = FakeCtx()
    hp.register(c)
    yield c
    hp._reset_for_tests()


def test_added_flag_is_reported_in_the_edit_result(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    entry = out["docs_drift"]
    assert "new" not in entry
    assert [a["check"] for a in entry["added"]] == ["added-flag-undocumented"]
    a = entry["added"][0]
    assert a["doc"] == "README.md:16"                    # the last row of the options table
    assert a["code"].startswith("notesync/cli.py:")
    assert "`--verbose`" in a["problem"] and "no doc mentions it" in a["problem"]
    assert a["confidence"] == "medium"
    assert "added 1 name(s) that no doc mentions" in entry["note"]
    assert "no longer match" not in entry["note"]
    assert entry["still_open"] == 1


def test_added_environment_variable_is_reported(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", TOKEN, ADD_ENV)
    added = out["docs_drift"]["added"]
    assert [(a["check"], a["doc"].split(":")[0]) for a in added] == [("added-env-undocumented", "README.md")]
    assert "`NOTESYNC_TIMEOUT`" in added[0]["problem"]
    assert "NOTESYNC_TOKEN" in added[0]["problem"]       # the documented sibling it was found next to


def test_documenting_the_name_resolves_it(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    fid = out["docs_drift"]["added"][0]["id"]
    row = "| `--dry-run` | off | print what would be copied |\n"
    out = do_edit(notesync, "README.md", row, row + "| `--verbose` | off | say what is copied |\n")
    assert out["docs_drift"]["resolved"] == [fid]
    assert out["docs_drift"]["still_open"] == 0
    assert hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0) is None


def test_reminder_before_the_turn_ends_names_it(ctx, notesync):
    do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    nudge = hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0)
    assert nudge["action"] == "continue"
    assert "added 1 name that no doc mentions" in nudge["message"]
    assert "--verbose" in nudge["message"]
    assert "no longer match" not in nudge["message"]


def test_removed_and_added_in_one_session_are_told_apart(ctx, notesync):
    do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    out = do_edit(notesync, "notesync/cli.py", TOKEN, ADD_ENV)
    entry = out["docs_drift"]
    assert "new" not in entry and len(entry["added"]) == 1      # the rename was reported by the first edit
    assert entry["still_open"] == 3
    nudge = hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0)
    assert "left 2 places where the docs no longer match the code" in nudge["message"]
    assert "added 1 name that no doc mentions" in nudge["message"]


def test_a_renamed_flag_is_not_also_reported_as_added(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert "added" not in out["docs_drift"]
    assert len(out["docs_drift"]["new"]) == 2


def test_nothing_when_the_docs_were_written_first(ctx, notesync):
    row = "| `--dry-run` | off | print what would be copied |\n"
    edit(notesync, "README.md", row, row + "| `--verbose` | off | say what is copied |\n")
    assert do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG) is None


def test_nothing_when_the_docs_document_no_flag(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = "# notesync\n\nCopies notes. Run `make test` before sending a change.\n"
    files.pop("docs/configuration.md")
    root = make_repo(files)
    assert do_edit(root, "notesync/cli.py", DRY, ADD_FLAG) is None
    assert do_edit(root, "notesync/cli.py", TOKEN, ADD_ENV) is None


def test_environment_variable_needs_a_documented_sibling_with_its_prefix(ctx, notesync):
    new = TOKEN + '    home = os.environ.get("XDG_CACHE_HOME", "")\n    region = os.environ.get("SYNC_REGION", "")\n'
    assert do_edit(notesync, "notesync/cli.py", TOKEN, new) is None


def test_hidden_flags_and_test_code_are_left_alone(ctx, make_repo):
    files = dict(NOTESYNC)
    files["tests/test_cli.py"] = "import argparse\n\np = argparse.ArgumentParser()\n"
    root = make_repo(files)
    hidden = DRY + '    parser.add_argument("--trace-io", action="store_true", help=argparse.SUPPRESS)\n'
    assert do_edit(root, "notesync/cli.py", DRY, hidden) is None
    assert do_edit(root, "tests/test_cli.py", "p = argparse.ArgumentParser()\n",
                   'p = argparse.ArgumentParser()\np.add_argument("--fixture-dir")\n') is None


def test_setting_turns_it_off(notesync):
    hp._reset_for_tests()
    hp.register(FakeCtx({"report_added": False}))
    assert do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG) is None
    assert hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0) is None
    hp._reset_for_tests()


def test_min_confidence_high_leaves_it_out(notesync):
    hp._reset_for_tests()
    hp.register(FakeCtx({"min_confidence": "high"}))
    assert do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG) is None
    hp._reset_for_tests()


def test_ignore_names_applies(notesync):
    hp._reset_for_tests()
    hp.register(FakeCtx({"ignore_names": ["--verbose"]}))
    assert do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG) is None
    hp._reset_for_tests()


def test_tools_see_it_while_the_session_is_open(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    fid = out["docs_drift"]["added"][0]["id"]
    scan = json.loads(ctx.tools["docs_drift_scan"]["handler"]({"path": notesync}, session_id="s1"))
    assert [f["id"] for f in scan["findings"]] == [fid]
    info = json.loads(ctx.tools["docs_drift_explain"]["handler"]({"finding_id": fid, "path": notesync}, session_id="s1"))
    assert info["name"] == "--verbose"
    assert info["what_this_check_means"]
    assert "doc_context" in info and "code_context" in info


def test_it_is_not_a_check_and_whole_repository_scans_do_not_report_it(notesync):
    assert not [c for c in list(CHECKS) + list(ALL_CHECKS) if c.startswith("added-")]
    sc = Scanner(notesync)
    before = sc.scan()
    edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    edit(notesync, "notesync/cli.py", TOKEN, ADD_ENV)
    assert sc.scan().findings == []                                 # default checks
    assert sc.scan(before=before.index).findings == []              # edit-aware, as changed_only runs it
    result, _, problem = sc.scan_changes("HEAD")
    assert result.findings == [] and not problem
    both = sc.scan(before=before.index, added=True).findings
    assert sorted(f.check for f in both) == ["added-env-undocumented", "added-flag-undocumented"]
    assert sc.scan(added=True).findings == []                       # nothing to compare with: nothing to say


def test_several_added_flags_point_at_the_same_place(ctx, notesync):
    more = ADD_FLAG + '    parser.add_argument("--retries", type=int, default=3)\n'
    out = do_edit(notesync, "notesync/cli.py", DRY, more)
    added = out["docs_drift"]["added"]
    assert sorted(a["problem"].split("`")[1] for a in added) == ["--retries", "--verbose"]
    assert {a["doc"] for a in added} == {"README.md:16"}
    assert "added 2 name(s)" in out["docs_drift"]["note"]
    assert os.path.exists(os.path.join(notesync, "README.md"))


def test_a_renamed_variable_is_not_also_reported_as_added(ctx, notesync):
    out = do_edit(notesync, "notesync/cli.py", '"NOTESYNC_TOKEN"', '"NOTESYNC_API_TOKEN"')
    assert "added" not in out["docs_drift"]
    assert {n["check"] for n in out["docs_drift"]["new"]} == {"env-undefined"}
    for rel in ("README.md", "docs/configuration.md"):
        edit(notesync, rel, "NOTESYNC_TOKEN", "NOTESYNC_API_TOKEN")
    assert hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0) is None


def test_old_name_deleted_from_the_docs_leaves_the_new_one_to_report(ctx, notesync):
    do_edit(notesync, "notesync/cli.py", '"--dry-run"', '"--simulate"')
    edit(notesync, "README.md", "notesync ./notes --dry-run\n", "")
    edit(notesync, "README.md", "| `--dry-run` | off | print what would be copied |\n", "")
    nudge = hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0)
    assert "added 1 name that no doc mentions" in nudge["message"] and "--simulate" in nudge["message"]


def test_an_edit_that_leaves_the_file_unparsable_does_not_resolve_it(ctx, notesync):
    """Seen in a recorded session on encode/uvicorn: a patch broke the indentation of the file
    that defines the new flag, and the plugin reported the open note as resolved."""
    out = do_edit(notesync, "notesync/cli.py", DRY, ADD_FLAG)
    fid = out["docs_drift"]["added"][0]["id"]
    body = "    args = build_parser().parse_args(argv)\n"
    broken = "args = build_parser().parse_args(argv)\n"
    out = do_edit(notesync, "notesync/cli.py", body, broken) or {}            # the file no longer parses
    with open(cli_path(notesync), encoding="utf-8") as fh:
        with pytest.raises(SyntaxError):
            compile(fh.read(), "cli.py", "exec")
    assert "resolved" not in out.get("docs_drift", {})
    out = do_edit(notesync, "notesync/cli.py", broken, body) or {}            # repaired
    assert "added" not in out.get("docs_drift", {}) and "resolved" not in out.get("docs_drift", {})
    row = "| `--dry-run` | off | print what would be copied |\n"
    out = do_edit(notesync, "README.md", row, row + "| `--verbose` | off | say what is copied |\n")
    assert out["docs_drift"]["resolved"] == [fid]


def test_a_flag_deleted_by_the_edit_that_breaks_the_file_is_not_kept(ctx, notesync):
    sc = Scanner(notesync)
    assert "dry-run" in sc.scan().index.flag_facts
    edit(notesync, "notesync/cli.py", DRY, "  broken = (\n")
    assert "dry-run" not in sc.scan().index.flag_facts

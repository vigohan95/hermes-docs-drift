"""``python -m docsdrift``: exit codes and output forms. Also: this repository's own docs are clean."""

import json
import os
import re
import subprocess
import sys

from conftest import NOTESYNC, ROOT, edit
from docsdrift.cli import main
from docsdrift.scan import Scanner


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_clean_repository_exits_zero(capsys, notesync):
    code, out, _ = run(capsys, notesync)
    assert code == 0
    assert out.startswith("docs-drift: 0 findings (2 doc files checked against")


def test_findings_exit_one_and_show_both_sides(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--timeout` | `30` |", "| `--timeout` | `60` |")
    root = make_repo(files)
    code, out, _ = run(capsys, root)
    assert code == 1
    assert "README.md:15  default-mismatch  [high]  DD-" in out
    assert "  docs: README.md:15  | `--timeout` | `60` |" in out
    assert "  code: notesync/cli.py:9  " in out
    assert "  fix:  " in out
    assert run(capsys, root, "--exit-zero")[0] == 0


def test_json_output(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files)
    code, out, _ = run(capsys, root, "--json")
    data = json.loads(out)
    assert code == 1
    assert data["summary"]["by_check"] == {"path-missing": 1}
    assert data["findings"][0]["doc"] == "README.md:28"


def test_since_head_reports_only_new_drift(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files)
    assert run(capsys, root, "--since", "HEAD")[0] == 0
    edit(root, "notesync/cli.py", '"--output-dir"', '"--dest"')
    code, out, _ = run(capsys, root, "--since", "HEAD")
    assert code == 1
    assert out.startswith("docs-drift (new since HEAD): 2 findings")
    assert "missing.md" not in out
    assert "replace `--output-dir` with `--dest`" in out


def test_explain(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files)
    fid = Scanner(root).scan().findings[0].id
    code, out, _ = run(capsys, root, "--explain", fid)
    assert code == 0 and "why this was reported:" in out and "docs:" in out
    code, out, _ = run(capsys, root, "--explain", fid, "--json")
    assert json.loads(out)["id"] == fid
    code, _, err = run(capsys, root, "--explain", "DD-00000000")
    assert code == 2 and "no finding with id" in err


def test_checks_option_and_listing(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\nSee `notesync/nope.py`.\n"
    root = make_repo(files)
    assert run(capsys, root)[0] == 0
    assert run(capsys, root, "--checks", "all")[0] == 1
    assert run(capsys, root, "--checks", "+path-ref-missing")[0] == 1
    code, out, _ = run(capsys, "--list-checks")
    assert code == 0
    assert re.search(r"^path-missing\s+default", out, re.M)
    assert re.search(r"^path-ref-missing\s+opt-in", out, re.M)


def test_no_git_flag(capsys, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files, use_git=False)
    assert run(capsys, root, "--no-git")[0] == 1


def test_module_entry_point_runs(notesync):
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-m", "docsdrift", notesync, "--json"],
                         capture_output=True, text=True, env=env, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["summary"]["findings"] == 0


def test_this_repository_has_no_drift():
    """The plugin's own README, examples and docs must pass every check the plugin has."""
    result = Scanner(ROOT).scan(checks="all")
    assert result.incomplete is False
    assert [f.brief() for f in result.findings] == []

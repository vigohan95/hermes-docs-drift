"""Whole-repository checks: one positive case each, and the guards that keep them quiet."""

import os

import pytest

from conftest import NOTESYNC, by_check, write_files
from docsdrift.model import CHECKS
from docsdrift.scan import DEFAULT_CHECKS, OPT_IN_CHECKS, Scanner, apply_ignores, explain, find_root, resolve_checks


def scan(root, **kw):
    kw.setdefault("use_git", True)
    use_git = kw.pop("use_git")
    return Scanner(root, use_git=use_git).scan(**kw)


def names(result, check):
    return sorted(f.name for f in by_check(result, check))


# ------------------------------------------------------------------ baseline
def test_clean_project_has_no_findings(notesync):
    result = scan(notesync, checks="all")
    assert result.findings == []
    assert result.incomplete is False
    assert result.doc_files == 2
    assert result.code_files >= 2


def test_default_and_opt_in_checks_cover_every_check():
    assert set(DEFAULT_CHECKS) | set(OPT_IN_CHECKS) == set(CHECKS)
    assert not set(DEFAULT_CHECKS) & set(OPT_IN_CHECKS)


# ------------------------------------------------------------------ cli flags
def test_flag_in_docs_that_the_code_does_not_define(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("notesync ./notes --dry-run", "notesync ./notes --verbose")
    root = make_repo(files)
    found = by_check(scan(root), "cli-flag-undefined")
    assert [f.name for f in found] == ["--verbose"]
    f = found[0]
    assert (f.doc_file, f.doc_line) == ("README.md", 7)
    assert "--verbose" in f.doc_quote
    assert f.id.startswith("DD-") and len(f.id) == 11
    assert f.why


def test_flags_of_other_programs_are_not_checked(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n```sh\npip install --upgrade notesync\ndocker run --rm -it image\ngit commit --amend\n```\n"
    assert scan(make_repo(files)).findings == []


def test_negated_flag_is_accepted_when_the_positive_exists(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n```sh\nnotesync ./notes --no-dry-run\n```\n"
    assert by_check(scan(make_repo(files)), "cli-flag-undefined") == []


def test_flag_on_a_deprecated_line_is_not_reported(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\nThe deprecated form `notesync ./notes --target ./x` still works for now.\n"
    assert by_check(scan(make_repo(files)), "cli-flag-undefined") == []


def test_flag_in_a_changelog_section_is_not_reported(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n## Changelog\n\n```sh\nnotesync ./notes --target ./x\n```\n"
    assert by_check(scan(make_repo(files)), "cli-flag-undefined") == []


def test_flag_defined_only_as_a_string_elsewhere_is_trusted(make_repo):
    files = dict(NOTESYNC)
    files["notesync/extra.py"] = "FLAGS = ['--verbose']\n"
    files["README.md"] = files["README.md"].replace("notesync ./notes --dry-run", "notesync ./notes --verbose")
    assert by_check(scan(make_repo(files)), "cli-flag-undefined") == []


def test_python_dash_m_invocation_is_ours(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n```sh\npython -m notesync.cli ./notes --quiet\n```\n"
    assert names(scan(make_repo(files)), "cli-flag-undefined") == ["--quiet"]


def test_project_without_any_flag_definitions_is_not_checked(make_repo):
    root = make_repo({
        "pyproject.toml": '[project]\nname = "tool"\n\n[project.scripts]\ntool = "tool:main"\n',
        "tool.py": "def main():\n    pass\n",
        "README.md": "# tool\n\n```sh\ntool --anything\n```\n",
    })
    assert scan(root).findings == []


# ------------------------------------------------------------------ env
def test_env_variable_in_docs_that_nothing_reads(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace(
        "Set `NOTESYNC_TOKEN` to enable the remote upload.",
        "Set `NOTESYNC_TOKEN` to enable the remote upload and `NOTESYNC_REGION` to pick a region.")
    found = by_check(scan(make_repo(files)), "env-undefined")
    assert [f.name for f in found] == ["NOTESYNC_REGION"]
    assert found[0].doc_file == "README.md"


def test_env_variable_without_our_prefix_is_not_reported(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\nSet `AWS_REGION` and `HTTPS_PROXY` if you need them.\n"
    assert by_check(scan(make_repo(files)), "env-undefined") == []


def test_env_variable_used_in_a_shell_script_counts_as_read(make_repo):
    files = dict(NOTESYNC)
    files["scripts/run.sh"] = "#!/bin/sh\necho \"$NOTESYNC_REGION\"\n"
    files["README.md"] += "\nSet `NOTESYNC_REGION` to pick a region.\n"
    assert by_check(scan(make_repo(files)), "env-undefined") == []


# ------------------------------------------------------------------ defaults
def test_documented_default_differs_from_the_code(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--timeout` | `30` |", "| `--timeout` | `60` |")
    found = by_check(scan(make_repo(files)), "default-mismatch")
    assert [f.name for f in found] == ["--timeout"]
    f = found[0]
    assert f.doc_line == 15
    assert (f.code_file, f.code_line) == ("notesync/cli.py", 9)
    assert "30" in f.message and "60" in f.message


def test_equal_defaults_written_differently_are_not_reported(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--output-dir` | `./out` |", "| `--output-dir` | \"./out\" |")
    files["README.md"] = files["README.md"].replace("| `--timeout` | `30` |", "| `--timeout` | 30 seconds |")
    assert by_check(scan(make_repo(files)), "default-mismatch") == []


def test_table_without_a_default_column_is_not_a_default_claim(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n| Option | Example |\n| --- | --- |\n| `--timeout` | `90` |\n"
    assert by_check(scan(make_repo(files)), "default-mismatch") == []


# ------------------------------------------------------------------ npm / make
WEB = {
    "package.json": '{\n  "name": "web",\n  "scripts": {\n    "build": "tsc",\n    "test": "vitest"\n  }\n}\n',
    "src/index.ts": "export const x = 1\n",
    "Makefile": ".PHONY: build\n\nbuild:\n\tnpm run build\n",
    "README.md": "# web\n\n```sh\nnpm run build\nnpm test\nmake build\n```\n",
}


def test_npm_script_and_make_target_that_exist_are_fine(make_repo):
    assert scan(make_repo(dict(WEB))).findings == []


def test_npm_script_that_does_not_exist(make_repo):
    files = dict(WEB)
    files["README.md"] += "\n```sh\nnpm run lint\nyarn typecheck\npnpm run build\n```\n"
    result = scan(make_repo(files))
    assert "lint" in names(result, "npm-script-missing")
    assert "build" not in names(result, "npm-script-missing")
    f = [f for f in by_check(result, "npm-script-missing") if f.name == "lint"][0]
    assert f.doc_line == 10
    assert "package.json" in f.message


def test_npm_builtin_commands_are_not_scripts(make_repo):
    files = dict(WEB)
    files["README.md"] += "\n```sh\nnpm install\nnpm ci\nnpm publish\nyarn add left-pad\nnpx vitest run\n```\n"
    assert by_check(scan(make_repo(files)), "npm-script-missing") == []


def test_npm_commands_without_a_package_json_are_not_checked(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n```sh\nnpm run lint\n```\n"
    assert by_check(scan(make_repo(files)), "npm-script-missing") == []


def test_make_target_that_does_not_exist(make_repo):
    files = dict(WEB)
    files["README.md"] += "\n```sh\nmake deploy\nmake -j4 build\n```\n"
    found = by_check(scan(make_repo(files)), "make-target-missing")
    assert [f.name for f in found] == ["deploy"]
    assert found[0].doc_line == 10


def test_make_pattern_rules_and_variables_are_not_targets(make_repo):
    files = dict(WEB)
    files["Makefile"] += "\nout/%.html: %.md\n\ttrue\n"
    files["README.md"] += "\n```sh\nmake out/page.html\nmake build V=1\n```\n"
    assert by_check(scan(make_repo(files)), "make-target-missing") == []


# ------------------------------------------------------------------ paths
def test_link_to_a_missing_file(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\nSee [the guide](docs/guide.md) and ![logo](img/logo.png).\n"
    result = scan(make_repo(files))
    assert names(result, "path-missing") == ["docs/guide.md", "img/logo.png"]


def test_links_that_are_not_repository_files_are_ignored(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += (
        "\n[a](https://example.com/x.md) [b](#usage) [c](mailto:a@example.com) [d](/absolute/site/path)\n"
        "[e](docs/configuration.md#section) [f](docs/) [g](<docs/configuration.md>)\n"
    )
    assert by_check(scan(make_repo(files)), "path-missing") == []


def test_link_is_resolved_relative_to_the_doc(make_repo):
    files = dict(NOTESYNC)
    files["docs/configuration.md"] += "\nBack to [the readme](../README.md) or [nothing](../MISSING.md).\n"
    result = scan(make_repo(files))
    assert names(result, "path-missing") == ["MISSING.md"]
    assert by_check(result, "path-missing")[0].doc_file == "docs/configuration.md"


def test_link_to_an_untracked_but_existing_file_is_fine(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[notes](NOTES.md)\n"
    root = make_repo(files)
    write_files(root, {"NOTES.md": "# notes\n"})
    assert by_check(scan(root), "path-missing") == []


def test_link_to_a_gitignored_build_output_is_not_reported(make_repo):
    files = dict(NOTESYNC)
    files[".gitignore"] = "site/\n"
    files["README.md"] += "\n[the built site](site/index.html)\n"
    assert by_check(scan(make_repo(files)), "path-missing") == []


# ------------------------------------------------------------------ opt-in
def test_path_in_inline_code_is_opt_in(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\nThe parser lives in `notesync/cli.py`; helpers are in `notesync/helpers.py`.\n"
    root = make_repo(files)
    assert scan(root).findings == []
    assert names(scan(root, checks="+path-ref-missing"), "path-ref-missing") == ["notesync/helpers.py"]


def test_undocumented_flag_is_opt_in(make_repo):
    files = dict(NOTESYNC)
    files["notesync/cli.py"] = files["notesync/cli.py"].replace(
        '    parser.add_argument("--dry-run", action="store_true")',
        '    parser.add_argument("--dry-run", action="store_true")\n'
        '    parser.add_argument("--checksum", action="store_true")')
    root = make_repo(files)
    assert scan(root).findings == []
    assert names(scan(root, checks="all"), "cli-flag-undocumented") == ["--checksum"]


# ------------------------------------------------------------------ options
def test_resolve_checks():
    assert resolve_checks(None) == list(DEFAULT_CHECKS)
    assert resolve_checks("all") == list(CHECKS)
    assert resolve_checks("path-missing,env-undefined") == ["path-missing", "env-undefined"]
    assert sorted(resolve_checks(["+path-ref-missing"])) == sorted(list(DEFAULT_CHECKS) + ["path-ref-missing"])
    assert "path-missing" not in resolve_checks("-path-missing")
    assert resolve_checks("no-such-check") == list(DEFAULT_CHECKS)


def test_only_the_requested_checks_run(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n\n```sh\nnotesync . --nope\n```\n"
    root = make_repo(files)
    assert set(scan(root).counts()) == {"path-missing", "cli-flag-undefined"}
    assert set(scan(root, checks="path-missing").counts()) == {"path-missing"}


def test_ids_are_stable_and_do_not_depend_on_the_line(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    a = scan(make_repo(dict(files), name="a"))
    files["README.md"] = "intro line\n\n" + files["README.md"]
    b = scan(make_repo(files, name="b"))
    assert a.ids() == b.ids() and len(a.ids()) == 1
    assert a.findings[0].doc_line < b.findings[0].doc_line


def test_explain_quotes_both_sides(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--timeout` | `30` |", "| `--timeout` | `60` |")
    root = make_repo(files)
    sc = Scanner(root)
    result = sc.scan()
    info = explain(sc, result, result.findings[0].id)
    assert info["check"] == "default-mismatch"
    assert any("--timeout" in line and "60" in line for line in info["doc_context"])
    assert any("default=30" in line for line in info["code_context"])
    assert info["why"] and info["what_this_check_means"]
    assert explain(sc, result, "DD-00000000") is None


def test_apply_ignores_by_name_and_path(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    files["docs/configuration.md"] += "\n[y](gone.md)\n"
    root = make_repo(files)
    assert len(scan(root).findings) == 2
    assert [f.name for f in apply_ignores(scan(root), ["missing.md"], []).findings] == ["docs/gone.md"]
    assert [f.name for f in apply_ignores(scan(root), [], ["docs/*"]).findings] == ["missing.md"]


def test_scan_without_git(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files, use_git=False)
    assert names(scan(root, use_git=False), "path-missing") == ["missing.md"]


def test_repository_without_docs(make_repo):
    root = make_repo({"pyproject.toml": '[project]\nname = "x"\n', "x.py": "print(1)\n"})
    result = scan(root)
    assert result.findings == []
    assert any("No Markdown" in n for n in result.notes)


def test_time_budget_marks_the_scan_incomplete(make_repo, notesync):
    result = Scanner(notesync).scan(budget_s=0.0)
    assert result.incomplete is True
    assert result.findings == []


def test_unreadable_and_binary_files_do_not_break_the_scan(make_repo):
    files = dict(NOTESYNC)
    root = make_repo(files)
    with open(os.path.join(root, "notesync", "blob.py"), "wb") as fh:
        fh.write(b"\xff\xfe\x00\x00 not text \x00\x01")
    with open(os.path.join(root, "docs", "bad.md"), "wb") as fh:
        fh.write(b"# bad \xff\xfe [x](nope.md)\n")
    result = scan(root)
    assert result.incomplete is False


def test_find_root_climbs_to_the_project(notesync):
    assert os.path.samefile(find_root(os.path.join(notesync, "docs", "configuration.md")), notesync)
    assert os.path.samefile(find_root(os.path.join(notesync, "notesync")), notesync)


def test_find_root_strict_outside_a_project(tmp_path):
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    got = find_root(str(lonely), strict=True)
    # tmp_path itself is not a project; a stray marker above it on this machine would make this not None
    if got is not None:
        pytest.skip(f"a project marker exists above the temp directory: {got}")
    assert got is None

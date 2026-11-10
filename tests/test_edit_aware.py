"""Findings that depend on what an edit removed (``before=`` and ``scan_changes``)."""

import os

from conftest import NOTESYNC, by_check, edit, git, write_files
from docsdrift.scan import Scanner, explain

WEB = {
    "package.json": '{\n  "name": "web",\n  "scripts": {\n    "build": "tsc",\n    "test": "vitest"\n  }\n}\n',
    "src/index.ts": "export const port = process.env.WEB_PORT || '3000'\n",
    "Makefile": ".PHONY: build\n\nbuild:\n\tnpm run build\n\nserve:\n\ttrue\n",
    "README.md": (
        "# web\n\nRun `npm run build` first.\n\n```sh\nnpm run build\nmake serve\n```\n\n"
        "The port comes from `WEB_PORT`.\n\nSee [the entry point](src/index.ts).\n"
    ),
}


def rename_flag(root):
    edit(root, "notesync/cli.py", '"--output-dir"', '"--dest"')


def test_renamed_flag_is_reported_with_the_new_name(notesync):
    sc = Scanner(notesync)
    before = sc.scan()
    assert before.findings == []
    rename_flag(notesync)
    after = sc.scan(before=before.index)
    found = by_check(after, "cli-flag-undefined")
    assert sorted((f.doc_file, f.doc_line) for f in found) == [("README.md", 6), ("docs/configuration.md", 5)]
    readme = [f for f in found if f.doc_file == "README.md"][0]
    assert readme.name == "--output-dir"
    assert "removed from the code by the edit" in readme.message
    assert readme.code_file == "notesync/cli.py"
    assert "--dest" in readme.suggestion
    assert 14 in readme.doc_lines                      # the options table row is listed too


def test_whole_repo_scan_reports_the_same_ids_without_the_hint(notesync):
    sc = Scanner(notesync)
    before = sc.scan()
    rename_flag(notesync)
    plain = sc.scan()
    aware = sc.scan(before=before.index)
    assert plain.ids() == aware.ids()
    assert all("--dest" not in f.suggestion for f in plain.findings)


def test_flag_only_mentioned_in_prose_needs_the_edit(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("notesync ./notes --dry-run\n", "")
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    edit(root, "notesync/cli.py", '"--dry-run"', '"--simulate"')
    # the table row is the only mention: a whole-repo scan has no command to anchor it to
    assert by_check(sc.scan(), "cli-flag-undefined") == []
    found = by_check(sc.scan(before=before.index), "cli-flag-undefined")
    assert [(f.name, f.doc_file) for f in found] == [("--dry-run", "README.md")]


def test_removed_flag_on_a_history_line_is_not_reported(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace(
        "notesync ./notes --dry-run\n", "").replace(
        "| `--dry-run` | off | print what would be copied |", "`--dry-run` is deprecated and will go away.")
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    edit(root, "notesync/cli.py", '"--dry-run"', '"--simulate"')
    assert by_check(sc.scan(before=before.index), "cli-flag-undefined") == []


def test_flag_that_still_exists_elsewhere_was_not_removed(make_repo):
    files = dict(NOTESYNC)
    files["notesync/other.py"] = "import argparse\np = argparse.ArgumentParser()\np.add_argument('--output-dir')\n"
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    rename_flag(root)
    assert sc.scan(before=before.index).findings == []


def test_removed_env_variable(notesync):
    sc = Scanner(notesync)
    before = sc.scan()
    edit(notesync, "notesync/cli.py", '"NOTESYNC_TOKEN"', '"NOTESYNC_API_KEY"')
    found = by_check(sc.scan(before=before.index), "env-undefined")
    assert sorted(f.doc_file for f in found) == ["README.md", "docs/configuration.md"]
    f = found[0]
    assert f.name == "NOTESYNC_TOKEN"
    assert "NOTESYNC_API_KEY" in f.suggestion
    assert f.code_file == "notesync/cli.py"


def test_removed_env_variable_without_project_prefix_needs_the_edit(make_repo):
    root = make_repo(dict(WEB))
    sc = Scanner(root)
    before = sc.scan()
    assert before.findings == []
    edit(root, "src/index.ts", "process.env.WEB_PORT", "process.env.HTTP_PORT")
    found = by_check(sc.scan(before=before.index), "env-undefined")
    assert [(f.name, f.doc_line) for f in found] == [("WEB_PORT", 10)]
    assert "HTTP_PORT" in found[0].suggestion


def test_removed_npm_script_and_make_target(make_repo):
    root = make_repo(dict(WEB))
    sc = Scanner(root)
    before = sc.scan()
    edit(root, "package.json", '"build": "tsc"', '"compile": "tsc"')
    edit(root, "Makefile", "serve:", "start:")
    after = sc.scan(before=before.index)
    npm = by_check(after, "npm-script-missing")
    assert [(f.name, f.doc_line) for f in npm] == [("build", 3)]
    assert 6 in npm[0].doc_lines
    assert "removed from package.json by the edit" in npm[0].message
    assert "compile" in npm[0].suggestion
    make = by_check(after, "make-target-missing")
    assert [(f.name, f.doc_line) for f in make] == [("serve", 7)]
    assert "start" in make[0].suggestion


def test_moved_file_is_reported_with_its_new_place(make_repo):
    root = make_repo(dict(WEB))
    sc = Scanner(root)
    before = sc.scan()
    os.makedirs(os.path.join(root, "lib"))
    os.replace(os.path.join(root, "src", "index.ts"), os.path.join(root, "lib", "index.ts"))
    found = by_check(sc.scan(before=before.index), "path-missing")
    assert [(f.name, f.doc_line) for f in found] == [("src/index.ts", 12)]
    assert "lib/index.ts" in found[0].suggestion


def test_explain_a_removed_by_edit_finding(notesync):
    sc = Scanner(notesync)
    before = sc.scan()
    rename_flag(notesync)
    after = sc.scan(before=before.index)
    info = explain(sc, after, after.findings[0].id)
    assert any("--output-dir" in line for line in info["doc_context"])
    assert any("--dest" in line for line in info["code_context"])
    assert any("before the edit" in w for w in info["why"])


# ------------------------------------------------------------------ scan_changes
def test_scan_changes_reports_only_what_the_uncommitted_edit_caused(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[old problem](missing.md)\n"
    root = make_repo(files)
    sc = Scanner(root)
    assert [f.name for f in sc.scan().findings] == ["missing.md"]
    rename_flag(root)
    result, resolved, problem = sc.scan_changes("HEAD")
    assert problem is None and resolved == []
    assert {f.check for f in result.findings} == {"cli-flag-undefined"}
    assert all(f.name == "--output-dir" for f in result.findings)


def test_scan_changes_lists_findings_the_edit_resolved(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[old problem](missing.md)\n"
    root = make_repo(files)
    sc = Scanner(root)
    write_files(root, {"missing.md": "# now it exists\n"})
    result, resolved, problem = sc.scan_changes("HEAD")
    assert result.findings == [] and problem is None
    assert [f.name for f in resolved] == ["missing.md"]


def test_scan_changes_with_nothing_changed(notesync):
    result, resolved, problem = Scanner(notesync).scan_changes("HEAD")
    assert result.findings == [] and resolved == [] and problem is None
    assert any("No files differ" in n for n in result.notes)


def test_scan_changes_sees_a_deleted_file(notesync):
    os.remove(os.path.join(notesync, "docs", "configuration.md"))
    result, _, _ = Scanner(notesync).scan_changes("HEAD")
    found = by_check(result, "path-missing")
    assert [(f.name, f.doc_file) for f in found] == [("docs/configuration.md", "README.md")]


def test_scan_changes_after_the_edit_is_committed_is_quiet(notesync):
    rename_flag(notesync)
    git(notesync, "commit", "-qam", "rename")
    sc = Scanner(notesync)
    result, _, _ = sc.scan_changes("HEAD")
    assert result.findings == []
    # ... and the whole-repo scan still shows the stale docs
    assert len(sc.scan().findings) == 2
    older, _, _ = sc.scan_changes("HEAD~1")
    assert len(older.findings) == 2


def test_scan_changes_without_git_shows_everything_and_says_so(make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[x](missing.md)\n"
    root = make_repo(files, use_git=False)
    result, resolved, problem = Scanner(root, use_git=False).scan_changes("HEAD")
    assert [f.name for f in result.findings] == ["missing.md"]
    assert problem and "not a git repository" in problem


def test_baseline_overlay_does_not_stick(notesync):
    sc = Scanner(notesync)
    rename_flag(notesync)
    first, _, _ = sc.scan_changes("HEAD")
    assert len(first.findings) == 2
    # the baseline pass read the old cli.py from git; the next plain scan must see the file on disk
    assert len(sc.scan().findings) == 2
    again, _, _ = sc.scan_changes("HEAD")
    assert again.ids() == first.ids()


def test_fixing_the_docs_clears_the_findings(notesync):
    sc = Scanner(notesync)
    before = sc.scan()
    rename_flag(notesync)
    assert len(sc.scan(before=before.index).findings) == 2
    edit(notesync, "README.md", "--output-dir", "--dest")
    edit(notesync, "docs/configuration.md", "--output-dir", "--dest")
    assert sc.scan(before=before.index).findings == []
    assert sc.scan_changes("HEAD")[0].findings == []


# ------------------------------------------------------------------ names only the edit-aware path knows
ZO = {
    "Cargo.toml": """
        [package]
        name = "zo"
        version = "0.1.0"
        """,
    "src/config.rs": """
        use std::env;

        pub fn maxage() -> Option<std::ffi::OsString> {
            env::var_os("_ZO_MAXAGE")
        }

        pub fn data_dir() -> Option<std::ffi::OsString> {
            env::var_os("_ZO_DATA_DIR")
        }
        """,
    "README.md": """
        # zo

        ## Environment variables

        - `_ZO_DATA_DIR`: where the database is kept.
        - `_ZO_MAXAGE`: the total age after which entries are deleted.
        """,
}


def test_removed_variable_whose_name_starts_with_an_underscore(make_repo):
    root = make_repo(dict(ZO))
    sc = Scanner(root)
    before = sc.scan(checks="all")
    assert before.findings == []
    edit(root, "src/config.rs", '"_ZO_MAXAGE"', '"_ZO_MAX_AGE"')
    found = by_check(sc.scan(before=before.index), "env-undefined")
    assert [(f.name, f.doc_file, f.doc_line) for f in found] == [("_ZO_MAXAGE", "README.md", 6)]
    assert "before the edit the code read `_ZO_MAXAGE` at src/config.rs:4" in found[0].why


def test_underscore_variable_still_written_in_the_code_was_not_removed(make_repo):
    files = dict(ZO)
    files["src/help.rs"] = 'pub const HELP: &str = "_ZO_MAXAGE  maximum total age";\n'
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    edit(root, "src/config.rs", '"_ZO_MAXAGE"', '"_ZO_MAX_AGE"')
    assert by_check(sc.scan(before=before.index), "env-undefined") == []


def test_plain_scan_does_not_know_underscore_variables(make_repo):
    files = dict(ZO)
    files["README.md"] = ZO["README.md"] + "        - `_ZO_GONE`: read by nothing.\n"
    root = make_repo(files)
    assert Scanner(root).scan(checks="all").findings == []


CLICKAPP = {
    "pyproject.toml": """
        [project]
        name = "chat"
        version = "0.1.0"

        [project.scripts]
        chat = "chat.cli:main"
        """,
    "chat/__init__.py": "",
    "chat/cli.py": """
        import os

        import click


        def setting(name):
            return os.environ.get(name.upper())


        @click.command()
        @click.option("--tools-debug", is_flag=True, envvar="CHAT_TOOLS_DEBUG", help="show tool calls")
        @click.option("--key", envvar=["CHAT_KEY", "CHAT_API_KEY"], help="the API key")
        def main(tools_debug, key):
            click.echo(str(tools_debug) + str(key))
        """,
    "README.md": """
        # chat

        Add `--tools-debug` to see the tool calls. You can also set the `CHAT_TOOLS_DEBUG`
        environment variable to `1`.

        The key is read from `--key`, `CHAT_KEY` or `CHAT_API_KEY`.
        """,
}


def test_removed_click_envvar_binding(make_repo):
    root = make_repo(dict(CLICKAPP))
    sc = Scanner(root)
    before = sc.scan(checks="all")
    assert before.findings == []
    edit(root, "chat/cli.py", 'envvar="CHAT_TOOLS_DEBUG"', 'envvar="CHAT_DEBUG_TOOLS"')
    found = by_check(sc.scan(before=before.index), "env-undefined")
    assert [(f.name, f.doc_file, f.doc_line) for f in found] == [("CHAT_TOOLS_DEBUG", "README.md", 3)]
    assert "before the edit an option was bound to `CHAT_TOOLS_DEBUG` with envvar= at chat/cli.py:11" in found[0].why


def test_removed_name_from_a_click_envvar_list(make_repo):
    root = make_repo(dict(CLICKAPP))
    sc = Scanner(root)
    before = sc.scan()
    edit(root, "chat/cli.py", 'envvar=["CHAT_KEY", "CHAT_API_KEY"]', 'envvar="CHAT_KEY"')
    found = by_check(sc.scan(before=before.index), "env-undefined")
    assert [(f.name, f.doc_line) for f in found] == [("CHAT_API_KEY", 6)]


def test_click_envvar_binding_changes_nothing_in_a_plain_scan(make_repo):
    files = dict(CLICKAPP)
    files["chat/cli.py"] = CLICKAPP["chat/cli.py"].replace('envvar="CHAT_TOOLS_DEBUG", ', "")
    with_binding = Scanner(make_repo(dict(CLICKAPP))).scan(checks="all")
    without = Scanner(make_repo(files)).scan(checks="all")
    assert with_binding.findings == []
    # The docs name a variable nothing binds any more. Without the code as it was before, a
    # plain scan cannot tell that from a name the code builds (``setting()`` above): withheld.
    assert without.findings == []
    assert without.suppressed.get("env-maybe-derived-from-settings-field") == 1

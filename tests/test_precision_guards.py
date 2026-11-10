"""Guards added after reading the findings of real repositories.

Each test is the reduced form of a false report or a miss seen on a real
repository; the comment names the repository it came from. The README section
"Measured precision" says which run each group of guards followed.
"""

import os

import pytest

from conftest import NOTESYNC, by_check, edit
from docsdrift.checks import _leads_item, _listing_flags
from docsdrift.scan import Scanner


def names(result, check="cli-flag-undefined"):
    return sorted(f.name for f in by_check(result, check))


def with_readme(extra):
    files = dict(NOTESYNC)
    files["README.md"] += extra
    return files


# ------------------------------------------------- a name that survives in the code
def test_whole_repo_scan_keeps_quiet_when_the_name_survives_in_code(make_repo):
    # casey/just: `--file` in a user recipe; the word is an identifier all over the code
    files = dict(NOTESYNC)
    files["notesync/sync.py"] = "verbose = False\n"
    files["README.md"] = files["README.md"].replace("notesync ./notes --dry-run", "notesync ./notes --verbose")
    result = Scanner(make_repo(files)).scan()
    assert names(result) == []
    assert result.suppressed.get("flag-has-loose-trace") == 1


def test_edit_that_renames_only_the_flag_string_is_still_reported(make_repo):
    files = dict(NOTESYNC)
    files["notesync/cli.py"] = files["notesync/cli.py"].replace("args.dry_run", "args.dry_run or False")
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    assert before.findings == []
    edit(root, "notesync/cli.py", '"--dry-run"', '"--simulate", dest="dry_run"')
    # the identifier dry_run is still there, so a scan that does not know about the edit says nothing
    assert names(sc.scan()) == []
    found = by_check(sc.scan(before=before.index), "cli-flag-undefined")
    assert [(f.name, f.doc_file, f.doc_line) for f in found] == [("--dry-run", "README.md", 7)]
    assert "--simulate" in found[0].suggestion


# ------------------------------------------------- option lists
# three options the code defines, as list items: enough for the list to count as this project's own
OPTION_LIST = "\n- `--output-dir`: where the copies go\n- `--timeout`: seconds to wait\n- `--dry-run`: print only\n"


def test_option_that_leads_its_list_item_is_a_claim(make_repo):
    root = make_repo(with_readme(OPTION_LIST + "- `--checksum`: compare file hashes\n"))
    assert names(Scanner(root).scan()) == ["--checksum"]


def test_flag_mentioned_inside_a_sentence_of_a_list_item_is_not_a_claim(make_repo):
    # yt-dlp/yt-dlp README.md:168: "... installed with pip's `--pre` flag"
    root = make_repo(with_readme(OPTION_LIST + "- Nightly builds can be installed with pip's `--pre` flag.\n"))
    assert names(Scanner(root).scan()) == []


@pytest.mark.parametrize("line,flag,expected", [
    ("* `--pre`: allow pre-releases", "`--pre`", True),
    ("- `-p`, `--pre`: allow pre-releases", "`--pre`", True),
    ("### `--pre`", "`--pre`", True),
    ("1. `--pre` allows pre-releases", "`--pre`", True),
    ("| `--pre` | off | allow pre-releases |", "`--pre`", True),
    ("| pre-releases | `--pre` | off |", "`--pre`", True),
    ("<tr><td><code>--pre</code></td><td>allow pre-releases</td></tr>", "--pre", True),
    ("* can be installed with pip's `--pre` flag", "`--pre`", False),
    ("| long name | write `--pre` before the package |", "`--pre`", False),
])
def test_leads_item(line, flag, expected):
    assert _leads_item(line, flag) is expected


def test_uppercase_flag_is_a_placeholder(make_repo):
    # casey/just README.md:4807: `--LONG` stands for "any long option"
    root = make_repo(with_readme(OPTION_LIST + "- `--LONG`: any long option\n\n```sh\nnotesync ./notes --NAME\n```\n"))
    assert names(Scanner(root).scan()) == []


# ------------------------------------------------- another program's flags after our command
def test_flags_after_another_program_name_belong_to_that_program(make_repo):
    # simonw/llm docs/setup.md:78: `llm python -m pip install ... --index-url ...`
    extra = "\n```sh\nnotesync python -m pip install --index-url https://example.invalid/simple pkg\n```\n"
    assert names(Scanner(make_repo(with_readme(extra))).scan()) == []


def test_flags_before_another_program_name_are_still_checked(make_repo):
    extra = "\n```sh\nnotesync --quiet python -m pip install --index-url https://example.invalid/simple pkg\n```\n"
    assert names(Scanner(make_repo(with_readme(extra))).scan()) == ["--quiet"]


# ------------------------------------------------- pasted --help output
HELP_README = (
    "# notesync\n\n"
    "```\n"
    "Usage: notesync [options] SOURCE\n\n"
    "  -o, --output-dir DIR   where the copies go\n"
    "      --timeout N        seconds to wait\n"
    "      --dry-run          print what would be copied\n"
    "```\n"
)


def test_removed_flag_in_a_pasted_help_listing_is_reported(make_repo):
    # gitleaks/gitleaks and yt-dlp/yt-dlp list their options as pasted --help output
    files = dict(NOTESYNC)
    files["README.md"] = HELP_README
    del files["docs/configuration.md"]
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    assert before.findings == []
    edit(root, "notesync/cli.py", '"--timeout"', '"--wait"')
    assert names(sc.scan()) == []                      # no command line or option list anchors it
    found = by_check(sc.scan(before=before.index), "cli-flag-undefined")
    assert [(f.name, f.doc_file, f.doc_line) for f in found] == [("--timeout", "README.md", 7)]


@pytest.mark.parametrize("line,expected", [
    ("  -o, --output-dir DIR   where the copies go", ["output-dir"]),
    ("      --timeout N        seconds to wait", ["timeout"]),
    ("  --color, --no-color    turn colour on or off", ["color", "no-color"]),
    ("  -v                     more output, see --timeout", []),
    ("notesync ./notes --dry-run", []),
    ("  writes to the directory given by --output-dir", []),
])
def test_listing_flags(line, expected):
    assert _listing_flags(line) == expected


# ------------------------------------------------- aliases
def test_alias_on_the_line_of_a_documented_flag_is_not_undocumented(make_repo):
    # yt-dlp/yt-dlp: `--convert-subs` is documented; `--convert-sub` and `--convert-subtitles` are its aliases
    files = dict(NOTESYNC)
    files["notesync/cli.py"] = files["notesync/cli.py"].replace('"--dry-run"', '"--dry-run", "--simulate"')
    result = Scanner(make_repo(files)).scan(checks="all")
    assert names(result, "cli-flag-undocumented") == []
    assert result.suppressed.get("alias-of-documented-flag") == 1


# ------------------------------------------------- generated pages named in .gitignore
def test_many_links_to_git_ignored_pages_are_not_reported(make_repo):
    # pdm-project/pdm: docs/reference/cli.md is generated at build time and git-ignored, and linked
    # from dozens of places. An earlier version stopped asking git after 40 links and reported the rest.
    files = dict(NOTESYNC)
    files[".gitignore"] = "docs/reference/\n"
    links = "".join(f"- see [the reference](docs/reference/cli.md#item-{i})\n" for i in range(60))
    files["README.md"] += "\n" + links + "- and [the settings](docs/reference/settings.md)\n- and [a missing page](docs/nope.md)\n"
    result = Scanner(make_repo(files)).scan()
    assert names(result, "path-missing") == ["docs/nope.md"]
    assert result.suppressed.get("link-to-untracked-or-ignored-file") == 2


# ------------------------------------------------- a default that is announced, not current
def test_announced_future_default_is_not_a_default_claim(make_repo):
    # mikefarah/yq: "Set `--flag=true` to get this behaviour (flag will default to true in late 2025)"
    files = dict(NOTESYNC)
    files["docs/configuration.md"] += "\nSet `--timeout=60` for slow disks (the flag will default to 60 in the next release).\n"
    assert names(Scanner(make_repo(files)).scan(), "default-mismatch") == []


def test_sentence_that_uses_the_current_default_is_still_a_claim(make_repo):
    files = dict(NOTESYNC)
    files["docs/configuration.md"] += "\nWithout `--timeout` the tool will use the default of 60 and then give up.\n"
    assert names(Scanner(make_repo(files)).scan(), "default-mismatch") == ["--timeout"]


# ------------------------------------------------- guards added after scanning hermes-agent itself (b7db40d)
def test_default_quoted_inside_a_code_span_equals_the_code(make_repo):
    # website/docs/user-guide/messaging/discord.md:313: the cell is `"safe"`, the code default is 'safe'
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--output-dir` | `./out` |", "| `--output-dir` | `\"./out\"` |")
    assert names(Scanner(make_repo(files)).scan(), "default-mismatch") == []


def test_placeholder_link_target_is_not_a_link(make_repo):
    # optional-skills/productivity/shop/SKILL.md:182: "present it as a [Finish in Shop](url) link"
    extra = "\nShow the address as a [Finish in Shop](url) link. See also [the licence](LICENCE).\n"
    result = Scanner(make_repo(with_readme(extra))).scan()
    assert names(result, "path-missing") == ["LICENCE"]
    assert result.suppressed.get("placeholder-link") == 1


def test_page_whose_links_belong_to_another_tree_is_left_alone(make_repo):
    # optional-skills/mlops/training/unsloth/references/llms-full.md: a documentation site exported into
    # one file; 58 of its links are routes of that site
    files = dict(NOTESYNC)
    files["handbook/guide.md"] = "# Guide\n\n" + "".join(f"- [part {i}](basics/part-{i}.md)\n" for i in range(9))
    files["README.md"] += "\n" + "".join(f"- [page {i}](docs/page-{i}.md)\n" for i in range(3))
    result = Scanner(make_repo(files)).scan()
    # three dead links next to a live one are still reported: they are not most of that page's links ...
    assert names(result, "path-missing") == ["docs/page-0.md", "docs/page-1.md", "docs/page-2.md"]
    assert result.suppressed.get("links-of-page-from-another-tree") == 9


def test_link_to_a_file_the_edit_removed_is_reported_even_on_such_a_page(make_repo):
    files = dict(NOTESYNC)
    files["handbook/guide.md"] = ("# Guide\n\n[the settings](../docs/configuration.md)\n\n"
                                + "".join(f"- [part {i}](basics/part-{i}.md)\n" for i in range(9)))
    root = make_repo(files)
    sc = Scanner(root)
    before = sc.scan()
    assert names(before, "path-missing") == []
    os.remove(os.path.join(root, "docs", "configuration.md"))
    found = by_check(sc.scan(before=before.index), "path-missing")
    assert sorted((f.doc_file, f.name) for f in found) == [
        ("README.md", "docs/configuration.md"), ("handbook/guide.md", "docs/configuration.md")]


def test_env_shaped_word_in_a_quoted_sentence_is_not_a_variable(make_repo):
    # optional-skills/devops/actual-setup/references/opencode.md:69:
    #   opencode run ... "Reply with exactly this text: OPENCODE_ACTUAL_OK"
    extra = "\n```sh\nnotesync ./notes --dry-run \"Reply with exactly this text: NOTESYNC_READY_OK\"\n```\n"
    assert names(Scanner(make_repo(with_readme(extra))).scan(), "env-undefined") == []


@pytest.mark.parametrize("block_line", [
    "export NOTESYNC_REGION=eu",
    "NOTESYNC_REGION=eu notesync ./notes",
    "docker run -e \"NOTESYNC_REGION=eu west\" notesync",
    "echo \"region is $NOTESYNC_REGION\"",
    "{\"env\": {\"NOTESYNC_REGION\": \"eu\"}}",
])
def test_variable_positions_in_a_code_block_are_still_claims(make_repo, block_line):
    root = make_repo(with_readme("\n```\n" + block_line + "\n```\n"))
    assert names(Scanner(root).scan(), "env-undefined") == ["NOTESYNC_REGION"]


def test_flags_after_a_script_that_forwards_its_arguments_are_not_checked(make_repo):
    # optional-skills/software-development/python-debugpy/SKILL.md:101:
    #   scripts/run_tests.sh tests/path/to/test_file.py --showlocals --tb=long   (pytest's flags)
    files = with_readme("\n```sh\nscripts/run_tests.sh tests/test_cli.py --showlocals\nscripts/sync.sh --frobnicate\n```\n")
    files["scripts/run_tests.sh"] = "#!/bin/sh\nexec python -m pytest \"$@\"\n"
    files["scripts/sync.sh"] = "#!/bin/sh\nexec notesync ./notes --dry-run\n"
    result = Scanner(make_repo(files)).scan()
    assert names(result) == ["--frobnicate"]
    assert result.suppressed.get("script-forwards-arguments") == 1

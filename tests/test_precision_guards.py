"""Guards added after the first held-out run (EVIDENCE/labels.json, round 1).

Each test is the reduced form of a false report or a miss seen on a real
repository; the comment names the repository it came from.
"""

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

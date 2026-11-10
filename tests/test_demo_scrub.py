"""The demo drivers must not write the account name or a secret into a transcript."""

import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "demo"))

import scrub as scrub_mod  # noqa: E402
from scrub import ScrubbedStream, scrub  # noqa: E402

WIN_TEMP = "C:\\Users\\Jane Q\\AppData\\Local\\Temp"
WIN_HOME = "C:\\Users\\Jane Q"
KW = dict(temp_dirs=[WIN_TEMP], home_dirs=[WIN_HOME], user="Jane Q")


def clean(text, **kw):
    out = scrub(text, **dict(KW, **kw))
    assert "jane" not in out.lower()
    return out


def test_plain_windows_path():
    assert clean(WIN_TEMP + "\\docs-drift-demo-abc\\notesync") == "%TEMP%\\docs-drift-demo-abc\\notesync"


def test_json_escaped_once_and_twice():
    project = WIN_TEMP + "\\demo\\notesync\\cli.py"
    once = json.dumps({"root": project})
    twice = json.dumps({"output": once})
    assert clean(once) == '{"root": "%TEMP%\\\\demo\\\\notesync\\\\cli.py"}'
    assert "%TEMP%" in clean(twice)


def test_forward_slashes_git_bash_and_case():
    assert clean("C:/Users/Jane Q/AppData/Local/Temp/x") == "%TEMP%/x"
    assert clean("/c/Users/Jane Q/AppData/Local/Temp/x") == "%TEMP%/x"
    assert clean("c:\\users\\jane q\\appdata\\local\\temp\\x") == "%TEMP%\\x"


def test_home_outside_temp_and_longest_rule_first():
    assert clean(WIN_HOME + "\\Documents\\a.txt") == "~\\Documents\\a.txt"
    assert clean("--- a/" + WIN_TEMP + "\\p\\a.py\n+++ b/" + WIN_TEMP + "\\p\\a.py") == \
        "--- a/%TEMP%\\p\\a.py\n+++ b/%TEMP%\\p\\a.py"


def test_account_name_left_in_another_users_path_form():
    assert clean("D:\\Users\\Jane Q\\x") == "D:\\Users\\<user>\\x"


def test_posix_paths():
    kw = dict(temp_dirs=["/var/folders/zz/T"], home_dirs=["/Users/jane"], user="jane")
    assert scrub("/var/folders/zz/T/demo-1/a.py and /Users/jane/.hermes", **kw) == "%TEMP%/demo-1/a.py and ~/.hermes"
    # "/tmp" alone is not rewritten: it names no one and would match inside other paths
    assert scrub("/tmp/demo-1 src/tmp/x", temp_dirs=["/tmp"], home_dirs=["/home/jane"], user="jane") == \
        "/tmp/demo-1 src/tmp/x"


def test_a_path_that_only_starts_like_the_home_is_left_alone():
    assert scrub("C:\\Users\\Jane Quincy\\x", temp_dirs=[], home_dirs=[WIN_HOME], user="") == "C:\\Users\\Jane Quincy\\x"


def test_secret_values_are_replaced():
    key = "ABCDEF0123456789abcdef"
    out = scrub("Authorization: Bearer %s\n--api-key %s" % (key, key), secrets=[key], **KW)
    assert key not in out
    assert out.count("<redacted>") == 2
    # a short or empty value is not treated as a secret
    assert scrub("abc", secrets=["", "abc"], **KW) == "abc"


def test_stream_scrubs_lines_split_across_writes():
    sink = io.StringIO()
    stream = ScrubbedStream(sink, secrets=["s3cr3t-value"], **KW)
    stream.write('"root": "C:\\\\Users\\\\Jane')
    stream.write(' Q\\\\AppData\\\\Local\\\\Temp\\\\d"\nkey s3cr3t')
    stream.write("-value")
    stream.flush()
    text = sink.getvalue()
    assert text == '"root": "%TEMP%\\\\d"\nkey <redacted>'


def test_defaults_come_from_this_machine():
    import tempfile
    here = os.path.join(tempfile.gettempdir(), "docs-drift-demo-x", "notesync")
    out = scrub(here + "\n" + json.dumps(here) + "\n" + here.replace("\\", "/"))
    if scrub_mod._path_pattern(tempfile.gettempdir()) is None:
        pytest.skip("the temp directory here is a bare top-level path such as /tmp")
    for line in out.splitlines():
        assert line.strip('"').startswith("%TEMP%"), out
    home = os.path.expanduser("~")
    if len([p for p in home.replace("\\", "/").split("/") if p]) >= 2:
        assert scrub(os.path.join(home, "x")).startswith("~")


def test_drivers_install_the_scrubber():
    for name in ("run_demo.py", "run_real.py"):
        path = os.path.join(ROOT, "demo", name)
        if not os.path.exists(path):
            pytest.fail(name + " is missing")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        assert "scrub.install(" in source, name


def test_driver_output_has_no_temp_or_home_prefix(tmp_path):
    """Run the stub driver far enough to print the project path through the scrubber."""
    code = (
        "import sys, os, tempfile\n"
        "sys.path.insert(0, %r)\n"
        "import scrub\n"
        "scrub.install(secrets=[os.environ['DD_TEST_SECRET']])\n"
        "work = tempfile.mkdtemp(prefix='docs-drift-demo-')\n"
        "print('kept: ' + work)\n"
        "print('home: ' + os.path.expanduser('~'))\n"
        "print('key: ' + os.environ['DD_TEST_SECRET'])\n"
        "os.rmdir(work)\n"
    ) % os.path.join(ROOT, "demo")
    env = dict(os.environ, DD_TEST_SECRET="not-a-real-secret-0123456789", PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout
    lines = out.splitlines()
    import tempfile
    if scrub_mod._path_pattern(tempfile.gettempdir()) is not None:
        assert lines[0].startswith("kept: %TEMP%"), out
    assert lines[2] == "key: <redacted>"
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= 3:
        assert user.lower() not in lines[0].lower()
    assert scrub_mod is not None


def test_real_model_driver_is_skipped_without_a_key():
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCS_DRIFT_")}
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "demo", "run_real.py")], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert proc.stdout.startswith("skipped: DOCS_DRIFT_API_KEY is not set")


def test_named_directories_are_replaced_in_every_spelling():
    out = scrub(r"D:\work\hermes-home\plugins and D:/work/hermes-home/logs",
                named=[(r"D:\work\hermes-home", "$HERMES_HOME")], temp_dirs=[], home_dirs=[], user="")
    assert out == r"$HERMES_HOME\plugins and $HERMES_HOME/logs"

"""The Hermes wiring, driven the way Hermes drives it: register(ctx), then hooks and handlers."""

import importlib.util
import json
import os
import re
import sys
import types

import pytest

from conftest import NOTESYNC, ROOT, edit, write_files
from docsdrift import hermes_plugin as hp


class FakeCtx:
    """Records what a plugin registers; the same surface Hermes' PluginContext offers."""

    def __init__(self, settings=None):
        self.tools, self.hooks, self.commands = {}, {}, {}
        self.settings = dict(settings or {})

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None,
                      is_async=False, description="", emoji="", override=False):
        self.tools[name] = dict(toolset=toolset, schema=schema, handler=handler, override=override)

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = handler

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


@pytest.fixture
def ctx():
    hp._reset_for_tests()
    c = FakeCtx()
    hp.register(c)
    yield c
    hp._reset_for_tests()


def cli_path(root):
    return os.path.join(root, "notesync", "cli.py")


def write_result(path, n=10):
    return json.dumps({"bytes_written": n, "dirs_created": False, "path": path})


def patch_result(path):
    return json.dumps({"success": True, "diff": "--- a\n+++ b\n", "files_modified": [path]})


def do_edit(root, rel, old, new, session="s1", tool="patch"):
    """One agent edit as Hermes runs it: pre hook, the write itself, transform hook."""
    path = os.path.join(root, *rel.split("/"))
    args = {"mode": "replace", "path": path, "old_string": old, "new_string": new}
    assert hp.on_pre_tool_call(tool_name=tool, args=args, session_id=session, task_id="t", tool_call_id="c") is None
    edit(root, rel, old, new)
    out = hp.on_transform_tool_result(tool_name=tool, args=args, result=patch_result(path),
                                      session_id=session, task_id="t", tool_call_id="c", duration_ms=3, status="ok")
    return None if out is None else json.loads(out)


# ------------------------------------------------------------------ registration
def manifest():
    """Just the list fields this test needs; avoids depending on PyYAML."""
    text = open(os.path.join(ROOT, "plugin.yaml"), encoding="utf-8").read()
    out = {}
    for key in ("provides_tools", "provides_hooks"):
        m = re.search(r"^" + key + r":\s*\n((?:\s+-\s+.+\n)+)", text, re.M)
        out[key] = re.findall(r"-\s+([\w-]+)", m.group(1)) if m else []
    out["version"] = re.search(r"^version:\s*\"?([\w.]+)", text, re.M).group(1)
    return out


def test_registrations_match_the_manifest(ctx):
    m = manifest()
    assert sorted(ctx.tools) == sorted(m["provides_tools"]) == ["docs_drift_explain", "docs_drift_scan"]
    assert sorted(ctx.hooks) == sorted(m["provides_hooks"]) == ["pre_tool_call", "pre_verify", "transform_tool_result"]
    assert list(ctx.commands) == ["drift"]
    assert all(t["override"] is False for t in ctx.tools.values())
    for name, t in ctx.tools.items():
        assert t["schema"]["name"] == name
        assert t["schema"]["parameters"]["type"] == "object"


def test_manifest_version_matches_the_package():
    import docsdrift

    assert manifest()["version"] == docsdrift.__version__


def test_plugin_loads_under_a_namespaced_import_like_hermes_does():
    # the same steps as Hermes' _load_directory_module: an empty parent package, then the plugin
    # directory imported as "<parent>.<slug>" so that only relative imports can work
    parent = "hermes_plugins_test"
    name = parent + ".docs_drift"
    ns = types.ModuleType(parent)
    ns.__path__ = []
    ns.__package__ = parent
    sys.modules[parent] = ns
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name
    module.__path__ = [ROOT]
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        c = FakeCtx()
        module.register(c)
        assert set(c.tools) == {"docs_drift_scan", "docs_drift_explain"}
        assert c.tools["docs_drift_scan"]["handler"].__module__.startswith(name + ".")
    finally:
        for key in [k for k in sys.modules if k == parent or k.startswith(parent + ".")]:
            del sys.modules[key]


def test_registering_without_slash_command_support_still_works():
    class OldCtx(FakeCtx):
        register_command = None

    hp._reset_for_tests()
    c = OldCtx()
    hp.register(c)
    assert len(c.tools) == 2 and len(c.hooks) == 3
    hp._reset_for_tests()


# ------------------------------------------------------------------ hook: the main flow
def test_edit_that_renames_a_flag_is_reported_in_the_tool_result(ctx, notesync):
    data = do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert data["success"] is True                      # the original result is kept
    drift = data["docs_drift"]
    assert sorted(f["doc"] for f in drift["new"]) == ["README.md:6", "docs/configuration.md:5"]
    first = [f for f in drift["new"] if f["doc"] == "README.md:6"][0]
    assert first["check"] == "cli-flag-undefined"
    assert first["code"].startswith("notesync/cli.py:")
    assert "--dest" in first["suggestion"]
    assert first["id"].startswith("DD-")
    assert drift["still_open"] == 2
    assert "2 place(s)" in drift["note"]


def test_fixing_the_docs_reports_resolved_then_goes_quiet(ctx, notesync):
    first = do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    ids = {f["doc"].split(":")[0]: f["id"] for f in first["docs_drift"]["new"]}
    second = do_edit(notesync, "README.md", "--output-dir", "--dest")
    assert second["docs_drift"]["resolved"] == [ids["README.md"]]
    assert second["docs_drift"]["still_open"] == 1
    assert "new" not in second["docs_drift"]
    third = do_edit(notesync, "docs/configuration.md", "--output-dir", "--dest")
    assert third["docs_drift"]["resolved"] == [ids["docs/configuration.md"]]
    assert third["docs_drift"]["still_open"] == 0
    # nothing left: later edits are passed through untouched
    assert do_edit(notesync, "notesync/cli.py", "seconds to wait", "seconds to wait for a lock") is None


def test_open_finding_is_not_repeated_but_survives_unrelated_edits(ctx, notesync):
    assert "docs_drift" in do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    # an unrelated second edit: nothing new to say, so the result is left alone
    assert do_edit(notesync, "notesync/cli.py", "seconds to wait", "seconds to wait for a lock") is None
    # ... but the finding is still tracked, so the finish check still knows about it
    nudge = hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0, final_response="done")
    assert nudge["action"] == "continue"
    assert "README.md:6" in nudge["message"] and "--dest" in nudge["message"]


def test_drift_that_was_there_before_the_session_is_not_blamed_on_the_edit(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[old problem](missing.md)\n"
    root = make_repo(files)
    assert do_edit(root, "notesync/cli.py", "seconds to wait", "seconds to wait for a lock") is None
    data = do_edit(root, "notesync/cli.py", '"--timeout"', '"--wait"')
    assert [f["check"] for f in data["docs_drift"]["new"]] == ["cli-flag-undefined"]


def test_write_file_edit_is_handled_too(ctx, notesync):
    path = cli_path(notesync)
    text = open(path, encoding="utf-8").read().replace('"NOTESYNC_TOKEN"', '"NOTESYNC_API_KEY"')
    args = {"path": path, "content": text}
    hp.on_pre_tool_call(tool_name="write_file", args=args, session_id="w")
    write_files(notesync, {"notesync/cli.py": text})
    out = hp.on_transform_tool_result(tool_name="write_file", args=args, result=write_result(path), session_id="w")
    drift = json.loads(out)["docs_drift"]
    assert {f["check"] for f in drift["new"]} == {"env-undefined"}
    assert all("NOTESYNC_API_KEY" in f["suggestion"] for f in drift["new"])


def test_v4a_patch_paths_are_understood(ctx, notesync, monkeypatch):
    monkeypatch.setattr(hp, "_agent_cwd", lambda: notesync)
    body = "*** Begin Patch\n*** Update File: notesync/cli.py\n@@\n-x\n+y\n*** Move File: docs/a.md -> docs/b.md\n*** End Patch\n"
    paths = hp._edit_paths("patch", {"mode": "patch", "patch": body})
    rel = sorted(os.path.relpath(p, notesync).replace(os.sep, "/") for p in paths)
    assert rel == ["docs/a.md", "docs/b.md", "notesync/cli.py"]
    args = {"mode": "patch", "patch": body}
    hp.on_pre_tool_call(tool_name="patch", args=args, session_id="v")
    edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    out = hp.on_transform_tool_result(tool_name="patch", args=args, result=json.dumps({"success": True}), session_id="v")
    assert len(json.loads(out)["docs_drift"]["new"]) == 2


def test_baseline_falls_back_to_git_when_the_pre_hook_did_not_run(ctx, notesync):
    path = cli_path(notesync)
    edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    out = hp.on_transform_tool_result(tool_name="patch", args={"path": path}, result=patch_result(path), session_id="g")
    drift = json.loads(out)["docs_drift"]
    assert len(drift["new"]) == 2
    assert all("--dest" in f["suggestion"] for f in drift["new"])


def test_without_git_the_first_edit_is_accepted_silently(ctx, make_repo):
    root = make_repo(dict(NOTESYNC), use_git=False)
    path = cli_path(root)
    edit(root, "notesync/cli.py", '"--output-dir"', '"--dest"')
    out = hp.on_transform_tool_result(tool_name="patch", args={"path": path}, result=patch_result(path), session_id="n")
    assert out is None
    # from here on the session has a baseline, so the next edit is compared with it
    data = do_edit(root, "notesync/cli.py", '"--timeout"', '"--wait"', session="n")
    assert [f["doc"] for f in data["docs_drift"]["new"]] == ["README.md:15"]


def test_sessions_do_not_share_state(ctx, notesync):
    assert "docs_drift" in do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"', session="a")
    # another session starts after that edit: for it, the drift was already there
    assert do_edit(notesync, "notesync/cli.py", "seconds to wait", "seconds to wait for a lock", session="b") is None
    assert hp.on_pre_verify(session_id="b", changed_paths=[cli_path(notesync)], attempt=0) is None


# ------------------------------------------------------------------ hook: staying out of the way
def test_other_tools_are_ignored(ctx, notesync):
    assert hp.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}, session_id="s") is None
    assert hp.on_transform_tool_result(tool_name="read_file", args={"path": cli_path(notesync)},
                                       result=json.dumps({"content": "x"}), session_id="s") is None
    assert hp._sessions == {}


def test_failed_edits_are_ignored(ctx, notesync):
    path = cli_path(notesync)
    args = {"path": path}
    hp.on_pre_tool_call(tool_name="patch", args=args, session_id="s")
    edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    for result in (json.dumps({"success": False, "error": "old_string not found"}),
                   json.dumps({"error": "permission denied"}), "not json", None, 17,
                   json.dumps(["a", "list"])):
        assert hp.on_transform_tool_result(tool_name="patch", args=args, result=result, session_id="s") is None


def test_hooks_never_raise_on_strange_input(ctx):
    for args in (None, "a string", 3, [], {"path": None}, {"path": 5}, {"path": ""}, {"path": "\x00bad"},
                 {"path": "Z:/does/not/exist/file.py"}, {"mode": "patch", "patch": None}):
        assert hp.on_pre_tool_call(tool_name="patch", args=args) is None
        assert hp.on_pre_tool_call(tool_name="write_file", args=args, session_id=None, task_id=None) is None
        assert hp.on_transform_tool_result(tool_name="patch", args=args, result=json.dumps({"success": True})) is None
    assert hp.on_pre_tool_call() is None
    assert hp.on_transform_tool_result() is None
    assert hp.on_pre_verify() is None
    assert hp.on_pre_verify(changed_paths="not a list", attempt=None) is None
    assert hp.on_pre_verify(changed_paths=[None, 3, "Z:/nope.py"]) is None


def test_edit_outside_any_project_is_ignored(ctx, tmp_path):
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    if hp.find_root(str(lonely), strict=True) is not None:
        pytest.skip("a project marker exists above the temp directory")
    path = str(lonely / "note.py")
    write_files(str(lonely), {"note.py": "x = 1\n"})
    assert hp.on_pre_tool_call(tool_name="write_file", args={"path": path}) is None
    assert hp.on_transform_tool_result(tool_name="write_file", args={"path": path}, result=write_result(path)) is None


def test_a_crash_inside_the_scan_does_not_reach_hermes(ctx, notesync, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(hp, "_scan", boom)
    path = cli_path(notesync)
    assert hp.on_pre_tool_call(tool_name="patch", args={"path": path}) is None
    assert hp.on_transform_tool_result(tool_name="patch", args={"path": path}, result=patch_result(path)) is None


# ------------------------------------------------------------------ pre_verify
def test_finish_check_nudges_once_and_only_for_open_drift(ctx, notesync):
    changed = [cli_path(notesync)]
    assert hp.on_pre_verify(session_id="s1", changed_paths=changed, attempt=0) is None      # nothing edited yet
    do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    nudge = hp.on_pre_verify(session_id="s1", platform="cli", model="m", coding=True, attempt=0,
                             final_response="Renamed the flag.", changed_paths=changed)
    assert set(nudge) == {"action", "message"} and nudge["action"] == "continue"
    assert "your edits in this session left 2 places" in nudge["message"]
    assert hp.on_pre_verify(session_id="s1", changed_paths=changed, attempt=1) is None      # asked once already
    edit(notesync, "README.md", "--output-dir", "--dest")                                  # fixed outside the edit tools
    edit(notesync, "docs/configuration.md", "--output-dir", "--dest")
    assert hp.on_pre_verify(session_id="s1", changed_paths=changed, attempt=0) is None


# ------------------------------------------------------------------ settings
def test_settings_turn_the_hooks_off(notesync):
    hp._reset_for_tests()
    hp.register(FakeCtx({"report_after_edit": False}))
    assert do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"') is None
    hp._reset_for_tests()

    hp.register(FakeCtx({"nudge_before_finish": "false"}))
    write_files(notesync, {"notesync/cli.py": NOTESYNC["notesync/cli.py"]})
    assert "docs_drift" in do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert hp.on_pre_verify(session_id="s1", changed_paths=[cli_path(notesync)], attempt=0) is None
    hp._reset_for_tests()


def test_ignore_and_limit_settings(notesync):
    hp._reset_for_tests()
    hp.register(FakeCtx({"ignore_paths": "docs/*", "max_reported": 1}))
    data = do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert [f["doc"] for f in data["docs_drift"]["new"]] == ["README.md:6"]
    hp._reset_for_tests()

    hp.register(FakeCtx({"max_reported": 1}))
    write_files(notesync, {"notesync/cli.py": NOTESYNC["notesync/cli.py"]})
    data = do_edit(notesync, "notesync/cli.py", '"--output-dir"', '"--dest"')
    assert len(data["docs_drift"]["new"]) == 1 and data["docs_drift"]["more"] == 1
    hp._reset_for_tests()


def test_bad_setting_values_fall_back_to_defaults():
    hp._reset_for_tests()
    hp.register(FakeCtx({"hook_time_budget_s": "soon", "max_reported": None, "min_confidence": "maybe",
                         "checks": "no-such-check", "ignore_names": 7}))
    assert hp._setting("hook_time_budget_s") == 8
    assert hp._setting("max_reported") == 8
    assert hp._min_confidence() == "medium"
    assert hp._checks_setting() == list(hp.DEFAULT_CHECKS)
    assert hp._setting("ignore_names") == []

    class Broken:
        def get_config(self, key, default=None):
            raise RuntimeError("config store is gone")

    hp._ctx = Broken()
    assert hp._setting("max_reported") == 8
    hp._reset_for_tests()


# ------------------------------------------------------------------ tools
def call(ctx, name, args, **kw):
    return json.loads(ctx.tools[name]["handler"](args, **kw))


def test_scan_tool_on_a_clean_repository(ctx, notesync):
    data = call(ctx, "docs_drift_scan", {"path": notesync})
    assert data["summary"]["findings"] == 0 and data["findings"] == []
    assert data["summary"]["doc_files_checked"] == 2
    assert data["checks_run"] == list(hp.DEFAULT_CHECKS)
    assert "next" not in data


def test_scan_tool_reports_findings_and_explain_shows_both_sides(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("| `--timeout` | `30` |", "| `--timeout` | `60` |")
    root = make_repo(files)
    data = call(ctx, "docs_drift_scan", {"path": os.path.join(root, "docs")})        # any path inside the repo
    assert data["summary"]["by_check"] == {"default-mismatch": 1}
    f = data["findings"][0]
    assert (f["doc"], f["code"]) == ("README.md:15", "notesync/cli.py:9")
    info = call(ctx, "docs_drift_explain", {"finding_id": f["id"], "path": root})
    assert info["id"] == f["id"]
    assert any("60" in line for line in info["doc_context"])
    assert any("default=30" in line for line in info["code_context"])


def test_scan_tool_defaults_to_the_session_directory(ctx, notesync, monkeypatch):
    monkeypatch.setattr(hp, "_agent_cwd", lambda: os.path.join(notesync, "notesync"))
    assert os.path.samefile(call(ctx, "docs_drift_scan", {})["root"], notesync)
    assert os.path.samefile(call(ctx, "docs_drift_scan", None)["root"], notesync)


def test_scan_tool_changed_only(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[old problem](missing.md)\n"
    root = make_repo(files)
    edit(root, "notesync/cli.py", '"--output-dir"', '"--dest"')
    whole = call(ctx, "docs_drift_scan", {"path": root})
    assert whole["summary"]["by_check"] == {"path-missing": 1, "cli-flag-undefined": 2}
    changed = call(ctx, "docs_drift_scan", {"path": root, "changed_only": True})
    assert changed["summary"]["by_check"] == {"cli-flag-undefined": 2}
    assert changed["compared_with"] == "git HEAD"
    assert all("--dest" in f["suggestion"] for f in changed["findings"])


def test_scan_tool_inside_a_session_knows_what_the_session_removed(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] = files["README.md"].replace("notesync ./notes --dry-run\n", "")
    root = make_repo(files)
    data = do_edit(root, "notesync/cli.py", '"--dry-run"', '"--simulate"', session="s9")
    fid = data["docs_drift"]["new"][0]["id"]
    scan = call(ctx, "docs_drift_scan", {"path": root}, session_id="s9", task_id="t")
    assert [f["id"] for f in scan["findings"]] == [fid]
    assert "also_compared_with" in scan
    info = call(ctx, "docs_drift_explain", {"finding_id": fid, "path": root}, session_id="s9")
    assert info["name"] == "--dry-run" and any("--simulate" in line for line in info["code_context"])


def test_scan_tool_options(ctx, make_repo):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[a](one.md) [b](two.md) [c](three.md)\n\nSee `notesync/nope.py`.\n"
    root = make_repo(files)
    data = call(ctx, "docs_drift_scan", {"path": root, "max_findings": 2})
    assert len(data["findings"]) == 2 and "truncated" in data
    data = call(ctx, "docs_drift_scan", {"path": root, "checks": ["path-ref-missing"], "max_findings": "x"})
    assert data["summary"]["by_check"] == {"path-ref-missing": 1}
    data = call(ctx, "docs_drift_scan", {"path": root, "checks": "all", "min_confidence": "high"})
    assert data["summary"]["findings"] >= 3


def test_tool_errors_are_json_not_exceptions(ctx, notesync, tmp_path):
    assert "does not exist" in call(ctx, "docs_drift_scan", {"path": str(tmp_path / "nope")})["error"]
    assert "finding_id is required" in call(ctx, "docs_drift_explain", {"path": notesync})["error"]
    missing = call(ctx, "docs_drift_explain", {"finding_id": "DD-00000000", "path": notesync})
    assert "no finding with id" in missing["error"] and "hint" in missing
    assert "error" in call(ctx, "docs_drift_explain", "garbage")


def test_tool_handlers_accept_the_keywords_hermes_passes(ctx, notesync):
    out = ctx.tools["docs_drift_scan"]["handler"]({"path": notesync}, task_id="t1", session_id="s1",
                                                 user_task="check the docs", parent_agent=None)
    assert json.loads(out)["summary"]["findings"] == 0


# ------------------------------------------------------------------ slash command
def test_drift_command(ctx, make_repo, monkeypatch):
    files = dict(NOTESYNC)
    files["README.md"] += "\n[old problem](missing.md)\n\nSee `notesync/nope.py`.\n"
    root = make_repo(files)
    monkeypatch.setattr(hp, "_agent_cwd", lambda: root)
    drift = ctx.commands["drift"]
    out = drift("")
    assert out.startswith("docs-drift ") and "1 finding " in out and "README.md:28  path-missing" in out
    assert "2 findings" in drift("--all")
    assert "0 findings" in drift("--changed")
    assert "1 finding " in drift(f'"{root}"')
    assert "/drift explain <id>" in drift("help")
    listing = drift("checks")
    assert "on   path-missing" in listing and "off  path-ref-missing" in listing
    fid = re.search(r"DD-[0-9a-f]{8}", out).group(0)
    explained = drift(f"explain {fid}")
    assert "why this was reported:" in explained and "docs:" in explained
    assert "no finding with id" in drift("explain DD-00000000")
    assert drift("explain").startswith("usage:")
    assert "does not exist" in drift("Z:/no/such/place")
    assert isinstance(drift(None), str)


def test_state_is_bounded(ctx, notesync):
    path = cli_path(notesync)
    for i in range(hp.MAX_SESSIONS + 5):
        hp.on_pre_tool_call(tool_name="patch", args={"path": path}, session_id=f"s{i}")
    assert len(hp._sessions) == hp.MAX_SESSIONS
    assert len(hp._scanners) == 1

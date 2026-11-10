"""benchmarks/summarize_real.py: the tables are built from what the transcripts say, and nothing else."""

import json
import os
import sys

from conftest import ROOT

sys.path.insert(0, os.path.join(ROOT, "benchmarks"))
import summarize_real  # noqa: E402


def transcript(plugin, verdict, calls, first=None, before=0, after=0, requests=7):
    """A transcript in the shape demo/run_real.py prints. ``calls`` is [(answer number, tool name, arguments)]."""
    lines = ["docs-drift run with a real model   2026-11-10T14:46:20Z", "",
             "--- 1. what Hermes did (the events it prints with --format stream-json) ---"]
    lines += [f"[14:46:5{i}Z] tool call    {name} {json.dumps(args)}" for i, (_n, name, args) in enumerate(calls)]
    lines += ["", "--- 2. what the model was sent and what it answered (the relay log, unedited) ---"]
    for n in sorted({n for n, _name, _args in calls}):
        lines.append(f"[14:47:0{n}Z] request {n} to model m: 3 messages, 4 tools offered")
        lines.append(f"[14:47:0{n}Z] answer {n} (1.0 s, prompt 10 / completion 5 tokens):")
        lines += [f"tool call: {name} " + json.dumps(args)[:40] for k, name, args in calls if k == n]
    lines += ["", "--- 3. afterwards ---"]
    if first:
        lines.append(f"the plugin told the model something: yes, first in request {first} (edit result)")
    summary = {"task": "add-flag", "model": "m", "plugin": plugin, "settings": "defaults", "exit_code": 0, "requests": requests,
               "verdict": verdict, "stale_lines": 0, "entries": 0, "entries_with_findings": 0, "findings_reported": 0,
               "reminder": False, "spoke": bool(first), "spoke_how": "edit result" if first else "",
               "doc_edits_before": before, "doc_edits_after": after}
    return "\n".join(lines + ["OUTCOME: " + verdict, "SUMMARY: " + json.dumps(summary, sort_keys=True)]) + "\n"


SCRATCH = r"$HERMES_HOME\cache\scratch\notes\a.md"
INSIDE = r"%TEMP%\docs-drift-real-abc123\notesync\docs\configuration.md"


def test_a_scratch_file_outside_the_project_is_not_a_doc_edit():
    assert summarize_real.in_project("README.md") and summarize_real.in_project(r"docs\configuration.md")
    assert summarize_real.in_project(INSIDE)
    assert not summarize_real.in_project(SCRATCH) and not summarize_real.in_project(r"C:\notes\a.md")
    assert not summarize_real.in_project("/tmp/a.md") and not summarize_real.in_project("~/a.md")
    text = transcript(True, "docs consistent", first=3, before=1, after=3, calls=[
        (1, "read_file", {"path": "README.md"}),
        (2, "patch", {"path": "notesync/cli.py", "old_string": "x" * 200, "new_string": "y"}),
        (2, "write_file", {"content": "a\n", "path": SCRATCH}),
        (3, "patch", {"new_string": "z" * 200, "path": "README.md"}),
        (4, "write_file", {"content": "b\n", "path": SCRATCH}),
        (4, "write_file", {"content": "c\n", "path": INSIDE}),
    ])
    assert summarize_real.recount(text) == {"before": 0, "after": 2, "outside_before": 1, "outside_after": 1}


def test_recount_gives_up_when_the_two_sections_do_not_show_the_same_edits():
    text = transcript(False, "docs stale", calls=[(1, "patch", {"path": "a.py"})])
    assert summarize_real.recount(text) == {"before": 0, "after": 0, "outside_before": 0, "outside_after": 0}
    assert summarize_real.recount(text.replace("tool call: patch ", "tool call: write_file ")) is None


def test_the_tables_keep_batches_of_five_apart_and_then_pool_them(tmp_path, capsys):
    for n in range(1, 8):
        with_plugin = transcript(True, "docs consistent", first=2, before=0, after=1,
                                 calls=[(1, "patch", {"path": "cli.py"}), (2, "patch", {"path": "README.md"})])
        without = transcript(False, "docs stale" if n != 2 else "docs consistent", before=2 if n == 4 else 0,
                             calls=[(1, "patch", {"path": "cli.py"})]
                             + ([(1, "write_file", {"path": SCRATCH}), (1, "write_file", {"path": SCRATCH})] if n == 4 else [])
                             + ([(2, "patch", {"path": "README.md"})] if n == 2 else []))
        if n == 2:
            without = without.replace('"doc_edits_before": 0', '"doc_edits_before": 1')
        (tmp_path / f"m-add-flag-plugin-{n}.txt").write_text(with_plugin, encoding="utf-8")
        (tmp_path / f"m-add-flag-none-{n}.txt").write_text(without, encoding="utf-8")
    (tmp_path / "other.txt").write_text("not a session\n", encoding="utf-8")
    assert summarize_real.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "| m | add-flag | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 5 | 35 |" in out
    assert "| m | add-flag | no plugin | 5 (1-5) | 1 | 4 | 0 | 1 | n/a | n/a | 35 |" in out
    assert "| m | add-flag | plugin | 2 (6-10) | 2 | 0 | 0 | 2 | 2 | 2 | 14 |" in out
    assert "| m | add-flag | no plugin | 7 (all) | 1 | 6 | 0 | 1 | n/a | n/a | 49 |" in out
    assert "chat requests in these 14 sessions: 98" in out
    assert "m-add-flag-none-4.txt: the SUMMARY line says 2 before / 0 after; 2 + 0 of those were files outside the project" in out
    assert "no SUMMARY line (not a --task session, or the driver stopped early): other.txt" in out
    assert "| `m-add-flag-none-4.txt` | 14:46:20 | 7 | 0 | n/a | 0 / - | n/a | docs stale |" in out

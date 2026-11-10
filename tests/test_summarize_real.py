"""benchmarks/summarize_real.py: the tables are built from what the transcripts say, and nothing else."""

import hashlib
import json
import os
import subprocess
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


def git(cwd, *args):
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
                           *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return done.stdout.strip()


def test_a_transcript_kept_in_another_commit_is_read_through_its_pointer(tmp_path, capsys):
    kept = transcript(True, "docs consistent", first=2, before=0, after=1, requests=9,
                      calls=[(1, "patch", {"path": "cli.py"}), (2, "patch", {"path": "README.md"})]).encode("utf-8")
    here = transcript(False, "docs stale", calls=[(1, "patch", {"path": "cli.py"})])
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "m-add-flag-plugin-1.txt").write_bytes(kept)
    (runs / "m-add-flag-none-1.txt").write_bytes(here.encode("utf-8"))
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "both")
    commit = git(tmp_path, "rev-parse", "HEAD")
    (runs / "m-add-flag-plugin-1.txt").unlink()
    pointer = runs / ("m-add-flag-plugin-1" + summarize_real.MOVED)
    fields = (f"- commit: `{commit}`\n- path: `runs/m-add-flag-plugin-1.txt`\n"
              f"- sha256: `{hashlib.sha256(kept).hexdigest()}`\n")
    pointer.write_text("# kept elsewhere\n\n" + fields, encoding="utf-8")

    assert summarize_real.main([str(runs)]) == 0
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.startswith("| `m-add-flag-")]
    assert [r.split("`")[1] for r in rows] == ["m-add-flag-none-1.txt", "m-add-flag-plugin-1.txt"]   # sorted as before
    assert "| `m-add-flag-plugin-1.txt` | 14:46:20 | 9 | 0 | edit result | 0 / 1 | not delivered | docs consistent |" in out
    assert "| m | add-flag | plugin | 1 (1-5) | 1 | 0 | 0 | 1 | 1 | 1 | 9 |" in out
    assert "chat requests in these 2 sessions: 16" in out and "not in the tables" not in out

    # the transcript in that commit is not the one the pointer was written for: it is not counted
    pointer.write_text("# kept elsewhere\n\n" + fields.replace(hashlib.sha256(kept).hexdigest(), "0" * 64), encoding="utf-8")
    assert summarize_real.main([str(runs)]) == 0
    out = capsys.readouterr().out
    assert "chat requests in these 1 sessions: 7" in out
    assert "not in the tables: m-add-flag-plugin-1.txt is kept in another commit, named in m-add-flag-plugin-1.MOVED.md" in out
    assert "| m | add-flag | plugin |" not in out

    # a pointer that names no commit, and a commit this clone does not have
    for broken in ("# kept elsewhere\n", fields.replace(commit, "1" * 40)):
        pointer.write_text(broken, encoding="utf-8")
        assert summarize_real.moved(str(pointer)) is None


def test_the_pointer_in_this_repository_names_a_transcript_of_the_right_shape():
    """The one transcript kept on another branch: its pointer has the three fields the summarizer reads."""
    folder = os.path.join(ROOT, "evidence", "real-model", "round3")
    pointers = [n for n in os.listdir(folder) if n.endswith(summarize_real.MOVED)]
    assert pointers == ["qwen3.8-27b-rename-plugin-4.MOVED.md"]
    with open(os.path.join(folder, pointers[0]), encoding="utf-8") as fh:
        fields = dict(summarize_real._POINTER.findall(fh.read()))
    assert set(fields) == {"commit", "path", "sha256"}
    assert len(fields["commit"]) == 40 and len(fields["sha256"]) == 64
    assert fields["path"] == "evidence/real-model/round3/qwen3.8-27b-rename-plugin-4.txt"
    assert not os.path.exists(os.path.join(ROOT, *fields["path"].split("/")))

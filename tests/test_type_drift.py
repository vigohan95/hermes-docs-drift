"""demo/type_drift.py: what is kept of a terminal's output. The pseudo-terminal itself is not started here."""

import os
import sys

from conftest import ROOT

sys.path.insert(0, os.path.join(ROOT, "demo"))
import type_drift  # noqa: E402

ESC = "\x1b"
RULE = "─" * 40
STATUS = " ☤ none · ctx -- · 12s · …\\some\\dir\\notesync (main)  / commands · @ files"
FRAME = f"{RULE}\r\n─\r\n{ESC}[1m❯ {ESC}[0mType / to browse commands, or Ctrl+P for the palette\r\n{RULE}\r\n{STATUS}\r\n"


def typed(command, answer):
    """Roughly what the terminal receives while ``command`` is typed and answered."""
    keys = "".join(f"{ESC}[2K❯ {command[:i]}\r" for i in range(1, len(command) + 1))
    menu = f" {command}  Check that README/docs still match the code (docs-drift).  \r\n"
    return (keys + menu + f"{ESC}[?25l{ESC}[2 q⚙️  {command}\r\n" + FRAME
            + f" \x08{ESC}[32m" + answer.replace("\n", "\r\n") + f"{ESC}[0m\r\n" + FRAME + f"{ESC}[?25h{ESC}[0 q")


def test_control_sequences_and_carriage_returns_are_removed():
    raw = f"{ESC}[2 q{ESC}[38;5;244mone{ESC}[0m\r\n{ESC}]0;title\x07two\rthree{ESC}[?25h"
    assert type_drift.plain(raw) == ["one", "two", "three"]


def test_the_frame_around_the_input_field_is_not_an_answer():
    for line in (RULE, "─", "", "   ", "❯ Type / to browse commands, or Ctrl+P for the palette", STATUS,
                 "Type / to browse commands, or Ctrl+P for the palette"):
        assert type_drift.is_frame(line), line
    for line in ("docs-drift .: 0 findings", "  docs: README.md:8  notesync ./notes --output-dir ./backup",
                 "README.md:8  cli-flag-undefined  [high]  DD-5fb3c36f"):
        assert not type_drift.is_frame(line), line


def test_the_answer_is_what_follows_the_echo_of_the_command():
    answer = ("docs-drift .: 1 finding (2 doc files checked against 4 code files, 76 ms)\n"
              "README.md:8  cli-flag-undefined  [high]  DD-5fb3c36f\n"
              "  docs: README.md:8  notesync ./notes --output-dir ./backup")
    assert type_drift.answer_lines(typed("/drift", answer), "/drift") == answer.split("\n")
    # indentation inside the answer is kept; the keys typed before the echo are not part of it
    changed = type_drift.answer_lines(typed("/drift --changed", answer), "/drift --changed")
    assert changed[2].startswith("  docs: ") and not any("❯" in ln for ln in changed)


def test_no_echo_means_no_answer_rather_than_a_guess():
    assert type_drift.answer_lines(FRAME + "docs-drift .: 0 findings\r\n", "/drift") is None
    assert type_drift.answer_lines(typed("/drift", ""), "/drift") == []


def test_without_hermes_on_the_path_the_driver_skips(capsys):
    assert type_drift.main(["--hermes", "no-such-program-docs-drift"]) == 0
    assert capsys.readouterr().out.startswith("skipped:")


def test_waiting_for_the_input_field_counts_only_what_came_after_the_start():
    class Terminal:
        def __init__(self):
            # the placeholder in the field differs between starts; the status line is always there
            self.chunks = [f"{ESC}[1m❯ {ESC}[0mFind and fix a failing test\r\n{ESC}[2m{STATUS}{ESC}[0m"]

        def read(self, size):
            if self.chunks:
                return self.chunks.pop(0)
            raise EOFError

    reader = type_drift.Reader(Terminal())
    assert reader.wait_for(type_drift.READY, 0, limit=5)
    assert not reader.wait_for(type_drift.READY, len(reader.text()), limit=0.5)

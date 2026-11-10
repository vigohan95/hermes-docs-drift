"""Type /drift into an interactive Hermes chat and print what Hermes printed back.

    HERMES_HOME=<a Hermes home with the plugin> python demo/type_drift.py [COMMAND ...]

Starts ``hermes chat --cli`` in a pseudo-terminal, in a fresh copy of
examples/notesync in which ``--output-dir`` has been renamed to ``--dest`` in the
code only (not committed). Types each command (default: ``/drift`` and
``/drift --changed``) one key at a time, presses Enter, and prints the lines
Hermes printed in answer.

No model is contacted. Hermes is pointed at a closed local port, and only slash
commands are typed, which Hermes handles itself.

What is printed is the terminal output after the line in which Hermes echoes the
command, with control sequences removed and without the lines Hermes redraws
around its input field (the rules, the prompt, the status line). Paths go
through ``scrub`` like in the other drivers.

Needs the pseudo-terminal package Hermes itself depends on: pywinpty on Windows,
ptyprocess elsewhere. Without it the script prints one line starting with
``skipped:`` and exits with status 0. It has been run on Windows only.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
import time
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scrub  # noqa: E402
from run_demo import ROOT, copy_example, run  # noqa: E402
from run_real import plugin_line  # noqa: E402

CONTROL = re.compile(
    r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]"            # CSI ... final byte, with or without an intermediate
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"      # OSC ... BEL or ST
    r"|\x1b[()][0-9A-Za-z]"                    # character set
    r"|\x1b[=>78DEHM]"                         # keypad modes, save and restore, index
)
RULE = set("─━═-")
CLOSED_PORT = "http://127.0.0.1:9/v1"
QUESTION = "Help improve Hermes?"
READY = "☤"        # the status line Hermes draws under its input field; the field's placeholder text varies


def plain(raw: str) -> List[str]:
    """Terminal output as lines of text: control sequences removed, a carriage return ends a line."""
    text = CONTROL.sub("", raw).replace("\r\n", "\n").replace("\r", "\n").replace("\x08", "")
    return [ln.rstrip() for ln in text.split("\n")]


def is_frame(line: str) -> bool:
    """A line Hermes redraws around its input field, not part of any answer."""
    s = line.strip()
    return (not s or set(s) <= RULE or s.startswith("❯") or "☤" in s
            or s.startswith("Type / to browse commands"))


def answer_lines(raw: str, command: str) -> Optional[List[str]]:
    """What was printed after the line that echoes ``command``; None if there is no such line."""
    lines = plain(raw)
    echo = [i for i, ln in enumerate(lines)
            if ln.strip().endswith(command) and not ln.strip().startswith("❯") and len(ln.strip()) <= len(command) + 6]
    if not echo:
        return None
    kept = [ln for ln in lines[echo[-1] + 1:] if not is_frame(ln)]
    return [kept[0].lstrip()] + kept[1:] if kept else kept


def spawn(argv: List[str], cwd: str, env: dict):
    try:
        if os.name == "nt":
            from winpty import PtyProcess
        else:
            from ptyprocess import PtyProcessUnicode as PtyProcess
    except ImportError:
        return None
    return PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(50, 200))


class Reader:
    """Collects what the terminal prints, on a thread."""

    def __init__(self, proc):
        self.proc, self.parts, self.lock = proc, [], threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = self.proc.read(4096)
            except Exception:           # EOFError when Hermes has exited
                return
            if data:
                with self.lock:
                    self.parts.append(data)

    def text(self) -> str:
        with self.lock:
            return "".join(self.parts)

    def settle(self, quiet: float, limit: float) -> None:
        """Wait until nothing has been printed for ``quiet`` seconds, at most ``limit``."""
        start = last = time.time()
        size = -1
        while time.time() - start < limit:
            now = len(self.text())
            if now != size:
                size, last = now, time.time()
            elif time.time() - last >= quiet:
                return
            time.sleep(0.2)

    def wait_for(self, marker: str, start: int, limit: float) -> bool:
        """Wait until ``marker`` has been printed after position ``start``, at most ``limit`` seconds."""
        end = time.time() + limit
        while time.time() < end:
            if marker in CONTROL.sub("", self.text()[start:]):
                return True
            time.sleep(0.2)
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("commands", nargs="*", default=["/drift", "/drift --changed"])
    ap.add_argument("--hermes", default="hermes", help="how to start Hermes (default: hermes)")
    args = ap.parse_args(argv)
    hermes = shlex.split(args.hermes, posix=(os.name != "nt"))
    if shutil.which(hermes[0]) is None:
        print(f"skipped: {hermes[0]} is not on PATH")
        return 0

    work = tempfile.mkdtemp(prefix="docs-drift-typed-")
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    scrub.install(named=[(os.path.abspath(home), "$HERMES_HOME"), (ROOT, "<docs-drift>")])
    repo = os.path.join(work, "notesync")
    os.makedirs(repo)
    copy_example(repo)
    cli = os.path.join(repo, "notesync", "cli.py")
    with open(cli, encoding="utf-8") as fh:
        source = fh.read()
    with open(cli, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source.replace('"--output-dir"', '"--dest"').replace("args.output_dir", "args.dest"))

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", OPENAI_BASE_URL=CLOSED_PORT)
    env.pop("DOCS_DRIFT_API_KEY", None)
    proc = spawn(hermes + ["chat", "--cli", "--provider", "custom", "--base-url", CLOSED_PORT,
                           "--api-key", "not-a-real-key", "-m", "none"], repo, env)
    if proc is None:
        print("skipped: no pseudo-terminal package (pywinpty on Windows, ptyprocess elsewhere)")
        shutil.rmtree(work, ignore_errors=True)
        return 0

    print(f"docs-drift: slash commands typed into an interactive Hermes chat   {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print("hermes:   " + (run(hermes + ["--version"], env=env).splitlines() or ["(no version output)"])[0])
    print("plugin:   " + plugin_line(hermes, env))
    print(f"source:   docs-drift commit {run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'])}")
    print("project:  a fresh copy of examples/notesync with one commit; then --output-dir renamed to --dest in")
    print("          notesync/cli.py and not committed. The docs still say --output-dir.")
    print("terminal: a pseudo-terminal, 200 columns wide. No model: Hermes was given a closed local port.")
    print("shown:    what Hermes printed after echoing each command, control sequences removed, without the")
    print("          lines it redraws around its input field")
    print()

    reader = Reader(proc)
    reader.settle(quiet=4, limit=90)
    asked = 0
    if QUESTION in reader.text():           # first start of this Hermes home asks about usage data: decline
        asked = len(reader.text())
        proc.write("2")
        time.sleep(0.5)
        proc.write("\r")
        print(f'(Hermes asked "{QUESTION}" on the first start of this home; answered 2, no)')
        print()
    if not reader.wait_for(READY, asked, limit=240):
        shown = [ln for ln in plain(reader.text()[asked:]) if ln.strip()]
        print("(the last lines the terminal showed)")
        for ln in shown[-12:]:
            print("  " + ln[:160])
        print()
        print("RESULT: FAILED, Hermes did not show its input field")
        proc.terminate(force=True)
        shutil.rmtree(work, ignore_errors=True)
        return 1
    reader.settle(quiet=4, limit=60)

    ok = True
    for command in args.commands:
        before = len(reader.text())
        for ch in command:
            proc.write(ch)
            time.sleep(0.02)
        time.sleep(0.5)
        proc.write("\r")
        reader.settle(quiet=3, limit=60)
        lines = answer_lines(reader.text()[before:], command)
        print("> " + command)
        if lines is None:
            ok = False
            print("  (Hermes did not echo the command; nothing to show)")
        else:
            ok = ok and any(ln.startswith("docs-drift") for ln in lines)
            for ln in lines:
                print("  " + ln)
        print()
    try:
        proc.write("/exit\r")
        time.sleep(3)
        if proc.isalive():
            proc.terminate(force=True)
    except Exception:
        pass
    shutil.rmtree(work, ignore_errors=True)
    print("RESULT: ok, every command was answered by docs-drift" if ok
          else "RESULT: FAILED, a command got no answer from docs-drift")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

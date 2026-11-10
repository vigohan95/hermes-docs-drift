"""Run one session with a real language model in a real Hermes and print a transcript.

    python demo/run_real.py [--hermes "hermes"] [--label TEXT] [--toolsets file]
                            [--project DIR --prompt TEXT --old NAME] [--keep]

The model is any OpenAI-compatible endpoint with tool calling, named by three
environment variables:

    DOCS_DRIFT_BASE_URL   for example https://api.example.com/v1
    DOCS_DRIFT_MODEL      the model id at that endpoint
    DOCS_DRIFT_API_KEY    the key

Without ``DOCS_DRIFT_API_KEY`` the script prints one line and exits with status 0:
it costs money to run, so it is not part of the tests or of CI. ``demo/run_demo.py``
is the version without a model.

What this does:

1. copies the project (``examples/notesync`` unless ``--project`` names another
   one; a git checkout is cloned locally at its current commit) to a temporary
   directory;
2. starts ``demo/relay.py``, which forwards requests unchanged to the endpoint,
   adds the key, counts the requests and logs what the model was sent;
3. runs ``hermes chat -q PROMPT --provider custom --base-url http://127.0.0.1:<port>/v1``
   in the copy. Hermes gets a placeholder instead of the key;
4. prints what Hermes did, the relay log, and what the project looks like
   afterwards: which files changed, and where the old name is still written.

The prompt is the plain request and nothing else. Whether the plugin takes part
depends only on the Hermes home in use (``HERMES_HOME``): run it once with a home
where docs-drift is installed and once with a home where it is not, and compare
the last lines. This script installs nothing and changes no Hermes setting.

The exit status is 0 when Hermes finished the turn, whatever the model did.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import scrub  # noqa: E402  (demo/scrub.py)
from run_demo import PROMPT, REMINDER, copy_example, free_port, indent, run, show, stamp  # noqa: E402

DOC_SUFFIXES = (".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc")
DOC_DIRS = ("docs/", "doc/", "documentation/", "website/", "man/")
HISTORY = ("changelog", "changes", "history", "news", "release")   # a record of the past: old names belong there
EDIT_TOOLS = ("write_file", "patch")


def is_doc(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    return low.endswith(DOC_SUFFIXES) or low.startswith(DOC_DIRS)


def is_history(rel: str) -> bool:
    return os.path.basename(rel.replace("\\", "/")).lower().startswith(HISTORY)


def show_result(event: dict) -> None:
    """Like ``run_demo.show``, but says "no docs_drift block" only for edits."""
    name = str(event.get("name", ""))
    try:
        out = json.loads(event.get("output") or "")
    except ValueError:
        out = None
    if name in EDIT_TOOLS or name.startswith("docs_drift") or (isinstance(out, dict) and "docs_drift" in out):
        show(event)
        return
    print(f"[{stamp(event.get('timestamp'))}] tool result  {name} ({event.get('duration_ms')} ms)")


def clone_project(src: str, dest: str) -> str:
    """A local clone of a git checkout at its current commit; returns the short commit id."""
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", src, dest], check=True)
    return run(["git", "-C", dest, "rev-parse", "--short", "HEAD"])


def plugin_line(hermes, env) -> str:
    listing = run(hermes + ["plugins", "list"], env=env)
    for line in listing.splitlines():
        if "docs-drift" in line:
            cells = [c.strip() for c in line.replace("│", "|").split("|") if c.strip()]
            return "docs-drift is installed in this Hermes home (" + ", ".join(cells[1:3]) + ")"
    return "docs-drift is NOT installed in this Hermes home"


def plugin_settings() -> str:
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    path = os.path.join(home, "config.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return "defaults (no config.yaml)"
    # The few lines under plugins.entries.docs-drift.settings, read without a YAML library.
    stack, found = [], []
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        depth = len(raw) - len(raw.lstrip())
        key, _, value = raw.strip().partition(":")
        while stack and stack[-1][0] >= depth:
            stack.pop()
        where = [k for _d, k in stack]
        if where == ["plugins", "entries", "docs-drift", "settings"] and value.strip():
            found.append(f"{key.strip()}: {value.strip()}")
        stack.append((depth, key.strip()))
    return ", ".join(found) if found else "defaults"


def old_name_lines(repo: str, old: str):
    """(doc lines, other lines) of tracked and new files that still contain ``old``."""
    out = subprocess.run(["git", "grep", "-n", "-I", "--untracked", "-F", "-e", old], cwd=repo,
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    docs, other = [], []
    for line in out.splitlines():
        rel = line.split(":", 1)[0]
        # a changelog or release notes file counts as "other": the old name is correct there
        (docs if is_doc(rel) and not is_history(rel) else other).append(line.strip())
    return docs, other


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run one docs-drift session with a real model in a real Hermes.")
    ap.add_argument("--hermes", default=os.environ.get("HERMES_CMD", "hermes"),
                    help="command that starts Hermes (default: hermes, or $HERMES_CMD)")
    ap.add_argument("--project", default="", help="project to copy (default: examples/notesync)")
    ap.add_argument("--prompt", default=PROMPT, help="the request given to the agent")
    ap.add_argument("--old", default="--output-dir", help="the name the request removes; looked for afterwards")
    ap.add_argument("--label", default="", help="free text for the transcript header")
    ap.add_argument("--keep", action="store_true", help="keep the temporary project directory")
    ap.add_argument("--toolsets", default="", help="passed to hermes chat -t (default: Hermes' own default)")
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--max-requests", type=int, default=20, help="chat requests the relay lets through")
    args = ap.parse_args(argv)

    key = os.environ.get("DOCS_DRIFT_API_KEY", "")
    base_url = os.environ.get("DOCS_DRIFT_BASE_URL", "")
    model = os.environ.get("DOCS_DRIFT_MODEL", "")
    if not key:
        print("skipped: DOCS_DRIFT_API_KEY is not set (this demo needs a real model; see demo/run_demo.py for the stub)")
        return 0
    if not base_url or not model:
        print("DOCS_DRIFT_BASE_URL and DOCS_DRIFT_MODEL must be set as well")
        return 2
    # Everything printed from here on has the key and the temp and home directory prefixes replaced.
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    scrub.install(secrets=[key], named=[(os.path.abspath(home), "$HERMES_HOME"), (ROOT, "<docs-drift>")])

    hermes = shlex.split(args.hermes, posix=(os.name != "nt"))
    work = tempfile.mkdtemp(prefix="docs-drift-real-")
    relay_log = os.path.join(work, "relay.log")
    port = free_port()

    # Hermes and everything it starts run without the key.
    env = {k: v for k, v in os.environ.items() if k != "DOCS_DRIFT_API_KEY"}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for name in ("NO_PROXY", "no_proxy"):
        env[name] = ",".join(x for x in (env.get(name, ""), "127.0.0.1", "localhost") if x)

    if args.project:
        src = os.path.abspath(args.project)
        repo = os.path.join(work, os.path.basename(src.rstrip("\\/")) or "project")
        commit = clone_project(src, repo)
        origin = run(["git", "-C", src, "remote", "get-url", "origin"]).splitlines()
        project = f"a local clone of {origin[0] if origin else os.path.basename(src)} at commit {commit}"
    else:
        repo = os.path.join(work, "notesync")
        os.makedirs(repo)
        copy_example(repo)
        project = "a fresh copy of examples/notesync with one commit"

    print(f"docs-drift run with a real model   {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    if args.label:
        print("run:      " + args.label)
    print("hermes:   " + (run(hermes + ["--version"], env=env).splitlines() or ["(no version output)"])[0])
    print("plugin:   " + plugin_line(hermes, env))
    print("settings: " + plugin_settings())
    print(f"source:   docs-drift commit {run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'])}")
    print(f"model:    {model} at {base_url}, through demo/relay.py on 127.0.0.1:{port}")
    print("          (the relay forwards requests unchanged, adds the key and counts; Hermes has no key)")
    print("project:  " + project)
    print("prompt:   " + args.prompt)
    print("toolsets: " + (args.toolsets or "Hermes' default"))
    print()

    relay = subprocess.Popen([sys.executable, os.path.join(HERE, "relay.py"), "--port", str(port), "--log", relay_log,
                              "--max-requests", str(args.max_requests)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    events = []
    raw_lines = []
    try:
        ready = relay.stdout.readline()
        if "relay on" not in ready:
            print("the relay did not start: " + ready.strip())
            return 2
        cmd = hermes + ["chat", "-q", args.prompt, "--provider", "custom", "--base-url", f"http://127.0.0.1:{port}/v1",
                        "--api-key", "not-a-real-key", "-m", model, "--yolo",
                        "--format", "stream-json", "--max-turns", str(args.max_turns)]
        if args.toolsets:
            cmd += ["-t", args.toolsets]
        shown = " ".join(shlex.quote(c) if os.name != "nt" else (f'"{c}"' if " " in c else c) for c in cmd)
        print("--- 1. what Hermes did (the events it prints with --format stream-json) ---")
        print("$ " + shown)
        proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        said = []          # text arrives in small pieces; print it as one block

        def flush_text(at_ms=None) -> None:
            text = "".join(said).strip()
            said.clear()
            if text:
                print(f"[{stamp(at_ms)}] assistant    " + indent(text).lstrip())

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line) if line.startswith("{") else None
            except ValueError:
                event = None
            if not isinstance(event, dict):
                raw_lines.append(line)
                continue
            events.append(event)
            if event.get("type") == "text":
                said.append(str(event.get("text", "")))
                continue
            flush_text(event.get("timestamp"))
            if event.get("type") == "tool_result":
                show_result(event)
            else:
                show(event)
        flush_text()
        proc.wait()
    finally:
        relay.terminate()
        try:
            relay.wait(timeout=10)
        except subprocess.TimeoutExpired:
            relay.kill()

    print()
    print("--- 2. what the model was sent and what it answered (the relay log, unedited) ---")
    log_text = ""
    if os.path.exists(relay_log):
        with open(relay_log, encoding="utf-8") as fh:
            log_text = fh.read()
    print(log_text.rstrip())

    print()
    print("--- 3. afterwards ---")
    outputs = []
    for e in events:
        if e.get("type") == "tool_result":
            try:
                outputs.append((e.get("name"), json.loads(e.get("output") or "")))
            except ValueError:
                outputs.append((e.get("name"), {}))
    blocks = [o["docs_drift"] for _n, o in outputs if isinstance(o, dict) and "docs_drift" in o]
    reported = sum(len(b.get("new") or []) for b in blocks)
    end = [e for e in events if e.get("type") == "result"]
    exit_code = end[-1].get("exit_code") if end else None
    requests = log_text.count("] request ") - log_text.count("refused by the relay")
    side = log_text.count("a side request from Hermes without tools")
    print(f"Hermes exit_code: {exit_code}")
    print(f"chat requests sent to the model: {requests} (of which {side} side requests without tools)")
    if end:
        print("tokens reported by Hermes: " + json.dumps(end[-1].get("tokens")))
    print(f"edit results that carried a docs_drift entry: {len(blocks)} ({reported} findings reported in them)")
    print("reminder before the end of the turn (pre_verify): " + ("delivered" if REMINDER in log_text else "not delivered"))
    print()
    print("$ git status --short")
    status = run(["git", "status", "--short"], cwd=repo)
    print(status or "(no changes)")
    changed = [ln[3:].strip().strip('"') for ln in status.splitlines() if len(ln) > 3]
    code_changed = [c for c in changed if not is_doc(c)]
    docs_left, other_left = old_name_lines(repo, args.old)
    print(f'$ git grep -n -F -e "{args.old}"        (where the old name is still written)')
    print("\n".join(docs_left + other_left) or "(nowhere)")
    history = [ln for ln in other_left if is_doc(ln.split(":", 1)[0])]
    if history:
        print(f"({len(history)} of these lines are in a changelog or release notes and are not counted as stale docs)")
    print("$ python -m docsdrift . --since HEAD        (the same scanner, run outside Hermes)")
    print(run([sys.executable, "-m", "docsdrift", repo, "--since", "HEAD"], env=dict(env, PYTHONPATH=ROOT)).replace(repo, "."))
    print()
    if not code_changed:
        outcome = "no code file was changed"
    elif docs_left:
        outcome = f"docs stale ({len(docs_left)} line(s) in the docs still use {args.old})"
    else:
        outcome = f"docs consistent (no doc file uses {args.old} any more)"
    print("OUTCOME: " + outcome)
    if raw_lines and exit_code != 0:
        print("other output from Hermes:")
        print(indent("\n".join(raw_lines[-20:]), "  "))
    if args.keep:
        print(f"kept: {work}")
        print(f"kept (real path, standard error only): {work}", file=sys.stderr)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

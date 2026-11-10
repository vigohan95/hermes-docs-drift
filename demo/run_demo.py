"""Run the example session in a real Hermes and print a transcript.

    python demo/run_demo.py rename  [--hermes "hermes"] [--keep]
    python demo/run_demo.py forget

What this does:

1. copies ``examples/notesync`` to a temporary directory and commits it;
2. starts ``demo/scripted_model.py`` on a free local port (a fixed script that
   stands in for a language model, so no API key is needed);
3. runs ``hermes chat -q ... --provider custom --base-url http://127.0.0.1:<port>/v1``
   in that directory and reads the events Hermes prints;
4. prints what Hermes did, what the model stub was sent, and whether each
   expected step happened. Exit status 0 only when all of them did.

The plugin must already be installed and enabled in the Hermes home in use
(``hermes plugins install <path-or-repo> --enable``). This script does not
install anything and does not change the Hermes configuration.

``--hermes`` is the command that starts Hermes, for example
``"python -m hermes_cli.main"`` from a source checkout. The value after
``--api-key`` passed to Hermes is the literal text ``not-a-real-key``; the stub
ignores it.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROMPT = "Rename the --output-dir flag of notesync to --dest."
REMINDER = "docs-drift: your edits in this session left"


def stamp(ms=None) -> str:
    t = time.gmtime(ms / 1000.0) if ms else time.gmtime()
    return time.strftime("%H:%M:%SZ", t)


def run(cmd, cwd=None, env=None) -> str:
    out = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (out.stdout + out.stderr).rstrip()


def copy_example(dest: str) -> None:
    src = os.path.join(ROOT, "examples", "notesync")
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), src)
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                text = fh.read()
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.invalid", "-c", "core.autocrlf=false",
           "-c", "commit.gpgsign=false"]
    subprocess.run(git + ["init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(git + ["add", "-A"], cwd=dest, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "notesync example"], cwd=dest, check=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def indent(text: str, pad: str = "             ") -> str:
    return "\n".join(pad + ln for ln in text.splitlines())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the docs-drift example session in a real Hermes.")
    ap.add_argument("script", choices=["rename", "forget"])
    ap.add_argument("--hermes", default=os.environ.get("HERMES_CMD", "hermes"),
                    help="command that starts Hermes (default: hermes, or $HERMES_CMD)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary project directory")
    ap.add_argument("--max-turns", type=int, default=12)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    hermes = shlex.split(args.hermes, posix=(os.name != "nt"))
    work = tempfile.mkdtemp(prefix="docs-drift-demo-")
    repo = os.path.join(work, "notesync")
    os.makedirs(repo)
    copy_example(repo)
    model_log = os.path.join(work, "model.log")
    port = free_port()

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for key in ("NO_PROXY", "no_proxy"):
        env[key] = ",".join(x for x in (env.get(key, ""), "127.0.0.1", "localhost") if x)

    print(f'docs-drift demo "{args.script}"   {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}')
    print("hermes:  " + (run(hermes + ["--version"], env=env).splitlines() or ["(no version output)"])[0])
    commit = run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"])
    print(f"plugin:  docs-drift, source commit {commit}")
    print(f"model:   demo/scripted_model.py on 127.0.0.1:{port}. A fixed script, not a language model:")
    print("         it sends the next scripted tool call or message whatever it is told. The agent loop,")
    print("         the patch tool, plugin loading and the hooks are the unmodified Hermes ones.")
    print("project: a fresh copy of examples/notesync with one commit")
    print(f"prompt:  {PROMPT}")
    print()

    server = subprocess.Popen([sys.executable, os.path.join(HERE, "scripted_model.py"), args.script,
                               "--port", str(port), "--log", model_log],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    events = []
    raw_lines = []
    try:
        ready = server.stdout.readline()
        if "scripted model" not in ready:
            print("the model stub did not start: " + ready.strip())
            return 2
        cmd = hermes + ["chat", "-q", PROMPT, "--provider", "custom", "--base-url", f"http://127.0.0.1:{port}/v1",
                        "--api-key", "not-a-real-key", "-m", "scripted-demo", "--yolo",
                        "--format", "stream-json", "--max-turns", str(args.max_turns)]
        shown = " ".join(shlex.quote(c) if os.name != "nt" else (f'"{c}"' if " " in c else c) for c in cmd)
        print("--- 1. what Hermes did (the events it prints with --format stream-json) ---")
        print("$ " + shown)
        proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if not line.startswith("{"):
                raw_lines.append(line)
                continue
            try:
                event = json.loads(line)
            except ValueError:
                raw_lines.append(line)
                continue
            events.append(event)
            show(event)
        proc.wait()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    print()
    print("--- 2. what the model stub was sent and what it answered (its log, unedited) ---")
    log_text = ""
    if os.path.exists(model_log):
        with open(model_log, encoding="utf-8") as fh:
            log_text = fh.read()
    print(log_text.rstrip())

    print()
    print("--- 3. checks ---")
    ok = True

    def check(passed: bool, text: str) -> None:
        nonlocal ok
        ok = ok and bool(passed)
        print(("ok    " if passed else "FAIL  ") + text)

    results = [e for e in events if e.get("type") == "tool_result"]
    outputs = []
    for e in results:
        try:
            outputs.append((e.get("name"), json.loads(e.get("output") or "")))
        except ValueError:
            outputs.append((e.get("name"), {}))
    first = outputs[0][1] if outputs else {}
    new = (first.get("docs_drift") or {}).get("new") or []
    check(len(new) == 2, f"the result of the first edit carried a docs_drift block with 2 new findings (got {len(new)})")
    check(sorted(f.get("doc", "").split(":")[0] for f in new) == ["README.md", "docs/configuration.md"],
          "the findings point at README.md and docs/configuration.md")
    resolved = [o.get("docs_drift", {}).get("still_open") for n, o in outputs[1:] if n == "patch" and "docs_drift" in o]
    check(resolved[-1:] == [0], f"after the doc edits the hook reported 0 findings still open (sequence: {resolved})")
    scans = [o for n, o in outputs if n == "docs_drift_scan"]
    check(bool(scans) and scans[-1].get("summary", {}).get("findings") == 0, "docs_drift_scan (changed_only) returned 0 findings")
    if args.script == "rename":
        explains = [o for n, o in outputs if n == "docs_drift_explain"]
        check(bool(explains) and explains[0].get("id") == (new[0].get("id") if new else None),
              "docs_drift_explain returned the finding the hook reported")
    else:
        check(REMINDER in log_text, "Hermes delivered the pre_verify reminder to the model before the turn ended")
    end = [e for e in events if e.get("type") == "result"]
    check(bool(end) and end[-1].get("exit_code") == 0, "Hermes finished the turn with exit_code 0")

    print()
    print("$ git status --short        (in the project)")
    print(run(["git", "status", "--short"], cwd=repo))
    print("$ python -m docsdrift .     (the same scanner, run outside Hermes)")
    print(run([sys.executable, "-m", "docsdrift", repo], env=dict(env, PYTHONPATH=ROOT)).replace(repo, "."))
    print()
    print("RESULT: " + ("ok" if ok else "FAILED"))
    if raw_lines and not ok:
        print("other output from Hermes:")
        print(indent("\n".join(raw_lines[-20:]), "  "))
    if args.keep:
        print(f"kept: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


def show(event: dict) -> None:
    kind = event.get("type")
    at = stamp(event.get("timestamp"))
    if kind == "tool_use":
        print(f"[{at}] tool call    {event.get('name')} {json.dumps(event.get('input'), ensure_ascii=False)}")
    elif kind == "tool_result":
        print(f"[{at}] tool result  {event.get('name')} ({event.get('duration_ms')} ms)")
        try:
            out = json.loads(event.get("output") or "")
        except ValueError:
            print(indent(str(event.get("output"))[:2000]))
            return
        if str(event.get("name", "")).startswith("docs_drift"):
            print(indent(json.dumps(out, indent=2, ensure_ascii=False)))
        else:
            rest = sorted(k for k in out if k != "docs_drift")
            print(indent(f"(fields from Hermes' own tool, not shown: {', '.join(rest)})"))
            if "docs_drift" in out:
                print(indent('"docs_drift": ' + json.dumps(out["docs_drift"], indent=2, ensure_ascii=False)))
            else:
                print(indent("(no docs_drift block: the edit caused no new drift and resolved none)"))
    elif kind == "text":
        print(f"[{at}] assistant    {str(event.get('text', '')).strip()}")
    elif kind == "result":
        print(f"[{at}] end of turn  exit_code {event.get('exit_code')}, {event.get('duration_ms')} ms")


if __name__ == "__main__":
    sys.exit(main())

"""A stand-in for a language model, for running the demo without any API key.

    python demo/scripted_model.py <script> [--port 18765] [--log FILE]

This is an OpenAI-compatible ``/v1/chat/completions`` endpoint on 127.0.0.1
whose replies come from a fixed script. It decides nothing: each reply is
the next step of the script. Everything it is sent comes from a real Hermes
process, and the log shows the tool results Hermes delivered, including the
``docs_drift`` block this plugin adds.

It exists so that the plugin can be shown working inside an unmodified Hermes
on a machine that has no model configured. It is not a mock of Hermes: the
agent loop, the ``patch`` tool, plugin loading and the hooks are the real ones.

Scripts:

``rename``  rename ``--output-dir`` to ``--dest`` in the example project, read
            the drift report, ask for the explanation, fix both doc files,
            re-scan.
``forget``  make the same rename and say "done" without touching the docs, to
            show the reminder before the turn ends; then fix the docs.

A step is either a tool call or a final message. A tool call may take values
from the previous tool result (the finding id, the doc file and line), so the
script follows what the plugin actually reported rather than hard-coding it.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "scripted-demo"


def _last_tool_result(messages):
    for m in reversed(messages):
        if m.get("role") == "tool":
            content = m.get("content")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            try:
                return json.loads(content)
            except (TypeError, ValueError):
                return {"_raw": content}
    return {}


def _drift(messages):
    """The docs_drift block of the most recent tool result that has one."""
    for m in reversed(messages):
        if m.get("role") != "tool":
            continue
        try:
            data = json.loads(m.get("content") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("docs_drift"):
            return data["docs_drift"]
    return {}


def _call(name, **args):
    return {"tool": name, "args": args}


def _say(text):
    return {"text": text}


def _fix_doc_steps():
    return [
        lambda ms: _call("patch", mode="replace", path="README.md",
                         old_string="--output-dir", new_string="--dest", replace_all=True),
        lambda ms: _call("patch", mode="replace", path="docs/configuration.md",
                         old_string="--output-dir", new_string="--dest", replace_all=True),
        lambda ms: _call("docs_drift_scan", changed_only=True),
    ]


SCRIPTS = {
    "rename": [
        lambda ms: _call("patch", mode="replace", path="notesync/cli.py",
                         old_string='"--output-dir"', new_string='"--dest"'),
        lambda ms: _call("docs_drift_explain", id=(_drift(ms).get("new") or [{}])[0].get("id", "")),
        *_fix_doc_steps(),
        lambda ms: _say("Renamed --output-dir to --dest in notesync/cli.py and updated README.md and "
                        "docs/configuration.md, which still used the old name. docs_drift_scan is clean."),
    ],
    "forget": [
        lambda ms: _call("patch", mode="replace", path="notesync/cli.py",
                         old_string='"--output-dir"', new_string='"--dest"'),
        lambda ms: _say("Done. The flag is now --dest."),
        *_fix_doc_steps(),
        lambda ms: _say("The docs still used --output-dir; README.md and docs/configuration.md are updated "
                        "and docs_drift_scan is clean."),
    ],
}


class Handler(BaseHTTPRequestHandler):
    server_version = "scripted-model/1"
    script = []
    log = None
    lock = threading.Lock()
    step = 0

    def log_message(self, *args):  # keep stderr quiet
        return

    def _write_log(self, text):
        if self.log:
            with self.lock:
                with open(self.log, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(text + "\n")

    def _json(self, code, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": MODEL_ID, "object": "model", "owned_by": "local", "context_length": 200000}]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": {"message": "bad json"}})
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        messages = body.get("messages") or []
        has_tools = bool(body.get("tools"))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not has_tools:
            # Hermes side requests (session title and the like): not part of the script.
            reply = _say("Rename a CLI flag")
            self._write_log(f"[{stamp}] side request without tools -> fixed short reply")
        else:
            with self.lock:
                index = Handler.step
                Handler.step += 1
            last = messages[-1] if messages else {}
            if last.get("role") == "tool":
                self._write_log(f"[{stamp}] Hermes -> model, tool result:\n"
                                + json.dumps(_last_tool_result(messages), indent=2, ensure_ascii=False))
            else:
                content = last.get("content")
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                self._write_log(f"[{stamp}] Hermes -> model, {last.get('role')} message:\n{content}")
            offered = [t.get("function", {}).get("name", "") for t in body.get("tools") or []]
            if index == 0:
                self._write_log(f"[{stamp}] tools Hermes offered to the model: {', '.join(sorted(offered))}")
                for t in body.get("tools") or []:
                    desc = t.get("function", {}).get("description", "")
                    for line in desc.splitlines():
                        if "docs_drift" in line:
                            self._write_log(f"[{stamp}] listed under {t['function']['name']}: {line.strip()}")
            if index < len(self.script):
                reply = self.script[index](messages)
            else:
                reply = _say("(the script has no more steps)")
            if "tool" in reply and reply["tool"] not in offered and "tool_call" in offered:
                # Hermes loads plugin tools on demand: they are listed under tool_search and
                # invoked through its tool_call bridge, which is what a model would do here.
                reply = _call("tool_call", calls=[{"name": reply["tool"], "arguments": reply["args"]}])
            self._write_log(f"[{stamp}] model -> Hermes (script step {index + 1}/{len(self.script)}):\n"
                            + json.dumps(reply, indent=2, ensure_ascii=False) + "\n")
        self._respond(body, reply)

    def _respond(self, body, reply):
        created = int(time.time())
        cid = f"chatcmpl-scripted-{created}-{Handler.step}"
        if "tool" in reply:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{Handler.step:04d}", "type": "function",
                "function": {"name": reply["tool"], "arguments": json.dumps(reply["args"])}}]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": reply["text"]}
            finish = "stop"
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if not body.get("stream"):
            self._json(200, {"id": cid, "object": "chat.completion", "created": created, "model": MODEL_ID,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                             "usage": usage})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def chunk(delta, finish_reason=None, **extra):
            data = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": MODEL_ID,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}], **extra}
            self.wfile.write(b"data: " + json.dumps(data).encode("utf-8") + b"\n\n")
            self.wfile.flush()

        if "tool" in reply:
            call = dict(message["tool_calls"][0], index=0)
            chunk({"role": "assistant", "content": None, "tool_calls": [call]})
        else:
            chunk({"role": "assistant", "content": reply["text"]})
        chunk({}, finish)
        self.wfile.write(b"data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk", "created": created, "model": MODEL_ID,
            "choices": [], "usage": usage}).encode("utf-8") + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("script", choices=sorted(SCRIPTS))
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--log", default="")
    args = parser.parse_args(argv)
    Handler.script = SCRIPTS[args.script]
    Handler.log = args.log or None
    class Server(ThreadingHTTPServer):
        allow_reuse_address = False      # on Windows, reuse would let two processes share the port

    server = Server(("127.0.0.1", args.port), Handler)
    print(f"scripted model '{args.script}' on http://127.0.0.1:{args.port}/v1 (pid {__import__('os').getpid()})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Pass chat requests from Hermes to a real OpenAI-compatible endpoint, and keep a log.

    python demo/relay.py --port 8123 --log relay.log [--max-requests 40] [--trace trace.jsonl]

Reads the endpoint from the environment:

    DOCS_DRIFT_BASE_URL   for example https://api.example.com/v1
    DOCS_DRIFT_API_KEY    the key for that endpoint

``demo/run_real.py`` starts this and points Hermes at ``http://127.0.0.1:<port>/v1``.
Request and response bodies are forwarded unchanged. The relay exists for three
reasons:

- the key stays in this process. Hermes is given a placeholder, so the key cannot
  end up in a Hermes log, session file or transcript;
- it counts the chat requests and refuses new ones after ``--max-requests``, so a
  run cannot spend more than planned;
- it logs what the model was sent after each step (tool results, reminders) and
  what the model answered, which is the evidence that the model saw the
  ``docs_drift`` entry.

The log never contains request headers. The system prompt is not logged.

``--trace`` writes a second file for scripts, one JSON object per line: for each
request of the conversation whether it carried something the plugin wrote (a
``docs_drift`` entry with new findings in an edit result, or the reminder), and
for each answer the tool calls in it with their full arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SHOWN = 1400
REMINDER = "docs-drift: your edits in this session"


def told_by_plugin(messages) -> dict:
    """Does this request carry a docs_drift entry with new findings in a tool result, or the reminder."""
    edit = reminder = False
    for message in messages or []:
        role, text = message.get("role"), _text_of(message.get("content"))
        if role == "tool" and '"docs_drift"' in text:
            try:
                entry = (json.loads(text) or {}).get("docs_drift")
            except (ValueError, AttributeError):
                entry = None
            if isinstance(entry, dict) and (entry.get("new") or entry.get("added")):
                edit = True
        elif role != "system" and REMINDER in text:
            reminder = True
    return {"told_edit": edit, "told_reminder": reminder}


def _now() -> str:
    return time.strftime("%H:%M:%SZ", time.gmtime())


def _text_of(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return "" if content is None else str(content)


def _clip(text: str, limit: int = SHOWN) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + f" ... ({len(text) - limit} more characters)"


def describe_tool_result(content: str) -> str:
    """A tool result as logged: the ``docs_drift`` entry in full, the other fields by name."""
    try:
        data = json.loads(content)
    except ValueError:
        return _clip(content)
    if isinstance(data, dict) and "docs_drift" in data:
        rest = sorted(k for k in data if k != "docs_drift")
        return ("(other fields, not shown: " + ", ".join(rest) + ")\n"
                + '"docs_drift": ' + json.dumps(data["docs_drift"], indent=2, ensure_ascii=False))
    return _clip(content)


def describe_message(message: dict) -> str:
    role = message.get("role")
    if role == "tool":
        return "tool result:\n" + describe_tool_result(_text_of(message.get("content")))
    if role == "assistant":
        parts = []
        text = _text_of(message.get("content"))
        if text.strip():
            parts.append(_clip(text, 300))
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            parts.append(f"(its own earlier tool call: {fn.get('name')})")
        return "assistant: " + " ".join(parts)
    return f"{role} message:\n" + _clip(_text_of(message.get("content")))


def read_answer(raw: bytes, content_type: str) -> dict:
    """Text, tool calls and token counts of a response, streamed or not."""
    out = {"text": "", "calls": [], "reasoning_chars": 0, "usage": None}
    body = raw.decode("utf-8", "replace")
    if "text/event-stream" in content_type or body.lstrip().startswith("data:"):
        calls = {}
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                event = json.loads(chunk)
            except ValueError:
                continue
            if event.get("usage"):
                out["usage"] = event["usage"]
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                out["text"] += delta.get("content") or ""
                out["reasoning_chars"] += len(delta.get("reasoning_content") or delta.get("reasoning") or "")
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(call.get("index", 0), {"name": "", "arguments": ""})
                    fn = call.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
        out["calls"] = [calls[k] for k in sorted(calls)]
        return out
    try:
        data = json.loads(body)
    except ValueError:
        out["text"] = body
        return out
    out["usage"] = data.get("usage")
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        out["text"] += _text_of(message.get("content"))
        out["reasoning_chars"] += len(message.get("reasoning_content") or message.get("reasoning") or "")
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            out["calls"].append({"name": fn.get("name") or "", "arguments": fn.get("arguments") or ""})
    return out


class Relay(BaseHTTPRequestHandler):
    server_version = "docs-drift-relay/1"
    base_url = ""
    api_key = ""
    log_path = None
    trace_path = None
    max_requests = 40
    lock = threading.Lock()
    count = 0
    seen = 0          # messages of the main conversation already logged

    def log_message(self, *args):  # keep stderr quiet
        return

    def _log(self, text: str) -> None:
        if self.log_path:
            with self.lock:
                with open(self.log_path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(text + "\n")

    def _trace(self, record: dict) -> None:
        if self.trace_path:
            with self.lock:
                with open(self.trace_path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _upstream(self, path: str) -> str:
        path = path.split("?", 1)[0]
        if path.startswith("/v1"):
            path = path[3:]
        return self.base_url.rstrip("/") + path

    def _forward(self, method: str, body: bytes | None):
        headers = {"Authorization": "Bearer " + self.api_key, "User-Agent": "docs-drift-demo/0.1",
                   "Accept": self.headers.get("Accept") or "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._upstream(self.path), data=body, headers=headers, method=method)
        return urllib.request.urlopen(req, timeout=600)

    def do_GET(self):
        if not self.path.startswith("/v1/"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            with self._forward("GET", None) as resp:
                raw = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type") or "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        except urllib.error.HTTPError as exc:
            self._json(exc.code, {"error": {"message": f"upstream answered HTTP {exc.code}"}})
        except Exception as exc:
            self._json(502, {"error": {"message": f"relay could not reach the endpoint: {type(exc).__name__}"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw_request = self.rfile.read(length)
        if not self.path.split("?", 1)[0].rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            body = json.loads(raw_request or b"{}")
        except ValueError:
            self._json(400, {"error": {"message": "bad json"}})
            return
        with self.lock:
            Relay.count += 1
            number = Relay.count
        if number > self.max_requests:
            self._log(f"[{_now()}] request {number} refused by the relay: the limit of this run is {self.max_requests}")
            self._json(429, {"error": {"message": "request limit of this demo run reached", "type": "relay_limit"}})
            return
        self._log_request(number, body)
        started = time.time()
        try:
            resp = self._forward("POST", raw_request)
        except urllib.error.HTTPError as exc:
            detail = exc.read()
            self._log(f"[{_now()}] answer {number}: HTTP {exc.code} from the endpoint: "
                      + _clip(detail.decode("utf-8", "replace"), 400))
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type") or "application/json")
            self.send_header("Content-Length", str(len(detail)))
            self.end_headers()
            self.wfile.write(detail)
            return
        except Exception as exc:
            self._log(f"[{_now()}] answer {number}: the relay could not reach the endpoint ({type(exc).__name__})")
            self._json(502, {"error": {"message": f"relay could not reach the endpoint: {type(exc).__name__}"}})
            return
        with resp:
            content_type = resp.headers.get("Content-Type") or "application/json"
            # HTTP/1.0 reply without a length: bytes go to Hermes as they arrive, the close ends the body.
            self.send_response(resp.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            chunks = []
            try:
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionError):
                pass
        self.close_connection = True
        answer = read_answer(b"".join(chunks), content_type)
        usage = answer["usage"] or {}
        head = (f"[{_now()}] answer {number} ({time.time() - started:.1f} s, prompt {usage.get('prompt_tokens', '?')} / "
                f"completion {usage.get('completion_tokens', '?')} tokens)")
        lines = []
        if answer["text"].strip():
            lines.append("text: " + _clip(answer["text"]))
        for call in answer["calls"]:
            lines.append(f"tool call: {call['name']} {_clip(call['arguments'], 700)}")
        if not lines:
            lines.append("(empty)")
        self._log(head + ":\n" + "\n".join(lines) + "\n")
        if body.get("tools"):
            self._trace({"answer": number, "calls": answer["calls"]})

    def _log_request(self, number: int, body: dict) -> None:
        messages = body.get("messages") or []
        tools = body.get("tools") or []
        if not tools:
            self._log(f"[{_now()}] request {number}: a side request from Hermes without tools "
                      f"({len(messages)} messages, such as the session title); not part of the conversation")
            return
        self._trace(dict({"request": number}, **told_by_plugin(messages)))
        names = sorted((t.get("function") or {}).get("name", "") for t in tools)
        head = f"[{_now()}] request {number} to model {body.get('model')}: {len(messages)} messages, {len(names)} tools offered"
        with self.lock:
            first = Relay.seen == 0
            new = messages[Relay.seen:] if len(messages) >= Relay.seen else messages
            Relay.seen = len(messages)
        lines = [head]
        if first:
            by_name = [n for n in names if n.startswith("docs_drift")]
            mentioned = any("docs_drift" in json.dumps(t) for t in tools)
            where = ("offered by name: " + ", ".join(by_name)) if by_name else (
                "listed inside another tool's description" if mentioned else "not offered")
            lines.append("docs_drift tools: " + where)
        for message in new:
            if message.get("role") == "system":
                lines.append(f"system prompt ({len(_text_of(message.get('content')))} characters, not shown)")
            else:
                lines.append(describe_message(message))
        self._log("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forward Hermes' chat requests to a real endpoint and log them.")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--max-requests", type=int, default=40)
    ap.add_argument("--trace", default="", help="also write one JSON line per request and answer to this file")
    args = ap.parse_args(argv)
    Relay.base_url = os.environ.get("DOCS_DRIFT_BASE_URL", "")
    Relay.api_key = os.environ.get("DOCS_DRIFT_API_KEY", "")
    if not Relay.base_url or not Relay.api_key:
        print("relay: DOCS_DRIFT_BASE_URL and DOCS_DRIFT_API_KEY must be set", flush=True)
        return 2
    Relay.log_path = args.log
    Relay.trace_path = args.trace or None
    Relay.max_requests = args.max_requests
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Relay)
    print(f"relay on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

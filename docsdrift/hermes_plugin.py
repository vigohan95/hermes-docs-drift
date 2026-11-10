"""Hermes wiring: two tools, three hooks and one slash command.

What happens in a session:

* ``pre_tool_call`` (``write_file`` / ``patch`` only) takes a baseline scan of
  the repository the edit is about to touch, once per session and repository.
* ``transform_tool_result`` re-scans after the edit landed and, only when the
  edit left the docs disagreeing with the code in a way they did not before,
  adds a ``docs_drift`` entry to that tool result. Nothing is added otherwise.
  The re-scan is given the baseline's index of the code, so a flag, variable,
  script, target or file that the session's edits removed is reported wherever
  the docs still use it.
* ``pre_verify`` asks the agent to keep going once if it tries to finish while
  drift it introduced in this session is still open.

Every callback catches its own errors: a problem in this plugin must never
block or change a tool call.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import threading
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .model import CHECKS, Finding, Index, ScanResult
from .report import format_new_drift, format_result
from .scan import DEFAULT_CHECKS, Scanner, apply_ignores, explain, find_root, resolve_checks

logger = logging.getLogger("docs-drift")

TOOLSET = "docs_drift"
EDIT_TOOLS = ("write_file", "patch")
MAX_SCANNERS = 4
MAX_SESSIONS = 16
TOOL_BUDGET_S = 120.0

SETTING_DEFAULTS: Dict[str, Any] = {
    "checks": [],
    "min_confidence": "medium",
    "report_after_edit": True,
    "nudge_before_finish": True,
    "hook_time_budget_s": 8,
    "max_reported": 8,
    "ignore_names": [],
    "ignore_paths": [],
}

_lock = threading.RLock()
_scanners: "OrderedDict[str, Scanner]" = OrderedDict()
_sessions: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
_ctx: Any = None


# ---------------------------------------------------------------- settings
def _setting(key: str) -> Any:
    default = SETTING_DEFAULTS[key]
    getter = getattr(_ctx, "get_config", None)
    if not callable(getter):
        return default
    try:
        value = getter(key, default)
    except Exception:
        return default
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, list):
        if isinstance(value, str):
            return [v for v in re.split(r"[,\s]+", value) if v]
        return list(value) if isinstance(value, (list, tuple, set)) else default
    if isinstance(default, int):
        try:
            return max(1, int(float(value)))
        except (TypeError, ValueError):
            return default
    return str(value)


def _checks_setting(override: Any = None) -> List[str]:
    spec = override if override not in (None, "", []) else (_setting("checks") or None)
    return resolve_checks(spec)


def _min_confidence(override: Any = None) -> str:
    value = str(override or _setting("min_confidence")).strip().lower()
    return value if value in ("high", "medium") else "medium"


# ---------------------------------------------------------------- paths
def _agent_cwd() -> str:
    try:
        from agent.runtime_cwd import resolve_agent_cwd  # Hermes; absent in plain unit tests

        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


def _abs(path: str) -> str:
    path = os.path.expanduser(str(path).strip())
    if not os.path.isabs(path):
        path = os.path.join(_agent_cwd(), path)
    return os.path.abspath(path)


_V4A_HEADER = re.compile(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+?)\s*$|^\*\*\* Move File:\s*(.+?)\s*->\s*(.+?)\s*$", re.M)


def _edit_paths(tool_name: str, args: Any, result: Any = None) -> List[str]:
    """Paths an edit tool call names (arguments first, then what the result says it touched)."""
    out: List[str] = []
    if isinstance(result, dict):
        for key in ("resolved_path", "path"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                out.append(v)
        fm = result.get("files_modified")
        if isinstance(fm, (list, tuple)):
            out.extend(str(v) for v in fm if isinstance(v, str) and v.strip())
    if isinstance(args, dict):
        v = args.get("path")
        if isinstance(v, str) and v.strip():
            out.append(v)
        body = args.get("patch")
        if tool_name == "patch" and isinstance(body, str):
            for m in _V4A_HEADER.finditer(body):
                out.extend(g for g in m.groups() if g)
    seen: Set[str] = set()
    uniq = []
    for p in out:
        a = _abs(p)
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def _roots_for(paths: Iterable[str]) -> List[str]:
    roots: List[str] = []
    for p in paths:
        try:
            root = find_root(p, strict=True)
        except Exception:
            root = None
        if root and root not in roots:
            roots.append(root)
    return roots


def _scanner(root: str) -> Scanner:
    with _lock:
        sc = _scanners.get(root)
        if sc is None:
            sc = Scanner(root)
            _scanners[root] = sc
            while len(_scanners) > MAX_SCANNERS:
                _scanners.popitem(last=False)
        else:
            _scanners.move_to_end(root)
        return sc


def _state(owner: str, root: str, create: bool = True) -> Optional[Dict[str, Any]]:
    key = (owner, root)
    with _lock:
        st = _sessions.get(key)
        if st is None and create:
            # baseline: finding ids before the session's first edit; index: the code side at that moment
            st = {"baseline": None, "index": None, "open": {}}
            _sessions[key] = st
            while len(_sessions) > MAX_SESSIONS:
                _sessions.popitem(last=False)
        elif st is not None:
            _sessions.move_to_end(key)
        return st


def _owner(kw: Dict[str, Any]) -> str:
    return str(kw.get("session_id") or kw.get("task_id") or "default")


def _session_state(root: str, kw: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The edit-tracking state for a repository: this session's, else the most recently used one."""
    with _lock:
        for key in ("session_id", "task_id"):
            owner = (kw or {}).get(key)
            if owner and (str(owner), root) in _sessions:
                return _sessions[(str(owner), root)]
        for (_, r), st in reversed(_sessions.items()):
            if r == root:
                return st
    return None


def _scan(root: str, budget_s: Optional[float], checks: Any = None, min_confidence: Any = None,
          overlay: Optional[Dict[str, Optional[str]]] = None, refresh: bool = True,
          before: Optional[Index] = None) -> ScanResult:
    sc = _scanner(root)
    result = sc.scan(overlay=overlay, checks=_checks_setting(checks), min_confidence=_min_confidence(min_confidence),
                     budget_s=budget_s, refresh=refresh, before=before)
    return apply_ignores(result, _setting("ignore_names"), _setting("ignore_paths"))


# ---------------------------------------------------------------- hooks
def _edit_landed(tool_name: str, result: Any) -> Optional[Dict[str, Any]]:
    """The parsed result when the edit was applied, else None."""
    if not isinstance(result, str):
        return None
    try:
        data = json.loads(result)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    if tool_name == "write_file":
        return data if "bytes_written" in data else None
    if tool_name == "patch":
        return data if data.get("success") is True else None
    return None


def on_pre_tool_call(tool_name: str = "", args: Any = None, **kw: Any) -> None:
    """Take the baseline before the first edit in a repository. Never blocks, never raises."""
    try:
        if tool_name not in EDIT_TOOLS or not _setting("report_after_edit"):
            return None
        owner = _owner(kw)
        budget = float(_setting("hook_time_budget_s"))
        with _lock:
            for root in _roots_for(_edit_paths(tool_name, args)):
                st = _state(owner, root)
                if st["baseline"] is not None:
                    continue
                result = _scan(root, budget)
                if not result.incomplete:
                    st["baseline"], st["index"] = result.ids(), result.index
    except Exception:
        logger.debug("docs-drift pre_tool_call failed", exc_info=True)
    return None


def _baseline_from_git(root: str, budget: float) -> Optional[ScanResult]:
    """Fallback when no pre-edit scan exists: what the scan says with uncommitted changes undone."""
    sc = _scanner(root)
    sc.repo.refresh()
    overlay = sc.repo.changed_vs("HEAD")
    if overlay is None:
        return None
    result = _scan(root, budget, overlay=overlay, refresh=False)
    return None if result.incomplete else result


def _rescan(owner: str, root: str, budget: float) -> Optional[Tuple[List[Finding], List[Finding], int]]:
    """(new findings, findings fixed since the last look, still open) or None when unknown."""
    st = _state(owner, root)
    if st["baseline"] is None:
        base = _baseline_from_git(root, budget)
        if base is not None:
            st["baseline"], st["index"] = base.ids(), base.index
    # Always compared with the session baseline, not with the previous edit: a name the session
    # removed stays reported until the docs (or the code) are fixed.
    current = _scan(root, budget, before=st["index"])
    if current.incomplete:
        return None
    if st["baseline"] is None:
        # Without git there is nothing to compare with: accept the present state silently.
        st["baseline"], st["index"] = current.ids(), current.index
    now = {f.id: f for f in current.findings}
    open_before: Dict[str, Finding] = st["open"]
    fixed = [f for fid, f in open_before.items() if fid not in now]
    new = [f for fid, f in now.items() if fid not in st["baseline"] and fid not in open_before]
    still = {fid: now[fid] for fid in open_before if fid in now}
    for f in new:
        still[f.id] = f
    st["open"] = still
    return new, fixed, len(still)


def on_transform_tool_result(tool_name: str = "", args: Any = None, result: Any = None, **kw: Any) -> Optional[str]:
    """Add a ``docs_drift`` entry to an edit result when that edit caused drift (or fixed reported drift)."""
    try:
        if tool_name not in EDIT_TOOLS or not _setting("report_after_edit"):
            return None
        data = _edit_landed(tool_name, result)
        if data is None:
            return None
        owner = _owner(kw)
        budget = float(_setting("hook_time_budget_s"))
        limit = int(_setting("max_reported"))
        new_all: List[Finding] = []
        fixed_all: List[Finding] = []
        open_total = 0
        with _lock:
            for root in _roots_for(_edit_paths(tool_name, args, data)):
                out = _rescan(owner, root, budget)
                if out is None:
                    continue
                new, fixed, still = out
                new_all.extend(new)
                fixed_all.extend(fixed)
                open_total += still
        if not new_all and not fixed_all:
            return None
        entry: Dict[str, Any] = {}
        if new_all:
            entry["note"] = (
                f"This edit left {len(new_all)} place(s) where the docs no longer match the code. "
                "Update the docs (or the code) before finishing; docs_drift_explain <id> shows both sides."
            )
            entry["new"] = [f.brief() for f in new_all[:limit]]
            if len(new_all) > limit:
                entry["more"] = len(new_all) - limit
        if fixed_all:
            entry["resolved"] = [f.id for f in fixed_all]
        entry["still_open"] = open_total
        if not new_all:
            entry["note"] = f"{len(fixed_all)} docs-drift finding(s) resolved by this edit; {open_total} still open."
        data["docs_drift"] = entry
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        logger.debug("docs-drift transform_tool_result failed", exc_info=True)
        return None


def on_pre_verify(changed_paths: Any = None, attempt: int = 0, **kw: Any) -> Optional[Dict[str, str]]:
    """Keep the turn going once when drift from this session is still open."""
    try:
        if not _setting("nudge_before_finish") or attempt:
            return None
        owner = _owner(kw)
        budget = float(_setting("hook_time_budget_s"))
        still: List[Finding] = []
        with _lock:
            roots = _roots_for(_abs(p) for p in (changed_paths or []) if isinstance(p, str))
            for root in roots:
                st = _state(owner, root, create=False)
                if not st or not st["open"]:
                    continue
                out = _rescan(owner, root, budget)
                if out is None:
                    continue
                still.extend(_state(owner, root)["open"].values())
        if not still:
            return None
        text = format_new_drift(still, limit=int(_setting("max_reported")))
        text = text.replace("this edit left", "your edits in this session left", 1)
        return {"action": "continue", "message": text + "\nFix these (or say why the docs are right) before finishing."}
    except Exception:
        logger.debug("docs-drift pre_verify failed", exc_info=True)
        return None


# ---------------------------------------------------------------- tools
SCAN_SCHEMA = {
    "name": "docs_drift_scan",
    "description": (
        "Check that README and Markdown docs still match the code in a repository: command-line flags, "
        "environment variables, documented defaults, npm scripts, make targets and links to files. "
        "Offline and deterministic (parses files, runs git; no model, no network). Returns findings with "
        "file:line on the docs side and, where known, on the code side. Use changed_only=true after editing "
        "code to see only the drift caused by uncommitted changes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository or any path inside it. Default: the session working directory."},
            "changed_only": {"type": "boolean", "description": "Only report findings introduced by uncommitted changes (compared with git HEAD). Default false."},
            "checks": {
                "type": "array", "items": {"type": "string"},
                "description": "Check ids to run, 'all', or '+id' / '-id' relative to the defaults. Ids: " + ", ".join(CHECKS) + ".",
            },
            "min_confidence": {"type": "string", "enum": ["high", "medium"], "description": "Lowest confidence to report. Default medium."},
            "max_findings": {"type": "integer", "description": "Findings to return (default 30)."},
        },
        "required": [],
    },
}

EXPLAIN_SCHEMA = {
    "name": "docs_drift_explain",
    "description": (
        "Explain one docs-drift finding: the quoted docs lines, the quoted code lines, why it was reported, "
        "and a suggested fix. Take the id from docs_drift_scan or from the docs_drift entry of an edit result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "finding_id": {"type": "string", "description": "Finding id, for example DD-1a2b3c4d."},
            "path": {"type": "string", "description": "Repository or any path inside it. Default: the session working directory."},
        },
        "required": ["finding_id"],
    },
}


def _tool_root(args: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    raw = args.get("path") if isinstance(args, dict) else None
    start = _abs(raw) if isinstance(raw, str) and raw.strip() else _agent_cwd()
    if not os.path.exists(start):
        return None, f"path does not exist: {start}"
    root = find_root(start, strict=True)
    if root is None:
        return None, (
            f"{start} is not inside a project (no .git, pyproject.toml, package.json, go.mod, Cargo.toml, "
            "setup.py or Makefile in it or above it). Pass the repository path."
        )
    return root, None


def _scan_for_tool(root: str, changed_only: bool, checks: Any, min_confidence: Any,
                   before: Optional[Index] = None) -> Tuple[ScanResult, List[Finding], Optional[str]]:
    sc = _scanner(root)
    kw = dict(checks=_checks_setting(checks), min_confidence=_min_confidence(min_confidence), budget_s=TOOL_BUDGET_S)
    if changed_only:
        result, resolved, problem = sc.scan_changes("HEAD", **kw)
    else:
        result, resolved, problem = sc.scan(before=before, **kw), [], None
    return apply_ignores(result, _setting("ignore_names"), _setting("ignore_paths")), resolved, problem


def _session_index(root: str, kw: Optional[Dict[str, Any]] = None) -> Optional[Index]:
    st = _session_state(root, kw)
    return st["index"] if st else None


def handle_scan(args: Any = None, **kw: Any) -> str:
    try:
        args = args if isinstance(args, dict) else {}
        root, err = _tool_root(args)
        if err:
            return json.dumps({"error": err})
        try:
            limit = max(1, min(200, int(args.get("max_findings") or 30)))
        except (TypeError, ValueError):
            limit = 30
        with _lock:
            before = None if args.get("changed_only") else _session_index(root, kw)
            result, resolved, problem = _scan_for_tool(
                root, bool(args.get("changed_only")), args.get("checks"), args.get("min_confidence"), before)
        data = result.to_dict(limit=limit)
        data["checks_run"] = _checks_setting(args.get("checks"))
        if args.get("changed_only"):
            data["compared_with"] = "git HEAD"
            data["resolved_by_changes"] = [f.id for f in resolved]
        elif before is not None:
            data["also_compared_with"] = "the code before this session's first edit: names removed since then are reported"
        if problem:
            data.setdefault("notes", []).append(problem)
        if result.findings:
            data["next"] = "docs_drift_explain with a finding id shows both sides and a suggested fix."
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.debug("docs_drift_scan failed", exc_info=True)
        return json.dumps({"error": f"docs_drift_scan failed: {type(exc).__name__}: {exc}"})


def _find_and_explain(root: str, finding_id: str, kw: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Look for the finding in a fresh scan; findings caused by edits need the pre-edit code to compare with."""
    sc = _scanner(root)
    fid = finding_id.strip()
    before = _session_index(root, kw)
    for checks in (None, "all"):
        result, _, _ = _scan_for_tool(root, False, checks, "medium", before)
        info = explain(sc, result, fid)
        if info is not None:
            return info
    result, _, problem = _scan_for_tool(root, True, "all", "medium")     # uncommitted changes vs git HEAD
    if not problem:
        info = explain(sc, result, fid)
        if info is not None:
            return info
    return None


def handle_explain(args: Any = None, **kw: Any) -> str:
    try:
        args = args if isinstance(args, dict) else {}
        fid = str(args.get("finding_id") or "").strip()
        if not fid:
            return json.dumps({"error": "finding_id is required (for example DD-1a2b3c4d)"})
        root, err = _tool_root(args)
        if err:
            return json.dumps({"error": err})
        with _lock:
            info = _find_and_explain(root, fid, kw)
        if info is None:
            return json.dumps({
                "error": f"no finding with id {fid} in {root}",
                "hint": "It may already be fixed. Run docs_drift_scan to list current findings.",
            })
        return json.dumps(info, ensure_ascii=False)
    except Exception as exc:
        logger.debug("docs_drift_explain failed", exc_info=True)
        return json.dumps({"error": f"docs_drift_explain failed: {type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------- slash command
COMMAND_HELP = (
    "/drift [path]            scan the repository (default: the working directory)\n"
    "/drift --changed [path]  only drift introduced by uncommitted changes\n"
    "/drift --all [path]      also run the opt-in checks\n"
    "/drift explain <id>      show one finding with both sides\n"
    "/drift checks            list the checks"
)


def handle_command(raw_args: str = "") -> str:
    try:
        try:
            words = shlex.split(raw_args or "", posix=(os.name != "nt"))
        except ValueError:
            words = (raw_args or "").split()
        words = [w.strip("\"'") for w in words]
        if words and words[0] in ("help", "--help", "-h"):
            return COMMAND_HELP
        if words and words[0] == "checks":
            enabled = set(_checks_setting())
            return "\n".join(f"{'on ' if cid in enabled else 'off'}  {cid:24} {text}" for cid, text in CHECKS.items())
        if words and words[0] == "explain":
            if len(words) < 2:
                return "usage: /drift explain <id> [path]"
            root, err = _tool_root({"path": words[2] if len(words) > 2 else ""})
            if err:
                return err
            with _lock:
                info = _find_and_explain(root, words[1])
            if info is None:
                return f"no finding with id {words[1]} in {root}"
            lines = [f"{info['doc']}  {info['check']}  [{info['confidence']}]  {info['id']}", f"  {info['problem']}"]
            if info.get("suggestion"):
                lines.append(f"  fix: {info['suggestion']}")
            lines.append("why this was reported:")
            lines.extend(f"  - {w}" for w in info.get("why", []))
            lines.append("docs:")
            lines.extend(info.get("doc_context", []))
            if info.get("code_context"):
                lines.append("code:")
                lines.extend(info["code_context"])
            return "\n".join(lines)
        changed = "--changed" in words
        checks = "all" if "--all" in words else None
        rest = [w for w in words if not w.startswith("--")]
        root, err = _tool_root({"path": rest[0] if rest else ""})
        if err:
            return err
        with _lock:
            before = None if changed else _session_index(root)
            result, resolved, problem = _scan_for_tool(root, changed, checks, None, before)
        title = "docs-drift (new since HEAD)" if changed else "docs-drift"
        text = format_result(result, limit=30, title=f"{title} {root}")
        if problem:
            text += f"\nnote: {problem}"
        if resolved:
            text += f"\nresolved by the changes: {len(resolved)}"
        return text
    except Exception as exc:
        logger.debug("/drift failed", exc_info=True)
        return f"/drift failed: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- register
def register(ctx: Any) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_tool(
        name="docs_drift_scan", toolset=TOOLSET, schema=SCAN_SCHEMA, handler=handle_scan,
        description=SCAN_SCHEMA["description"],
    )
    ctx.register_tool(
        name="docs_drift_explain", toolset=TOOLSET, schema=EXPLAIN_SCHEMA, handler=handle_explain,
        description=EXPLAIN_SCHEMA["description"],
    )
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("transform_tool_result", on_transform_tool_result)
    ctx.register_hook("pre_verify", on_pre_verify)
    register_command = getattr(ctx, "register_command", None)
    if callable(register_command):
        try:
            register_command(
                "drift", handle_command,
                description="Check that README/docs still match the code (docs-drift).",
                args_hint="[--changed|--all] [path] | explain <id> | checks",
            )
        except Exception:  # an older Hermes without slash-command support: tools and hooks still work
            logger.debug("docs-drift: slash command not registered", exc_info=True)


def _reset_for_tests() -> None:
    global _ctx
    with _lock:
        _scanners.clear()
        _sessions.clear()
    _ctx = None


__all__ = ["register", "handle_scan", "handle_explain", "handle_command",
           "on_pre_tool_call", "on_transform_tool_result", "on_pre_verify", "DEFAULT_CHECKS"]

"""Code-side facts: what the code defines, reads and exposes.

Two kinds of knowledge are collected:

* structured facts with a file and line (an ``add_argument("--x")`` call, an
  ``os.environ.get("X", "v")`` read, a ``scripts`` entry in package.json);
* cheap whole-repository traces (every ``--flag`` literal, every
  ENV_SHAPED token) used to decide that a documented name is *known*.

A documented name is only reported when it has no trace at all, so the trace
side errs towards "known".
"""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover - older interpreters
    _toml = None

from .repo import Repo

ENV_TOKEN = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![A-Za-z0-9_])")
FLAG_LITERAL = re.compile(r"(?<![\w-])--([a-zA-Z][\w-]*)")

_LIT = r"(\"[^\"\n]*\"|'[^'\n]*'|-?\d+(?:\.\d+)?|True|False|true|false)"
ENV_READ_CALL = re.compile(
    r"(?:os\.environ\.get|os\.getenv|environ\.get|getenv|os\.Getenv|os\.LookupEnv|"
    r"env::var(?:_os)?|System\.getenv|ENV\.fetch|Deno\.env\.get|env\.get|env\.str|env\.int|"
    r"env\.bool|env)\s*\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']\s*(?:,\s*" + _LIT + r"\s*)?[,)]"
)
ENV_READ_INDEX = re.compile(
    r"(?:os\.environ|environ|\$_SERVER|process\.env\b|(?:\$_)?ENV)\s*\[\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']\s*\]"
)
ENV_READ_ATTR = re.compile(
    r"(?:process|import\.meta)\.env\.([A-Z][A-Z0-9_]{2,})\b(?:\s*(?:\|\||\?\?)\s*"
    + r"(\"[^\"\n]*\"|'[^'\n]*'|`[^`\n$]*`|-?\d+(?:\.\d+)?|true|false))?"
)
# Seen only by the edit-aware path (what an edit removed), never by a plain scan:
# a read of a variable whose name starts with an underscore (zoxide's ``_ZO_MAXAGE``),
# and a variable click or typer binds to an option with ``envvar=``.
_UNDER = r"(_[A-Z][A-Z0-9_]{2,})"
UNDER_ENV_TOKEN = re.compile(r"(?<![A-Za-z0-9_])_[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*(?![A-Za-z0-9_])")
UNDER_ENV_READ = re.compile(
    r"(?:os\.environ\.get|os\.getenv|environ\.get|getenv|os\.Getenv|os\.LookupEnv|env::var(?:_os)?|"
    r"System\.getenv|ENV\.fetch|Deno\.env\.get|env\.get)\s*\(\s*[\"']" + _UNDER + r"[\"']"
    r"|(?:os\.environ|environ|\$_SERVER|process\.env\b|(?:\$_)?ENV)\s*\[\s*[\"']" + _UNDER + r"[\"']\s*\]"
    r"|(?:process|import\.meta)\.env\." + _UNDER + r"\b"
)
ENVVAR_BINDING = re.compile(r"\benvvar\s*=\s*(\[[^\]\n]*\]|\([^)\n]*\)|\"[^\"\n]*\"|'[^'\n]*')")
_ENVVAR_NAME = re.compile(r"[\"']([A-Z_][A-Z0-9_]{2,})[\"']")
DYN_PREFIX = re.compile(r"[\"'`]([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_)(?:[\"'`]|\{|\$\{|%s|%\()")
ENV_PREFIX_DECL = re.compile(
    r"(?i)(?:env_?prefix|SetEnvPrefix|envPrefix|env_nested_delimiter|prefix)\s*[=:(]\s*[\"']([A-Za-z][A-Za-z0-9_]*)[\"']"
)
AUTO_ENV = re.compile(
    r"BaseSettings|pydantic_settings|AutomaticEnv\(|envconfig\.Process|auto_envvar_prefix|"
    r"environs|dynaconf|decouple|figment|envy::|clap\([^)]*env\b|arg\([^)]*env\b|"
    r"process\.env\[\s*[A-Za-z_`]|os\.environ\[\s*[a-z_]|os\.environ\.get\(\s*[a-z_f]|"
    r"os\.getenv\(\s*[a-z_f]|os\.Getenv\(\s*[a-z]|ENV\[\s*[a-z]|convict\(|dotenv-flow|"
    r"env-var|envalid|znv|t3-oss/env\b|from_env\b|envsubst|std::env::vars|os\.Environ\(\)|"
    r"for\s+\w+\s*,\s*\w+\s+in\s+os\.environ|Object\.(?:keys|entries)\(process\.env\)"
)

_AUTO_ENV_NO_ENV_WORD = re.compile(r"BaseSettings|pydantic_settings|dynaconf|decouple|figment|convict\(")

_CSS_LIKE = (".css", ".scss", ".sass", ".less", ".styl", ".svg", ".html", ".htm", ".vue", ".svelte")
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|e2e|testdata|fixtures?|__fixtures__|examples?|"
    r"samples?|benchmarks?|bench|demos?|docs?|website|scripts|tools|hack|ci|\.github|"
    r"\.circleci|vendor|third_party|node_modules)(/|$)|(_test\.go|[._-]test\.[a-z]+|"
    r"[._-]spec\.[a-z]+|conftest\.py|test_[^/]*\.py)$",
    re.I,
)


def is_support_path(rel: str) -> bool:
    """Tests, examples, CI and tooling: real code, but not the product surface."""
    return bool(_TEST_PATH.search(rel))


@dataclass
class Fact:
    kind: str                 # "flag" | "env" | "env-edit" (used only to tell what an edit removed)
    name: str                 # "--dry-run" | "APP_PORT"
    file: str
    line: int
    default: Any = None
    has_default: bool = False
    framework: str = ""
    hidden: bool = False


@dataclass
class FileFacts:
    env_tokens: Set[str] = field(default_factory=set)
    under_tokens: Set[str] = field(default_factory=set)      # _NAMES written in the file
    flag_literals: Set[str] = field(default_factory=set)
    facts: List[Fact] = field(default_factory=list)
    dyn_prefixes: Set[str] = field(default_factory=set)
    auto_env: bool = False


def norm_flag(name: str) -> str:
    """Canonical flag key: no dashes in front, ``_`` -> ``-``, lowercase."""
    return name.lstrip("-").replace("_", "-").lower()


def _unquote(lit: Optional[str]) -> Any:
    if lit is None:
        return None
    s = lit.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        return s[1:-1]
    if s in ("True", "true"):
        return True
    if s in ("False", "false"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- Python (ast)
def _const(node: ast.AST, consts: Dict[str, Any]) -> Tuple[bool, Any]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return True, node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return True, consts[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        ok, v = _const(node.operand, consts)
        if ok and isinstance(v, (int, float)) and not isinstance(v, bool):
            return True, -v
    return False, None


def _python_facts(rel: str, text: str, out: FileFacts) -> None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return
    consts: Dict[str, Any] = {}
    seen_twice: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (str, int, float, bool)):
                if name in consts:
                    seen_twice.add(name)
                consts[name] = node.value.value
    for name in seen_twice:
        consts.pop(name, None)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
        if attr not in ("add_argument", "option", "Option", "add_option"):
            continue
        names: List[str] = []
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--"):
                for part in a.value.split("/"):
                    part = part.strip().split(" ")[0]
                    if part.startswith("--") and len(part) > 2:
                        names.append(part)
        if not names:
            continue
        has_default = False
        default: Any = None
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        if "default" in kw:
            has_default, default = _const(kw["default"], consts)
            if default is None:
                has_default = False
        elif attr == "Option" and node.args:
            ok, v = _const(node.args[0], consts)
            first_is_name = isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and node.args[0].value.startswith("-")
            if ok and v is not None and not first_is_name:
                has_default, default = True, v
        if not has_default:
            action = kw.get("action")
            if isinstance(action, ast.Constant) and action.value == "store_true":
                has_default, default = True, False
            elif isinstance(action, ast.Constant) and action.value == "store_false":
                has_default, default = True, True
            elif attr == "option":
                is_flag = kw.get("is_flag")
                if isinstance(is_flag, ast.Constant) and is_flag.value is True:
                    has_default, default = True, False
        framework = "argparse" if attr == "add_argument" else ("typer" if attr == "Option" else "click")
        hidden = False
        help_node = kw.get("help")
        if isinstance(help_node, ast.Attribute) and help_node.attr == "SUPPRESS":
            hidden = True
        elif isinstance(help_node, ast.Name) and help_node.id == "SUPPRESS":
            hidden = True
        hid = kw.get("hidden")
        if isinstance(hid, ast.Constant) and hid.value is True:
            hidden = True
        for i, n in enumerate(names):
            if n.startswith("--no-") and i > 0:
                out.flag_literals.add(norm_flag(n))
                continue
            out.facts.append(Fact("flag", n, rel, node.lineno, default, has_default, framework, hidden))


# ---------------------------------------------------------------- JS / Go (regex)
def _call_args(text: str, open_paren: int, limit: int = 600) -> List[str]:
    """Top-level arguments of the call whose ``(`` is at ``open_paren``."""
    depth = 0
    quote = ""
    cur = ""
    args: List[str] = []
    end = min(len(text), open_paren + limit)
    i = open_paren
    while i < end:
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\" and i + 1 < end:
                cur += text[i + 1]
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            if depth > 1:
                cur += ch
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                if cur.strip():
                    args.append(cur.strip())
                return args
            cur += ch
        elif ch == "," and depth == 1:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    return []


_JS_OPTION = re.compile(r"\.(?:option|requiredOption|addOption\(\s*new\s+Option)\s*\(")
_JS_LITERAL = re.compile(r"^(\"[^\"]*\"|'[^']*'|`[^`$]*`|-?\d+(?:\.\d+)?|true|false)$")
_GO_FLAG = re.compile(
    r"(?:\bflag|\bpflag|\bfs|\bflags|\bflagSet|\bFlagSet|Flags\(\))\."
    r"(?:String|Int|Bool|Duration|Float64|Int64|Uint|Uint64|StringSlice|StringArray|Count|IntSlice)"
    r"(?:Var)?(P)?\(\s*(?:&[\w.\[\]]+\s*,\s*)?\"([a-zA-Z][\w.-]*)\"\s*,\s*(?:\"[^\"]{0,1}\"\s*,\s*)?([^,\n]+),"
)


def _js_facts(rel: str, text: str, out: FileFacts) -> None:
    for m in _JS_OPTION.finditer(text):
        args = _call_args(text, m.end() - 1)
        if not args:
            continue
        first = args[0]
        if not (first[:1] in "\"'`"):
            continue
        spec = first.strip("\"'`")
        line = _line_of(text, m.start())
        longs = re.findall(r"--([a-zA-Z][\w-]*)", spec)
        if longs:
            default: Any = None
            has_default = False
            for cand in args[2:4]:
                if _JS_LITERAL.match(cand):
                    default, has_default = _unquote(cand), True
                    break
            for n in longs:
                if n.startswith("no-"):
                    out.flag_literals.add(norm_flag(n))
                    continue
                out.facts.append(Fact("flag", "--" + n, rel, line, default, has_default, "commander"))
        elif re.match(r"^[a-zA-Z][\w-]*$", spec) and len(args) >= 2 and args[1].startswith("{"):
            body = args[1]
            dm = re.search(r"\bdefault\s*:\s*(\"[^\"]*\"|'[^']*'|-?\d+(?:\.\d+)?|true|false)\s*[,}\n]", body + "}")
            default = _unquote(dm.group(1)) if dm else None
            out.facts.append(Fact("flag", "--" + spec, rel, line, default, bool(dm), "yargs"))
            out.flag_literals.add(norm_flag(spec))


def _go_facts(rel: str, text: str, out: FileFacts) -> None:
    for m in _GO_FLAG.finditer(text):
        name = m.group(2)
        raw = m.group(3).strip()
        default: Any = None
        has_default = False
        if re.match(r"^(\"[^\"]*\"|-?\d+(?:\.\d+)?|true|false)$", raw):
            default, has_default = _unquote(raw), True
        out.facts.append(Fact("flag", "--" + name, rel, _line_of(text, m.start()), default, has_default, "go-flag"))
        out.flag_literals.add(norm_flag(name))


def extract_file(rel: str, text: str) -> FileFacts:
    out = FileFacts()
    low = rel.lower()
    if "_" in text:
        out.env_tokens = set(ENV_TOKEN.findall(text))
    if "--" in text and not low.endswith(_CSS_LIKE):
        out.flag_literals = {norm_flag(m) for m in FLAG_LITERAL.findall(text)}
    if "env" in text or "ENV" in text or "Env" in text:
        seen_env: Set[Tuple[str, int]] = set()
        for rx in (ENV_READ_CALL, ENV_READ_ATTR, ENV_READ_INDEX):
            for m in rx.finditer(text):
                name = m.group(1)
                line = _line_of(text, m.start())
                if (name, line) in seen_env:
                    continue
                seen_env.add((name, line))
                lit = m.group(2) if rx is not ENV_READ_INDEX and m.lastindex and m.lastindex >= 2 else None
                out.facts.append(Fact("env", name, rel, line, _unquote(lit), lit is not None, "env"))
        out.auto_env = bool(AUTO_ENV.search(text))
        if "envvar" in text:
            for m in ENVVAR_BINDING.finditer(text):
                line = _line_of(text, m.start())
                for name in _ENVVAR_NAME.findall(m.group(1)):
                    out.facts.append(Fact("env-edit", name, rel, line, None, False, "envvar"))
    else:
        out.auto_env = bool(_AUTO_ENV_NO_ENV_WORD.search(text))
    if '"_' in text or "'_" in text or "._" in text:
        out.under_tokens = set(UNDER_ENV_TOKEN.findall(text))
        if out.under_tokens:
            for m in UNDER_ENV_READ.finditer(text):
                name = m.group(1) or m.group(2) or m.group(3)
                out.facts.append(Fact("env-edit", name, rel, _line_of(text, m.start()), None, False, "env"))
    if '_"' in text or "_'" in text or "_`" in text or "_{" in text or "_$" in text or "_%" in text:
        out.dyn_prefixes = set(DYN_PREFIX.findall(text))
    if "refix" in text or "REFIX" in text:
        for m in ENV_PREFIX_DECL.finditer(text):
            out.dyn_prefixes.add(m.group(1).upper().rstrip("_") + "_")
    if low.endswith((".py", ".pyi")):
        if "add_argument(" in text or "ption(" in text:
            _python_facts(rel, text, out)
    elif low.endswith((".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".mts", ".cts")):
        if "ption(" in text:
            _js_facts(rel, text, out)
    elif low.endswith(".go") and ("flag" in text or "Flags()" in text):
        _go_facts(rel, text, out)
    return out


# ---------------------------------------------------------------- project level
@dataclass
class Project:
    names: Set[str] = field(default_factory=set)           # project / package names
    commands: Dict[str, str] = field(default_factory=dict)  # own command -> where declared
    npm_scripts: Dict[str, str] = field(default_factory=dict)   # script -> package.json path
    has_package_json: bool = False
    make_targets: Dict[str, str] = field(default_factory=dict)  # target -> "Makefile:12"
    make_patterns: List[str] = field(default_factory=list)
    make_dynamic: bool = False
    has_makefile: bool = False
    generated_makefile: bool = False
    site_roots: List[str] = field(default_factory=list)     # directories of docs-site configs
    python_packages: Set[str] = field(default_factory=set)  # top-level importable packages


_SITE_CONFIG = re.compile(
    r"(^|/)(mkdocs\.ya?ml|docusaurus\.config\.[cm]?[jt]s|conf\.py|_config\.ya?ml|book\.toml|"
    r"hugo\.(toml|ya?ml|json)|config\.toml|astro\.config\.[cm]?[jt]s|next\.config\.[cm]?[jt]s|"
    r"gatsby-config\.[jt]s|\.vitepress/config\.[cm]?[jt]s|\.vuepress/config\.[jt]s|"
    r"docs\.json|mint\.json|antora\.yml|_quarto\.yml|typedoc\.json|sidebars?\.[jt]s(on)?|"
    r"SUMMARY\.md|_sidebar\.md|_toc\.yml|nav\.ya?ml|\.readthedocs\.ya?ml)$"
)
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.@%/$(){}-]+(?:[ \t]+[A-Za-z0-9_.@%/$(){}-]+)*)[ \t]*::?(?!=)")
_MAKEFILE_NAME = re.compile(r"(^|/)(GNUmakefile|[Mm]akefile(\.[\w-]+)?|[\w.-]+\.mk)$")
_GENERATED_MAKE = re.compile(
    r"(^|/)(CMakeLists\.txt|configure\.ac|configure\.in|Makefile\.in|Makefile\.am|Makefile\.PL|"
    r"meson\.build|configure|Makefile\.SH|extconf\.rb|SConstruct|Imakefile)$"
)


def _load_toml(text: str) -> Dict[str, Any]:
    if _toml is None:
        return {}
    try:
        return _toml.loads(text)
    except Exception:
        return {}


def _toml_section_keys(text: str, section: str) -> List[str]:
    """Keys of ``[section]`` without a TOML parser (fallback for old Pythons)."""
    m = re.search(r"^\[" + re.escape(section) + r"\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not m:
        return []
    return re.findall(r"^\s*[\"']?([\w.-]+)[\"']?\s*=", m.group(1), re.M)


def scan_project(repo: Repo) -> Project:
    p = Project()
    p.names.add(os.path.basename(repo.root.rstrip("/\\")))
    origin = repo.origin_name()
    if origin:
        p.names.add(origin)
    for rel in repo.files:
        name = rel.rsplit("/", 1)[-1]
        depth = rel.count("/")
        if "node_modules/" in rel:
            continue
        if _SITE_CONFIG.search(rel) and name != "config.toml" or (name == "config.toml" and repo.has_dir((rel.rsplit("/", 1)[0] + "/content").lstrip("/"))):
            p.site_roots.append(rel.rsplit("/", 1)[0] if "/" in rel else "")
        if _GENERATED_MAKE.search(rel) and depth <= 1:
            p.generated_makefile = True
        if name == "package.json":
            text = repo.read(rel)
            if text is None:
                continue
            try:
                data = json.loads(text)
            except (ValueError, RecursionError):
                continue
            if not isinstance(data, dict):
                continue
            p.has_package_json = True
            pkg_name = data.get("name") if isinstance(data.get("name"), str) else ""
            if pkg_name and depth == 0:
                p.names.add(pkg_name.split("/")[-1])
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                for k in scripts:
                    p.npm_scripts.setdefault(str(k), rel)
            b = data.get("bin")
            if isinstance(b, str) and pkg_name:
                p.commands.setdefault(pkg_name.split("/")[-1], rel)
            elif isinstance(b, dict):
                for k in b:
                    p.commands.setdefault(str(k), rel)
        elif name == "pyproject.toml":
            text = repo.read(rel) or ""
            data = _load_toml(text)
            proj = data.get("project") if isinstance(data.get("project"), dict) else {}
            poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else {}
            poetry = poetry if isinstance(poetry, dict) else {}
            for src in (proj, poetry):
                if isinstance(src.get("name"), str) and depth == 0:
                    p.names.add(src["name"])
                scripts = src.get("scripts")
                if isinstance(scripts, dict):
                    for k in scripts:
                        p.commands.setdefault(str(k), rel)
            if not data:
                for sec in ("project.scripts", "tool.poetry.scripts"):
                    for k in _toml_section_keys(text, sec):
                        p.commands.setdefault(k, rel)
        elif name in ("setup.py", "setup.cfg"):
            text = repo.read(rel) or ""
            m = re.search(r"console_scripts[\"']?\s*[:=]\s*(.{0,2000})", text, re.S)
            if m:
                for cm in re.finditer(r"[\"']?\s*([A-Za-z][\w.-]*)\s*=\s*[\w.]+:[\w.]+", m.group(1)):
                    p.commands.setdefault(cm.group(1), rel)
        elif name == "Cargo.toml":
            text = repo.read(rel) or ""
            data = _load_toml(text)
            pkg = data.get("package") if isinstance(data.get("package"), dict) else {}
            has_main = repo.has_file((rel.rsplit("/", 1)[0] + "/src/main.rs").lstrip("/")) if "/" in rel else repo.has_file("src/main.rs")
            if isinstance(pkg.get("name"), str) and has_main:
                p.commands.setdefault(pkg["name"], rel)
            for b in data.get("bin") or []:
                if isinstance(b, dict) and isinstance(b.get("name"), str):
                    p.commands.setdefault(b["name"], rel)
        elif name == "go.mod" and depth == 0:
            text = repo.read(rel) or ""
            m = re.search(r"^module\s+(\S+)", text, re.M)
            if m:
                base = m.group(1).rstrip("/").split("/")[-1]
                if re.match(r"^v\d+$", base) and "/" in m.group(1):
                    base = m.group(1).rstrip("/").split("/")[-2]
                p.names.add(base)
                if repo.has_file("main.go"):
                    p.commands.setdefault(base, rel)
        elif _MAKEFILE_NAME.search(rel):
            text = repo.read(rel)
            if text is None:
                continue
            p.has_makefile = True
            for i, ln in enumerate(text.splitlines(), 1):
                if ln.startswith(("\t", "#", " ")) or not ln.strip():
                    if re.match(r"^\s*(-?include|sinclude)\s", ln):
                        p.make_dynamic = p.make_dynamic or "$(" in ln
                    continue
                if re.match(r"^(-?include|sinclude)\s", ln):
                    if "$(" in ln or "${" in ln or "*" in ln:
                        p.make_dynamic = True
                    else:
                        # An included file that is not in the repository is generated.
                        base = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
                        for inc in ln.split()[1:]:
                            if not (repo.has_file(base + inc) or repo.has_file(inc)):
                                p.make_dynamic = True
                    continue
                if "$(eval" in ln or "$(foreach" in ln or ln.startswith("define "):
                    p.make_dynamic = True
                m = _MAKE_TARGET.match(ln)
                if not m:
                    continue
                for t in m.group(1).split():
                    if "$" in t:
                        p.make_dynamic = True
                    elif "%" in t:
                        p.make_patterns.append(t)
                    elif t == ".PHONY":
                        for ph in ln.split(":", 1)[1].split():
                            if "$" not in ph:
                                p.make_targets.setdefault(ph, f"{rel}:{i}")
                    else:
                        p.make_targets.setdefault(t, f"{rel}:{i}")
        elif name in ("__init__.py", "__main__.py"):
            parts = rel.split("/")
            if len(parts) == 2:
                p.python_packages.add(parts[0])
            elif len(parts) == 3 and parts[0] in ("src", "lib", "python"):
                p.python_packages.add(parts[1])
    for rel in repo.files:
        parts = rel.split("/")
        if len(parts) == 3 and parts[0] == "cmd" and parts[2] == "main.go":
            p.commands.setdefault(parts[1], rel)
    p.names = {n for n in p.names if n}
    return p

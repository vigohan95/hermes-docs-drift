"""The checks. Each one compares claims found in docs with facts from code.

Design rule shared by all of them: a finding needs positive evidence that the
doc line is about *this* project (its own command, its own variable prefix,
its own Makefile) and no trace of the documented name in the code. When either
part is uncertain the finding is dropped and counted in ``suppressed``.
"""

from __future__ import annotations

import difflib
import fnmatch
import posixpath
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote

from .docs import Command, Doc, block_at, commands_of, table_columns, table_header_for
from .facts import ENV_TOKEN, FLAG_LITERAL, Fact, Project, is_support_path, norm_flag
from .model import Finding
from .repo import Repo

THIRD_PARTY_ENV_PREFIXES = {
    "AWS", "GITHUB", "GITLAB", "CI", "DOCKER", "NODE", "NPM", "YARN", "PNPM", "PYTHON", "PIP",
    "UV", "GOOGLE", "GCP", "GCLOUD", "AZURE", "ARM", "OPENAI", "ANTHROPIC", "HF", "HUGGINGFACE",
    "KUBE", "KUBERNETES", "K8S", "XDG", "LC", "SSL", "HTTP", "HTTPS", "NO", "ALL", "GIT", "SSH",
    "TF", "CARGO", "RUST", "RUSTUP", "GO", "JAVA", "CUDA", "OMP", "MKL", "TORCH", "TRANSFORMERS",
    "WANDB", "POSTGRES", "PG", "MYSQL", "REDIS", "MONGO", "MONGODB", "DATABASE", "DB", "OTEL",
    "SENTRY", "VERCEL", "NETLIFY", "NEXT", "VITE", "REACT", "GATSBY", "NUXT", "EXPO", "DJANGO",
    "FLASK", "CELERY", "RAILS", "RACK", "BUNDLE", "GEM", "COMPOSER", "PHP", "TERM", "LANG",
    "HOME", "PATH", "USER", "TMP", "TEMP", "DEBUG", "LOG", "SMTP", "MAIL", "S3", "MINIO",
    "CLOUDFLARE", "CF", "STRIPE", "TWILIO", "SLACK", "DISCORD", "TELEGRAM", "JWT", "OAUTH",
    "API", "APP", "SECRET", "MAX", "MIN", "DEFAULT", "ENABLE", "DISABLE", "USE", "IS", "HAS",
    "CMAKE", "CC", "CXX", "LD", "MAKE", "QT", "ANDROID", "IOS", "XCODE", "JAVA", "GRADLE",
    "MAVEN", "SPRING", "DOTNET", "ASPNETCORE", "NUGET", "ELECTRON", "CHROME", "PUPPETEER",
    "PLAYWRIGHT", "CYPRESS", "JEST", "PYTEST", "TOX", "COVERAGE", "CODECOV", "SONAR", "TRAVIS",
    "CIRCLE", "CIRCLECI", "BUILDKITE", "JENKINS", "RUNNER", "ACTIONS", "INPUT", "DEPENDABOT",
    "OLLAMA", "LANGCHAIN", "GEMINI", "MISTRAL", "GROQ", "COHERE", "PINECONE", "SUPABASE",
    "FIREBASE", "HEROKU", "FLY", "RENDER", "RAILWAY", "DIGITALOCEAN", "LINODE", "VULTR",
    "ELASTIC", "ELASTICSEARCH", "KAFKA", "RABBITMQ", "AMQP", "NATS", "ETCD", "CONSUL", "VAULT",
    "NOMAD", "PROMETHEUS", "GRAFANA", "DATADOG", "DD", "NEW", "SQL", "ODBC", "ORACLE", "LD",
    "DYLD", "SYSTEMD", "DBUS", "WAYLAND", "DISPLAY", "SHELL", "EDITOR", "PAGER", "TZ", "HOST",
    "HOSTNAME", "PORT", "SERVER", "CLIENT", "TEST", "DEV", "PROD", "STAGING", "LOCAL", "REMOTE",
    "SOURCE", "TARGET", "BUILD", "RELEASE", "VERSION", "INSTALL", "PREFIX", "CONFIG", "DATA",
    "CACHE", "OUTPUT", "INPUT", "FILE", "DIR", "ROOT", "BASE", "WORK", "PROJECT", "REPO",
    "BRANCH", "COMMIT", "TAG", "IMAGE", "CONTAINER", "COMPOSE", "HELM", "ANSIBLE", "TERRAFORM",
    "PULUMI", "CDK", "SAM", "SERVERLESS", "LAMBDA", "EC2", "ECS", "EKS", "RDS", "SQS", "SNS",
    "HTTP2", "TLS", "CERT", "CA", "KEY", "TOKEN", "AUTH", "LOGIN", "PASSWORD", "ADMIN", "MY",
    "YOUR", "SOME", "FOO", "BAR", "EXAMPLE", "SAMPLE", "DEMO", "CUSTOM", "EXTRA", "OTHER",
}

WRAPPER_PREFIXES = [
    ["uv", "run"], ["poetry", "run"], ["pipenv", "run"], ["pdm", "run"], ["hatch", "run"],
    ["rye", "run"], ["pipx", "run"], ["pnpm", "exec"], ["pnpm", "dlx"], ["yarn", "dlx"],
    ["bundle", "exec"], ["npx"], ["pnpx"], ["bunx"], ["uvx"], ["sudo"], ["time"], ["exec"],
    ["command"], ["nohup"], ["winpty"],
]
PASSTHROUGH_WORDS = {"run", "exec", "x", "dlx", "shell", "wrap", "with", "spawn", "ssh", "sh", "watch", "do"}
IGNORED_FLAGS = {"help", "version", "h", "v"}

CONTRIBUTOR_DOC = re.compile(
    r"(readme|contributing|development|developing|developers?|hacking|building|build|install\w*|"
    r"setup|getting[-_ ]?started|quick[-_ ]?start|usage|testing|maintain\w*|agents|claude)",
    re.I,
)
FOREIGN_BLOCK = re.compile(
    r"\b(wget|curl|tar\s|unzip|npx\s+create-|npm\s+init|npm\s+create|yarn\s+create|pnpm\s+create|"
    r"cargo\s+new|cargo\s+init|django-admin|rails\s+new|composer\s+create|dotnet\s+new|cmake|"
    r"\./configure|docker\s+(run|exec)|kubectl|ssh\s|degit|create-react-app|vue\s+create|ng\s+new)"
)
PATH_REF = re.compile(r"^\.?/?[\w@.+-]+(?:/[\w@.+-]+)+$")
PATH_REF_EXT = {
    "py", "pyi", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "rb", "java", "kt", "c", "h",
    "cc", "cpp", "hpp", "cs", "php", "sh", "bash", "ps1", "yml", "yaml", "toml", "json", "md",
    "mdx", "cfg", "ini", "sql", "proto", "tf", "lua", "swift", "mk", "gradle", "ex", "exs", "vue",
    "svelte", "css", "scss", "html",
}
PLACEHOLDER_WORDS = re.compile(
    r"(^|[/_.-])(your|my|example|examples?|foo|bar|baz|xxx|some|sample|path|to|name|file|filename|"
    r"project|app|myapp|module|package|component|dir|folder|src/index|src/main|src/app|lib/index)([/_.-]|$)",
    re.I,
)
GENERATED_FIRST_SEG = {"dist", "build", "out", "target", "node_modules", "coverage", ".next", "bin", "obj", "public", "tmp", "_build", "site"}
SITE_DIR_NAMES = {"docs", "doc", "website", "site", "content", "documentation", "book", "guide", "guides", "pages", "wiki"}
DEFAULT_RX = re.compile(
    r"(?i)\bdefaults?\b(?:\s+value)?\s*(?:is|to|of|are)?\s*[:=]?\s*"
    r"(`[^`]+`|\"[^\"]+\"|'[^']+'|-?\d+(?:\.\d+)?(?![\w.%])|\btrue\b|\bfalse\b)"
)
OPTION_SPAN = re.compile(r"^(?:-[A-Za-z](?:,|\s|/)\s*)?--([a-zA-Z][\w-]*)(?:[\s=,|/\[<].*)?$")
LIST_OR_TABLE_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|<t[dr]|<li|<dt)")
HIDDEN_NAME = re.compile(r"(debug|internal|experimental|deprecated|hidden|unsafe|legacy|test|dev|ci)", re.I)


def _clip(s: str, n: int = 180) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


class Context:
    """Everything a check needs: the repo, parsed docs and the code index."""

    def __init__(
        self,
        repo: Repo,
        docs: List[Doc],
        project: Project,
        env_tokens: Set[str],
        flag_literals: Set[str],
        facts: List[Fact],
        dyn_prefixes: Set[str],
        auto_env: bool,
        loose: Callable[[Iterable[str]], Set[str]],
        doc_mentions: Callable[[], Tuple[Set[str], Set[str]]],
    ):
        self.repo = repo
        self.docs = docs
        self.project = project
        self.env_tokens = env_tokens
        self.flag_literals = flag_literals
        self.facts = facts
        self.dyn_prefixes = dyn_prefixes
        self.auto_env = auto_env
        self.loose = loose
        self.doc_mentions = doc_mentions
        self.suppressed: Dict[str, int] = {}
        self.notes: List[str] = []
        self._commands: Dict[str, List[Command]] = {}
        self._flag_lines: Dict[str, Dict[str, int]] = {}
        self._env_lines: Dict[str, Dict[str, int]] = {}
        self._by_path: Dict[str, Doc] = {d.path: d for d in docs}
        self.env_facts: Dict[str, List[Fact]] = {}
        self.flag_facts: Dict[str, List[Fact]] = {}
        for f in facts:
            if f.kind == "env":
                self.env_facts.setdefault(f.name, []).append(f)
            else:
                self.flag_facts.setdefault(norm_flag(f.name), []).append(f)
        self.name_keys: Set[str] = set()
        for n in project.names:
            pieces = [x for x in re.split(r"[^A-Za-z0-9]+", n.upper()) if x]
            if pieces:
                self.name_keys.add(pieces[0])
                self.name_keys.add("".join(pieces))
                self.name_keys.add("_".join(pieces))

    def flag_lines(self, doc: Doc) -> Dict[str, int]:
        """flag key -> first line in this doc that writes ``--flag``."""
        hit = self._flag_lines.get(doc.path)
        if hit is None:
            hit = {}
            for i, ln in enumerate(doc.lines, 1):
                if "--" in ln:
                    for m in FLAG_LITERAL.findall(ln):
                        hit.setdefault(norm_flag(m), i)
            self._flag_lines[doc.path] = hit
        return hit

    def env_lines(self, doc: Doc) -> Dict[str, int]:
        """ENV_NAME -> first line in this doc that mentions it."""
        hit = self._env_lines.get(doc.path)
        if hit is None:
            hit = {}
            for i, ln in enumerate(doc.lines, 1):
                if "_" in ln:
                    for m in ENV_TOKEN.findall(ln):
                        hit.setdefault(m, i)
            self._env_lines[doc.path] = hit
        return hit

    def skip(self, reason: str, n: int = 1) -> None:
        self.suppressed[reason] = self.suppressed.get(reason, 0) + n

    def commands(self, doc: Doc) -> List[Command]:
        if doc.path not in self._commands:
            self._commands[doc.path] = commands_of(doc)
        return self._commands[doc.path]

    def code_line(self, rel: str, line: int) -> str:
        text = self.repo.read(rel)
        if not text or line <= 0:
            return ""
        lines = text.splitlines()
        return _clip(lines[line - 1]) if line <= len(lines) else ""

    def foreign_block(self, doc: Doc, cmd: Command) -> bool:
        """True when the surrounding code block sets up some other project."""
        if cmd.inline:
            return False
        blk = block_at(doc, cmd.block_start)
        if blk is None:
            return False
        text = "\n".join(blk.lines)
        if FOREIGN_BLOCK.search(text):
            return True
        names = {n.lower() for n in self.project.names}
        for m in re.finditer(r"git\s+clone\s+(?:--?[\w-]+(?:[= ]\S+)?\s+)*(\S+)", text):
            base = m.group(1).rstrip("/").split("/")[-1]
            base = base[:-4] if base.endswith(".git") else base
            if base.lower() not in names:
                return True
        for m in re.finditer(r"(?:^|&&|;)\s*\$?\s*cd\s+(\S+)", text, re.M):
            target = m.group(1).strip("\"'").rstrip("/")
            if target in ("..", "-", "~", ".", "") or target.startswith(("$", "<", "{")):
                continue
            first = target.lstrip("./").split("/")[0]
            if first.lower() in names or self.repo.has_dir(first):
                continue
            doc_dir = posixpath.dirname(doc.path)
            if doc_dir and self.repo.has_dir(posixpath.normpath(posixpath.join(doc_dir, target))):
                continue
            return True
        return False


# ------------------------------------------------------------------ own command
def own_command(ctx: Context, doc: Doc, tokens: List[str]) -> Optional[Tuple[str, List[str]]]:
    """(command label, remaining tokens) when the line runs this project's CLI."""
    toks = list(tokens)
    changed = True
    while changed and toks:
        changed = False
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
            toks = toks[1:]
            changed = True
        for pre in WRAPPER_PREFIXES:
            if toks[: len(pre)] == pre and len(toks) > len(pre):
                toks = toks[len(pre):]
                while toks and toks[0].startswith("-") and toks[0] != "-m":
                    toks = toks[1:]
                changed = True
                break
    if not toks:
        return None
    t0 = toks[0].strip("\"'")
    rest = toks[1:]
    project = ctx.project
    repo = ctx.repo
    doc_dir = posixpath.dirname(doc.path)

    def repo_file(p: str) -> Optional[str]:
        p = p.strip("\"'")
        if not p or p.startswith(("/", "~", "$")) or "*" in p:
            return None
        for base in ("", doc_dir):
            cand = posixpath.normpath(posixpath.join(base, p))
            if not cand.startswith("..") and repo.has_file(cand):
                return cand
        return None

    if re.match(r"^(python|python3|py)(\d[\d.]*)?(\.exe)?$", t0):
        while rest and rest[0].startswith("-") and rest[0] not in ("-m",):
            rest = rest[1:]
        if len(rest) >= 2 and rest[0] == "-m":
            mod = rest[1]
            if mod.split(".")[0] in project.python_packages:
                return ("python -m " + mod, rest[2:])
            return None
        if rest and rest[0].endswith(".py") and repo_file(rest[0]):
            return ("python " + rest[0], rest[1:])
        return None
    if t0 in ("node", "bash", "sh", "zsh", "deno", "bun", "ruby", "php", "tsx", "ts-node") and rest:
        if t0 in ("deno", "bun") and rest[0] == "run":
            rest = rest[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if rest and re.search(r"\.\w{1,4}$", rest[0]) and repo_file(rest[0]):
            return (t0 + " " + rest[0], rest[1:])
        return None
    if t0 == "cargo" and rest[:1] == ["run"] and "--" in rest:
        return ("cargo run --", rest[rest.index("--") + 1:])
    if t0 == "go" and rest[:1] == ["run"] and len(rest) >= 2 and rest[1].startswith("."):
        return ("go run " + rest[1], rest[2:])
    if t0.startswith("./") or t0.startswith("../") or (("/" in t0) and not t0.startswith(("/", "~"))):
        hit = repo_file(t0)
        if hit:
            return (t0, rest)
        base = t0.rsplit("/", 1)[-1]
        if base in project.commands:
            return (base, rest)
        return None
    name = t0[:-4] if t0.endswith(".exe") else t0
    if name in project.commands:
        return (name, rest)
    return None


def _flags_in(tokens: List[str]) -> List[str]:
    out: List[str] = []
    for i, tok in enumerate(tokens):
        if tok == "--":
            break
        bare = tok.strip("[](),").rstrip(".")
        if not bare.startswith("--"):
            if not bare.startswith("-") and bare.lower() in PASSTHROUGH_WORDS:
                break
            continue
        name = bare[2:].split("=", 1)[0]
        if not re.match(r"^[a-zA-Z][\w-]*$", name):
            continue
        if any(c in tok for c in "<>{}|…") and "=" not in tok:
            continue
        out.append(name)
    return out


def _closest_flag(ctx: Context, key: str) -> Optional[Fact]:
    cands = [k for k, v in ctx.flag_facts.items() if any(not is_support_path(f.file) for f in v)]
    hit = difflib.get_close_matches(key, cands, n=1, cutoff=0.5)
    if not hit:
        return None
    facts = [f for f in ctx.flag_facts[hit[0]] if not is_support_path(f.file)]
    return facts[0] if facts else None


def check_cli_flags(ctx: Context) -> List[Finding]:
    """cli-flag-undefined: flags used in docs with this project's own command."""
    claims: Dict[Tuple[str, str], Dict[str, Any]] = {}   # (doc, key) -> info
    per_command: Dict[str, Set[str]] = {}
    for doc in ctx.docs:
        for cmd in ctx.commands(doc):
            own = own_command(ctx, doc, cmd.tokens)
            if not own:
                continue
            label, rest = own
            if doc.stale_context(cmd.line):
                ctx.skip("stale-context")
                continue
            for name in _flags_in(rest):
                key = norm_flag(name)
                if key in IGNORED_FLAGS:
                    continue
                per_command.setdefault(label.split(" ")[0] + ":" + label, set()).add(key)
                info = claims.setdefault((doc.path, key), {"lines": [], "label": label, "raw": name, "src": "command"})
                if cmd.line not in info["lines"]:
                    info["lines"].append(cmd.line)
        # option lists and tables
        mentions: Dict[str, List[int]] = {}
        for sp in doc.spans:
            m = OPTION_SPAN.match(sp.text)
            if not m or not LIST_OR_TABLE_LINE.match(doc.line_text(sp.line)):
                continue
            if doc.stale_context(sp.line):
                continue
            mentions.setdefault(norm_flag(m.group(1)), []).append(sp.line)
        mentions = {k: v for k, v in mentions.items() if k not in IGNORED_FLAGS}
        if mentions:
            known = [k for k in mentions if _flag_strict(ctx, k)]
            if len(known) >= 3 and len(known) >= 0.7 * len(mentions):
                for key, lines in mentions.items():
                    if key in known:
                        continue
                    info = claims.setdefault((doc.path, key), {"lines": [], "label": "", "raw": key, "src": "option-list"})
                    for ln in lines:
                        if ln not in info["lines"]:
                            info["lines"].append(ln)
            else:
                ctx.skip("option-list-not-ours", len([k for k in mentions if k not in known]))
    if not claims:
        return []
    all_keys = {k for (_, k) in claims}
    strict = {k for k in all_keys if _flag_strict(ctx, k)}
    unresolved = sorted(all_keys - strict)
    loose_known = ctx.loose(unresolved) if unresolved else set()
    structured = {k for k, v in ctx.flag_facts.items() if any(not is_support_path(f.file) for f in v)}
    literal_convention = len(strict) >= 5 and len(strict) >= 0.8 * len(all_keys)
    findings: List[Finding] = []
    for (doc_path, key), info in sorted(claims.items()):
        if key in strict:
            continue
        doc = ctx._by_path[doc_path]
        if info["src"] == "command":
            group = None
            for g, keys in per_command.items():
                if g.endswith(":" + info["label"]) and key in keys:
                    group = keys
                    break
            group = group or {key}
            known_n = len([k for k in group if k in strict or k in loose_known])
            if not (len(structured) >= 3 or (known_n >= 2 and known_n >= 0.5 * len(group))):
                ctx.skip("cli-not-understood")
                continue
        if key in loose_known:
            if not literal_convention:
                ctx.skip("flag-has-loose-trace")
                continue
            confidence = "medium"
        else:
            confidence = "high"
        line = min(info["lines"])
        near = _closest_flag(ctx, key)
        why = [
            f"no literal --{key} (or --{key.replace('-', '_')}) in any non-doc file",
            "no identifier or string for it either" if confidence == "high" else
            "a similarly named identifier exists, but this project defines its flags as literal strings",
        ]
        if info["src"] == "command":
            why.append(f"the doc line runs this project's own command `{info['label']}`")
            msg = f"`--{info['raw']}` is used with `{info['label']}` in the docs, but the code does not define that flag."
        else:
            why.append("it sits in an option list where at least 70% of the other flags are defined in the code")
            msg = f"`--{info['raw']}` is documented as an option, but the code does not define that flag."
        f = Finding(
            check="cli-flag-undefined", name="--" + key, doc_file=doc_path, doc_line=line,
            doc_quote=_clip(doc.line_text(line)), message=msg, confidence=confidence,
            doc_lines=sorted(info["lines"]), why=why,
        )
        if near:
            f.code_file, f.code_line = near.file, near.line
            f.code_quote = ctx.code_line(near.file, near.line)
            f.suggestion = f"Closest flag defined in code: `{near.name}` ({near.file}:{near.line}). If it was renamed, update the docs to `{near.name}`; otherwise remove the flag from the docs."
        else:
            f.suggestion = "Remove the flag from the docs, or restore it in the code."
        findings.append(f.finish())
    return findings


def _flag_strict(ctx: Context, key: str) -> bool:
    if key in ctx.flag_literals or key in ctx.flag_facts:
        return True
    if key.startswith("no-") and (key[3:] in ctx.flag_literals or key[3:] in ctx.flag_facts):
        return True
    return False


def check_flags_undocumented(ctx: Context) -> List[Finding]:
    flag_mentions, _ = ctx.doc_mentions()
    by_file: Dict[str, Dict[str, Fact]] = {}
    for key, facts in ctx.flag_facts.items():
        for f in facts:
            if is_support_path(f.file):
                continue
            by_file.setdefault(f.file, {}).setdefault(key, f)
    findings: List[Finding] = []
    for file, flags in sorted(by_file.items()):
        def mentioned(k: str) -> bool:
            # `--no-color` documents `--color` and the other way round
            other = k[3:] if k.startswith("no-") else "no-" + k
            return k in flag_mentions or other in flag_mentions

        documented = [k for k in flags if mentioned(k)]
        if len(documented) < 3 or len(documented) < 0.6 * len(flags):
            continue
        # where the siblings are documented
        best_doc, best_line, best_n = None, 0, 0
        for doc in ctx.docs:
            where = ctx.flag_lines(doc)
            hits = [where[k] for k in documented if k in where]
            if len(hits) > best_n:
                best_doc, best_line, best_n = doc, max(hits), len(hits)
        if best_doc is None or best_n < 3 or best_n < 0.6 * len(flags):
            # the flags are not listed in one place we can point at (often a generated reference)
            if len(documented) < len(flags):
                ctx.skip("flag-siblings-not-listed-in-one-doc")
            continue
        for key, fact in sorted(flags.items()):
            if mentioned(key) or key in IGNORED_FLAGS or HIDDEN_NAME.search(key):
                continue
            if getattr(fact, "hidden", False):
                continue
            f = Finding(
                check="cli-flag-undocumented", name="--" + key, doc_file=best_doc.path, doc_line=best_line,
                doc_quote=_clip(best_doc.line_text(best_line)),
                message=f"`{fact.name}` is defined in {fact.file} but no doc mentions it; {best_n} of the other {len(flags) - 1} flags from that file are documented in {best_doc.path}.",
                confidence="medium", code_file=fact.file, code_line=fact.line,
                code_quote=ctx.code_line(fact.file, fact.line),
                suggestion=f"Document `{fact.name}` next to its siblings in {best_doc.path} (around line {best_line}).",
                why=[f"{len(documented)} of {len(flags)} flags defined in {fact.file} appear in the docs", "this one appears in no doc file"],
            )
            findings.append(f.finish())
    return findings


# ------------------------------------------------------------------ env vars
EXTERNAL_URL = re.compile(r"https?://")


def _own_env_prefix(ctx: Context, name: str) -> Optional[str]:
    prefix = name.split("_")[0]
    joined = name.replace("_", "")
    for key in ctx.name_keys:
        if len(key) >= 3 and (prefix == key or name.startswith(key + "_")):
            return "the prefix matches the project name"
    if prefix in THIRD_PARTY_ENV_PREFIXES or len(prefix) < 2:
        return None
    siblings = {n for n in ctx.env_facts if n.split("_")[0] == prefix and n != name}
    if len(siblings) >= 2:
        return f"the code reads {len(siblings)} other variables starting with {prefix}_ (e.g. {sorted(siblings)[0]})"
    return None


def _doc_env_claims(doc: Doc) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for sp in doc.spans:
        for name in ENV_TOKEN.findall(sp.text):
            out.setdefault(name, []).append(sp.line)
    for blk in doc.blocks:
        for i, ln in enumerate(blk.lines):
            for name in ENV_TOKEN.findall(ln):
                out.setdefault(name, []).append(blk.start + i)
    return out


def check_env(ctx: Context) -> List[Finding]:
    findings: List[Finding] = []
    pending: List[Tuple[Doc, str, List[int], str]] = []
    for doc in ctx.docs:
        for name, lines in _doc_env_claims(doc).items():
            if len(name) < 5 or name in ctx.env_tokens:
                continue
            reason = _own_env_prefix(ctx, name)
            if not reason:
                continue
            if any(name.startswith(p) for p in ctx.dyn_prefixes):
                ctx.skip("env-built-dynamically")
                continue
            live = [ln for ln in lines if not doc.stale_context(ln)]
            if not live:
                ctx.skip("stale-context")
                continue
            if all(EXTERNAL_URL.search(doc.line_text(ln)) for ln in live):
                # "set FOO=1 (see https://other-project...)": most often another tool's variable
                ctx.skip("env-next-to-external-link")
                continue
            pending.append((doc, name, sorted(set(live)), reason))
    if not pending:
        return findings
    # A settings library may map MYAPP_DB_HOST to a field called db_host.
    remainders = {}
    for _, name, _, _ in pending:
        parts = name.split("_")
        for cut in (1, 2):
            if len(parts) > cut:
                rem = "-".join(parts[cut:]).lower()
                if len(rem) >= 4:
                    remainders.setdefault(name, []).append(rem)
    loose_hit = ctx.loose(sorted({r for v in remainders.values() for r in v})) if ctx.auto_env else set()
    for doc, name, lines, reason in pending:
        if ctx.auto_env and any(r in loose_hit for r in remainders.get(name, [])):
            ctx.skip("env-maybe-derived-from-settings-field")
            continue
        if ctx.auto_env and not remainders.get(name):
            ctx.skip("env-maybe-derived-from-settings-field")
            continue
        line = lines[0]
        f = Finding(
            check="env-undefined", name=name, doc_file=doc.path, doc_line=line,
            doc_quote=_clip(doc.line_text(line)),
            message=f"`{name}` is documented, but no non-doc file in the repository contains that name.",
            doc_lines=lines,
            why=[reason, f"`{name}` does not occur in any code, config or script file",
                 "no code builds variable names from that prefix dynamically"],
        )
        close = difflib.get_close_matches(name, list(ctx.env_facts), n=1, cutoff=0.72)
        if close:
            fact = ctx.env_facts[close[0]][0]
            f.code_file, f.code_line = fact.file, fact.line
            f.code_quote = ctx.code_line(fact.file, fact.line)
            f.suggestion = f"Closest variable read by the code: `{close[0]}` ({fact.file}:{fact.line}). If it was renamed, update the docs; otherwise remove `{name}` from the docs."
        else:
            f.suggestion = f"Remove `{name}` from the docs, or read it in the code."
        findings.append(f.finish())
    return findings


def check_env_undocumented(ctx: Context) -> List[Finding]:
    _, env_mentions = ctx.doc_mentions()
    product: Dict[str, Fact] = {}
    for name, facts in ctx.env_facts.items():
        for f in facts:
            if not is_support_path(f.file):
                product.setdefault(name, f)
    groups: Dict[str, List[str]] = {}
    for name in product:
        groups.setdefault(name.split("_")[0], []).append(name)
    findings: List[Finding] = []
    for prefix, names in sorted(groups.items()):
        own = any(len(k) >= 3 and prefix == k for k in ctx.name_keys)
        if prefix in THIRD_PARTY_ENV_PREFIXES and not own:
            continue
        documented = [n for n in names if n in env_mentions]
        missing = [n for n in names if n not in env_mentions and not HIDDEN_NAME.search(n)]
        if not missing or len(documented) < 3 or len(documented) < 0.6 * len(names):
            continue
        best_doc, best_line, best_n = None, 0, 0
        for doc in ctx.docs:
            where = ctx.env_lines(doc)
            hits = [where[d] for d in documented if d in where]
            if len(hits) > best_n:
                best_doc, best_line, best_n = doc, max(hits), len(hits)
        if best_doc is None or best_n < 3:
            continue
        for name in sorted(missing):
            fact = product[name]
            f = Finding(
                check="env-undocumented", name=name, doc_file=best_doc.path, doc_line=best_line,
                doc_quote=_clip(best_doc.line_text(best_line)),
                message=f"The code reads `{name}` ({fact.file}:{fact.line}) but no doc mentions it; {best_n} other {prefix}_ variables are documented in {best_doc.path}.",
                confidence="medium", code_file=fact.file, code_line=fact.line,
                code_quote=ctx.code_line(fact.file, fact.line),
                suggestion=f"Document `{name}` next to the other {prefix}_ variables in {best_doc.path} (around line {best_line}).",
                why=[f"{len(documented)} of {len(names)} {prefix}_ variables read by the code appear in the docs", "this one appears in no doc file"],
            )
            findings.append(f.finish())
    return findings


# ------------------------------------------------------------------ defaults
def _norm_value(v: Any) -> Tuple[str, Any]:
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    low = s.lower()
    if low in ("true", "false"):
        return ("bool", low == "true")
    if re.match(r"^-?\d+(\.\d+)?$", s):
        return ("num", float(s))
    return ("str", s)


def _doc_default(doc: Doc, line: int, name_span: str) -> Optional[str]:
    text = doc.line_text(line)
    header = table_header_for(doc, line)
    if header:
        cols = table_columns(text)
        for i, h in enumerate(header):
            if re.match(r"^defaults?( value)?$", h.strip("* _`")) and i < len(cols):
                cell = cols[i].strip()
                if cell.count("`") == 2 and cell.startswith("`") and cell.endswith("`"):
                    return cell
                if re.match(r"^(\"[^\"]*\"|'[^']*'|-?\d+(\.\d+)?|true|false|[\w./:-]+)$", cell, re.I):
                    return cell
                return None
        return None
    m = DEFAULT_RX.search(text)
    if not m:
        return None
    if len(list(DEFAULT_RX.finditer(text))) > 1:
        return None
    val = m.group(1)
    if val.strip("`") == name_span:
        return None
    return val


def check_defaults(ctx: Context) -> List[Finding]:
    findings: List[Finding] = []
    for doc in ctx.docs:
        by_line: Dict[int, List[str]] = {}
        for sp in doc.spans:
            by_line.setdefault(sp.line, []).append(sp.text)
        for line, spans in sorted(by_line.items()):
            names: Dict[Tuple[str, str], str] = {}
            for s in spans:
                if ENV_TOKEN.fullmatch(s):
                    names[("env", s)] = s
                else:
                    m = OPTION_SPAN.match(s)
                    if m:
                        names[("flag", norm_flag(m.group(1)))] = s
            if len(names) != 1:
                continue
            (kind, key), span_text = next(iter(names.items()))
            facts = (ctx.env_facts if kind == "env" else ctx.flag_facts).get(key, [])
            facts = [f for f in facts if not is_support_path(f.file)] or []
            if not facts or not all(f.has_default for f in facts):
                continue
            raw = _doc_default(doc, line, span_text)
            if raw is None or doc.stale_context(line):
                continue
            code_vals = {_norm_value(f.default) for f in facts}
            if len(code_vals) != 1:
                ctx.skip("default-defined-in-several-places")
                continue
            ckind, cval = next(iter(code_vals))
            dkind, dval = _norm_value(raw)
            if ckind == "str" and (cval == "" or any(c in cval for c in "{$%<")):
                continue
            if dkind == "str" and (not dval or " " in dval or dval.lower() in ("none", "null", "nil", "unset", "-", "n/a", "empty", "auto")):
                continue
            if dkind == "str" and ckind == "num" and re.match(r"^-?\d+(\.\d+)?\s*[a-zA-Z%]+$", dval):
                ctx.skip("default-has-unit")
                continue
            if kind == "env" and ckind == "str" and dkind in ("num", "bool"):
                dkind, dval = "str", raw.strip("`\"' ")
                if isinstance(cval, str) and cval.lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                    if dval.lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                        truthy = {"true", "1", "yes", "on"}
                        if (cval.lower() in truthy) == (dval.lower() in truthy):
                            continue
            if dkind != ckind:
                ctx.skip("default-types-not-comparable")
                continue
            same = (abs(cval - dval) < 1e-9) if ckind == "num" else (cval == dval)
            if same:
                continue
            fact = facts[0]
            shown = fact.default
            label = key if kind == "env" else "--" + key
            f = Finding(
                check="default-mismatch", name=label, doc_file=doc.path, doc_line=line,
                doc_quote=_clip(doc.line_text(line)),
                message=f"Docs say the default of `{label}` is {raw.strip()}, the code says {shown!r}.",
                code_file=fact.file, code_line=fact.line, code_quote=ctx.code_line(fact.file, fact.line),
                suggestion=f"Change the documented default to {shown!r}, or change the code if the docs are right.",
                why=["the doc line names exactly one option and states one default",
                     f"the code defines one static default for it ({fact.file}:{fact.line})"],
            )
            findings.append(f.finish())
    return findings


# ------------------------------------------------------------------ npm / make
def _contributor_doc(path: str) -> bool:
    return "/" not in path or bool(CONTRIBUTOR_DOC.search(posixpath.basename(path)))


def _npm_script_of(tokens: List[str]) -> Optional[str]:
    if not tokens or tokens[0] not in ("npm", "yarn", "pnpm", "bun"):
        return None
    pm, rest = tokens[0], tokens[1:]
    if "--" in rest:
        rest = rest[: rest.index("--")]
    name = None
    if "run" in rest or "run-script" in rest:
        i = rest.index("run") if "run" in rest else rest.index("run-script")
        after = [t for t in rest[i + 1:] if not t.startswith("-")]
        before = rest[:i]
        if any(t in ("exec", "dlx", "x", "create", "init") for t in before):
            return None
        name = after[0] if after else None
    elif pm == "npm" and rest[:1] == ["test"]:
        name = "test"
    elif pm in ("yarn", "pnpm") and rest and ":" in rest[0] and not rest[0].startswith("-"):
        name = rest[0]
    if not name or not re.match(r"^[A-Za-z0-9][\w:.-]*$", name):
        return None
    return name


def check_npm_scripts(ctx: Context) -> List[Finding]:
    p = ctx.project
    if not p.has_package_json or not p.npm_scripts:
        return []
    findings: List[Finding] = []
    for doc in ctx.docs:
        refs: Dict[str, List[Command]] = {}
        for cmd in ctx.commands(doc):
            name = _npm_script_of(cmd.tokens)
            if name:
                refs.setdefault(name, []).append(cmd)
        if not refs:
            continue
        known = [n for n in refs if n in p.npm_scripts]
        doc_text = "\n".join(doc.lines)
        for name, cmds in sorted(refs.items()):
            if name in p.npm_scripts:
                continue
            if re.search(r"[\"']" + re.escape(name) + r"[\"']\s*:", doc_text):
                ctx.skip("script-defined-in-doc-snippet")
                continue
            live = [c for c in cmds if not doc.stale_context(c.line) and not ctx.foreign_block(doc, c)]
            if not live:
                ctx.skip("other-project-or-stale")
                continue
            if not (_contributor_doc(doc.path) or known):
                ctx.skip("script-doc-not-about-this-package")
                continue
            line = live[0].line
            close = difflib.get_close_matches(name, list(p.npm_scripts), n=1, cutoff=0.6)
            f = Finding(
                check="npm-script-missing", name=name, doc_file=doc.path, doc_line=line,
                doc_quote=_clip(doc.line_text(line)),
                message=f"Docs run the script `{name}`, but no package.json in the repository defines it.",
                doc_lines=sorted({c.line for c in live}),
                confidence="high" if (known or "/" not in doc.path) else "medium",
                why=[f"{len(p.npm_scripts)} scripts are defined across the repository's package.json files; `{name}` is not one of them",
                     "the doc does not define that script in a JSON snippet"],
            )
            if close:
                where = p.npm_scripts[close[0]]
                f.code_file = where
                f.suggestion = f"Closest script: `{close[0]}` ({where}). Update the docs or add the script."
            else:
                f.suggestion = "Update the docs or add the script to package.json."
            findings.append(f.finish())
    return findings


def check_make_targets(ctx: Context) -> List[Finding]:
    p = ctx.project
    if not p.has_makefile or not p.make_targets:
        return []
    if p.generated_makefile:
        ctx.notes.append("make-target-missing skipped: the build generates or wraps Makefiles (CMake/autotools/meson).")
        return []
    if p.make_dynamic:
        ctx.notes.append("make-target-missing skipped: a Makefile computes target names or includes generated files.")
        return []
    findings: List[Finding] = []
    for doc in ctx.docs:
        refs: Dict[str, List[Command]] = {}
        for cmd in ctx.commands(doc):
            t = cmd.tokens
            if not t or t[0] not in ("make", "gmake") or "-f" in t or "-C" in t or any(x.startswith(("-C", "--directory", "--file")) for x in t):
                continue
            skip_next = False
            for tok in t[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if tok in ("-j", "-l", "-o", "-W", "-I"):
                    skip_next = True
                    continue
                if tok.startswith("-") or "=" in tok or not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", tok):
                    continue
                refs.setdefault(tok, []).append(cmd)
        if not refs:
            continue

        def is_known(name: str) -> bool:
            if name in p.make_targets:
                return True
            return any(fnmatch.fnmatchcase(name, pat.replace("%", "*")) for pat in p.make_patterns)

        known = [n for n in refs if is_known(n)]
        for name, cmds in sorted(refs.items()):
            if is_known(name):
                continue
            live = [c for c in cmds if not doc.stale_context(c.line) and not ctx.foreign_block(doc, c)]
            if not live:
                ctx.skip("other-project-or-stale")
                continue
            if not known and not _contributor_doc(doc.path):
                ctx.skip("make-doc-not-about-this-project")
                continue
            if not known and len(refs) == 1 and name in ("install", "all", "clean", "check", "test", "build"):
                ctx.skip("generic-make-target-without-context")
                continue
            line = live[0].line
            close = difflib.get_close_matches(name, list(p.make_targets), n=1, cutoff=0.6)
            f = Finding(
                check="make-target-missing", name=name, doc_file=doc.path, doc_line=line,
                doc_quote=_clip(doc.line_text(line)),
                message=f"Docs run `make {name}`, but no Makefile in the repository defines that target.",
                doc_lines=sorted({c.line for c in live}),
                confidence="high" if known else "medium",
                why=[f"{len(p.make_targets)} targets are defined across the repository's Makefiles; `{name}` is not one of them and matches no pattern rule",
                     "no Makefile computes target names"],
            )
            if close:
                where = p.make_targets[close[0]]
                f.code_file, _, ln = where.rpartition(":")
                f.code_line = int(ln) if ln.isdigit() else 0
                f.code_quote = ctx.code_line(f.code_file, f.code_line)
                f.suggestion = f"Closest target: `{close[0]}` ({where}). Update the docs or add the target."
            else:
                f.suggestion = "Update the docs or add the target."
            findings.append(f.finish())
    return findings


# ------------------------------------------------------------------ paths
def _site_mode(ctx: Context, doc_path: str) -> bool:
    roots = ctx.project.site_roots
    if not roots:
        return False
    parts = doc_path.split("/")
    if len(parts) > 1 and parts[0].lower() in SITE_DIR_NAMES:
        return True
    for r in roots:
        if r and doc_path.startswith(r + "/"):
            return True
    return False


def check_paths(ctx: Context) -> List[Finding]:
    repo = ctx.repo
    submodules = repo.submodule_paths()
    basenames: Dict[str, List[str]] = {}
    for f in repo.files:
        basenames.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    findings: List[Finding] = []
    ignore_calls = 0
    for doc in ctx.docs:
        site = _site_mode(ctx, doc.path)
        doc_dir = posixpath.dirname(doc.path)
        seen: Dict[str, Finding] = {}
        for link in doc.links:
            t = link.target.strip()
            if (not t or t.startswith(("#", "/", "?", "\\")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t)
                    or any(c in t for c in "{}<>$*|\"'`") or "%7B" in t or " " in t):
                continue
            t = unquote(t.split("#", 1)[0].split("?", 1)[0])
            if not t or t in (".", "..") or t.startswith("@"):
                continue
            target = posixpath.normpath(posixpath.join(doc_dir, t))
            if target.startswith("..") or target == ".":
                continue
            if repo.exists(target):
                continue
            base = target.rsplit("/", 1)[-1]
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            if ext in ("html", "htm"):
                ctx.skip("link-to-generated-html")
                continue
            if not ext:
                alts = [target + s for s in (".md", ".mdx", "/index.md", "/index.mdx", "/README.md", "/_index.md", ".rst", ".ipynb", ".markdown")]
                if any(repo.exists(a) for a in alts):
                    continue
                if site:
                    ctx.skip("site-route-link")
                    continue
            if any(target == s or target.startswith(s + "/") for s in submodules):
                ctx.skip("link-into-submodule")
                continue
            segs = target.split("/")
            if any(repo.has_file("/".join(segs[:i])) for i in range(1, len(segs))):
                ctx.skip("link-through-symlink")
                continue
            if doc.stale_context(link.line) and link.kind != "html":
                # links in changelog-like sections are still links; only skip explicit history lines
                pass
            variant = repo.case_variant(target)
            if not variant:
                if repo.on_disk(target):
                    ctx.skip("link-to-untracked-or-ignored-file")
                    continue
                if site and base in basenames:
                    ctx.skip("site-resolved-link")
                    continue
                if site:
                    alt = posixpath.normpath(posixpath.join(doc.path.rsplit(".", 1)[0], t))
                    if repo.exists(alt):
                        continue
                if ignore_calls < 40:
                    ignore_calls += 1
                    if repo.ignored(target):
                        ctx.skip("link-to-untracked-or-ignored-file")
                        continue
            if target in seen:
                if link.line not in seen[target].doc_lines:
                    seen[target].doc_lines.append(link.line)
                continue
            if variant:
                msg = f"Link target `{t}` does not exist with that letter case; the repository has `{variant}`."
                sug = f"Change the link to match `{variant}` (links are case-sensitive on GitHub and Linux)."
                code_file = variant
            else:
                msg = f"Link target `{t}` resolves to `{target}`, which is not in the repository."
                moved = basenames.get(base, [])
                if len(moved) == 1:
                    sug = f"A file with the same name exists at `{moved[0]}`; if it moved, update the link."
                    code_file = moved[0]
                else:
                    sug = "Fix or remove the link."
                    code_file = ""
            f = Finding(
                check="path-missing", name=target, doc_file=doc.path, doc_line=link.line,
                doc_quote=_clip(doc.line_text(link.line)), message=msg, suggestion=sug,
                code_file=code_file, doc_lines=[link.line],
                why=["the link is relative and stays inside the repository",
                     "the target is neither tracked, untracked-on-disk, git-ignored nor inside a submodule"],
            )
            seen[target] = f
        findings.extend(f.finish() for f in seen.values())
    return findings


def check_path_refs(ctx: Context) -> List[Finding]:
    repo = ctx.repo
    basenames: Dict[str, List[str]] = {}
    for f in repo.files:
        basenames.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    top_dirs = {f.split("/", 1)[0] for f in repo.files if "/" in f}
    findings: List[Finding] = []
    for doc in ctx.docs:
        doc_dir = posixpath.dirname(doc.path)
        seen: Dict[str, Finding] = {}
        for sp in doc.spans:
            t = sp.text
            if not PATH_REF.match(t) or t.startswith(("http", "www.")):
                continue
            base = t.rsplit("/", 1)[-1]
            if "." not in base or base.rsplit(".", 1)[-1].lower() not in PATH_REF_EXT:
                continue
            rel = t[2:] if t.startswith("./") else t.lstrip("/")
            segs = rel.split("/")
            if segs[0] not in top_dirs or segs[0].lower() in GENERATED_FIRST_SEG:
                continue
            if PLACEHOLDER_WORDS.search(rel):
                continue
            cands = [posixpath.normpath(rel)]
            if doc_dir:
                cands.append(posixpath.normpath(posixpath.join(doc_dir, rel)))
            if any(repo.exists(c) or repo.case_variant(c) for c in cands):
                continue
            parent = posixpath.dirname(cands[0])
            if not repo.has_dir(parent):
                ctx.skip("path-ref-parent-dir-missing")
                continue
            if repo.on_disk(cands[0]) or doc.stale_context(sp.line):
                ctx.skip("path-ref-generated-or-stale")
                continue
            # Only keep it when the sentence is about the repository, not the reader's project.
            line_text = doc.line_text(sp.line).lower()
            if re.search(r"\b(create|add|new|generate[sd]?|will|your|you can|write|save|output|e\.g\.|such as|like)\b", line_text):
                ctx.skip("path-ref-about-readers-project")
                continue
            if rel in seen:
                seen[rel].doc_lines.append(sp.line)
                continue
            moved = [m for m in basenames.get(base, [])]
            f = Finding(
                check="path-ref-missing", name=rel, doc_file=doc.path, doc_line=sp.line,
                doc_quote=_clip(doc.line_text(sp.line)), confidence="medium",
                message=f"Docs refer to `{t}`; the directory `{parent}/` exists but that file does not.",
                doc_lines=[sp.line],
                why=[f"`{segs[0]}/` is a top-level directory of the repository and `{parent}/` exists",
                     "the file is not tracked, not on disk and the sentence does not ask the reader to create it"],
            )
            if len(moved) == 1:
                f.code_file = moved[0]
                f.suggestion = f"A file named `{base}` exists at `{moved[0]}`; if it moved, update the reference."
            else:
                f.suggestion = "Update or remove the reference."
            seen[rel] = f
        findings.extend(f.finish() for f in seen.values())
    return findings


ALL_CHECKS: Dict[str, Callable[[Context], List[Finding]]] = {
    "path-missing": check_paths,
    "path-ref-missing": check_path_refs,
    "cli-flag-undefined": check_cli_flags,
    "cli-flag-undocumented": check_flags_undocumented,
    "env-undefined": check_env,
    "env-undocumented": check_env_undocumented,
    "default-mismatch": check_defaults,
    "npm-script-missing": check_npm_scripts,
    "make-target-missing": check_make_targets,
}

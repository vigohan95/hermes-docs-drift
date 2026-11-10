"""Injected drift: change the code in memory, leave the docs alone, see if the scanner notices.

    python benchmarks/inject.py <targets_dir> <out_dir> owner__name [owner__name ...]

This measures recall for the situation the Hermes hook is built for: an edit to
code that the docs describe. Nothing is written to the target repository; the
changed file contents are passed to the scanner as an overlay.

Candidates are chosen without asking the scanner whether it would report them:

* flag:   a flag defined in non-test code (argparse / click / typer / cobra /
          clap / commander / yargs extractors) whose literal ``--name`` occurs
          in a checked doc.
* env:    a variable read in non-test code whose name occurs in a checked doc.
* npm:    a root package.json script that a checked doc runs (npm/yarn/pnpm).
* make:   a Makefile target that a checked doc runs (``make <target>``).
* path:   a tracked file that a checked doc links to with a relative link.

Mutations:

* flag "literal":  ``--name`` -> ``--zq-renamed`` in every non-doc file.
* flag "refactor": the same, plus the identifier spellings (``the_name``,
  ``theName``) renamed as whole identifiers in every non-doc file, as a
  rename refactoring would do.
* env:   ``NAME`` -> ``NAME_ZQ`` as a whole token in every non-doc file.
* npm:   the script key renamed in package.json.
* make:  the target renamed in the Makefile that defines it.
* path:  the linked file removed.

"Detected" means the scan of the mutated tree has a finding of the matching
check with that name, and the scan of the original tree did not. Up to
``PER_KIND`` candidates per kind and repository, picked with a fixed seed.
"""

from __future__ import annotations

import json
import os
import posixpath
import random
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsdrift.facts import is_support_path, norm_flag  # noqa: E402
from docsdrift.scan import Scanner  # noqa: E402

PER_KIND = 12
SEED = 20261110


def _doc_texts(scanner: Scanner) -> Dict[str, str]:
    out = {}
    for rel in scanner.repo.doc_files():
        text = scanner.repo.read(rel)
        if text:
            out[rel] = text
    return out


def _replace_everywhere(scanner: Scanner, code_files: List[str], subs: List[Tuple[re.Pattern, str]],
                        needles: List[str]) -> Dict[str, Optional[str]]:
    overlay: Dict[str, Optional[str]] = {}
    for rel in code_files:
        text = scanner.repo.read(rel)
        if not text or not any(n in text for n in needles):
            continue
        new = text
        for rx, rep in subs:
            new = rx.sub(rep, new)
        if new != text:
            overlay[rel] = new
    return overlay


def _camel(parts: List[str]) -> str:
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def candidates(scanner: Scanner) -> Dict[str, list]:
    repo = scanner.repo
    docs = _doc_texts(scanner)
    all_docs = "\n".join(docs.values())
    project = scanner._project[1] if scanner._project else None
    flags: Dict[str, str] = {}
    envs: Dict[str, str] = {}
    for rel, (_, ff) in scanner._facts.items():
        if is_support_path(rel):
            continue
        for f in ff.facts:
            if f.hidden:
                continue
            if f.kind == "flag" and f.name.startswith("--") and len(f.name) > 4:
                if re.search(r"(?<![\w-])" + re.escape(f.name) + r"(?![\w-])", all_docs):
                    flags.setdefault(f.name, f"{f.file}:{f.line}")
            elif f.kind == "env":
                if re.search(r"(?<![A-Za-z0-9_])" + re.escape(f.name) + r"(?![A-Za-z0-9_])", all_docs):
                    envs.setdefault(f.name, f"{f.file}:{f.line}")
    npm: Dict[str, str] = {}
    make: Dict[str, str] = {}
    if project:
        for name, where in project.npm_scripts.items():
            if where != "package.json":
                continue
            if re.search(r"(?:npm run|pnpm run|pnpm|yarn run|yarn|bun run)\s+" + re.escape(name) + r"(?![\w:.-])", all_docs):
                npm[name] = where
        for name, where in project.make_targets.items():
            if re.search(r"(?<![\w-])make\s+" + re.escape(name) + r"(?![\w.-])", all_docs):
                make[name] = where
    paths: Dict[str, str] = {}
    link = re.compile(r"\]\(([^)\s]+)\)")
    for rel, text in docs.items():
        for m in link.finditer(text):
            t = m.group(1)
            if t.startswith(("#", "/", "http:", "https:", "mailto:")) or ":" in t.split("/")[0]:
                continue
            t = unquote(t.split("#", 1)[0].split("?", 1)[0])
            if not t:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), t))
            if repo.has_file(target):
                paths.setdefault(target, rel)
    return {"flag": sorted(flags.items()), "env": sorted(envs.items()), "npm": sorted(npm.items()),
            "make": sorted(make.items()), "path": sorted(paths.items())}


def mutate(scanner: Scanner, kind: str, name: str, where: str, variant: str = "") -> Dict[str, Optional[str]]:
    repo = scanner.repo
    code_files = repo.code_files()
    if kind == "flag":
        bare = name.lstrip("-")
        subs = [(re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])"), "--zq-renamed")]
        needles = [name]
        if variant == "refactor":
            parts = [p for p in re.split(r"[-_]", bare) if p]
            snake, camel = "_".join(parts), _camel(parts)
            for ident, rep in ((snake, "zq_renamed"), (camel, "zqRenamed")):
                subs.append((re.compile(r"(?<![A-Za-z0-9_])" + re.escape(ident) + r"(?![A-Za-z0-9_])"), rep))
                needles.append(ident)
            if len(parts) > 1:
                subs.append((re.compile(r"(?<![\w-])" + re.escape("-".join(parts)) + r"(?![\w-])"), "zq-renamed"))
                needles.append("-".join(parts))
        return _replace_everywhere(scanner, code_files, subs, needles)
    if kind == "env":
        rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
        return _replace_everywhere(scanner, code_files, [(rx, name + "_ZQ")], [name])
    if kind == "npm":
        text = repo.read("package.json") or ""
        new = re.sub(r'"' + re.escape(name) + r'"(\s*:)', '"' + name + '-zq"\\1', text, count=1)
        return {"package.json": new} if new != text else {}
    if kind == "make":
        mk = where.rsplit(":", 1)[0]
        text = repo.read(mk) or ""
        new = re.sub(r"(?m)^" + re.escape(name) + r"(\s*:)", name + "-zq\\1", text)
        new = re.sub(r"(?m)^(\.PHONY\s*:.*?)(?<![\w-])" + re.escape(name) + r"(?![\w-])", "\\1" + name + "-zq", new)
        return {mk: new} if new != text else {}
    if kind == "path":
        return {name: None}
    return {}


EXPECT = {"flag": "cli-flag-undefined", "env": "env-undefined", "npm": "npm-script-missing",
          "make": "make-target-missing", "path": "path-missing"}


def run_repo(root: str) -> dict:
    scanner = Scanner(root)
    base = scanner.scan()
    base_ids = base.ids()
    cands = candidates(scanner)
    rng = random.Random(SEED)
    rows = []
    for kind, items in cands.items():
        picked = items if len(items) <= PER_KIND else sorted(rng.sample(items, PER_KIND))
        for name, where in picked:
            variants = ("literal", "refactor") if kind == "flag" else ("",)
            for variant in variants:
                overlay = mutate(scanner, kind, name, where, variant)
                row = {"kind": kind + ("/" + variant if variant else ""), "name": name, "where": where,
                       "files_changed": len(overlay)}
                if not overlay:
                    row["detected"] = None
                    row["note"] = "mutation changed nothing"
                    rows.append(row)
                    continue
                t0 = time.monotonic()
                res = scanner.scan(overlay=overlay, refresh=False)
                row["scan_s"] = round(time.monotonic() - t0, 2)
                new = [f for f in res.findings if f.id not in base_ids]
                want = norm_flag(name) if kind == "flag" else name
                hit = [f for f in new if f.check == EXPECT[kind]
                       and ((norm_flag(f.name) if kind == "flag" else f.name) == want)]
                row["detected"] = bool(hit)
                row["new_findings"] = len(new)
                row["other_new_findings"] = [f"{f.check} {f.name} {f.doc_file}:{f.doc_line}" for f in new if f not in hit][:10]
                if hit:
                    row["finding"] = f"{hit[0].doc_file}:{hit[0].doc_line} [{hit[0].confidence}]"
                rows.append(row)
    return {"candidates_available": {k: len(v) for k, v in cands.items()}, "baseline_findings": len(base.findings), "rows": rows}


def main() -> int:
    targets, out_dir, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        root = os.path.join(targets, name)
        sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        data = run_repo(root)
        data.update(repo=name.replace("__", "/", 1), sha=sha, per_kind_limit=PER_KIND, seed=SEED)
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        tally: Dict[str, List[int]] = {}
        for r in data["rows"]:
            if r["detected"] is None:
                continue
            t = tally.setdefault(r["kind"], [0, 0])
            t[1] += 1
            t[0] += 1 if r["detected"] else 0
        print(name, data["candidates_available"], {k: f"{a}/{b}" for k, (a, b) in tally.items()}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

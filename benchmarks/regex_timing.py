"""Time every regular expression in docsdrift/ on long repetitive strings.

    python benchmarks/regex_timing.py [N] [LANES] > evidence/regex-timing.txt

Python cannot interrupt a regular-expression search, so a pattern that needs quadratic time
on one crafted line can hold a hook long past its time limit. This script looks for such
patterns. It is a test over chosen inputs, not a proof.

The patterns are taken from the source with ``ast``: the first argument of every call of
``re.compile``, ``search``, ``match``, ``fullmatch``, ``findall``, ``finditer``, ``sub``,
``subn`` and ``split``. A part of a pattern that is only known at run time (an escaped flag
name in an f-string, for instance) is replaced by the word ``name``.

Each pattern is run with ``finditer``, which tries a match at every position, over
``prefix + unit * k + suffix`` cut to N characters (default 32,000), for every unit, prefix
and suffix below plus the words of the pattern itself. A linear pattern needs a few
milliseconds for such a string. A string that takes THRESH seconds or more is reported
together with the time at twice the length; a search still running after LIMIT seconds is
killed with its process.

A pattern whose input is cut to a fixed length by the code around it is timed at that
length (CAPS).

The numbers depend on the machine and on what else it is doing, so a run on a busy machine
can report a string that a quiet one does not.
"""

from __future__ import annotations

import ast
import multiprocessing as mp
import os
import re
import sys
import tempfile
import time

THRESH = 0.05
LIMIT = 4.0

UNITS = [
    " ", "\t", "a", "A", "_", "-", "--", "`", "``", "` ", "`a", "#", "# ", "*", "~", ".", "/", "\\", "|", "| ",
    "<", ">", "<a ", "<a x ", "<img ", "=", " = ", ":", ": ", "'", '"', "(", ")", "[", "]", "{", "}", "$", "${", "$(", "%",
    "](", "[a](", "[a]: ", "](<", "](a", "](a (", '](a "', "](a(", "!", "@", ",", ";", "&", "&&", "0", "1.", "a.", "a/",
    "./", "../", "a.b", "a-", "-a", "--a ", "--a-", "--a=", "-a, --b ", "[--a] ", "A_", "_A", "A_B", "A_B ", "A_B=",
    "$A", "${A", "%A%", "x ", " x", "\\\n", "\n", " \n", "a\n", "\n\t", "\r\n", "\n[", "\n[a]\n", "a = 1\n", "a=", "a =",
    '"a"', "'a'", '"a",', "'a', ", '"a": ', "(a", "a(", "a)", "[a", "a]", "a,", ", ", "a ", "ab", "aB", "a1", "1a",
    "é", " ", "*** ", "->", " -> ", "File:", "\n*** Update File:", "\n*** Move File: a ->",
    "name", "name ", "'name'", '"name"', "name=", "--name ", "-name", "name:", "name.", "name/", "name\n",
    "git clone ", "git clone --a ", "git clone -a b ", "cd ", "&& cd ", "; cd ", "path = ", "\npath = a", "url = ",
    "\nurl = a/", "default", "default ", "default: ", "console_scripts", "module ", "include ", "http://", "a@b ",
]
PREFIXES = ["", "x ", "# ", "<a ", "name "]
SUFFIXES = ["", "x", "\n"]

# (a piece of the pattern, the longest input the code gives it)
CAPS = (
    # facts.py: the entries of a console_scripts block, which the enclosing pattern cuts at 2,000 characters
    (r"\s*([A-Za-z][\w.-]*)\s*=\s*[\w.]+:[\w.]+", 2000),
)

FUNCS = {"compile": 1, "search": 2, "match": 2, "fullmatch": 2, "findall": 2, "finditer": 2, "sub": 4, "subn": 4, "split": 3}


def text_of(node: ast.AST) -> str:
    """The string an expression builds. What is only known at run time counts as the word "name"."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(text_of(v.value) if isinstance(v, ast.FormattedValue) else text_of(v) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return text_of(node.left) + text_of(node.right)
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "re.escape" and node.args:
        return re.escape(text_of(node.args[0]))
    if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
        return "name"
    raise ValueError(ast.unparse(node))


def flags_of(node: ast.AST | None) -> int:
    if node is None:
        return 0
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return flags_of(node.left) | flags_of(node.right)
    if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "re":
        return int(getattr(re, node.attr))
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    raise ValueError(ast.unparse(node))


def patterns(package: str) -> list:
    """(file:line, function, pattern or None, flags, why not) for every regular-expression call."""
    out = []
    for fn in sorted(os.listdir(package)):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(package, fn), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                    and node.func.attr in FUNCS and node.args):
                continue
            where = f"{fn}:{node.lineno}"
            at = FUNCS[node.func.attr]
            flag_node = node.args[at] if len(node.args) > at else None
            for kw in node.keywords:
                if kw.arg == "flags":
                    flag_node = kw.value
            try:
                pat, flags = text_of(node.args[0]), flags_of(flag_node)
                re.compile(pat, flags)
            except (ValueError, re.error) as exc:
                out.append((where, node.func.attr, None, 0, f"{type(exc).__name__}: {exc}"))
                continue
            out.append((where, node.func.attr, pat, flags, ""))
    return out


def worker(conn) -> None:
    cache: dict = {}
    while True:
        job = conn.recv()
        if job is None:
            return
        pat, flags, text = job
        rx = cache.get((pat, flags))
        if rx is None:
            rx = cache[(pat, flags)] = re.compile(pat, flags)
        t = time.perf_counter()
        for _ in rx.finditer(text):
            pass
        conn.send(time.perf_counter() - t)


class Timer:
    """One search at a time in a child process that is killed when the search takes too long."""

    def __init__(self) -> None:
        self.start()

    def start(self) -> None:
        self.parent, child = mp.Pipe()
        self.proc = mp.Process(target=worker, args=(child,), daemon=True)
        self.proc.start()

    def time(self, pat: str, flags: int, text: str):
        self.parent.send((pat, flags, text))
        if self.parent.poll(LIMIT):
            return self.parent.recv()
        self.proc.kill()
        self.proc.join()
        self.start()
        return None


def lane(pats: list, n0: int, path: str) -> None:
    timer = Timer()
    with open(path, "w", encoding="utf-8", newline="\n") as out:
        for where, func, pat, flags, err in pats:
            if pat is None:
                out.write(f"SKIP {where} {func} {err}\n")
                continue
            words: list = []
            for w in re.findall(r"[A-Za-z_]{2,}", pat):
                if w not in words:
                    words.append(w)
            units = UNITS + words[:10] + [w + " " for w in words[:10]] + [w + "(" for w in words[:4]] + [w + "=" for w in words[:4]]
            prefixes = PREFIXES + [w + " " for w in words[:3]] + words[:3]
            n = n0
            for piece, cap in CAPS:
                if piece in pat:
                    n = min(n, cap)
            slow = cases = 0
            worst = (0.0, "")
            for u in units:
                for pre in prefixes:
                    for suf in SUFFIXES:
                        cases += 1
                        k = max(1, n // len(u))
                        t1 = timer.time(pat, flags, pre + u * k + suf)
                        if t1 is not None and t1 < THRESH:
                            if t1 > worst[0]:
                                worst = (t1, f"prefix={pre!r} unit={u!r} suffix={suf!r}")
                            continue
                        t2 = timer.time(pat, flags, pre + u * (2 * k) + suf) if t1 is not None else None
                        slow += 1
                        if slow <= 5:
                            out.write(f"  slow: {where} prefix={pre!r} unit={u!r} suffix={suf!r} "
                                      f"t({n})={'killed' if t1 is None else format(t1, '.3f')} "
                                      f"t({2 * n})={'killed' if t2 is None else format(t2, '.3f')}\n")
                            out.flush()
            out.write(f"{'SLOW' if slow else 'ok  '} {where} {func} n={n} strings={cases} slow={slow} "
                      f"slowest_other={worst[0]:.3f}s {worst[1]} :: {pat[:70]!r}\n")
            out.flush()


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 32000
    lanes = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) // 2)
    package = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docsdrift")
    pats = patterns(package)
    seen, uniq = set(), []
    for p in pats:
        key = (p[2], p[3])
        if p[2] is not None and key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    with tempfile.TemporaryDirectory() as tmp:
        procs = []
        for i in range(lanes):
            pr = mp.Process(target=lane, args=(uniq[i::lanes], n, os.path.join(tmp, f"lane{i}.txt")))
            pr.start()
            procs.append(pr)
        for pr in procs:
            pr.join()
        lines: list = []
        for i in range(lanes):
            with open(os.path.join(tmp, f"lane{i}.txt"), encoding="utf-8") as fh:
                lines += fh.read().splitlines()
    results = [ln for ln in lines if not ln.startswith("  ")]
    strings = sum(int(m.group(1)) for m in (re.search(r" strings=(\d+) ", ln) for ln in results) if m)
    print(f"regular-expression calls: {len(pats)}; different patterns: {len(uniq)}; "
          f"strings timed: {strings}; length: {n}; reported at {THRESH}s; killed at {LIMIT:g}s")
    print(f"python {sys.version.split()[0]} on {sys.platform}; {lanes} processes at once")
    print(f"patterns with a slow string: {sum(ln.startswith('SLOW') for ln in results)}; "
          f"patterns not timed: {sum(ln.startswith('SKIP') for ln in results)}")
    print()
    blocks, block = [], []
    for ln in lines:                       # the slow strings of a pattern come before its result line
        block.append(ln)
        if not ln.startswith("  "):
            name, _, line = ln.split()[1].partition(":")
            blocks.append(((name, int(line)), block))
            block = []
    for _key, block in sorted(blocks, key=lambda b: b[0]):
        for ln in block:
            print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Markdown reader: code spans, fenced blocks, links and command lines.

This is not a full CommonMark parser. It extracts only what the checks need
and keeps exact line numbers for every item.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})\s*([^\s`{]*)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
LINK_TARGET = re.compile(
    r"\]\(\s*(<[^>\n]+>|[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
REF_DEF = re.compile(r"^\s{0,3}\[([^\]^][^\]]*)\]:\s*(<[^>]+>|\S+)")
# The attribute must follow whitespace: `:href="expr"` / `v-bind:href` are template bindings, not paths.
HTML_SRC = re.compile(r"<(?:img|a|source|video)\b(?:[^>]*?\s)?(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.I)

SHELL_LANGS = {
    "", "sh", "bash", "shell", "zsh", "console", "terminal", "shell-session",
    "shellsession", "sh-session", "bat", "cmd", "powershell", "ps1", "fish", "text", "txt",
    "plaintext", "plain", "command", "cli",
}
PROMPT = re.compile(r"^\s*(?:\$|>|%|#|PS\s?[^>]*>|[\w.@~:/\\-]*[\$#])\s+(?=\S)")
SIMPLE_PROMPT = re.compile(r"^\s*(?:\$|>|%)\s+(?=\S)")

# Lines that talk about history, not about the current behaviour.
STALE_WORDS = re.compile(
    r"\b(deprecat\w*|removed|renamed|no longer|formerly|previously|legacy|obsolete|"
    r"was replaced|has been replaced|replaced by|replaces|instead of|used to|old name|"
    r"prior to|before v?\d|as of v?\d|since v?\d|in v?\d+\.\d+|breaking|migrat\w*|"
    r"not (yet )?(supported|implemented|available)|planned|coming soon|future|todo|"
    r"proposal|proposed|would|could|might|hypothetical|for example,? (if|a)|e\.g\.)\b",
    re.I,
)
STALE_HEADING = re.compile(
    r"\b(change\s?log|changes|history|release notes?|what'?s new|migrat\w*|upgrad\w*|"
    r"deprecat\w*|breaking|roadmap|todo|future|planned|proposal|ideas|alternatives|"
    r"comparison|vs\.?|faq|troubleshoot\w*|related|see also|acknowledg\w*|credits|"
    r"background|motivation|prior art|inspiration)\b",
    re.I,
)


@dataclass
class Block:
    start: int               # 1-based line of the first content line
    lang: str
    lines: List[str]


@dataclass
class Span:
    line: int
    text: str


@dataclass
class Link:
    line: int
    target: str
    kind: str                # "link" | "ref" | "html"


@dataclass
class Command:
    line: int
    text: str                # the command as written (joined continuations)
    tokens: List[str]
    block_start: int         # 0 for inline spans
    inline: bool


@dataclass
class Doc:
    path: str
    lines: List[str]
    blocks: List[Block] = field(default_factory=list)
    spans: List[Span] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    headings: List[Tuple[int, int, str]] = field(default_factory=list)   # (line, level, title)
    in_block: List[bool] = field(default_factory=list)                   # per line, 0-based
    _heading_idx: Optional[List[int]] = None

    def heading_at(self, line: int) -> str:
        """Nearest heading path ("A > B") above a 1-based line."""
        stack: List[Tuple[int, str]] = []
        for hl, level, title in self.headings:
            if hl > line:
                break
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        return " > ".join(t for _, t in stack)

    def stale_context(self, line: int) -> bool:
        """True when the line or its heading talks about past/future behaviour."""
        text = self.lines[line - 1] if 0 < line <= len(self.lines) else ""
        if STALE_WORDS.search(text):
            return True
        return bool(STALE_HEADING.search(self.heading_at(line)))

    def line_text(self, line: int) -> str:
        return self.lines[line - 1] if 0 < line <= len(self.lines) else ""


def _blank_html_comments(lines: List[str]) -> List[str]:
    out: List[str] = []
    inside = False
    for ln in lines:
        res = ""
        i = 0
        while i < len(ln):
            if inside:
                j = ln.find("-->", i)
                if j < 0:
                    i = len(ln)
                else:
                    inside = False
                    i = j + 3
            else:
                j = ln.find("<!--", i)
                if j < 0:
                    res += ln[i:]
                    i = len(ln)
                else:
                    res += ln[i:j]
                    inside = True
                    i = j + 4
        out.append(res)
    return out


def parse_markdown(path: str, text: str) -> Doc:
    raw_lines = text.splitlines()
    # front matter
    start = 0
    if raw_lines and raw_lines[0].strip() == "---":
        for i in range(1, min(len(raw_lines), 200)):
            if raw_lines[i].strip() in ("---", "..."):
                start = i + 1
                break
    lines = _blank_html_comments(raw_lines)
    for i in range(start):
        lines[i] = ""
    doc = Doc(path=path, lines=raw_lines)
    in_block = [False] * len(lines)
    fence_char = ""
    fence_len = 0
    cur: Optional[Block] = None
    for idx, ln in enumerate(lines):
        m = FENCE.match(ln)
        if cur is None:
            if m:
                fence_char = m.group(2)[0]
                fence_len = len(m.group(2))
                cur = Block(start=idx + 2, lang=m.group(3).lower().strip(), lines=[])
                in_block[idx] = True
                continue
            h = HEADING.match(ln)
            if h:
                title = re.sub(r"[`*_]", "", h.group(2)).strip()
                doc.headings.append((idx + 1, len(h.group(1)), title))
            # indented code blocks are ignored (ambiguous with list continuation)
            for sm in CODE_SPAN.finditer(ln):
                body = sm.group(2).strip()
                if body:
                    doc.spans.append(Span(idx + 1, body))
            no_code = CODE_SPAN.sub(lambda mm: " " * len(mm.group(0)), ln)
            for lm in LINK_TARGET.finditer(no_code):
                doc.links.append(Link(idx + 1, lm.group(1).strip("<>"), "link"))
            rm = REF_DEF.match(no_code)
            if rm:
                doc.links.append(Link(idx + 1, rm.group(2).strip("<>"), "ref"))
            for hm in HTML_SRC.finditer(no_code):
                doc.links.append(Link(idx + 1, hm.group(1), "html"))
        else:
            in_block[idx] = True
            if m and m.group(2)[0] == fence_char and len(m.group(2)) >= fence_len and not m.group(3):
                doc.blocks.append(cur)
                cur = None
                continue
            cur.lines.append(ln)
    if cur is not None:
        doc.blocks.append(cur)
    doc.in_block = in_block
    return doc


_OPS = {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>", "2>&1", "|&"}


def split_command(text: str) -> List[str]:
    """Whitespace split that keeps quoted strings together. Never raises."""
    tokens: List[str] = []
    cur = ""
    quote = ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch.isspace():
            if cur:
                tokens.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        tokens.append(cur)
    return tokens


def _segments(tokens: List[str]) -> List[List[str]]:
    """Split a token list at shell operators into simple commands."""
    segs: List[List[str]] = [[]]
    for t in tokens:
        if t in _OPS or t.endswith(";") and len(t) > 1 and not t.startswith(("'", '"')):
            if t.endswith(";") and t not in _OPS:
                segs[-1].append(t[:-1])
            segs.append([])
        else:
            segs[-1].append(t)
    return [s for s in segs if s]


def commands_of(doc: Doc) -> List[Command]:
    """Every shell command line found in fenced shell blocks and code spans."""
    out: List[Command] = []
    for blk in doc.blocks:
        if blk.lang not in SHELL_LANGS:
            continue
        has_prompt = any(SIMPLE_PROMPT.match(l) for l in blk.lines)
        i = 0
        while i < len(blk.lines):
            ln = blk.lines[i]
            line_no = blk.start + i
            i += 1
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            if has_prompt:
                if not SIMPLE_PROMPT.match(ln):
                    continue        # program output
                ln = SIMPLE_PROMPT.sub("", ln, count=1)
            while ln.rstrip().endswith(("\\", "`", "^")) and i < len(blk.lines) and ln.rstrip()[-1] in "\\^`":
                last = ln.rstrip()[-1]
                if last == "`" and blk.lang not in ("powershell", "ps1"):
                    break
                ln = ln.rstrip()[:-1] + " " + blk.lines[i].strip()
                i += 1
            if "$(" in ln or "`" in ln or "<<" in ln:
                continue
            for seg in _segments(split_command(ln)):
                out.append(Command(line_no, " ".join(seg), seg, blk.start, False))
    for sp in doc.spans:
        text = SIMPLE_PROMPT.sub("", sp.text, count=1)
        if " " not in text.strip() or "$(" in text:
            continue
        for seg in _segments(split_command(text)):
            out.append(Command(sp.line, " ".join(seg), seg, 0, True))
    return out


def block_at(doc: Doc, start: int) -> Optional[Block]:
    for b in doc.blocks:
        if b.start == start:
            return b
    return None


def table_columns(line: str) -> List[str]:
    """Cells of a Markdown table row (empty list when the line is not a row)."""
    s = line.strip()
    if "|" not in s:
        return []
    # protect pipes inside code spans
    protected = CODE_SPAN.sub(lambda m: m.group(0).replace("|", "\0"), s)
    if protected.startswith("|"):
        protected = protected[1:]
    if protected.endswith("|"):
        protected = protected[:-1]
    return [c.replace("\0", "|").strip() for c in protected.split("|")]


def table_header_for(doc: Doc, line: int) -> List[str]:
    """Header cells of the table a 1-based line belongs to (lowercased)."""
    i = line - 1
    while i > 0 and "|" in doc.lines[i - 1] and not doc.in_block[i - 1]:
        i -= 1
    # i is the first row of the table; a header is followed by a |---| row
    if i + 1 < len(doc.lines) and re.match(r"^\s*\|?\s*:?-{2,}", doc.lines[i + 1]):
        return [c.lower() for c in table_columns(doc.lines[i])]
    return []

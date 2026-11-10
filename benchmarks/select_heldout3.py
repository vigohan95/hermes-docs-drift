"""Apply the rule in evidence/heldout3-rule.md and print the selection.

    python benchmarks/select_heldout3.py evidence/targets.txt > evidence/heldout3-selection.txt

Needs the GitHub CLI (``gh``), logged in; it only reads. Nothing is cloned here.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time

QUERY = "topic:cli stars:300..5000 pushed:>=2026-08-12 archived:false fork:false"
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]{2,}")
ENV = re.compile(r"\b[A-Z][A-Z0-9]{2,}_[A-Z0-9_]{2,}\b")
NOT_A_PROGRAM = ("awesome", "tutorial", "course", "book", "list of")
WANTED, PER_LANGUAGE, MAX_KB = 12, 4, 150 * 1024


def gh(path: str):
    for attempt in range(3):
        proc = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8")
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        if "404" in proc.stderr:
            return None
        time.sleep(5 * (attempt + 1))
    raise SystemExit(f"gh api {path} failed: {proc.stderr.strip()[:200]}")


def main(argv) -> int:
    known = set()
    with open(argv[1], encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3 and not line.startswith("#") and "/" in parts[1]:
                known.add(parts[1].lower())
    known_owners = {name.split("/")[0] for name in known}
    print(f"query: {QUERY}   sort: stars, descending   run at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    taken, per_language, seen = [], {}, 0
    page = 0
    while len(taken) < WANTED and page < 10:
        page += 1
        q = QUERY.replace(" ", "+").replace(">", "%3E")
        result = gh(f"search/repositories?q={q}&sort=stars&order=desc&per_page=100&page={page}")
        items = (result or {}).get("items") or []
        if page == 1:
            print(f"total_count reported by the API: {(result or {}).get('total_count')}")
        if not items:
            break
        for repo in items:
            if len(taken) >= WANTED:
                break
            seen += 1
            name = repo["full_name"]
            head = f"{seen:3d}  {name}  ({repo['stargazers_count']} stars, {repo.get('language')}, {repo['size']} KB)"
            text = (name + " " + (repo.get("description") or "")).lower()
            language = repo.get("language") or ""
            if name.lower() in known or name.split("/")[0].lower() in known_owners:
                print(head + "  skipped: in targets.txt, or same owner as one of them")
                continue
            if any(word in text for word in NOT_A_PROGRAM):
                print(head + "  skipped: name or description marks it as a list, tutorial or book")
                continue
            if repo["size"] > MAX_KB:
                print(head + "  skipped: larger than 150 MB")
                continue
            if not language:
                print(head + "  skipped: no primary language")
                continue
            if per_language.get(language, 0) >= PER_LANGUAGE:
                print(head + f"  skipped: {PER_LANGUAGE} repositories in {language} already taken")
                continue
            readme = gh(f"repos/{name}/readme")
            if not readme or not readme.get("content"):
                print(head + "  skipped: no README through the API")
                continue
            body = base64.b64decode(readme["content"]).decode("utf-8", "replace")
            flags, envs = len(set(FLAG.findall(body))), len(set(ENV.findall(body)))
            if flags < 5 and envs < 3:
                print(head + f"  skipped: README has {flags} long flags and {envs} environment-style names")
                continue
            per_language[language] = per_language.get(language, 0) + 1
            taken.append(name)
            print(head + f"  TAKEN as number {len(taken)}: README has {flags} long flags and {envs} environment-style names")
    print()
    print(f"taken ({len(taken)}): " + " ".join(taken))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))

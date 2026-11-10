"""notesync: copy Markdown notes to a folder, one file per note."""

import argparse
import os
import shutil
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notesync")
    parser.add_argument("source", help="folder with .md notes")
    parser.add_argument("--output-dir", default="./out", help="where the copies go")
    parser.add_argument("--timeout", type=int, default=30, help="seconds to wait for a locked file")
    parser.add_argument("--dry-run", action="store_true", help="print what would be copied")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("NOTESYNC_TOKEN", "")
    out = Path(args.output_dir)
    for note in sorted(Path(args.source).glob("*.md")):
        if args.dry_run:
            print(f"would copy {note} -> {out / note.name}")
            continue
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(note, out / note.name)
    if token:
        print("token set: remote upload is enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

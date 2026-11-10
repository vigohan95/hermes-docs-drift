"""notesync: copy Markdown notes to a folder and upload them."""

import argparse
from pathlib import Path

from .sync import copy_notes
from .upload import read_token, upload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notesync")
    parser.add_argument("source", help="folder with .md notes")
    parser.add_argument("--output-dir", default="./out", help="where the copies go")
    parser.add_argument("--timeout", type=int, default=30, help="seconds to wait for the server")
    parser.add_argument("--retries", type=int, default=3, help="how often a failed upload is tried again")
    parser.add_argument("--legacy-sync", action="store_true",
                        help="deprecated: copy the files one by one, as version 0.2 did")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    copied = copy_notes(Path(args.source), Path(args.output_dir), one_by_one=args.legacy_sync)
    token = read_token()
    if token:
        upload(copied, token, timeout=args.timeout, retries=args.retries)
    print(f"{len(copied)} notes copied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Uploading the copies."""

import os
import time
from pathlib import Path
from typing import List


def read_token() -> str:
    """The upload token: from NOTESYNC_TOKEN, else from the file NOTESYNC_TOKEN_FILE names."""
    token = os.environ.get("NOTESYNC_TOKEN", "")
    if not token:
        token_file = os.environ.get("NOTESYNC_TOKEN_FILE", "")
        if token_file:
            token = Path(token_file).read_text(encoding="utf-8").strip()
    return token


def send(path: Path, token: str, timeout: int) -> bool:
    """Send one file. The example has no server, so this only checks the file is readable."""
    return path.is_file() and bool(token) and timeout > 0


def upload(files: List[Path], token: str, timeout: int, retries: int) -> int:
    """Upload the files; a file that fails is tried again ``retries`` times."""
    sent = 0
    for path in files:
        for attempt in range(retries + 1):
            if send(path, token, timeout):
                sent += 1
                break
            time.sleep(min(2 ** attempt, 30))
    return sent

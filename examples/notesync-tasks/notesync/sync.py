"""Copying the notes."""

import shutil
from pathlib import Path
from typing import List


def copy_notes(source: Path, dest: Path, one_by_one: bool = False) -> List[Path]:
    """Copy every .md file in ``source`` to ``dest`` and return the copies."""
    notes = sorted(source.glob("*.md"))
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    if one_by_one:
        # the 0.2 way: open, read and write each file, flushing after every one
        for note in notes:
            target = dest / note.name
            with open(note, "rb") as src, open(target, "wb") as out:
                out.write(src.read())
                out.flush()
            copied.append(target)
        return copied
    for note in notes:
        copied.append(Path(shutil.copy2(note, dest / note.name)))
    return copied

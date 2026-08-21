"""
Filesystem listing helpers used by the browse API.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int  # 0 for directories (we don't recursively size every listing — too slow for big trees)


def list_directory(path: str) -> list[Entry]:
    """
    List immediate children of `path`. Skips entries that can't be
    stat'd (permission-denied, broken symlinks, etc.) instead of
    raising — one locked file shouldn't break browsing the whole folder.
    Directories are sorted first, then files, both alphabetically
    (case-insensitive) — matches what people expect from Explorer.
    """
    entries: list[Entry] = []
    try:
        with os.scandir(path) as it:
            for de in it:
                try:
                    is_dir = de.is_dir(follow_symlinks=False)
                    size = 0 if is_dir else de.stat().st_size
                    entries.append(Entry(name=de.name, is_dir=is_dir, size=size))
                except OSError:
                    continue  # locked / inaccessible — skip, don't crash the listing
    except OSError:
        return []

    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries

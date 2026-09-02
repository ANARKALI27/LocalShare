"""
Upload handling.

Mirrors the same safety rules as downloads: destination paths go
through safe_join, filenames get sanitized, and nothing is ever fully
buffered in memory — incoming file data is read and written in fixed
chunks.
"""
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from app.server.security import sanitize_filename, safe_join
from app.transfer.download import CHUNK_SIZE

if TYPE_CHECKING:
    from fastapi import UploadFile


def unique_destination(path: str) -> str:
    """
    If `path` already exists, return a variant like 'name (1).ext',
    'name (2).ext', etc. — never silently overwrite an existing file.
    """
    if not os.path.exists(path):
        return path

    directory, filename = os.path.split(path)
    base, ext = os.path.splitext(filename)

    counter = 1
    while True:
        candidate = os.path.join(directory, f"{base} ({counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def resolve_upload_path(shared_root: str, relative_path: str) -> str:
    """
    Turn a client-supplied relative path (e.g. "photos/vacation/img.jpg",
    possibly from a folder upload) into a safe absolute destination
    inside `shared_root`. Every path segment is sanitized individually,
    then the whole thing is validated with safe_join.
    """
    raw_segments = [s for s in relative_path.replace("\\", "/").split("/") if s]
    clean_segments = [sanitize_filename(s) for s in raw_segments] or ["unnamed"]
    return safe_join(shared_root, *clean_segments)


async def save_upload(
    upload_file: UploadFile, destination: str, on_progress=None
) -> tuple[str, int]:
    """
    Stream an incoming UploadFile to disk in chunks. Returns
    (actual_destination_path, bytes_written) — the actual path may
    differ from the requested `destination` if a same-name file already
    existed there (see unique_destination); callers that need to refer
    back to the saved file (e.g. building a download link) MUST use the
    returned path, not the one they passed in. Creates parent
    directories as needed (for folder uploads that include nested paths).

    on_progress, if given, is called with the cumulative bytes written
    so far after each chunk — optional, for callers that want to report
    live progress (e.g. into the Transfers page) without this function
    needing to know anything about how that's tracked.
    """
    os.makedirs(os.path.dirname(destination), exist_ok=True)

    destination = unique_destination(destination)

    loop = asyncio.get_event_loop()
    total = 0
    with open(destination, "wb") as out:
        while True:
            chunk = await upload_file.read(CHUNK_SIZE)
            if not chunk:
                break
            # Offloaded to a thread — a blocking file.write() call
            # directly in this async function would freeze the entire
            # server's event loop for the duration of every write,
            # stalling unrelated requests (other people's downloads,
            # other uploads' chunks) while this one file is being saved.
            await loop.run_in_executor(None, out.write, chunk)
            total += len(chunk)
            if on_progress is not None:
                on_progress(total)

    return destination, total

"""
Streaming download logic.

Everything here reads in fixed-size chunks. Nothing ever does
`data = file.read()` on a whole file — that's the one rule this
module exists to enforce, since a 50GB file read whole would crash
the process (or at minimum thrash the disk cache badly).
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from collections.abc import Iterator

CHUNK_SIZE = 1024 * 1024  # 1 MB — large enough to be efficient, small enough to stay light on RAM


def stream_file(path: str) -> Iterator[bytes]:
    """Yield a file's contents in fixed-size chunks."""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """
    Parse an HTTP "Range: bytes=start-end" header. Returns an inclusive
    (start, end) byte range clamped to the file's actual size, or None
    if the header is absent/unparseable/unsatisfiable (caller should
    then serve the whole file normally).

    Only single-range requests are supported ("bytes=0-999") — that
    covers browser video/audio seeking and download managers, which is
    what this exists for. Multi-range ("bytes=0-10,20-30") is rare in
    practice for media and falls back to a full response.
    """
    if not range_header or not range_header.startswith("bytes="):
        return None

    spec = range_header[len("bytes="):].strip()
    if "," in spec:
        return None  # multi-range not supported — serve the full file instead

    if "-" not in spec:
        return None

    start_str, _, end_str = spec.partition("-")

    try:
        if start_str == "":
            # suffix range like "bytes=-500" = last 500 bytes
            suffix_len = int(end_str)
            if suffix_len <= 0:
                return None
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str != "" else file_size - 1
    except ValueError:
        return None

    if start < 0 or start >= file_size or end < start:
        return None

    end = min(end, file_size - 1)
    return start, end


def stream_file_range(path: str, start: int, end: int) -> Iterator[bytes]:
    """Yield bytes [start, end] (inclusive) of a file, in fixed-size chunks."""
    remaining = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def create_zip_archive(source_dir: str) -> str:
    """
    Build a zip of `source_dir` into a temp file on disk and return its
    path. We build to disk rather than in-memory: zipfile.write() reads
    each source file in internal chunks (not all at once), so this stays
    memory-light even for very large folders — the only cost is temp
    disk space equal to the zip size, which is unavoidable for a
    correct zip (its central directory has to be finalized at the end).

    Caller is responsible for deleting the returned path once the
    response has finished streaming it (see routes.py's use of
    BackgroundTask for this).
    """
    fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="localshare_")
    os.close(fd)

    base_name = os.path.basename(source_dir.rstrip(os.sep))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(source_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                # arcname keeps the top folder name so extracting the
                # zip recreates "FolderName/..." rather than dumping
                # contents loose — matches what people expect.
                rel_path = os.path.relpath(full_path, source_dir)
                arcname = os.path.join(base_name, rel_path)
                try:
                    zf.write(full_path, arcname)
                except OSError:
                    continue  # locked/inaccessible file — skip it, don't fail the whole zip

    return zip_path


def cleanup_temp_file(path: str) -> None:
    """Best-effort deletion of a temp file (e.g. a generated zip) after it's been sent."""
    try:
        os.unlink(path)
    except OSError:
        pass

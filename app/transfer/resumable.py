"""
Resumable upload sessions.

Large uploads (multi-GB) can realistically drop mid-transfer on a real
LAN — a laptop stepping out of Wi-Fi range, a cable getting bumped,
sleep mode. Instead of one all-or-nothing POST (the original Phase 5
approach, still used for small stuff like message attachments), the
browser splits a file into chunks and PUTs each one at an explicit
byte offset. If a chunk fails, only that chunk needs retrying. If the
whole tab closes, an upload_id kept client-side (in localStorage) lets
the transfer resume from wherever the server actually left off,
verified against the server's own byte count rather than trusted
blindly.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.transfer.range_tracking import Range, is_fully_covered, merge_range, total_covered
from app.transfer.upload import resolve_upload_path, unique_destination


@dataclass
class UploadSession:
    id: str
    item_id: str
    dest_dir: str  # resolved, safe absolute folder the file will land in
    relative_path: str  # e.g. "photos/vacation/img.jpg" — preserves folder-upload structure
    total_size: int
    temp_path: str
    created_at: float = field(default_factory=time.time)
    bytes_received: int = 0
    covered_ranges: list[Range] = field(default_factory=list)
    finalized: bool = False


class ResumableUploadManager:
    def __init__(self) -> None:
        self._sessions: dict[str, UploadSession] = {}
        self._lock = threading.Lock()
        self._temp_dir = tempfile.mkdtemp(prefix="localshare_resumable_")

    def start_session(
        self, item_id: str, dest_dir: str, relative_path: str, total_size: int
    ) -> UploadSession:
        if total_size < 0:
            raise ValueError("total_size must not be negative")

        session_id = uuid.uuid4().hex
        temp_path = os.path.join(self._temp_dir, session_id + ".part")
        # Pre-allocate an empty file so byte-offset writes always have
        # something valid to seek into, even for the very first chunk.
        open(temp_path, "wb").close()

        session = UploadSession(
            id=session_id,
            item_id=item_id,
            dest_dir=dest_dir,
            relative_path=relative_path,
            total_size=total_size,
            temp_path=temp_path,
        )
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> UploadSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def write_chunk(self, session_id: str, offset: int, data: bytes) -> UploadSession:
        """
        Writes a chunk at an explicit byte offset. Chunks may arrive in
        any order and may safely overlap (a retried/duplicate chunk is
        idempotent) — this intentionally does NOT require offset to
        match "how many bytes so far," unlike the original strictly-
        sequential version, so the browser can upload several chunks
        concurrently instead of one at a time. See range_tracking.py
        for the (separately, exhaustively tested) logic that makes this
        safe: coverage is tracked as a set of byte ranges, and
        finalize() refuses to complete unless they form one unbroken
        span with no gaps.
        """
        session = self.get(session_id)
        if session is None:
            raise KeyError("unknown upload session")
        if session.finalized:
            raise ValueError("session already finalized")
        if offset < 0 or offset + len(data) > session.total_size:
            raise ValueError(
                f"chunk at offset {offset} (length {len(data)}) is out of bounds "
                f"for a {session.total_size}-byte file"
            )

        # The actual disk write is serialized behind the lock —
        # deliberately, unlike an earlier version of this method that
        # opened the same file concurrently from multiple threads
        # assuming that was safe cross-platform. It's genuinely fine on
        # POSIX, but Windows file-handle sharing is stricter by
        # default and this was never actually tested there, only
        # inferred — exactly the kind of assumption not worth carrying
        # into something as core as "can this app upload a file at
        # all." The concurrency benefit of uploading several chunks at
        # once mostly comes from overlapping NETWORK transfer time
        # across chunks anyway; serializing the brief disk write itself
        # costs very little of that.
        with self._lock:
            with open(session.temp_path, "r+b") as f:
                f.seek(offset)
                f.write(data)
            session.covered_ranges = merge_range(session.covered_ranges, (offset, offset + len(data)))
            session.bytes_received = total_covered(session.covered_ranges)
        return session

    def finalize(self, session_id: str) -> str:
        """
        Move the completed temp file to its real destination (going
        through the same safe path resolution and duplicate-avoidance
        as the regular upload path) and mark the session done. Returns
        the final absolute path.
        """
        session = self.get(session_id)
        if session is None:
            raise KeyError("unknown upload session")
        if not is_fully_covered(session.covered_ranges, session.total_size):
            raise ValueError(
                f"upload incomplete: {session.bytes_received}/{session.total_size} bytes received"
            )

        final_path = resolve_upload_path(session.dest_dir, session.relative_path)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        final_path = unique_destination(final_path)

        # shutil.move (not os.replace) because the temp dir and the
        # destination folder can be on different drives on Windows
        # (e.g. temp on C:, shared folder on D:) — a plain rename fails
        # across drives, but shutil.move falls back to copy+delete.
        shutil.move(session.temp_path, final_path)

        with self._lock:
            session.finalized = True
        return final_path

    def cancel(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is None:
            return
        try:
            os.unlink(session.temp_path)
        except OSError:
            pass
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup(self) -> None:
        """Wipe all sessions and their temp files — called when the server stops."""
        with self._lock:
            self._sessions.clear()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

"""
Tracks files received via upload, for the "Received" page — a
dedicated view of what's arrived from others, separate from the
general Shared Items list (which mixes manually-added and received
files together with no way to tell them apart) and separate from
Transfers/History (which also include downloads TO other people, not
just uploads received here). No I/O, same reasoning as transfers.py:
pure bookkeeping, tested on its own before trusting it.
"""
from __future__ import annotations

import threading
import time

MAX_ENTRIES = 200


class ReceivedLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    def record(
        self, filename: str, size: int, source_address: str, path: str, now: float | None = None
    ) -> None:
        entry = {
            "filename": filename,
            "size": size,
            "source_address": source_address,
            "path": path,
            "received_at": now if now is not None else time.time(),
        }
        with self._lock:
            self._entries.insert(0, entry)  # most recent first
            if len(self._entries) > MAX_ENTRIES:
                self._entries = self._entries[:MAX_ENTRIES]

    def all_entries(self) -> list[dict]:
        with self._lock:
            return list(self._entries)  # defensive copy

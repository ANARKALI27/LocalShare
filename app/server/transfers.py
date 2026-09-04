"""
Tracks active uploads/downloads for the "Transfers" page — how far
along each one is, current speed, ETA, and whether it's been asked to
cancel. No I/O here at all, deliberately: this is pure bookkeeping,
completely separate from the actual streaming/writing code that
reports into it, so the bookkeeping logic itself can be tested
thoroughly before trusting it.
"""
from __future__ import annotations

import threading
import time
import uuid

MAX_HISTORY = 200  # capped so this can't grow forever across a long-running session


class TransferRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._transfers: dict[str, dict] = {}
        self._history: list[dict] = []

    def start_transfer(
        self,
        direction: str,
        filename: str,
        total_bytes: int,
        client_address: str = "",
        transfer_id: str | None = None,
    ) -> str:
        """direction is 'upload' or 'download'. Returns the transfer_id
        (either the one supplied, or a freshly generated one) — callers
        that already have a natural identifier for this transfer (e.g.
        a resumable upload session's own id) can pass it in directly,
        so the two stay correlated for cancellation to work cleanly."""
        transfer_id = transfer_id or uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._transfers[transfer_id] = {
                "direction": direction,
                "filename": filename,
                "total_bytes": total_bytes,
                "bytes_transferred": 0,
                "client_address": client_address,
                "started_at": now,
                "last_update_at": now,
                "last_update_bytes": 0,
                "speed_bytes_per_sec": 0.0,
                "cancelled": False,
                "finished": False,
            }
        return transfer_id

    def update_progress(self, transfer_id: str, bytes_transferred: int, now: float | None = None) -> None:
        current_time = now if now is not None else time.time()
        with self._lock:
            t = self._transfers.get(transfer_id)
            if t is None or t["finished"]:
                return
            elapsed = current_time - t["last_update_at"]
            if elapsed > 0:
                delta_bytes = bytes_transferred - t["last_update_bytes"]
                t["speed_bytes_per_sec"] = max(0.0, delta_bytes / elapsed)
            t["bytes_transferred"] = bytes_transferred
            t["last_update_at"] = current_time
            t["last_update_bytes"] = bytes_transferred

    def finish_transfer(self, transfer_id: str) -> None:
        with self._lock:
            t = self._transfers.get(transfer_id)
            if t is None or t["finished"]:
                return  # already finished — guards against double-recording history below
            t["finished"] = True
            t["finished_at"] = time.time()
            t["speed_bytes_per_sec"] = 0.0
            self._history.insert(0, {
                "transfer_id": transfer_id,
                "direction": t["direction"],
                "filename": t["filename"],
                "total_bytes": t["total_bytes"],
                "bytes_transferred": t["bytes_transferred"],
                "client_address": t["client_address"],
                "started_at": t["started_at"],
                "finished_at": t["finished_at"],
                "cancelled": t["cancelled"],
            })
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[:MAX_HISTORY]

    def get_history(self) -> list[dict]:
        """Most-recent-first list of completed transfers (both
        successful and cancelled) — for the History page. A defensive
        copy, same reasoning as active_devices() in discovery.py."""
        with self._lock:
            return list(self._history)

    def cancel_transfer(self, transfer_id: str) -> bool:
        """Marks a transfer as cancelled. Returns False if no such
        active transfer exists (already finished, or never existed) —
        the caller can use this to report a clear error rather than a
        silent no-op."""
        with self._lock:
            t = self._transfers.get(transfer_id)
            if t is None or t["finished"]:
                return False
            t["cancelled"] = True
            return True

    def is_cancelled(self, transfer_id: str) -> bool:
        with self._lock:
            t = self._transfers.get(transfer_id)
            return bool(t and t["cancelled"])

    def get_active(self, now: float | None = None) -> list[dict]:
        """Active = not finished (cancelled-but-not-yet-finished still
        shows, so the UI can reflect 'cancelling...' until the actual
        stream/write loop notices and stops)."""
        current_time = now if now is not None else time.time()
        with self._lock:
            active = []
            for transfer_id, t in self._transfers.items():
                if t["finished"]:
                    continue
                remaining = max(0, t["total_bytes"] - t["bytes_transferred"])
                eta_seconds = (remaining / t["speed_bytes_per_sec"]) if t["speed_bytes_per_sec"] > 0 else None
                active.append({
                    "transfer_id": transfer_id,
                    "direction": t["direction"],
                    "filename": t["filename"],
                    "total_bytes": t["total_bytes"],
                    "bytes_transferred": t["bytes_transferred"],
                    "client_address": t["client_address"],
                    "speed_bytes_per_sec": t["speed_bytes_per_sec"],
                    "eta_seconds": eta_seconds,
                    "cancelled": t["cancelled"],
                })
            return sorted(active, key=lambda x: x["filename"].lower())

    def prune_finished(self, older_than_seconds: float = 60.0, now: float | None = None) -> None:
        """Housekeeping — removes finished entries after a delay
        (rather than immediately) so a just-completed transfer can
        still briefly show as '100%' in the UI before disappearing,
        instead of vanishing the instant it finishes."""
        current_time = now if now is not None else time.time()
        with self._lock:
            self._transfers = {
                tid: t for tid, t in self._transfers.items()
                if not t["finished"] or (current_time - t["last_update_at"]) < older_than_seconds
            }

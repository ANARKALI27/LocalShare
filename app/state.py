"""
Central in-memory state for LocalShare.

This is intentionally decoupled from the GUI: the HTTP/WebDAV server
(Phase 3+) will read from the same ShareManager instance, so "what's
shared" has exactly one source of truth.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SharedItem:
    """A single file or folder the user has chosen to share."""

    path: str  # absolute, original path on disk — never copied
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("\\/")) or self.path

    @property
    def is_dir(self) -> bool:
        return os.path.isdir(self.path)

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)

    def size_bytes(self) -> int:
        """Best-effort size. For folders, walks the tree (skips unreadable files)."""
        if not self.exists:
            return 0
        if not self.is_dir:
            try:
                return os.path.getsize(self.path)
            except OSError:
                return 0
        total = 0
        for root, _dirs, files in os.walk(self.path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    continue  # locked/inaccessible file — skip, don't crash
        return total


class ShareManager:
    """
    Holds the list of currently-shared items and notifies listeners
    (the GUI, later the server) when the list changes.
    """

    def __init__(self) -> None:
        self._items: dict[str, SharedItem] = {}
        self._listeners: list[Callable[[], None]] = []

    # -- subscription -----------------------------------------------------
    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    # -- mutation -----------------------------------------------------------
    def add_path(self, path: str) -> SharedItem | None:
        """Add a path if it exists and isn't already shared. Returns the item or None."""
        path = os.path.normpath(path)
        if not os.path.exists(path):
            return None
        # avoid duplicate shares of the exact same path
        for existing in self._items.values():
            if os.path.normcase(existing.path) == os.path.normcase(path):
                return existing
        item = SharedItem(path=path)
        self._items[item.id] = item
        self._notify()
        return item

    def remove(self, item_id: str) -> None:
        if item_id in self._items:
            del self._items[item_id]
            self._notify()

    def clear(self) -> None:
        self._items.clear()
        self._notify()

    # -- read -----------------------------------------------------------
    def all_items(self) -> list[SharedItem]:
        return list(self._items.values())

    def get(self, item_id: str) -> SharedItem | None:
        return self._items.get(item_id)

    def __len__(self) -> int:
        return len(self._items)

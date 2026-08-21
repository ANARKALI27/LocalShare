"""
In-memory message store for the private messaging section.

Deliberately simple and ephemeral: messages and attachments live only
for the current sharing session and are wiped when the server stops.
There's no persistence file and no encryption beyond what the LAN
itself provides — this is meant for quick back-and-forth during a
session, not as a durable chat log.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field

from app.server.security import sanitize_filename


@dataclass
class Attachment:
    id: str
    filename: str
    size: int
    mime_type: str


@dataclass
class Message:
    id: int
    sender: str
    text: str
    timestamp: float
    attachments: list[Attachment] = field(default_factory=list)


class MessageStore:
    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._next_id = 1
        self._lock = threading.Lock()
        # Attachments live in their own temp dir, separate from any
        # shared folder — this is not part of the file-browsing tree,
        # so it's addressed only through the messages API.
        self.attachments_dir = tempfile.mkdtemp(prefix="localshare_msgs_")

    def _next_message_id(self) -> int:
        with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            return msg_id

    def add_message(self, sender: str, text: str) -> Message:
        msg = Message(
            id=self._next_message_id(),
            sender=sanitize_display_name(sender),
            text=text.strip()[:4000],  # generous but bounded — this isn't meant for essays
            timestamp=time.time(),
        )
        with self._lock:
            self._messages.append(msg)
        return msg

    def attachment_dest_path(self, message_id: int, filename: str) -> str:
        """Where a given message's attachment should be written on disk."""
        msg_dir = os.path.join(self.attachments_dir, str(message_id))
        os.makedirs(msg_dir, exist_ok=True)
        safe_name = sanitize_filename(filename)
        return os.path.join(msg_dir, safe_name)

    def attachment_source_path(self, message_id: int, filename: str) -> str | None:
        """
        Resolve a requested attachment to its actual path, verifying it
        belongs to that message and doesn't escape the attachments dir.
        Returns None if not found or if the path would escape (guards
        against a crafted filename in the URL).
        """
        msg_dir = os.path.realpath(os.path.join(self.attachments_dir, str(message_id)))
        safe_name = sanitize_filename(filename)
        candidate = os.path.realpath(os.path.join(msg_dir, safe_name))
        if not candidate.startswith(msg_dir + os.sep) and candidate != msg_dir:
            return None
        if not os.path.isfile(candidate):
            return None
        return candidate

    def list_since(self, since_id: int) -> list[Message]:
        with self._lock:
            return [m for m in self._messages if m.id > since_id]

    def latest_id(self) -> int:
        with self._lock:
            return self._messages[-1].id if self._messages else 0

    def cleanup(self) -> None:
        """Wipe all messages and attachment files — called when the server stops."""
        with self._lock:
            self._messages.clear()
        shutil.rmtree(self.attachments_dir, ignore_errors=True)


def sanitize_display_name(name: str) -> str:
    """Keep sender names short and free of anything that'd break rendering."""
    name = (name or "").strip()
    name = "".join(ch for ch in name if ch.isprintable())[:40]
    return name or "Anonymous"

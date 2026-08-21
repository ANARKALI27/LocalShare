"""
Background HTTP server lifecycle management.

Runs uvicorn inside a daemon thread. The GUI thread calls start()/stop()
and gets back immediately; uvicorn's event loop runs entirely off the
Qt event loop, so drag-and-drop and the rest of the UI stay responsive
while the server is serving transfers.
"""
from __future__ import annotations

import threading
import time

import uvicorn
from fastapi import FastAPI

from app.network.ip import find_available_port, get_lan_ip
from app.server.messages import MessageStore
from app.server.routes import build_router
from app.state import ShareManager


class ServerHandle:
    """
    Wraps a running (or stopped) uvicorn server instance.

    Usage:
        handle = ServerHandle(share_manager)
        handle.start()          # non-blocking, returns once the socket is listening
        handle.address          # "http://192.168.1.105:8765"
        handle.stop()           # blocks briefly until the thread exits
    """

    def __init__(self, share_manager: ShareManager, preferred_port: int = 8765) -> None:
        self.share_manager = share_manager
        self.preferred_port = preferred_port

        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.host: str | None = None
        self.port: int | None = None
        self.message_store: MessageStore | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> str | None:
        if not self.is_running or self.host is None:
            return None
        return f"http://{self.host}:{self.port}"

    def start(self, timeout: float = 5.0) -> str:
        """
        Start the server in a background thread. Blocks only until the
        socket is confirmed listening (typically milliseconds), not for
        the server's whole lifetime. Returns the resulting address.
        """
        if self.is_running:
            return self.address  # type: ignore[return-value]

        self.host = get_lan_ip()
        self.port = find_available_port(self.preferred_port)
        self.message_store = MessageStore()

        app = FastAPI(title="LocalShare")
        app.include_router(build_router(self.share_manager, self.message_store))

        config = uvicorn.Config(
            app,
            host="0.0.0.0",  # bind all interfaces so LAN clients can reach it
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        # Wait for uvicorn to actually be listening before returning,
        # so the GUI doesn't show an address that isn't live yet.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                break
            time.sleep(0.02)

        return self.address  # type: ignore[return-value]

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self.message_store is not None:
            self.message_store.cleanup()
        self._server = None
        self._thread = None
        self.host = None
        self.port = None
        self.message_store = None

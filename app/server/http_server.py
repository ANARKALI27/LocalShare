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
from app.server.auth import AccessControl
from app.server.messages import MessageStore
from app.server.transfers import TransferRegistry
from app.server.routes import build_router
from app.state import ShareManager
from app.transfer.resumable import ResumableUploadManager


class ServerHandle:
    """
    Wraps a running (or stopped) uvicorn server instance.

    Usage:
        handle = ServerHandle(share_manager, access_control)
        handle.start()          # non-blocking, returns once the socket is listening
        handle.address          # "http://192.168.1.105:8765"
        handle.stop()           # blocks briefly until the thread exits

    access_control is owned by the caller (the GUI), not created fresh
    here — PIN settings need to be configurable BEFORE Start Sharing is
    clicked, so this class just uses whatever state it's handed rather
    than resetting it on every start().
    """

    def __init__(
        self, share_manager: ShareManager, access_control: AccessControl, preferred_port: int = 8765
    ) -> None:
        self.share_manager = share_manager
        self.access_control = access_control
        self.preferred_port = preferred_port

        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.host: str | None = None
        self.port: int | None = None
        self.message_store: MessageStore | None = None
        self.resumable_manager: ResumableUploadManager | None = None
        self.transfer_registry: TransferRegistry | None = None

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
        self.resumable_manager = ResumableUploadManager()
        self.transfer_registry = TransferRegistry()

        app = FastAPI(title="LocalShare")
        app.include_router(
            build_router(
                self.share_manager, self.message_store, self.resumable_manager,
                self.access_control, self.transfer_registry,
            )
        )

        # Lazy import (see auth_middleware.py) — keeps that module
        # importable in environments without starlette/fastapi installed.
        from app.server.auth_middleware import build_auth_middleware_class

        app.add_middleware(build_auth_middleware_class(), access_control=self.access_control)

        config = uvicorn.Config(
            app,
            host="0.0.0.0",  # bind all interfaces so LAN clients can reach it
            port=self.port,
            log_level="warning",
            access_log=False,
            # Skip uvicorn's own logging.config.dictConfig setup. It
            # references formatter classes by dotted string path, which
            # fails to resolve inside a PyInstaller-frozen executable
            # ("Unable to configure formatter 'default'") even though
            # the identical code runs fine via `python main.py`. We
            # don't need colored console logging in a windowed app with
            # no visible console anyway.
            log_config=None,
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
        if self.resumable_manager is not None:
            self.resumable_manager.cleanup()
        self._server = None
        self._thread = None
        self.host = None
        self.port = None
        self.message_store = None
        self.resumable_manager = None
        self.transfer_registry = None

"""
WebDAV server, for people who specifically want Windows Explorer to
browse the share like a mapped network drive.

Honest limitations (see README for the full explanation):
  - Anonymous access only, permanently — Windows Explorer's WebDAV
    client refuses to send Basic-auth credentials over plain HTTP by
    default, so there's no reasonable way to add PIN/password
    protection here even now that the browser share supports it (see
    app/server/auth.py). If you need access control, use the browser
    share instead — WebDAV will never have it, by design, not because
    it hasn't been built yet.
  - Only shared FOLDERS appear over WebDAV, not individually-shared
    single files — WebDAV publishes filesystem roots, and there's no
    safe way to expose one file without exposing its whole parent
    folder alongside it.
  - Explorer's WebDAV client (the "WebClient" service) is well
    documented to work unreliably on any port other than 80 (the
    standard WebDAV/HTTP port) — this is a Windows client limitation,
    not something a server can configure around. Because of this, on
    Windows this server tries to bind port 80 by default, which
    requires running LocalShare elevated. Linux's native WebDAV clients
    (GVFS/Nautilus, Dolphin, davfs2) don't show the same documented
    restriction, so on Linux/macOS this uses a normal auto-picked port
    instead — no reason to require sudo for a limitation that appears
    to be Windows-specific. (This platform difference is reasoned from
    available documentation, not verified by direct testing on Linux —
    if WebDAV behaves oddly there, that's useful to know.)
  - Uses "cheroot" (a mature, production-grade WSGI server) rather
    than Python's built-in wsgiref: wsgiref replies with HTTP/1.0 and
    closes the connection after every response, and testing showed
    Explorer abandoning the connection after that first response
    (sending OPTIONS, getting a reply, then never following up with
    PROPFIND) — consistent with well-documented Windows WebDAV client
    quirks around persistent connections. cheroot serves proper
    HTTP/1.1 keep-alive, which is what wsgidav itself is built around.
  - Even with that fixed, Explorer's WebDAV client is slow to
    enumerate large folders and can time out on very large transfers.
    For big files, the browser share is the reliable path.

I could not runtime-test this against a real Windows Explorer client
in the environment that built this code — please verify the Map
Network Drive workflow on your actual machines (see README).
"""
from __future__ import annotations

import platform
import threading

from app.network.ip import find_available_port, get_lan_ip
from app.state import ShareManager

# On Windows, Explorer's WebDAV client needs port 80 specifically (see
# module docstring). Elsewhere, use the normal "pick any free port"
# behavior — 0 here is a sentinel meaning "auto", not a literal port.
_IS_WINDOWS = platform.system() == "Windows"
DEFAULT_WEBDAV_PORT = 80 if _IS_WINDOWS else 0


class WebDavHandle:
    """
    Mirrors ServerHandle's start()/stop()/is_running/address shape, so
    the GUI can treat both servers the same way.
    """

    def __init__(self, share_manager: ShareManager, preferred_port: int = DEFAULT_WEBDAV_PORT) -> None:
        self.share_manager = share_manager
        self.preferred_port = preferred_port

        self._server = None  # cheroot.wsgi.Server instance, once started
        self._thread: threading.Thread | None = None
        self.host: str | None = None
        self.port: int | None = None
        self._subscribed = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> str | None:
        if not self.is_running or self.host is None:
            return None
        return f"http://{self.host}:{self.port}"

    @property
    def explorer_path(self) -> str | None:
        """
        The connection string to paste into the OS's native file
        manager to mount this share — Explorer's "Map Network Drive"
        UNC format on Windows, or a dav:// URI (GVFS/Nautilus, Dolphin)
        on Linux/macOS.
        """
        if not self.is_running:
            return None
        if _IS_WINDOWS:
            # @port is only included for non-standard ports; omitting it
            # on port 80 matches the conventional WebDAV UNC format and
            # avoids giving Explorer one more thing to potentially choke on.
            if self.port == 80:
                return f"\\\\{self.host}\\DavWWWRoot"
            return f"\\\\{self.host}@{self.port}\\DavWWWRoot"
        return f"dav://{self.host}:{self.port}/"

    def _build_provider_mapping(self) -> dict[str, str]:
        """
        Map each shared FOLDER to a WebDAV share path like "/MyFolder".
        Single shared files are intentionally excluded (see module
        docstring). Names are de-duplicated by suffixing the item id
        if two shared folders happen to have the same name.
        """
        mapping: dict[str, str] = {}
        seen_names: set[str] = set()
        for item in self.share_manager.all_items():
            if not item.is_dir or not item.exists:
                continue
            safe_name = item.name.replace("/", "_").replace("\\", "_") or "folder"
            key_name = safe_name
            if key_name in seen_names:
                key_name = f"{safe_name}_{item.id}"
            seen_names.add(key_name)
            mapping[f"/{key_name}"] = item.path
        return mapping

    def start(self, timeout: float = 5.0) -> str:
        if self.is_running:
            return self.address  # type: ignore[return-value]

        mapping = self._build_provider_mapping()
        if not mapping:
            raise RuntimeError(
                "No shared folders to publish over WebDAV yet. "
                "(Only folders can be shared this way — individual files aren't supported "
                "over WebDAV; share them via the browser link instead.)"
            )

        # Lazy import: keeps the rest of the app working even if wsgidav
        # or cheroot isn't installed, and gives a clear error message if so.
        try:
            from wsgidav.wsgidav_app import WsgiDAVApp
        except ImportError as exc:
            raise RuntimeError(
                'WebDAV requires the "wsgidav" package. Install it with: pip install wsgidav'
            ) from exc

        try:
            from cheroot.wsgi import Server as CherootWSGIServer
        except ImportError as exc:
            raise RuntimeError(
                'WebDAV requires the "cheroot" package for a properly persistent HTTP/1.1 '
                "connection (Windows Explorer's WebDAV client needs this). "
                "Install it with: pip install cheroot"
            ) from exc

        self.host = get_lan_ip()
        # preferred_port == 0 is the "auto-pick" sentinel (used on
        # non-Windows platforms — see DEFAULT_WEBDAV_PORT above).
        self.port = (
            find_available_port(8766) if self.preferred_port == 0 else self.preferred_port
        )

        config = {
            "host": self.host,
            "port": self.port,
            "provider_mapping": mapping,
            # "*": True = anonymous access allowed for every share not
            # explicitly listed otherwise. See module docstring for why
            # we don't attempt PIN/credential protection here.
            "simple_dc": {"user_mapping": {"*": True}},
            "verbose": 1,
            "logging": {"enable_loggers": []},
        }
        app = WsgiDAVApp(config)

        self._server = CherootWSGIServer((self.host, self.port), app, numthreads=10)
        attempted_port = self.port  # save before we clear it below, for accurate error messages
        try:
            self._server.prepare()  # binds the socket; raises here on permission/port conflicts
        except PermissionError:
            self._server = None
            self.host = None
            self.port = None
            if _IS_WINDOWS:
                raise RuntimeError(
                    f"Couldn't bind port {attempted_port} (needed because Windows Explorer's "
                    "WebDAV client is unreliable on non-standard ports). Close whatever else might "
                    "be using it (IIS, Skype, another web server) and restart LocalShare elevated "
                    "— run your terminal itself \"as administrator\" and launch main.py from there. "
                    "If you'd rather not run elevated, the browser share above works without any "
                    "special privileges."
                )
            raise RuntimeError(
                f"Couldn't bind port {attempted_port}: permission denied. "
                "This is unexpected on this platform — the browser share above works "
                "without any special privileges either way."
            )
        except OSError as exc:
            self._server = None
            self.host = None
            self.port = None
            raise RuntimeError(
                f"Couldn't start the WebDAV server on port {attempted_port}: {exc}. "
                "Something else may already be using this port."
            )

        self._thread = threading.Thread(target=self._server.serve, daemon=True)
        self._thread.start()

        if not self._subscribed:
            self.share_manager.on_change(self._on_shares_changed)
            self._subscribed = True

        return self.address  # type: ignore[return-value]

    def _on_shares_changed(self) -> None:
        """
        wsgidav's provider mapping is fixed at app construction time, so
        adding/removing a shared folder while WebDAV is running requires
        a quick restart to pick up the change. This causes a brief
        (sub-second) interruption for anyone actively browsing via
        Explorer — an accepted trade-off for keeping this feature simple.
        """
        if self.is_running:
            try:
                self.start_after_restart()
            except RuntimeError:
                # e.g. the last shared folder was just removed — stop cleanly
                self.stop()

    def start_after_restart(self) -> str:
        preferred = self.port or self.preferred_port
        self.stop()
        self.preferred_port = preferred
        return self.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self.host = None
        self.port = None

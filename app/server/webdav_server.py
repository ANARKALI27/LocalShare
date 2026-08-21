"""
WebDAV server, for people who specifically want Windows Explorer to
browse the share like a mapped network drive.

Honest limitations (see README for the full explanation):
  - Anonymous access only. Windows Explorer's WebDAV client refuses to
    send Basic-auth credentials over plain HTTP by default, so a PIN
    can't be enforced here the way it can for the browser UI. If you
    need access control, use the browser share with a PIN instead.
  - Only shared FOLDERS appear over WebDAV, not individually-shared
    single files — WebDAV publishes filesystem roots, and there's no
    safe way to expose one file without exposing its whole parent
    folder alongside it.
  - Explorer's WebDAV client (the "WebClient" service) is well
    documented to work unreliably on any port other than 80 (the
    standard WebDAV/HTTP port) — this is a Windows client limitation,
    not something a server can configure around. Because of this, this
    server tries to bind port 80 by default, which requires running
    LocalShare as Administrator on Windows. If it can't get port 80
    (not running as admin, or something else is using it — IIS, Skype,
    etc. sometimes do), it fails with a clear error rather than
    silently falling back to a port that Explorer likely won't accept
    reliably.
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

import threading

from app.network.ip import get_lan_ip
from app.state import ShareManager

# The standard WebDAV/HTTP port. Windows Explorer's built-in WebDAV
# client is documented to work unreliably on any other port, so we
# deliberately do NOT auto-pick an alternate port the way the main
# HTTP server does — a WebDAV server on a non-standard port would
# "work" from Python's side while still failing in Explorer, which is
# a worse experience than a clear upfront error.
DEFAULT_WEBDAV_PORT = 80


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
        """The string to paste into Explorer's 'Map Network Drive' -> 'Connect to a website' dialog."""
        if not self.is_running:
            return None
        # @port is only included for non-standard ports; omitting it on
        # port 80 matches the conventional WebDAV UNC format and avoids
        # giving Explorer one more thing to potentially choke on.
        if self.port == 80:
            return f"\\\\{self.host}\\DavWWWRoot"
        return f"\\\\{self.host}@{self.port}\\DavWWWRoot"

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
        self.port = self.preferred_port

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
        try:
            self._server.prepare()  # binds the socket; raises here on permission/port conflicts
        except PermissionError:
            self._server = None
            self.host = None
            self.port = None
            raise RuntimeError(
                f"Couldn't bind port {self.preferred_port} (needed because Windows Explorer's "
                "WebDAV client is unreliable on non-standard ports). Close whatever else might be "
                "using it (IIS, Skype, another web server) and restart LocalShare as Administrator "
                "— run your terminal itself \"as administrator\" and launch main.py from there. "
                "If you'd rather not run as admin, the browser share above works without any "
                "special privileges."
            )
        except OSError as exc:
            self._server = None
            self.host = None
            self.port = None
            raise RuntimeError(
                f"Couldn't start the WebDAV server on port {self.preferred_port}: {exc}. "
                "Something else may already be using this port — check for IIS, Skype, or "
                "another local web server."
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

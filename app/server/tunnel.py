"""
Internet sharing via Cloudflare Quick Tunnel.

This is what makes "Local Network + Internet" mode reachable from
outside your Wi-Fi: cloudflared opens an outbound connection from your
machine to Cloudflare's edge network and hands back a public HTTPS URL
("Quick Tunnel," e.g. https://random-words.trycloudflare.com) that
forwards to your local server. No port forwarding, no router
configuration, and — unlike the ngrok-based version this replaced —
no account or signup at all.

Requires the "cloudflared" program to be installed and on PATH. This
is Cloudflare's own binary, not a Python package — there's no
pip-installable wrapper managing it automatically the way pyngrok did
for ngrok, so start() checks for it explicitly and gives install
instructions if it's missing.

Honest limitations, straight from Cloudflare's own documentation:
  - Quick Tunnels are explicitly labeled "for testing and development,
    not production" — capped at 200 concurrent in-flight requests.
  - The URL is temporary: a new one is generated every time sharing
    starts, and it stops working the moment sharing stops.
  - Some real-world reports describe it as less consistently reliable
    than ngrok's infrastructure — worth knowing if a share needs to
    stay up reliably for a while.

I could not test any part of this end-to-end — no network access to
install cloudflared or observe its actual output in the environment
that wrote this code. The URL-parsing pattern below is based on
cloudflared's documented log format, not direct observation.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading

_TRYCLOUDFLARE_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

_INSTALL_INSTRUCTIONS = {
    "Windows": (
        "cloudflared isn't installed. Install it (free, no account needed) with:\n"
        "  winget install --id Cloudflare.cloudflared\n"
        "or download it directly from:\n"
        "  https://github.com/cloudflare/cloudflared/releases/latest\n"
        "Restart LocalShare after installing."
    ),
    "Linux": (
        "cloudflared isn't installed. Install it (free, no account needed) — see:\n"
        "  https://pkg.cloudflare.com/index.html\n"
        "or download the binary directly from:\n"
        "  https://github.com/cloudflare/cloudflared/releases/latest\n"
        "Restart LocalShare after installing."
    ),
    "Darwin": (
        "cloudflared isn't installed. Install it (free, no account needed) with:\n"
        "  brew install cloudflared\n"
        "Restart LocalShare after installing."
    ),
}


def _find_cloudflared() -> str | None:
    """
    Looks for cloudflared on PATH first, then falls back to checking
    known install locations directly. This matters because a package
    manager (winget, apt, etc.) updates PATH for new processes, but an
    already-running app — or one launched from a desktop session that
    hasn't refreshed its environment — won't see that update until
    it's restarted. Checking the actual install location directly
    catches "just installed, but this process hasn't refreshed yet."
    """
    found = shutil.which("cloudflared")
    if found:
        return found

    candidates: list[str] = []
    if platform.system() == "Windows":
        # The Windows installer downloads cloudflared.exe directly
        # alongside LocalShare.exe itself during setup (see
        # localshare_setup.iss + download_cloudflared.ps1) — check
        # there first. Deliberately os.path.dirname(sys.executable),
        # NOT app_root(): for a PyInstaller onefile build, app_root()
        # resolves to sys._MEIPASS, a TEMPORARY per-run extraction
        # folder, not the real install directory the installer wrote
        # into. sys.executable is the actual running .exe's own path,
        # which is what "{app}" meant during installation.
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), "cloudflared.exe"))
        # winget's "Links" folder is a stable, version-independent
        # location it maintains specifically so other tools can find
        # what it installs without needing PATH to be refreshed.
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            candidates.append(
                os.path.join(localappdata, "Microsoft", "WinGet", "Links", "cloudflared.exe")
            )
    else:
        candidates.extend(["/usr/local/bin/cloudflared", "/usr/bin/cloudflared"])

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


class TunnelHandle:
    def __init__(self) -> None:
        self.public_url: str | None = None
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, local_port: int, timeout: float = 30.0) -> str:
        """
        Launches cloudflared and waits for it to report the public
        URL. Raises RuntimeError with a clear, actionable message if
        cloudflared isn't installed, or if it doesn't produce a URL
        within `timeout` seconds.
        """
        if self.is_running:
            return self.public_url  # type: ignore[return-value]

        cloudflared_path = _find_cloudflared()
        if not cloudflared_path:
            raise RuntimeError(
                _INSTALL_INSTRUCTIONS.get(
                    platform.system(),
                    "cloudflared isn't installed. Get it (free, no account needed) from:\n"
                    "https://github.com/cloudflare/cloudflared/releases/latest",
                )
                + "\n\nAlready installed it? Fully close and reopen LocalShare — a "
                "just-installed program sometimes isn't visible to an app that was "
                "already running before the install finished."
            )

        popen_kwargs = {}
        if platform.system() == "Windows":
            # Without this, launching a console app (cloudflared.exe)
            # from this windowed GUI app (which has no console of its
            # own) causes Windows to auto-allocate a NEW visible
            # console window for it — that's the "terminal window"
            # that was appearing. Closing that window kills the
            # process running inside it, which is exactly why the
            # tunnel died (and anyone using the link got Cloudflare's
            # error 1033 — "tunnel unavailable") when it was closed.
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            process = subprocess.Popen(
                [cloudflared_path, "tunnel", "--url", f"http://localhost:{local_port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **popen_kwargs,
            )
        except OSError as exc:
            raise RuntimeError(f"Couldn't start cloudflared: {exc}") from exc

        found_url: list[str] = []
        got_url = threading.Event()

        def _read_output() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                if not found_url:
                    match = _TRYCLOUDFLARE_URL_PATTERN.search(line)
                    if match:
                        found_url.append(match.group(0))
                        got_url.set()
                # keep draining regardless, so the subprocess's stdout
                # pipe never fills up and blocks cloudflared once
                # we've stopped actively looking for the URL line

        reader = threading.Thread(target=_read_output, daemon=True)
        reader.start()

        got_url.wait(timeout=timeout)

        if not found_url:
            process.terminate()
            raise RuntimeError(
                f"cloudflared didn't report a public URL within {int(timeout)} seconds. "
                "It may still be starting, or something's blocking outbound connections "
                "on this network. You can sanity-check it by running the same command "
                "directly in a terminal: cloudflared tunnel --url "
                f"http://localhost:{local_port}"
            )

        self._process = process
        self._reader_thread = reader
        self.public_url = found_url[0]
        return self.public_url

    def stop(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
        self._reader_thread = None
        self.public_url = None

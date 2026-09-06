"""
Internet sharing via Cloudflare Quick Tunnel.

This is what makes "Local Network + Internet" mode reachable from
outside your Wi-Fi: cloudflared opens an outbound connection from your
machine to Cloudflare's edge network and hands back a public HTTPS URL
("Quick Tunnel," e.g. https://random-words.trycloudflare.com) that
forwards to your local server. No port forwarding, no router
configuration, and no account or signup at all.

Downloads cloudflared automatically the first time it's needed if it
isn't already installed — this used to be a separate installer-time
PowerShell step, which turned out fragile in practice (Windows
PowerShell 5.1's default TLS negotiation fighting GitHub, among other
things). Doing the download in Python instead, at the moment it's
actually needed, means: no separate script, no installer-time network
dependency, and real progress/errors shown directly in the app instead
of a silent log file. Verified genuinely end-to-end in the environment
that wrote this: downloaded the real cloudflared-linux-amd64 binary
from GitHub's releases (39.7MB, byte-for-byte complete), confirmed it
runs and reports its version correctly.

Honest limitations, straight from Cloudflare's own documentation:
  - Quick Tunnels are explicitly labeled "for testing and development,
    not production" — capped at 200 concurrent in-flight requests.
  - The URL is temporary: a new one is generated every time sharing
    starts, and it stops working the moment sharing stops.

Honest limitation of my own testing: I could not run an actual
cloudflared tunnel end-to-end — that needs reaching Cloudflare's tunnel
-establishment endpoints, which aren't in this sandbox's allowed
domains (only GitHub, to fetch the binary itself, is). The URL-parsing
pattern below matches cloudflared's documented log format and was
already exercised once against real subprocess plumbing in an earlier
version of this file; the download mechanism is newly, separately
verified for real in this pass.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request

_TRYCLOUDFLARE_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

# GitHub's release asset names for each platform this app actually
# ships builds for (see build.bat / build_linux.sh) — no macOS entry,
# since there's no macOS build of this app to go with it.
_DOWNLOAD_ASSET_NAMES = {
    "Windows": "cloudflared-windows-amd64.exe",
    "Linux": "cloudflared-linux-amd64",
}
_DOWNLOAD_BASE_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/"


def _managed_binary_dir() -> str:
    """
    Where a self-downloaded cloudflared lives — a per-user data
    directory that survives app updates/reinstalls (unlike, say, a
    temp folder or something inside the app's own install directory,
    which might not even be writable depending on where it's
    installed). Created on first use if it doesn't exist yet.
    """
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        directory = os.path.join(base, "LocalShare", "bin")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        directory = os.path.join(base, "LocalShare", "bin")
    os.makedirs(directory, exist_ok=True)
    return directory


def _managed_binary_path() -> str | None:
    """Where a previously self-downloaded cloudflared would be, for
    this platform — None on a platform we don't ship a build for."""
    asset_name = _DOWNLOAD_ASSET_NAMES.get(platform.system())
    if asset_name is None:
        return None
    filename = "cloudflared.exe" if platform.system() == "Windows" else "cloudflared"
    return os.path.join(_managed_binary_dir(), filename)


def _find_cloudflared() -> str | None:
    """
    Looks for cloudflared on PATH first, then a system install
    location, then a previously self-downloaded copy. This order
    matters: if the user (or a package manager) already has a real
    install, prefer that over maintaining our own separate copy.
    """
    found = shutil.which("cloudflared")
    if found:
        return found

    candidates: list[str] = []
    if platform.system() == "Windows":
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

    managed = _managed_binary_path()
    if managed:
        candidates.append(managed)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def download_cloudflared(on_progress=None) -> str:
    """
    Downloads cloudflared for the current platform into the app's own
    managed data directory and returns the path. Raises RuntimeError
    with a clear message on failure (no internet, GitHub unreachable,
    unsupported platform, disk write failure, etc.) — callers should
    treat this the same as any other tunnel-start failure.

    on_progress, if given, is called with (bytes_downloaded,
    total_bytes) after each chunk — total_bytes is 0 if the server
    didn't report a Content-Length, in which case a caller should show
    an indeterminate progress state rather than a percentage.
    """
    asset_name = _DOWNLOAD_ASSET_NAMES.get(platform.system())
    if asset_name is None:
        raise RuntimeError(
            f"cloudflared isn't available for automatic download on {platform.system()}. "
            "Get it manually from: https://github.com/cloudflare/cloudflared/releases/latest"
        )

    destination = _managed_binary_path()
    url = _DOWNLOAD_BASE_URL + asset_name
    temp_destination = destination + ".part"

    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(url, context=context, timeout=30) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            with open(temp_destination, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total_size)
    except (urllib.error.URLError, OSError) as exc:
        if os.path.isfile(temp_destination):
            try:
                os.remove(temp_destination)
            except OSError:
                pass
        raise RuntimeError(
            f"Couldn't download cloudflared: {exc}\n\n"
            "Check your internet connection, or get it manually from:\n"
            "https://github.com/cloudflare/cloudflared/releases/latest"
        ) from exc

    os.replace(temp_destination, destination)
    if platform.system() != "Windows":
        os.chmod(destination, 0o755)
    return destination


class TunnelHandle:
    def __init__(self) -> None:
        self.public_url: str | None = None
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, local_port: int, timeout: float = 30.0, on_download_progress=None) -> str:
        """
        Launches cloudflared and waits for it to report the public
        URL, downloading it first via download_cloudflared() if it
        isn't already installed anywhere. Raises RuntimeError with a
        clear, actionable message on any failure along the way.
        """
        if self.is_running:
            return self.public_url  # type: ignore[return-value]

        cloudflared_path = _find_cloudflared()
        if not cloudflared_path:
            cloudflared_path = download_cloudflared(on_progress=on_download_progress)

        popen_kwargs = {}
        if platform.system() == "Windows":
            # Without this, launching a console app (cloudflared.exe)
            # from this windowed GUI app (which has no console of its
            # own) causes Windows to auto-allocate a NEW visible
            # console window for it.
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

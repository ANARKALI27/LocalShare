"""
Update checking: compares this app's version against another running
LocalShare instance's version (queried over the network) and reports
whether a newer one is available. Also supports finding and
downloading an installer file the other instance happens to be
sharing (matched by filename — see routes.py's /api/latest-build).

Deliberately does NOT attempt to replace the running exe's own files
directly — that requires carefully choreographing around Windows
locking the file of a running executable, which isn't something to
ship without being able to test on real Windows. Instead, once a new
installer is downloaded, it's handed to the OS's own "open with
default app" mechanism — the official Inno Setup installer (Windows)
or package manager (Linux) then does the actual replacing, using
mechanisms that are already built and tested for exactly this.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import urllib.error
import urllib.request


def normalize_address(address: str) -> str:
    """Adds a scheme if the user typed a bare host:port, and strips trailing slashes."""
    address = address.strip().rstrip("/")
    if not address:
        return address
    if not address.startswith("http://") and not address.startswith("https://"):
        address = "http://" + address
    return address


def compare_versions(v1: str, v2: str) -> int:
    """
    Compares two dotted version strings numerically, segment by segment
    (so "1.10.0" is correctly greater than "1.9.0" — a naive string
    comparison would get this backwards). Returns -1 if v1 < v2, 0 if
    equal, 1 if v1 > v2. Shorter versions are padded with zeros
    ("1.2" == "1.2.0"). Falls back to string comparison if a segment
    isn't a plain integer, rather than crashing on an unexpected format.
    """

    def parse(v: str) -> list:
        segments = v.strip().split(".")
        parsed = []
        for seg in segments:
            try:
                parsed.append(int(seg))
            except ValueError:
                parsed.append(seg)  # non-numeric segment (e.g. "1.0.0-beta") — compare as-is
        return parsed

    p1, p2 = parse(v1), parse(v2)
    length = max(len(p1), len(p2))
    p1 += [0] * (length - len(p1))
    p2 += [0] * (length - len(p2))

    for a, b in zip(p1, p2):
        if type(a) is not type(b):
            a, b = str(a), str(b)  # avoid TypeError comparing int to str
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


class UpdateCheckResult:
    def __init__(
        self,
        ok: bool,
        error: str | None = None,
        remote_version: str | None = None,
        is_newer: bool = False,
    ) -> None:
        self.ok = ok
        self.error = error
        self.remote_version = remote_version
        self.is_newer = is_newer


def check_for_update(address: str, current_version: str, timeout: float = 5.0) -> UpdateCheckResult:
    """
    Queries another LocalShare instance's /api/version endpoint and
    compares it to `current_version`. Never raises — network errors,
    timeouts, and unexpected responses all come back as a
    non-ok UpdateCheckResult with a human-readable error message.
    """
    normalized = normalize_address(address)
    if not normalized:
        return UpdateCheckResult(ok=False, error="Enter an address first (e.g. 192.168.1.104:8765)")

    url = f"{normalized}/api/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return UpdateCheckResult(ok=False, error=f"Couldn't reach {normalized}: {exc.reason}")
    except TimeoutError:
        return UpdateCheckResult(ok=False, error=f"Timed out reaching {normalized}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return UpdateCheckResult(
            ok=False, error=f"{normalized} responded, but not with valid version info"
        )

    remote_version = data.get("version")
    if not remote_version:
        return UpdateCheckResult(ok=False, error=f"{normalized} didn't report a version")

    is_newer = compare_versions(remote_version, current_version) > 0
    return UpdateCheckResult(ok=True, remote_version=remote_version, is_newer=is_newer)


class LatestBuildResult:
    def __init__(self, available: bool, name: str | None = None, download_url: str | None = None) -> None:
        self.available = available
        self.name = name
        self.download_url = download_url


def find_latest_build(address: str, timeout: float = 5.0) -> LatestBuildResult:
    """
    Asks the other instance whether it's sharing something that looks
    like a LocalShare installer (see routes.py's /api/latest-build).
    Never raises — any failure just comes back as "not available"
    rather than surfacing a separate error, since this is a bonus on
    top of the version check, not something that should itself block
    reporting "yes, an update exists."
    """
    normalized = normalize_address(address)
    if not normalized:
        return LatestBuildResult(available=False)

    try:
        with urllib.request.urlopen(f"{normalized}/api/latest-build", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return LatestBuildResult(available=False)

    if not data.get("available"):
        return LatestBuildResult(available=False)

    return LatestBuildResult(
        available=True, name=data.get("name"), download_url=data.get("download_url")
    )


def download_build(address: str, download_url: str, filename: str, timeout: float = 30.0) -> str:
    """
    Streams the installer file to a temp directory. Returns the local
    path it was saved to. Raises RuntimeError with a clear message on
    any failure — caller (a background thread) is expected to catch
    this and report it rather than let it propagate raw.
    """
    normalized = normalize_address(address)
    url = f"{normalized}{download_url}"

    dest_dir = tempfile.mkdtemp(prefix="localshare_update_")
    dest_path = os.path.join(dest_dir, filename)

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(dest_path, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)  # 1MB at a time — same chunking discipline as the rest of the app
                if not chunk:
                    break
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Couldn't download the update: {exc}") from exc

    return dest_path


def open_with_default_app(path: str) -> None:
    """
    Hands the downloaded file to the OS's own "open with default app"
    mechanism — the Inno Setup installer on Windows, or the desktop's
    package-manager GUI on Linux for a .deb. This is the actual "install"
    step, and it's mechanisms that are already built and tested for
    exactly this, not something invented here.
    """
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: S606 — the standard, correct way to do this on Windows
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

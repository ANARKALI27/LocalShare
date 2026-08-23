"""
Update checking: compares this app's version against another running
LocalShare instance's version (queried over the network) and reports
whether a newer one is available.

Deliberately does NOT attempt to download-and-replace the running exe
automatically — that requires carefully choreographing around Windows
locking the file of a running executable, which isn't something to
ship without being able to test on real Windows. Instead this points
the person to the existing, already-reliable file-sharing mechanism to
grab the new build.
"""
from __future__ import annotations

import json
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

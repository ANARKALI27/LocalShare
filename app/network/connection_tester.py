"""
Verifies a discovered device's LocalShare server is actually
reachable — a device can show up in discovery (it's on the network and
broadcasting) while its actual HTTP server is down, unreachable due to
AP/client isolation, or blocked by a firewall rule that specifically
targets TCP but not the UDP discovery port. Marking a device "online"
purely because a discovery packet arrived would be actively misleading
in exactly those cases — this hits the real server instead to confirm.

Pure stdlib (urllib), no new dependency — this is a single lightweight
GET request with a short timeout, not worth pulling in requests/httpx
for.
"""
from __future__ import annotations

import urllib.error
import urllib.request


def test_connection(ip: str, port: int, timeout: float = 3.0) -> bool:
    """
    True if the device's /ping endpoint responds successfully within
    the timeout. /ping is deliberately the target — it's exempt from
    PIN protection (see auth_middleware.py), so this reports "is the
    server actually up" independent of whether it's PIN-locked, which
    is the right question for "is this device online," not "can I
    access its files."
    """
    url = f"http://{ip}:{port}/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False

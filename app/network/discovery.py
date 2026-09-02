"""
Pure logic for LAN device discovery — building/parsing the UDP
announcement packets LocalShare instances broadcast to find each
other, and tracking which devices have been seen recently. No socket
I/O here at all, deliberately, so this can be tested thoroughly
before trusting it with real network traffic (which can include
garbage/malformed packets from anything else on the network, not just
other LocalShare instances).
"""
from __future__ import annotations

import json
import time

DISCOVERY_PORT = 53317  # arbitrary, chosen to avoid common well-known ports
STALE_AFTER_SECONDS = 30  # a device not heard from in this long is considered gone


def build_announcement(device_id: str, name: str, address: str, version: str) -> bytes:
    """Serializes this instance's announcement to broadcast. device_id
    is a random per-launch identifier (not tied to hardware) — lets a
    listener recognize and ignore its OWN broadcast without needing
    to compare IP addresses, which get confusing with multiple network
    interfaces/VPNs."""
    payload = {
        "app": "LocalShare",
        "device_id": device_id,
        "name": name,
        "address": address,
        "version": version,
    }
    return json.dumps(payload).encode("utf-8")


def parse_announcement(data: bytes) -> dict | None:
    """
    Parses an incoming announcement. Returns None (never raises) for
    anything malformed or not actually a LocalShare announcement —
    the discovery port will inevitably see garbage from other
    software or malformed/truncated packets, and that must never
    crash the listener.
    """
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("app") != "LocalShare":
        return None
    required = ("device_id", "name", "address", "version")
    if not all(isinstance(payload.get(k), str) and payload.get(k) for k in required):
        return None
    return {k: payload[k] for k in required}


class DeviceRegistry:
    """Tracks devices seen via discovery announcements, with
    staleness-based pruning — a device that's gone quiet (closed the
    app, left the network) should disappear from the list rather than
    linger forever as a stale, misleading entry."""

    def __init__(self) -> None:
        self._devices: dict[str, dict] = {}  # device_id -> {name, address, version, last_seen}

    def see(self, device_id: str, name: str, address: str, version: str, now: float | None = None) -> None:
        self._devices[device_id] = {
            "name": name,
            "address": address,
            "version": version,
            "last_seen": now if now is not None else time.time(),
        }

    def active_devices(self, now: float | None = None, stale_after: float = STALE_AFTER_SECONDS) -> list[dict]:
        """Returns currently-active devices (seen within stale_after
        seconds), sorted by name, WITHOUT mutating internal state —
        pruning of genuinely-gone entries happens separately in
        prune(), keeping this method a pure, side-effect-free query."""
        current_time = now if now is not None else time.time()
        active = [
            {"device_id": did, **info}
            for did, info in self._devices.items()
            if current_time - info["last_seen"] <= stale_after
        ]
        return sorted(active, key=lambda d: d["name"].lower())

    def prune(self, now: float | None = None, stale_after: float = STALE_AFTER_SECONDS) -> None:
        """Actually removes stale entries from internal storage —
        called periodically so the registry doesn't grow forever with
        devices that came and went long ago."""
        current_time = now if now is not None else time.time()
        self._devices = {
            did: info for did, info in self._devices.items()
            if current_time - info["last_seen"] <= stale_after
        }

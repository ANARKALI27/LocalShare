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

# Broadcasts go out roughly every 5s (see discovery_service.py), so:
# - ONLINE: missed at most one or two broadcasts — still solidly present
# - OFFLINE (grace period): missed several in a row, but not so long that
#   it's clearly gone — shown as "Offline, last seen Ns ago" rather than
#   vanishing, so a brief network hiccup doesn't make cards flicker
#   in and out of the list
# - Anything older than OFFLINE_REMOVE_AFTER_SECONDS is pruned entirely
ONLINE_WITHIN_SECONDS = 15
OFFLINE_REMOVE_AFTER_SECONDS = 60


def build_announcement(
    device_code: str, name: str, ip: str, port: int, version: str, capabilities: list[str] | None = None,
) -> bytes:
    """
    Serializes this instance's announcement to broadcast. device_code
    is the PERSISTENT per-installation identity (see device_identity.py)
    — not a per-launch random value — specifically so a listener can
    recognize "this is the same device I saw yesterday" across
    restarts, IP changes, and network switches. Also lets a listener
    recognize and ignore its OWN broadcast without needing to compare
    IP addresses, which get confusing with multiple network
    interfaces/VPNs.
    """
    payload = {
        "app": "LocalShare",
        "device_code": device_code,
        "name": name,
        "ip": ip,
        "port": port,
        "version": version,
        "capabilities": capabilities or [],
    }
    return json.dumps(payload).encode("utf-8")


def parse_announcement(data: bytes) -> dict | None:
    """
    Parses an incoming announcement. Returns None (never raises) for
    anything malformed or not actually a LocalShare announcement —
    the discovery port will inevitably see garbage from other
    software or malformed/truncated packets, and that must never
    crash the listener. Deliberately strict about what's accepted:
    this is unauthenticated data from the network, and the only things
    ever advertised are the basic identity/address fields below — never
    file paths, credentials, or anything else that could matter if
    spoofed (see the project README's security notes for more).
    """
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("app") != "LocalShare":
        return None

    device_code = payload.get("device_code")
    name = payload.get("name")
    ip = payload.get("ip")
    port = payload.get("port")
    version = payload.get("version")

    if not isinstance(device_code, str) or not device_code.startswith("LS-"):
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(ip, str) or not ip:
        return None
    if not isinstance(port, int) or not (0 < port < 65536):
        return None
    if not isinstance(version, str) or not version:
        return None

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
        capabilities = []

    return {
        "device_code": device_code, "name": name, "ip": ip,
        "port": port, "version": version, "capabilities": capabilities,
    }


class DeviceRegistry:
    """
    Tracks devices seen via discovery announcements, keyed by their
    persistent device_code (not IP — the IP is expected to change
    over the same device's lifetime, per the whole point of having a
    persistent code at all). Devices move through three states as time
    passes without a fresh announcement: online, offline (grace
    period — still shown, not yet removed), then pruned entirely.
    """

    def __init__(self) -> None:
        self._devices: dict[str, dict] = {}  # device_code -> {name, ip, port, version, capabilities, last_seen}

    def see(
        self, device_code: str, name: str, ip: str, port: int, version: str,
        capabilities: list[str] | None = None, now: float | None = None,
    ) -> None:
        self._devices[device_code] = {
            "name": name,
            "ip": ip,
            "port": port,
            "version": version,
            "capabilities": capabilities or [],
            "last_seen": now if now is not None else time.time(),
        }

    def known_devices(self, now: float | None = None) -> list[dict]:
        """
        Every device not yet pruned, each annotated with an "online"
        boolean and "seconds_since_seen" — the UI decides how to
        render each state, this just reports it. Sorted by name, then
        online-first, so the list doesn't visually reshuffle every
        tick as devices' online/offline status flips.
        """
        current_time = now if now is not None else time.time()
        result = []
        for code, info in self._devices.items():
            elapsed = current_time - info["last_seen"]
            if elapsed > OFFLINE_REMOVE_AFTER_SECONDS:
                continue
            result.append({
                "device_code": code,
                **info,
                "online": elapsed <= ONLINE_WITHIN_SECONDS,
                "seconds_since_seen": elapsed,
            })
        return sorted(result, key=lambda d: (not d["online"], d["name"].lower()))

    def prune(self, now: float | None = None) -> None:
        """Actually removes long-gone entries from internal storage —
        called periodically so the registry doesn't grow forever with
        devices that came and went long ago. Separate from
        known_devices() so that method stays a pure, side-effect-free
        query."""
        current_time = now if now is not None else time.time()
        self._devices = {
            code: info for code, info in self._devices.items()
            if current_time - info["last_seen"] <= OFFLINE_REMOVE_AFTER_SECONDS
        }

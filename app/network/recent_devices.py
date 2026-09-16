"""
Tracks devices the user has successfully connected to (via LAN or
Global lookup) for quick reconnect — a plain list of {device_code,
name}, most-recent-first, persisted via QSettings. Deliberately does
NOT cache an address/tunnel URL alongside each entry: a recent
device's connection info can genuinely change between visits (new LAN
IP, new tunnel URL), so "reconnecting" to a recent device re-runs the
normal lookup with that device's code rather than reusing a
potentially-stale cached address.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings

MAX_RECENT_DEVICES = 10
_SETTINGS_KEY = "recent_devices"


def _load() -> list[dict]:
    raw = QSettings("LocalShare", "LocalShare").value(_SETTINGS_KEY, "[]", type=str)
    try:
        devices = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(devices, list):
        return []
    return [d for d in devices if isinstance(d, dict) and "device_code" in d]


def _save(devices: list[dict]) -> None:
    QSettings("LocalShare", "LocalShare").setValue(_SETTINGS_KEY, json.dumps(devices))


def add_recent_device(device_code: str, name: str) -> None:
    """Records a successful connection, moving this device to the
    front if it was already recorded (so reconnecting to the same
    device repeatedly doesn't create duplicate or stale entries)."""
    devices = [d for d in _load() if d["device_code"] != device_code]
    devices.insert(0, {"device_code": device_code, "name": name})
    _save(devices[:MAX_RECENT_DEVICES])


def get_recent_devices() -> list[dict]:
    return _load()


def remove_recent_device(device_code: str) -> None:
    _save([d for d in _load() if d["device_code"] != device_code])

"""
Persistent device identity for Nearby Devices — a device code that
survives app restarts, IP changes, and switching networks, unlike the
per-launch identifier the original discovery prototype used (see
discovery_service.py's history: it generated a fresh uuid4 on every
launch, which defeats the whole point of a "persistent identity" this
feature needs).

The code deliberately contains nothing derived from hardware, the
network, or personal information — it's pure random data, generated
once and stored locally. secrets.choice() (not random.choice()) is
used specifically because this is a cryptographically secure random
source, per the requirement that this not be guessable/predictable.
"""
from __future__ import annotations

import secrets
import socket

from PySide6.QtCore import QSettings

# Excludes visually ambiguous characters (0/O, 1/I/L) — this code is
# meant to be readable, typed, and shared by hand (e.g. the "enter a
# device code" search box), so avoiding characters people commonly
# misread or mistype matters more here than a slightly larger alphabet.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_SEGMENT_LENGTH = 4


def _generate_code_segment() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_SEGMENT_LENGTH))


def generate_device_code() -> str:
    """A new LS-XXXX-XXXX code, e.g. LS-7K4P-92MX. Pure randomness —
    contains no hardware ID, IP address, username, or other derivable
    information, and isn't reproducible from anything about this
    machine."""
    return f"LS-{_generate_code_segment()}-{_generate_code_segment()}"


def get_or_create_device_code() -> str:
    """The persistent identity for this LocalShare installation —
    generated once on first call and stored thereafter, so every
    subsequent call (including after a restart) returns the same
    value."""
    settings = QSettings("LocalShare", "LocalShare")
    code = settings.value("device_code", "", type=str)
    if not code:
        code = generate_device_code()
        settings.setValue("device_code", code)
    return code


def get_or_create_write_token() -> str:
    """
    A second, PRIVATE secret alongside the device code — used only to
    prove ownership of this device's entry in the global connect
    registry (see global_registry.py), never displayed or shared
    anywhere. The device code identifies a device publicly; this token
    is what lets that device (and only that device) update its own
    registry entry, per the "Device ID is not an authentication
    credential" distinction the feature's own design calls for.
    Generated with the same cryptographically secure source as the
    device code itself, at a length that's not meant to be typed by a
    person (unlike the code), since it's never something a person
    should need to see or share.
    """
    settings = QSettings("LocalShare", "LocalShare")
    token = settings.value("global_write_token", "", type=str)
    if not token:
        token = secrets.token_urlsafe(32)
        settings.setValue("global_write_token", token)
    return token


def regenerate_device_code() -> str:
    """Explicitly replaces the stored code with a new one — only ever
    called from a user-initiated, confirmed action (see the Settings >
    Device > Regenerate flow), never automatically. Also rotates the
    write_token alongside it: the old code's registry entry (if any)
    becomes orphaned regardless once nobody looks it up anymore, and a
    new code should get a fresh token rather than reusing the old
    device's private secret for a new public identity."""
    settings = QSettings("LocalShare", "LocalShare")
    code = generate_device_code()
    settings.setValue("device_code", code)
    settings.setValue("global_write_token", secrets.token_urlsafe(32))
    return code


def get_default_device_name() -> str:
    """Falls back to the OS computer name — a reasonable default that
    doesn't require the user to configure anything before Nearby
    Devices is useful, while still being changeable in Settings."""
    try:
        name = socket.gethostname()
        return name if name else "LocalShare Device"
    except OSError:
        return "LocalShare Device"


def get_device_name() -> str:
    settings = QSettings("LocalShare", "LocalShare")
    name = settings.value("device_name", "", type=str)
    return name if name else get_default_device_name()


def set_device_name(name: str) -> None:
    QSettings("LocalShare", "LocalShare").setValue("device_name", name.strip())

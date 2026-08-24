"""
PIN-based access control.

Design: a single random `token` is the actual source of truth for
access. The PIN is a human-typeable proxy for it — entering the
correct PIN gets you a cookie containing the token, and knowing the
token directly (e.g. via a link with ?token=... embedded, used for
QR-code convenience) grants the same access. Both checks use
constant-time comparison so response timing can't leak information
about the correct value.

This is deliberately simple: one shared secret for the whole sharing
session, not per-user accounts. That fits what this app actually is —
a temporary share you're handing to specific people, not a multi-user
system with identities to manage.
"""
from __future__ import annotations

import secrets


class AccessControl:
    def __init__(self) -> None:
        self.enabled = False
        self.pin: str | None = None
        self.token: str = secrets.token_urlsafe(24)

    def enable(self, pin: str | None = None) -> str:
        """
        Turns on PIN protection. If no PIN is given, generates a random
        6-digit one. Always issues a fresh token (so any old links/QR
        codes from a previous sharing session stop working). Returns
        the active PIN.
        """
        self.enabled = True
        self.pin = pin.strip() if pin and pin.strip() else self._generate_pin()
        self.token = secrets.token_urlsafe(24)
        return self.pin

    def disable(self) -> None:
        self.enabled = False
        self.pin = None
        self.token = secrets.token_urlsafe(24)  # invalidate any existing sessions immediately

    @staticmethod
    def _generate_pin() -> str:
        """A random 6-digit PIN, e.g. '048213'. Zero-padded — always 6 digits."""
        return f"{secrets.randbelow(1_000_000):06d}"

    def verify_pin(self, attempt: str) -> bool:
        if not self.enabled or self.pin is None or not attempt:
            return False
        # constant-time comparison: a naive `==` leaks how many
        # leading characters matched via response timing, which is a
        # real (if minor) side channel for something PIN-like
        return secrets.compare_digest(attempt.strip(), self.pin)

    def is_authorized(self, cookie_token: str | None, query_token: str | None) -> bool:
        if not self.enabled:
            return True
        if cookie_token and secrets.compare_digest(cookie_token, self.token):
            return True
        if query_token and secrets.compare_digest(query_token, self.token):
            return True
        return False

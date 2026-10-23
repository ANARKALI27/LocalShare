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

import math
import secrets
import threading
import time


class LoginThrottle:
    """
    Slows down PIN guessing. A 6-digit PIN has only a million
    possibilities, so without a limit someone on the network could try
    them all in minutes.

    - Per client: after MAX_FAILURES wrong PINs inside WINDOW seconds,
      that client is locked out for a lock time that doubles every
      time it happens again (5 min, 10 min, ... capped at 1 hour).
    - Global: if the whole share sees GLOBAL_MAX_FAILURES wrong PINs
      inside WINDOW seconds (an attacker rotating addresses), every
      PIN attempt is paused for LOCK_SECONDS.

    A correct PIN is also refused while locked — otherwise a locked-out
    attacker could still keep guessing and just watch for the one that
    works.
    """

    MAX_FAILURES = 5
    WINDOW = 300.0
    LOCK_SECONDS = 300.0
    MAX_LOCK_SECONDS = 3600.0
    GLOBAL_MAX_FAILURES = 40
    MAX_TRACKED_CLIENTS = 1000

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._global_failures: list[float] = []
        self._global_locked_until = 0.0

    def retry_after(self, client: str) -> int:
        """Seconds until this client may try again (0 = allowed now)."""
        now = self._clock()
        with self._lock:
            remaining = max(
                self._locked_until.get(client, 0.0) - now, self._global_locked_until - now, 0.0
            )
        return math.ceil(remaining) if remaining > 0 else 0

    def record_failure(self, client: str) -> None:
        now = self._clock()
        with self._lock:
            recent = [t for t in self._failures.get(client, []) if now - t < self.WINDOW]
            recent.append(now)
            self._failures[client] = recent
            if len(recent) >= self.MAX_FAILURES:
                strikes = self._strikes.get(client, 0)
                lock_for = min(self.LOCK_SECONDS * (2 ** strikes), self.MAX_LOCK_SECONDS)
                self._locked_until[client] = now + lock_for
                self._strikes[client] = strikes + 1
                self._failures[client] = []

            self._global_failures = [t for t in self._global_failures if now - t < self.WINDOW]
            self._global_failures.append(now)
            if len(self._global_failures) >= self.GLOBAL_MAX_FAILURES:
                self._global_locked_until = now + self.LOCK_SECONDS
                self._global_failures = []

            if len(self._failures) > self.MAX_TRACKED_CLIENTS:
                self._prune(now)

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
            self._locked_until.pop(client, None)
            self._strikes.pop(client, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()
            self._strikes.clear()
            self._global_failures.clear()
            self._global_locked_until = 0.0

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._failures.items() if not v or now - v[-1] >= self.WINDOW]:
            if self._locked_until.get(key, 0.0) <= now:
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)
                self._strikes.pop(key, None)


class AccessControl:
    def __init__(self) -> None:
        self.enabled = False
        self.pin: str | None = None
        self.token: str = secrets.token_urlsafe(24)
        self.throttle = LoginThrottle()

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
        self.throttle.reset()
        return self.pin

    def disable(self) -> None:
        self.enabled = False
        self.pin = None
        self.token = secrets.token_urlsafe(24)  # invalidate any existing sessions immediately

    @staticmethod
    def _generate_pin() -> str:
        """A random 6-digit PIN, e.g. '048213'. Zero-padded — always 6 digits."""
        return f"{secrets.randbelow(1_000_000):06d}"

    def attempt_pin(self, attempt: str, client: str) -> tuple[bool, int]:
        """
        Rate-limited PIN check for the login form. Returns
        (ok, retry_after_seconds); retry_after > 0 means the client is
        currently locked out and the PIN was NOT even checked.
        """
        wait = self.throttle.retry_after(client)
        if wait > 0:
            return False, wait
        if self.verify_pin(attempt):
            self.throttle.record_success(client)
            return True, 0
        self.throttle.record_failure(client)
        return False, self.throttle.retry_after(client)

    def verify_pin(self, attempt: str) -> bool:
        if not self.enabled or self.pin is None or not attempt:
            return False
        # constant-time comparison: a naive `==` leaks how many
        # leading characters matched via response timing, which is a
        # real (if minor) side channel for something PIN-like
        # compare_digest on str raises TypeError for non-ASCII input, so
        # compare the UTF-8 bytes instead.
        return secrets.compare_digest(attempt.strip().encode("utf-8"), self.pin.encode("utf-8"))

    def is_authorized(self, cookie_token: str | None, query_token: str | None) -> bool:
        if not self.enabled:
            return True
        expected = self.token.encode("utf-8")
        if cookie_token and secrets.compare_digest(cookie_token.encode("utf-8"), expected):
            return True
        if query_token and secrets.compare_digest(query_token.encode("utf-8"), expected):
            return True
        return False

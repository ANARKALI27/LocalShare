"""
Device ID -> current Cloudflare tunnel URL lookup, via a free-tier
Firebase Realtime Database the user sets up themselves (see
GLOBAL_CONNECT_SETUP.md for the one-time steps). This is deliberately
NOT a custom signaling/relay server — LocalShare already has a working,
free, zero-maintenance way to make a device reachable from the
internet (Cloudflare Quick Tunnel, see app/server/tunnel.py). The only
missing piece for "connect using just a Device ID" is answering
"what's this device's current address" — a plain REST call to a
managed database answers that without needing any new relay/P2P
infrastructure, or a server for anyone to rent, patch, or keep running.

Security model, since this stores data in a database anyone with the
project URL can technically query: each device generates a random,
private write_token (see device_identity.py) alongside its public
device_code, kept only in local settings and never displayed or
shared. Every write includes it; the database's own security rules
(see GLOBAL_CONNECT_SETUP.md) only allow overwriting an EXISTING
device_id's entry if the incoming write_token matches the one already
stored there. This is a real, standard Firebase Realtime Database
pattern — not a custom cryptographic protocol — and its actual
guarantee is: nobody but the original device can update or squat an
existing device_id's entry once the two write_tokens have to match.
It does NOT provide end-to-end confidentiality of the tunnel URL
itself (anyone who knows a specific device_id and has the database URL
could still read that entry) — treat the tunnel URL and PIN the same
way you already do for any other Global-mode share.

Reads are left open (needed for the lookup itself to work at all
without every user configuring Firebase Authentication) — see the
setup doc for exactly what this does and doesn't protect against.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

HEARTBEAT_INTERVAL_SECONDS = 30
ONLINE_WITHIN_SECONDS = 90  # a couple missed heartbats' worth of slack before "offline"


class GlobalRegistryError(Exception):
    pass


def _request(url: str, method: str, payload: dict | None = None, timeout: float = 6.0) -> dict | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            if not body or body == b"null":
                return None
            return json.loads(body)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise GlobalRegistryError(str(exc)) from exc


def register(
    database_url: str, device_code: str, write_token: str, tunnel_url: str,
    device_name: str, pin_required: bool,
) -> None:
    """
    Registers (or updates) this device's current tunnel URL. Called
    once when Global sharing starts, and again on each heartbeat while
    it stays active — the recorded timestamp is what lookup() uses to
    decide online vs offline, not just presence of an entry (a device
    that crashed without unregistering should eventually read as
    offline, not permanently "online" forever).
    """
    url = f"{database_url.rstrip('/')}/devices/{device_code}.json"
    payload = {
        "write_token": write_token,
        "tunnel_url": tunnel_url,
        "device_name": device_name,
        "pin_required": pin_required,
        "last_seen": time.time(),
    }
    _request(url, "PUT", payload)


def unregister(database_url: str, device_code: str, write_token: str) -> None:
    """
    Marks this device offline immediately when Global sharing stops,
    rather than waiting out the full online-timeout window.

    Deliberately does NOT issue an actual HTTP DELETE, and deliberately
    does NOT write to just the last_seen sub-path either — both were
    considered and both have a real hole. A DELETE has no body, so
    there's no way to include write_token with it, and a rule
    permissive enough to allow deletes without checking that token
    would let ANYONE delete ANY device's entry. Writing only to the
    last_seen sub-path is subtler: Firebase's security rules evaluate
    against the data at the RULE's own path (the whole device_code
    node), not just the touched sub-field — so newData's write_token
    would simply reflect the unchanged EXISTING value, making the
    "tokens match" check compare that value to itself and pass
    unconditionally, regardless of who sent the request. Sending a
    full, normal register() write instead — genuinely including the
    real write_token in the payload being compared — is what actually
    exercises the security rule correctly, and reuses the exact same
    write path register() already does for a heartbeat, just with an
    intentionally-expired timestamp.
    """
    url = f"{database_url.rstrip('/')}/devices/{device_code}.json"
    payload = {
        "write_token": write_token,
        "tunnel_url": None,
        "device_name": None,
        "pin_required": False,
        "last_seen": 0,
    }
    try:
        _request(url, "PUT", payload)
    except GlobalRegistryError:
        pass  # best-effort — if this fails, the entry still ages out via the normal timeout


def lookup(database_url: str, device_code: str) -> dict | None:
    """
    Looks up a device by its code. Returns None if the code has never
    been registered, OR is not a syntactically plausible LocalShare
    device code — this second check happens BEFORE any network call,
    both to fail fast on an obvious typo and so a stray database query
    for garbage input can't be used to probe the registry with
    arbitrary paths.

    Returned dict has an "online" bool (based on last_seen recency, a
    real heartbeat — never assumed true just because a record exists)
    in addition to the raw stored fields.
    """
    if not device_code.startswith("LS-") or len(device_code) != 12:
        return None

    url = f"{database_url.rstrip('/')}/devices/{device_code}.json"
    result = _request(url, "GET")
    if result is None:
        return None

    last_seen = result.get("last_seen", 0)
    online = (time.time() - last_seen) <= ONLINE_WITHIN_SECONDS
    return {
        "device_code": device_code,
        "tunnel_url": result.get("tunnel_url"),
        "device_name": result.get("device_name", "Unknown device"),
        "pin_required": result.get("pin_required", False),
        "online": online,
        "last_seen": last_seen,
    }

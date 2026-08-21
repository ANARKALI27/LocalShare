"""
Detect the local machine's LAN-facing IP address.

Strategy: open a UDP "connection" (no packets actually sent) to a
public IP and read back which local interface the OS would use to
route there. This reliably picks the active adapter (Wi-Fi vs
Ethernet) without needing to enumerate adapters manually, and without
requiring internet access — UDP sockets don't send anything on
connect().
"""
from __future__ import annotations

import socket


def get_lan_ip() -> str:
    """
    Best-effort LAN IP for this machine. Falls back to 127.0.0.1 if
    nothing better can be determined (e.g. no network at all).
    """
    candidates: list[str] = []

    # Primary method: ask the OS which local address it would use to
    # reach the outside world. Works even offline since no packet is
    # actually sent for UDP until you call send/sendto.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                candidates.append(ip)
    except OSError:
        pass

    # Fallback: enumerate all addresses for the hostname and pick the
    # first private-range one (handles machines with no default route).
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in candidates and _is_private_ipv4(ip):
                candidates.append(ip)
    except OSError:
        pass

    for ip in candidates:
        if _is_private_ipv4(ip):
            return ip

    return candidates[0] if candidates else "127.0.0.1"


def _is_private_ipv4(ip: str) -> bool:
    """True for RFC1918 private ranges (typical home/office LAN) — used to
    prefer a real LAN address over VPN/link-local/carrier-grade NAT ranges."""
    try:
        parts = [int(p) for p in ip.split(".")]
    except ValueError:
        return False
    if len(parts) != 4:
        return False
    a, b = parts[0], parts[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def find_available_port(start_port: int = 8765, max_attempts: int = 20) -> int:
    """
    Find an available TCP port starting at `start_port`, incrementing
    until a free one is found (or raise if none found in range).
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue  # port in use — try the next one
    raise RuntimeError(
        f"No available port found in range {start_port}-{start_port + max_attempts - 1}"
    )

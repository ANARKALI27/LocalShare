"""
Finds this machine's IPv4 interfaces and their broadcast addresses, so
LAN discovery can announce itself on EVERY network adapter.

Why: sending one packet to 255.255.255.255 (the "limited broadcast")
only goes out of the single adapter the OS picks by routing metric. On a
PC with several adapters — Wi-Fi plus WSL / Hyper-V / VirtualBox / VPN
virtual adapters, which is very common on Windows — that is often NOT the
Wi-Fi/Ethernet adapter the other computer is on, so the other computer
never hears the announcement even though everything else works. Sending
per adapter, from that adapter's own address, fixes it.
"""
from __future__ import annotations

import socket
import struct

from app.network.ip import _is_private_ipv4, get_lan_ip


def _usable(ip: str) -> bool:
    return _is_private_ipv4(ip) and not ip.startswith("169.254.")


def _guess_broadcast(ip: str) -> str:
    """Directed broadcast assuming the (by far most common) /24 network."""
    a, b, c, _ = ip.split(".")
    return f"{a}.{b}.{c}.255"


def _linux_interfaces() -> list[tuple[str, str]]:
    import fcntl

    SIOCGIFADDR, SIOCGIFNETMASK = 0x8915, 0x891B
    found: list[tuple[str, str]] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _index, name in socket.if_nameindex():
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                ip = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFADDR, ifreq)[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFNETMASK, ifreq)[20:24])
            except OSError:
                continue  # interface has no IPv4 address
            if not _usable(ip):
                continue
            ip_int = struct.unpack("!I", socket.inet_aton(ip))[0]
            mask_int = struct.unpack("!I", socket.inet_aton(mask))[0]
            broadcast = socket.inet_ntoa(struct.pack("!I", ip_int | (~mask_int & 0xFFFFFFFF)))
            found.append((ip, broadcast))
    finally:
        sock.close()
    return found


def get_ipv4_interfaces() -> list[tuple[str, str]]:
    """[(local_ip, broadcast_ip), ...] for every usable private IPv4 adapter."""
    found: list[tuple[str, str]] = []
    try:
        found = _linux_interfaces()
    except (ImportError, OSError, AttributeError):
        found = []  # not Linux (no fcntl) — fall through to the portable way

    if not found:
        ips: list[str] = []
        try:
            hostname = socket.gethostname()
            ips.extend(socket.gethostbyname_ex(hostname)[2])
            ips.extend(info[4][0] for info in socket.getaddrinfo(hostname, None, socket.AF_INET))
        except OSError:
            pass
        ips.append(get_lan_ip())
        seen: set[str] = set()
        for ip in ips:
            if ip not in seen and _usable(ip):
                seen.add(ip)
                found.append((ip, _guess_broadcast(ip)))
    return found

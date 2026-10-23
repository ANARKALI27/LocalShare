"""
Broadcasts this LocalShare instance's presence on the LAN and listens
for other instances doing the same, feeding sightings into a
DeviceRegistry (see discovery.py for the tested, pure logic this
wraps). Best-effort: if the network doesn't support broadcast, or the
discovery port is already in use, Nearby Devices just stays empty —
this never crashes the app or blocks anything else from working.
"""
from __future__ import annotations

import socket
import threading
import time

from app.network.discovery import DISCOVERY_PORT, DeviceRegistry, build_announcement, parse_announcement
from app.network.interfaces import get_ipv4_interfaces


class DeviceDiscoveryService:
    def __init__(
        self, device_code: str, name: str, get_port, version: str, get_address,
        capabilities: list[str] | None = None,
    ) -> None:
        # device_code is the PERSISTENT per-installation identity (see
        # device_identity.py) — passed in rather than generated here,
        # since this service may be started/stopped repeatedly across
        # the app's lifetime while the identity itself must not change.
        self.device_code = device_code
        self.name = name
        # get_port, like get_address below, is called fresh before
        # every broadcast rather than read once at construction time —
        # the actual server port isn't known until the server starts
        # (ServerHandle.port is None beforehand), and this service is
        # constructed once at app startup, well before that happens.
        self._get_port = get_port
        self.version = version
        self.capabilities = capabilities or []
        # Called fresh before every broadcast rather than captured once
        # — the LAN address can genuinely change while the app is
        # running (switching networks, connecting/disconnecting a VPN).
        self._get_address = get_address
        self.registry = DeviceRegistry()
        self._running = False
        self._wake = threading.Event()  # set by announce_now() to broadcast immediately
        self._listen_socket: socket.socket | None = None
        self._listen_thread: threading.Thread | None = None
        self._broadcast_thread: threading.Thread | None = None
        # Set once discovery genuinely can't run (e.g. port already
        # bound by something else) — the Nearby Devices UI uses this
        # to show "discovery unavailable" rather than a misleading
        # empty "no devices found" state, per the spec's distinction
        # between "nothing found" and "couldn't even look."
        self.unavailable_reason: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.unavailable_reason = None

        try:
            listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_socket.bind(("", DISCOVERY_PORT))
            listen_socket.settimeout(1.0)  # lets the loop check self._running periodically instead of blocking forever
        except OSError as exc:
            # Port already in use (e.g. another LocalShare instance
            # already listening — fine, that one will do the listening
            # for this machine) or otherwise unavailable (firewall,
            # permissions). Discovery just doesn't run this session;
            # nothing else about the app is affected.
            self._running = False
            self.unavailable_reason = str(exc)
            return

        self._listen_socket = listen_socket
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()
        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._broadcast_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._listen_socket is not None:
            try:
                self._listen_socket.close()
            except OSError:
                pass
            self._listen_socket = None

    def _listen_loop(self) -> None:
        while self._running and self._listen_socket is not None:
            try:
                data, _addr = self._listen_socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed — stop() was called
            parsed = parse_announcement(data)
            if parsed is None or parsed["device_code"] == self.device_code:
                continue  # not a valid LocalShare announcement, or our own broadcast — ignore
            # Prefer the address the packet REALLY came from over the one
            # written inside it: a PC with several adapters (Wi-Fi, WSL,
            # VPN...) may advertise an address on an adapter we can't
            # reach, while the packet's source is, by definition, an
            # address that reached us.
            source_ip = _addr[0] if _addr and not _addr[0].startswith("127.") else parsed["ip"]
            self.registry.see(
                parsed["device_code"], parsed["name"], source_ip,
                parsed["port"], parsed["version"], parsed["capabilities"],
            )

    def announce_now(self) -> None:
        """Broadcast right away instead of waiting for the next 5s tick
        (used by the Nearby Devices Refresh button)."""
        self._wake.set()

    def _send_announcement(self, packet: bytes) -> None:
        """
        Sends the announcement out of EVERY usable network adapter (see
        interfaces.py for why a single 255.255.255.255 send isn't
        enough), each from that adapter's own address, to both the
        limited broadcast and that network's directed broadcast. Falls
        back to the old single send if no adapter could be listed.
        """
        interfaces = get_ipv4_interfaces()
        sent_any = False
        for local_ip, broadcast_ip in interfaces:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((local_ip, 0))  # pins the outgoing adapter
                for target in {"255.255.255.255", broadcast_ip}:
                    try:
                        sock.sendto(packet, (target, DISCOVERY_PORT))
                        sent_any = True
                    except OSError:
                        pass  # this adapter/network refused it — try the others
            except OSError:
                pass
            finally:
                sock.close()
        if not sent_any:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(packet, ("<broadcast>", DISCOVERY_PORT))
            except OSError:
                pass
            finally:
                sock.close()

    def _broadcast_loop(self) -> None:
        while self._running:
            ip = self._get_address()
            port = self._get_port()
            if ip and port:
                packet = build_announcement(
                    self.device_code, self.name, ip, port, self.version, self.capabilities,
                )
                self._send_announcement(packet)
            self.registry.prune()
            # ~5s between announcements, but wakes early for announce_now()
            # and notices stop() quickly.
            for _ in range(50):
                if not self._running:
                    return
                if self._wake.wait(0.1):
                    self._wake.clear()
                    break

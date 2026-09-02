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
import uuid

from app.network.discovery import DISCOVERY_PORT, DeviceRegistry, build_announcement, parse_announcement


class DeviceDiscoveryService:
    def __init__(self, name: str, version: str, get_address) -> None:
        self.device_id = uuid.uuid4().hex
        self.name = name
        self.version = version
        # Called fresh before every broadcast rather than captured once
        # — the LAN address can genuinely change while the app is
        # running (switching networks, connecting/disconnecting a VPN).
        self._get_address = get_address
        self.registry = DeviceRegistry()
        self._running = False
        self._listen_socket: socket.socket | None = None
        self._listen_thread: threading.Thread | None = None
        self._broadcast_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        try:
            listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_socket.bind(("", DISCOVERY_PORT))
            listen_socket.settimeout(1.0)  # lets the loop check self._running periodically instead of blocking forever
        except OSError:
            # Port already in use (e.g. another LocalShare instance
            # already listening — fine, that one will do the listening
            # for this machine) or otherwise unavailable. Discovery
            # just doesn't run this session; nothing else is affected.
            self._running = False
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
            if parsed is None or parsed["device_id"] == self.device_id:
                continue  # not a valid LocalShare announcement, or our own broadcast — ignore
            self.registry.see(parsed["device_id"], parsed["name"], parsed["address"], parsed["version"])

    def _broadcast_loop(self) -> None:
        send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while self._running:
                address = self._get_address()
                if address:
                    packet = build_announcement(self.device_id, self.name, address, self.version)
                    try:
                        send_socket.sendto(packet, ("<broadcast>", DISCOVERY_PORT))
                    except OSError:
                        pass  # network hiccup — skip this cycle, try again next time
                self.registry.prune()
                for _ in range(50):  # sleep ~5s total, but in short slices so stop() is noticed quickly
                    if not self._running:
                        break
                    time.sleep(0.1)
        finally:
            send_socket.close()

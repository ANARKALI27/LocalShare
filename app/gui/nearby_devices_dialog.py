"""
Nearby Devices — shows other LocalShare instances discovered on the
local network, lets the user open one directly in their browser, and
surfaces device codes for copy/search.

Implemented as a dialog opened from a button, matching how Settings
already works in this app, rather than as a sidebar page — the app's
sidebar navigation was deliberately removed in an earlier revision in
favor of this single-page-plus-dialogs layout, and reintroducing
sidebar nav for one feature would contradict that decision and the
existing visual style.

The dialog only ever READS from a DeviceDiscoveryService passed in by
MainWindow — it doesn't own discovery itself, matching the separation
the spec for this feature asked for (GUI receives device state
updates rather than performing network discovery directly).

Visual style: glassmorphism-inspired (translucent layered cards, soft
light borders, ambient shadows), applied via QSS rgba backgrounds
WITHIN this dialog's own opaque, natively-framed window — deliberately
NOT via making the dialog window itself translucent. This app's own
existing glass-effect feature for the main window explicitly avoids
relying on real backdrop transparency, precisely because it isn't
reliable across platforms without native compositor support (Windows
Acrylic/Mica, etc.) that can't be verified without a real machine to
test on for each one. This dialog follows that same lesson: the glass
LOOK comes from translucent card backgrounds blending against this
window's own solid content area, not from seeing whatever is actually
behind the window.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.hover_button import HoverGlowButton
from app.network.connection_tester import test_connection

AUTO_REFRESH_INTERVAL_MS = 6000  # within the spec's suggested 5-10s range


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """'#RRGGBB' -> 'rgba(r, g, b, a)' for glass-style translucent QSS
    backgrounds. Genuine OS-level window/backdrop blur (true
    glassmorphism) isn't attempted here — see the module docstring for
    why — this achieves the same visual language (translucent layered
    panels, soft light borders) reliably within a single opaque
    window, which doesn't depend on platform-specific compositor
    support this project has no way to test."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _apply_glass_shadow(widget: QWidget, blur: int = 24, alpha: int = 90) -> None:
    """Soft ambient shadow used throughout the glass styling below —
    the closest reliable equivalent to a backdrop blur's soft edge
    that QGraphicsDropShadowEffect can actually deliver."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, 4)
    shadow.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(shadow)


class _ConnectionTestWorker(QThread):
    """Runs test_connection() off the GUI thread — it's a blocking
    network call with up to a few seconds of timeout, which would
    freeze the dialog if run directly on the main thread."""

    finished_test = Signal(str, bool)  # device_code, is_reachable

    def __init__(self, device_code: str, ip: str, port: int) -> None:
        super().__init__()
        self._device_code = device_code
        self._ip = ip
        self._port = port

    def run(self) -> None:
        reachable = test_connection(self._ip, self._port)
        self.finished_test.emit(self._device_code, reachable)


class _DeviceCard(QFrame):
    """One discovered device's card: identity, address, status, and
    actions. The whole card is clickable to open the device (per the
    spec), with a visible hover cue so that isn't a surprise, and the
    secondary actions (copy, test) live in an explicit menu rather than
    also being click targets on the same card, to avoid the ambiguity
    of overlapping click zones."""

    def __init__(self, device_info: dict, theme_colors: dict, parent=None) -> None:
        super().__init__(parent)
        self.device_info = device_info
        self.theme_colors = theme_colors
        self._test_worker: _ConnectionTestWorker | None = None

        self.setObjectName("DeviceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        surface_glass = _hex_to_rgba(theme_colors["surface"], 0.55)
        surface_glass_hover = _hex_to_rgba(theme_colors["surface"], 0.72)
        self.setStyleSheet(
            f"""
            QFrame#DeviceCard {{
                background-color: {surface_glass};
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.10);
            }}
            QFrame#DeviceCard:hover {{
                background-color: {surface_glass_hover};
                border: 1px solid {_hex_to_rgba(theme_colors['accent'], 0.6)};
            }}
            """
        )
        _apply_glass_shadow(self, blur=20, alpha=70)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        online = device_info["online"]
        status_dot = "●" if online else "○"
        status_color = theme_colors["accent"] if online else theme_colors["text_dim"]

        name_label = QLabel(f"\U0001F4BB {device_info['name']}")
        name_label.setStyleSheet(f"color: {theme_colors['text']}; font-size: 15px; font-weight: 600;")
        top_row.addWidget(name_label)
        top_row.addStretch()

        self.status_label = QLabel(status_dot)
        self.status_label.setStyleSheet(f"color: {status_color}; font-size: 15px;")
        top_row.addWidget(self.status_label)

        menu_btn = HoverGlowButton("⋮", glow_color=theme_colors["accent"])
        menu_btn.setFixedWidth(32)
        menu_btn.clicked.connect(self._show_menu)
        top_row.addWidget(menu_btn)
        layout.addLayout(top_row)

        detail_text = f"{device_info['device_code']}\n{device_info['ip']}:{device_info['port']}"
        detail_label = QLabel(detail_text)
        detail_label.setStyleSheet(f"color: {theme_colors['text_dim']}; font-size: 12px;")
        layout.addWidget(detail_label)

        if not online:
            seconds = int(device_info["seconds_since_seen"])
            self.status_text_label = QLabel(f"Offline · last seen {seconds}s ago")
        else:
            self.status_text_label = QLabel("Same Network")
        self.status_text_label.setStyleSheet(f"color: {status_color}; font-size: 12px;")
        layout.addWidget(self.status_text_label)

        self.hover_hint = QLabel("Open LocalShare →")
        self.hover_hint.setStyleSheet(f"color: {theme_colors['accent']}; font-size: 11px;")
        self.hover_hint.hide()
        layout.addWidget(self.hover_hint)

    def enterEvent(self, event) -> None:
        self.hover_hint.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_hint.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._open_device()
        super().mousePressEvent(event)

    def _open_device(self) -> None:
        url = f"http://{self.device_info['ip']}:{self.device_info['port']}"
        QDesktopServices.openUrl(QUrl(url))

    def _show_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Open", self._open_device)
        menu.addAction("View Details", self._show_details)
        menu.addAction("Copy Address", self._copy_address)
        menu.addAction("Copy Device Code", self._copy_code)
        menu.addAction("Test Connection", self._start_connection_test)
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _show_details(self) -> None:
        info = self.device_info
        status_text = "● Online" if info["online"] else f"○ Offline · last seen {int(info['seconds_since_seen'])}s ago"
        QMessageBox.information(
            self,
            "Device Details",
            f"Device Name\n{info['name']}\n\n"
            f"Device Code\n{info['device_code']}\n\n"
            f"IP Address\n{info['ip']}\n\n"
            f"Port\n{info['port']}\n\n"
            f"Connection\nSame Network\n\n"
            f"Status\n{status_text}\n\n"
            f"LocalShare Version\n{info['version']}",
        )

    def _copy_address(self) -> None:
        url = f"http://{self.device_info['ip']}:{self.device_info['port']}"
        QApplication.clipboard().setText(url)

    def _copy_code(self) -> None:
        QApplication.clipboard().setText(self.device_info["device_code"])

    def _start_connection_test(self) -> None:
        self.status_text_label.setText("Testing connection…")
        worker = _ConnectionTestWorker(
            self.device_info["device_code"], self.device_info["ip"], self.device_info["port"],
        )
        worker.finished_test.connect(self._on_connection_test_result)
        self._test_worker = worker  # kept alive on the instance until it finishes
        worker.start()

    def _on_connection_test_result(self, device_code: str, reachable: bool) -> None:
        if reachable:
            self.status_text_label.setText("✓ Online — server responded")
            self.status_text_label.setStyleSheet(f"color: {self.theme_colors['accent']}; font-size: 12px;")
        else:
            self.status_text_label.setText("⚠ Discovered but server unavailable")
            self.status_text_label.setStyleSheet(f"color: #F87171; font-size: 12px;")


class NearbyDevicesDialog(QDialog):
    def __init__(self, discovery_service, theme_colors: dict, parent=None) -> None:
        super().__init__(parent)
        self.discovery_service = discovery_service
        self.theme_colors = theme_colors
        self._cards: list[_DeviceCard] = []

        self.setWindowTitle("Nearby Devices")
        self.setMinimumSize(420, 480)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_colors['bg']};
            }}
            """
        )

        root = QVBoxLayout(self)

        header_row = QHBoxLayout()
        self.status_header = QLabel("Nearby Devices")
        self.status_header.setStyleSheet(f"color: {theme_colors['text']}; font-size: 18px; font-weight: 600;")
        header_row.addWidget(self.status_header)
        header_row.addStretch()
        refresh_btn = HoverGlowButton("↻ Refresh", glow_color=theme_colors["accent"])
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)
        root.addLayout(header_row)

        self.scan_status_label = QLabel("")
        self.scan_status_label.setStyleSheet(f"color: {theme_colors['text_dim']}; font-size: 12px;")
        root.addWidget(self.scan_status_label)

        code_row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Enter Device Code (LS-XXXX-XXXX)")
        self.code_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {_hex_to_rgba(theme_colors['surface'], 0.5)};
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 8px;
                padding: 8px 10px;
                color: {theme_colors['text']};
            }}
            QLineEdit:focus {{
                border: 1px solid {_hex_to_rgba(theme_colors['accent'], 0.7)};
            }}
            """
        )
        code_row.addWidget(self.code_input)
        connect_btn = HoverGlowButton("Connect", glow_color=theme_colors["accent"])
        connect_btn.clicked.connect(self._connect_by_code)
        code_row.addWidget(connect_btn)
        root.addLayout(code_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.cards_container = QWidget()
        self.cards_container.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.addStretch()
        self.scroll_area.setWidget(self.cards_container)
        root.addWidget(self.scroll_area, stretch=1)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setStyleSheet(f"color: {theme_colors['text_dim']}; font-size: 13px;")
        root.addWidget(self.empty_state_label)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self.refresh)
        self._auto_refresh_timer.start(AUTO_REFRESH_INTERVAL_MS)

        self.refresh()

    def refresh(self) -> None:
        if self.discovery_service is None or not self.discovery_service.is_running:
            self.scan_status_label.setText("⚠ Discovery unavailable")
            self._render_devices(
                [],
                empty_message=(
                    "Nearby device discovery is unavailable.\n\n"
                    "Your firewall or network may be blocking local discovery."
                ),
            )
            return

        if self.discovery_service.unavailable_reason:
            self.scan_status_label.setText(
                "⚠ Discovery unavailable — the network discovery port may be blocked "
                "by your firewall or already in use."
            )
            self._render_devices(
                [],
                empty_message=(
                    "Nearby device discovery is unavailable.\n\n"
                    "Your firewall or network may be blocking local discovery."
                ),
            )
            return

        devices = self.discovery_service.registry.known_devices()
        if devices:
            self.scan_status_label.setText(f"✓ Scan complete — {len(devices)} device(s) found")
        else:
            self.scan_status_label.setText("● Scanning local network…")
        self._render_devices(
            devices,
            empty_message=(
                "No LocalShare devices found\n\n"
                "Make sure another device is connected\nto the same Wi-Fi or Ethernet network."
            ),
        )

    def _render_devices(self, devices: list[dict], empty_message: str = "") -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        self.empty_state_label.setText(empty_message)
        self.empty_state_label.setVisible(len(devices) == 0)
        self.scroll_area.setVisible(len(devices) > 0)

        for device in devices:
            card = _DeviceCard(device, self.theme_colors)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self._cards.append(card)

    def _connect_by_code(self) -> None:
        code = self.code_input.text().strip().upper()
        if not code:
            return
        if self.discovery_service is None:
            return
        devices = self.discovery_service.registry.known_devices()
        match = next((d for d in devices if d["device_code"] == code), None)
        if match:
            url = f"http://{match['ip']}:{match['port']}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.scan_status_label.setText(f"No device found on this network with code {code}")

    def closeEvent(self, event) -> None:
        self._auto_refresh_timer.stop()
        super().closeEvent(event)

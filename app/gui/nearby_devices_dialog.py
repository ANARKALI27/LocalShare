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

from datetime import datetime
from html import escape as html_escape

from PySide6.QtCore import QSettings, QThread, Qt, QTimer, QUrl, Signal
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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.network import global_registry
from app.network.connection_tester import test_connection
from app.network.recent_devices import add_recent_device, get_recent_devices, remove_recent_device

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


_T = "255, 255, 255"  # overlay tint: white on dark themes, black on light ones


def _set_tint(theme_colors: dict) -> None:
    """Pick the translucent-overlay colour so borders/hover fills stay
    visible on both dark and light themes."""
    global _T
    h = theme_colors["bg"].lstrip("#")
    luma = 0.299 * int(h[0:2], 16) + 0.587 * int(h[2:4], 16) + 0.114 * int(h[4:6], 16)
    _T = "0, 0, 0" if luma > 140 else "255, 255, 255"


def _button_qss(theme_colors: dict, primary: bool = False) -> str:
    """Shared QSS for the plain QPushButtons in this dialog (plain, not
    HoverGlowButton — see the note in _DeviceCard about nested graphics
    effects rendering invisibly)."""
    accent = theme_colors["accent"]
    if primary:
        return f"""
            QPushButton {{
                background-color: {accent}; color: #FFFFFF; border: none;
                border-radius: 8px; padding: 8px 18px; font-weight: 600; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {theme_colors.get('accent_hover', accent)}; }}
            QPushButton:pressed {{ background-color: {_hex_to_rgba(accent, 0.75)}; }}
        """
    return f"""
        QPushButton {{
            background-color: rgba({_T}, 0.06); color: {theme_colors['text']};
            border: 1px solid rgba({_T}, 0.12); border-radius: 8px;
            padding: 7px 14px; font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: rgba({_T}, 0.12);
            border: 1px solid {_hex_to_rgba(accent, 0.6)};
        }}
        QPushButton:pressed {{ background-color: rgba({_T}, 0.04); }}
    """


def _menu_qss(theme_colors: dict) -> str:
    return f"""
        QMenu {{
            background-color: {theme_colors['surface']}; color: {theme_colors['text']};
            border: 1px solid rgba({_T}, 0.14); border-radius: 10px; padding: 6px;
        }}
        QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 6px; }}
        QMenu::item:selected {{ background-color: {_hex_to_rgba(theme_colors['accent'], 0.28)}; }}
        QMenu::separator {{ height: 1px; background: rgba({_T}, 0.10); margin: 4px 8px; }}
    """


class _AutoHideLabel(QLabel):
    """A QLabel that takes no space while it has no text, so status
    lines don't leave an empty gap in the layout."""

    def setText(self, text: str) -> None:  # noqa: N802 — Qt naming
        super().setText(text)
        self.setVisible(bool(text))


def _section_label(text: str, theme_colors: dict) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {theme_colors['text_dim']}; font-size: 11px; font-weight: 700; "
        "letter-spacing: 1.5px; background: transparent;"
    )
    return label


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


class _GlobalLookupWorker(QThread):
    """Runs a global_registry.lookup() call off the GUI thread — same
    reasoning as _ConnectionTestWorker above: it's a blocking network
    request, which would freeze the dialog if run directly."""

    finished_lookup = Signal(str, object)  # device_code, result dict or None

    def __init__(self, registry_url: str, device_code: str) -> None:
        super().__init__()
        self._registry_url = registry_url
        self._device_code = device_code

    def run(self) -> None:
        try:
            result = global_registry.lookup(self._registry_url, self._device_code)
        except global_registry.GlobalRegistryError:
            result = None
        self.finished_lookup.emit(self._device_code, result)


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
        _set_tint(theme_colors)
        self._test_worker: _ConnectionTestWorker | None = None

        self.setObjectName("DeviceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        accent = theme_colors["accent"]
        self.setStyleSheet(
            f"""
            QFrame#DeviceCard {{
                background-color: {_hex_to_rgba(theme_colors['surface'], 0.92)};
                border-radius: 14px;
                border: 1px solid rgba({_T}, 0.12);
            }}
            QFrame#DeviceCard:hover {{
                background-color: {_hex_to_rgba(theme_colors['surface'], 0.99)};
                border: 1px solid {_hex_to_rgba(accent, 0.7)};
            }}
            """
        )
        _apply_glass_shadow(self, blur=26, alpha=110)

        online = device_info["online"]
        status_color = "#34D399" if online else theme_colors["text_dim"]

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 14, 14, 14)
        outer.setSpacing(14)

        # Avatar: a round badge with the device's initial — gives each
        # card an identity at a glance instead of a generic emoji.
        initial = (device_info["name"].strip()[:1] or "?").upper()
        avatar = QLabel(initial)
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {_hex_to_rgba(accent, 0.22)}; color: {accent}; "
            f"border: 1px solid {_hex_to_rgba(accent, 0.5)}; border-radius: 23px; "
            "font-size: 19px; font-weight: 700;"
        )
        outer.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(5)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel(device_info["name"])
        name_label.setStyleSheet(
            f"color: {theme_colors['text']}; font-size: 15px; font-weight: 700; background: transparent;"
        )
        name_row.addWidget(name_label)

        # Status chip: green "Online" / grey "Offline"
        self.status_label = QLabel("● Online" if online else "○ Offline")
        self.status_label.setStyleSheet(
            f"color: {status_color}; background-color: {_hex_to_rgba(status_color if online else '#888888', 0.16)}; "
            "border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;"
        )
        name_row.addWidget(self.status_label)
        name_row.addStretch()
        info.addLayout(name_row)

        code_label = QLabel(device_info["device_code"])
        code_label.setStyleSheet(
            f"color: {theme_colors['text']}; background-color: rgba({_T}, 0.07); "
            "border-radius: 6px; padding: 2px 8px; font-family: Consolas, 'DejaVu Sans Mono', monospace; "
            "font-size: 12px;"
        )
        code_row = QHBoxLayout()
        code_row.addWidget(code_label)
        code_row.addStretch()
        info.addLayout(code_row)

        addr_label = QLabel(f"{device_info['ip']}:{device_info['port']}")
        addr_label.setStyleSheet(f"color: {theme_colors['text_dim']}; font-size: 12px; background: transparent;")
        info.addWidget(addr_label)

        if not online:
            seconds = int(device_info["seconds_since_seen"])
            self.status_text_label = QLabel(f"Offline · last seen {seconds}s ago")
        else:
            self.status_text_label = QLabel("Same Network")
        self.status_text_label.setStyleSheet(
            f"color: {accent if online else theme_colors['text_dim']}; font-size: 12px; "
            "font-weight: 600; background: transparent;"
        )
        info.addWidget(self.status_text_label)

        self.hover_hint = QLabel("Click to open LocalShare →")
        self.hover_hint.setStyleSheet(f"color: {accent}; font-size: 11px; background: transparent;")
        self.hover_hint.hide()
        info.addWidget(self.hover_hint)
        outer.addLayout(info, stretch=1)

        # Plain QPushButton on purpose (NOT HoverGlowButton): nesting a
        # widget that has its own graphics effect inside this shadowed
        # card makes it render invisible (confirmed by testing earlier).
        menu_btn = QPushButton("⋮")
        menu_btn.setFixedSize(34, 34)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet(
            f"""
            QPushButton {{ background-color: rgba({_T}, 0.06); color: {theme_colors['text']};
                border: 1px solid rgba({_T}, 0.12); border-radius: 17px; font-size: 16px; font-weight: 700; }}
            QPushButton:hover {{ background-color: rgba({_T}, 0.14); border: 1px solid {_hex_to_rgba(accent, 0.6)}; }}
            """
        )
        menu_btn.clicked.connect(self._show_menu)
        self._menu_btn = menu_btn
        outer.addWidget(menu_btn, alignment=Qt.AlignmentFlag.AlignTop)

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
        menu.setStyleSheet(_menu_qss(self.theme_colors))
        menu.addAction("Open", self._open_device)
        menu.addAction("View Details", self._show_details)
        menu.addSeparator()
        menu.addAction("Copy Address", self._copy_address)
        menu.addAction("Copy Device Code", self._copy_code)
        menu.addAction("Test Connection", self._start_connection_test)
        menu.exec(self._menu_btn.mapToGlobal(self._menu_btn.rect().bottomLeft()))

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
            self.status_text_label.setStyleSheet(f"color: #34D399; font-size: 12px; font-weight: 600; background: transparent;")
        else:
            self.status_text_label.setText("⚠ Discovered but server unavailable")
            self.status_text_label.setStyleSheet(f"color: #F87171; font-size: 12px; font-weight: 600; background: transparent;")


class NearbyDevicesDialog(QDialog):
    def __init__(self, discovery_service, theme_colors: dict, parent=None) -> None:
        super().__init__(parent)
        self.discovery_service = discovery_service
        self.theme_colors = theme_colors
        _set_tint(theme_colors)
        self._cards: list[_DeviceCard] = []
        self._global_lookup_worker: _GlobalLookupWorker | None = None

        self.setWindowTitle("Nearby Devices")
        self.setMinimumSize(480, 600)
        self.resize(500, 660)
        accent = theme_colors["accent"]
        self.setStyleSheet(f"QDialog {{ background-color: {theme_colors['bg']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)

        # ---- header: title + live status pill + refresh ----
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.status_header = QLabel("Nearby Devices")
        self.status_header.setStyleSheet(
            f"color: {theme_colors['text']}; font-size: 24px; font-weight: 800; background: transparent;"
        )
        title_col.addWidget(self.status_header)
        self.scan_status_label = QLabel("")
        self.scan_status_label.setStyleSheet(
            f"color: {theme_colors['text_dim']}; font-size: 12px; background: transparent;"
        )
        title_col.addWidget(self.scan_status_label)
        header_row.addLayout(title_col)
        header_row.addStretch()
        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(_button_qss(theme_colors))
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header_row)

        # ---- connect-by-ID panel (glass card, no graphics effect so
        # nothing inside it can render invisibly) ----
        connect_panel = QFrame()
        connect_panel.setObjectName("ConnectPanel")
        connect_panel.setStyleSheet(
            f"""
            QFrame#ConnectPanel {{
                background-color: {_hex_to_rgba(theme_colors['surface'], 0.85)};
                border-radius: 14px;
                border: 1px solid rgba({_T}, 0.12);
            }}
            """
        )
        panel_layout = QVBoxLayout(connect_panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(8)
        panel_layout.addWidget(_section_label("CONNECT BY DEVICE ID", theme_colors))

        code_row = QHBoxLayout()
        code_row.setSpacing(10)
        self.code_input = QLineEdit()
        self.code_input.setText("LS-")
        self.code_input.setPlaceholderText("LS-XXXX-XXXX")
        self.code_input.setMaxLength(12)
        self.code_input.textChanged.connect(self._on_code_input_changed)
        self.code_input.returnPressed.connect(self._connect_by_code)
        self.code_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba({_T}, 0.10);
                border: 1px solid rgba({_T}, 0.12);
                border-radius: 8px; padding: 9px 12px;
                color: {theme_colors['text']};
                font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 14px; letter-spacing: 1px;
            }}
            QLineEdit:focus {{ border: 1px solid {_hex_to_rgba(accent, 0.85)}; }}
            """
        )
        code_row.addWidget(self.code_input, stretch=1)
        connect_btn = QPushButton("Connect")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setStyleSheet(_button_qss(theme_colors, primary=True))
        connect_btn.clicked.connect(self._connect_by_code)
        code_row.addWidget(connect_btn)
        panel_layout.addLayout(code_row)

        connect_hint = QLabel(
            "Works on your local network instantly. Reaching a device anywhere else on the "
            "internet needs Global Connect set up in Settings → Device."
        )
        connect_hint.setWordWrap(True)
        connect_hint.setStyleSheet(f"color: {theme_colors['text_dim']}; font-size: 11px; background: transparent;")
        panel_layout.addWidget(connect_hint)

        # Reports whichever of LAN / global actually happened — never
        # implies a global device is nearby.
        self.connect_status_label = _AutoHideLabel("")
        self.connect_status_label.hide()
        self.connect_status_label.setWordWrap(True)
        self.connect_status_label.setStyleSheet(
            f"color: {theme_colors['text_dim']}; font-size: 12px; background: transparent;"
        )
        panel_layout.addWidget(self.connect_status_label)
        root.addWidget(connect_panel)

        # ---- recent devices (hidden until there is at least one) ----
        self.recent_label = _section_label("RECENT DEVICES", theme_colors)
        self.recent_label.hide()
        root.addWidget(self.recent_label)

        self.recent_container = QWidget()
        self.recent_container.setStyleSheet("background: transparent;")
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(6)
        self.recent_container.hide()
        root.addWidget(self.recent_container)
        self._recent_row_widgets: list[QWidget] = []

        # ---- discovered devices ----
        self.devices_label = _section_label("ON THIS NETWORK", theme_colors)
        root.addWidget(self.devices_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: rgba({_T}, 0.22); border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            """
        )
        self.cards_container = QWidget()
        self.cards_container.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 4, 8)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch()
        self.scroll_area.setWidget(self.cards_container)
        root.addWidget(self.scroll_area, stretch=1)

        # Empty state: its own glass panel so the dialog never looks
        # blank on first open.
        self.empty_state_panel = QFrame()
        self.empty_state_panel.setObjectName("EmptyStatePanel")
        self.empty_state_panel.setStyleSheet(
            f"""
            QFrame#EmptyStatePanel {{
                background-color: {_hex_to_rgba(theme_colors['surface'], 0.85)};
                border-radius: 14px;
                border: 1px dashed rgba({_T}, 0.18);
            }}
            """
        )
        empty_state_layout = QVBoxLayout(self.empty_state_panel)
        empty_state_layout.setContentsMargins(24, 28, 24, 28)
        empty_state_layout.setSpacing(8)
        empty_state_layout.addStretch()
        empty_icon = QLabel("\U0001F4E1")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet("font-size: 34px; background: transparent;")
        empty_state_layout.addWidget(empty_icon)
        self.empty_state_label = QLabel("")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(
            f"color: {theme_colors['text_dim']}; font-size: 13px; background: transparent;"
        )
        empty_state_layout.addWidget(self.empty_state_label)
        empty_state_layout.addStretch()
        root.addWidget(self.empty_state_panel, stretch=1)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self.refresh)
        self._auto_refresh_timer.start(AUTO_REFRESH_INTERVAL_MS)

        self._refresh_recent_devices()
        self.refresh()

    def refresh(self) -> None:
        if self.discovery_service is not None and hasattr(self.discovery_service, "announce_now"):
            self.discovery_service.announce_now()  # also tell others we're here, right now
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
            self.scan_status_label.setStyleSheet("color: #34D399; font-size: 12px; background: transparent;")
        else:
            self.scan_status_label.setText("● Scanning local network…")
            self.scan_status_label.setStyleSheet(
                f"color: {self.theme_colors['text_dim']}; font-size: 12px; background: transparent;"
            )
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
        self.empty_state_panel.setVisible(len(devices) == 0)
        self.devices_label.setText(
            f"ON THIS NETWORK  ·  {len(devices)}" if devices else "ON THIS NETWORK"
        )
        self.scroll_area.setVisible(len(devices) > 0)

        for device in devices:
            card = _DeviceCard(device, self.theme_colors)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self._cards.append(card)

    def _on_code_input_changed(self, text: str) -> None:
        """
        Auto-uppercases as the user types, since device codes are
        always uppercase and typing them in lowercase would otherwise
        just fail to match with no obvious reason why. Blocks signals
        while rewriting the text to avoid re-triggering this same
        handler recursively, and restores the cursor position
        afterward so retyping the (now-uppercased) text doesn't jump
        the cursor to an unexpected spot mid-typing.
        """
        upper = text.upper()
        if upper == text:
            return
        cursor_pos = self.code_input.cursorPosition()
        self.code_input.blockSignals(True)
        self.code_input.setText(upper)
        self.code_input.setCursorPosition(cursor_pos)
        self.code_input.blockSignals(False)

    def _refresh_recent_devices(self) -> None:
        for widget in self._recent_row_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._recent_row_widgets = []

        devices = get_recent_devices()
        self.recent_label.setVisible(len(devices) > 0)
        self.recent_container.setVisible(len(devices) > 0)

        for device in devices:
            row = self._build_recent_row(device["device_code"], device["name"])
            self.recent_layout.addWidget(row)
            self._recent_row_widgets.append(row)

    def _build_recent_row(self, device_code: str, name: str) -> QWidget:
        row = QFrame()
        row.setObjectName("RecentRow")
        row.setStyleSheet(
            f"""
            QFrame#RecentRow {{
                background-color: {_hex_to_rgba(self.theme_colors['surface'], 0.7)};
                border-radius: 10px;
                border: 1px solid rgba({_T}, 0.08);
            }}
            """
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel(
            f"<span style='font-weight:600;'>{html_escape(name)}</span>"
            f"&nbsp;&nbsp;<span style='color:{self.theme_colors['text_dim']};'>{html_escape(device_code)}</span>"
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(f"color: {self.theme_colors['text']}; font-size: 12px; background: transparent;")
        layout.addWidget(label, stretch=1)

        connect_btn = QPushButton("Connect")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setStyleSheet(_button_qss(self.theme_colors))
        connect_btn.clicked.connect(lambda: self._reconnect_to_recent(device_code))
        layout.addWidget(connect_btn)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(30, 30)
        remove_btn.setToolTip("Remove from recent")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(
            f"""
            QPushButton {{ background: transparent; color: {self.theme_colors['text_dim']}; border: none;
                border-radius: 15px; font-size: 12px; }}
            QPushButton:hover {{ background-color: rgba(248, 113, 113, 0.2); color: #F87171; }}
            """
        )
        remove_btn.clicked.connect(lambda: self._remove_recent(device_code))
        layout.addWidget(remove_btn)

        return row

    def _reconnect_to_recent(self, device_code: str) -> None:
        # Always re-runs the normal lookup rather than reusing a
        # cached address — see the Recent Devices section comment in
        # __init__ for why (an address can genuinely change between
        # visits, LAN IP or Global tunnel URL alike).
        self.code_input.setText(device_code)
        self._connect_by_code()

    def _remove_recent(self, device_code: str) -> None:
        remove_recent_device(device_code)
        self._refresh_recent_devices()

    def _connect_by_code(self) -> None:
        code = self.code_input.text().strip().upper()
        if not code:
            return

        # LAN first, per the feature's own preference order — a device
        # on the same network is found instantly with no network
        # round-trip, and shouldn't wait on (or depend on) the global
        # registry being configured at all.
        if self.discovery_service is not None:
            devices = self.discovery_service.registry.known_devices()
            match = next((d for d in devices if d["device_code"] == code), None)
            if match:
                url = f"http://{match['ip']}:{match['port']}"
                self.connect_status_label.setText(f"✓ Found on your local network — opening {url}")
                add_recent_device(code, match["name"])
                self._refresh_recent_devices()
                QDesktopServices.openUrl(QUrl(url))
                return

        registry_url = QSettings("LocalShare", "LocalShare").value("global_registry_url", "", type=str).strip()
        if not registry_url:
            self.connect_status_label.setText(
                f"No device found on this network with code {code}. To reach a device "
                "anywhere else, set up Global Connect in Settings → Device."
            )
            return

        self.connect_status_label.setText("Searching…")
        worker = _GlobalLookupWorker(registry_url, code)
        worker.finished_lookup.connect(self._on_global_lookup_result)
        self._global_lookup_worker = worker
        worker.start()

    def _on_global_lookup_result(self, device_code: str, result: dict | None) -> None:
        if result is None:
            self.connect_status_label.setText(
                f"Device not found\n\nCheck the Device ID and try again. ({device_code})"
            )
            return

        if not result["online"]:
            last_seen_text = datetime.fromtimestamp(result["last_seen"]).strftime("%I:%M %p") \
                if result["last_seen"] else "unknown"
            self.connect_status_label.setText(
                f"Device not available\n\n{device_code} is currently offline.\n"
                f"Last seen: {last_seen_text}"
            )
            return

        self.connect_status_label.setText(f"✓ Found {result['device_name']} — connecting…")
        add_recent_device(device_code, result["device_name"])
        self._refresh_recent_devices()
        QDesktopServices.openUrl(QUrl(result["tunnel_url"]))

    def closeEvent(self, event) -> None:
        self._auto_refresh_timer.stop()
        super().closeEvent(event)

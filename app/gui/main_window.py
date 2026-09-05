"""
Main window for LocalShare.

Phase 2: GUI shell + drag/drop + shared-items list.
Phase 3: Start/Stop Sharing now runs a real FastAPI server in a
background thread; the address shown is live and Copy Address works.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import tempfile
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.drop_zone import DropZone
from app.gui.gradient_background import AnimatedGradientBackground, STYLES
from app.gui.custom_theme_dialog import CustomThemeDialog
from app.gui.hover_button import HoverGlowButton
import app.gui.hover_button as hover_button_module
from app.gui.qr_widget import generate_qr_pixmap
from app.gui.theme import (
    ACCENT_PRESETS,
    CARD_BORDER,
    CARD_RADIUS,
    CARD_SHADOW_BLUR,
    FULL_KEYS,
    THEMES,
    build_stylesheet,
    theme_to_json,
    theme_from_json,
)
from app.paths import ICON_PATH
from app.gui.update_checker import (
    check_for_update,
    download_build,
    find_latest_build,
    open_with_default_app,
)
from app.server.auth import AccessControl
from app.server.http_server import ServerHandle
from app.network.discovery_service import DeviceDiscoveryService
from app.server.tunnel import TunnelHandle
from app.server.webdav_server import WebDavHandle
from app.state import ShareManager, SharedItem
from app.version import APP_VERSION


class _ServerStartWorker(QThread):
    """Starts the server off the GUI thread (binding + uvicorn readiness can take a moment)."""

    finished_ok = Signal(str)  # address
    finished_error = Signal(str)  # error message

    def __init__(self, handle: ServerHandle) -> None:
        super().__init__()
        self._handle = handle

    def run(self) -> None:
        try:
            address = self._handle.start()
            self.finished_ok.emit(address or "")
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI, never crash
            self.finished_error.emit(str(exc))


class _ServerStopWorker(QThread):
    """Stops the server off the GUI thread (joins the uvicorn thread, up to a few seconds)."""

    finished = Signal()

    def __init__(self, handle: ServerHandle) -> None:
        super().__init__()
        self._handle = handle

    def run(self) -> None:
        self._handle.stop()
        self.finished.emit()


class _UpdateCheckWorker(QThread):
    """
    Runs the network request off the GUI thread so a slow/unreachable
    address doesn't freeze the window. Also checks whether the other
    instance is sharing something that looks like an installer, so an
    "Install Now" option is ready immediately rather than needing a
    second round-trip after the user decides they want it.
    """

    finished = Signal(object, object)  # UpdateCheckResult, LatestBuildResult | None

    def __init__(self, address: str) -> None:
        super().__init__()
        self._address = address

    def run(self) -> None:
        result = check_for_update(self._address, APP_VERSION)
        build_result = find_latest_build(self._address) if (result.ok and result.is_newer) else None
        self.finished.emit(result, build_result)


class _UpdateDownloadWorker(QThread):
    """Downloads the update installer off the GUI thread — this can take
    a while for a large file, and must not freeze the window."""

    finished_ok = Signal(str)  # local file path
    finished_error = Signal(str)

    def __init__(self, address: str, download_url: str, filename: str) -> None:
        super().__init__()
        self._address = address
        self._download_url = download_url
        self._filename = filename

    def run(self) -> None:
        try:
            local_path = download_build(self._address, self._download_url, self._filename)
            self.finished_ok.emit(local_path)
        except RuntimeError as exc:
            self.finished_error.emit(str(exc))


class _TunnelStartWorker(QThread):
    """
    Starts the ngrok tunnel off the GUI thread — connecting and
    waiting for it to report its public URL takes a few seconds
    (longer on first use, when pyngrok downloads the ngrok binary),
    which would freeze the window if run directly on the main thread.
    """

    finished_ok = Signal(str)  # public_url
    finished_error = Signal(str)  # error message

    def __init__(self, tunnel_handle: TunnelHandle, local_port: int, auth_token: str) -> None:
        super().__init__()
        self._handle = tunnel_handle
        self._local_port = local_port
        self._auth_token = auth_token

    def run(self) -> None:
        try:
            public_url = self._handle.start(self._local_port, self._auth_token)
            self.finished_ok.emit(public_url)
        except RuntimeError as exc:
            self.finished_error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LocalShare")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(520, 720)
        self.setMinimumSize(380, 420)  # small enough to shrink comfortably, never unusably tiny

        _persisted = QSettings("LocalShare", "LocalShare")
        self._custom_themes: dict[str, dict] = self._load_custom_themes(_persisted)
        self._current_theme_name = _persisted.value("theme_name", "Default Dark")
        if self._current_theme_name not in THEMES and self._current_theme_name not in self._custom_themes:
            self._current_theme_name = "Default Dark"  # guards against a stale/invalid saved name
        self._custom_accent = _persisted.value("custom_accent", None) or None  # QSettings can return "" instead of None
        self._bg_image_path: str | None = _persisted.value("image_path", None) or None
        self._bg_video_path: str | None = _persisted.value("video_path", None) or None
        self._card_radius = _persisted.value("card_radius", "Medium")
        if self._card_radius not in CARD_RADIUS:
            self._card_radius = "Medium"
        self._card_border = _persisted.value("card_border", "Subtle")
        if self._card_border not in CARD_BORDER:
            self._card_border = "Subtle"
        self._card_shadow = _persisted.value("card_shadow", "None")
        if self._card_shadow not in CARD_SHADOW_BLUR:
            self._card_shadow = "None"
        self._surface_alpha = float(_persisted.value("surface_alpha", 1.0))
        self._local_pin_preference: bool = False  # your own PIN choice for Local mode, remembered separately from Global's forced-on state
        self.theme_colors = self._compute_theme_colors()
        # Applied at the QApplication level, not just this window — a
        # per-widget stylesheet doesn't reliably cascade to separate
        # top-level windows (QDialog, QMessageBox), which was leaving
        # the Settings dialog and popups rendering unstyled/white
        # against the app's dark theme. The application level is what
        # Qt actually guarantees reaches every window.
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme_colors, self._current_card_style()))

        self.share_manager = ShareManager()
        self.share_manager.on_change(self._refresh_shared_list)

        self.access_control = AccessControl()
        self.server_handle = ServerHandle(self.share_manager, self.access_control)
        self.webdav_handle = WebDavHandle(self.share_manager)
        self.tunnel_handle = TunnelHandle()
        try:
            device_name = socket.gethostname()
        except OSError:
            device_name = "LocalShare"
        self.discovery_service = DeviceDiscoveryService(
            name=device_name,
            version=APP_VERSION,
            # Only announces itself while actually sharing something —
            # a device just sitting idle with nothing shared has
            # nothing useful for a "nearby device" to connect to.
            get_address=lambda: self.server_handle.address if self.server_handle.is_running else None,
        )
        self._start_worker: _ServerStartWorker | None = None
        self._stop_worker: _ServerStopWorker | None = None
        self._tunnel_worker: _TunnelStartWorker | None = None
        self._local_address: str | None = None
        self._auto_update_worker: _UpdateCheckWorker | None = None
        self._update_download_worker: _UpdateDownloadWorker | None = None
        self._last_checked_address: str | None = None

        self._build_ui()

        # Resume shares first (if enabled) — this may itself trigger
        # auto-start-on-add if that's also enabled, which is the
        # correct behavior: restored shares should come back online
        # the same way freshly-dropped ones would.
        self._maybe_resume_previous_shares()

        # Independent of resuming shares: start the server immediately
        # on launch if that preference is on, even with nothing shared
        # yet (e.g. someone who adds files a moment later via Explorer
        # drag-and-drop still wants the server already listening).
        if QSettings("LocalShare", "LocalShare").value("auto_start_on_launch", False, type=bool):
            if not self.server_handle.is_running:
                self._begin_server_start()

        # Slight delay so this doesn't compete with the splash screen /
        # initial window rendering — a background check, not a blocker.
        QTimer.singleShot(2000, self._auto_check_for_updates_on_startup)

        if not QSettings("LocalShare", "LocalShare").value("has_shown_welcome_guide", False, type=bool):
            QTimer.singleShot(600, self._show_welcome_guide)

    # -- UI construction -----------------------------------------------------------
    def _build_ui(self) -> None:
        # Wrapped in a scroll area so the window stays genuinely
        # resizable in both directions: if it's ever made smaller than
        # the content needs (a lot has been added to this window over
        # time — WebDAV status, QR code, update checker, etc.), a
        # scrollbar appears instead of anything getting clipped or cut off.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll_area)

        central = AnimatedGradientBackground()
        central.set_colors(self.theme_colors["bg"], self.theme_colors["accent"])
        self.gradient_background = central
        scroll_area.setWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("LocalShare")
        title.setObjectName("Title")
        title_row.addWidget(title)

        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet(
            f"color: {self.theme_colors['text_dim']}; font-size: 12px; padding-top: 6px;"
        )
        self._version_label = version_label  # kept for theme refresh
        title_row.addWidget(version_label)

        title_row.addStretch()

        self.setup_guide_btn = HoverGlowButton("❓ Setup Guide", glow_color=self.theme_colors["accent"])
        self.setup_guide_btn.setToolTip("Getting-started steps, including setting up Internet Sharing")
        self.setup_guide_btn.clicked.connect(self._show_welcome_guide)
        title_row.addWidget(self.setup_guide_btn)

        self.settings_btn = HoverGlowButton("⚙️ Settings", glow_color=self.theme_colors["accent"])
        self.settings_btn.setToolTip("Theme, accent color, and background options")
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        title_row.addWidget(self.settings_btn)

        root.addLayout(title_row)

        # These live inside the Settings dialog (built below), not the
        # main window layout — created here so they're available for
        # theme-refresh/glow-color updates the same way as before.
        self.accent_color_btn = HoverGlowButton("🎨 Custom…", glow_color=self.theme_colors["accent"])
        self.accent_color_btn.setToolTip("Choose a custom accent color")
        self.accent_color_btn.clicked.connect(self._choose_accent_color)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        if self._custom_themes:
            self.theme_combo.addItems(self._custom_themes.keys())
        self.theme_combo.setCurrentText(self._current_theme_name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_selected)

        # Small clickable color-swatch buttons, one per accent preset —
        # built once here; styling (rounded, filled with that preset's
        # color) doesn't change with the app theme, so no glow-color
        # refresh needed for these like the other buttons.
        self.accent_preset_buttons: list[QPushButton] = []
        for preset_name, preset_hex in ACCENT_PRESETS.items():
            swatch = QPushButton()
            swatch.setFixedSize(22, 22)
            swatch.setToolTip(preset_name)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setStyleSheet(
                f"background-color: {preset_hex}; border-radius: 11px; border: 1px solid rgba(255,255,255,0.15);"
            )
            swatch.clicked.connect(lambda checked=False, hex_color=preset_hex: self._choose_accent_preset(hex_color))
            self.accent_preset_buttons.append(swatch)

        _bg_settings = QSettings("LocalShare", "LocalShare")
        _persisted_bg_mode = _bg_settings.value("background_mode", "solid")
        if _persisted_bg_mode not in ("solid", "gradient", "image", "video"):
            _persisted_bg_mode = "solid"
        _persisted_gradient_style = _bg_settings.value("gradient_style", STYLES[0] if STYLES else "Sweep")
        _persisted_image_path = _bg_settings.value("image_path", "") or None
        _persisted_image_position = _bg_settings.value("image_position", "Center")
        _persisted_image_scaling = _bg_settings.value("image_scaling", "Fill")
        _persisted_image_opacity = float(_bg_settings.value("image_opacity", 1.0))
        _persisted_overlay_opacity = float(_bg_settings.value("overlay_opacity", 0.35))
        _persisted_video_path = _bg_settings.value("video_path", "") or None
        _persisted_video_loop = _bg_settings.value("video_loop", True, type=bool)
        _persisted_video_autoplay = _bg_settings.value("video_autoplay", True, type=bool)
        _persisted_video_opacity = float(_bg_settings.value("video_opacity", 1.0))
        _persisted_video_speed = float(_bg_settings.value("video_speed", 1.0))

        # -- mode selector --------------------------------------------------------------
        self.bg_mode_group = QButtonGroup(self)
        self.bg_mode_solid_radio = QRadioButton("Solid")
        self.bg_mode_gradient_radio = QRadioButton("Gradient")
        self.bg_mode_image_radio = QRadioButton("Image")
        self.bg_mode_video_radio = QRadioButton("Video")
        for btn in (self.bg_mode_solid_radio, self.bg_mode_gradient_radio, self.bg_mode_image_radio, self.bg_mode_video_radio):
            self.bg_mode_group.addButton(btn)
        {"solid": self.bg_mode_solid_radio, "gradient": self.bg_mode_gradient_radio,
         "image": self.bg_mode_image_radio, "video": self.bg_mode_video_radio}[_persisted_bg_mode].setChecked(True)

        # -- gradient sub-panel --------------------------------------------------------------
        self.gradient_style_combo = QComboBox()
        self.gradient_style_combo.addItems(STYLES)
        if _persisted_gradient_style in STYLES:
            self.gradient_style_combo.setCurrentText(_persisted_gradient_style)
        self.gradient_style_combo.currentTextChanged.connect(self.gradient_background.set_style)
        self.gradient_style_combo.currentTextChanged.connect(
            lambda style: QSettings("LocalShare", "LocalShare").setValue("gradient_style", style)
        )

        # -- image sub-panel --------------------------------------------------------------
        self.choose_image_btn = HoverGlowButton("Choose Image…", glow_color=self.theme_colors["accent"])
        self.choose_image_btn.clicked.connect(self._choose_background_image)
        self.image_path_label = QLabel("None")
        if _persisted_image_path:
            self._set_elided_label(self.image_path_label, os.path.basename(_persisted_image_path))
        self.image_position_combo = QComboBox()
        self.image_position_combo.addItems(["Center", "Top", "Bottom", "Left", "Right"])
        self.image_position_combo.setCurrentText(_persisted_image_position)
        self.image_scaling_combo = QComboBox()
        self.image_scaling_combo.addItems(["Fill", "Fit", "Stretch", "Original"])
        self.image_scaling_combo.setCurrentText(_persisted_image_scaling)
        self.image_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.image_opacity_slider.setRange(0, 100)
        self.image_opacity_slider.setValue(int(_persisted_image_opacity * 100))
        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(0, 100)
        self.overlay_opacity_slider.setValue(int(_persisted_overlay_opacity * 100))
        for widget in (self.image_position_combo, self.image_scaling_combo, self.image_opacity_slider, self.overlay_opacity_slider):
            (widget.currentTextChanged if isinstance(widget, QComboBox) else widget.valueChanged).connect(
                self._apply_image_background_settings
            )

        # -- video sub-panel --------------------------------------------------------------
        self.choose_video_btn = HoverGlowButton("Choose Video…", glow_color=self.theme_colors["accent"])
        self.choose_video_btn.clicked.connect(self._choose_background_video)
        self.video_path_label = QLabel("None")
        if _persisted_video_path:
            self._set_elided_label(self.video_path_label, os.path.basename(_persisted_video_path))
        self.video_loop_checkbox = QCheckBox("Loop video")
        self.video_loop_checkbox.setChecked(_persisted_video_loop)
        self.video_mute_checkbox = QCheckBox("Mute audio")
        self.video_mute_checkbox.setChecked(True)
        self.video_mute_checkbox.setEnabled(False)  # always muted — see gradient_background.py; nothing to toggle
        self.video_mute_checkbox.setToolTip("Background video never has audio output attached — always silent.")
        self.video_autoplay_checkbox = QCheckBox("Play automatically")
        self.video_autoplay_checkbox.setChecked(_persisted_video_autoplay)
        self.video_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.video_opacity_slider.setRange(0, 100)
        self.video_opacity_slider.setValue(int(_persisted_video_opacity * 100))
        self.video_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.video_speed_slider.setRange(50, 200)  # 0.5x .. 2.0x
        self.video_speed_slider.setValue(int(_persisted_video_speed * 100))
        for widget in (self.video_loop_checkbox, self.video_autoplay_checkbox, self.video_opacity_slider, self.video_speed_slider):
            (widget.toggled if isinstance(widget, QCheckBox) else widget.valueChanged).connect(
                self._apply_video_background_settings
            )

        self.bg_mode_solid_radio.toggled.connect(lambda checked: checked and self._set_background_mode("solid"))
        self.bg_mode_gradient_radio.toggled.connect(lambda checked: checked and self._set_background_mode("gradient"))
        self.bg_mode_image_radio.toggled.connect(lambda checked: checked and self._set_background_mode("image"))
        self.bg_mode_video_radio.toggled.connect(lambda checked: checked and self._set_background_mode("video"))

        # Apply the restored state to the actual widget now — the
        # signal connections above were wired up after the persisted
        # values were loaded, so restoring at startup needs this
        # explicit call rather than relying on signals alone.
        self.gradient_background.set_style(_persisted_gradient_style if _persisted_gradient_style in STYLES else STYLES[0])
        if _persisted_image_path:
            self.gradient_background.set_image(
                _persisted_image_path, _persisted_image_position, _persisted_image_scaling,
                _persisted_image_opacity, _persisted_overlay_opacity,
            )
        if _persisted_video_path:
            self.gradient_background.set_video(
                _persisted_video_path, _persisted_video_loop, True, _persisted_video_autoplay,
                _persisted_video_opacity, _persisted_video_speed,
            )
        self.gradient_background.set_mode(_persisted_bg_mode)

        # -- particle overlay: Snow/Rain/Fire on top of ANY background mode --
        _persisted_particle_overlay = _bg_settings.value("particle_overlay", "None")
        self.particle_overlay_combo = QComboBox()
        self.particle_overlay_combo.addItems(["None", "Snow", "Rain", "Fire", "Ink"])
        if _persisted_particle_overlay in ("None", "Snow", "Rain", "Fire", "Ink"):
            self.particle_overlay_combo.setCurrentText(_persisted_particle_overlay)
        self.particle_overlay_combo.currentTextChanged.connect(self._set_particle_overlay)
        self.gradient_background.set_particle_overlay(
            None if _persisted_particle_overlay == "None" else _persisted_particle_overlay
        )

        # -- card style + transparency --------------------------------------------------------------
        self.card_radius_combo = QComboBox()
        self.card_radius_combo.addItems(CARD_RADIUS.keys())
        self.card_radius_combo.setCurrentText(self._card_radius)
        self.card_radius_combo.currentTextChanged.connect(self._set_card_radius)

        self.card_border_combo = QComboBox()
        self.card_border_combo.addItems(CARD_BORDER.keys())
        self.card_border_combo.setCurrentText(self._card_border)
        self.card_border_combo.currentTextChanged.connect(self._set_card_border)

        self.card_shadow_combo = QComboBox()
        self.card_shadow_combo.addItems(CARD_SHADOW_BLUR.keys())
        self.card_shadow_combo.setCurrentText(self._card_shadow)
        self.card_shadow_combo.currentTextChanged.connect(self._set_card_shadow)

        self.transparency_slider = QSlider(Qt.Orientation.Horizontal)
        self.transparency_slider.setRange(30, 100)  # never fully invisible — 30% is the floor
        self.transparency_slider.setValue(int(self._surface_alpha * 100))
        # sliderReleased, not valueChanged: _set_surface_alpha re-applies
        # the ENTIRE application's stylesheet, which is genuinely
        # expensive — valueChanged fires continuously while dragging
        # (potentially dozens of times a second), so wiring it there
        # was re-running that expensive full-app restyle on every pixel
        # of drag movement. This is almost certainly what looked like
        # "delay" — applying once on release is the standard pattern
        # for exactly this kind of slider.
        self.transparency_slider.sliderReleased.connect(
            lambda: self._set_surface_alpha(self.transparency_slider.value())
        )

        # -- glass effect: experimental, see _refresh_glass_backdrop() --
        _persisted_glass_effect = QSettings("LocalShare", "LocalShare").value("glass_effect", "Off")
        if _persisted_glass_effect not in ("Off", "Subtle", "Medium", "Strong"):
            _persisted_glass_effect = "Off"
        self.glass_effect_combo = QComboBox()
        self.glass_effect_combo.addItems(["Off", "Subtle", "Medium", "Strong"])
        self.glass_effect_combo.setCurrentText(_persisted_glass_effect)
        self.glass_effect_combo.currentTextChanged.connect(self._set_glass_effect)
        self._glass_effect = _persisted_glass_effect
        self._glass_temp_path = os.path.join(tempfile.gettempdir(), "localshare_glass_backdrop.png")

        # _build_settings_dialog() is called at the end of _build_ui(),
        # once every widget it references (including the auto-update
        # checkbox, created further down) actually exists.

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.pathsDropped.connect(self._on_paths_dropped)
        root.addWidget(self.drop_zone)

        # Or browse manually (drag-and-drop isn't the only way in)
        browse_row = QHBoxLayout()
        browse_files_btn = QPushButton("Add Files…")
        browse_files_btn.clicked.connect(self._browse_files)
        browse_folder_btn = QPushButton("Add Folder…")
        browse_folder_btn.clicked.connect(self._browse_folder)
        browse_row.addWidget(browse_files_btn)
        browse_row.addWidget(browse_folder_btn)
        browse_row.addStretch()
        root.addLayout(browse_row)

        # Shared items section
        section_label = QLabel("SHARED ITEMS")
        section_label.setObjectName("SectionLabel")
        root.addWidget(section_label)

        self.shared_list = QListWidget()
        self.shared_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.shared_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.shared_list.customContextMenuRequested.connect(self._show_item_context_menu)
        root.addWidget(self.shared_list, stretch=1)

        # Server status
        status_row = QHBoxLayout()
        self.status_dot = QLabel("○")
        self.status_dot.setObjectName("StatusDot")
        self.status_label = QLabel("Ready to Share")
        self.address_label = QLabel("Address: —")
        self.address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.address_label)
        root.addLayout(status_row)

        # WebDAV (experimental — see tooltip). Off by default: it's the
        # weaker-security, less-reliable path, so it should be opt-in.
        # -- Sharing mode -----------------------------------------------------------
        mode_label = QLabel("SHARING MODE")
        mode_label.setObjectName("SectionLabel")
        root.addWidget(mode_label)

        mode_row = QHBoxLayout()
        self.local_only_radio = QRadioButton("Local Network Only")
        self.local_only_radio.setChecked(True)
        self.internet_radio = QRadioButton("Global")
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.addButton(self.local_only_radio)
        self.mode_button_group.addButton(self.internet_radio)
        mode_row.addWidget(self.local_only_radio)
        mode_row.addWidget(self.internet_radio)
        root.addLayout(mode_row)
        self.internet_radio.toggled.connect(self._on_mode_changed)

        # Explicit "you are here" line — the radio dots alone are a
        # small, easy-to-miss signal, especially before the indicator
        # styling fix; this makes the active mode unambiguous at a glance.
        self.mode_indicator_label = QLabel("● Local Network Only selected")
        self.mode_indicator_label.setStyleSheet(
            f"color: {self.theme_colors['accent']}; font-size: 12px; font-weight: 600;"
        )
        root.addWidget(self.mode_indicator_label)

        # The ngrok authtoken field lives in Settings → Sharing, not
        # here — this row is about mode selection, that's about
        # configuring what Global mode needs to actually work.

        self.tunnel_status_label = QLabel("")
        self.tunnel_status_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.tunnel_status_label.setWordWrap(True)
        self.tunnel_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tunnel_status_label.hide()
        root.addWidget(self.tunnel_status_label)

        # -- PIN protection -----------------------------------------------------------
        # Local mode: a real checkbox — PIN is optional, user's choice.
        # Global mode: no checkbox at all (nothing that looks toggleable),
        # just a plain label stating it's mandatory — see _on_mode_changed.
        pin_row = QHBoxLayout()
        self.pin_checkbox = QCheckBox("Require PIN to access")
        self.pin_checkbox.toggled.connect(self._on_pin_checkbox_toggled)
        pin_row.addWidget(self.pin_checkbox)

        self.pin_mandatory_label = QLabel("🔒 PIN required (mandatory for Global sharing)")
        self.pin_mandatory_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 13px;")
        self.pin_mandatory_label.hide()
        pin_row.addWidget(self.pin_mandatory_label)

        self.custom_pin_input = QLineEdit()
        self.custom_pin_input.setPlaceholderText("Custom PIN (optional)")
        self.custom_pin_input.setMaxLength(12)
        self.custom_pin_input.hide()
        pin_row.addWidget(self.custom_pin_input)
        root.addLayout(pin_row)

        self.pin_display_label = QLabel("")
        self.pin_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin_display_label.setStyleSheet(
            f"color: {self.theme_colors['accent']}; font-size: 22px; font-weight: 700; letter-spacing: 4px;"
        )
        self.pin_display_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pin_display_label.hide()
        root.addWidget(self.pin_display_label)

        self.webdav_checkbox = QCheckBox("Also enable Network Drive access")
        self.webdav_checkbox.setToolTip(
            "Lets Windows Explorer or your file manager show this share as a\n"
            "mapped network drive, instead of only working through a browser.\n\n"
            "On Windows, this requires running LocalShare as Administrator\n"
            "(a technical limitation of Windows itself, not this app).\n\n"
            "Other limits: only shared FOLDERS show up this way (not\n"
            "individually-shared files), and it can be slow or unreliable for\n"
            "very large transfers. For big files, use the browser address instead."
        )
        root.addWidget(self.webdav_checkbox)

        self.webdav_status_label = QLabel("")
        self.webdav_status_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.webdav_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.webdav_status_label.setWordWrap(True)
        self.webdav_status_label.hide()
        root.addWidget(self.webdav_status_label)

        # QR code — lets a phone scan the address instead of typing it.
        # Shown centered, only while the server is running.
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.hide()
        root.addWidget(self.qr_label)

        self.qr_caption_label = QLabel("Scan with a phone to open this share")
        self.qr_caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_caption_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.qr_caption_label.hide()
        root.addWidget(self.qr_caption_label)

        self.save_qr_btn = HoverGlowButton("Save QR Code…", glow_color=self.theme_colors["accent"])
        self.save_qr_btn.clicked.connect(self._save_qr_code)
        self.save_qr_btn.hide()
        root.addWidget(self.save_qr_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._current_qr_pixmap = None

        # Action buttons
        action_row = QHBoxLayout()
        self.copy_address_btn = HoverGlowButton("Copy Address", glow_color=self.theme_colors["accent"])
        self.copy_address_btn.setEnabled(False)  # enabled once server is running (Phase 3)
        self.copy_address_btn.clicked.connect(self._copy_address)

        self.toggle_server_btn = HoverGlowButton("Start Sharing", glow_color=self.theme_colors["accent"])
        self.toggle_server_btn.setObjectName("PrimaryButton")
        self.toggle_server_btn.clicked.connect(self._on_toggle_server_clicked)

        action_row.addWidget(self.copy_address_btn)
        action_row.addStretch()
        action_row.addWidget(self.toggle_server_btn)
        root.addLayout(action_row)

        # Update checking — points at another running LocalShare instance
        # (typically the "main" copy someone keeps up to date) rather than
        # any internet server, since this app has no central host.
        update_row = QHBoxLayout()
        self.update_source_input = QLineEdit()
        saved_source = QSettings("LocalShare", "LocalShare").value("update_source", "")
        # Shown as a placeholder hint, not pre-filled text — the field
        # starts empty and ready to type a new address into, rather
        # than making you delete the old one first. The saved address
        # still works automatically for the startup auto-check (below),
        # which reads it directly rather than from this field's text.
        self.update_source_input.setPlaceholderText(
            f"e.g. 192.168.1.104:8765 (last used: {saved_source})"
            if saved_source
            else "Update source address (e.g. 192.168.1.104:8765)"
        )
        update_row.addWidget(self.update_source_input, stretch=1)

        self.check_update_btn = HoverGlowButton("Check for Updates", glow_color=self.theme_colors["accent"])
        self.check_update_btn.clicked.connect(self._check_for_updates)
        update_row.addWidget(self.check_update_btn)
        root.addLayout(update_row)

        self.auto_check_updates_checkbox = QCheckBox("Automatically check for updates on startup")
        self.auto_check_updates_checkbox.setToolTip(
            "Silently checks the address above shortly after launch — only speaks up "
            "if a newer version is actually found. Doesn't require re-entering the "
            "address each time; it's remembered from your last manual check."
        )
        auto_check_default = QSettings("LocalShare", "LocalShare").value(
            "auto_check_updates", True, type=bool
        )
        self.auto_check_updates_checkbox.setChecked(auto_check_default)
        self.auto_check_updates_checkbox.toggled.connect(
            lambda checked: QSettings("LocalShare", "LocalShare").setValue(
                "auto_check_updates", checked
            )
        )
        # Lives in the Settings dialog (built below), not directly in
        # the main window — same consolidation as theme/accent/gradient.

        self.credit_label = QLabel("Developed by ANARKALI")
        self.credit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.credit_label.setStyleSheet(
            f"color: {self.theme_colors['text_dim']}; font-size: 11px; letter-spacing: 0.5px;"
        )
        root.addWidget(self.credit_label)

        self._build_settings_dialog()
        self._apply_card_style_to_widgets()

    # -- drop / browse handlers -----------------------------------------------------------
    def _on_paths_dropped(self, paths: list[str]) -> None:
        skipped = []
        for path in paths:
            item = self.share_manager.add_path(path)
            if item is None:
                skipped.append(path)
        if skipped:
            QMessageBox.warning(
                self,
                "Some items couldn't be added",
                "These paths no longer exist or aren't accessible:\n" + "\n".join(skipped),
            )

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to share")
        for p in paths:
            self.share_manager.add_path(p)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a folder to share")
        if path:
            self.share_manager.add_path(path)

    # -- shared list rendering -----------------------------------------------------------
    def _refresh_shared_list(self) -> None:
        self.shared_list.clear()
        for item in self.share_manager.all_items():
            icon = "📁" if item.is_dir else "📄"
            list_item = QListWidgetItem(f"{icon}  {item.name}")
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            list_item.setToolTip(item.path)
            self.shared_list.addItem(list_item)
        self._persist_shared_paths()
        self._maybe_auto_start_sharing()

    def _persist_shared_paths(self) -> None:
        """Remembers what's currently shared, so 'Automatically resume
        previous shares' (Settings -> Sharing) has something to restore
        on next launch."""
        paths = [item.path for item in self.share_manager.all_items()]
        QSettings("LocalShare", "LocalShare").setValue("last_shared_paths", paths)

    def _maybe_resume_previous_shares(self) -> None:
        settings = QSettings("LocalShare", "LocalShare")
        if not settings.value("auto_resume_shares", False, type=bool):
            return
        saved_paths = settings.value("last_shared_paths", [])
        if not saved_paths:
            return
        if isinstance(saved_paths, str):
            saved_paths = [saved_paths]  # QSettings collapses a single-item list to a bare string
        for path in saved_paths:
            # add_path() already handles a path that no longer exists
            # by returning None — resuming is inherently best-effort,
            # so a missing file is silently skipped rather than erroring
            self.share_manager.add_path(path)

    def _show_item_context_menu(self, pos) -> None:
        list_item = self.shared_list.itemAt(pos)
        if list_item is None:
            return
        item_id = list_item.data(Qt.ItemDataRole.UserRole)
        shared_item: SharedItem | None = self.share_manager.get(item_id)
        if shared_item is None:
            return

        menu = QMenu(self)

        open_action = QAction("Open in File Explorer", self)
        open_action.triggered.connect(lambda: self._open_in_explorer(shared_item))
        menu.addAction(open_action)

        menu.addSeparator()

        remove_action = QAction("Remove from sharing", self)
        remove_action.triggered.connect(lambda: self.share_manager.remove(item_id))
        menu.addAction(remove_action)
        menu.exec(self.shared_list.mapToGlobal(pos))

    def _open_in_explorer(self, shared_item: SharedItem) -> None:
        """
        Opens the item's location in the OS file manager — for a folder,
        opens the folder itself; for a file, opens its containing folder
        with the file visible (QDesktopServices handles this distinction
        automatically per-platform).
        """
        if not shared_item.exists:
            QMessageBox.warning(
                self, "Can't open location", "This item no longer exists at its original path."
            )
            return
        target = shared_item.path if shared_item.is_dir else os.path.dirname(shared_item.path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    # -- server controls -----------------------------------------------------------
    def _on_toggle_server_clicked(self) -> None:
        if self.server_handle.is_running:
            self._confirm_stop_sharing()
            return

        if len(self.share_manager) == 0:
            QMessageBox.information(
                self, "Nothing to share", "Drag in a file or folder before starting the server."
            )
            return

        self._begin_server_start()

    def _confirm_stop_sharing(self) -> None:
        reply = QMessageBox.question(
            self,
            "Stop sharing?",
            "This will disconnect active sharing sessions.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._stop_server()

    def _begin_server_start(self) -> None:
        """
        The actual "start the server" logic, factored out so both the
        manual Start Sharing button and automatic sharing-on-add (see
        _maybe_auto_start_sharing) go through the exact same path —
        one place that configures PIN protection and kicks off the
        background start worker, not two copies that could drift apart.
        """
        if self.server_handle.is_running:
            return
        if self._start_worker is not None and self._start_worker.isRunning():
            # A start is already in progress (this genuinely happens at
            # launch: "auto-resume shares" can trigger "auto-start on
            # add" at nearly the same moment "auto-start on launch"
            # fires separately). Without this guard, a second call here
            # would overwrite self._start_worker while the first
            # QThread is still running — its only Python reference
            # gone, Qt destroys it mid-flight, which is exactly the
            # "QThread: Destroyed while thread is still running" crash.
            return

        # No authtoken validation needed here specifically — tunnel.py's
        # start() checks for one when the tunnel actually connects and
        # raises a clear, actionable error if it's missing, rather than
        # duplicating that check at every call site that might trigger
        # Global mode.

        # Configure PIN protection BEFORE the server starts, so the
        # very first request it ever serves is already covered — not
        # a window where the share is briefly open before the PIN
        # kicks in.
        if self.pin_checkbox.isChecked():
            custom_pin = self.custom_pin_input.text().strip() or None
            actual_pin = self.access_control.enable(pin=custom_pin)
            self._show_pin(actual_pin)
        else:
            self.access_control.disable()
            self.pin_display_label.hide()

        self.toggle_server_btn.setEnabled(False)
        self.toggle_server_btn.setText("Starting…")
        self.status_dot.setText("◌")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['accent']}; font-size: 14px;")
        self.status_label.setText("Starting server…")

        self._start_worker = _ServerStartWorker(self.server_handle)
        self._start_worker.finished_ok.connect(self._on_server_started)
        self._start_worker.finished_error.connect(self._on_server_start_failed)
        self._start_worker.start()

    def _maybe_auto_start_sharing(self) -> None:
        """
        Starts the server automatically the instant the first item is
        shared, per Settings -> Sharing -> "Automatically start sharing
        when files are added" (on by default). Only triggers going
        from empty to non-empty — adding more items afterward, or
        re-adding after an explicit Stop Sharing, doesn't restart
        anything on its own.
        """
        if self.server_handle.is_running:
            return
        if self._start_worker is not None and self._start_worker.isRunning():
            return  # already starting
        if len(self.share_manager) == 0:
            return
        if not QSettings("LocalShare", "LocalShare").value("auto_start_on_add", True, type=bool):
            return
        self._begin_server_start()

    def _show_pin(self, pin: str) -> None:
        self.pin_display_label.setText(f"PIN: {pin}")
        self.pin_display_label.show()

    def _build_share_url(self, base_address: str) -> str:
        """Appends the access token to a share address when PIN protection
        is on, so a QR code or copied link grants one-tap access instead
        of forcing the PIN to be retyped."""
        if self.access_control.enabled:
            return f"{base_address}/?token={self.access_control.token}"
        return base_address

    def _on_server_started(self, address: str) -> None:
        self.status_dot.setText("●")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['success']}; font-size: 14px;")
        self.status_label.setText("Sharing")
        self._local_address = address
        self.copy_address_btn.setEnabled(True)
        self.toggle_server_btn.setText("Stop Sharing")
        self.toggle_server_btn.setEnabled(True)
        # Locked while running to avoid a confusing mid-session change —
        # switching modes or PIN settings means stopping and restarting.
        self.webdav_checkbox.setEnabled(False)
        self.local_only_radio.setEnabled(False)
        self.internet_radio.setEnabled(False)
        self.pin_checkbox.setEnabled(False)
        self.custom_pin_input.setEnabled(False)

        if self.internet_radio.isChecked():
            # Don't show the LAN address/QR yet — it will NOT work for
            # someone outside this network, and showing it now (even
            # briefly) would be actively misleading. Wait for the
            # tunnel to actually connect before showing anything.
            self.address_label.setText("Address: connecting to internet tunnel…")
            self._hide_qr_code()
            self._start_tunnel()
        else:
            self.address_label.setText(f"Address: {self._build_share_url(address)}")
            self._show_qr_code(self._build_share_url(address))

        if self.webdav_checkbox.isChecked():
            self._start_webdav()

    def _start_tunnel(self) -> None:
        port = self.server_handle.port
        auth_token = QSettings("LocalShare", "LocalShare").value("ngrok_auth_token", "")
        self.tunnel_status_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.tunnel_status_label.setText("Starting internet tunnel (ngrok)…")
        self.tunnel_status_label.show()

        self._tunnel_worker = _TunnelStartWorker(self.tunnel_handle, port, auth_token)
        self._tunnel_worker.finished_ok.connect(self._on_tunnel_started)
        self._tunnel_worker.finished_error.connect(self._on_tunnel_failed)
        self._tunnel_worker.start()

    def _on_tunnel_started(self, public_url: str) -> None:
        share_url = self._build_share_url(public_url)
        self.tunnel_status_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.tunnel_status_label.setText(f"Internet address: {share_url}")
        self.address_label.setText(f"Address: {share_url}")
        self._show_qr_code(share_url)

    def _on_tunnel_failed(self, error: str) -> None:
        self.tunnel_status_label.setStyleSheet(
            f"color: {self.theme_colors['danger']}; font-size: 12px; font-weight: 600;"
        )
        self.tunnel_status_label.setText(
            f"⚠ Internet sharing failed: {error}\n"
            f"Your share is NOT reachable from outside your network right now."
        )
        self.tunnel_status_label.show()
        self.address_label.setText("Address: internet tunnel failed — see message below")
        self._hide_qr_code()
        QMessageBox.warning(
            self,
            "Internet sharing failed",
            f"Couldn't start internet sharing:\n\n{error}\n\n"
            f"Your files are only reachable on your local network right now, "
            f"not from the internet. Fix the issue above, then click Stop "
            f"Sharing and Start Sharing again to retry.",
        )

    def _on_mode_changed(self, internet_checked: bool) -> None:
        if internet_checked:
            self.mode_indicator_label.setText("● Global selected")
            # Internet exposure without a PIN is a real risk (see
            # tunnel.py / README) — mandatory here, and shown as a plain
            # statement rather than a disabled checkbox, so it doesn't
            # look like a toggle someone could turn off if only they
            # clicked the right spot.
            self.pin_checkbox.hide()
            self.pin_mandatory_label.show()
            self.pin_checkbox.setChecked(True)  # underlying state, even though hidden
            self.custom_pin_input.setVisible(True)  # can still choose your own PIN, just can't disable it
        else:
            self.mode_indicator_label.setText("● Local Network Only selected")
            self.pin_mandatory_label.hide()
            self.pin_checkbox.show()
            self.pin_checkbox.setEnabled(True)
            # Restore YOUR actual choice for Local mode, rather than
            # leaving the checkbox stuck on the True that Global mode
            # forced — that forced value was never something you
            # picked, so it shouldn't linger after leaving that mode.
            self.pin_checkbox.setChecked(self._local_pin_preference)
            self.custom_pin_input.setVisible(self.pin_checkbox.isChecked())
            self.tunnel_status_label.hide()

    def _on_pin_checkbox_toggled(self, checked: bool) -> None:
        self.custom_pin_input.setVisible(checked)
        if not checked:
            self.pin_display_label.hide()
        # Only remember this as your actual Local-mode preference when
        # it's genuinely your action — the checkbox is only interactive
        # in Local mode; in Global mode we force it via setChecked()
        # ourselves (see _on_mode_changed above), and without this
        # guard that forced change would incorrectly overwrite your
        # real preference.
        if not self.internet_radio.isChecked():
            self._local_pin_preference = checked

    def _show_qr_code(self, address: str) -> None:
        pixmap = generate_qr_pixmap(address)
        if pixmap is None:
            # "qrcode" package not installed — fail quietly rather than
            # blocking sharing over an optional convenience feature.
            self.qr_label.hide()
            self.qr_caption_label.hide()
            self.save_qr_btn.hide()
            self._current_qr_pixmap = None
            return
        self._current_qr_pixmap = pixmap
        self.qr_label.setPixmap(pixmap)
        self.qr_label.show()
        self.qr_caption_label.show()
        self.save_qr_btn.show()

    def _hide_qr_code(self) -> None:
        self.qr_label.clear()
        self.qr_label.hide()
        self.qr_caption_label.hide()
        self.save_qr_btn.hide()
        self._current_qr_pixmap = None

    def _save_qr_code(self) -> None:
        if self._current_qr_pixmap is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save QR Code", "LocalShare-QR.png", "PNG Image (*.png)"
        )
        if not path:
            return  # user cancelled
        if not path.lower().endswith(".png"):
            path += ".png"
        if not self._current_qr_pixmap.save(path, "PNG"):
            QMessageBox.warning(self, "Couldn't save QR code", f"Failed to save to:\n{path}")

    def _start_webdav(self) -> None:
        try:
            self.webdav_handle.start()
        except RuntimeError as exc:
            self.webdav_status_label.setText(f"Network Drive access not started: {exc}")
            self.webdav_status_label.show()
            return
        if platform.system() == "Windows":
            instructions = "Network Drive: paste this into Explorer's 'Map Network Drive' dialog:"
        else:
            instructions = "Network Drive: use this address in your file manager's 'Connect to Server':"
        self.webdav_status_label.setText(f"{instructions}\n{self.webdav_handle.explorer_path}")
        self.webdav_status_label.show()

    def _on_server_start_failed(self, error: str) -> None:
        self.toggle_server_btn.setText("Start Sharing")
        self.toggle_server_btn.setEnabled(True)
        self.status_dot.setText("●")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['danger']}; font-size: 14px;")
        self.status_label.setText("Server Error")
        QMessageBox.critical(
            self,
            "Unable to start server",
            f"LocalShare couldn't start the server:\n\n{error}",
        )

    def _stop_server(self) -> None:
        self.toggle_server_btn.setEnabled(False)
        self.toggle_server_btn.setText("Stopping…")

        self._stop_worker = _ServerStopWorker(self.server_handle)
        self._stop_worker.finished.connect(self._on_server_stopped)
        self._stop_worker.start()

    def _on_server_stopped(self) -> None:
        if self.webdav_handle.is_running:
            self.webdav_handle.stop()
        self.webdav_status_label.hide()
        self.webdav_checkbox.setEnabled(True)

        if self.tunnel_handle.is_running:
            self.tunnel_handle.stop()
        self.tunnel_status_label.hide()

        self.access_control.disable()
        self.pin_display_label.hide()

        self._hide_qr_code()

        self.status_dot.setText("○")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 14px;")
        self.status_label.setText("Ready to Share")
        self.address_label.setText("Address: —")
        self.copy_address_btn.setEnabled(False)
        self.toggle_server_btn.setText("Start Sharing")
        self.toggle_server_btn.setEnabled(True)

        self.local_only_radio.setEnabled(True)
        self.internet_radio.setEnabled(True)
        self.pin_checkbox.setEnabled(True)
        self.custom_pin_input.setEnabled(True)
        self._local_address = None

    def _copy_address(self) -> None:
        if self.tunnel_handle.is_running and self.tunnel_handle.public_url:
            address = self._build_share_url(self.tunnel_handle.public_url)
        else:
            address = self.server_handle.address
            if address:
                address = self._build_share_url(address)
        if address:
            QGuiApplication.clipboard().setText(address)

    def _current_card_style(self) -> dict:
        return {
            "radius": self._card_radius,
            "border": self._card_border,
            "surface_alpha": self._surface_alpha,
        }

    def _current_base_colors(self) -> dict:
        """
        A fresh copy of the currently selected theme's palette — either
        one of the built-in THEMES or a custom one from
        self._custom_themes. Always a copy, never the shared dict entry
        itself — accent-color customization mutates this per-window
        copy, and mutating the shared object directly would permanently
        corrupt that theme's "true default" for the rest of the app's
        lifetime (and for every other theme built from the same base
        objects).
        """
        if self._current_theme_name in self._custom_themes:
            return dict(self._custom_themes[self._current_theme_name])
        base = THEMES.get(self._current_theme_name, THEMES["Default Dark"])
        return dict(base)

    def _load_custom_themes(self, settings: QSettings) -> dict:
        """Reads saved custom themes from settings. Any corruption (a
        hand-edited or half-written value) falls back to an empty dict
        rather than crashing startup — losing custom themes gracefully
        is far better than the app refusing to open."""
        raw = settings.value("custom_themes", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            name: colors
            for name, colors in data.items()
            if isinstance(colors, dict) and all(k in colors for k in FULL_KEYS)
        }

    def _save_custom_themes(self) -> None:
        QSettings("LocalShare", "LocalShare").setValue(
            "custom_themes", json.dumps(self._custom_themes)
        )

    def _is_current_theme_dark(self) -> bool:
        """Whether the active theme's background is dark or light — used
        to pick a lighten-vs-darken direction for a custom accent's hover
        state. Derived from the theme's own base bg (not self.theme_colors,
        which may not exist yet the first time this runs, e.g. restoring
        a saved custom accent during __init__ before the rest of the
        window is built) — a custom accent never changes 'bg' anyway, so
        this is exactly equivalent once the window is fully up."""
        return QColor(self._current_base_colors()["bg"]).lightness() < 128

    def _compute_hover_color(self, hex_color: str) -> str:
        """
        Derives a hover-state variant of a custom accent color. Dark
        backgrounds want a LIGHTER hover for contrast; light backgrounds
        want a DARKER one — matches the relationship already present
        between the built-in accent/accent_hover pairs in each palette.
        """
        color = QColor(hex_color)
        adjusted = color.lighter(115) if self._is_current_theme_dark() else color.darker(115)
        return adjusted.name()

    def _compute_theme_colors(self) -> dict:
        """The current theme's palette with any custom accent override
        applied — shared by both the initial __init__ setup and
        _apply_theme(), so there's exactly one place that logic lives."""
        colors = self._current_base_colors()
        if self._custom_accent:
            colors["accent"] = self._custom_accent
            colors["accent_hover"] = self._compute_hover_color(self._custom_accent)
        return colors

    def _apply_theme(self) -> None:
        """Rebuilds theme_colors from the current base + any custom accent
        override, then pushes it out to every widget that needs it."""
        colors = self._compute_theme_colors()
        self.theme_colors = colors

        QApplication.instance().setStyleSheet(build_stylesheet(colors, self._current_card_style()))
        self.drop_zone.set_theme(colors)

        dim_style = f"color: {colors['text_dim']}; font-size: 12px;"
        self.webdav_status_label.setStyleSheet(dim_style)
        self.qr_caption_label.setStyleSheet(dim_style)
        self.tunnel_status_label.setStyleSheet(dim_style)
        self.pin_display_label.setStyleSheet(
            f"color: {colors['accent']}; font-size: 22px; font-weight: 700; letter-spacing: 4px;"
        )
        self.credit_label.setStyleSheet(
            f"color: {colors['text_dim']}; font-size: 11px; letter-spacing: 0.5px;"
        )
        self._version_label.setStyleSheet(
            f"color: {colors['text_dim']}; font-size: 12px; padding-top: 6px;"
        )
        self.mode_indicator_label.setStyleSheet(
            f"color: {colors['accent']}; font-size: 12px; font-weight: 600;"
        )
        self.pin_mandatory_label.setStyleSheet(f"color: {colors['text_dim']}; font-size: 13px;")
        if hasattr(self, "_about_label"):
            self._about_label.setStyleSheet(f"color: {colors['text_dim']}; font-size: 12px;")
        self.gradient_background.set_colors(colors["bg"], colors["accent"])
        self.accent_color_btn.set_glow_color(colors["accent"])
        self.toggle_server_btn.set_glow_color(colors["accent"])
        self.save_qr_btn.set_glow_color(colors["accent"])
        self.copy_address_btn.set_glow_color(colors["accent"])
        self.check_update_btn.set_glow_color(colors["accent"])
        self.settings_btn.set_glow_color(colors["accent"])
        self._settings_close_btn.set_glow_color(colors["accent"])
        for btn in getattr(self, "_theme_action_buttons", []):
            btn.set_glow_color(colors["accent"])

        # status dot color depends on server state, not just theme
        if self.server_handle.is_running:
            self.status_dot.setStyleSheet(f"color: {colors['success']}; font-size: 14px;")
        else:
            self.status_dot.setStyleSheet(f"color: {colors['text_dim']}; font-size: 14px;")

        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()

    def _set_card_radius(self, value: str) -> None:
        self._card_radius = value
        QSettings("LocalShare", "LocalShare").setValue("card_radius", value)
        self._apply_theme()
        self._apply_card_style_to_widgets()

    def _set_card_border(self, value: str) -> None:
        self._card_border = value
        QSettings("LocalShare", "LocalShare").setValue("card_border", value)
        self._apply_theme()
        self._apply_card_style_to_widgets()

    def _set_card_shadow(self, value: str) -> None:
        self._card_shadow = value
        QSettings("LocalShare", "LocalShare").setValue("card_shadow", value)
        self._apply_card_style_to_widgets()

    def _set_surface_alpha(self, slider_value: int) -> None:
        self._surface_alpha = slider_value / 100.0
        QSettings("LocalShare", "LocalShare").setValue("surface_alpha", self._surface_alpha)
        self._apply_theme()

    def _set_elided_label(self, label: QLabel, full_text: str, max_width: int = 220) -> None:
        """Truncates long text (e.g. a filename) with an ellipsis so it
        never forces a row to overflow horizontally, while keeping the
        full text available on hover — used for background image/video
        filenames, which can be long and were previously a real cause
        of the Settings dialog needing horizontal scrolling."""
        metrics = label.fontMetrics()
        elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideMiddle, max_width)
        label.setText(elided)
        label.setToolTip(full_text)

    def _set_glass_effect(self, value: str) -> None:
        self._glass_effect = value
        QSettings("LocalShare", "LocalShare").setValue("glass_effect", value)
        self._refresh_glass_backdrop()

    def _refresh_glass_backdrop(self) -> None:
        """
        Experimental: blurs a SNAPSHOT of whatever's currently behind
        the shared items list and uses it as that list's background —
        an approximation of glassmorphism, since Qt Widgets has no
        native support for blurring what's actually behind a
        translucent panel. Refreshed on resize/theme/background-setting
        changes, NOT continuously per animation frame (that would mean
        re-capturing and re-blurring a region many times a second,
        which is expensive and risky) — so with an animated background
        (Gradient/Video), this will look like a still, slightly stale
        blur rather than a genuinely live one. Any failure along the
        way (capture, blur, file write) falls back to the normal flat
        card background rather than leaving something broken on screen.
        """
        blur_radii = {"Off": 0, "Subtle": 8, "Medium": 16, "Strong": 28}
        radius = blur_radii.get(getattr(self, "_glass_effect", "Off"), 0)

        if radius == 0 or not hasattr(self, "shared_list"):
            if hasattr(self, "shared_list"):
                self.shared_list.setStyleSheet("")  # revert to normal QSS-driven card styling
            return

        try:
            offset = self.shared_list.mapTo(self.gradient_background, QPoint(0, 0))
            size = self.shared_list.size()
            if size.width() <= 0 or size.height() <= 0:
                return

            snapshot = self.gradient_background.capture_region(QRect(offset, size))
            if snapshot.isNull():
                self.shared_list.setStyleSheet("")
                return

            scene = QGraphicsScene()
            item = QGraphicsPixmapItem(snapshot)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(radius)
            item.setGraphicsEffect(blur)
            scene.addItem(item)

            blurred = QPixmap(snapshot.size())
            blurred.fill(Qt.GlobalColor.transparent)
            painter = QPainter(blurred)
            scene.render(painter, target=QRectF(blurred.rect()), source=QRectF(snapshot.rect()))
            painter.end()

            if not blurred.save(self._glass_temp_path, "PNG"):
                self.shared_list.setStyleSheet("")
                return

            radius_px = CARD_RADIUS.get(self._card_radius, 8)
            border_width, border_key = CARD_BORDER.get(self._card_border, (1, "border"))
            border_color = self.theme_colors[border_key] if border_key != "transparent" else "transparent"
            path_for_qss = self._glass_temp_path.replace("\\", "/")
            self.shared_list.setStyleSheet(
                f"QListWidget {{ background-image: url({path_for_qss}); "
                f"background-position: top left; border: {border_width}px solid {border_color}; "
                f"border-radius: {radius_px}px; padding: 4px; }}"
            )
        except Exception:
            # Experimental effect — any failure here should never break
            # the app or leave something corrupted-looking on screen.
            self.shared_list.setStyleSheet("")

    def _apply_card_style_to_widgets(self) -> None:
        """
        QSS has no box-shadow property at all, so 'shadow' is done via
        QGraphicsDropShadowEffect applied directly to genuinely simple
        card-like widgets — NOT to self.settings_dialog itself. That
        was a real mistake: a graphics effect applied to an entire
        dialog containing a big scrolling widget tree doesn't render as
        a soft shadow, it visibly breaks down into a duplicated "echo"
        of the whole dialog's content. A top-level window also already
        gets its own native OS shadow, so a dialog-wide effect was
        never the right target to begin with — only small, self-
        contained cards should get this.
        """
        blur = CARD_SHADOW_BLUR.get(self._card_shadow, 0)
        for widget in (self.shared_list,):
            if blur > 0:
                shadow = QGraphicsDropShadowEffect(widget)
                shadow.setBlurRadius(blur)
                shadow.setOffset(0, 3)
                shadow.setColor(QColor(0, 0, 0, 130))
                widget.setGraphicsEffect(shadow)
            else:
                widget.setGraphicsEffect(None)

    def _on_theme_selected(self, theme_name: str) -> None:
        if theme_name not in THEMES and theme_name not in self._custom_themes:
            return
        self._current_theme_name = theme_name
        # Switching to a genuinely different named theme replaces its
        # look wholesale, including that theme's own accent — a custom
        # accent picked under a previous theme shouldn't silently stick
        # around and clash with the newly chosen palette.
        self._custom_accent = None
        self._apply_theme()
        settings = QSettings("LocalShare", "LocalShare")
        settings.setValue("theme_name", theme_name)
        settings.setValue("custom_accent", "")  # cleared, per the reset above — persist that too

    def _choose_accent_preset(self, hex_color: str) -> None:
        self._custom_accent = hex_color
        self._apply_theme()
        QSettings("LocalShare", "LocalShare").setValue("custom_accent", hex_color)

    def _choose_accent_color(self) -> None:
        initial = QColor(self.theme_colors["accent"])
        color = QColorDialog.getColor(initial, self, "Choose Accent Color")
        if not color.isValid():
            return  # user cancelled
        self._custom_accent = color.name()
        self._apply_theme()
        QSettings("LocalShare", "LocalShare").setValue("custom_accent", color.name())

    def _on_reduce_motion_toggled(self, enabled: bool) -> None:
        self.gradient_background.set_reduce_motion(enabled)
        hover_button_module.ANIMATION_DURATION_MS = 0 if enabled else 180
        QSettings("LocalShare", "LocalShare").setValue("reduce_motion", enabled)

    def _set_performance_mode(self, mode: str) -> None:
        self.gradient_background.set_performance_mode(mode)
        QSettings("LocalShare", "LocalShare").setValue("performance_mode", mode)

    def _set_particle_overlay(self, value: str) -> None:
        self.gradient_background.set_particle_overlay(None if value == "None" else value)
        QSettings("LocalShare", "LocalShare").setValue("particle_overlay", value)

    def _set_background_mode(self, mode: str) -> None:
        self.gradient_background.set_mode(mode)
        QSettings("LocalShare", "LocalShare").setValue("background_mode", mode)
        self._refresh_background_subpanel_visibility(mode)
        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()

    def _refresh_background_subpanel_visibility(self, mode: str) -> None:
        self.gradient_panel.setVisible(mode == "gradient")
        self.image_panel.setVisible(mode == "image")
        self.video_panel.setVisible(mode == "video")

    def _choose_background_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Background Image", "", "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if not path:
            return
        ok = self.gradient_background.set_image(
            path,
            self.image_position_combo.currentText(),
            self.image_scaling_combo.currentText(),
            self.image_opacity_slider.value() / 100.0,
            self.overlay_opacity_slider.value() / 100.0,
        )
        if not ok:
            QMessageBox.warning(
                self, "Couldn't load image", f"This file couldn't be loaded as an image:\n{path}"
            )
            return
        self._bg_image_path = path
        self._set_elided_label(self.image_path_label, os.path.basename(path))
        QSettings("LocalShare", "LocalShare").setValue("image_path", path)
        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()

    def _apply_image_background_settings(self, *_args) -> None:
        settings = QSettings("LocalShare", "LocalShare")
        position = self.image_position_combo.currentText()
        scaling = self.image_scaling_combo.currentText()
        opacity = self.image_opacity_slider.value() / 100.0
        overlay = self.overlay_opacity_slider.value() / 100.0
        settings.setValue("image_position", position)
        settings.setValue("image_scaling", scaling)
        settings.setValue("image_opacity", opacity)
        settings.setValue("overlay_opacity", overlay)
        if self._bg_image_path:
            self.gradient_background.set_image(self._bg_image_path, position, scaling, opacity, overlay)
        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()

    def _choose_background_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Background Video", "", "Videos (*.mp4 *.webm)"
        )
        if not path:
            return
        ok = self.gradient_background.set_video(
            path,
            self.video_loop_checkbox.isChecked(),
            True,  # always muted — see gradient_background.py
            self.video_autoplay_checkbox.isChecked(),
            self.video_opacity_slider.value() / 100.0,
            self.video_speed_slider.value() / 100.0,
        )
        if not ok:
            error_detail = getattr(self.gradient_background, "_video_error", None)
            message = (
                f"This file couldn't be loaded as a background video:\n{path}"
                + (f"\n\n{error_detail}" if error_detail else "")
            )
            QMessageBox.warning(self, "Couldn't load video", message)
            return
        self._bg_video_path = path
        self._set_elided_label(self.video_path_label, os.path.basename(path))
        QSettings("LocalShare", "LocalShare").setValue("video_path", path)
        if getattr(self, "_glass_effect", "Off") != "Off":
            # For video specifically, the first captured frame may not
            # have arrived yet (decoding is asynchronous) — the glass
            # backdrop may briefly show a blank/black capture until the
            # next trigger (resize, or any other settings change)
            # refreshes it again with an actual frame in place.
            self._refresh_glass_backdrop()

    def _apply_video_background_settings(self, *_args) -> None:
        settings = QSettings("LocalShare", "LocalShare")
        loop = self.video_loop_checkbox.isChecked()
        autoplay = self.video_autoplay_checkbox.isChecked()
        opacity = self.video_opacity_slider.value() / 100.0
        speed = self.video_speed_slider.value() / 100.0
        settings.setValue("video_loop", loop)
        settings.setValue("video_autoplay", autoplay)
        settings.setValue("video_opacity", opacity)
        settings.setValue("video_speed", speed)
        if self._bg_video_path:
            self.gradient_background.set_video(self._bg_video_path, loop, True, autoplay, opacity, speed)
        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()

    def _reset_appearance(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset appearance?",
            "This restores LocalShare's default appearance — theme, accent color, "
            "background, cards, motion, and performance settings all revert to their "
            "defaults. Custom themes you've saved are NOT deleted. This can't be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        settings = QSettings("LocalShare", "LocalShare")

        # -- reset the actual state + persisted settings first — this is
        # the part that's guaranteed to happen regardless of whether any
        # individual widget's displayed value technically changes below --
        self._current_theme_name = "Default Dark"
        self._custom_accent = None
        self._card_radius = "Medium"
        self._card_border = "Subtle"
        self._card_shadow = "None"
        self._surface_alpha = 1.0
        self._glass_effect = "Off"
        self._bg_image_path = None
        self._bg_video_path = None

        for key, value in [
            ("theme_name", "Default Dark"), ("custom_accent", ""),
            ("card_radius", "Medium"), ("card_border", "Subtle"), ("card_shadow", "None"),
            ("surface_alpha", 1.0), ("glass_effect", "Off"),
            ("background_mode", "solid"), ("particle_overlay", "None"), ("gradient_style", STYLES[0]),
            ("image_path", ""), ("video_path", ""),
            ("image_position", "Center"), ("image_scaling", "Fill"),
            ("image_opacity", 1.0), ("overlay_opacity", 0.35),
            ("video_loop", True), ("video_autoplay", True),
            ("video_opacity", 1.0), ("video_speed", 1.0),
            ("reduce_motion", False), ("performance_mode", "Balanced"),
        ]:
            settings.setValue(key, value)

        # -- sync widget appearances to match (cosmetic; the actual
        # re-application happens explicitly below regardless) --
        self.theme_combo.setCurrentText("Default Dark")
        self.card_radius_combo.setCurrentText("Medium")
        self.card_border_combo.setCurrentText("Subtle")
        self.card_shadow_combo.setCurrentText("None")
        self.glass_effect_combo.setCurrentText("Off")
        self.gradient_style_combo.setCurrentText(STYLES[0])
        self.particle_overlay_combo.setCurrentText("None")
        self.image_position_combo.setCurrentText("Center")
        self.image_scaling_combo.setCurrentText("Fill")
        self.bg_mode_solid_radio.setChecked(True)
        self.perf_balanced_radio.setChecked(True)
        self.reduce_motion_checkbox.setChecked(False)
        self.transparency_slider.setValue(100)
        self.image_opacity_slider.setValue(100)
        self.overlay_opacity_slider.setValue(35)
        self.video_loop_checkbox.setChecked(True)
        self.video_autoplay_checkbox.setChecked(True)
        self.video_opacity_slider.setValue(100)
        self.video_speed_slider.setValue(100)
        self.image_path_label.setText("None")
        self.image_path_label.setToolTip("")
        self.video_path_label.setText("None")
        self.video_path_label.setToolTip("")

        # -- explicitly re-apply everything — guaranteed to take effect
        # even for values that were already at their default and so
        # wouldn't have fired a change signal from the widget updates above --
        self.gradient_background.set_mode("solid")
        self.gradient_background.set_particle_overlay(None)
        self.gradient_background.set_style(STYLES[0])
        self.gradient_background.set_image(None, "Center", "Fill", 1.0, 0.35)
        self.gradient_background.set_video(None, True, True, True, 1.0, 1.0)
        self.gradient_background.set_performance_mode("Balanced")
        self.gradient_background.set_reduce_motion(False)
        hover_button_module.ANIMATION_DURATION_MS = 180
        self._refresh_background_subpanel_visibility("solid")
        self._apply_theme()
        self._apply_card_style_to_widgets()

        QMessageBox.information(self, "Appearance reset", "Default appearance restored.")

    def _delete_current_theme(self) -> None:
        name = self._current_theme_name
        if name not in self._custom_themes:
            QMessageBox.information(
                self,
                "Can't delete this theme",
                f'"{name}" is a built-in theme and can\'t be deleted — only custom themes '
                f"you've created or imported can be removed.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Delete theme?",
            f'Delete "{name}"? This can\'t be undone.',
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self._custom_themes[name]
        self._save_custom_themes()

        index = self.theme_combo.findText(name)
        if index >= 0:
            # Removing the currently-selected item moves the combo's
            # selection to another entry automatically, which fires
            # _on_theme_selected and applies the new theme as a side
            # effect. The explicit fallback below just guards against
            # that not happening, since I can't verify this live.
            self.theme_combo.removeItem(index)
        if self._current_theme_name == name:
            self.theme_combo.setCurrentText("Default Dark")

    def _open_custom_theme_dialog(self) -> None:
        dialog = CustomThemeDialog(self.theme_colors, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        colors = dialog.result_colors()

        name, ok = QInputDialog.getText(self, "Save Theme", "Name:", text="My Theme")
        name = name.strip()
        if not ok or not name:
            return  # cancelled, or saved with a blank name — don't save an unnamed theme

        if name in THEMES:
            QMessageBox.warning(
                self,
                "Name already used",
                f'"{name}" is one of the built-in theme names — pick a different name.',
            )
            return

        is_overwrite = name in self._custom_themes
        self._custom_themes[name] = colors
        self._save_custom_themes()

        if not is_overwrite:
            self.theme_combo.addItem(name)
        self.theme_combo.setCurrentText(name)  # triggers _on_theme_selected, which applies it

    def _export_current_theme(self) -> None:
        default_filename = f"{self._current_theme_name.replace(' ', '_')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme", default_filename, "JSON Files (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(theme_to_json(self._current_theme_name, self.theme_colors))
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't export theme", f"Failed to save to:\n{path}\n\n{exc}")

    def _import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Theme", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't read file", f"Failed to open:\n{path}\n\n{exc}")
            return

        try:
            name, colors = theme_from_json(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid theme file", str(exc))
            return

        # Avoid silently colliding with an existing name (built-in or
        # already-imported custom theme) — append a numeric suffix
        # rather than overwriting something without asking.
        original_name = name
        suffix = 1
        while name in THEMES or name in self._custom_themes:
            suffix += 1
            name = f"{original_name} ({suffix})"

        self._custom_themes[name] = colors
        self._save_custom_themes()
        self.theme_combo.addItem(name)
        self.theme_combo.setCurrentText(name)
        QMessageBox.information(self, "Theme imported", f'Imported as "{name}" and applied.')

    def _build_settings_dialog(self) -> None:
        """
        Builds the Settings dialog once at startup. The controls inside
        it (theme toggle, accent color, gradient background) are the
        same widget instances created just before this call — moving
        them here just changes where they're displayed, not their
        behavior or state.

        Laid out as a sidebar + pages (General/Sharing/Appearance/etc.
        style, per the original spec) rather than one long scrolling
        column — each page gets its own scroll area too, so a tall page
        still can't cause the overlap/clipping issue from before.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setMinimumSize(560, 480)
        dialog.resize(640, 620)

        dialog_outer_layout = QVBoxLayout(dialog)
        dialog_outer_layout.setContentsMargins(0, 0, 0, 0)
        dialog_outer_layout.setSpacing(0)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        dialog_outer_layout.addLayout(body_layout, stretch=1)

        nav_list = QListWidget()
        nav_list.setObjectName("SettingsNav")
        nav_list.setFixedWidth(160)
        nav_list.setFrameShape(QFrame.Shape.NoFrame)
        body_layout.addWidget(nav_list)

        pages_stack = QStackedWidget()
        body_layout.addWidget(pages_stack, stretch=1)

        def add_page(title: str) -> QVBoxLayout:
            """Creates one nav entry + a scrollable page, returns the
            page's content layout for that section's widgets to be
            added to — same addWidget/addLayout calls as before, just
            routed to the right page instead of one shared layout."""
            nav_list.addItem(title)
            page_scroll = QScrollArea()
            page_scroll.setWidgetResizable(True)
            page_scroll.setFrameShape(QFrame.Shape.NoFrame)
            page_content = QWidget()
            page_scroll.setWidget(page_content)
            page_layout = QVBoxLayout(page_content)
            page_layout.setContentsMargins(20, 20, 20, 20)
            page_layout.setSpacing(14)
            pages_stack.addWidget(page_scroll)
            return page_layout

        settings = QSettings("LocalShare", "LocalShare")

        # -- Sharing page --------------------------------------------------------------
        layout = add_page("Sharing")

        self.auto_start_on_add_checkbox = QCheckBox("Automatically start sharing when files are added")
        self.auto_start_on_add_checkbox.setChecked(
            settings.value("auto_start_on_add", True, type=bool)
        )
        self.auto_start_on_add_checkbox.toggled.connect(
            lambda checked: QSettings("LocalShare", "LocalShare").setValue(
                "auto_start_on_add", checked
            )
        )
        layout.addWidget(self.auto_start_on_add_checkbox)

        self.auto_start_on_launch_checkbox = QCheckBox("Automatically start server when LocalShare launches")
        self.auto_start_on_launch_checkbox.setChecked(
            settings.value("auto_start_on_launch", False, type=bool)
        )
        self.auto_start_on_launch_checkbox.toggled.connect(
            lambda checked: QSettings("LocalShare", "LocalShare").setValue(
                "auto_start_on_launch", checked
            )
        )
        layout.addWidget(self.auto_start_on_launch_checkbox)

        self.auto_resume_shares_checkbox = QCheckBox("Automatically resume previous shares")
        self.auto_resume_shares_checkbox.setToolTip(
            "Re-adds whatever was shared last session, on launch — only files/folders "
            "that still exist at their original location are restored."
        )
        self.auto_resume_shares_checkbox.setChecked(
            settings.value("auto_resume_shares", False, type=bool)
        )
        self.auto_resume_shares_checkbox.toggled.connect(
            lambda checked: QSettings("LocalShare", "LocalShare").setValue(
                "auto_resume_shares", checked
            )
        )
        layout.addWidget(self.auto_resume_shares_checkbox)

        internet_label = QLabel("INTERNET SHARING")
        internet_label.setObjectName("SectionLabel")
        layout.addWidget(internet_label)

        ngrok_note = QLabel(
            "Internet Sharing (the \"Global\" option) uses ngrok, which requires a free "
            "account. Get your authtoken from the ngrok dashboard and paste it below."
        )
        ngrok_note.setWordWrap(True)
        ngrok_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(ngrok_note)

        ngrok_signup_row = QHBoxLayout()
        ngrok_signup_btn = HoverGlowButton("Get authtoken (opens browser)", glow_color=self.theme_colors["accent"])
        ngrok_signup_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://dashboard.ngrok.com/get-started/your-authtoken"))
        )
        ngrok_signup_row.addWidget(ngrok_signup_btn)
        ngrok_signup_row.addStretch()
        layout.addLayout(ngrok_signup_row)

        self.ngrok_token_input = QLineEdit()
        self.ngrok_token_input.setPlaceholderText("Paste your ngrok authtoken here")
        self.ngrok_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        _saved_token = settings.value("ngrok_auth_token", "")
        if _saved_token:
            self.ngrok_token_input.setText(_saved_token)
        self.ngrok_token_input.editingFinished.connect(
            lambda: QSettings("LocalShare", "LocalShare").setValue(
                "ngrok_auth_token", self.ngrok_token_input.text().strip()
            )
        )
        layout.addWidget(self.ngrok_token_input)
        layout.addStretch()

        # -- Appearance page --------------------------------------------------------------
        layout = add_page("Appearance")

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme"))
        theme_row.addStretch()
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)

        theme_actions_grid = QGridLayout()
        theme_actions_grid.setHorizontalSpacing(10)
        theme_actions_grid.setVerticalSpacing(6)
        create_theme_btn = HoverGlowButton("+ Create Theme", glow_color=self.theme_colors["accent"])
        create_theme_btn.clicked.connect(self._open_custom_theme_dialog)
        delete_theme_btn = HoverGlowButton("🗑 Delete", glow_color=self.theme_colors["accent"])
        delete_theme_btn.clicked.connect(self._delete_current_theme)
        export_theme_btn = HoverGlowButton("Export…", glow_color=self.theme_colors["accent"])
        export_theme_btn.clicked.connect(self._export_current_theme)
        import_theme_btn = HoverGlowButton("Import…", glow_color=self.theme_colors["accent"])
        import_theme_btn.clicked.connect(self._import_theme)
        # 2 columns — wraps into a 2x2 grid instead of a single row
        # that overflows/needs horizontal scrolling in a narrow dialog
        theme_actions_grid.addWidget(create_theme_btn, 0, 0)
        theme_actions_grid.addWidget(delete_theme_btn, 0, 1)
        theme_actions_grid.addWidget(export_theme_btn, 1, 0)
        theme_actions_grid.addWidget(import_theme_btn, 1, 1)
        layout.addLayout(theme_actions_grid)
        self._theme_action_buttons = [create_theme_btn, delete_theme_btn, export_theme_btn, import_theme_btn]

        accent_label = QLabel("Accent color")
        layout.addWidget(accent_label)
        accent_swatch_grid = QGridLayout()
        accent_swatch_grid.setHorizontalSpacing(8)
        accent_swatch_grid.setVerticalSpacing(6)
        for i, swatch in enumerate(self.accent_preset_buttons):
            accent_swatch_grid.addWidget(swatch, i // 5, i % 5)  # 5 columns — wraps into 2 rows of 5
        accent_swatch_grid.setColumnStretch(5, 1)  # keeps swatches left-aligned instead of spreading out
        layout.addLayout(accent_swatch_grid)

        accent_custom_row = QHBoxLayout()
        accent_custom_row.addStretch()
        accent_custom_row.addWidget(self.accent_color_btn)
        layout.addLayout(accent_custom_row)

        reset_appearance_row = QHBoxLayout()
        reset_appearance_btn = HoverGlowButton("Reset Appearance", glow_color=self.theme_colors["accent"])
        reset_appearance_btn.clicked.connect(self._reset_appearance)
        reset_appearance_row.addWidget(reset_appearance_btn)
        reset_appearance_row.addStretch()
        layout.addLayout(reset_appearance_row)
        reset_appearance_note = QLabel(
            "Restores theme, accent, background, cards, motion, and performance settings "
            "to their defaults — everything on the Appearance, Background, and Effects pages."
        )
        reset_appearance_note.setWordWrap(True)
        reset_appearance_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(reset_appearance_note)
        self._theme_action_buttons.append(reset_appearance_btn)
        layout.addStretch()

        # -- Background page --------------------------------------------------------------
        layout = add_page("Background")

        bg_mode_grid = QGridLayout()
        bg_mode_grid.setHorizontalSpacing(16)
        bg_mode_grid.setVerticalSpacing(6)
        mode_buttons = (self.bg_mode_solid_radio, self.bg_mode_gradient_radio, self.bg_mode_image_radio, self.bg_mode_video_radio)
        for i, btn in enumerate(mode_buttons):
            bg_mode_grid.addWidget(btn, i // 2, i % 2)  # 2 columns — wraps into a 2x2 grid instead
            # of a single row that overflows/needs horizontal scrolling in a narrow dialog
        layout.addLayout(bg_mode_grid)

        particle_overlay_row = QHBoxLayout()
        particle_overlay_row.addWidget(QLabel("Overlay effect"))
        particle_overlay_row.addStretch()
        particle_overlay_row.addWidget(self.particle_overlay_combo)
        layout.addLayout(particle_overlay_row)
        particle_overlay_note = QLabel(
            "Snow, Rain, Fire, or Ink drawn on top — works with any background mode above. "
            "Ink is a stylized flow effect that reacts to your mouse cursor, not a real fluid "
            "simulation (that needs GPU shaders, which this app doesn't use)."
        )
        particle_overlay_note.setWordWrap(True)
        particle_overlay_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(particle_overlay_note)

        # -- gradient panel --
        self.gradient_panel = QWidget()
        gradient_panel_layout = QVBoxLayout(self.gradient_panel)
        gradient_panel_layout.setContentsMargins(0, 4, 0, 0)
        gradient_style_row = QHBoxLayout()
        gradient_style_row.addWidget(QLabel("Gradient style"))
        gradient_style_row.addStretch()
        gradient_style_row.addWidget(self.gradient_style_combo)
        gradient_panel_layout.addLayout(gradient_style_row)
        layout.addWidget(self.gradient_panel)

        # -- image panel --
        self.image_panel = QWidget()
        image_panel_layout = QVBoxLayout(self.image_panel)
        image_panel_layout.setContentsMargins(0, 4, 0, 0)
        image_choose_row = QHBoxLayout()
        image_choose_row.addWidget(self.choose_image_btn)
        image_choose_row.addWidget(self.image_path_label)
        image_choose_row.addStretch()
        image_panel_layout.addLayout(image_choose_row)
        image_position_row = QHBoxLayout()
        image_position_row.addWidget(QLabel("Position"))
        image_position_row.addStretch()
        image_position_row.addWidget(self.image_position_combo)
        image_panel_layout.addLayout(image_position_row)
        image_scaling_row = QHBoxLayout()
        image_scaling_row.addWidget(QLabel("Scaling"))
        image_scaling_row.addStretch()
        image_scaling_row.addWidget(self.image_scaling_combo)
        image_panel_layout.addLayout(image_scaling_row)
        image_opacity_row = QHBoxLayout()
        image_opacity_row.addWidget(QLabel("Opacity"))
        image_opacity_row.addWidget(self.image_opacity_slider)
        image_panel_layout.addLayout(image_opacity_row)
        overlay_opacity_row = QHBoxLayout()
        overlay_opacity_row.addWidget(QLabel("Overlay"))
        overlay_opacity_row.addWidget(self.overlay_opacity_slider)
        image_panel_layout.addLayout(overlay_opacity_row)
        layout.addWidget(self.image_panel)

        # -- video panel --
        self.video_panel = QWidget()
        video_panel_layout = QVBoxLayout(self.video_panel)
        video_panel_layout.setContentsMargins(0, 4, 0, 0)
        video_choose_row = QHBoxLayout()
        video_choose_row.addWidget(self.choose_video_btn)
        video_choose_row.addWidget(self.video_path_label)
        video_choose_row.addStretch()
        video_panel_layout.addLayout(video_choose_row)
        video_panel_layout.addWidget(self.video_loop_checkbox)
        video_panel_layout.addWidget(self.video_mute_checkbox)
        video_panel_layout.addWidget(self.video_autoplay_checkbox)
        video_opacity_row = QHBoxLayout()
        video_opacity_row.addWidget(QLabel("Opacity"))
        video_opacity_row.addWidget(self.video_opacity_slider)
        video_panel_layout.addLayout(video_opacity_row)
        video_speed_row = QHBoxLayout()
        video_speed_row.addWidget(QLabel("Speed"))
        video_speed_row.addWidget(self.video_speed_slider)
        video_panel_layout.addLayout(video_speed_row)
        video_note = QLabel(
            "Video backgrounds are the least-tested part of LocalShare — if playback "
            "looks wrong or the app slows down, switch back to Solid or Gradient."
        )
        video_note.setWordWrap(True)
        video_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        video_panel_layout.addWidget(video_note)
        layout.addWidget(self.video_panel)
        layout.addStretch()

        self._refresh_background_subpanel_visibility(
            QSettings("LocalShare", "LocalShare").value("background_mode", "solid")
        )

        # -- Effects page (Cards, Transparency, Glass, Motion, Performance) --------------------------------------------------------------
        layout = add_page("Effects")

        cards_label = QLabel("CARDS")
        cards_label.setObjectName("SectionLabel")
        layout.addWidget(cards_label)

        card_radius_row = QHBoxLayout()
        card_radius_row.addWidget(QLabel("Corner radius"))
        card_radius_row.addStretch()
        card_radius_row.addWidget(self.card_radius_combo)
        layout.addLayout(card_radius_row)

        card_border_row = QHBoxLayout()
        card_border_row.addWidget(QLabel("Border"))
        card_border_row.addStretch()
        card_border_row.addWidget(self.card_border_combo)
        layout.addLayout(card_border_row)

        card_shadow_row = QHBoxLayout()
        card_shadow_row.addWidget(QLabel("Shadow"))
        card_shadow_row.addStretch()
        card_shadow_row.addWidget(self.card_shadow_combo)
        layout.addLayout(card_shadow_row)

        transparency_row = QHBoxLayout()
        transparency_row.addWidget(QLabel("Transparency"))
        transparency_row.addWidget(self.transparency_slider)
        layout.addLayout(transparency_row)
        transparency_note = QLabel(
            "Makes cards see-through over your background — doesn't blur what's behind them "
            "(see Glass Effect below for that)."
        )
        transparency_note.setWordWrap(True)
        transparency_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(transparency_note)

        glass_label = QLabel("GLASS EFFECT")
        glass_label.setObjectName("SectionLabel")
        layout.addWidget(glass_label)

        glass_row = QHBoxLayout()
        glass_row.addWidget(QLabel("Blur behind cards"))
        glass_row.addStretch()
        glass_row.addWidget(self.glass_effect_combo)
        layout.addLayout(glass_row)
        glass_note = QLabel(
            "Genuinely experimental — blurs a snapshot of your background behind the shared "
            "items list. Qt has no native support for this, so it's a real hack: the blur is a "
            "still snapshot, refreshed on resize/theme/background changes rather than tracking "
            "a moving background frame-by-frame. With an animated background (Gradient/Video), "
            "expect it to look slightly stale rather than perfectly live. Turn it off if it "
            "looks wrong or hurts performance."
        )
        glass_note.setWordWrap(True)
        glass_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(glass_note)

        motion_label = QLabel("MOTION")
        motion_label.setObjectName("SectionLabel")
        layout.addWidget(motion_label)

        _motion_settings = QSettings("LocalShare", "LocalShare")
        _persisted_reduce_motion = _motion_settings.value("reduce_motion", False, type=bool)
        _persisted_performance_mode = _motion_settings.value("performance_mode", "Balanced")
        if _persisted_performance_mode not in ("Quality", "Balanced", "Performance"):
            _persisted_performance_mode = "Balanced"

        self.reduce_motion_checkbox = QCheckBox("Reduce Motion")
        self.reduce_motion_checkbox.setToolTip(
            "Freezes animated backgrounds and speeds up hover effects to instant, "
            "without changing your chosen theme or background."
        )
        self.reduce_motion_checkbox.setChecked(_persisted_reduce_motion)
        self.reduce_motion_checkbox.toggled.connect(self._on_reduce_motion_toggled)
        layout.addWidget(self.reduce_motion_checkbox)

        performance_label = QLabel("PERFORMANCE")
        performance_label.setObjectName("SectionLabel")
        layout.addWidget(performance_label)

        self.performance_mode_group = QButtonGroup(self)
        self.perf_quality_radio = QRadioButton("Quality")
        self.perf_balanced_radio = QRadioButton("Balanced")
        self.perf_performance_radio = QRadioButton("Performance")
        for btn in (self.perf_quality_radio, self.perf_balanced_radio, self.perf_performance_radio):
            self.performance_mode_group.addButton(btn)
        {"Quality": self.perf_quality_radio, "Balanced": self.perf_balanced_radio,
         "Performance": self.perf_performance_radio}[_persisted_performance_mode].setChecked(True)
        self.perf_quality_radio.toggled.connect(lambda c: c and self._set_performance_mode("Quality"))
        self.perf_balanced_radio.toggled.connect(lambda c: c and self._set_performance_mode("Balanced"))
        self.perf_performance_radio.toggled.connect(lambda c: c and self._set_performance_mode("Performance"))
        perf_grid = QGridLayout()
        perf_grid.setHorizontalSpacing(16)
        perf_grid.setVerticalSpacing(6)
        perf_grid.addWidget(self.perf_quality_radio, 0, 0)
        perf_grid.addWidget(self.perf_balanced_radio, 0, 1)
        perf_grid.addWidget(self.perf_performance_radio, 1, 0)
        layout.addLayout(perf_grid)
        layout.addStretch()

        # Apply restored state now — the toggled signals above only
        # fire on a genuine state *change*, which won't happen just
        # from setChecked() during construction if the widget already
        # defaulted to that value.
        self.gradient_background.set_performance_mode(_persisted_performance_mode)
        self.gradient_background.set_reduce_motion(_persisted_reduce_motion)
        hover_button_module.ANIMATION_DURATION_MS = 0 if _persisted_reduce_motion else 180

        # -- Updates page --------------------------------------------------------------
        layout = add_page("Updates")
        layout.addWidget(self.auto_check_updates_checkbox)
        layout.addStretch()

        # -- About page --------------------------------------------------------------
        layout = add_page("About")
        about_text = QLabel(f"LocalShare v{APP_VERSION} — Developed by ANARKALI")
        about_text.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self._about_label = about_text  # kept for theme refresh
        layout.addWidget(about_text)
        layout.addStretch()

        nav_list.currentRowChanged.connect(pages_stack.setCurrentIndex)
        nav_list.setCurrentRow(0)
        self.settings_nav_list = nav_list

        close_btn = HoverGlowButton("Close", glow_color=self.theme_colors["accent"])
        close_btn.clicked.connect(dialog.accept)
        close_btn_wrapper = QWidget()
        close_btn_layout = QVBoxLayout(close_btn_wrapper)
        close_btn_layout.setContentsMargins(16, 8, 16, 16)
        close_btn_layout.addWidget(close_btn)
        dialog_outer_layout.addWidget(close_btn_wrapper)

        self.settings_dialog = dialog
        self._settings_close_btn = close_btn  # kept for theme/glow-color refresh

    def _open_settings_dialog(self) -> None:
        # No per-dialog stylesheet patch needed anymore — styling is
        # applied at the QApplication level (see __init__/_apply_theme),
        # which Qt reliably cascades to every window including this one.
        self.settings_dialog.exec()

    def _show_welcome_guide(self) -> None:
        """
        Shown once, automatically, the first time LocalShare runs —
        also reachable anytime afterward via the '?' button next to
        Settings, since a one-time-only dialog is easy to accidentally
        dismiss before actually reading it.
        """
        QSettings("LocalShare", "LocalShare").setValue("has_shown_welcome_guide", True)

        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome to LocalShare")
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(14)

        heading = QLabel("Welcome to LocalShare 👋")
        heading.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {self.theme_colors['text']};")
        layout.addWidget(heading)

        intro = QLabel(
            "Sharing on your local network (same Wi-Fi) works immediately — drag files in, "
            "hit Start Sharing, and you're done. No account, no setup."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {self.theme_colors['text']}; font-size: 13px;")
        layout.addWidget(intro)

        internet_label = QLabel("Want to share over the Internet too?")
        internet_label.setStyleSheet(f"font-weight: 600; color: {self.theme_colors['text']}; font-size: 13px;")
        layout.addWidget(internet_label)

        steps_note = QLabel(
            "\"Global\" sharing uses ngrok, which needs a free account — this is a one-time setup:"
        )
        steps_note.setWordWrap(True)
        steps_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        layout.addWidget(steps_note)

        steps = [
            ("1", "Create a free ngrok account", "https://dashboard.ngrok.com/signup"),
            ("2", "Copy your authtoken", "https://dashboard.ngrok.com/get-started/your-authtoken"),
            ("3", "Paste it into Settings → Sharing → ngrok Authtoken", None),
        ]
        for number, text, url in steps:
            step_row = QHBoxLayout()
            number_label = QLabel(number)
            number_label.setFixedWidth(20)
            number_label.setStyleSheet(f"color: {self.theme_colors['accent']}; font-weight: 600;")
            step_row.addWidget(number_label)
            text_label = QLabel(text)
            text_label.setWordWrap(True)
            text_label.setStyleSheet(f"color: {self.theme_colors['text']}; font-size: 12px;")
            step_row.addWidget(text_label, stretch=1)
            if url:
                open_btn = HoverGlowButton("Open", glow_color=self.theme_colors["accent"])
                open_btn.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
                step_row.addWidget(open_btn)
            layout.addLayout(step_row)

        skip_note = QLabel("You can skip this entirely if you only need Local Network sharing.")
        skip_note.setWordWrap(True)
        skip_note.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 11px;")
        layout.addWidget(skip_note)

        button_row = QHBoxLayout()
        maybe_later_btn = HoverGlowButton("Maybe Later", glow_color=self.theme_colors["accent"])
        maybe_later_btn.clicked.connect(dialog.accept)
        button_row.addWidget(maybe_later_btn)
        button_row.addStretch()
        open_settings_btn = HoverGlowButton("Open Settings Now", glow_color=self.theme_colors["accent"])
        open_settings_btn.clicked.connect(lambda: (dialog.accept(), self._open_settings_dialog()))
        button_row.addWidget(open_settings_btn)
        layout.addLayout(button_row)

        dialog.exec()

    def _check_for_updates(self) -> None:
        address = self.update_source_input.text().strip()
        if not address:
            # field is empty (by design — see _build_ui) — fall back to
            # whatever was used last time instead of forcing a retype
            address = QSettings("LocalShare", "LocalShare").value("update_source", "")
        if not address:
            QMessageBox.information(
                self,
                "Enter an address",
                "Enter the address of another running LocalShare instance to check "
                "(e.g. the one on the PC that keeps the latest version), then try again.",
            )
            return

        QSettings("LocalShare", "LocalShare").setValue("update_source", address)
        self._last_checked_address = address

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("Checking…")

        self._update_worker = _UpdateCheckWorker(address)
        self._update_worker.finished.connect(self._on_update_check_finished)
        self._update_worker.start()

    def _on_update_check_finished(self, result, build_result) -> None:
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")

        # Clear the field and refresh the placeholder hint — ready to
        # type a different address next time without deleting anything
        # first, while the just-used address is remembered for both the
        # placeholder hint and the startup auto-check.
        saved = QSettings("LocalShare", "LocalShare").value("update_source", "")
        self.update_source_input.clear()
        self.update_source_input.setPlaceholderText(
            f"e.g. 192.168.1.104:8765 (last used: {saved})"
            if saved
            else "Update source address (e.g. 192.168.1.104:8765)"
        )

        if not result.ok:
            QMessageBox.warning(self, "Couldn't check for updates", result.error)
            return

        if not result.is_newer:
            QMessageBox.information(
                self, "Up to date", f"You're running the latest version (v{APP_VERSION})."
            )
            return

        self._offer_update_install(result, build_result)

    def _auto_check_for_updates_on_startup(self) -> None:
        """
        Runs a background check against the last-used update source
        (if any) shortly after launch, with no manual address entry
        needed. Unlike the manual "Check for Updates" button, this
        stays silent unless there's actually something to report — an
        "up to date" popup on every single launch would just be noise.
        Controlled by a checkbox so it's opt-out, not forced.
        """
        settings = QSettings("LocalShare", "LocalShare")
        if not settings.value("auto_check_updates", True, type=bool):
            return
        address = settings.value("update_source", "")
        if not address:
            return  # nothing saved yet — nothing to auto-check against

        self._last_checked_address = address
        self._auto_update_worker = _UpdateCheckWorker(address)
        self._auto_update_worker.finished.connect(self._on_auto_update_check_finished)
        self._auto_update_worker.start()

    def _on_auto_update_check_finished(self, result, build_result) -> None:
        if not result.ok or not result.is_newer:
            return  # silent on error or already up to date — see docstring above
        self._offer_update_install(result, build_result)

    def _offer_update_install(self, result, build_result) -> None:
        """
        Shared by both the manual and automatic update paths: if the
        other instance is sharing something that looks like an
        installer, offer to download and launch it right now. If not,
        fall back to just pointing at the address, same as before.
        """
        if build_result is not None and build_result.available:
            reply = QMessageBox.question(
                self,
                "Update available",
                f"A newer version is available: v{result.remote_version} "
                f"(you have v{APP_VERSION}).\n\n"
                f"Found: {build_result.name}\n\n"
                f"Download and install it now? LocalShare will close so the "
                f"installer can run cleanly.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._start_update_download(build_result)
        else:
            QMessageBox.information(
                self,
                "Update available",
                f"A newer version is available: v{result.remote_version} "
                f"(you have v{APP_VERSION}).\n\n"
                f"Open {self._last_checked_address} in your browser and download "
                f"the latest LocalShare installer from the shared files, then run it.",
            )

    def _start_update_download(self, build_result) -> None:
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("Downloading update…")

        self._update_download_worker = _UpdateDownloadWorker(
            self._last_checked_address, build_result.download_url, build_result.name
        )
        self._update_download_worker.finished_ok.connect(self._on_update_downloaded)
        self._update_download_worker.finished_error.connect(self._on_update_download_failed)
        self._update_download_worker.start()

    def _on_update_download_failed(self, error: str) -> None:
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")
        QMessageBox.warning(self, "Download failed", error)

    def _on_update_downloaded(self, local_path: str) -> None:
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")

        # I couldn't test this exact hand-off (launching a downloaded
        # installer and then closing this app) end-to-end without a
        # real Windows/Linux machine — if the installer doesn't open
        # automatically, the file is still safely on disk at the path
        # shown below.
        try:
            open_with_default_app(local_path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Downloaded, but couldn't launch it",
                f"The update downloaded successfully to:\n{local_path}\n\n"
                f"But it couldn't be opened automatically ({exc}). "
                f"Open that file yourself to install it.",
            )
            return

        QMessageBox.information(
            self,
            "Installing…",
            "The installer should now be opening. LocalShare will close so it "
            "can update cleanly — reopen it once installation finishes.",
        )
        QApplication.instance().quit()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        # Refreshes the glass-effect backdrop snapshot (if enabled) to
        # match the new window size — otherwise it'd keep showing a
        # blurred capture from before the resize, visibly stale/wrong.
        if getattr(self, "_glass_effect", "Off") != "Off":
            self._refresh_glass_backdrop()
        super().resizeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        """Pauses animated/video backgrounds while minimized (nothing is
        visible, so decoding frames just burns CPU/GPU for no reason),
        resumes when restored."""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.gradient_background.pause_for_minimize()
            else:
                self.gradient_background.resume_from_minimize()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        if self.server_handle.is_running:
            self.server_handle.stop()
        if self.webdav_handle.is_running:
            self.webdav_handle.stop()
        if self.tunnel_handle.is_running:
            self.tunnel_handle.stop()
        if self.discovery_service.is_running:
            self.discovery_service.stop()
        event.accept()

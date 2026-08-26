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

from PySide6.QtCore import Qt, QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon
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
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.drop_zone import DropZone
from app.gui.gradient_background import AnimatedGradientBackground, STYLES
from app.gui.custom_theme_dialog import CustomThemeDialog
from app.gui.hover_button import HoverGlowButton
from app.gui.qr_widget import generate_qr_pixmap
from app.gui.theme import ACCENT_PRESETS, FULL_KEYS, THEMES, build_stylesheet, theme_to_json, theme_from_json
from app.paths import ICON_PATH
from app.gui.update_checker import (
    check_for_update,
    download_build,
    find_latest_build,
    open_with_default_app,
)
from app.server.auth import AccessControl
from app.server.http_server import ServerHandle
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
    Starts the cloudflared tunnel off the GUI thread — launching the
    subprocess and waiting for it to report its public URL takes a
    few seconds, which would freeze the window if run directly on the
    main thread.
    """

    finished_ok = Signal(str)  # public_url
    finished_error = Signal(str)  # error message

    def __init__(self, tunnel_handle: TunnelHandle, local_port: int) -> None:
        super().__init__()
        self._handle = tunnel_handle
        self._local_port = local_port

    def run(self) -> None:
        try:
            public_url = self._handle.start(self._local_port)
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
        self._local_pin_preference: bool = False  # your own PIN choice for Local mode, remembered separately from Global's forced-on state
        self.theme_colors = self._compute_theme_colors()
        # Applied at the QApplication level, not just this window — a
        # per-widget stylesheet doesn't reliably cascade to separate
        # top-level windows (QDialog, QMessageBox), which was leaving
        # the Settings dialog and popups rendering unstyled/white
        # against the app's dark theme. The application level is what
        # Qt actually guarantees reaches every window.
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme_colors))

        self.share_manager = ShareManager()
        self.share_manager.on_change(self._refresh_shared_list)

        self.access_control = AccessControl()
        self.server_handle = ServerHandle(self.share_manager, self.access_control)
        self.webdav_handle = WebDavHandle(self.share_manager)
        self.tunnel_handle = TunnelHandle()
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

        _gradient_settings = QSettings("LocalShare", "LocalShare")
        _persisted_gradient_style = _gradient_settings.value("gradient_style", STYLES[0] if STYLES else "Sweep")
        _persisted_gradient_enabled = _gradient_settings.value("gradient_enabled", False, type=bool)

        self.gradient_style_combo = QComboBox()
        self.gradient_style_combo.addItems(STYLES)
        if _persisted_gradient_style in STYLES:
            self.gradient_style_combo.setCurrentText(_persisted_gradient_style)
        self.gradient_style_combo.setEnabled(_persisted_gradient_enabled)
        self.gradient_style_combo.currentTextChanged.connect(self.gradient_background.set_style)
        self.gradient_style_combo.currentTextChanged.connect(
            lambda style: QSettings("LocalShare", "LocalShare").setValue("gradient_style", style)
        )

        self.gradient_bg_checkbox = QCheckBox("🌈 Animated gradient background")
        self.gradient_bg_checkbox.setToolTip(
            "A slowly shifting gradient behind the window content, instead of a flat color."
        )
        self.gradient_bg_checkbox.setChecked(_persisted_gradient_enabled)
        self.gradient_bg_checkbox.toggled.connect(self.gradient_background.set_animated)
        self.gradient_bg_checkbox.toggled.connect(self.gradient_style_combo.setEnabled)
        self.gradient_bg_checkbox.toggled.connect(
            lambda checked: QSettings("LocalShare", "LocalShare").setValue("gradient_enabled", checked)
        )

        # Apply the restored values to the actual background widget
        # explicitly — setCurrentText()/setChecked() above ran before
        # these signal connections existed, so relying on the signals
        # alone wouldn't reflect a restored "on" state at startup.
        self.gradient_background.set_style(self.gradient_style_combo.currentText())
        self.gradient_background.set_animated(_persisted_gradient_enabled)

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

        # No token/signup field here — Cloudflare Quick Tunnel (unlike
        # the ngrok version this replaced) needs no account, just the
        # "cloudflared" program installed and on PATH. start() in
        # tunnel.py gives clear install instructions if it's missing.

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

        # No token/signup validation needed for Global mode anymore —
        # Cloudflare Quick Tunnel just needs "cloudflared" installed,
        # which tunnel.py checks for when the tunnel actually starts
        # and reports clearly if it's missing.

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
        self.tunnel_status_label.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self.tunnel_status_label.setText("Starting internet tunnel (cloudflared)…")
        self.tunnel_status_label.show()

        self._tunnel_worker = _TunnelStartWorker(self.tunnel_handle, port)
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

        QApplication.instance().setStyleSheet(build_stylesheet(colors))
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
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(14)

        sharing_label = QLabel("SHARING")
        sharing_label.setObjectName("SectionLabel")
        layout.addWidget(sharing_label)

        settings = QSettings("LocalShare", "LocalShare")

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

        appearance_label = QLabel("APPEARANCE")
        appearance_label.setObjectName("SectionLabel")
        layout.addWidget(appearance_label)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme"))
        theme_row.addStretch()
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)

        theme_actions_row = QHBoxLayout()
        create_theme_btn = HoverGlowButton("+ Create Theme", glow_color=self.theme_colors["accent"])
        create_theme_btn.clicked.connect(self._open_custom_theme_dialog)
        export_theme_btn = HoverGlowButton("Export…", glow_color=self.theme_colors["accent"])
        export_theme_btn.clicked.connect(self._export_current_theme)
        import_theme_btn = HoverGlowButton("Import…", glow_color=self.theme_colors["accent"])
        import_theme_btn.clicked.connect(self._import_theme)
        theme_actions_row.addWidget(create_theme_btn)
        theme_actions_row.addStretch()
        theme_actions_row.addWidget(export_theme_btn)
        theme_actions_row.addWidget(import_theme_btn)
        layout.addLayout(theme_actions_row)
        self._theme_action_buttons = [create_theme_btn, export_theme_btn, import_theme_btn]

        accent_swatch_row = QHBoxLayout()
        accent_swatch_row.addWidget(QLabel("Accent color"))
        accent_swatch_row.addStretch()
        for swatch in self.accent_preset_buttons:
            accent_swatch_row.addWidget(swatch)
        layout.addLayout(accent_swatch_row)

        accent_custom_row = QHBoxLayout()
        accent_custom_row.addStretch()
        accent_custom_row.addWidget(self.accent_color_btn)
        layout.addLayout(accent_custom_row)

        layout.addWidget(self.gradient_bg_checkbox)

        gradient_style_row = QHBoxLayout()
        gradient_style_row.addWidget(QLabel("Gradient style"))
        gradient_style_row.addStretch()
        gradient_style_row.addWidget(self.gradient_style_combo)
        layout.addLayout(gradient_style_row)

        updates_label = QLabel("UPDATES")
        updates_label.setObjectName("SectionLabel")
        layout.addWidget(updates_label)
        layout.addWidget(self.auto_check_updates_checkbox)

        about_label = QLabel("ABOUT")
        about_label.setObjectName("SectionLabel")
        layout.addWidget(about_label)
        about_text = QLabel(f"LocalShare v{APP_VERSION} — Developed by ANARKALI")
        about_text.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 12px;")
        self._about_label = about_text  # kept for theme refresh
        layout.addWidget(about_text)

        close_btn = HoverGlowButton("Close", glow_color=self.theme_colors["accent"])
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        self.settings_dialog = dialog
        self._settings_close_btn = close_btn  # kept for theme/glow-color refresh

    def _open_settings_dialog(self) -> None:
        # No per-dialog stylesheet patch needed anymore — styling is
        # applied at the QApplication level (see __init__/_apply_theme),
        # which Qt reliably cascades to every window including this one.
        self.settings_dialog.exec()

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

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        if self.server_handle.is_running:
            self.server_handle.stop()
        if self.webdav_handle.is_running:
            self.webdav_handle.stop()
        if self.tunnel_handle.is_running:
            self.tunnel_handle.stop()
        event.accept()

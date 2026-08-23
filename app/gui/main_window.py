"""
Main window for LocalShare.

Phase 2: GUI shell + drag/drop + shared-items list.
Phase 3: Start/Stop Sharing now runs a real FastAPI server in a
background thread; the address shown is live and Copy Address works.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.drop_zone import DropZone
from app.gui.qr_widget import generate_qr_pixmap
from app.gui.theme import DARK, LIGHT, build_stylesheet
from app.server.http_server import ServerHandle
from app.server.webdav_server import WebDavHandle
from app.state import ShareManager, SharedItem


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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LocalShare")
        self.resize(480, 640)

        self._is_dark = True
        self._custom_accent: str | None = None  # hex string, e.g. "#FF8A3D" — None means use the theme default
        self.theme_colors = self._current_base_colors()
        self.setStyleSheet(build_stylesheet(self.theme_colors))

        self.share_manager = ShareManager()
        self.share_manager.on_change(self._refresh_shared_list)

        self.server_handle = ServerHandle(self.share_manager)
        self.webdav_handle = WebDavHandle(self.share_manager)
        self._start_worker: _ServerStartWorker | None = None
        self._stop_worker: _ServerStopWorker | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("LocalShare")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch()

        self.accent_color_btn = QPushButton("🎨")
        self.accent_color_btn.setToolTip("Choose a custom accent color")
        self.accent_color_btn.setFixedWidth(36)
        self.accent_color_btn.clicked.connect(self._choose_accent_color)
        title_row.addWidget(self.accent_color_btn)

        self.theme_toggle_btn = QPushButton("☀️ Light")
        self.theme_toggle_btn.setToolTip("Switch between dark and light theme")
        self.theme_toggle_btn.clicked.connect(self._toggle_theme)
        title_row.addWidget(self.theme_toggle_btn)

        root.addLayout(title_row)

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
        self.status_label = QLabel("Server: Stopped")
        self.address_label = QLabel("Address: —")
        self.address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.address_label)
        root.addLayout(status_row)

        # WebDAV (experimental — see tooltip). Off by default: it's the
        # weaker-security, less-reliable path, so it should be opt-in.
        self.webdav_checkbox = QCheckBox("Also enable WebDAV (Explorer-mappable, experimental)")
        self.webdav_checkbox.setToolTip(
            "Lets Windows Explorer map this share as a network drive via\n"
            "'Map Network Drive' -> 'Connect to a website'.\n\n"
            "Requires running LocalShare as Administrator: Windows' WebDAV\n"
            "client is unreliable on non-standard ports, so this uses port 80.\n\n"
            "Other limitations: shared FOLDERS\n"
            "only (not individually-shared files), and Explorer's WebDAV client\n"
            "can be slow or unreliable for very large transfers.\n"
            "For big files, use the browser address instead."
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

        self.save_qr_btn = QPushButton("Save QR Code…")
        self.save_qr_btn.clicked.connect(self._save_qr_code)
        self.save_qr_btn.hide()
        root.addWidget(self.save_qr_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._current_qr_pixmap = None

        # Action buttons
        action_row = QHBoxLayout()
        self.copy_address_btn = QPushButton("Copy Address")
        self.copy_address_btn.setEnabled(False)  # enabled once server is running (Phase 3)
        self.copy_address_btn.clicked.connect(self._copy_address)

        self.toggle_server_btn = QPushButton("Start Sharing")
        self.toggle_server_btn.setObjectName("PrimaryButton")
        self.toggle_server_btn.clicked.connect(self._on_toggle_server_clicked)

        action_row.addWidget(self.copy_address_btn)
        action_row.addStretch()
        action_row.addWidget(self.toggle_server_btn)
        root.addLayout(action_row)

        self.credit_label = QLabel("Developed by ANARKALI")
        self.credit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.credit_label.setStyleSheet(
            f"color: {self.theme_colors['text_dim']}; font-size: 11px; letter-spacing: 0.5px;"
        )
        root.addWidget(self.credit_label)

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
            self._stop_server()
            return

        if len(self.share_manager) == 0:
            QMessageBox.information(
                self, "Nothing to share", "Drag in a file or folder before starting the server."
            )
            return

        self.toggle_server_btn.setEnabled(False)
        self.toggle_server_btn.setText("Starting…")

        self._start_worker = _ServerStartWorker(self.server_handle)
        self._start_worker.finished_ok.connect(self._on_server_started)
        self._start_worker.finished_error.connect(self._on_server_start_failed)
        self._start_worker.start()

    def _on_server_started(self, address: str) -> None:
        self.status_dot.setText("●")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['success']}; font-size: 14px;")
        self.status_label.setText("Server: Running")
        self.address_label.setText(f"Address: {address}")
        self.copy_address_btn.setEnabled(True)
        self.toggle_server_btn.setText("Stop Sharing")
        self.toggle_server_btn.setEnabled(True)
        self.webdav_checkbox.setEnabled(False)  # locked while running to avoid a confusing mid-session toggle

        self._show_qr_code(address)

        if self.webdav_checkbox.isChecked():
            self._start_webdav()

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
            self.webdav_status_label.setText(f"WebDAV not started: {exc}")
            self.webdav_status_label.show()
            return
        self.webdav_status_label.setText(
            f"WebDAV: paste this into Explorer's 'Map Network Drive' dialog:\n"
            f"{self.webdav_handle.explorer_path}"
        )
        self.webdav_status_label.show()

    def _on_server_start_failed(self, error: str) -> None:
        self.toggle_server_btn.setText("Start Sharing")
        self.toggle_server_btn.setEnabled(True)
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
        self._hide_qr_code()

        self.status_dot.setText("○")
        self.status_dot.setStyleSheet(f"color: {self.theme_colors['text_dim']}; font-size: 14px;")
        self.status_label.setText("Server: Stopped")
        self.address_label.setText("Address: —")
        self.copy_address_btn.setEnabled(False)
        self.toggle_server_btn.setText("Start Sharing")
        self.toggle_server_btn.setEnabled(True)

    def _copy_address(self) -> None:
        address = self.server_handle.address
        if address:
            QGuiApplication.clipboard().setText(address)

    def _current_base_colors(self) -> dict:
        """
        A fresh copy of the active base palette (dark or light). Always
        a copy, never the shared DARK/LIGHT dict itself — accent-color
        customization mutates this per-window copy, and mutating the
        module-level constants directly would permanently corrupt the
        "true default" palette for the rest of the app's lifetime.
        """
        base = DARK if self._is_dark else LIGHT
        return dict(base)

    def _compute_hover_color(self, hex_color: str) -> str:
        """
        Derives a hover-state variant of a custom accent color. Dark
        backgrounds want a LIGHTER hover for contrast; light backgrounds
        want a DARKER one — matches the relationship already present
        between the built-in accent/accent_hover pairs in each palette.
        """
        color = QColor(hex_color)
        adjusted = color.lighter(115) if self._is_dark else color.darker(115)
        return adjusted.name()

    def _apply_theme(self) -> None:
        """Rebuilds theme_colors from the current base + any custom accent
        override, then pushes it out to every widget that needs it."""
        colors = self._current_base_colors()
        if self._custom_accent:
            colors["accent"] = self._custom_accent
            colors["accent_hover"] = self._compute_hover_color(self._custom_accent)
        self.theme_colors = colors

        self.setStyleSheet(build_stylesheet(colors))
        self.drop_zone.set_theme(colors)
        self.theme_toggle_btn.setText("☀️ Light" if self._is_dark else "🌙 Dark")

        dim_style = f"color: {colors['text_dim']}; font-size: 12px;"
        self.webdav_status_label.setStyleSheet(dim_style)
        self.qr_caption_label.setStyleSheet(dim_style)
        self.credit_label.setStyleSheet(
            f"color: {colors['text_dim']}; font-size: 11px; letter-spacing: 0.5px;"
        )

        # status dot color depends on server state, not just theme
        if self.server_handle.is_running:
            self.status_dot.setStyleSheet(f"color: {colors['success']}; font-size: 14px;")
        else:
            self.status_dot.setStyleSheet(f"color: {colors['text_dim']}; font-size: 14px;")

    def _toggle_theme(self) -> None:
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _choose_accent_color(self) -> None:
        initial = QColor(self.theme_colors["accent"])
        color = QColorDialog.getColor(initial, self, "Choose Accent Color")
        if not color.isValid():
            return  # user cancelled
        self._custom_accent = color.name()
        self._apply_theme()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        if self.server_handle.is_running:
            self.server_handle.stop()
        if self.webdav_handle.is_running:
            self.webdav_handle.stop()
        event.accept()

"""
DropZone: a widget that accepts files and folders dragged from Windows
Explorer (or anywhere else) and emits their absolute paths.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

from app.gui.theme import DARK


class DropZone(QWidget):
    """Emits `pathsDropped(list[str])` with absolute paths of dropped files/folders."""

    pathsDropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        self.setObjectName("DropZone")
        self._colors = DARK
        self._active = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_label = QLabel("📂")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 40px;")
        self._add_readability_shadow(self._icon_label)

        self._text_label = QLabel("Drag & drop files or folders here")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setObjectName("DropZoneText")
        self._add_readability_shadow(self._text_label)

        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)

        self._apply_style()

    def _add_readability_shadow(self, label: QLabel) -> None:
        """Same technique as MainWindow's version — this widget's own
        background is transparent (just a dashed border), so its icon
        and text sit directly on whatever animated/image/video
        background is active, which can be almost any color."""
        shadow = QGraphicsDropShadowEffect(label)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 200))
        label.setGraphicsEffect(shadow)

    def set_theme(self, colors: dict) -> None:
        """Called by MainWindow when the user switches theme."""
        self._colors = colors
        self._apply_style()

    # -- styling -----------------------------------------------------------
    def _apply_style(self) -> None:
        border_color = self._colors["accent"] if self._active else self._colors["border"]
        bg_color = (
            f"rgba(76, 141, 255, 0.08)" if self._active else "transparent"
        )
        self.setStyleSheet(
            f"""
            #DropZone {{
                border: 2px dashed {border_color};
                border-radius: 12px;
                background-color: {bg_color};
            }}
            #DropZoneText {{
                color: {self._colors['text_dim']};
                font-size: 13px;
            }}
            """
        )

    # -- drag & drop events -----------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._active = True
            self._apply_style()
            self._text_label.setText("Release to share")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._active = False
        self._apply_style()
        self._text_label.setText("Drag & drop files or folders here")

    def dropEvent(self, event: QDropEvent) -> None:
        self._active = False
        self._apply_style()
        self._text_label.setText("Drag & drop files or folders here")

        paths: list[str] = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                paths.append(local_path)

        if paths:
            self.pathsDropped.emit(paths)
        event.acceptProposedAction()

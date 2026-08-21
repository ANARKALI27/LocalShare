"""
DropZone: a widget that accepts files and folders dragged from Windows
Explorer (or anywhere else) and emits their absolute paths.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class DropZone(QWidget):
    """Emits `pathsDropped(list[str])` with absolute paths of dropped files/folders."""

    pathsDropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        self.setObjectName("DropZone")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_label = QLabel("📂")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 40px;")

        self._text_label = QLabel("Drag & drop files or folders here")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setObjectName("DropZoneText")

        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)

        self._apply_style(active=False)

    # -- styling -----------------------------------------------------------
    def _apply_style(self, active: bool) -> None:
        border_color = "#4C8DFF" if active else "#3A3D46"
        bg_color = "rgba(76, 141, 255, 0.08)" if active else "transparent"
        self.setStyleSheet(
            f"""
            #DropZone {{
                border: 2px dashed {border_color};
                border-radius: 12px;
                background-color: {bg_color};
            }}
            #DropZoneText {{
                color: #A9ACB5;
                font-size: 13px;
            }}
            """
        )

    # -- drag & drop events -----------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_style(active=True)
            self._text_label.setText("Release to share")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._apply_style(active=False)
        self._text_label.setText("Drag & drop files or folders here")

    def dropEvent(self, event: QDropEvent) -> None:
        self._apply_style(active=False)
        self._text_label.setText("Drag & drop files or folders here")

        paths: list[str] = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                paths.append(local_path)

        if paths:
            self.pathsDropped.emit(paths)
        event.acceptProposedAction()

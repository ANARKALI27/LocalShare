"""
Custom theme builder — lets someone pick their own core colors and
see a live preview, rather than being limited to the built-in presets.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import CORE_KEYS, derive_full_palette

CORE_LABELS = {
    "bg": "Background",
    "surface": "Surface",
    "border": "Border",
    "text": "Text",
    "text_dim": "Muted Text",
    "accent": "Accent",
    "success": "Success",
    "danger": "Danger",
}


class CustomThemeDialog(QDialog):
    """
    Modal dialog for building a custom theme. Call exec() and check the
    result — on QDialog.Accepted, result_colors() gives the full
    derived 13-key palette ready to apply/save.
    """

    def __init__(self, initial_colors: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Theme")
        self.setMinimumWidth(360)

        # Seed the pickers from whatever's currently active — editing
        # a starting point is much friendlier than picking 8 colors
        # completely from scratch.
        self.core_colors = {key: initial_colors.get(key, "#888888") for key in CORE_KEYS}
        self._swatch_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        for key in CORE_KEYS:
            row = QHBoxLayout()
            row.addWidget(QLabel(CORE_LABELS[key]))
            row.addStretch()
            swatch = QPushButton()
            swatch.setFixedSize(32, 22)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.clicked.connect(lambda checked=False, k=key: self._pick_color(k))
            self._swatch_buttons[key] = swatch
            row.addWidget(swatch)
            layout.addLayout(row)

        preview_label_heading = QLabel("Preview")
        layout.addWidget(preview_label_heading)

        self.preview = QWidget()
        self.preview.setFixedHeight(70)
        preview_layout = QVBoxLayout(self.preview)
        self.preview_text = QLabel("Sample Text")
        self.preview_button = QLabel("  Sample Button  ")
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(self.preview_button)
        layout.addWidget(self.preview)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Theme…")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._refresh_swatches()
        self._refresh_preview()

    def _pick_color(self, key: str) -> None:
        initial = QColor(self.core_colors[key])
        color = QColorDialog.getColor(initial, self, f"Choose {CORE_LABELS[key]} Color")
        if not color.isValid():
            return  # user cancelled
        self.core_colors[key] = color.name()
        self._refresh_swatches()
        self._refresh_preview()

    def _refresh_swatches(self) -> None:
        for key, btn in self._swatch_buttons.items():
            btn.setStyleSheet(
                f"background-color: {self.core_colors[key]}; "
                f"border: 1px solid rgba(255,255,255,0.25); border-radius: 4px;"
            )

    def _refresh_preview(self) -> None:
        full = derive_full_palette(self.core_colors)
        self.preview.setStyleSheet(
            f"background-color: {full['bg']}; border: 1px solid {full['border']}; border-radius: 8px;"
        )
        self.preview_text.setStyleSheet(f"color: {full['text']}; background: transparent; padding: 4px 8px;")
        self.preview_button.setStyleSheet(
            f"background-color: {full['accent']}; color: white; border-radius: 5px; "
            f"padding: 4px 8px; margin: 0 8px;"
        )

    def result_colors(self) -> dict:
        """The full, derived 13-key palette — call after exec() returns Accepted."""
        return derive_full_palette(self.core_colors)

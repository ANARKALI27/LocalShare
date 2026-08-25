"""
Optional animated gradient background for the main window's content
area. Off by default — a toggle in the GUI turns it on. When off, it
just paints a flat fill matching the current theme (identical to the
previous plain background); when on, a diagonal gradient slowly
sweeps between the theme's background and accent colors.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget


class AnimatedGradientBackground(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg_color = QColor("#1E1F26")
        self._accent_color = QColor("#4C8DFF")
        self._animated = False
        self._start_time = time.monotonic()

        self._timer = QTimer(self)
        self._timer.setInterval(50)  # ~20fps — smooth enough, light on CPU
        self._timer.timeout.connect(self.update)

    def set_colors(self, bg_hex: str, accent_hex: str) -> None:
        self._bg_color = QColor(bg_hex)
        self._accent_color = QColor(accent_hex)
        self.update()

    def set_animated(self, enabled: bool) -> None:
        self._animated = enabled
        if enabled:
            self._start_time = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        painter = QPainter(self)

        if not self._animated:
            painter.fillRect(self.rect(), self._bg_color)
            painter.end()
            return

        elapsed = time.monotonic() - self._start_time
        w, h = max(self.width(), 1), max(self.height(), 1)

        # Sweep the gradient's angle slowly (full rotation every ~20s)
        # and let the accent stop's position drift back and forth, so
        # it never looks static or robotically uniform.
        angle = (elapsed / 20.0) * 2 * math.pi
        x1 = w / 2 + math.cos(angle) * w * 0.6
        y1 = h / 2 + math.sin(angle) * h * 0.6
        x2 = w / 2 - math.cos(angle) * w * 0.6
        y2 = h / 2 - math.sin(angle) * h * 0.6

        gradient = QLinearGradient(x1, y1, x2, y2)
        accent_dim = QColor(self._accent_color)
        accent_dim.setAlpha(60)  # kept subtle — this is a background, not the main event

        gradient.setColorAt(0.0, self._bg_color)
        gradient.setColorAt(0.5, accent_dim)
        gradient.setColorAt(1.0, self._bg_color)

        painter.fillRect(self.rect(), gradient)
        painter.end()

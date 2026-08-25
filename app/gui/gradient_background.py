"""
Optional animated gradient background for the main window's content
area. Off by default — a toggle in the GUI turns it on, and a style
picker chooses which animation. When off, it paints a flat fill
matching the current theme (identical to the previous plain background).
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

STYLES = ["Sweep", "Pulse", "Aurora"]


class AnimatedGradientBackground(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg_color = QColor("#1E1F26")
        self._accent_color = QColor("#4C8DFF")
        self._animated = False
        self._style = "Sweep"
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

    def set_style(self, style: str) -> None:
        if style in STYLES:
            self._style = style
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._animated:
            painter.fillRect(self.rect(), self._bg_color)
            painter.end()
            return

        elapsed = time.monotonic() - self._start_time
        w, h = max(self.width(), 1), max(self.height(), 1)

        if self._style == "Pulse":
            self._paint_pulse(painter, w, h, elapsed)
        elif self._style == "Aurora":
            self._paint_aurora(painter, w, h, elapsed)
        else:
            self._paint_sweep(painter, w, h, elapsed)

        painter.end()

    def _paint_sweep(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """Original style: a diagonal linear gradient slowly rotating around the center."""
        angle = (elapsed / 20.0) * 2 * math.pi
        x1 = w / 2 + math.cos(angle) * w * 0.6
        y1 = h / 2 + math.sin(angle) * h * 0.6
        x2 = w / 2 - math.cos(angle) * w * 0.6
        y2 = h / 2 - math.sin(angle) * h * 0.6

        gradient = QLinearGradient(x1, y1, x2, y2)
        accent_dim = QColor(self._accent_color)
        accent_dim.setAlpha(60)

        gradient.setColorAt(0.0, self._bg_color)
        gradient.setColorAt(0.5, accent_dim)
        gradient.setColorAt(1.0, self._bg_color)

        painter.fillRect(self.rect(), gradient)

    def _paint_pulse(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """A radial glow at the center that slowly breathes in and out."""
        painter.fillRect(self.rect(), self._bg_color)

        pulse = 0.5 + 0.5 * math.sin(elapsed * (2 * math.pi / 6.0))  # ~6s per breath, stays in 0..1
        max_radius = math.hypot(w, h) * 0.6
        radius = max_radius * (0.35 + 0.35 * pulse)

        gradient = QRadialGradient(QPointF(w / 2, h / 2), max(radius, 1.0))
        accent_dim = QColor(self._accent_color)
        accent_dim.setAlpha(int(50 + 40 * pulse))
        faded = QColor(self._accent_color)
        faded.setAlpha(0)

        gradient.setColorAt(0.0, accent_dim)
        gradient.setColorAt(1.0, faded)

        painter.fillRect(self.rect(), gradient)

    def _paint_aurora(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """A few soft colored blobs drifting slowly at different speeds/paths — the
        classic 'aurora' / mesh-gradient look, kept subtle since this is a background."""
        painter.fillRect(self.rect(), self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # Three blobs with distinct periods/phases so they never fall
        # into visible sync with each other.
        blobs = [
            (0.35, 0.0, 13.0),
            (0.65, 2.1, 17.0),
            (0.5, 4.2, 21.0),
        ]
        blob_radius = math.hypot(w, h) * 0.35

        for base_alpha, phase, period in blobs:
            t = (elapsed / period) * 2 * math.pi + phase
            cx = w / 2 + math.sin(t) * w * 0.32
            cy = h / 2 + math.cos(t * 0.8) * h * 0.32

            gradient = QRadialGradient(QPointF(cx, cy), max(blob_radius, 1.0))
            core = QColor(self._accent_color)
            core.setAlpha(int(45 * base_alpha))
            edge = QColor(self._accent_color)
            edge.setAlpha(0)

            gradient.setColorAt(0.0, core)
            gradient.setColorAt(1.0, edge)

            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), blob_radius, blob_radius)

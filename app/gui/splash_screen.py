"""
Splash screen shown briefly when the app starts: "LocalShare" with a
sparkle/glitter animation and a "Developed By ANARKALI" credit line.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGraphicsOpacityEffect, QPainter, QRadialGradient
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.theme import DARK


class _Sparkle:
    """One glinting particle: fixed position, independent twinkle timing/color."""

    __slots__ = ("x", "y", "phase", "speed", "size", "color")

    def __init__(self) -> None:
        self.x = random.uniform(0.05, 0.95)  # normalized 0..1, scaled to widget size at paint time
        self.y = random.uniform(0.05, 0.95)
        self.phase = random.uniform(0, math.tau)
        self.speed = random.uniform(1.5, 3.2)
        self.size = random.uniform(2.0, 5.0)
        self.color = random.choice(
            [
                QColor(255, 255, 255),  # white
                QColor(255, 214, 102),  # gold
                QColor(124, 178, 255),  # soft blue
            ]
        )


class SplashScreen(QWidget):
    """
    A frameless, centered window that shows a sparkle animation behind
    the title/subtitle, fades in, holds, fades out, then emits
    `finished` so the caller can show the real MainWindow.
    """

    finished = Signal()

    SPARKLE_COUNT = 28

    def __init__(self, hold_ms: int = 1400, fade_ms: int = 500) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(420, 260)

        self._bg_color = QColor(DARK["bg"])
        self._sparkles = [_Sparkle() for _ in range(self.SPARKLE_COUNT)]
        self._start_time = time.monotonic()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        title = QLabel("LocalShare")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {DARK['text']}; font-size: 34px; font-weight: 700; "
            f'font-family: "Segoe UI", sans-serif; background: transparent;'
        )

        subtitle = QLabel("Developed By ANARKALI")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"color: {DARK['text_dim']}; font-size: 13px; letter-spacing: 1px; "
            f'font-family: "Segoe UI", sans-serif; background: transparent;'
        )

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Fade the whole window in/out from transparent to opaque.
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_in.setDuration(fade_ms)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hold_ms = hold_ms
        self._fade_ms = fade_ms
        self._fade_out_anim: QPropertyAnimation | None = None

        # Redraws the sparkle field on a steady tick while the splash is visible.
        self._sparkle_timer = QTimer(self)
        self._sparkle_timer.setInterval(50)  # ~20fps — plenty smooth for a subtle background glint
        self._sparkle_timer.timeout.connect(self.update)

    def start(self) -> None:
        self._center_on_screen()
        self.show()
        self._fade_in.start()
        self._sparkle_timer.start()
        QTimer.singleShot(self._fade_ms + self._hold_ms, self._fade_out)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill the background explicitly rather than relying on a QSS
        # background-color, since overriding paintEvent on a plain
        # QWidget bypasses the stylesheet's automatic background fill.
        painter.fillRect(self.rect(), self._bg_color)

        elapsed = time.monotonic() - self._start_time
        w, h = self.width(), self.height()

        painter.setPen(Qt.PenStyle.NoPen)
        for sp in self._sparkles:
            twinkle = 0.15 + 0.85 * abs(math.sin(elapsed * sp.speed + sp.phase))
            color = QColor(sp.color)
            color.setAlphaF(twinkle * 0.9)

            cx, cy = sp.x * w, sp.y * h
            radius = sp.size * (0.6 + 0.4 * twinkle)

            gradient = QRadialGradient(QPointF(cx, cy), radius * 2)
            gradient.setColorAt(0.0, color)
            faded = QColor(color)
            faded.setAlpha(0)
            gradient.setColorAt(1.0, faded)

            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), radius * 2, radius * 2)

        painter.end()
        # Qt paints child widgets (the title/subtitle labels) after this
        # returns, so they naturally layer on top of the sparkle field.

    def _fade_out(self) -> None:
        fade_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        fade_out.setDuration(self._fade_ms)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(self._on_fade_out_done)
        fade_out.start()
        self._fade_out_anim = fade_out  # keep a reference so it isn't garbage-collected mid-animation

    def _on_fade_out_done(self) -> None:
        self._sparkle_timer.stop()
        self.close()
        self.finished.emit()

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )

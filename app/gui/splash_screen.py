"""
Splash screen shown briefly when the app starts: "LocalShare" with a
sparkle/glitter animation and a "Developed By ANARKALI" credit line.

The window itself is genuinely transparent (desktop shows through
outside the rounded panel) rather than a solid rectangle — only the
rounded panel area is filled, so it reads as a floating card rather
than a plain opaque box. Entrance uses a combined fade + scale-in
transition; exit is a plain fade-out, unchanged from before.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

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
    A frameless, transparent, centered window that shows a sparkle
    animation behind the title/subtitle on a rounded panel, fades +
    scales in, holds, fades out, then emits `finished` so the caller
    can show the real MainWindow.
    """

    finished = Signal()

    SPARKLE_COUNT = 28

    def __init__(self, hold_ms: int = 1400, fade_ms: int = 500) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        # Makes the window's own background genuinely transparent — only
        # what paintEvent actually draws (the rounded panel + sparkles)
        # is visible; everything else shows the desktop through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(420, 260)

        self._panel_color = QColor(DARK["bg"])
        self._panel_color.setAlphaF(0.92)  # slightly translucent panel, not fully opaque
        self._sparkles = [_Sparkle() for _ in range(self.SPARKLE_COUNT)]
        self._start_time = time.monotonic()
        self._scale = 0.92  # entrance starts slightly zoomed-out, animates to 1.0

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

        # Scale-in runs alongside the fade — a small "pop" on entrance,
        # driven by a plain QTimer since QPropertyAnimation can't target
        # a bare Python attribute directly without a QObject property.
        self._scale_start_time = time.monotonic()
        self._scale_duration = fade_ms / 1000.0
        self._scale_timer = QTimer(self)
        self._scale_timer.setInterval(16)  # ~60fps — this is a short, one-shot entrance effect
        self._scale_timer.timeout.connect(self._advance_scale)

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
        self._scale_start_time = time.monotonic()
        self._scale_timer.start()
        QTimer.singleShot(self._fade_ms + self._hold_ms, self._fade_out)

    def _advance_scale(self) -> None:
        t = (time.monotonic() - self._scale_start_time) / max(self._scale_duration, 0.001)
        if t >= 1.0:
            self._scale = 1.0
            self._scale_timer.stop()
        else:
            # ease-out cubic, matching the fade's easing curve so both
            # transitions finish in visual sync
            eased = 1 - (1 - t) ** 3
            self._scale = 0.92 + 0.08 * eased
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Scale around the center for the entrance "pop" — everything
        # below is drawn in this transformed space.
        painter.translate(w / 2, h / 2)
        painter.scale(self._scale, self._scale)
        painter.translate(-w / 2, -h / 2)

        # Rounded panel, not a plain rect — this is what makes the
        # transparency actually visible (desktop shows through the
        # corners/margins outside this shape) rather than just being a
        # technically-transparent-but-visually-identical solid window.
        panel_rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(panel_rect, 22, 22)
        painter.fillPath(path, self._panel_color)
        painter.setClipPath(path)  # keep sparkles confined to the panel shape

        elapsed = time.monotonic() - self._start_time

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


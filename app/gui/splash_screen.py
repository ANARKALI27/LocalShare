"""
Splash screen shown briefly when the app starts: "LocalShare" over an
animated version of the app's own share-glyph icon (three connected
nodes, on the same blue-to-purple gradient as the actual app icon) —
previously a plain dark panel with generic gold/white/blue sparkles
that had no visual connection to the app's actual branding.

The window itself is genuinely transparent (desktop shows through
outside the rounded panel) rather than a solid rectangle — only the
rounded panel area is filled, so it reads as a floating card rather
than a plain opaque box. Entrance uses a combined fade + scale-in
transition; exit is a plain fade-out, unchanged from before.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

# Same two colors as assets/localshare.ico/.png — the splash panel
# should look like it belongs to the same app as its own taskbar icon.
_GRADIENT_START = QColor(76, 141, 255)   # #4C8DFF
_GRADIENT_END = QColor(168, 85, 247)     # #A855F7


class SplashScreen(QWidget):
    """
    A frameless, transparent, centered window that shows the animated
    share-glyph on a gradient panel behind the title/subtitle, fades +
    scales in, holds, fades out, then emits `finished` so the caller
    can show the real MainWindow.
    """

    finished = Signal()

    def __init__(self, hold_ms: int = 1400, fade_ms: int = 500) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        # Makes the window's own background genuinely transparent — only
        # what paintEvent actually draws (the rounded panel + glyph)
        # is visible; everything else shows the desktop through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(420, 260)

        self._start_time = time.monotonic()
        self._scale = 0.92  # entrance starts slightly zoomed-out, animates to 1.0

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(0, 70, 0, 0)  # leaves room above for the glyph, drawn in paintEvent

        title = QLabel("LocalShare")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: white; font-size: 34px; font-weight: 700; "
            'font-family: "Segoe UI", sans-serif; background: transparent;'
        )

        subtitle = QLabel("Developed By ANARKALI")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            "color: rgba(255, 255, 255, 0.75); font-size: 13px; letter-spacing: 1px; "
            'font-family: "Segoe UI", sans-serif; background: transparent;'
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

        # Drives the glyph's pulse animation while the splash is visible.
        self._glyph_timer = QTimer(self)
        self._glyph_timer.setInterval(33)  # ~30fps — smooth enough for a slow pulse, lighter than 60fps
        self._glyph_timer.timeout.connect(self.update)

    def start(self) -> None:
        self._center_on_screen()
        self.show()
        self._fade_in.start()
        self._glyph_timer.start()
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
        # Filled with the same diagonal gradient as the app's own icon,
        # rather than a plain dark color, so the splash actually looks
        # like it belongs to this app.
        panel_rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(panel_rect, 22, 22)
        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0.0, _GRADIENT_START)
        gradient.setColorAt(1.0, _GRADIENT_END)
        painter.fillPath(path, gradient)
        painter.setClipPath(path)  # keep the glyph confined to the panel shape

        self._draw_glyph(painter, w)

        painter.end()
        # Qt paints child widgets (the title/subtitle labels) after this
        # returns, so they naturally layer on top of the glyph.

    def _draw_glyph(self, painter: QPainter, panel_width: int) -> None:
        """
        The same three-node share glyph as the app's icon, centered in
        the upper portion of the panel (the labels below occupy the
        rest). Animated with a soft pulse on each node and a small dot
        traveling along each connecting line, suggesting data actively
        moving between the nodes — a loading-screen animation that's
        actually about what this app does, not a generic effect.
        """
        elapsed = time.monotonic() - self._start_time
        white = QColor(255, 255, 255)

        cx = panel_width / 2 - 30
        cy = 70.0
        top = QPointF(cx + 70, cy - 35)
        bottom = QPointF(cx + 70, cy + 35)
        center = QPointF(cx, cy)

        painter.setPen(QColor(255, 255, 255, 130))
        painter.drawLine(center, top)
        painter.drawLine(center, bottom)

        # A soft pulsing glow behind the main node, breathing slowly —
        # this is the "loading" cue, replacing the old sparkle field.
        pulse = 0.5 + 0.5 * math.sin(elapsed * 2.4)
        glow_radius = 22 + 6 * pulse
        glow = QRadialGradient(center, glow_radius)
        glow_color = QColor(white)
        glow_color.setAlphaF(0.35 * pulse)
        glow.setColorAt(0.0, glow_color)
        faded = QColor(white)
        faded.setAlpha(0)
        glow.setColorAt(1.0, faded)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_radius, glow_radius)

        painter.setBrush(white)
        painter.drawEllipse(center, 15, 15)
        painter.drawEllipse(top, 11, 11)
        painter.drawEllipse(bottom, 11, 11)

        # Small dots traveling from the main node outward along each
        # line, looping — visually reads as "sending," matching what
        # the icon's static version can only imply.
        for target, phase_offset in ((top, 0.0), (bottom, 0.5)):
            t = (elapsed * 0.6 + phase_offset) % 1.0
            travel_x = center.x() + (target.x() - center.x()) * t
            travel_y = center.y() + (target.y() - center.y()) * t
            dot_alpha = math.sin(t * math.pi)  # fades in at the start, out at the end of each trip
            dot_color = QColor(white)
            dot_color.setAlphaF(max(0.0, dot_alpha))
            painter.setBrush(dot_color)
            painter.drawEllipse(QPointF(travel_x, travel_y), 4, 4)

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
        self._glyph_timer.stop()
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


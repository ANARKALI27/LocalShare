"""
Splash screen shown briefly when the app starts: "LocalShare" with a
fade-in animation and a "Developed By ANARKALI" credit line.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from app.gui.theme import DARK


class SplashScreen(QWidget):
    """
    A frameless, centered window that fades its content in, holds for a
    moment, then emits `finished` so the caller can show the real
    MainWindow and close this one.
    """

    finished = Signal()

    def __init__(self, hold_ms: int = 1400, fade_ms: int = 500) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(420, 260)
        self.setStyleSheet(f"background-color: {DARK['bg']};")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        title = QLabel("LocalShare")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {DARK['text']}; font-size: 34px; font-weight: 700; "
            f'font-family: "Segoe UI", sans-serif;'
        )

        subtitle = QLabel("Developed By ANARKALI")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"color: {DARK['text_dim']}; font-size: 13px; letter-spacing: 1px; "
            f'font-family: "Segoe UI", sans-serif;'
        )

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Fade the whole window in from transparent to opaque.
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

    def start(self) -> None:
        self._center_on_screen()
        self.show()
        self._fade_in.start()
        # hold, then fade out, then signal we're done
        QTimer.singleShot(self._fade_ms + self._hold_ms, self._fade_out)

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

"""
A QPushButton with a smooth animated glow on hover.

Implemented via an animated QGraphicsDropShadowEffect rather than
trying to animate the button's own background color: Qt's stylesheet
system already paints QPushButton backgrounds (including :hover
states) as part of its base rendering, and fighting that with custom
paintEvent color-blending is fragile and easy to get subtly wrong
without a real display to check it against. A soft glow layered on
top works with the stylesheet instead of against it, and is a
reliable, well-supported way to get a genuine animated transition.
"""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton

# Module-level so Settings -> Performance can adjust every button's
# hover animation at once (Quality/Balanced/Performance modes) without
# needing to reach into each individual button instance. Read fresh at
# animation-trigger time, not cached at construction — see enterEvent/
# leaveEvent below.
ANIMATION_DURATION_MS = 180
MAX_GLOW_RADIUS = 20


class HoverGlowButton(QPushButton):
    def __init__(self, *args, glow_color: str = "#4C8DFF", **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setColor(QColor(glow_color))
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(0)
        self.setGraphicsEffect(self._shadow)

        self._animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_glow_color(self, color_hex: str) -> None:
        self._shadow.setColor(QColor(color_hex))

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        self._animation.stop()
        self._animation.setDuration(ANIMATION_DURATION_MS)
        self._animation.setStartValue(self._shadow.blurRadius())
        self._animation.setEndValue(MAX_GLOW_RADIUS)
        self._animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        self._animation.stop()
        self._animation.setDuration(ANIMATION_DURATION_MS)
        self._animation.setStartValue(self._shadow.blurRadius())
        self._animation.setEndValue(0)
        self._animation.start()
        super().leaveEvent(event)

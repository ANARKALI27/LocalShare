"""
The main window's background layer. Supports four modes:
  - "solid": a flat fill matching the current theme (the original,
    always-safe default)
  - "gradient": the animated gradient styles (Sweep/Pulse/Aurora)
  - "image": a user-picked image (JPG/PNG/WEBP), with position,
    scaling, opacity, and a readability overlay
  - "video": a user-picked video (MP4/WEBM) looping silently in the
    background

Solid and gradient modes are unchanged from before and remain fully
tested. Image mode is new but low-risk (QPixmap, no new dependency).
Video mode is the one genuinely unverified piece of this whole
project — it needs QtMultimedia (never used elsewhere here), and I
have no way to confirm actual frame decoding, performance while the
file server is also running, or Windows DPI behavior without a real
machine. It's implemented defensively (lazy import, error signal
handling, graceful fallback to solid color on any failure) but should
be the first thing tested on a real run.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.gui.background_layout_math import compute_image_placement

STYLES = ["Sweep", "Pulse", "Aurora", "Mesh", "Fluid", "Snow", "Rain", "Fire"]
PARTICLE_STYLES = ["Snow", "Rain", "Fire"]
MODES = ["solid", "gradient", "image", "video"]


class AnimatedGradientBackground(QWidget):
    _SNOW_COUNT = 45
    _RAIN_COUNT = 60
    _FIRE_COUNT = 35

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg_color = QColor("#1E1F26")
        self._accent_color = QColor("#4C8DFF")
        self._mode = "solid"
        self._style = "Sweep"
        self._start_time = time.monotonic()

        # -- image mode state --
        self._image_path: str | None = None
        self._image_pixmap: QPixmap | None = None
        self._image_position = "Center"
        self._image_scaling = "Fill"
        self._image_opacity = 1.0
        self._overlay_opacity = 0.35  # a dark scrim over the image, for text readability

        # -- video mode state --
        self._video_path: str | None = None
        self._video_opacity = 1.0
        self._video_loop = True
        self._video_muted = True
        self._video_autoplay = True
        self._video_speed = 1.0
        self._video_player = None  # QMediaPlayer, created lazily only if video mode is actually used
        self._video_sink = None
        self._current_video_image: QImage | None = None
        self._video_error: str | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(50)  # ~20fps default (Balanced) — see set_performance_mode()
        self._timer.timeout.connect(self.update)
        self._reduce_motion = False

    # -- performance / reduce motion -----------------------------------------------------------

    def set_performance_mode(self, mode: str) -> None:
        """Adjusts the animated-background frame rate. Quality/Balanced/
        Performance trade smoothness for lighter CPU/GPU use — a real,
        directly-controlled effect, not just a label."""
        intervals = {"Quality": 33, "Balanced": 50, "Performance": 100}  # ms per frame: ~30/20/10fps
        self._timer.setInterval(intervals.get(mode, 50))

    def set_reduce_motion(self, enabled: bool) -> None:
        """Freezes whatever's currently animating (gradient timer,
        video playback) without changing the selected background mode
        — reduce motion is about removing movement, not switching away
        from the look someone chose."""
        self._reduce_motion = enabled
        if enabled:
            self._timer.stop()
            if self._video_player is not None:
                self._video_player.pause()
        else:
            if self._mode == "gradient":
                self._timer.start()
            elif self._mode == "video" and self._video_player is not None and self._video_autoplay:
                self._video_player.play()

    # -- mode / solid / gradient (unchanged behavior from before) -----------------

    def set_colors(self, bg_hex: str, accent_hex: str) -> None:
        self._bg_color = QColor(bg_hex)
        self._accent_color = QColor(accent_hex)
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self._mode = mode
        if mode == "gradient" and not self._reduce_motion:
            self._start_time = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()
        if mode == "video":
            self._ensure_video_player()
            if self._video_player is not None and self._video_autoplay and not self._reduce_motion:
                self._video_player.play()
        elif self._video_player is not None:
            self._video_player.pause()
        self.update()

    def set_animated(self, enabled: bool) -> None:
        """Back-compat with the old checkbox-based API: 'animated' now
        just means mode == 'gradient' vs 'solid'."""
        self.set_mode("gradient" if enabled else "solid")

    def set_style(self, style: str) -> None:
        if style in STYLES:
            self._style = style
            self.update()

    # -- image mode -----------------------------------------------------------

    def set_image(self, path: str | None, position: str, scaling: str, opacity: float, overlay_opacity: float) -> bool:
        """Loads an image for background use. Returns False (and leaves
        the previous image in place) if the file can't be loaded as an
        image — never raises, since a corrupt/unsupported file
        shouldn't crash the app."""
        self._image_position = position
        self._image_scaling = scaling
        self._image_opacity = max(0.0, min(1.0, opacity))
        self._overlay_opacity = max(0.0, min(1.0, overlay_opacity))

        if path is None:
            self._image_path = None
            self._image_pixmap = None
            self.update()
            return True

        if not os.path.isfile(path):
            return False

        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False  # unsupported/corrupt file — caller should show an error, not crash

        self._image_path = path
        self._image_pixmap = pixmap
        self.update()
        return True

    # -- video mode -----------------------------------------------------------

    def _ensure_video_player(self) -> None:
        if self._video_player is not None:
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except ImportError:
            self._video_error = 'Video backgrounds need the QtMultimedia module (part of PySide6-Addons).'
            return

        player = QMediaPlayer(self)
        sink = QVideoSink(self)
        player.setVideoSink(sink)
        # Deliberately never call player.setAudioOutput(...) — with no
        # audio output attached at all, playback is silent by
        # construction, which is a simpler and more certain way to
        # guarantee "muted by default" than attaching one and setting
        # its volume to zero.
        sink.videoFrameChanged.connect(self._on_video_frame)
        player.errorOccurred.connect(self._on_video_error)

        self._video_player = player
        self._video_sink = sink

    def _on_video_frame(self, frame) -> None:
        image = frame.toImage()
        if not image.isNull():
            self._current_video_image = image
            self.update()

    def _on_video_error(self, error, error_string: str) -> None:
        self._video_error = error_string or "Unknown video playback error"
        # Fail gracefully rather than leaving a frozen/broken video
        # visible — fall back to a flat fill.
        self.set_mode("solid")

    def set_video(self, path: str | None, loop: bool, muted: bool, autoplay: bool, opacity: float, speed: float) -> bool:
        """
        Loads a video for background use. muted is accepted for API
        symmetry with the settings dialog, but playback is always
        silent regardless (see _ensure_video_player) — there's no
        audio output attached at all, so there's nothing to un-mute.
        Returns False if QtMultimedia isn't available or the player
        can't be created; never raises.
        """
        self._video_loop = loop
        self._video_muted = muted
        self._video_autoplay = autoplay
        self._video_speed = max(0.5, min(2.0, speed))
        self._video_opacity = max(0.0, min(1.0, opacity))

        if path is None:
            self._video_path = None
            if self._video_player is not None:
                self._video_player.stop()
            self._current_video_image = None
            self.update()
            return True

        if not os.path.isfile(path):
            return False

        self._ensure_video_player()
        if self._video_player is None:
            return False  # QtMultimedia unavailable — see self._video_error

        from PySide6.QtCore import QUrl

        self._video_path = path
        self._video_error = None
        self._video_player.setSource(QUrl.fromLocalFile(path))
        self._video_player.setLoops(-1 if loop else 1)  # -1 = QMediaPlayer.Infinite
        self._video_player.setPlaybackRate(self._video_speed)
        if autoplay:
            self._video_player.play()
        return True

    def pause_for_minimize(self) -> None:
        """Called when the window is minimized — pauses video decoding
        and gradient animation so neither burns CPU/GPU while nothing
        is visible."""
        if self._video_player is not None and self._mode == "video":
            self._video_player.pause()
        if self._mode == "gradient":
            self._timer.stop()

    def resume_from_minimize(self) -> None:
        if self._reduce_motion:
            return  # stays paused either way if reduce motion is on
        if self._video_player is not None and self._mode == "video" and self._video_autoplay:
            self._video_player.play()
        if self._mode == "gradient":
            self._timer.start()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt's naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._mode == "gradient":
            self._paint_gradient(painter)
        elif self._mode == "image" and self._image_pixmap is not None:
            self._paint_image(painter)
        elif self._mode == "video" and self._current_video_image is not None:
            self._paint_video(painter)
        else:
            # "solid", or a non-gradient mode that has nothing loaded
            # yet (e.g. "image" mode selected but no file chosen) —
            # always safe to fall back to a flat fill rather than
            # painting nothing at all.
            painter.fillRect(self.rect(), self._bg_color)

        painter.end()

    def _paint_gradient(self, painter: QPainter) -> None:
        elapsed = time.monotonic() - self._start_time
        w, h = max(self.width(), 1), max(self.height(), 1)
        if self._style == "Pulse":
            self._paint_pulse(painter, w, h, elapsed)
        elif self._style == "Aurora":
            self._paint_aurora(painter, w, h, elapsed)
        elif self._style == "Mesh":
            self._paint_mesh(painter, w, h, elapsed)
        elif self._style == "Fluid":
            self._paint_fluid(painter, w, h, elapsed)
        elif self._style == "Snow":
            self._paint_snow(painter, w, h, elapsed)
        elif self._style == "Rain":
            self._paint_rain(painter, w, h, elapsed)
        elif self._style == "Fire":
            self._paint_fire(painter, w, h, elapsed)
        else:
            self._paint_sweep(painter, w, h, elapsed)

    def _paint_image(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), self._bg_color)  # letterbox color for Fit mode

        pixmap = self._image_pixmap
        w, h = self.width(), self.height()
        scale_x, scale_y, offset_x, offset_y = compute_image_placement(
            w, h, pixmap.width(), pixmap.height(), self._image_scaling, self._image_position
        )

        painter.save()
        painter.setOpacity(self._image_opacity)
        target_rect = QRectF(offset_x, offset_y, pixmap.width() * scale_x, pixmap.height() * scale_y)
        painter.drawPixmap(target_rect, pixmap, QRectF(pixmap.rect()))
        painter.restore()

        if self._overlay_opacity > 0:
            overlay = QColor(0, 0, 0)
            overlay.setAlphaF(self._overlay_opacity)
            painter.fillRect(self.rect(), overlay)

    def _paint_video(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), self._bg_color)
        image = self._current_video_image
        w, h = self.width(), self.height()
        scale_x, scale_y, offset_x, offset_y = compute_image_placement(
            w, h, image.width(), image.height(), "Fill", "Center"
        )
        painter.save()
        painter.setOpacity(self._video_opacity)
        target_rect = QRectF(offset_x, offset_y, image.width() * scale_x, image.height() * scale_y)
        painter.drawImage(target_rect, image, QRectF(image.rect()))
        painter.restore()

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

    def _paint_mesh(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """A 'mesh gradient' look: blobs at FIXED grid anchor points
        (unlike Aurora's drifting blobs) that gently pulse in size and
        opacity — a more structured, geometric feel than Aurora's
        organic drift."""
        painter.fillRect(self.rect(), self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # 5 anchor points: 4 corners-ish + center, normalized 0..1
        anchors = [
            (0.2, 0.25, 0.0), (0.8, 0.2, 1.3), (0.5, 0.5, 2.6),
            (0.2, 0.8, 3.9), (0.8, 0.8, 5.2),
        ]
        radius = math.hypot(w, h) * 0.28

        for ax, ay, phase in anchors:
            pulse = 0.5 + 0.5 * math.sin(elapsed * 0.5 + phase)
            cx, cy = ax * w, ay * h
            r = radius * (0.7 + 0.3 * pulse)

            gradient = QRadialGradient(QPointF(cx, cy), max(r, 1.0))
            core = QColor(self._accent_color)
            core.setAlpha(int(40 * (0.5 + 0.5 * pulse)))
            edge = QColor(self._accent_color)
            edge.setAlpha(0)
            gradient.setColorAt(0.0, core)
            gradient.setColorAt(1.0, edge)

            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), r, r)

    def _paint_fluid(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """Two large, slow-moving overlapping blobs on smooth circular
        paths — a liquid/lava-lamp feel, distinct from Aurora's several
        smaller, faster-drifting blobs."""
        painter.fillRect(self.rect(), self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        blob_radius = math.hypot(w, h) * 0.42
        blobs = [(0.0, 26.0), (math.pi, 34.0)]  # (phase offset, period in seconds)

        for phase, period in blobs:
            t = (elapsed / period) * 2 * math.pi + phase
            cx = w / 2 + math.cos(t) * w * 0.22
            cy = h / 2 + math.sin(t * 0.7) * h * 0.22

            gradient = QRadialGradient(QPointF(cx, cy), max(blob_radius, 1.0))
            core = QColor(self._accent_color)
            core.setAlpha(38)
            edge = QColor(self._accent_color)
            edge.setAlpha(0)
            gradient.setColorAt(0.0, core)
            gradient.setColorAt(1.0, edge)

            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), blob_radius, blob_radius)

    def _paint_snow(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """Small pale particles drifting slowly downward, looping from
        top to bottom, with a gentle horizontal sway."""
        painter.fillRect(self.rect(), self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(self._SNOW_COUNT):
            phase = (i / self._SNOW_COUNT)
            fall_speed = 18 + (i % 5) * 6  # px/sec, varied per-particle for a natural look
            y = (elapsed * fall_speed + phase * h) % h
            drift = math.sin(elapsed * 0.6 + i) * 12
            x = (phase * w + drift) % w
            size = 1.8 + (i % 4) * 0.7

            color = QColor(255, 255, 255)
            color.setAlphaF(0.55)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), size, size)

    def _paint_rain(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """Thin diagonal streaks falling fast, looping from top to
        bottom — same looping mechanism as snow, faster and drawn as
        short lines instead of dots."""
        painter.fillRect(self.rect(), self._bg_color)

        pen_color = QColor(self._accent_color).lighter(140)
        pen_color.setAlphaF(0.35)
        painter.setPen(pen_color)

        for i in range(self._RAIN_COUNT):
            phase = i / self._RAIN_COUNT
            fall_speed = 340 + (i % 7) * 30
            y = (elapsed * fall_speed + phase * h) % h
            x = (phase * w * 1.3) % w  # wider spread than h so streaks don't visibly repeat in lockstep
            length = 14 + (i % 3) * 4
            # a slight diagonal lean, consistent direction for all drops
            painter.drawLine(QPointF(x, y), QPointF(x - length * 0.25, y - length))

    def _paint_fire(self, painter: QPainter, w: int, h: int, elapsed: float) -> None:
        """Warm particles rising from the bottom edge, fading out as
        they climb — embers/flicker, confined to the lower portion of
        the widget rather than filling the whole background."""
        painter.fillRect(self.rect(), self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        fire_band_h = h * 0.6  # particles only rise through the bottom 60%

        for i in range(self._FIRE_COUNT):
            phase = i / self._FIRE_COUNT
            rise_speed = 40 + (i % 5) * 10
            risen = (elapsed * rise_speed + phase * fire_band_h) % fire_band_h
            y = h - risen
            sway = math.sin(elapsed * 1.4 + i * 1.7) * 8
            x = (phase * w + sway) % w
            size = 2.0 + (i % 3) * 1.2

            # hotter/brighter near the bottom, fading toward the top of its rise
            fade = max(0.0, min(1.0, risen / fire_band_h))
            alpha = 1.0 - fade
            color = QColor(255, int(140 - 60 * fade), int(30 * (1 - fade)))
            color.setAlphaF(max(0.0, alpha) * 0.8)

            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), size, size)


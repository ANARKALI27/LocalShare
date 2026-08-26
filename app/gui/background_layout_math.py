"""
Pure math for placing a background image within a widget, given a
scaling mode and position — no Qt dependency at all, deliberately, so
this can be tested thoroughly without a display. The Qt-specific
paintEvent code just calls compute_image_placement() and draws.
"""
from __future__ import annotations

SCALING_MODES = ["Fill", "Fit", "Stretch", "Original"]
POSITIONS = ["Center", "Top", "Bottom", "Left", "Right"]


def compute_image_placement(
    widget_w: float,
    widget_h: float,
    image_w: float,
    image_h: float,
    scaling: str,
    position: str,
) -> tuple[float, float, float, float]:
    """
    Returns (scale_x, scale_y, offset_x, offset_y) — how much to scale
    the image on each axis, and where to draw its top-left corner so
    it ends up placed correctly within the widget.

    - Fill: uniformly scaled to cover the entire widget, cropping
      whatever overflows (like CSS background-size: cover).
    - Fit: uniformly scaled to fit entirely within the widget,
      letterboxing (like CSS background-size: contain).
    - Stretch: scaled independently on each axis to exactly match the
      widget size, ignoring aspect ratio.
    - Original: not scaled at all (1:1), just positioned.

    `position` only matters when the scaled image doesn't exactly fill
    the widget (Fit's letterboxing, Original being smaller/larger, or
    which side gets cropped in Fill).
    """
    if widget_w <= 0 or widget_h <= 0 or image_w <= 0 or image_h <= 0:
        return (1.0, 1.0, 0.0, 0.0)  # degenerate input — caller should skip drawing

    if scaling == "Fill":
        scale = max(widget_w / image_w, widget_h / image_h)
        scale_x = scale_y = scale
    elif scaling == "Fit":
        scale = min(widget_w / image_w, widget_h / image_h)
        scale_x = scale_y = scale
    elif scaling == "Stretch":
        scale_x = widget_w / image_w
        scale_y = widget_h / image_h
    else:  # "Original"
        scale_x = scale_y = 1.0

    scaled_w = image_w * scale_x
    scaled_h = image_h * scale_y

    if position == "Left":
        offset_x = 0.0
    elif position == "Right":
        offset_x = widget_w - scaled_w
    else:  # Center, Top, Bottom all center horizontally
        offset_x = (widget_w - scaled_w) / 2

    if position == "Top":
        offset_y = 0.0
    elif position == "Bottom":
        offset_y = widget_h - scaled_h
    else:  # Center, Left, Right all center vertically
        offset_y = (widget_h - scaled_h) / 2

    return (scale_x, scale_y, offset_x, offset_y)

"""
Color themes for the desktop app. Two palettes (dark/light) plus a
single function that builds the full Qt stylesheet from whichever one
is active — so switching themes is just re-running this with the
other palette, not maintaining two separate stylesheet strings by hand.
"""
from __future__ import annotations

import json

from app.paths import CHECKMARK_ICON_PATH

# QSS url() wants forward slashes regardless of platform — Windows
# backslash paths aren't parsed correctly inside a stylesheet string.
_CHECKMARK_URL = CHECKMARK_ICON_PATH.replace("\\", "/")

DARK = {
    "bg": "#1E1F26",
    "surface": "#262832",
    "border": "#33353F",
    "text": "#E7E8EC",
    "text_dim": "#9296A1",
    "accent": "#4C8DFF",
    "accent_hover": "#5D98FF",
    "success": "#4CD787",
    "success_bg": "rgba(76, 216, 135, 0.12)",
    "success_border": "#2E7D53",
    "danger": "#FF6B6B",
    "hover_bg": "#383B47",
    "selected_bg": "#33405C",
}

LIGHT = {
    "bg": "#F5F6F8",
    "surface": "#FFFFFF",
    "border": "#DCDFE4",
    "text": "#20222A",
    "text_dim": "#6B6F76",
    "accent": "#2F6FE0",
    "accent_hover": "#255CC0",
    "success": "#1E9E5A",
    "success_bg": "rgba(30, 158, 90, 0.10)",
    "success_border": "#1E9E5A",
    "danger": "#D64545",
    "hover_bg": "#EDEFF3",
    "selected_bg": "#D9E4FA",
}

# Additional named theme presets. Each shares the same key structure
# as DARK/LIGHT above. success/danger stay close to a consistent
# green/red across the dark-family themes on purpose — that's a
# semantic color (success = good, danger = bad), and letting it drift
# per-theme would undermine recognizing it at a glance.
_DARK_SUCCESS = {"success": "#4CD787", "success_bg": "rgba(76, 216, 135, 0.12)", "success_border": "#2E7D53", "danger": "#FF6B6B"}

MIDNIGHT = {
    "bg": "#0D1117", "surface": "#161B22", "border": "#2A303C",
    "text": "#E6EDF3", "text_dim": "#8B96A5",
    "accent": "#58A6FF", "accent_hover": "#79B8FF",
    "hover_bg": "#1F2530", "selected_bg": "#1F3A5F",
    **_DARK_SUCCESS,
}

OCEAN = {
    "bg": "#071E22", "surface": "#0F2C31", "border": "#1C4249",
    "text": "#E3F6F5", "text_dim": "#8FB9BC",
    "accent": "#22D3EE", "accent_hover": "#4FE0F5",
    "hover_bg": "#153841", "selected_bg": "#134752",
    **_DARK_SUCCESS,
}

AURORA = {
    "bg": "#0F1420", "surface": "#171C2C", "border": "#2B3350",
    "text": "#E8EAF6", "text_dim": "#8E96B8",
    "accent": "#4ADE80", "accent_hover": "#6EE8A0",
    "hover_bg": "#1F263B", "selected_bg": "#1E3A2E",
    **_DARK_SUCCESS,
}

PURPLE_HAZE = {
    "bg": "#1A1225", "surface": "#241934", "border": "#3B2A52",
    "text": "#EEE6FA", "text_dim": "#A895C4",
    "accent": "#A855F7", "accent_hover": "#BB7BFA",
    "hover_bg": "#2E2143", "selected_bg": "#3A2856",
    **_DARK_SUCCESS,
}

CYBER = {
    "bg": "#0A0A0F", "surface": "#14141C", "border": "#2A2A38",
    "text": "#F0F0FA", "text_dim": "#9494AC",
    "accent": "#FF3EA5", "accent_hover": "#FF6BBB",
    "hover_bg": "#1E1E2A", "selected_bg": "#3A1E32",
    **_DARK_SUCCESS,
}

EMERALD = {
    "bg": "#0B1F17", "surface": "#12281F", "border": "#1F4234",
    "text": "#E4F5EC", "text_dim": "#8DBBA3",
    "accent": "#10B981", "accent_hover": "#34CB9C",
    "hover_bg": "#183A2C", "selected_bg": "#164A34",
    **_DARK_SUCCESS,
}

CRIMSON = {
    "bg": "#1F0D0D", "surface": "#2A1414", "border": "#4A2323",
    "text": "#F7E6E6", "text_dim": "#C29A9A",
    "accent": "#EF4444", "accent_hover": "#F26B6B",
    "hover_bg": "#3A1B1B", "selected_bg": "#4A1F1F",
    **_DARK_SUCCESS,
}

SLATE = {
    "bg": "#1E2228", "surface": "#262B33", "border": "#3A4048",
    "text": "#E7EAEE", "text_dim": "#94A0AC",
    "accent": "#60A5FA", "accent_hover": "#7FB8FB",
    "hover_bg": "#2E343D", "selected_bg": "#2C3E52",
    **_DARK_SUCCESS,
}

# Registry of every selectable theme, in the order they should appear
# in the picker. "Default Dark" and "Light" reuse the original DARK/
# LIGHT dicts directly — same object, not a copy — so anything that
# still imports DARK/LIGHT by name (drop_zone.py) keeps working
# unchanged.
THEMES: dict[str, dict] = {
    "Default Dark": DARK,
    "Midnight": MIDNIGHT,
    "Ocean": OCEAN,
    "Aurora": AURORA,
    "Purple Haze": PURPLE_HAZE,
    "Cyber": CYBER,
    "Emerald": EMERALD,
    "Crimson": CRIMSON,
    "Slate": SLATE,
    "Light": LIGHT,
}

# Accent color presets, offered alongside the custom color picker.
ACCENT_PRESETS: dict[str, str] = {
    "Blue": "#4C8DFF",
    "Indigo": "#6366F1",
    "Purple": "#A855F7",
    "Violet": "#8B5CF6",
    "Cyan": "#22D3EE",
    "Teal": "#14B8A6",
    "Green": "#22C55E",
    "Orange": "#F97316",
    "Pink": "#EC4899",
    "Red": "#EF4444",
}

# -- Custom theme builder: core colors, derived palette, JSON export/import -----

# The colors someone actually picks in the Custom Theme dialog — kept
# small and non-redundant. Everything else in the full 13-key palette
# (accent_hover, success_bg, hover_bg, etc.) is a computed variant of
# one of these, not something worth asking a person to hand-pick.
CORE_KEYS = ["bg", "surface", "border", "text", "text_dim", "accent", "success", "danger"]

# The full set of keys build_stylesheet() actually consumes — used to
# validate an imported theme file has everything required.
FULL_KEYS = [
    "bg", "surface", "border", "text", "text_dim", "accent", "accent_hover",
    "success", "success_bg", "success_border", "danger", "hover_bg", "selected_bg",
]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Not a valid hex color: {hex_color!r}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    clamped = [max(0, min(255, int(c))) for c in rgb]
    return "#{:02X}{:02X}{:02X}".format(*clamped)


def _lighten(hex_color: str, factor: float) -> str:
    """Blends toward white by `factor` (0..1)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor))


def _darken(hex_color: str, factor: float) -> str:
    """Blends toward black by `factor` (0..1)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r * (1 - factor), g * (1 - factor), b * (1 - factor)))


def _perceived_brightness(hex_color: str) -> float:
    """0 (black) to 1 (white) — standard perceived-brightness weighting."""
    r, g, b = _hex_to_rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _hex_to_rgba_string(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def derive_full_palette(core: dict) -> dict:
    """
    Expands a minimal CORE_KEYS palette (the colors someone actually
    picks in the Custom Theme dialog) into the full palette
    build_stylesheet() expects, computing sensible derived values
    (hover states, tinted backgrounds) rather than asking someone to
    hand-pick 13 near-duplicate colors.
    """
    is_dark = _perceived_brightness(core["bg"]) < 0.5

    accent_hover = _lighten(core["accent"], 0.18) if is_dark else _darken(core["accent"], 0.18)
    hover_bg = _lighten(core["surface"], 0.10) if is_dark else _darken(core["surface"], 0.06)

    return {
        "bg": core["bg"],
        "surface": core["surface"],
        "border": core["border"],
        "text": core["text"],
        "text_dim": core["text_dim"],
        "accent": core["accent"],
        "accent_hover": accent_hover,
        "success": core["success"],
        "success_bg": _hex_to_rgba_string(core["success"], 0.12),
        "success_border": core["success"],
        "danger": core["danger"],
        "hover_bg": hover_bg,
        "selected_bg": _hex_to_rgba_string(core["accent"], 0.18),
    }


def theme_to_json(name: str, colors: dict) -> str:
    """Serializes a theme to the small JSON format used for export/import."""
    payload = {
        "app": "LocalShare",
        "name": name,
        "colors": {k: colors[k] for k in FULL_KEYS if k in colors},
    }
    return json.dumps(payload, indent=2)


def theme_from_json(json_text: str) -> tuple[str, dict]:
    """
    Parses an exported theme JSON. Raises ValueError with a clear,
    specific message if the file isn't valid JSON, isn't a theme file,
    or is missing a required color — never raises a raw/confusing
    exception type up to the caller.
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "colors" not in data:
        raise ValueError("This doesn't look like a LocalShare theme file (missing 'colors').")

    colors = data["colors"]
    if not isinstance(colors, dict):
        raise ValueError("This theme file's 'colors' field is malformed.")

    missing = [k for k in FULL_KEYS if k not in colors]
    if missing:
        raise ValueError(f"Theme file is missing required color(s): {', '.join(missing)}")

    name = data.get("name") or "Imported Theme"
    return name, {k: colors[k] for k in FULL_KEYS}


CARD_RADIUS = {"Sharp": 0, "Small": 4, "Medium": 8, "Large": 14, "Extra Large": 20}
CARD_BORDER = {"None": (0, "transparent"), "Subtle": (1, "border"), "Visible": (2, "border")}
CARD_SHADOW_BLUR = {"None": 0, "Subtle": 10, "Medium": 20, "Strong": 34}


def build_stylesheet(c: dict, card_style: dict | None = None) -> str:
    """
    card_style (all optional, sensible defaults if omitted):
      - radius: one of CARD_RADIUS's keys (default "Medium")
      - border: one of CARD_BORDER's keys (default "Subtle")
      - surface_alpha: 0.0 (fully transparent) .. 1.0 (fully opaque), default 1.0

    Note on "surface transparency": this makes cards/panels genuinely
    see-through over whatever background is behind the window (solid,
    gradient, image, or video) — it does NOT blur that background,
    since Qt Widgets has no equivalent to CSS backdrop-filter. Real
    glassmorphism (blurring what's behind a translucent panel) would
    need custom compositing this project doesn't implement.
    """
    style = card_style or {}
    radius = CARD_RADIUS.get(style.get("radius", "Medium"), 8)
    border_width, border_key = CARD_BORDER.get(style.get("border", "Subtle"), (1, "border"))
    border_color = c[border_key] if border_key != "transparent" else "transparent"
    surface_alpha = style.get("surface_alpha", 1.0)
    surface_color = c["surface"] if surface_alpha >= 0.999 else _hex_to_rgba_string(c["surface"], surface_alpha)
    bg_color = c["bg"] if surface_alpha >= 0.999 else _hex_to_rgba_string(c["bg"], surface_alpha)

    return f"""
QMainWindow {{
    background-color: {c['bg']};
}}
QDialog {{
    background-color: {bg_color};
}}
QWidget {{
    color: {c['text']};
    font-family: "Segoe UI", sans-serif;
}}
QLabel, QCheckBox, QRadioButton {{
    background: transparent;
}}
QLabel#Title {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel#SectionLabel {{
    font-size: 12px;
    color: {c['text_dim']};
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QListWidget {{
    background-color: {surface_color};
    border: {border_width}px solid {border_color};
    border-radius: {radius}px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: {max(radius - 2, 0)}px;
}}
QListWidget::item:selected {{
    background-color: {c['selected_bg']};
    outline: none;
    border: none;
}}
QListWidget::item:focus {{
    outline: none;
    border: none;
}}
QListWidget:focus {{
    outline: none;
}}
QLineEdit {{
    background-color: {surface_color};
    border: {border_width}px solid {border_color};
    border-radius: {max(radius - 2, 0)}px;
    padding: 6px 10px;
    color: {c['text']};
}}
QLineEdit:focus {{
    border-color: {c['accent']};
}}
QLineEdit:disabled {{
    color: {c['text_dim']};
    background-color: {bg_color};
}}
QComboBox {{
    background-color: {surface_color};
    border: {border_width}px solid {border_color};
    border-radius: {max(radius - 2, 0)}px;
    padding: 6px 10px;
    color: {c['text']};
}}
QComboBox:hover {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    background: transparent;
    width: 22px;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['selected_bg']};
    outline: none;
}}
QPushButton {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 8px 14px;
    color: {c['text']};
}}
QPushButton:hover {{
    background-color: {c['hover_bg']};
}}
QPushButton#PrimaryButton {{
    background-color: {c['accent']};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {c['accent_hover']};
}}
QLabel#StatusDot {{
    font-size: 14px;
}}
QRadioButton, QCheckBox {{
    spacing: 8px;
    color: {c['text']};
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {c['border']};
    background-color: {c['surface']};
    border-radius: 4px;
}}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    border-color: {c['accent']};
    background-color: {c['accent']};
    image: url({_CHECKMARK_URL});
}}
QRadioButton:checked, QCheckBox:checked {{
    color: {c['accent']};
    font-weight: 600;
}}
QScrollArea {{
    border: none;
    background-color: {c['bg']};
}}
QScrollArea > QWidget > QWidget {{
    background-color: {c['bg']};
}}
QScrollBar:vertical {{
    background: {_hex_to_rgba_string(c['surface'], 0.35)};
    width: 12px;
    margin: 2px 2px 2px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {_hex_to_rgba_string(c['border'], 0.9)};
    border-radius: 5px;
    margin: 1px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['accent']};
}}
QScrollBar::handle:vertical:pressed {{
    background: {c['accent_hover']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    border: none;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: {_hex_to_rgba_string(c['surface'], 0.35)};
    height: 12px;
    margin: 0 2px 2px 2px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {_hex_to_rgba_string(c['border'], 0.9)};
    border-radius: 5px;
    margin: 1px;
    min-width: 36px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['accent']};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {c['accent_hover']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    border: none;
    background: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""

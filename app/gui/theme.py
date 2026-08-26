"""
Color themes for the desktop app. Two palettes (dark/light) plus a
single function that builds the full Qt stylesheet from whichever one
is active — so switching themes is just re-running this with the
other palette, not maintaining two separate stylesheet strings by hand.
"""
from __future__ import annotations

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
# still imports DARK/LIGHT by name (drop_zone.py, splash_screen.py)
# keeps working unchanged.
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


def build_stylesheet(c: dict) -> str:
    return f"""
QMainWindow {{
    background-color: {c['bg']};
}}
QDialog {{
    background-color: {c['bg']};
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
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background-color: {c['selected_bg']};
}}
QLineEdit {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {c['text']};
}}
QLineEdit:focus {{
    border-color: {c['accent']};
}}
QLineEdit:disabled {{
    color: {c['text_dim']};
    background-color: {c['bg']};
}}
QComboBox {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {c['text']};
}}
QComboBox:hover {{
    border-color: {c['accent']};
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
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['accent']};
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
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['accent']};
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

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

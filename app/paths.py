"""
Resolves the app's own resource paths (currently just the web/ folder)
in a way that works both when running normally (`python main.py`) and
when frozen into a single-file executable by PyInstaller.

PyInstaller's onefile mode extracts bundled data into a temporary
directory at runtime and exposes its path via sys._MEIPASS — code that
computes paths relative to __file__ the normal way breaks under this,
because __file__ points inside that temp extraction, not the original
source tree. This module is the one place that distinction is handled,
so nothing else needs to know or care whether it's running frozen.
"""
from __future__ import annotations

import os
import sys


def app_root() -> str:
    """
    The application's root directory: the PyInstaller extraction dir
    when frozen, otherwise the project root (the folder containing
    main.py, one level up from this app/ package).
    """
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS in onefile mode; onedir mode
        # doesn't set it, but the executable's own directory works
        # there since data files sit alongside it.
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # This file lives at <project_root>/app/paths.py
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


WEB_DIR = os.path.join(app_root(), "web")
ICON_PATH = os.path.join(app_root(), "assets", "localshare.png")
CHECKMARK_ICON_PATH = os.path.join(app_root(), "assets", "checkmark.png")
DONATE_QR_PATH = os.path.join(app_root(), "assets", "donate_qr.jpg")

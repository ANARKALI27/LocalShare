"""
LocalShare — LAN file sharing app.

Run with: python main.py
"""
import os
import sys

# In a windowed/no-console PyInstaller build, sys.stdout and
# sys.stderr are None (there's no console to write to). Any library
# that tries to write progress/log output to them — this bit us with
# uvicorn's default logging, and again with pyngrok downloading the
# ngrok binary ("'NoneType' object has no attribute 'write'") — will
# crash. Redirecting to a no-op sink here, before anything else
# imports, fixes this class of bug generally rather than patching each
# library that happens to hit it one at a time.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.splash_screen import SplashScreen
from app.paths import ICON_PATH


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LocalShare")
    # Sets the taskbar/dock/title-bar icon while the app is running.
    # This is separate from the .desktop file's Icon= entry (which only
    # covers the application-menu launcher on Linux) — without this
    # call, Qt has nothing to show at runtime and falls back to a
    # generic default that can look like an unrelated system icon.
    app.setWindowIcon(QIcon(ICON_PATH))

    window = MainWindow()

    splash = SplashScreen()

    def show_main_window() -> None:
        window.show()

    splash.finished.connect(show_main_window)
    splash.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""
LocalShare — LAN file sharing app.

Run with: python main.py
"""
import sys

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

"""
LocalShare — LAN file sharing app.

Run with: python main.py
"""
import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.splash_screen import SplashScreen


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LocalShare")

    window = MainWindow()

    splash = SplashScreen()

    def show_main_window() -> None:
        window.show()

    splash.finished.connect(show_main_window)
    splash.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

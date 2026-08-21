"""
LocalShare — LAN file sharing app.

Run with: python main.py
"""
import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LocalShare")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

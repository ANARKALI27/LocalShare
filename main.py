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

# Qt Multimedia's FFmpeg backend logs fairly verbosely by default
# (codec/format details for every media file it opens — this is
# what's behind the video background feature). That logging comes
# from native Qt/FFmpeg code, not Python, so it writes directly to the
# OS-level stderr handle rather than through sys.stderr above — the
# redirect just above this doesn't reach it at all. A windowed app
# normally has no console/stderr handle attached to the process at
# all, and on Windows, native code trying to write to that nonexistent
# handle has been observed to cause Windows to allocate a visible
# console window purely to give the output somewhere to go — which is
# exactly the unwanted terminal window that shows up once a video
# background is in use. Must be set before any PySide6/Qt module is
# imported, since Qt reads this at library-load time, not later.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg.*=false")

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

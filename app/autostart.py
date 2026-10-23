"""
Registers (or unregisters) LocalShare to launch automatically when the
user logs into their computer — a genuinely different thing from the
existing "auto_start_on_launch"/"auto_start_on_add" settings, which
control auto-starting SHARING once the app is already open, not
launching the app itself at OS startup.

Uses each platform's own standard, well-established mechanism rather
than anything exotic:
  - Windows: a per-user Registry Run key (HKEY_CURRENT_USER), which
    needs no admin rights and is the standard way apps do this —
    NOT the Startup folder (also common, but the registry key is
    simpler to manage programmatically: one value, cleanly removable,
    no shortcut file to construct).
  - Linux: an XDG autostart .desktop file in ~/.config/autostart/,
    the standard freedesktop.org mechanism respected by GNOME, KDE,
    XFCE, and most other desktop environments.

Both directions (enable/disable) are idempotent — calling enable()
when already enabled, or disable() when already disabled, is a no-op,
not an error.
"""
from __future__ import annotations

import os
import sys

_APP_NAME = "LocalShare"


def _get_launch_command() -> str:
    """
    The command the OS should run at login. For a PyInstaller-frozen
    build, sys.executable IS the actual LocalShare.exe/binary — no
    arguments needed. Running from source (sys.frozen unset), it's
    the Python interpreter plus this project's main.py path, quoted
    to survive spaces in either path.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{sys.executable}" "{main_script}"'


# -- Windows: HKEY_CURRENT_USER Run key -----------------------------------------------------------

def _windows_enable() -> None:
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _get_launch_command())
    finally:
        winreg.CloseKey(key)


def _windows_disable() -> None:
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
    except OSError:
        return  # the Run key itself doesn't exist — nothing to remove
    try:
        try:
            winreg.DeleteValue(key, _APP_NAME)
        except FileNotFoundError:
            pass  # already not registered — disabling is a no-op, not an error
    finally:
        winreg.CloseKey(key)


def _windows_is_enabled() -> bool:
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
    except OSError:
        return False
    try:
        winreg.QueryValueEx(key, _APP_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


# -- Linux: XDG autostart .desktop file -----------------------------------------------------------

def _linux_autostart_dir() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_home, "autostart")


def _linux_desktop_file_path() -> str:
    return os.path.join(_linux_autostart_dir(), "localshare.desktop")


def _linux_enable() -> None:
    autostart_dir = _linux_autostart_dir()
    os.makedirs(autostart_dir, exist_ok=True)
    contents = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_APP_NAME}\n"
        f"Exec={_get_launch_command()}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
    )
    with open(_linux_desktop_file_path(), "w") as f:
        f.write(contents)


def _linux_disable() -> None:
    try:
        os.remove(_linux_desktop_file_path())
    except FileNotFoundError:
        pass  # already not registered — disabling is a no-op, not an error


def _linux_is_enabled() -> bool:
    return os.path.isfile(_linux_desktop_file_path())


# -- public, platform-dispatching API -----------------------------------------------------------

def is_supported() -> bool:
    return sys.platform in ("win32", "linux")


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _windows_is_enabled()
    if sys.platform == "linux":
        return _linux_is_enabled()
    return False


def enable() -> None:
    if sys.platform == "win32":
        _windows_enable()
    elif sys.platform == "linux":
        _linux_enable()


def disable() -> None:
    if sys.platform == "win32":
        _windows_disable()
    elif sys.platform == "linux":
        _linux_disable()

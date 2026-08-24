#!/bin/bash
# Builds a standalone LocalShare Linux binary from source. Run this
# from inside the localshare project folder (where main.py lives).
set -e

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "python3 not found. Install it via your distro's package manager, then try again."
    exit 1
fi

# Using "python3 -m pip" instead of a bare "pip3" command — the latter
# isn't guaranteed to exist as a separate executable on every distro
# (e.g. Arch-based systems often only expose pip through the module
# invocation, not a standalone pip3 binary on PATH).
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "pip isn't available for $PY. Install it first, e.g.:"
    echo "  Debian/Ubuntu:  sudo apt install python3-pip"
    echo "  Arch/Manjaro:   sudo pacman -S python-pip"
    echo "  Fedora:         sudo dnf install python3-pip"
    exit 1
fi

echo "Installing/updating dependencies..."
"$PY" -m pip install -r requirements.txt
"$PY" -m pip install pyinstaller

echo
echo "Building LocalShare (this can take a few minutes)..."
"$PY" -m PyInstaller --noconfirm localshare.spec

echo
if [ -f "dist/LocalShare" ]; then
    echo "Build succeeded: dist/LocalShare"
else
    echo "Build finished but dist/LocalShare was not found -- check the output above for errors."
fi

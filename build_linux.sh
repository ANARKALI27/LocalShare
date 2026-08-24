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

install_with_pip() {
    # Try a normal install first. Only fall back to
    # --break-system-packages if pip specifically blocks it with the
    # PEP 668 "externally-managed-environment" error (modern Debian
    # 12+/Bookworm and some other distros) — forcing that flag
    # unconditionally would break older pip versions (pre-23.0, e.g.
    # Debian 11/Bullseye) that don't recognize it at all.
    local err_log
    err_log=$(mktemp)
    if "$PY" -m pip install "$@" 2>"$err_log"; then
        rm -f "$err_log"
        return 0
    fi
    if grep -qi "externally-managed-environment" "$err_log"; then
        echo "System Python is externally managed (PEP 668) -- retrying with --break-system-packages..."
        rm -f "$err_log"
        "$PY" -m pip install --break-system-packages "$@"
        return $?
    fi
    cat "$err_log"
    rm -f "$err_log"
    return 1
}

echo "Installing/updating dependencies..."
install_with_pip -r requirements.txt
install_with_pip pyinstaller

echo
echo "Building LocalShare (this can take a few minutes)..."
"$PY" -m PyInstaller --noconfirm localshare.spec

echo
if [ -f "dist/LocalShare" ]; then
    echo "Build succeeded: dist/LocalShare"
else
    echo "Build finished but dist/LocalShare was not found -- check the output above for errors."
fi

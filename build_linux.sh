#!/bin/bash
# Builds a standalone LocalShare Linux binary from source. Run this
# from inside the localshare project folder (where main.py lives).
set -e

echo "Installing/updating dependencies..."
pip3 install -r requirements.txt
pip3 install pyinstaller

echo
echo "Building LocalShare (this can take a few minutes)..."
python3 -m PyInstaller --noconfirm localshare.spec

echo
if [ -f "dist/LocalShare" ]; then
    echo "Build succeeded: dist/LocalShare"
else
    echo "Build finished but dist/LocalShare was not found -- check the output above for errors."
fi

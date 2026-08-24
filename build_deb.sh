#!/bin/bash
# Builds LocalShare and packages it into a single .deb installer for
# Debian/Ubuntu (and derivatives). Run from inside the project folder.
#
# Needs: dpkg-deb (part of the base "dpkg" package — already present
# on essentially any Debian-based system, no separate install needed).
set -e

echo "Step 1: Building LocalShare..."
bash build_linux.sh

if [ ! -f "dist/LocalShare" ]; then
    echo
    echo "dist/LocalShare was not found -- the build must succeed before creating a .deb."
    exit 1
fi

echo
echo "Step 2: Assembling the .deb package..."

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo
    echo "dpkg-deb not found. It's part of the base 'dpkg' package on Debian/Ubuntu"
    echo "(already present there by default). On other distros it may need installing:"
    echo "  Arch/Manjaro: sudo pacman -S dpkg"
    echo "  Fedora:       sudo dnf install dpkg"
    echo "If it's not packaged for your distro, build this step on an actual"
    echo "Debian/Ubuntu machine, VM, or container instead."
    exit 1
fi

# Pull the version straight from app/version.py so the two files can't
# drift out of sync the way the Windows installer's version has to be
# kept in sync by hand.
APP_VERSION=$(python3 -c "from app.version import APP_VERSION; print(APP_VERSION)")
sed -i "s/^Version:.*/Version: ${APP_VERSION}/" packaging/debian/DEBIAN/control

mkdir -p packaging/debian/usr/lib/localshare
cp dist/LocalShare packaging/debian/usr/lib/localshare/LocalShare
chmod 755 packaging/debian/usr/lib/localshare/LocalShare

mkdir -p packaging/debian/usr/bin
ln -sf /usr/lib/localshare/LocalShare packaging/debian/usr/bin/localshare

mkdir -p Output
DEB_NAME="localshare_${APP_VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group packaging/debian "Output/${DEB_NAME}"

echo
if [ -f "Output/${DEB_NAME}" ]; then
    echo "Package created: Output/${DEB_NAME}"
    echo "This is the ONLY file you need to share with Debian/Ubuntu users."
    echo "They install it with: sudo apt install ./Output/${DEB_NAME}"
else
    echo "Package build finished but Output/${DEB_NAME} was not found -- check the output above for errors."
fi

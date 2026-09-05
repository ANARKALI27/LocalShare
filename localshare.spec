# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for LocalShare. Shared by both build.bat (Windows)
# and build_deb.sh/build_linux.sh (Linux) — same source, same spec.
#
# Build with:  pyinstaller localshare.spec
# (see build.bat / build_linux.sh for the one-command versions)
#
# Web frameworks like uvicorn and wsgidav load some of their pieces
# dynamically (by string name, based on config) rather than with a
# plain top-level `import`, which is exactly what PyInstaller's static
# analysis can miss. The hiddenimports list below covers the ones
# known to commonly cause "ModuleNotFoundError" at runtime for this
# stack even though the app runs fine with a normal `python main.py`.
# If you hit a missing-module error anyway, note the exact module name
# from the error and add it here — that's a normal part of packaging
# a project like this, not a sign something is fundamentally broken.

import sys

hiddenimports = [
    # uvicorn picks its event loop / protocol implementation dynamically
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # wsgidav resolves its domain controller / provider / middleware
    # stack from config values (strings), not static imports
    "wsgidav.dc.simple_dc",
    "wsgidav.fs_dav_provider",
    "wsgidav.mw.debug_filter",
    "wsgidav.mw.error_printer",
    "wsgidav.mw.cors",
    "wsgidav.property_manager",
    "wsgidav.lock_manager",
    "wsgidav.default_conf",
    "cheroot.wsgi",
    "cheroot.ssl",
    # python-multipart's import name differs from its package name
    "multipart",
]

datas = [
    ("web", "web"),  # the browser UI (HTML/CSS/JS) — served as static files at runtime
    ("assets", "assets"),  # app icon (runtime taskbar/title-bar icon, loaded via app/paths.py)
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LocalShare",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression of the bundled Python DLL is a well-documented,
    # somewhat unpredictable cause of "Failed to import encodings
    # module" and similar interpreter-startup failures on Windows —
    # it works fine most of the time, then fails on certain Windows
    # versions/AV combinations in ways that are hard to reproduce or
    # diagnose after the fact. The app already bundles a full Python
    # runtime plus PySide6/FastAPI/uvicorn, so it's not a small
    # executable regardless — not worth trading genuine startup
    # reliability for UPX's marginal size savings on top of that.
    upx=False,
    upx_exclude=[],
    console=False,  # windowed app — no console window behind the GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/localshare.ico" if sys.platform.startswith("win") else None,
    # ^ Windows exe file icon only — icon= is a Windows/macOS-only
    # concept (embedded PE/Mach-O resource); explicitly gating it here
    # rather than relying on PyInstaller to silently no-op it on Linux,
    # since that behavior isn't something to bet an already-working
    # Linux build on without being able to verify it directly.
)

# COLLECT (onedir mode: a folder containing LocalShare.exe plus its
# dependencies alongside it) rather than a single self-extracting
# onefile executable. This is a deliberate reliability trade-off, not
# a default: onefile self-extracts its entire bundle to a fresh temp
# directory on every single launch, which is a well-documented source
# of exactly the "Failed to start embedded python interpreter" class
# of error — antivirus interference with the extraction, permissions
# issues on the temp directory, disk space, or a launch racing an
# antivirus scan of the just-extracted files. A plain folder sidesteps
# all of that: the files are just... there, unpacked once at install
# time, nothing to extract on every run. The trade-off is a slightly
# less tidy install (a folder instead of one file) and a very slightly
# slower first paint (loading DLLs individually vs. from one archive),
# both minor compared to "the app sometimes refuses to start at all."
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LocalShare",
)

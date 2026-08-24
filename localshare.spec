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
    a.binaries,
    a.datas,
    [],
    name="LocalShare",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
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

# LocalShare

A LAN file-sharing app: drag files/folders in, share an address, anyone
on the same network opens it in a browser to download, upload, and chat.

## Running from source

```
pip install -r requirements.txt
python main.py
```

## Building LocalShare.exe (Windows)

From inside this project folder:

```
build.bat
```

This installs dependencies (including PyInstaller), then builds
`dist\LocalShare.exe`. The build can take a few minutes.

**If the .exe fails to start with a `ModuleNotFoundError`:** this is a
known characteristic of packaging apps built on uvicorn/wsgidav — they
load some pieces dynamically based on config, which can slip past
PyInstaller's static import analysis. `localshare.spec` already lists
the imports known to commonly cause this for this stack, but if you
hit one anyway:

1. Note the exact module name from the error.
2. Add it to the `hiddenimports` list near the top of `localshare.spec`.
3. Rebuild with `pyinstaller --noconfirm localshare.spec`.

## Building a single-file installer (recommended for sharing)

`LocalShare.exe` alone is already standalone, but sharing an installer
instead means whoever you send it to doesn't need to know where to put
it or how to make a shortcut — they double-click, click Next a few
times, and it's installed with a Start Menu entry and (optionally) a
desktop icon.

One-time setup: install **Inno Setup** (free) from
https://jrsoftware.org/isinfo.php.

Then, from inside this project folder:

```
build_installer.bat
```

This builds `LocalShare.exe` (same as `build.bat`) and packages it
into `Output\LocalShareSetup.exe` — **that single file is the only
thing you need to share.** No folder, no `build.bat`, no hunting for
the `.exe` afterward.

The installer installs per-user (no admin rights needed to install or
run normally). WebDAV specifically still needs the installed app
launched via right-click → "Run as administrator" — that's a runtime
choice each time you want WebDAV, unrelated to how it was installed.

**Before building a new installer to share an update:** bump both
`APP_VERSION` in `app/version.py` *and* `MyAppVersion` in
`localshare_setup.iss` — they're separate values (one Python, one
Inno Setup) and don't sync automatically.

**If the .exe shows a blank/black window or "no Qt platform plugin"
error:** rebuild with `pyinstaller --noconfirm --collect-all PySide6 localshare.spec`
— this forces PyInstaller to bundle Qt's platform plugins, which are
occasionally missed by its default PySide6 hook.

## WebDAV / "Map Network Drive" (optional, experimental)

Requires running as Administrator (Windows only allows this feature to
bind port 80, and Explorer's WebDAV client is unreliable on any other
port — see the in-app tooltip for details). This is best-effort: the
browser share is the reliable path for anything large or important.

## Updating a friend's copy

There's no central update server for this project, so "Check for
Updates" works by asking *another running LocalShare instance* what
version it's on — typically whoever's PC has the newest build. Enter
that instance's address (shown in its own app window) and click Check.

If a newer version is found, it tells you but doesn't auto-download —
open that address in a browser and grab the new `LocalShareSetup.exe`
(or `LocalShare.exe`) from the shared files, then run/replace
accordingly. This is deliberate: automatically downloading and
swapping out a running `.exe` on Windows needs careful handling around
file locks that isn't safe to ship without testing on a real machine.

Before rebuilding a new version to share, bump `APP_VERSION` in
`app/version.py` (and `MyAppVersion` in `localshare_setup.iss` if
you're building an installer — see above).

## Accessing from a phone / other device

The browser share (files + messages) works from any device's browser
on the same network — Android, iPhone, another PC, doesn't matter.
There's no separate mobile app; open the address shown in LocalShare
from the phone's browser.

## Project structure

```
localshare/
├── main.py                  entry point
├── app/
│   ├── paths.py              resource path resolution (dev + frozen .exe)
│   ├── state.py               shared-items data model
│   ├── gui/                    PySide6 desktop UI
│   ├── server/                  HTTP server, WebDAV server, routes, security, messages
│   ├── transfer/                 streaming download/upload/resumable-upload logic
│   ├── network/                   LAN IP detection, port finding
│   └── utils/                      filesystem helpers
├── web/                        browser UI (file browser + messages)
├── localshare.spec           PyInstaller build config
└── build.bat                 one-command Windows build
```

## Security notes

- Only explicitly shared files/folders are accessible — path traversal
  is blocked (see `app/server/security.py`).
- **There is currently no access control on the browser share or
  messaging** — anyone who can reach the address on your LAN can
  browse, download, upload, and read/send messages. Earlier notes in
  this project referred to a PIN-protection option as the contrast to
  WebDAV's lack of one, but that PIN feature was never actually built.
  If you need access control, that's a real gap to close before
  relying on this for anything sensitive — ask to have it added.
- WebDAV has no access control at all and never will by design (see
  `app/server/webdav_server.py` for why) — anonymous-only.
- None of this is safe to expose to the internet — LAN use only.

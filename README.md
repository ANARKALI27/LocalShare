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

## Building a .deb package (Debian/Ubuntu)

From inside this project folder, on a Debian-based Linux system:

```
bash build_deb.sh
```

This builds a standalone Linux binary (same PyInstaller approach as
the Windows `.exe`) and packages it into `Output/localshare_<version>_amd64.deb`
— **that single file is the only thing you need to share** with a
Debian/Ubuntu user. They install it with:

```
sudo apt install ./localshare_<version>_amd64.deb
```

This installs `localshare` to their applications menu and adds a
`localshare` command to their terminal. No separate Python or pip
install needed on their end — it's self-contained, same as the exe.

Unlike the Windows installer, the version number here syncs
automatically from `app/version.py` — no separate file to remember to bump.

**Testing honesty note:** I validated the actual packaging pipeline
end-to-end (built a real `.deb`, inspected its contents with
`dpkg-deb --contents`/`--info` to confirm permissions, the symlink,
and metadata are all correct) using a placeholder binary, since I
can't install PySide6 in the environment that wrote this code. I
have *not* been able to `dpkg -i` this on a real Debian/Ubuntu desktop
and confirm the app actually launches and its shared library
dependencies (Qt/X11/Wayland) are satisfied — that's the one thing
only real testing on your end can confirm. If installing reports
missing shared libraries, that's a normal, fixable thing — tell me
the exact library name from the error and I'll add it as a `Depends:`
in `packaging/debian/DEBIAN/control`.

Also worth knowing: on Linux, WebDAV does **not** force port 80 the
way it does on Windows (that restriction is specific to Windows
Explorer's client) — it picks a normal port automatically, no `sudo`
needed. This is based on documentation of Linux's native WebDAV
clients (GVFS/Nautilus, Dolphin), not direct testing.

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

## Internet Sharing (v2)

By default, LocalShare only works on your local network ("Local
Network Only" mode) — that's still the right choice for most sharing
between people on the same Wi-Fi. "Global" mode exists for when the
other person genuinely isn't on your network.

**How it works:** [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
(`cloudflared`) opens an outbound connection from your machine to
Cloudflare's edge network and hands back a public HTTPS address that
forwards to your local server. No port forwarding or router
configuration needed, and no account or signup either.

**Setup:** none needed. The first time you use "Global" mode,
LocalShare automatically downloads `cloudflared` (Cloudflare's tunnel
program, ~40MB) into its own data directory if it isn't already
installed — no separate installer step, no PATH configuration. That
first connection takes a little longer while it downloads; every
connection after that is instant. If you already have `cloudflared`
installed system-wide (e.g. via `winget install --id
Cloudflare.cloudflared`), LocalShare uses that instead of downloading
its own copy.

Then in LocalShare: select "Global" mode, click Start Sharing. PIN
protection turns on automatically and can't be turned off in this
mode — see Security notes above for why. The public address appears
once the tunnel connects.

**Known limitations, straight from Cloudflare's own docs — not bugs:**
- Quick Tunnels are explicitly labeled "for testing and development,
  not production," and capped at 200 concurrent in-flight requests
- The public address is temporary — a new one generates every time
  you start sharing, and it stops working the moment you stop

**Testing honesty note:** the automatic download is genuinely verified
— downloaded the real `cloudflared` binary from GitHub's releases in
the environment that wrote this integration, confirmed it's complete
and runs correctly. What could NOT be tested end-to-end: actually
establishing a live tunnel to Cloudflare's edge network, since that
needs reaching endpoints outside that environment's network access.
The URL-parsing and subprocess-handling logic was verified against
cloudflared's documented output format and with mocked subprocess
behavior, not a live connection.

## Accessing from a phone / other device

The browser share (files + messages) works from any device's browser
on the same network — Android, iPhone, another PC, doesn't matter.
There's no separate mobile app; open the address shown in LocalShare
from the phone's browser.

## Nearby Devices

Click "Nearby Devices" to see other LocalShare installations on your
local network and open one directly in your browser — no need to ask
someone for their address. Works via LAN broadcast (UDP, port 53317),
with no central server involved; discovery only sees devices on the
same local network, not the internet.

Every installation has a persistent device code (e.g. `LS-7K4P-92MX`),
visible and editable (along with the device's display name) in
Settings → Device. The code is generated once via a cryptographically
secure random source, stays the same across restarts and network
changes, and never encodes anything about your hardware, IP address,
or identity — it's pure random data. Discovery can be turned off
entirely from that same Settings page.

A device only appears here while it's actively sharing something
(Start Sharing) — there's otherwise nothing to open at its address.

### Connecting by Device ID over the internet

The "Connect by Device ID" field tries your local network first, and —
if you've set up Global Connect — falls back to finding the device
anywhere on the internet using just its Device ID, no address or QR
code needed from the other person. This needs a one-time, free setup
on your own account (not something LocalShare can do for you): see
[GLOBAL_CONNECT_SETUP.md](GLOBAL_CONNECT_SETUP.md) for the exact
steps, then paste the resulting database URL into Settings → Device →
Connect Globally. Actual file transfer is unchanged — it's the same
Cloudflare tunnel and PIN protection Global sharing already uses; this
only replaces "share your address" with "share your Device ID."

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
- **PIN protection is available and off by default.** Turn on
  "Require PIN to access" before Start Sharing to require a 6-digit
  (or custom) PIN for the browser share and messaging — see
  `app/server/auth.py`. Without it, anyone who can reach the address
  on your network can browse, download, upload, and read/send messages.
- **PIN protection is mandatory, not optional, in "Local Network +
  Internet" mode** — the app forces it on and won't let you turn it
  off while that mode is selected, since the share is then reachable
  by anyone who finds the URL, not just people on your network.
- WebDAV has no access control at all and never will by design (see
  `app/server/webdav_server.py` for why) — anonymous-only, regardless
  of your PIN setting elsewhere. Don't rely on WebDAV for anything
  you wouldn't want fully public on your LAN.
- "Local Network Only" mode (the default) is LAN-only, same as
  always. "Global" mode uses Cloudflare Quick Tunnel — see the
  Internet Sharing section below.

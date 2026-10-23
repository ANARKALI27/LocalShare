# Changelog

Git tags mark the exact commit boundary for each version — `v1.0.0`,
`v2.0.0`, and `v3.0.0` can be checked out directly to get that
version's code with nothing from later versions mixed in:
```
git checkout v1.0.0   # pure v1
git checkout v2.0.0   # pure v2
git checkout v3.0.0   # current
```

---

## Security patch

**PIN brute-force protection.** A 6-digit PIN has only a million combinations, and the login form had no limit on guesses. Now 5 wrong PINs lock that client out for 5 minutes (doubling each repeat, up to 1 hour); 40 wrong PINs across the whole share pause all PIN attempts for 5 minutes (stops attackers who rotate addresses). While locked, even the correct PIN is refused. Works correctly behind the Cloudflare tunnel (uses `CF-Connecting-IP` only for loopback connections). The lock resets when sharing is re-enabled. PIN and token comparison now work on UTF-8 bytes, so a non-ASCII PIN can no longer raise an error.

**Login page.** The `next` redirect target is now validated as a same-site path (no more open redirect to `//evil.com`), URL-encoded, and fully HTML-escaped in the form. The auth cookie gets the `Secure` flag when the request came over HTTPS (Global/tunnel mode).

**Stored XSS fixes.** A file name like `<img src=x onerror=...>` was inserted into the preview panel via `innerHTML` (web/app.js) — now built with text nodes. Uploaded `.html`/`.svg`/`.xml`/`.js` files opened inline are served with a sandboxing `Content-Security-Policy`, so they can render but can't run script on the share's origin. `Content-Disposition` is now built safely (RFC 5987), so quotes/semicolons/line breaks in file names can't break the header.

**Cross-site request protection + security headers.** State-changing requests (upload, messages, cancel) carrying a foreign `Origin` (or `Sec-Fetch-Site: cross-site`) are rejected, so a random web page can't silently post to a LocalShare on your LAN. All responses now send `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (keeps `?token=` links from leaking) and a restrictive `Permissions-Policy`.

**Upload hardening.** Windows device names (`CON`, `NUL`, `COM1`, `aux.tar.gz`, …) are renamed; control characters stripped; names capped at 200 chars. Resumable uploads: chunks are capped at 32 MB (read in a stream, not buffered unbounded), at most 64 sessions at once, idle sessions expire after 24 h, and an upload larger than the free disk space is refused up front. Bad paths now return a clean 403 instead of a 500 (including at upload start instead of after the whole file arrived). Malformed `relative_paths` JSON can't crash the endpoint. Messages: max 10 attachments each, 5000 per session.

**Information leaks closed.** Folder ZIP downloads no longer follow a symlink inside a shared folder to a file outside it (e.g. a link to `~/.ssh/id_rsa`). `/api/received` no longer exposes the host's full on-disk paths to browsers.

**Update installers.** The LAN-peer update flow downloaded and launched whatever another device named; it now accepts only a plain `*.exe`/`*.deb` file name and the peer's own `/download?...` path (no `../`, no full URLs, no `user@host` tricks), and the confirmation says which device it comes from and to continue only if you trust it. GitHub update info: the release link is opened only if it is on `https://github.com/`, and asset links are filtered the same way.

**Not changed (by design, documented):** WebDAV is still anonymous and read/write on the local network because Windows Explorer can't send credentials over plain HTTP — only enable it on networks you trust. Cloudflared is downloaded over HTTPS from GitHub without a separate checksum.

Verified with an end-to-end test suite (36 checks): headers, symlink escape (download + ZIP), traversal, inline sandboxing, cross-origin blocking, upload name/path handling, resumable limits (oversize chunk, session cap, disk), Content-Disposition injection, PIN lockout (incl. correct PIN refused while locked, unlock after timeout, doubling, global lock), open-redirect and login-page XSS, installer-reference validation, GitHub URL filtering.

---

## Fix — Nearby Devices not seeing a Windows PC from Ubuntu

Discovery announced itself with a single UDP send to `255.255.255.255`. That "limited broadcast" leaves through only the ONE adapter the OS prefers by routing metric — on a Windows PC with WSL / Hyper-V / VirtualBox / VPN virtual adapters that is often not the Wi-Fi/Ethernet adapter the Ubuntu machine is on, so the Ubuntu side never heard it (while the reverse direction worked fine). Now the announcement is sent out of **every** private IPv4 adapter, each from its own address, to both the limited and that network's directed broadcast (real netmask on Linux, /24 assumed on Windows; falls back to the old single send if no adapter can be listed). The listener also records the address a packet actually arrived from instead of trusting the address written inside it, so a multi-adapter PC no longer shows an unreachable virtual-adapter IP. Pressing Refresh in Nearby Devices now also broadcasts immediately. New module `app/network/interfaces.py`.

---

## Auto-update popup now driven by GitHub releases

There is now ONE automatic update option — Settings → Updates → "Automatically check for updates on startup" — and it is connected to the GitHub releases of `ANARKALI27/LocalShare`. With it on, every time LocalShare opens it checks in the background (no more once-a-day limit), and as soon as you've published a newer release the user gets an "Update available" pop-up (`current → new` version, release date, release notes) with **Install** (opens that release's page on GitHub to download and run the installer) and **Later** (asks again next launch). Up to date, no internet, or GitHub rate-limited: completely silent. With the option off, nothing is checked automatically; Check Now still works. The old LAN-peer auto-check on startup was removed so there aren't two different update pop-ups (the manual LAN "Check for Updates" button still works). The Updates page button is now "Install Update".

---

## 3.4.0

Rolls up everything done since the 3.3.0 release: much faster bulk uploads (binary bulk endpoint, parallel batches, live speed/ETA), the 64-file upload-limit fix, the glass Shared Items card fix after Start Sharing, and the redesigned Nearby Devices window. Installer script updated: wizard/uninstaller icon, license page, publisher/support links, 64-bit + Windows 10 requirement, better compression, and uninstall now removes the "Launch at startup" Run-key entry; stale ngrok comment corrected (the app uses cloudflared).

---

## Fast bulk upload (thousands of files) + fix for the 64-file upload limit

**Why it was slow:** every file went through the resumable protocol — three requests (start, chunk, finalize) per file, one file after another. For 10–15k small files that's 40k+ round trips, so the per-request overhead (especially over Wi-Fi/tunnel latency) dwarfed the actual data.

**Now:** small files (≤ 4 MB) are packed into batches (up to 200 files / 32 MB each) and sent many-per-request via `/upload`, with 4 batches in flight at once; big files still use the chunked resumable path. File/folder pickers and drag-and-drop all share one upload engine, and the folder picker reads files in parallel groups. Progress now shows files done, bytes, speed and time left (e.g. `Uploading 3,420/15,000 files · 228 MB / 1.4 GB · 12 MB/s · ~4m left`). Failed batches retry up to 3 times on network errors.

Measured in a real headless Chromium against the real server (localhost): 300 files 7.3 s → 0.5 s; 15,000 files + one 9 MB file uploaded in 10.4 s, every byte verified identical. On a real network the gain is larger because latency is what the old way multiplied.

**Second speed-up — binary bulk endpoint.** Profiling showed the server's remaining cost was parsing `multipart/form-data` (slow in Python, one part per file) plus one event-loop round trip per file. New `POST /api/upload/bulk` takes a batch as a compact container (`[4-byte header length][JSON list of path+size][file bytes…]`) and writes the whole batch in a single worker-thread call: ~1,300 → ~14,000 files/s on the server (≈11×). Same safety as every other upload path: every path goes through `resolve_upload_path`/`safe_join`, names sanitized (Windows reserved names included), existing files never overwritten, batch capped at 1,000 files / 64 MB, malformed or size-mismatched bodies rejected, PIN and cross-site checks apply. The browser falls back to the multipart `/upload` automatically if it talks to an older LocalShare without this endpoint. Batches are now up to 500 files / 24 MB, files up to 8 MB are batched, 6 batches run in parallel (browsers allow ~6 connections per host — measured faster than 4 or 8), and large files upload alongside the batches instead of waiting for them.

**Bug fix (introduced by the security patch above):** the security limit of 64 simultaneous resumable uploads also counted *finished* uploads, so after the 64th large file in a row every further file failed ("Too many uploads in progress"). Only uploads still receiving data count now, and finished records are forgotten after 10 minutes.

---

## Fix — duplicated/striped glass Shared Items card after Start Sharing

The glass card's blurred backdrop is a snapshot of the card's own region, but it was only re-captured when the whole window resized. Start Sharing adds status / tunnel / PIN rows above the card, which shifts or resizes the card without resizing the window — so the old, differently-sized snapshot was tiled (CSS `background-repeat` defaults to repeat), showing the blurred image two or three times as stripes. Now the snapshot is re-taken (debounced, only when the card's position/size actually changed) whenever the card moves or resizes, and the background uses `no-repeat` so a stale image can never tile.

---

## Nearby Devices — UI refresh

Redesigned the Nearby Devices window: bigger title with a live scan-status line, a glass "Connect by Device ID" panel (monospace code field, Enter to connect, accent Connect button, auto-hiding status line), "Recent Devices" rows with Connect / remove, and an "On this network · N" section. Device cards now show a round initial avatar, a green Online / grey Offline chip, the device code as a monospace badge, address and "Same Network", with a hover hint and a circular ⋮ menu — the menu itself is now styled (it was a plain black system menu) and opens under the button, with a separator before the copy actions. Empty state is a dashed panel with an icon. Works on dark and light themes (overlay tint adapts). No behaviour changed: LAN-first connect, global lookup, recent devices, connection test all as before.

---

## Unreleased

**Real GitHub Releases-based update checking.** Settings → Updates now connects to the actual `ANARKALI27/LocalShare` GitHub repository (via `https://api.github.com/repos/ANARKALI27/LocalShare/releases/latest`) rather than only the existing LAN-peer address checker, which stays exactly as it was — the two are separate, legitimate ways to learn about an update, and nothing about the peer-based one was changed, including its own "automatically check for updates on startup" checkbox, its Check for Updates button, and its install-from-a-peer download flow.

New `app/github_update_checker.py`: fetches the latest published (non-draft, non-prerelease — GitHub's `/releases/latest` endpoint excludes both by default) release, normalizes a `v` tag prefix, and does proper segment-by-segment semantic version comparison (reusing the existing `compare_versions` the LAN checker already had, rather than a new implementation) — so `3.10.0` is correctly newer than `3.9.0`, not string-compared backwards. Every failure mode (no internet, GitHub down, DNS failure, rate limiting, an unexpected response shape) comes back as a plain, non-alarming status rather than a scary error, and is never mistaken for "update available" or allowed to block or crash the app.

Settings → Updates page rebuilt with a dedicated LocalShare Updates section: current version, an "Automatically check for updates" toggle (checks at most once every 24 hours, tracked via a stored last-check timestamp — never on every launch), a manual Check Now button, a Last Checked timestamp, and a status line that persists across reopening the dialog without re-checking. When a genuine newer release is found (manual or automatic), a dedicated Update Available dialog shows the version comparison, release date, and release notes from the actual GitHub release body, with View Update (opens the public releases page in the system's default browser — never an embedded one, never anything else) and Later. Automatic checks stay completely silent when already up to date or on any failure, matching the existing LAN auto-checker's own "don't nag" behavior; a manual Check Now still gets a small acknowledgement either way.

No GitHub login or token is used or required — this is a plain, public, read-only API call. Nothing downloaded from a release is ever executed automatically; View Update only ever opens the releases page for the person to choose and run the right installer themselves.

Verified: confirmed the real `ANARKALI27/LocalShare` repository and its actual `v3.3.0` release match this implementation's expected response shape exactly (fetched directly). Full edge-case coverage against a local mock GitHub API server — newer version detected, same version correctly not flagged, an installed version newer than the latest release correctly not flagged (covers a dev build ahead of the last release), a tag with no `v` prefix, numeric comparison correctness (3.10.0 vs 3.9.0), HTTP 403 rate-limiting, 404 no-releases, malformed/non-JSON responses, a response missing `tag_name` entirely, and a genuine connection failure to an unreachable port. Full Settings-dialog integration verified in a real headless Qt environment: constructing the window, a manual check correctly triggering the Update Available dialog for a newer release, the same check correctly NOT showing it and showing an "up to date" message instead when versions match, a network failure correctly showing neither, the status labels reflecting each outcome, View Update opening the correct cached release URL, and the automatic startup check correctly respecting both the 24-hour gate and the on/off setting. Also re-confirmed the existing LAN/peer update feature's widgets and behavior are completely unchanged.

**Fixed: the Shared Items card looked dark/flat on first launch even with Glass Effect already on, only fixing itself once a setting like Transparency was touched.** main.py constructs the window, plays the splash screen with the window still hidden, and only then shows it. The glass snapshot was being taken during that hidden phase, when Qt reports pre-layout defaults instead of real geometry (measured: position 0,0 and 640x480 instead of the card's actual 20,314 and 468x88) — so it captured the wrong part of the background, and nothing refreshed it after the window appeared. An earlier attempt at this fix (a zero-delay timer) did not help for exactly this reason: it still fired while the window was hidden. Now the snapshot is skipped while the window is hidden and refreshed from showEvent (immediately after layout, plus once more 300 ms later as a safety net). Verified by reproducing the real splash-then-show flow, confirming every snapshot after show uses the final settled geometry, and checking against a banded test background that the card's blur matches the colour actually behind it; also checked that Off stays a no-op and that changing the effect or resizing while visible still refresh correctly.

**Launch at startup.** New Settings checkbox — "Launch LocalShare when my computer starts" — registers LocalShare to open automatically at login, using each platform's own standard mechanism: a per-user Windows Registry Run key (no admin rights needed) or a Linux XDG autostart .desktop file. This is a genuinely different thing from the existing "automatically start server when LocalShare launches" setting, which only affects what happens once the app is already open — this one launches the app itself, before it's been opened at all. Correctly distinguishes a frozen/installed build (launches the actual executable) from running from source (launches via the Python interpreter). Hidden entirely on any platform other than Windows/Linux, rather than showing a control that couldn't do anything there. If enabling or disabling it fails (e.g. a permissions issue), the checkbox reverts to reflect what's actually true rather than showing a state that didn't take effect, with a clear error message explaining why.

Tested thoroughly given this touches real OS state: the Linux path end-to-end for real (not mocked) — enabling, verifying the actual .desktop file's contents, idempotent re-enabling, disabling, and idempotent re-disabling all confirmed against the real filesystem. The Windows registry path was tested against a mock winreg module built to match the real module's documented API shape, verifying the correct key/value get written, read, and removed, and that idempotent enable/disable both behave correctly — this environment has no Windows to test the real winreg module directly, so this is what's actually been verified: the logic's correctness against that shape, not a real Windows registry.

**Fixed: card/background still looked flat black even with the glass effect set to "Subtle."** Root cause: the previous fix changed the transparency/glass *defaults*, but the default background type was still "solid" — a flat, uniform color. Blurring a uniform color produces the same uniform color back, so the glass effect had nothing to visually show against, regardless of its own setting. Changed the default background to a subtle gradient (kept consistent across the initial-load default, the Settings dialog's displayed state, and Reset Appearance's target state), which gives the blur actual color variation to work with. Also fixed a real, separate bug found while touching this code: Reset Appearance hardcoded the transparency slider's displayed value to 100 regardless of what it had just set the actual transparency to (85), a genuine display/state mismatch — now computed from the real value instead of a disconnected hardcoded number.

**Fixed: dragging multiple folders onto the browser page didn't work.** The drop handler only ever read the flat `e.dataTransfer.files` list, which can't see into a dropped folder's contents at all — it needs the separate `webkitGetAsEntry()` API to recursively read a folder's structure, which nothing in this app was using yet. Implemented proper recursive traversal (handling the documented, easy-to-miss quirk that `readEntries()` returns results in batches and must be called repeatedly until empty, not just once), supporting any number of files and folders dropped together at once, nested arbitrarily deep — verified against mock objects matching the real browser API shape, including a test specifically replicating "two folders dropped at the same time," the exact scenario reported.

**Appreciation / support option.** A one-time, dismissible prompt on
first launch mentions that LocalShare can be appreciated via UPI from
Settings → About — never nags, never blocks anything, shown exactly
once. About page now has a "❤️ Thank the Developer" button (reachable
anytime afterward) showing a UPI QR code and ID for anyone who wants
to support the project, plus a note with an email address for bugs,
messages, or feature ideas. Entirely optional in every sense — the
app is fully functional with this ignored or dismissed immediately.

**Global Device ID Connect — connect to a device anywhere by its
Device ID, not just on the same LAN.** Extends Nearby Devices: enter a
Device ID in "Connect by Device ID" and LocalShare tries your local
network first (instant), then falls back to a global lookup if not
found locally.

Deliberately built WITHOUT a custom signaling/relay server —
LocalShare already has a free, zero-maintenance way to make a device
reachable from the internet (the existing Cloudflare Tunnel behind
"Global" sharing). The only missing piece for Device-ID-only
connection was answering "where is this device right now," which is
now a lookup against a free-tier Firebase Realtime Database the user
sets up themselves (GLOBAL_CONNECT_SETUP.md has the exact steps — a
few minutes on a free Google account, no server to rent or maintain).
Actual file transfer is entirely unchanged: it's the same Cloudflare
tunnel, PIN protection, and web UI Global sharing already used.

Security: each device holds a private write_token (separate from its
public Device ID, generated locally, never displayed) that must match
before its registry entry can be overwritten — this is what stops
someone from squatting an existing Device ID or redirecting it to a
URL they control. Found and fixed two real holes in this before
finalizing it, both through direct testing against a mock server
replicating Firebase's actual REST behavior, not by inspection: (1) an
initial security rule draft had a clause meant to permit deletion that
actually permitted ANY write with an empty body regardless of token,
and (2) an early "unregister" design that wrote only to a last_seen
sub-field turned out to make the token comparison compare Firebase's
existing stored value to itself, passing unconditionally regardless of
who sent the request. Both are fixed: "going offline" is now a full,
properly token-checked write (reusing the same path as a normal
heartbeat) rather than an HTTP DELETE or a partial-field write, either
of which turned out to have no way to carry proof of ownership.

Online/offline status is based on a real heartbeat (every 30s while
Global sharing is active) with a 90-second grace window before reading
as offline — not just "a record exists," and stopping sharing marks
the device offline immediately rather than waiting out that window.

Not implemented, and deliberately so rather than guessed at: the
spec's proposed interactive "incoming connection, accept/reject"
prompt. That needs its own signaling round-trip between the two
devices that hasn't been built or tested; Global mode's existing
automatic PIN requirement is the access-control gate for now, which is
a real, existing mechanism rather than newly-invented and unverified.
True P2P/NAT traversal (STUN/TURN/WebRTC) was also not attempted —
reusing the existing Cloudflare tunnel sidesteps needing it entirely
for this phase, at the cost of not being genuinely peer-to-peer.

**Nearby Devices — see and open other LocalShare installations on your
network.** New "Nearby Devices" button opens a dialog listing other
LocalShare instances discovered via LAN broadcast (no central server
involved), each shown as a card with name, persistent device code,
IP:port, and online/offline status. Click a card (or its "Open"
action) to launch that device's address in your default browser.
Secondary actions per device: copy address, copy device code, test
connection (verifies the actual server responds, not just that a
discovery packet arrived), and a details view.

Every LocalShare installation now has a persistent, cryptographically
random device code (LS-XXXX-XXXX format, via Python's `secrets`
module) that survives restarts, IP changes, and switching networks —
configurable in Settings → Device, along with an editable device name
and a "Regenerate Device Code" option (behind a confirmation, since it
means other devices will need to re-discover this one). Discovery can
be turned off entirely from the same page if the automatic LAN
broadcast isn't wanted.

This revives and substantially rewrites discovery code that already
existed in the project from an earlier phase but had become
disconnected from the UI — including fixing a real bug in that
original code: it generated a brand-new random device ID on every
single launch, which defeated the entire point of a "persistent"
identity. Implemented as a dialog opened from a button (matching how
Settings already works) rather than a sidebar page, since this app's
sidebar navigation was deliberately removed in an earlier revision —
reintroducing it for one feature would contradict that decision and
change the app's established visual style.

Verified with real, not mocked, testing throughout: two genuinely
separate OS processes, each announcing a different device identity,
discovered each other for real over actual UDP broadcast — directly
exercising the same scenario as manually testing with two physical
PCs. The connection tester was verified against real HTTP servers
including actual timeout behavior on an unroutable address. The full
GUI — MainWindow construction, the Nearby Devices dialog, and the new
Settings page — was constructed and exercised in a real (headless)
Qt environment, including the device name/regenerate/discovery-toggle
flows actually updating the live running service, not just verified
by inspection the way most of this project's GUI code has had to be.

**Internet sharing switched back to Cloudflare Quick Tunnel, final
this time.** After discovering ngrok's free tier caps at 1GB of
bandwidth per month — meaning a single ~140MB file upload used 14% of
an entire month's allowance, plausibly explaining reported slowness —
and researching real throughput benchmarks (mixed results, 20-46 Mbps
depending on the source) and a reported 100MB body-size limit on
Cloudflare's free tier that could have blocked exactly that kind of
large file, the decision was made to return to Cloudflare specifically
BUT implemented completely differently from the original v3.0.0
attempt: instead of the user needing to install `cloudflared`
separately (or a fragile installer-time PowerShell download script
that turned out unreliable — Windows PowerShell 5.1's default TLS
negotiation fighting GitHub, among other issues), `cloudflared` now
downloads itself automatically at runtime, in Python, the first time
Global mode is actually used — the same pattern that worked well for
pyngrok, just implemented directly with the standard library instead
of a third-party package this time. Verified genuinely end-to-end:
downloaded the real cloudflared binary from GitHub's releases,
confirmed complete and executable, confirmed it runs and reports its
version correctly, tested the full success/failure/already-installed
paths against the actual download function and TunnelHandle.start().

Removed the ngrok authtoken UI, the ngrok-specific Setup Guide steps,
and the pyngrok dependency entirely.

**Internet sharing switched back from Cloudflare Quick Tunnel to
ngrok** (via `pyngrok`) — reversing the v3.0.0 change below. Reasons:
Cloudflare Quick Tunnel's `cloudflared` binary needed a separate,
error-prone installer step (a PowerShell download script fighting
Windows PowerShell 5.1's default TLS negotiation, among other things)
that proved unreliable in practice; `pyngrok` manages its own binary
download automatically at runtime instead, with no separate installer
step needed. Trade-off: ngrok now requires a free account and
authtoken again (configured in Settings → Sharing), since ngrok no
longer offers Cloudflare's old no-signup option. Added a "❓ Setup
Guide" welcome dialog (shown once automatically, reachable anytime
after) walking through the authtoken setup with direct links.

Also fixed in the same pass:
- **Uploads could fail outright on Windows.** The concurrent-chunk
  upload system opened the same file from multiple threads
  simultaneously, verified safe on Linux but never actually tested on
  Windows, where file-handle sharing is stricter by default. Disk
  writes are now serialized behind a lock while still allowing
  network transfer to overlap across chunks.
- **Dragging a file onto the browser page did the browser's own
  default thing** (attempting to open/save it locally) instead of
  uploading it — there was no drag-and-drop handling on the web page
  at all, only on the desktop app's own drop zone. This also
  incidentally bypassed PIN protection, since the drop never reached
  the server. Added real drag-and-drop upload support to the browser
  page, including for PIN-protected shares.

---

## v3.0.0

**Internet sharing switched from ngrok to Cloudflare Quick Tunnel** —
no account or signup required anymore (ngrok required one). Uses the
`cloudflared` program directly rather than a Python package; detection
now also checks winget's install location directly as a fallback, not
just PATH, since a just-installed program isn't always visible on
PATH to a process that was already running.

**Real bugs found and fixed:**
- Failed internet tunnel no longer leaves a misleading local-only
  QR code/address on screen while in Global mode — it now shows
  nothing until the tunnel actually connects, with a clear warning if
  it fails
- Settings dialog (and likely every `QMessageBox` popup) was
  rendering unstyled/white — Qt doesn't reliably cascade a
  per-widget stylesheet to separate top-level windows; theming now
  applied at the `QApplication` level, which Qt does guarantee reaches
  every window
- Text input fields (`QLineEdit`) and dropdowns (`QComboBox`) had zero
  theme styling at all — rendered as solid black bars
- Radio button and checkbox selection indicators were invisible
  (a risky gradient trick produced inconsistent rendering) — replaced
  with simple, reliable checkmark icons
- PIN checkbox got permanently stuck "on" after visiting Global mode
  even after switching back to Local — now remembers your actual
  Local-mode preference separately from Global's forced-on state
- `pyngrok`/ngrok crashed in the packaged `.exe` specifically
  (`'NoneType' object has no attribute 'write'`) — same root cause as
  an earlier uvicorn bug (no console in a windowed build means
  `stdout` is `None`), fixed generally this time at the app's entry
  point rather than per-library
- Update-source address field showed a stale IP every launch — now
  starts empty and clears after each check, only falling back to the
  remembered address when needed

**Also new:**
- Full auto-update flow: on finding a newer version, offers
  "Install Now" — downloads the installer and hands off to the OS's
  own installer/package manager (safer than manually replacing a
  locked running `.exe`)
- Settings consolidated into one dialog (theme, accent color,
  gradient background, auto-update checkbox) instead of scattered
  controls
- Two more animated gradient background styles (Pulse, Aurora) with a
  style picker, alongside the original Sweep
- "WebDAV" renamed to "Network Drive access" throughout — same
  feature, plain-language name

---

## v2.0.0

**New:**
- PIN protection for the browser share and messaging (off by default,
  auto-generated or custom 6-digit code)
- Sharing Mode selector: **Local Network Only** (unchanged from v1) vs
  **Global** (new — reachable from outside your Wi-Fi via a tunnel)
- PIN is mandatory and locked on whenever Global mode is selected —
  can't be turned off, since the share is then reachable by anyone
  who finds the link
- QR codes and copied share links now embed an access token when PIN
  protection is on, so scanning still grants one-tap access without
  retyping the PIN

**Fixed:**
- Radio button and checkbox selection indicators were invisible due
  to the global dark-theme stylesheet overriding Qt's native
  rendering — added explicit indicator styling
- Corrected stale documentation (WebDAV docstring, README) that still
  claimed "no part of this app has access control," left over from
  before PIN protection existed

**Also added:** version number shown beside the app title; explicit
"● Local Network Only selected" / "● Global selected" text so the
active mode is unambiguous.

---

## v1.0.0

The original feature set — no PIN, no internet sharing, LAN-only.

- Drag-and-drop file/folder sharing over a browser-accessible local
  HTTP server
- Two-way transfers: download from the host, upload back to it
- Resumable uploads (chunked, offset-verified) and Range-based
  resumable downloads
- Hover previews (images, video, text snippets, folder peek)
- Private messaging with image/video attachments
- Dark/light theme toggle plus custom accent color picker
- QR code for phone access, with a "Save QR Code" export
- WebDAV / Explorer integration (experimental, Windows-specific
  port-80 requirement, anonymous-only by design)
- "Check for Updates" — compares version against another running
  LocalShare instance
- Animated splash screen, app icon, "Open in File Explorer" shortcut
- Windows packaging: PyInstaller `.exe` + Inno Setup installer
- Debian/Ubuntu packaging: PyInstaller binary + `.deb` package
- Distro-portable build scripts (PEP 668 handling, dpkg-deb detection,
  PATH-independent PyInstaller invocation)

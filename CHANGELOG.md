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

## Unreleased

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

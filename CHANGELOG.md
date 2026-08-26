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

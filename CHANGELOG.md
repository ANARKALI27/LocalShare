# Changelog

Git tags mark the exact commit boundary for each version — `v1.0.0`
and `v2.0.0` can be checked out directly to get that version's code
with nothing from later versions mixed in:
```
git checkout v1.0.0   # pure v1, no PIN/internet-sharing code exists at all
git checkout v2.0.0   # current
```

---

## v2.0.0

**New:**
- PIN protection for the browser share and messaging (off by default,
  auto-generated or custom 6-digit code)
- Sharing Mode selector: **Local Network Only** (unchanged from v1) vs
  **Global** (new — reachable from outside your Wi-Fi via an ngrok
  tunnel)
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

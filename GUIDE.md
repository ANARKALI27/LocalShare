# LocalShare by ANARKALI

Share files with anyone on your Wi-Fi — no internet, no accounts, no cables.

Drag a file in, share an address, and the other person opens it in any
browser to download, upload, or chat. That's the whole idea.

---

## ✨ Features

- **Drag & drop sharing** — drop files or folders in, they're instantly shareable
- **Works from any device** — the other person just opens a web address in
  their browser (phone, laptop, anything on the same network)
- **Two-way transfers** — they can send files back to you too, not just download
- **Big files won't restart from zero** — if an upload gets interrupted, it
  picks up where it left off instead of starting over
- **Hover previews** — see what's inside a file or folder before downloading it
- **Private messages** — a simple chat with photo/video sharing, built right in
- **QR code** — scan it with a phone camera to open the share instantly,
  no typing an address
- **Dark & light themes**, plus a custom accent color picker
- **PIN protection** — lock your share behind a 6-digit code so only people you give it to can access it
- **Share over the internet, not just Wi-Fi** (new in v2) — reach someone who isn't on your network
- **Windows Explorer / Linux file manager integration** (optional — see note below)
- **Check for Updates** button to see if a newer version is available

---

## 📥 Installing

### Windows
Run `LocalShareSetup.exe` and click through the installer. You'll get a
Start Menu entry and, optionally, a desktop icon. No other software needed.

### Debian / Ubuntu Linux
```
sudo apt install ./localshare_<version>_amd64.deb
```
LocalShare will appear in your applications menu, and you can also just
type `localshare` in a terminal.

---

## 🚀 How to use it

1. **Open LocalShare.**
2. **Drag a file or folder into the window** (or click "Add Files…" / "Add Folder…").
3. **Choose a sharing mode:**
   - **Local Network Only** (default) — for people on the same Wi-Fi as you. No PIN needed, though you can turn one on.
   - **Global** — for someone who isn't on your network. Requires `cloudflared` installed (free, one-time setup, see below — no account or signup needed) and **automatically requires a PIN** — you can't turn that off in this mode, since anyone with the link could otherwise reach it.
4. **Click "Start Sharing."** An address appears, along with a QR code. If PIN protection is on, the PIN shows on screen too — tell the other person what it is (or just send the QR code / link, which unlocks automatically).
5. **Give that address (or QR code) to whoever you're sharing with.**
6. **They open it in any web browser.** If a PIN is set and they typed the address by hand, they'll be asked to enter it once. They'll see everything you've shared and can download it.
7. **They can send things back too** — inside a shared folder, they'll see
   "Upload Files" / "Upload Folder" buttons.
8. **Want to chat?** Click the "Messages" tab at the top — works from either side,
   supports photos and videos.
9. **When you're done, click "Stop Sharing."**

### Setting up internet sharing (one-time)

Install `cloudflared` — no account or signup needed, unlike some
similar tools:
- **Windows:** `winget install --id Cloudflare.cloudflared`
- **Linux:** see https://pkg.cloudflare.com/index.html
- **macOS:** `brew install cloudflared`

That's it — select "Global" mode in LocalShare and click Start Sharing.

**Worth knowing:** Cloudflare's free tunnels are meant for casual/testing
use, not guaranteed always-on reliability — fine for sharing with a
friend, not something to depend on for anything critical.

---

## 💡 A few things worth knowing

- **Local Network Only mode needs both people on the same Wi-Fi/router** —
  that hasn't changed. Use Internet mode (above) if that's not possible.
- **PIN protection is off by default in Local Network mode** — turn it on
  yourself if you want it; anyone who reaches your address without it can
  browse, download, upload, and message freely. It's automatically forced
  on in Internet mode.
- **The "Network Drive access" feature** is a bonus for people who want
  people who want their file manager to show the share like a regular folder.
  It's labeled "experimental" for a reason — it can be finicky depending on
  your system, and it never supports a PIN even if one is set elsewhere.
  The browser method above always works and is the reliable path.

---

Developed by **ANARKALI**

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
3. **Click "Start Sharing."** An address like `http://192.168.1.105:8765`
   appears, along with a QR code.
4. **Give that address (or QR code) to whoever you're sharing with** — they
   need to be on the same Wi-Fi/network as you.
5. **They open it in any web browser.** They'll see everything you've shared
   and can download it.
6. **They can send things back too** — inside a shared folder, they'll see
   "Upload Files" / "Upload Folder" buttons.
7. **Want to chat?** Click the "Messages" tab at the top — works from either side,
   supports photos and videos.
8. **When you're done, click "Stop Sharing."**

That's genuinely the whole workflow — nothing to configure, no accounts to make.

---

## 💡 A few things worth knowing

- **Both people need to be on the same network** (same Wi-Fi, or same router).
  This doesn't work over the internet — it's for LAN use.
- **There's currently no password/PIN protection** — anyone who can reach your
  address on the network can access what you've shared. Fine for home/office
  use with people you trust; don't rely on it for sensitive files.
- **The Explorer/file-manager integration (WebDAV)** is a bonus feature for
  people who want their file manager to show the share like a regular folder.
  It's labeled "experimental" for a reason — it can be finicky depending on
  your system. The browser method above always works and is the reliable path.

---

Developed by **ANARKALI**

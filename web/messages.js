// LocalShare messages page. Polls for new messages (no websockets, keeps
// the server simple) and posts new ones as multipart/form-data so
// image/video attachments stream through the same upload machinery as
// the rest of the app.

const POLL_INTERVAL_MS = 3000;

const messagesListEl = document.getElementById("messages-list");
const composerEl = document.getElementById("composer");
const messageInputEl = document.getElementById("message-input");
const attachInputEl = document.getElementById("attach-input");
const attachmentPreviewEl = document.getElementById("attachment-preview");

// Every browser/device gets an editable display name, stored locally so
// it persists across visits on THIS device. (This is a real standalone
// web app served by the user's own machine — not a sandboxed artifact —
// so localStorage behaves normally here.)
function getDisplayName() {
  let name = localStorage.getItem("localshare_display_name");
  if (!name) {
    name = prompt("What's your name? (shown to the other person)", "") || "Anonymous";
    localStorage.setItem("localshare_display_name", name);
  }
  return name;
}

let displayName = getDisplayName();
let lastSeenId = 0;
let pendingFiles = [];

function formatTime(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatSize(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function isImageMime(mime) {
  return mime && mime.startsWith("image/");
}

function isVideoMime(mime) {
  return mime && mime.startsWith("video/");
}

function renderMessage(msg) {
  const bubble = document.createElement("div");
  bubble.className = "message-bubble" + (msg.sender === displayName ? " own" : "");

  const senderEl = document.createElement("div");
  senderEl.className = "message-sender";
  senderEl.textContent = msg.sender;
  bubble.appendChild(senderEl);

  if (msg.text) {
    const textEl = document.createElement("div");
    textEl.className = "message-text";
    textEl.textContent = msg.text; // textContent, never innerHTML — messages are untrusted input
    bubble.appendChild(textEl);
  }

  if (msg.attachments.length > 0) {
    const attachWrap = document.createElement("div");
    attachWrap.className = "message-attachments";
    for (const att of msg.attachments) {
      if (isImageMime(att.mime_type)) {
        const img = document.createElement("img");
        img.src = att.url;
        img.alt = att.filename;
        attachWrap.appendChild(img);
      } else if (isVideoMime(att.mime_type)) {
        const video = document.createElement("video");
        video.src = att.url;
        video.controls = true;
        attachWrap.appendChild(video);
      } else {
        const link = document.createElement("a");
        link.className = "file-attachment";
        link.href = att.url;
        link.textContent = `📄 ${att.filename} (${formatSize(att.size)})`;
        attachWrap.appendChild(link);
      }
    }
    bubble.appendChild(attachWrap);
  }

  const timeEl = document.createElement("div");
  timeEl.className = "message-time";
  timeEl.textContent = formatTime(msg.timestamp);
  bubble.appendChild(timeEl);

  return bubble;
}

function isScrolledToBottom() {
  const threshold = 60;
  return (
    messagesListEl.scrollHeight - messagesListEl.scrollTop - messagesListEl.clientHeight < threshold
  );
}

async function pollMessages() {
  try {
    const res = await fetch(`/api/messages?since=${lastSeenId}`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.messages.length > 0) {
      const wasAtBottom = isScrolledToBottom();
      const emptyState = messagesListEl.querySelector(".messages-empty");
      if (emptyState) emptyState.remove();

      for (const msg of data.messages) {
        messagesListEl.appendChild(renderMessage(msg));
      }
      lastSeenId = data.latest_id;

      if (wasAtBottom) {
        messagesListEl.scrollTop = messagesListEl.scrollHeight;
      }
    }
  } catch (err) {
    // silent — next poll will retry; no need to spam the UI over one dropped poll
  }
}

function renderPendingFiles() {
  attachmentPreviewEl.innerHTML = "";
  if (pendingFiles.length === 0) {
    attachmentPreviewEl.classList.add("hidden");
    return;
  }
  attachmentPreviewEl.classList.remove("hidden");
  pendingFiles.forEach((file, idx) => {
    const chip = document.createElement("div");
    chip.className = "pending-file";
    const label = document.createElement("span");
    label.textContent = `${file.type.startsWith("video/") ? "🎬" : "🖼️"} ${file.name}`;
    const remove = document.createElement("span");
    remove.className = "remove-pending";
    remove.textContent = "✕";
    remove.onclick = () => {
      pendingFiles.splice(idx, 1);
      renderPendingFiles();
    };
    chip.appendChild(label);
    chip.appendChild(remove);
    attachmentPreviewEl.appendChild(chip);
  });
}

attachInputEl.addEventListener("change", () => {
  pendingFiles.push(...Array.from(attachInputEl.files));
  attachInputEl.value = "";
  renderPendingFiles();
});

composerEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = messageInputEl.value.trim();
  if (!text && pendingFiles.length === 0) return;

  const formData = new FormData();
  formData.append("sender", displayName);
  formData.append("text", text);
  for (const file of pendingFiles) {
    formData.append("files", file);
  }

  messageInputEl.value = "";
  const filesToSend = pendingFiles;
  pendingFiles = [];
  renderPendingFiles();

  try {
    const res = await fetch("/api/messages", { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    // the next poll picks up the new message (including from ourselves),
    // keeping a single source of truth instead of rendering twice
    await pollMessages();
  } catch (err) {
    alert(`Couldn't send message: ${err.message}`);
    // put the content back so nothing is silently lost
    messageInputEl.value = text;
    pendingFiles = filesToSend;
    renderPendingFiles();
  }
});

if (messagesListEl.children.length === 0) {
  const empty = document.createElement("div");
  empty.className = "messages-empty";
  empty.textContent = "No messages yet — say hi 👋";
  messagesListEl.appendChild(empty);
}

pollMessages();
setInterval(pollMessages, POLL_INTERVAL_MS);

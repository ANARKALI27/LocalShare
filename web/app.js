// LocalShare web browser — no framework, keeps things simple and dependency-free.

const listingEl = document.getElementById("listing");
const listingBody = document.getElementById("listing-body");
const emptyStateEl = document.getElementById("empty-state");
const loadingEl = document.getElementById("loading");
const errorEl = document.getElementById("error");
const breadcrumbsEl = document.getElementById("breadcrumbs");
const uploadBarEl = document.getElementById("upload-bar");
const uploadFilesInput = document.getElementById("upload-files-input");
const uploadFolderInput = document.getElementById("upload-folder-input");
const uploadStatusEl = document.getElementById("upload-status");

function getUrlParams() {
  const params = new URLSearchParams(window.location.search);
  return {
    item: params.get("item") || "",
    path: params.get("path") || "",
  };
}

function formatSize(bytes) {
  if (bytes === 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function browseUrl(item, path) {
  const params = new URLSearchParams();
  if (item) params.set("item", item);
  if (path) params.set("path", path);
  return `/?${params.toString()}`;
}

function apiUrl(item, path) {
  const params = new URLSearchParams();
  if (item) params.set("item", item);
  if (path) params.set("path", path);
  return `/api/browse?${params.toString()}`;
}

function renderBreadcrumbs(breadcrumbs) {
  breadcrumbsEl.innerHTML = "";
  breadcrumbs.forEach((crumb, idx) => {
    if (idx > 0) {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "/";
      breadcrumbsEl.appendChild(sep);
    }
    const link = document.createElement("a");
    link.textContent = crumb.name;
    link.onclick = () => navigate(crumb.item, crumb.path);
    breadcrumbsEl.appendChild(link);
  });
}

function renderEntries(entries, currentItem, currentPath) {
  listingBody.innerHTML = "";

  const isRoot = !currentItem;

  if (entries.length === 0) {
    listingEl.classList.add("hidden");
    emptyStateEl.classList.remove("hidden");
    emptyStateEl.querySelector("p").textContent = isRoot
      ? "Nothing shared yet."
      : "This folder is empty.";
    return;
  }

  emptyStateEl.classList.add("hidden");
  listingEl.classList.remove("hidden");

  for (const entry of entries) {
    const tr = document.createElement("tr");

    // At root, each entry IS a separate shared item (its own id, path
    // always ""). Below root, entries are children within the current
    // shared item, addressed by appending their name to currentPath.
    const ref = isRoot
      ? { item: entry.id, path: "" }
      : { item: currentItem, path: currentPath ? `${currentPath}/${entry.name}` : entry.name };

    const nameTd = document.createElement("td");
    const nameWrap = document.createElement("div");
    nameWrap.className = "entry-name";
    const icon = document.createElement("span");
    icon.textContent = entry.is_dir ? "📁" : "📄";
    nameWrap.appendChild(icon);

    if (entry.is_dir) {
      const link = document.createElement("a");
      link.textContent = entry.name;
      link.href = browseUrl(ref.item, ref.path);
      link.onclick = (e) => {
        e.preventDefault();
        navigate(ref.item, ref.path);
      };
      nameWrap.appendChild(link);
    } else {
      const span = document.createElement("span");
      span.textContent = entry.name;
      nameWrap.appendChild(span);
    }
    nameTd.appendChild(nameWrap);

    const sizeTd = document.createElement("td");
    sizeTd.className = "col-size";
    sizeTd.textContent = entry.is_dir ? "—" : formatSize(entry.size);

    const actionsTd = document.createElement("td");
    actionsTd.className = "col-actions";
    const downloadLink = document.createElement("a");
    downloadLink.className = "action-btn";
    downloadLink.textContent = entry.is_dir ? "Download ZIP" : "Download";
    const dlParams = new URLSearchParams();
    dlParams.set("item", ref.item);
    dlParams.set("path", ref.path);
    downloadLink.href = `${entry.is_dir ? "/download-zip" : "/download"}?${dlParams.toString()}`;
    actionsTd.appendChild(downloadLink);

    tr.appendChild(nameTd);
    tr.appendChild(sizeTd);
    tr.appendChild(actionsTd);

    tr.addEventListener("mouseenter", (e) => schedulePreview(tr, ref, entry, e));
    tr.addEventListener("mousemove", (e) => positionPreviewNear(e));
    tr.addEventListener("mouseleave", hidePreview);

    listingBody.appendChild(tr);
  }
}

async function navigate(item, path) {
  history.pushState({}, "", browseUrl(item, path));
  await loadListing(item, path);
}

let currentBrowseItem = "";
let currentBrowsePath = "";

async function loadListing(item, path) {
  loadingEl.classList.remove("hidden");
  errorEl.classList.add("hidden");
  listingEl.classList.add("hidden");
  emptyStateEl.classList.add("hidden");
  uploadBarEl.classList.add("hidden");

  try {
    const res = await fetch(apiUrl(item, path));
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Server returned ${res.status}`);
    }
    const data = await res.json();
    loadingEl.classList.add("hidden");
    renderBreadcrumbs(data.breadcrumbs);
    renderEntries(data.entries, item, path);

    currentBrowseItem = item;
    currentBrowsePath = path;
    // Uploading only makes sense inside an actual shared folder, not at
    // the Home root (which just lists separate shared items/files).
    if (item) {
      uploadBarEl.classList.remove("hidden");
    }
  } catch (err) {
    loadingEl.classList.add("hidden");
    errorEl.classList.remove("hidden");
    errorEl.textContent = `Couldn't load this folder: ${err.message}`;
  }
}

// Chunk size for resumable uploads. Small enough to keep memory light
// and give frequent progress updates; large enough not to drown small
// LANs in per-request overhead.
const UPLOAD_CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB

// How many chunks to have in flight at once. The server now accepts
// chunks at any offset (not strictly in order), specifically so this
// can be >1: with only one chunk in flight at a time, network transfer
// and the server's disk write never overlap, which leaves real
// throughput on the table. A handful in flight lets those overlap
// without opening so many connections it works against itself.
const UPLOAD_CONCURRENCY = 3;

function uploadFingerprintKey(item, path, relativePath, file) {
  return `localshare_upload::${item}::${path}::${relativePath}::${file.size}::${file.lastModified}`;
}

/**
 * Uploads one file using the chunked resumable protocol, with several
 * chunks in flight concurrently rather than one at a time. If a
 * matching in-progress upload was left over from a previous attempt
 * (tracked by fingerprint in localStorage), resumes from wherever the
 * SERVER says it actually got to — never trusts the client's own
 * memory of progress, since that's exactly what can be wrong after a
 * crash/reload.
 */
async function uploadFileResumable(file, relativePath, item, path, onProgress) {
  const fpKey = uploadFingerprintKey(item, path, relativePath, file);
  let uploadId = localStorage.getItem(fpKey);
  let bytesReceived = 0;

  if (uploadId) {
    try {
      const statusRes = await fetch(`/api/upload/status/${uploadId}`);
      if (statusRes.ok) {
        const status = await statusRes.json();
        if (!status.finalized && status.total_size === file.size) {
          bytesReceived = status.bytes_received;
        } else {
          uploadId = null; // stale/mismatched session — start fresh
        }
      } else {
        uploadId = null; // session gone server-side (e.g. app was restarted)
      }
    } catch (err) {
      uploadId = null;
    }
  }

  if (!uploadId) {
    const startForm = new FormData();
    startForm.append("item", item);
    startForm.append("path", path);
    startForm.append("filename", file.name);
    startForm.append("relative_path", relativePath);
    startForm.append("total_size", String(file.size));
    const startRes = await fetch("/api/upload/start", { method: "POST", body: startForm });
    if (!startRes.ok) {
      const body = await startRes.json().catch(() => ({}));
      throw new Error(body.detail || `Couldn't start upload (${startRes.status})`);
    }
    const startData = await startRes.json();
    uploadId = startData.upload_id;
    bytesReceived = 0;
    localStorage.setItem(fpKey, uploadId);
  }

  // Chunk offsets still needing to be sent. Resuming still starts from
  // the server's last known position as a reasonable default, but
  // — unlike before — chunks from here on don't need to land in order,
  // since the server now tracks *which* byte ranges have arrived
  // rather than requiring one running "next expected offset."
  const chunkOffsets = [];
  for (let offset = bytesReceived; offset < file.size; offset += UPLOAD_CHUNK_SIZE) {
    chunkOffsets.push(offset);
  }

  let nextIndex = 0;
  let latestBytesReceived = bytesReceived;
  let uploadError = null;

  async function uploadOneChunk(offset) {
    const end = Math.min(offset + UPLOAD_CHUNK_SIZE, file.size);
    const chunk = file.slice(offset, end);

    let attempts = 0;
    while (true) {
      attempts++;
      let res;
      try {
        res = await fetch(`/api/upload/chunk/${uploadId}?offset=${offset}`, {
          method: "PUT",
          body: chunk,
        });
      } catch (networkErr) {
        // Transient network drop (Wi-Fi hiccup, cable bump) — worth
        // retrying rather than failing the whole upload, but not
        // forever if the connection is genuinely gone.
        if (attempts >= 10) {
          throw new Error("Connection lost repeatedly — check your network and try again");
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
        continue;
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Chunk upload failed (${res.status})`);
      }

      const data = await res.json();
      if (data.bytes_received > latestBytesReceived) {
        latestBytesReceived = data.bytes_received;
        if (onProgress) onProgress(latestBytesReceived, file.size);
      }
      return;
    }
  }

  async function worker() {
    while (nextIndex < chunkOffsets.length && !uploadError) {
      const offset = chunkOffsets[nextIndex++];
      try {
        await uploadOneChunk(offset);
      } catch (err) {
        uploadError = err;
        return;
      }
    }
  }

  const workerCount = Math.min(UPLOAD_CONCURRENCY, Math.max(chunkOffsets.length, 1));
  await Promise.all(Array.from({ length: workerCount }, () => worker()));

  if (uploadError) throw uploadError;

  // Belt-and-suspenders: confirm the server genuinely has every byte
  // before asking it to finalize, rather than assuming our own view
  // of "all workers finished" is exactly right.
  const finalStatusRes = await fetch(`/api/upload/status/${uploadId}`);
  const finalStatus = await finalStatusRes.json();
  if (finalStatus.bytes_received < file.size) {
    throw new Error(
      `Upload incomplete: ${finalStatus.bytes_received}/${file.size} bytes received`
    );
  }

  const finalizeRes = await fetch(`/api/upload/finalize/${uploadId}`, { method: "POST" });
  if (!finalizeRes.ok) {
    const body = await finalizeRes.json().catch(() => ({}));
    throw new Error(body.detail || `Couldn't finalize upload (${finalizeRes.status})`);
  }
  localStorage.removeItem(fpKey);
  return await finalizeRes.json();
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList);
  if (files.length === 0) return;

  uploadFilesInput.disabled = true;
  uploadFolderInput.disabled = true;

  let succeeded = 0;
  const failures = [];

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const relativePath = file.webkitRelativePath || file.name;

    try {
      await uploadFileResumable(file, relativePath, currentBrowseItem, currentBrowsePath, (sent, total) => {
        const pct = total > 0 ? Math.round((sent / total) * 100) : 0;
        uploadStatusEl.textContent = `Uploading ${i + 1}/${files.length}: ${file.name} — ${pct}%`;
      });
      succeeded++;
    } catch (err) {
      failures.push(`${file.name}: ${err.message}`);
    }
  }

  uploadStatusEl.textContent =
    failures.length > 0
      ? `Uploaded ${succeeded}/${files.length}, ${failures.length} failed`
      : `Uploaded ${succeeded} item${succeeded > 1 ? "s" : ""} ✓`;
  if (failures.length > 0) {
    console.error("Upload failures:", failures);
  }

  await loadListing(currentBrowseItem, currentBrowsePath);

  uploadFilesInput.disabled = false;
  uploadFolderInput.disabled = false;
  uploadFilesInput.value = "";
  uploadFolderInput.value = "";
  setTimeout(() => {
    uploadStatusEl.textContent = "";
  }, 6000);
}

uploadFilesInput.addEventListener("change", (e) => uploadFiles(e.target.files));
uploadFolderInput.addEventListener("change", (e) => uploadFiles(e.target.files));

// -- drag-and-drop upload directly onto the page -----------------------------------------------------------
//
// Without this, dropping a file onto the page does whatever the
// browser's own default drag-drop behavior is (typically trying to
// navigate to/open the dropped file as a local file, which often
// surfaces as an unexpected "save file" prompt) — the drop never
// reaches this app at all, which also means it silently skips
// whatever PIN protection is configured, since no request was ever
// made to the server in the first place. preventDefault() on both
// dragover and drop is required to suppress that and handle the files
// ourselves instead.
const mainContentEl = document.getElementById("main-content");

mainContentEl.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (currentBrowseItem) {
    mainContentEl.classList.add("drag-over");
  }
});

mainContentEl.addEventListener("dragleave", (e) => {
  // Only clear the highlight when actually leaving main-content, not
  // when passing over a child element within it (dragleave fires for
  // both, since child elements bubble their own dragleave up too).
  if (!mainContentEl.contains(e.relatedTarget)) {
    mainContentEl.classList.remove("drag-over");
  }
});

mainContentEl.addEventListener("drop", (e) => {
  e.preventDefault();
  mainContentEl.classList.remove("drag-over");
  if (!currentBrowseItem) {
    // Same rule as the button-based upload bar: uploading only makes
    // sense inside an actual shared folder, not at the Home root.
    return;
  }
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    uploadFiles(e.dataTransfer.files);
  }
});


// -- folder upload, including genuinely empty subfolders -----------------------------------------------------------
//
// The plain <input webkitdirectory> approach above has a hard browser
// limitation: it only ever reports actual FILES with their relative
// path attached — an empty subfolder produces literally no entry at
// all, so there's no way to detect or upload one through it. Where
// available (Chromium-based browsers), the File System Access API's
// showDirectoryPicker() gives real directory handles that CAN be
// walked recursively and DO reveal empty subfolders, so we prefer it
// and fall back to the old input for browsers that don't support it
// (Firefox, Safari) — same file-upload behavior either way, the only
// difference is whether empty folders come along for the ride.

async function walkDirectoryHandle(dirHandle, relativePrefix, files, emptyFolders) {
  let hasEntries = false;
  for await (const [name, handle] of dirHandle.entries()) {
    hasEntries = true;
    const entryPath = relativePrefix ? `${relativePrefix}/${name}` : name;
    if (handle.kind === "file") {
      const file = await handle.getFile();
      files.push({ file, relativePath: entryPath });
    } else if (handle.kind === "directory") {
      await walkDirectoryHandle(handle, entryPath, files, emptyFolders);
    }
  }
  if (!hasEntries && relativePrefix) {
    emptyFolders.push(relativePrefix);
  }
}

async function createEmptyFolder(relativePath, item, path) {
  const form = new FormData();
  form.append("item", item);
  form.append("path", path);
  form.append("relative_path", relativePath);
  const res = await fetch("/api/upload/create-folder", { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Couldn't create folder "${relativePath}" (${res.status})`);
  }
}

async function uploadFolderViaPicker() {
  let dirHandle;
  try {
    dirHandle = await window.showDirectoryPicker();
  } catch (err) {
    return; // user cancelled the picker — not an error
  }

  const files = [];
  const emptyFolders = [];
  await walkDirectoryHandle(dirHandle, dirHandle.name, files, emptyFolders);

  if (files.length === 0 && emptyFolders.length === 0) {
    uploadStatusEl.textContent = "That folder is empty — nothing to upload.";
    setTimeout(() => { uploadStatusEl.textContent = ""; }, 6000);
    return;
  }

  uploadFilesInput.disabled = true;
  uploadFolderInput.disabled = true;

  let succeeded = 0;
  const failures = [];

  // Empty folders first — if a file later needs one of these as its
  // parent directory, the upload endpoint already creates parent dirs
  // itself, so order between the two groups doesn't actually matter
  // for correctness, just for a sensible-looking progress readout.
  for (let i = 0; i < emptyFolders.length; i++) {
    const relativePath = emptyFolders[i];
    try {
      uploadStatusEl.textContent = `Creating empty folder ${i + 1}/${emptyFolders.length}: ${relativePath}`;
      await createEmptyFolder(relativePath, currentBrowseItem, currentBrowsePath);
      succeeded++;
    } catch (err) {
      failures.push(`${relativePath}: ${err.message}`);
    }
  }

  for (let i = 0; i < files.length; i++) {
    const { file, relativePath } = files[i];
    try {
      await uploadFileResumable(file, relativePath, currentBrowseItem, currentBrowsePath, (sent, total) => {
        const pct = total > 0 ? Math.round((sent / total) * 100) : 0;
        uploadStatusEl.textContent = `Uploading ${i + 1}/${files.length}: ${file.name} — ${pct}%`;
      });
      succeeded++;
    } catch (err) {
      failures.push(`${file.name}: ${err.message}`);
    }
  }

  const totalItems = files.length + emptyFolders.length;
  uploadStatusEl.textContent =
    failures.length > 0
      ? `Uploaded ${succeeded}/${totalItems}, ${failures.length} failed`
      : `Uploaded ${succeeded} item${succeeded > 1 ? "s" : ""} ✓`;
  if (failures.length > 0) {
    console.error("Upload failures:", failures);
  }

  await loadListing(currentBrowseItem, currentBrowsePath);

  uploadFilesInput.disabled = false;
  uploadFolderInput.disabled = false;
}

const uploadFolderLabel = document.getElementById("upload-folder-label");
if (window.showDirectoryPicker) {
  uploadFolderLabel.addEventListener("click", (e) => {
    e.preventDefault(); // skip the plain <input webkitdirectory> picker — use the richer API instead
    uploadFolderViaPicker();
  });
}
// If showDirectoryPicker isn't available, no listener is added here,
// and clicking the label falls through to its native behavior —
// opening the hidden <input webkitdirectory> exactly as before.

// -- hover previews -----------------------------------------------------------

const previewPanelEl = document.getElementById("preview-panel");
let previewHoverTimer = null;
let previewRequestToken = 0; // invalidates stale async responses if the user moves on quickly

function positionPreviewNear(mouseEvent) {
  const OFFSET = 16;
  const panelRect = previewPanelEl.getBoundingClientRect();
  let left = mouseEvent.clientX + OFFSET;
  let top = mouseEvent.clientY + OFFSET;

  // keep the panel on-screen — flip to the other side of the cursor if it'd overflow
  if (left + panelRect.width > window.innerWidth) {
    left = mouseEvent.clientX - panelRect.width - OFFSET;
  }
  if (top + panelRect.height > window.innerHeight) {
    top = mouseEvent.clientY - panelRect.height - OFFSET;
  }
  previewPanelEl.style.left = `${Math.max(8, left)}px`;
  previewPanelEl.style.top = `${Math.max(8, top)}px`;
}

function hidePreview() {
  clearTimeout(previewHoverTimer);
  previewRequestToken++; // any in-flight fetch for the old hover becomes stale
  previewPanelEl.classList.add("hidden");
  previewPanelEl.innerHTML = "";
}

function schedulePreview(row, ref, entry, mouseEvent) {
  clearTimeout(previewHoverTimer);
  const myToken = ++previewRequestToken;
  const pos = { x: mouseEvent.clientX, y: mouseEvent.clientY };
  // small delay so quickly scanning down a list doesn't fire a preview
  // fetch for every row you happen to pass over
  previewHoverTimer = setTimeout(() => showPreview(ref, entry, pos, myToken), 250);
}

async function showPreview(ref, entry, pos, myToken) {
  previewPanelEl.innerHTML = '<div class="preview-empty">Loading…</div>';
  previewPanelEl.classList.remove("hidden");
  positionPreviewNear({ clientX: pos.x, clientY: pos.y });

  try {
    if (entry.is_dir) {
      await renderFolderPreview(ref, myToken);
    } else {
      await renderFilePreview(ref, entry, myToken);
    }
  } catch (err) {
    if (myToken !== previewRequestToken) return;
    previewPanelEl.innerHTML = `<div class="preview-empty">Preview unavailable</div>`;
  }
}

async function renderFolderPreview(ref, myToken) {
  const params = new URLSearchParams();
  params.set("item", ref.item);
  params.set("path", ref.path);
  params.set("limit", "8");
  const res = await fetch(`/api/browse?${params.toString()}`);
  if (myToken !== previewRequestToken) return; // user moved on before this resolved
  if (!res.ok) throw new Error("browse failed");
  const data = await res.json();

  if (data.entries.length === 0) {
    previewPanelEl.innerHTML = '<div class="preview-empty">Empty folder</div>';
    return;
  }

  const list = document.createElement("ul");
  list.className = "preview-folder-list";
  for (const e of data.entries) {
    const li = document.createElement("li");
    const icon = document.createElement("span");
    icon.textContent = e.is_dir ? "📁" : "📄";
    const name = document.createElement("span");
    name.textContent = e.name;
    li.appendChild(icon);
    li.appendChild(name);
    list.appendChild(li);
  }
  previewPanelEl.innerHTML = "";
  previewPanelEl.appendChild(list);

  if (data.truncated) {
    const more = document.createElement("div");
    more.className = "preview-caption";
    more.textContent = `+${data.total - data.entries.length} more`;
    previewPanelEl.appendChild(more);
  }
}

async function renderFilePreview(ref, entry, myToken) {
  const infoParams = new URLSearchParams();
  infoParams.set("item", ref.item);
  infoParams.set("path", ref.path);
  const infoRes = await fetch(`/api/preview-info?${infoParams.toString()}`);
  if (myToken !== previewRequestToken) return;
  if (!infoRes.ok) throw new Error("preview-info failed");
  const info = await infoRes.json();

  const mediaUrl = `/preview?${infoParams.toString()}`;
  previewPanelEl.innerHTML = "";

  if (info.kind === "image") {
    const img = document.createElement("img");
    img.src = mediaUrl;
    previewPanelEl.appendChild(img);
  } else if (info.kind === "video") {
    const video = document.createElement("video");
    video.src = mediaUrl;
    video.muted = true;
    video.autoplay = true;
    video.loop = true;
    video.preload = "metadata";
    previewPanelEl.appendChild(video);
  } else if (info.kind === "text") {
    const textRes = await fetch(`/api/text-preview?${infoParams.toString()}`);
    if (myToken !== previewRequestToken) return;
    const textData = await textRes.json();
    const pre = document.createElement("div");
    pre.className = "preview-text";
    pre.textContent = textData.text + (textData.truncated ? "\n…" : "");
    previewPanelEl.appendChild(pre);
  } else {
    previewPanelEl.innerHTML = `<div class="preview-empty">${entry.name}<br>${formatSize(entry.size)}</div>`;
    return;
  }

  const caption = document.createElement("div");
  caption.className = "preview-caption";
  caption.textContent = `${entry.name} — ${formatSize(entry.size)}`;
  previewPanelEl.appendChild(caption);
}

window.addEventListener("popstate", () => {
  const { item, path } = getUrlParams();
  loadListing(item, path);
});

const initial = getUrlParams();
loadListing(initial.item, initial.path).finally(() => {
  if (typeof hideLoadingOverlay === "function") hideLoadingOverlay();
});

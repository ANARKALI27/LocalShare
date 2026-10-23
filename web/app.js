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

// -- fast bulk upload ------------------------------------------------------------------
//
// Uploading a big folder file-by-file with the resumable protocol costs
// three round trips PER FILE (start, chunk, finalize) and runs them one
// after another — for thousands of small files the per-request overhead
// dwarfs the actual data, which is why 10-15k files crawled. So:
//   * small files are packed into batches and sent many-per-request
//     through the plain /upload endpoint, with several batches in flight
//     at once;
//   * big files still use the chunked, resumable protocol (they're worth
//     the resume ability, and the overhead is negligible for them).
const SMALL_FILE_LIMIT = 8 * 1024 * 1024; // files up to 8 MB go in batches
const BATCH_MAX_FILES = 500;              // server accepts up to 1000 per batch
const BATCH_MAX_BYTES = 24 * 1024 * 1024; // keeps each request's memory/time bounded
const BATCH_CONCURRENCY = 6;              // batches in flight at once (browsers allow ~6 connections per host)

// Batches use a compact binary container (/api/upload/bulk) instead of
// multipart/form-data — multipart parsing on the server is the slow part
// for thousands of tiny files (measured ~11x faster). If an older server
// without that endpoint answers 404/405, this flips to false and batches
// fall back to the regular multipart /upload automatically.
let useBulkEndpoint = true;

function formatDuration(seconds) {
  if (!isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function packBatches(entries) {
  const batches = [];
  let current = [];
  let currentBytes = 0;
  for (const entry of entries) {
    if (
      current.length > 0 &&
      (current.length >= BATCH_MAX_FILES || currentBytes + entry.file.size > BATCH_MAX_BYTES)
    ) {
      batches.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(entry);
    currentBytes += entry.file.size;
  }
  if (current.length > 0) batches.push(current);
  return batches;
}

function buildBulkBody(batch) {
  // [4-byte big-endian header length][JSON header][file bytes, in order]
  const header = new TextEncoder().encode(
    JSON.stringify({ files: batch.map((e) => ({ p: e.relativePath, s: e.file.size })) })
  );
  const lenBytes = new Uint8Array(4);
  new DataView(lenBytes.buffer).setUint32(0, header.length, false);
  // A Blob just references the File objects — nothing is copied into
  // memory until the browser streams it out.
  return new Blob([lenBytes, header, ...batch.map((e) => e.file)]);
}

async function sendBatchOnce(batch, item, path) {
  if (useBulkEndpoint) {
    const params = new URLSearchParams({ item, path });
    const res = await fetch(`/api/upload/bulk?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: buildBulkBody(batch),
    });
    if (res.status !== 404 && res.status !== 405) return res;
    useBulkEndpoint = false; // older server — use multipart from now on
  }
  const form = new FormData();
  form.append("item", item);
  form.append("path", path);
  form.append("relative_paths", JSON.stringify(batch.map((e) => e.relativePath)));
  for (const e of batch) form.append("files", e.file, e.file.name);
  return fetch("/upload", { method: "POST", body: form });
}

async function uploadBatch(batch, item, path) {

  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await sendBatchOnce(batch, item, path);
      if (res.ok) return await res.json();
      if (res.status >= 400 && res.status < 500) {
        const body = await res.json().catch(() => ({}));
        throw Object.assign(new Error(body.detail || `Upload failed (${res.status})`), { fatal: true });
      }
      lastError = new Error(`Server error (${res.status})`);
    } catch (err) {
      if (err.fatal) throw err;
      lastError = err; // network drop — worth another try
    }
    await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
  }
  throw lastError || new Error("Upload failed");
}

/**
 * Shared by every way of starting an upload (file picker, folder
 * picker, drag-and-drop). entries = [{ file, relativePath }].
 */
async function uploadMany(entries, emptyFolders = []) {
  const item = currentBrowseItem;
  const path = currentBrowsePath;
  const totalItems = entries.length + emptyFolders.length;
  if (totalItems === 0) return;

  uploadFilesInput.disabled = true;
  uploadFolderInput.disabled = true;

  const failures = [];
  let succeeded = 0;
  let doneFiles = 0;
  let doneBytes = 0;
  let inFlightLargeBytes = 0;
  const totalFiles = entries.length;
  const totalBytes = entries.reduce((n, e) => n + e.file.size, 0);
  const startedAt = performance.now();
  let lastPaint = 0;

  function paint(force = false) {
    const now = performance.now();
    if (!force && now - lastPaint < 150) return; // don't thrash the DOM on every tiny file
    lastPaint = now;
    const bytes = doneBytes + inFlightLargeBytes;
    const elapsed = (now - startedAt) / 1000;
    const speed = elapsed > 0.5 ? bytes / elapsed : 0;
    const remaining = speed > 0 ? (totalBytes - bytes) / speed : NaN;
    let text = `Uploading ${doneFiles.toLocaleString()}/${totalFiles.toLocaleString()} files · ` +
      `${formatSize(bytes)} / ${formatSize(totalBytes)}`;
    if (speed > 0) text += ` · ${formatSize(speed)}/s`;
    const eta = formatDuration(remaining);
    if (eta && doneFiles < totalFiles) text += ` · ~${eta} left`;
    uploadStatusEl.textContent = text;
  }

  // Empty folders first (a handful of tiny requests).
  for (let i = 0; i < emptyFolders.length; i++) {
    try {
      uploadStatusEl.textContent = `Creating empty folder ${i + 1}/${emptyFolders.length}: ${emptyFolders[i]}`;
      await createEmptyFolder(emptyFolders[i], item, path);
      succeeded++;
    } catch (err) {
      failures.push(`${emptyFolders[i]}: ${err.message}`);
    }
  }

  const small = entries.filter((e) => e.file.size <= SMALL_FILE_LIMIT);
  const large = entries.filter((e) => e.file.size > SMALL_FILE_LIMIT);

  // Small files: batched, several batches at once.
  const batches = packBatches(small);
  let nextBatch = 0;
  async function batchWorker() {
    while (nextBatch < batches.length) {
      const batch = batches[nextBatch++];
      try {
        const data = await uploadBatch(batch, item, path);
        (data.results || []).forEach((r, idx) => {
          if (r.ok) {
            succeeded++;
          } else {
            failures.push(`${r.name || (batch[idx] && batch[idx].relativePath)}: ${r.error || "failed"}`);
          }
        });
      } catch (err) {
        for (const e of batch) failures.push(`${e.relativePath}: ${err.message}`);
      }
      doneFiles += batch.length;
      doneBytes += batch.reduce((n, e) => n + e.file.size, 0);
      paint();
    }
  }
  // Large files: chunked + resumable, one after another (each already
  // uses several chunks in flight). Runs ALONGSIDE the small-file
  // batches instead of after them, so one big file at the end of a
  // folder doesn't sit idle waiting for thousands of small ones.
  async function largeWorker() {
    for (const { file, relativePath } of large) {
      try {
        await uploadFileResumable(file, relativePath, item, path, (sent) => {
          inFlightLargeBytes += sent - (largeProgress.get(file) || 0);
          largeProgress.set(file, sent);
          paint();
        });
        succeeded++;
      } catch (err) {
        failures.push(`${file.name}: ${err.message}`);
      }
      inFlightLargeBytes -= largeProgress.get(file) || 0;
      largeProgress.delete(file);
      doneFiles++;
      doneBytes += file.size;
      paint(true);
    }
  }
  const largeProgress = new Map();

  await Promise.all([
    ...Array.from({ length: Math.min(BATCH_CONCURRENCY, Math.max(batches.length, 1)) }, () => batchWorker()),
    largeWorker(),
  ]);

  uploadStatusEl.textContent =
    failures.length > 0
      ? `Uploaded ${succeeded.toLocaleString()}/${totalItems.toLocaleString()}, ${failures.length.toLocaleString()} failed`
      : `Uploaded ${succeeded.toLocaleString()} item${succeeded > 1 ? "s" : ""} ✓`;
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

async function uploadFiles(fileList) {
  const files = Array.from(fileList);
  if (files.length === 0) return;
  await uploadMany(files.map((file) => ({ file, relativePath: file.webkitRelativePath || file.name })));
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
  if (!e.dataTransfer) return;

  const items = e.dataTransfer.items;
  const canReadEntries = items && items.length > 0 &&
    typeof items[0].webkitGetAsEntry === "function";

  if (!canReadEntries) {
    // Fallback for browsers without the entries API — this is what
    // the drop handler always did before: a flat file list, which
    // works fine for plain file drops but can't see into a dropped
    // folder's contents at all.
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
    return;
  }

  // Multiple items — files, folders, or a mix — can be dropped at
  // once. Each top-level item becomes its own entry (a FileSystemEntry:
  // either a file entry directly, or a directory entry that needs
  // recursing into), and every entry is walked in parallel; the actual
  // upload only starts once every one of them has finished collecting
  // its files, so nothing is lost from folders that take longer to
  // read than others.
  const topLevelEntries = [];
  for (const item of items) {
    const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
    if (entry) topLevelEntries.push(entry);
  }

  Promise.all(topLevelEntries.map((entry) => collectFilesFromEntry(entry, ""))).then(
    (groups) => {
      const allFiles = groups.flat();
      if (allFiles.length > 0) {
        uploadFiles(allFiles);
      }
    }
  );
});

// Recursively collects every file within a dropped entry (a single
// file, or a folder — possibly nested arbitrarily deep) into a flat
// array of real File objects, each tagged with webkitRelativePath so
// the existing uploadFiles() pipeline (built for the "Upload Folder"
// button's <input webkitdirectory>, which already relies on that same
// property) handles a dropped folder identically to a picked one,
// without needing its own separate code path.
function collectFilesFromEntry(entry, pathPrefix) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        const relativePath = pathPrefix + file.name;
        // webkitRelativePath is normally read-only and only ever set
        // by the browser itself for an <input webkitdirectory> pick —
        // for a File constructed via the entries API here, it's just
        // an ordinary empty string, and defineProperty is the standard,
        // widely-used way to attach the same path info uploadFiles()
        // already expects to find there.
        Object.defineProperty(file, "webkitRelativePath", {
          value: relativePath,
          configurable: true,
        });
        resolve([file]);
      });
    } else if (entry.isDirectory) {
      readAllDirectoryEntries(entry.createReader()).then((entries) => {
        Promise.all(
          entries.map((childEntry) =>
            collectFilesFromEntry(childEntry, pathPrefix + entry.name + "/")
          )
        ).then((groups) => resolve(groups.flat()));
      });
    } else {
      resolve([]);
    }
  });
}

// FileSystemDirectoryReader.readEntries() only returns entries in
// batches (the exact batch size is left up to the browser, but it is
// NOT guaranteed to return everything in one call) — the documented,
// correct way to read a full directory is to keep calling it until it
// resolves with an empty array. Skipping this and calling it only
// once — an easy mistake, since it looks like it should just return
// everything — silently truncates any folder large enough to need
// more than one batch.
function readAllDirectoryEntries(reader) {
  let allEntries = [];
  function readBatch() {
    return new Promise((resolve) => {
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(allEntries);
        } else {
          allEntries = allEntries.concat(batch);
          resolve(readBatch());
        }
      });
    });
  }
  return readBatch();
}


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
  // getFile() on thousands of files one-at-a-time is slow, so each
  // directory's files are resolved in parallel (in modest groups).
  const fileJobs = [];
  const subdirs = [];
  let hasEntries = false;
  for await (const [name, handle] of dirHandle.entries()) {
    hasEntries = true;
    const entryPath = relativePrefix ? `${relativePrefix}/${name}` : name;
    if (handle.kind === "file") {
      fileJobs.push({ handle, entryPath });
    } else if (handle.kind === "directory") {
      subdirs.push({ handle, entryPath });
    }
  }
  const GROUP = 64;
  for (let i = 0; i < fileJobs.length; i += GROUP) {
    const group = fileJobs.slice(i, i + GROUP);
    const resolved = await Promise.all(group.map((j) => j.handle.getFile()));
    resolved.forEach((file, idx) => files.push({ file, relativePath: group[idx].entryPath }));
  }
  for (const { handle, entryPath } of subdirs) {
    await walkDirectoryHandle(handle, entryPath, files, emptyFolders);
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

  await uploadMany(files, emptyFolders);
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
    // Built with textContent, not innerHTML: file names are untrusted
    // (a name like <img onerror=...> must show as text, never run).
    const empty = document.createElement("div");
    empty.className = "preview-empty";
    empty.appendChild(document.createTextNode(entry.name));
    empty.appendChild(document.createElement("br"));
    empty.appendChild(document.createTextNode(formatSize(entry.size)));
    previewPanelEl.appendChild(empty);
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

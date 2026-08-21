"""
FastAPI route definitions.

Phase 4: browser-facing file listing UI and streaming downloads.
Phase 5: uploads (single files and whole folders, streamed to disk).
Phase 6: WebDAV (separate server, see webdav_server.py).
Post-Phase-6 additions: Range-request support (needed for smooth video
preview seeking), hover previews (inline file preview + folder peek +
text snippets), and a private messaging section with image/video
attachments.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app.server.messages import MessageStore, Attachment
from app.server.security import PathSecurityError, safe_join
from app.state import ShareManager
from app.transfer.download import (
    cleanup_temp_file,
    create_zip_archive,
    parse_range_header,
    stream_file,
    stream_file_range,
)
from app.transfer.resumable import ResumableUploadManager
from app.transfer.upload import resolve_upload_path, save_upload
from app.utils.filesystem import list_directory

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web")

# Extensions we'll actually try to render as image/video previews. Anything
# else just shows an icon + size in the hover card — no point trying to
# preview a .exe or .zip inline.
PREVIEWABLE_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
PREVIEWABLE_VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}
PREVIEWABLE_TEXT_EXT = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv",
    ".log", ".ini", ".cfg", ".html", ".css", ".xml", ".sh", ".bat",
}
TEXT_PREVIEW_BYTES = 2000


def _split_path(path: str) -> list[str]:
    """Split a URL-style '/'-separated relative path into segments, dropping empties."""
    return [p for p in path.split("/") if p not in ("", ".")]


def _resolve_target(share_manager: ShareManager, item_id: str, rel_path: str) -> tuple[str, str]:
    """
    Resolve (item_id, rel_path) to an absolute filesystem path, going
    through safe_join so traversal attempts are rejected. Returns
    (absolute_path, display_name).
    """
    item = share_manager.get(item_id)
    if item is None or not item.exists:
        raise HTTPException(status_code=404, detail="Shared item not found")

    segments = _split_path(rel_path)
    if not segments:
        return item.path, item.name

    if not item.is_dir:
        raise HTTPException(status_code=400, detail="This shared item is a file, not a folder")

    try:
        target = safe_join(item.path, *segments)
    except PathSecurityError:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="File or folder not found")

    return target, segments[-1]


def _file_stream_response(request: Request, target: str, name: str, inline: bool) -> StreamingResponse:
    """
    Shared logic for /download and /preview: serves a file either as an
    attachment (forces download) or inline (browser renders it), with
    HTTP Range support in both cases — Range is what lets a <video> tag
    seek/scrub smoothly instead of re-downloading from the start, and
    lets download managers resume.
    """
    try:
        size = os.path.getsize(target)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found")

    media_type, _ = mimetypes.guess_type(name)
    media_type = media_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"

    range_header = request.headers.get("range")
    byte_range = parse_range_header(range_header, size)

    headers = {
        "Content-Disposition": f'{disposition}; filename="{name}"',
        "Accept-Ranges": "bytes",
    }

    if byte_range is not None:
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            stream_file_range(target, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers["Content-Length"] = str(size)
    return StreamingResponse(stream_file(target), media_type=media_type, headers=headers)


def build_router(
    share_manager: ShareManager, message_store: MessageStore, resumable_manager: ResumableUploadManager
) -> APIRouter:
    router = APIRouter()

    # -- browser UI shell -----------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with open(os.path.join(WEB_DIR, "index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @router.get("/messages", response_class=HTMLResponse)
    def messages_page() -> HTMLResponse:
        with open(os.path.join(WEB_DIR, "messages.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @router.get("/api/status")
    def status() -> dict:
        return {"app": "LocalShare", "status": "running", "shared_item_count": len(share_manager)}

    @router.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    # -- directory listing -----------------------------------------------------------
    @router.get("/api/browse")
    def browse(
        item: str = Query(default=""),
        path: str = Query(default=""),
        limit: int = Query(default=0, ge=0, le=200),
    ) -> dict:
        # No item selected: show the top-level shared items as the root listing.
        if not item:
            all_entries = [
                {
                    "id": i.id,
                    "name": i.name,
                    "is_dir": i.is_dir,
                    "size": 0 if i.is_dir else i.size_bytes(),
                }
                for i in share_manager.all_items()
                if i.exists
            ]
            entries = all_entries[:limit] if limit else all_entries
            return {
                "breadcrumbs": [{"name": "Home", "item": "", "path": ""}],
                "entries": entries,
                "total": len(all_entries),
                "truncated": limit > 0 and len(all_entries) > limit,
            }

        shared_item = share_manager.get(item)
        if shared_item is None or not shared_item.exists:
            raise HTTPException(status_code=404, detail="Shared item not found")

        target, _name = _resolve_target(share_manager, item, path)
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Not a folder")

        all_entries = [
            {"name": e.name, "is_dir": e.is_dir, "size": e.size} for e in list_directory(target)
        ]
        entries = all_entries[:limit] if limit else all_entries

        # Build breadcrumbs: Home / <shared item name> / <subfolders...>
        breadcrumbs = [{"name": "Home", "item": "", "path": ""}]
        segments = _split_path(path)
        accumulated = ""
        breadcrumbs.append({"name": shared_item.name, "item": item, "path": ""})
        for seg in segments:
            accumulated = f"{accumulated}/{seg}" if accumulated else seg
            breadcrumbs.append({"name": seg, "item": item, "path": accumulated})

        return {
            "breadcrumbs": breadcrumbs,
            "entries": entries,
            "total": len(all_entries),
            "truncated": limit > 0 and len(all_entries) > limit,
        }

    # -- hover previews -----------------------------------------------------------
    @router.get("/api/preview-info")
    def preview_info(item: str = Query(...), path: str = Query(default="")) -> dict:
        """
        Tells the frontend HOW to preview something, without sending the
        content itself: image/video (render inline via /preview), text
        (fetch a snippet via /api/text-preview), or "none" (just show an
        icon — e.g. for .exe, .zip, unknown types).
        """
        target, name = _resolve_target(share_manager, item, path)
        if os.path.isdir(target):
            return {"kind": "folder"}

        ext = os.path.splitext(name)[1].lower()
        if ext in PREVIEWABLE_IMAGE_EXT:
            kind = "image"
        elif ext in PREVIEWABLE_VIDEO_EXT:
            kind = "video"
        elif ext in PREVIEWABLE_TEXT_EXT:
            kind = "text"
        else:
            kind = "none"

        try:
            size = os.path.getsize(target)
        except OSError:
            size = 0

        return {"kind": kind, "size": size}

    @router.get("/api/text-preview")
    def text_preview(item: str = Query(...), path: str = Query(default="")) -> dict:
        target, _name = _resolve_target(share_manager, item, path)
        if os.path.isdir(target):
            raise HTTPException(status_code=400, detail="This is a folder")

        try:
            with open(target, "rb") as f:
                raw = f.read(TEXT_PREVIEW_BYTES + 1)
        except OSError:
            raise HTTPException(status_code=404, detail="File not found")

        truncated = len(raw) > TEXT_PREVIEW_BYTES
        text = raw[:TEXT_PREVIEW_BYTES].decode("utf-8", errors="replace")
        return {"text": text, "truncated": truncated}

    @router.get("/preview")
    def preview(request: Request, item: str = Query(...), path: str = Query(default="")) -> StreamingResponse:
        target, name = _resolve_target(share_manager, item, path)
        if os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Can't preview a folder as a file")
        return _file_stream_response(request, target, name, inline=True)

    # -- downloads -----------------------------------------------------------
    @router.get("/download")
    def download(request: Request, item: str = Query(...), path: str = Query(default="")) -> StreamingResponse:
        target, name = _resolve_target(share_manager, item, path)
        if os.path.isdir(target):
            raise HTTPException(
                status_code=400, detail="This is a folder — use /download-zip instead"
            )
        return _file_stream_response(request, target, name, inline=False)

    @router.get("/download-zip")
    def download_zip(item: str = Query(...), path: str = Query(default="")) -> StreamingResponse:
        target, name = _resolve_target(share_manager, item, path)
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="This is a file — use /download instead")

        zip_path = create_zip_archive(target)
        zip_size = os.path.getsize(zip_path)

        headers = {
            "Content-Disposition": f'attachment; filename="{name}.zip"',
            "Content-Length": str(zip_size),
        }
        return StreamingResponse(
            stream_file(zip_path),
            media_type="application/zip",
            headers=headers,
            background=BackgroundTask(cleanup_temp_file, zip_path),
        )

    router.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    # -- uploads -----------------------------------------------------------
    @router.post("/upload")
    async def upload(
        item: str = Form(...),
        path: str = Form(default=""),
        relative_paths: str = Form(default="[]"),
        files: list[UploadFile] = File(...),
    ) -> dict:
        if not item:
            raise HTTPException(
                status_code=400, detail="Choose a shared folder before uploading — can't upload to Home"
            )

        target_dir, _name = _resolve_target(share_manager, item, path)
        if not os.path.isdir(target_dir):
            raise HTTPException(status_code=400, detail="Upload destination must be a folder")

        try:
            rel_path_list = json.loads(relative_paths)
        except (json.JSONDecodeError, TypeError):
            rel_path_list = []

        results = []
        for idx, upload_file in enumerate(files):
            # Prefer the client-supplied relative path (used for folder
            # uploads, so nested structure is preserved); fall back to the
            # plain filename for single-file uploads.
            rel_path = (
                rel_path_list[idx]
                if idx < len(rel_path_list) and rel_path_list[idx]
                else upload_file.filename or "unnamed"
            )
            try:
                destination = resolve_upload_path(target_dir, rel_path)
            except PathSecurityError:
                results.append({"name": rel_path, "ok": False, "error": "invalid path"})
                continue

            try:
                actual_path, bytes_written = await save_upload(upload_file, destination)
                results.append(
                    {"name": os.path.basename(actual_path), "ok": True, "bytes": bytes_written}
                )
            except OSError as exc:
                # disk full, permission denied, path too long, etc. — report
                # per-file rather than failing the whole batch
                results.append({"name": rel_path, "ok": False, "error": str(exc)})

        failed = [r for r in results if not r["ok"]]
        return {
            "uploaded": len([r for r in results if r["ok"]]),
            "failed": len(failed),
            "results": results,
        }

    # -- resumable uploads (for large files — see resumable.py) -----------------
    @router.post("/api/upload/start")
    def start_resumable_upload(
        item: str = Form(...),
        path: str = Form(default=""),
        filename: str = Form(...),
        relative_path: str = Form(default=""),
        total_size: int = Form(...),
    ) -> dict:
        if not item:
            raise HTTPException(
                status_code=400, detail="Choose a shared folder before uploading — can't upload to Home"
            )
        target_dir, _name = _resolve_target(share_manager, item, path)
        if not os.path.isdir(target_dir):
            raise HTTPException(status_code=400, detail="Upload destination must be a folder")
        if total_size < 0:
            raise HTTPException(status_code=400, detail="Invalid total_size")

        session = resumable_manager.start_session(
            item, target_dir, relative_path or filename, total_size
        )
        return {"upload_id": session.id, "bytes_received": 0, "total_size": total_size}

    @router.get("/api/upload/status/{upload_id}")
    def resumable_upload_status(upload_id: str) -> dict:
        session = resumable_manager.get(upload_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown or expired upload session")
        return {
            "bytes_received": session.bytes_received,
            "total_size": session.total_size,
            "finalized": session.finalized,
        }

    @router.put("/api/upload/chunk/{upload_id}")
    async def upload_chunk(upload_id: str, request: Request, offset: int = Query(...)) -> dict:
        data = await request.body()
        try:
            session = resumable_manager.write_chunk(upload_id, offset, data)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown or expired upload session")
        except ValueError as exc:
            # 409 Conflict: the client's idea of progress doesn't match the
            # server's — it should re-check /status and retry from there,
            # not treat this as a fatal error.
            raise HTTPException(status_code=409, detail=str(exc))
        return {"bytes_received": session.bytes_received}

    @router.post("/api/upload/finalize/{upload_id}")
    def finalize_resumable_upload(upload_id: str) -> dict:
        try:
            final_path = resumable_manager.finalize(upload_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown or expired upload session")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "name": os.path.basename(final_path)}

    @router.delete("/api/upload/{upload_id}")
    def cancel_resumable_upload(upload_id: str) -> dict:
        resumable_manager.cancel(upload_id)
        return {"ok": True}

    # -- private messages -----------------------------------------------------------
    @router.get("/api/messages")
    def get_messages(since: int = Query(default=0, ge=0)) -> dict:
        msgs = message_store.list_since(since)
        return {
            "latest_id": message_store.latest_id(),
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "text": m.text,
                    "timestamp": m.timestamp,
                    "attachments": [
                        {
                            "filename": a.filename,
                            "size": a.size,
                            "mime_type": a.mime_type,
                            "url": f"/messages/attachment/{m.id}/{a.filename}",
                        }
                        for a in m.attachments
                    ],
                }
                for m in msgs
            ],
        }

    @router.post("/api/messages")
    async def post_message(
        sender: str = Form(default="Anonymous"),
        text: str = Form(default=""),
        files: list[UploadFile] = File(default=[]),
    ) -> JSONResponse:
        if not text.strip() and not files:
            raise HTTPException(status_code=400, detail="Message needs text or an attachment")

        msg = message_store.add_message(sender, text)

        for uf in files:
            if not uf.filename:
                continue
            dest = message_store.attachment_dest_path(msg.id, uf.filename)
            try:
                actual_path, bytes_written = await save_upload(uf, dest)
            except OSError:
                continue  # skip a failed attachment rather than failing the whole message
            mime_type, _ = mimetypes.guess_type(actual_path)
            msg.attachments.append(
                Attachment(
                    id=os.path.basename(actual_path),
                    filename=os.path.basename(actual_path),
                    size=bytes_written,
                    mime_type=mime_type or "application/octet-stream",
                )
            )

        return JSONResponse(
            {
                "id": msg.id,
                "sender": msg.sender,
                "text": msg.text,
                "timestamp": msg.timestamp,
                "attachments": [
                    {
                        "filename": a.filename,
                        "size": a.size,
                        "mime_type": a.mime_type,
                        "url": f"/messages/attachment/{msg.id}/{a.filename}",
                    }
                    for a in msg.attachments
                ],
            }
        )

    @router.get("/messages/attachment/{message_id}/{filename}")
    def get_attachment(request: Request, message_id: int, filename: str) -> StreamingResponse:
        path = message_store.attachment_source_path(message_id, filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        return _file_stream_response(request, path, os.path.basename(path), inline=True)

    return router

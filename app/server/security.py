"""
Path safety helpers.

Every route that turns a URL path into a filesystem path MUST go
through `safe_join`. This is the one place path-traversal protection
lives, so it can't be forgotten in some route and not another.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote, urlparse

# Matches a Windows drive letter ("C:", "C:\", "C:/") or a leading
# path separator — checked explicitly (not just via os.path.isabs)
# because isabs()'s behavior depends on the OS Python is running on,
# and this app's target platform (Windows) must always be caught even
# if a route handler runs through this on a different platform in dev/tests.
_ABS_PATH_PATTERN = re.compile(r"^([a-zA-Z]:[\\/]?|[\\/])")


class PathSecurityError(Exception):
    """Raised when a requested path would escape its shared root."""


def safe_join(root: str, *relative_parts: str) -> str:
    """
    Join `root` with untrusted relative path segments (e.g. from a URL),
    and guarantee the result is still inside `root`.

    Blocks:
      - "../../" traversal
      - absolute paths in a segment (e.g. "C:\\Windows")
      - null bytes
      - resolved symlink escapes

    Raises PathSecurityError if the result would land outside `root`.
    """
    root_real = os.path.realpath(root)

    candidate = root
    for part in relative_parts:
        if part is None:
            continue
        if "\x00" in part:
            raise PathSecurityError("null byte in path")
        # os.path.join ignores everything before an absolute segment,
        # which would let "C:\Windows" hijack the join — reject it outright.
        # Checked both ways: os.path.isabs (correct for whatever OS we're
        # actually running on) and the explicit pattern (correct for
        # Windows specifically, regardless of dev/test platform).
        if os.path.isabs(part) or _ABS_PATH_PATTERN.match(part):
            raise PathSecurityError(f"absolute path segment not allowed: {part!r}")
        candidate = os.path.join(candidate, part)

    candidate_real = os.path.realpath(candidate)

    # realpath resolves symlinks too, so a shared folder containing a
    # symlink pointing outside itself is also caught here.
    if candidate_real != root_real and not candidate_real.startswith(root_real + os.sep):
        raise PathSecurityError(f"path escapes shared root: {candidate!r}")

    return candidate_real


# Names Windows treats as devices, with or without an extension
# ("CON", "nul.txt", "COM1.log"). Writing to one of these on Windows
# doesn't create a file — it talks to a device — so an uploader could
# use it to hang or confuse the server. They're renamed on every
# platform so behavior is identical everywhere.
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}
MAX_FILENAME_LENGTH = 200


def sanitize_filename(name: str) -> str:
    """
    Strip characters that are invalid or dangerous in Windows filenames,
    for names arriving from uploads. Removes path separators, control
    characters and reserved characters, neutralizes Windows device
    names, and caps the length.
    """
    name = name.replace("\x00", "")
    name = os.path.basename(name.replace("\\", "/"))  # drop any directory component entirely
    name = "".join(ch for ch in name if ord(ch) >= 32 and ord(ch) != 127)
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "_")
    name = name.strip(" .")  # Windows disallows trailing dots/spaces
    if not name:
        return "unnamed"
    # Windows treats everything before the FIRST dot as the device name
    # ("aux.tar.gz" is still AUX).
    if name.split(".", 1)[0].strip(" ").upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    if len(name) > MAX_FILENAME_LENGTH:
        stem, ext = os.path.splitext(name)
        name = stem[: MAX_FILENAME_LENGTH - len(ext)] + ext
    return name


def content_disposition(disposition: str, filename: str) -> str:
    """
    Build a Content-Disposition header value that can't be broken out
    of by quotes, semicolons or line breaks in the file name. Gives an
    ASCII-only fallback plus the RFC 5987 `filename*` form (which
    browsers prefer) for the real, possibly non-ASCII name.
    """
    fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '"\\;%' else "_" for ch in filename
    ) or "file"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8\'\'{quote(filename, safe='')}"


# Types a browser would happily RUN if it were opened inline from our
# origin (script inside an uploaded .html or .svg). Those are served
# with a sandboxing Content-Security-Policy so they can render but can
# never execute script or touch the share's session.
ACTIVE_CONTENT_EXTENSIONS = {
    ".html", ".htm", ".xhtml", ".xht", ".svg", ".svgz", ".xml", ".xsl", ".xslt", ".js", ".mjs",
}


def is_active_content(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in ACTIVE_CONTENT_EXTENSIONS


def safe_redirect_path(target: str | None) -> str:
    """
    Accepts only a same-site absolute PATH ("/", "/messages?x=1") for
    post-login redirects. Anything else — "https://evil.com",
    "//evil.com", "/\\evil.com", control characters — falls back to "/",
    so the login form can't be turned into an open redirect.
    """
    if not target or not target.startswith("/"):
        return "/"
    if target.startswith("//") or "\\" in target:
        return "/"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
        return "/"
    if urlparse(target).netloc:
        return "/"
    return target


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",  # ?token= links must not leak via Referer
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def origin_allowed(method: str, headers) -> bool:
    """
    CSRF / DNS-rebinding guard for state-changing requests. A request
    that carries an Origin header must come from this same host — so a
    random web page the user happens to have open can't silently POST
    uploads/messages/cancels to a LocalShare running on the LAN. Requests
    with no Origin (curl, WebDAV clients, same-origin navigations in
    some browsers) are allowed; those aren't driven by a hostile page.
    """
    if method.upper() in SAFE_METHODS:
        return True
    if (headers.get("sec-fetch-site") or "").lower() == "cross-site":
        return False
    origin = headers.get("origin")
    if origin is None:
        return True
    host = (headers.get("host") or "").lower()
    if origin == "null" or not host:
        return False
    return urlparse(origin).netloc.lower() == host


def build_security_middleware_class():
    """Lazy starlette import, same reasoning as auth_middleware.build_auth_middleware_class."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class SecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if not origin_allowed(request.method, request.headers):
                return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
            response = await call_next(request)
            for key, value in SECURITY_HEADERS.items():
                response.headers.setdefault(key, value)
            return response

    return SecurityMiddleware

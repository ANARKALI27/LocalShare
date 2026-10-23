"""
Auth enforcement middleware.

When PIN protection is enabled, every request except a small,
deliberate allowlist must present a valid session cookie or a valid
?token= query param (the latter exists so a QR code / share link can
embed the token for one-tap access without retyping the PIN on a
phone). Everything else gets redirected to /login (for browser page
loads) or a 401 JSON response (for API/asset requests, where a
redirect would be confusing).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from app.server.auth import AccessControl

if TYPE_CHECKING:
    from starlette.requests import Request

# Exact-path exemptions: reachable even with PIN protection on.
EXEMPT_PATHS = {
    "/login",      # the PIN entry page itself — obviously can't require auth to reach it
    "/api/version",  # harmless metadata; lets the "Check for Updates" feature keep working
    "/ping",
}
# Prefix exemptions: needed so the login page itself can load its CSS/JS.
EXEMPT_PREFIXES = ("/static/",)

COOKIE_NAME = "ls_auth"


def client_key(request: "Request") -> str:
    """
    Who is this client, for rate limiting? Normally the socket address.
    Through the Cloudflare tunnel every request arrives from 127.0.0.1,
    so for loopback connections only we trust the address cloudflared
    forwards in CF-Connecting-IP — a remote caller can't set that header
    on a direct connection to be believed, since direct connections
    are not loopback.
    """
    host = request.client.host if request.client else "unknown"
    if host in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("cf-connecting-ip")
        if forwarded:
            return forwarded.strip()[:64]
    return host


def is_secure_request(request: "Request") -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def build_auth_middleware_class():
    """
    Returns the AuthMiddleware class, importing starlette only when
    this is actually called (i.e. when the server is really starting) —
    keeps this module importable for testing is_exempt() and
    AccessControl's logic even in environments without fastapi/starlette
    installed.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse, RedirectResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, access_control: AccessControl) -> None:
            super().__init__(app)
            self.access_control = access_control

        async def dispatch(self, request: "Request", call_next):
            if not self.access_control.enabled:
                return await call_next(request)

            path = request.url.path
            if is_exempt(path):
                return await call_next(request)

            cookie_token = request.cookies.get(COOKIE_NAME)
            query_token = request.query_params.get("token")

            if self.access_control.is_authorized(cookie_token, query_token):
                response = await call_next(request)
                # If they got in via a ?token= link (QR code / shared URL)
                # rather than an existing cookie, plant the cookie now so
                # subsequent navigation on this device doesn't need the
                # token in every URL.
                if query_token and cookie_token != self.access_control.token:
                    response.set_cookie(
                        COOKIE_NAME, self.access_control.token, httponly=True, samesite="lax",
                        secure=is_secure_request(request),
                    )
                return response

            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                return RedirectResponse(url=f"/login?next={quote(path, safe='/')}")
            return JSONResponse({"detail": "PIN required"}, status_code=401)

    return AuthMiddleware

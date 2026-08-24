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
                        COOKIE_NAME, self.access_control.token, httponly=True, samesite="lax"
                    )
                return response

            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                return RedirectResponse(url=f"/login?next={path}")
            return JSONResponse({"detail": "PIN required"}, status_code=401)

    return AuthMiddleware

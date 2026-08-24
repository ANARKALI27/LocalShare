"""
Internet sharing via ngrok tunnel.

This is what makes "Local Network + Internet" mode reachable from
outside your Wi-Fi: ngrok opens an outbound connection from your
machine to ngrok's servers and hands back a public HTTPS URL that
forwards to your local server. No port forwarding or router
configuration needed — and since the connection is initiated
outbound from your machine, it works even behind NAT/CGNAT.

Requires a free ngrok account and an authtoken (https://ngrok.com) —
this is ngrok's own requirement, not something this app adds.
pyngrok manages downloading the actual ngrok binary itself on first
use (needs internet access, which internet-sharing mode already
assumes).

Honest limitation: ngrok's free tier shows a one-time interstitial
warning page to first-time visitors before they reach the actual
site. That's expected ngrok behavior, not a bug in LocalShare.
"""
from __future__ import annotations


class TunnelHandle:
    def __init__(self) -> None:
        self.public_url: str | None = None
        self._tunnel = None

    @property
    def is_running(self) -> bool:
        return self._tunnel is not None

    def start(self, local_port: int, authtoken: str) -> str:
        """
        Opens an ngrok tunnel to the given local port. Returns the
        public HTTPS URL. Raises RuntimeError with a clear, actionable
        message on any failure (pyngrok not installed, missing/bad
        authtoken, no network, etc.) rather than letting a raw
        exception surface to the GUI.
        """
        if self.is_running:
            return self.public_url  # type: ignore[return-value]

        if not authtoken or not authtoken.strip():
            raise RuntimeError(
                "An ngrok authtoken is required for internet sharing (this is ngrok's "
                "requirement, even for their free tier). Get a free one at "
                "https://dashboard.ngrok.com/get-started/your-authtoken and paste it in."
            )

        try:
            from pyngrok import ngrok
        except ImportError as exc:
            raise RuntimeError(
                'Internet sharing requires the "pyngrok" package. Install it with: pip install pyngrok'
            ) from exc

        try:
            ngrok.set_auth_token(authtoken.strip())
            tunnel = ngrok.connect(addr=local_port, proto="http")
        except Exception as exc:
            # pyngrok wraps a lot of different failure modes (bad
            # token, no network, ngrok binary download failure) in its
            # own exception types — surface whatever it reports rather
            # than guessing which one happened.
            raise RuntimeError(f"Couldn't start the internet tunnel: {exc}") from exc

        self._tunnel = tunnel
        self.public_url = tunnel.public_url
        return self.public_url

    def stop(self) -> None:
        if self._tunnel is not None:
            try:
                from pyngrok import ngrok

                ngrok.disconnect(self._tunnel.public_url)
            except Exception:
                pass  # best-effort — the tunnel will time out on ngrok's side regardless
        self._tunnel = None
        self.public_url = None

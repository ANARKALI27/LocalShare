"""
Internet sharing via ngrok.

This is what makes "Local Network + Internet" mode reachable from
outside your Wi-Fi: pyngrok (the standard Python wrapper for ngrok)
opens an outbound connection from your machine to ngrok's edge network
and hands back a public HTTPS URL that forwards to your local server.
No port forwarding, no router configuration needed.

Unlike the Cloudflare Quick Tunnel this replaces, ngrok requires a
free account and an authtoken — there's no anonymous/no-signup tier
anymore. In exchange, pyngrok manages the ngrok binary itself
automatically (downloading it on first use, no separate installer
step needed the way cloudflared required), which is a meaningfully
simpler, more self-contained story for this app to rely on.

Honest limitation: I could not test the actual connection to ngrok's
servers end-to-end — this sandbox's own network restrictions block
bin.ngrok.com (where pyngrok fetches the ngrok binary from), so the
real download-and-connect path has never actually run in front of me.
What I could verify: pyngrok's actual API via direct inspection (not
memory) — connect()/set_auth_token()/disconnect()'s real signatures,
NgrokTunnel's real attributes, and the real exception hierarchy this
error handling is built around.
"""
from __future__ import annotations


class TunnelHandle:
    def __init__(self) -> None:
        self.public_url: str | None = None
        self._connected = False

    @property
    def is_running(self) -> bool:
        return self._connected

    def start(self, local_port: int, auth_token: str = "") -> str:
        """
        Connects an ngrok tunnel to local_port and returns the public
        URL. Raises RuntimeError with a clear, actionable message if
        no authtoken is configured, or if ngrok itself fails to
        connect (invalid token, no internet, ngrok's service down, a
        firewall blocking it, etc.).
        """
        if self.is_running:
            return self.public_url  # type: ignore[return-value]

        if not auth_token:
            raise RuntimeError(
                "Internet Sharing needs a free ngrok account and authtoken — "
                "Cloudflare's old no-signup option isn't available anymore.\n\n"
                "1. Sign up (free): https://dashboard.ngrok.com/signup\n"
                "2. Copy your authtoken: https://dashboard.ngrok.com/get-started/your-authtoken\n"
                "3. Paste it into Settings → Sharing → ngrok Authtoken\n\n"
                "Then try Internet Sharing again."
            )

        # Imported here, not at module load time, so this module stays
        # importable (e.g. for other code that just checks is_running)
        # even in an environment where pyngrok isn't installed yet.
        from pyngrok import ngrok
        from pyngrok.exception import PyngrokError

        try:
            ngrok.set_auth_token(auth_token)
            tunnel = ngrok.connect(local_port, "http")
        except PyngrokError as exc:
            raise RuntimeError(
                f"Couldn't start the ngrok tunnel: {exc}\n\n"
                "Double-check the authtoken in Settings → Sharing is correct and "
                "hasn't been revoked, and that this machine has internet access."
            ) from exc
        except Exception as exc:
            # pyngrok can also raise plain OSError/subprocess errors
            # (e.g. the ngrok binary itself failed to launch) that
            # aren't PyngrokError subclasses — still want a clear
            # message rather than a raw traceback either way.
            raise RuntimeError(f"Couldn't start the ngrok tunnel: {exc}") from exc

        if not tunnel.public_url:
            raise RuntimeError(
                "ngrok connected but didn't report a public URL — this is unexpected; "
                "try again, and if it keeps happening, check https://status.ngrok.com "
                "for an outage."
            )

        self.public_url = tunnel.public_url
        self._connected = True
        return self.public_url

    def stop(self) -> None:
        if self._connected and self.public_url:
            from pyngrok import ngrok
            try:
                ngrok.disconnect(self.public_url)
            except Exception:
                # Best-effort — if ngrok's already gone (process died,
                # network dropped), there's nothing meaningful left to
                # clean up, and this must not raise during shutdown.
                pass
        self._connected = False
        self.public_url = None

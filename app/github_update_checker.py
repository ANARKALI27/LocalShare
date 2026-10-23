"""
Checks the real LocalShare GitHub repository's Releases for a newer
version than the one currently running — distinct from
app/gui/update_checker.py, which checks another LocalShare instance
on the LAN by address and can optionally hand over an installer file
it's sharing. Both are legitimate, separate ways to learn about an
update; this module is the one that works for anyone with internet
access and no LAN peer to check against, by querying GitHub directly.

Deliberately does nothing beyond reporting what GitHub says: no
automatic downloading or running of anything GitHub returns. The only
action available from a detected update is opening the public
Releases page in the system's default browser, where the person picks
and runs the right installer themselves.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.gui.update_checker import compare_versions

REPO = "ANARKALI27/LocalShare"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases"

CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours — automatic checks don't run more often than this


def normalize_version(version: str) -> str:
    """Strips a leading 'v' (GitHub tags are conventionally "v3.3.0";
    this app's own APP_VERSION is plain "3.3.0") so the two can be
    compared on equal footing. Leaves everything else untouched —
    compare_versions already tolerates non-numeric segments."""
    version = version.strip()
    if version.lower().startswith("v") and len(version) > 1 and version[1].isdigit():
        return version[1:]
    return version


class GitHubReleaseInfo:
    def __init__(self, tag_name: str, name: str, html_url: str, published_at: str, body: str, assets: list) -> None:
        self.tag_name = tag_name
        self.version = normalize_version(tag_name)
        self.name = name or tag_name
        self.html_url = html_url
        self.published_at = published_at
        self.body = body or ""
        self.assets = assets  # list of {"name": ..., "browser_download_url": ...}


class GitHubUpdateCheckResult:
    def __init__(
        self,
        ok: bool,
        error: str | None = None,
        release: GitHubReleaseInfo | None = None,
        is_newer: bool = False,
    ) -> None:
        self.ok = ok
        self.error = error
        self.release = release
        self.is_newer = is_newer


def fetch_latest_release(timeout: float = 8.0) -> GitHubUpdateCheckResult:
    """
    Queries the GitHub Releases API for the latest published, non-draft,
    non-prerelease release — GitHub's own /releases/latest endpoint
    already excludes drafts and prereleases, which is exactly the
    "don't bother normal users with beta builds" behavior wanted here,
    with no extra filtering needed on this end. Never raises: every
    failure mode (no internet, GitHub down, rate limiting, an
    unexpected response shape) comes back as a non-ok result with a
    plain, non-alarming message, since none of these should ever be
    treated as "an update is available" or be allowed to disrupt the
    app in any way.
    """
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "LocalShare-UpdateChecker"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return GitHubUpdateCheckResult(ok=False, error="Rate limited by GitHub — try again later")
        if exc.code == 404:
            return GitHubUpdateCheckResult(ok=False, error="No published releases found")
        return GitHubUpdateCheckResult(ok=False, error=f"GitHub returned an error ({exc.code})")
    except urllib.error.URLError:
        return GitHubUpdateCheckResult(ok=False, error="Unable to check right now")
    except TimeoutError:
        return GitHubUpdateCheckResult(ok=False, error="Unable to check right now")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return GitHubUpdateCheckResult(ok=False, error="GitHub responded, but not with valid release info")

    tag_name = data.get("tag_name")
    if not tag_name:
        return GitHubUpdateCheckResult(ok=False, error="GitHub's response didn't include a release version")

    html_url = data.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/"):
        html_url = RELEASES_PAGE_URL  # never open a link that isn't on github.com

    release = GitHubReleaseInfo(
        tag_name=tag_name,
        name=data.get("name") or tag_name,
        html_url=html_url,
        published_at=data.get("published_at") or "",
        body=data.get("body") or "",
        assets=[
            {"name": a.get("name", ""), "browser_download_url": a.get("browser_download_url", "")}
            for a in data.get("assets", [])
            if isinstance(a, dict)
            and str(a.get("browser_download_url", "")).startswith("https://github.com/")
        ],
    )
    return GitHubUpdateCheckResult(ok=True, release=release)


def is_update_available(current_version: str, release: GitHubReleaseInfo) -> bool:
    """Proper segment-by-segment semantic comparison (via the same
    compare_versions the LAN update checker already uses and already
    has string-vs-numeric-segment handling for) — never a plain string
    comparison, which would get e.g. "3.10.0" vs "3.9.0" backwards."""
    return compare_versions(release.version, normalize_version(current_version)) > 0


def should_check_now(last_check_time: float, interval_seconds: float = CHECK_INTERVAL_SECONDS) -> bool:
    """True if it's been at least `interval_seconds` since the last
    successful check, or if there's no record of one yet. Keeps
    automatic checks from hitting the API needlessly on every launch —
    manual "Check Now" presses always bypass this, by simply not
    calling this function at all."""
    if last_check_time <= 0:
        return True
    return (time.time() - last_check_time) >= interval_seconds

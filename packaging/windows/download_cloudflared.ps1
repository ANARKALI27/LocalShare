# Downloads cloudflared (needed for Internet/Global sharing mode) into
# the LocalShare install directory during setup. Deliberately
# non-fatal: Local sharing works completely fine without cloudflared,
# so a failed download here (no internet at install time, GitHub
# temporarily unreachable, etc.) must never fail or block the overall
# LocalShare installation — it just means Global mode isn't ready yet,
# exactly the same "not found" state the app already handles and
# reports clearly if the user tries Global mode without it.

param(
    [Parameter(Mandatory = $true)]
    [string]$DestDir
)

$ErrorActionPreference = "Stop"
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$destination = Join-Path $DestDir "cloudflared.exe"

try {
    # Skip re-downloading if a previous install (or manual copy)
    # already placed it here — installs should be quick to repeat,
    # not re-fetch a ~55MB file every single time.
    if (Test-Path $destination) {
        exit 0
    }
    Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
}
catch {
    # Swallow any failure (no network, DNS issue, GitHub down, blocked
    # by a corporate firewall, etc.) — LocalShare itself must still
    # install successfully. The app's existing cloudflared-not-found
    # handling covers this gracefully at runtime if Global mode is used.
    if (Test-Path $destination) {
        Remove-Item $destination -Force -ErrorAction SilentlyContinue
    }
}

exit 0

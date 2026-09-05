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

$logPath = Join-Path $DestDir "cloudflared_install_log.txt"

function Write-Log {
    param([string]$Message)
    # Best-effort logging only — if even this fails (e.g. DestDir
    # somehow isn't writable), it must not throw and break the
    # non-fatal contract this whole script exists to uphold.
    try {
        Add-Content -Path $logPath -Value "$(Get-Date -Format 'u')  $Message" -ErrorAction SilentlyContinue
    } catch {}
}

# Windows PowerShell 5.1 (the default on most Windows 10/11 systems —
# distinct from PowerShell 7+) frequently does NOT negotiate TLS 1.2 by
# default, and GitHub requires it. Without this line, Invoke-WebRequest
# against github.com can fail outright on an otherwise perfectly good
# internet connection, with no obvious cause. This is the single most
# likely reason this script silently did nothing on a real machine.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    Write-Log "Could not enable TLS 1.2 explicitly: $($_.Exception.Message) — continuing anyway, some systems already default to it."
}

$ErrorActionPreference = "Stop"
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$destination = Join-Path $DestDir "cloudflared.exe"

try {
    # Skip re-downloading if a previous install (or manual copy)
    # already placed it here — installs should be quick to repeat,
    # not re-fetch a ~55MB file every single time.
    if (Test-Path $destination) {
        Write-Log "cloudflared.exe already present at $destination — skipping download."
        exit 0
    }
    Write-Log "Downloading $url to $destination ..."
    Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
    Write-Log "Download succeeded."
}
catch {
    # Swallow any failure (no network, DNS issue, GitHub down, blocked
    # by a corporate firewall, etc.) — LocalShare itself must still
    # install successfully. The app's existing cloudflared-not-found
    # handling covers this gracefully at runtime if Global mode is used.
    Write-Log "Download failed: $($_.Exception.Message)"
    if (Test-Path $destination) {
        Remove-Item $destination -Force -ErrorAction SilentlyContinue
    }
}

exit 0

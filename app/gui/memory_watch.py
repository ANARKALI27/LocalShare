"""
Cross-platform "how much memory is this process actually using right
now" check, without adding a new dependency (psutil would be the
obvious choice, but this is simple enough not to need it). Used by the
video-background memory watchdog in main_window.py — video playback
uses hardware-accelerated decoding on Windows, which can leak memory
in ways this app can't itself fully diagnose or prevent (it's Windows
Media Foundation's own decoder session, not this app's Python code),
so this exists as a safety net that catches genuinely runaway growth
rather than a fix for a specific root cause.
"""
from __future__ import annotations

import platform


def get_process_memory_mb() -> float | None:
    """
    Current process's resident memory, in megabytes. Returns None if
    it can't be determined on this platform/configuration — callers
    must treat that as "unknown, don't act on it" rather than "zero."
    """
    system = platform.system()
    try:
        if system == "Windows":
            return _get_process_memory_mb_windows()
        else:
            return _get_process_memory_mb_linux()
    except Exception:
        return None


def _get_process_memory_mb_windows() -> float | None:
    import ctypes
    import ctypes.wintypes as wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        return None
    return counters.WorkingSetSize / (1024 * 1024)


def _get_process_memory_mb_linux() -> float | None:
    # /proc/self/status's VmRSS line is the actual resident memory
    # (what's really occupying RAM), not VmSize (which includes
    # reserved-but-not-yet-used virtual address space and would
    # overstate things).
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) / 1024  # value is in kB
    return None

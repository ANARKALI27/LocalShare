"""
Path safety helpers.

Every route that turns a URL path into a filesystem path MUST go
through `safe_join`. This is the one place path-traversal protection
lives, so it can't be forgotten in some route and not another.
"""
from __future__ import annotations

import os
import re

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


def sanitize_filename(name: str) -> str:
    """
    Strip characters that are invalid or dangerous in Windows filenames,
    for names arriving from uploads. Doesn't touch the extension logic —
    just removes path separators and reserved characters.
    """
    name = name.replace("\x00", "")
    name = os.path.basename(name)  # drop any directory component entirely
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "_")
    name = name.strip(" .")  # Windows disallows trailing dots/spaces
    return name or "unnamed"

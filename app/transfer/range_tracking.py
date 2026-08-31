"""
Pure interval-merging logic for tracking which byte ranges of a file
have been received, independent of the order chunks arrive in. No I/O
here at all, deliberately — this is the part that must be provably
correct before trusting it with real uploads, since a silent gap would
produce a file that looks complete but is quietly corrupt.
"""
from __future__ import annotations

Range = tuple[int, int]  # (start, end), end exclusive — same convention as Python slicing


def merge_range(ranges: list[Range], new_range: Range) -> list[Range]:
    """
    Inserts new_range into a list of (start, end) ranges, merging with
    any that overlap or touch (end == start of the next one), and
    returns a new sorted, fully-merged, non-overlapping list. Handles
    duplicate/overlapping resends of the same bytes safely — merging
    a range that's already fully covered is a no-op.
    """
    all_ranges = sorted(ranges + [new_range])
    merged: list[Range] = [all_ranges[0]]
    for start, end in all_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # overlaps or exactly touches the previous range
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def total_covered(ranges: list[Range]) -> int:
    return sum(end - start for start, end in ranges)


def is_fully_covered(ranges: list[Range], total_size: int) -> bool:
    """True only if the ranges form one unbroken span from 0 to total_size
    — a completed download is exactly this, nothing looser."""
    if total_size == 0:
        return True  # an empty file is trivially "fully received"
    return len(ranges) == 1 and ranges[0] == (0, total_size)

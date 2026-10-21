"""Coverage-window helpers for the QA lane (T017).

Coverage is the honest answer to "which media milliseconds did this check actually
see?". ``partition_coverage`` splits ``[0, duration)`` into CHECKED windows (the
detector/observation really ran there) and gap windows carrying the caller's status —
UNSAMPLED for "never looked" and UNAVAILABLE for "cannot look" (no audio stream, no
observation source, media that does not decode). ``coverage_for`` folds windows back
into one status for an arbitrary range: a range is CHECKED only when CHECKED windows
cover it completely, and UNSAMPLED/UNAVAILABLE ranges stay UNKNOWN downstream — a
window that was never sampled is not checked, and it can never produce a PASS.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from microdrama.contracts.enums import CheckFamily, CoverageStatus
from microdrama.contracts.qa import CoverageWindow


def partition_coverage(
    asset_id: UUID,
    family: CheckFamily,
    duration_ms: int,
    covered: Sequence[tuple[int, int]],
    *,
    outside: CoverageStatus = CoverageStatus.UNSAMPLED,
    note: str | None = None,
) -> list[CoverageWindow]:
    """Partition ``[0, duration)`` into covered windows and gap windows with a status."""
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    windows: list[CoverageWindow] = []
    cursor = 0
    for start, end in sorted(covered):
        if not 0 <= start < end <= duration_ms:
            raise ValueError(f"covered range {(start, end)} must lie inside the media")
        if start > cursor:
            windows.append(
                CoverageWindow(asset_id=asset_id, check_family=family, start_ms=cursor,
                               end_ms=start, status=outside, note=note)
            )  # fmt: skip
        windows.append(
            CoverageWindow(asset_id=asset_id, check_family=family, start_ms=start,
                           end_ms=end, status=CoverageStatus.CHECKED)
        )  # fmt: skip
        cursor = end
    if cursor < duration_ms or not windows:
        windows.append(
            CoverageWindow(asset_id=asset_id, check_family=family, start_ms=cursor,
                           end_ms=duration_ms, status=outside, note=note)
        )  # fmt: skip
    return windows


def coverage_for(
    windows: Sequence[CoverageWindow], family: CheckFamily, start_ms: int, end_ms: int
) -> CoverageStatus:
    """Coverage status of ``[start_ms, end_ms)`` for one check family.

    CHECKED only when CHECKED windows cover the whole range; PARTIAL when some of it
    is checked; otherwise the worst overlapping status (UNAVAILABLE beats UNSAMPLED —
    "cannot look" is stronger information than "did not look"), and UNAVAILABLE when
    no window of that family overlaps at all.
    """
    overlapping = [
        w
        for w in windows
        if w.check_family is family and w.start_ms < end_ms and start_ms < w.end_ms
    ]
    if not overlapping:
        return CoverageStatus.UNAVAILABLE
    cursor = start_ms
    for w in sorted(overlapping, key=lambda w: w.start_ms):
        if w.status is CoverageStatus.CHECKED:
            if w.start_ms > cursor:
                break
            cursor = max(cursor, w.end_ms)
    if cursor >= end_ms:
        return CoverageStatus.CHECKED
    if any(w.status is CoverageStatus.CHECKED for w in overlapping):
        return CoverageStatus.PARTIAL
    statuses = {w.status for w in overlapping}
    if CoverageStatus.UNAVAILABLE in statuses:
        return CoverageStatus.UNAVAILABLE
    if CoverageStatus.UNSAMPLED in statuses:
        return CoverageStatus.UNSAMPLED
    return CoverageStatus.PARTIAL


def checked_ms(windows: Sequence[CoverageWindow]) -> int:
    """Total milliseconds actually checked (evidence, not a quality claim)."""
    return sum(w.end_ms - w.start_ms for w in windows if w.status is CoverageStatus.CHECKED)


def checked_ranges(windows: Sequence[CoverageWindow]) -> list[tuple[int, int]]:
    """The (start, end) millisecond ranges whose windows are CHECKED."""
    return sorted((w.start_ms, w.end_ms) for w in windows if w.status is CoverageStatus.CHECKED)


def summarize_coverage(
    windows: Sequence[CoverageWindow],
    *,
    max_entries: int = 24,
) -> dict[str, object]:
    """Bounded per-family summary for event payloads (events cap at 16 KiB)."""
    families: dict[str, list[CoverageWindow]] = {}
    for window in windows:
        families.setdefault(window.check_family.value, []).append(window)
    summary: dict[str, object] = {}
    for family, family_windows in sorted(families.items()):
        entries = [
            [w.start_ms, w.end_ms, w.status.value]
            for w in sorted(family_windows, key=lambda w: (w.start_ms, w.end_ms))
        ]
        summary[family] = {
            "window_count": len(entries),
            "checked_ms": checked_ms(family_windows),
            "windows": entries[:max_entries],
            "truncated": len(entries) > max_entries,
        }
    return summary


__all__ = [
    "checked_ms",
    "checked_ranges",
    "coverage_for",
    "partition_coverage",
    "summarize_coverage",
]

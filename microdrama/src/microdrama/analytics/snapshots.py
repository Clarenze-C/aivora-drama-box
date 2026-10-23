"""Per-platform metric snapshots with provenance, schedule truth and null honesty (T027).

The frozen contract is ``contracts.catalog.MetricSnapshot`` and the frozen table is
``performance_snapshots`` (migration 0005, append-only, one row per post+window).
Policy truth this module owns (SPEC §10, task_breakdown §5 T027):

- **Windows are schedules, not requests.** A snapshot for a window may only be
  recorded once the window boundary (24h/72h/7d after the post's ``verified_at``)
  has been reached. An early observation is ``PolicyDenied`` — never truncated to
  the boundary and never stored under a different window.
- **Unknown is null, never zero.** A metric the platform did not report keeps
  ``value=None`` end to end. Nothing in this module coerces a missing value to 0
  or fabricates a denominator.
- **Replay is idempotent; divergence is a conflict.** Recording the same
  ``(platform_post_id, snapshot_window)`` twice with an identical body returns the
  existing row; a different body for the same window is ``Conflict`` (the table is
  append-only — a platform restating numbers produces a *new* definitions version
  through the provider, not a mutation here).
- **Definitions are part of the number.** ``definitions_version`` and each metric's
  platform definition id travel with every value, and the ledger refuses to merge
  or compare series whose definitions differ (see ``ledger.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from microdrama.contracts.catalog import MetricSnapshot
from microdrama.contracts.enums import SnapshotWindow
from microdrama.contracts.errors import Conflict, NotFound, PolicyDenied
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence.db import Tx, insert_row, jsonb

# Window -> hours after ``verified_at`` before the snapshot may be observed.
WINDOW_BOUNDARY_HOURS: dict[SnapshotWindow, int] = {
    SnapshotWindow.H24: 24,
    SnapshotWindow.H72: 72,
    SnapshotWindow.D7: 24 * 7,
}


def window_boundary(verified_at: datetime, window: SnapshotWindow) -> datetime:
    """The earliest instant at which ``window`` may be observed for this post."""
    return verified_at + timedelta(hours=WINDOW_BOUNDARY_HOURS[window])


@dataclass(frozen=True)
class DueWindow:
    window: SnapshotWindow
    boundary: datetime
    recorded: bool


class SnapshotStore:
    """Recording and schedule logic over the append-only ``performance_snapshots`` table."""

    def __init__(self, tx: Tx) -> None:
        self._tx = tx

    # --- schedule --------------------------------------------------------------------

    def post_verified_at(self, platform_post_id: UUID) -> datetime:
        row = self._tx.fetchone(
            "SELECT verified_at, state FROM platform_posts WHERE id = %s",
            (platform_post_id,),
        )
        if row is None:
            raise NotFound("platform post not found", platform_post_id=str(platform_post_id))
        if row["verified_at"] is None:
            raise PolicyDenied(
                "post is not PUBLISHED_VERIFIED; no snapshot window has started",
                platform_post_id=str(platform_post_id),
                state=row["state"],
            )
        return row["verified_at"]

    def due_windows(self, platform_post_id: UUID, *, now: datetime) -> list[DueWindow]:
        """Every window for the post with its boundary and whether it is recorded.

        Windows whose boundary lies in the future are listed with ``recorded=False``;
        deciding whether a window is *due* is comparing ``boundary <= now``.
        """
        verified_at = self.post_verified_at(platform_post_id)
        recorded = {
            row["snapshot_window"]
            for row in self._tx.fetchall(
                "SELECT snapshot_window FROM performance_snapshots WHERE platform_post_id = %s",
                (platform_post_id,),
            )
        }
        due: list[DueWindow] = []
        for window, hours in WINDOW_BOUNDARY_HOURS.items():
            boundary = verified_at + timedelta(hours=hours)
            due.append(
                DueWindow(
                    window=window,
                    boundary=boundary,
                    recorded=window.value in recorded,
                )
            )
        return due

    # --- recording -------------------------------------------------------------------

    def record(self, snapshot: MetricSnapshot, *, now: datetime | None = None) -> UUID:
        """Persist one snapshot; idempotent per (post, window), refusing early windows.

        ``now`` (the submission instant) does not relax the rule: an observation
        made before the boundary stays early no matter when it is submitted.
        """
        self._check_boundary(snapshot)
        existing = self._tx.fetchone(
            "SELECT id, body FROM performance_snapshots "
            "WHERE platform_post_id = %s AND snapshot_window = %s",
            (snapshot.platform_post_id, snapshot.window.value),
        )
        if existing is not None:
            if canonical_hash(existing["body"]) == canonical_hash(snapshot.model_dump(mode="json")):
                return existing["id"]  # idempotent replay of identical data
            raise Conflict(
                "window already recorded with different data; the table is append-only",
                platform_post_id=str(snapshot.platform_post_id),
                window=snapshot.window.value,
            )
        row = insert_row(
            self._tx,
            "performance_snapshots",
            {
                "id": snapshot.snapshot_id,
                "platform_post_id": snapshot.platform_post_id,
                "platform": snapshot.platform.value,
                "account_ref": snapshot.account_ref,
                "external_post_id": snapshot.external_post_id,
                "episode_id": snapshot.episode_id,
                "snapshot_window": snapshot.window.value,
                "observed_at": snapshot.observed_at,
                "definitions_version": snapshot.definitions_version,
                "metrics": jsonb(
                    {name: value.model_dump() for name, value in snapshot.metrics.items()}
                ),
                "country": snapshot.country,
                "traffic": snapshot.traffic.value,
                "sample_count": snapshot.sample_count,
                "provenance": snapshot.provenance.value,
                "body": jsonb(snapshot.model_dump(mode="json")),
            },
        )
        return row["id"]

    def _check_boundary(self, snapshot: MetricSnapshot) -> datetime:
        verified_at = self.post_verified_at(snapshot.platform_post_id)
        boundary = window_boundary(verified_at, snapshot.window)
        if snapshot.observed_at < boundary:
            raise PolicyDenied(
                "snapshot window boundary not reached",
                platform_post_id=str(snapshot.platform_post_id),
                window=snapshot.window.value,
                boundary=boundary.isoformat(),
            )
        return boundary

    # --- reading ---------------------------------------------------------------------

    def snapshot_row(self, platform_post_id: UUID, window: SnapshotWindow) -> dict[str, Any] | None:
        return self._tx.fetchone(
            "SELECT * FROM performance_snapshots WHERE platform_post_id = %s AND snapshot_window = %s",
            (platform_post_id, window.value),
        )

    def episode_snapshots(self, episode_id: UUID) -> list[dict[str, Any]]:
        return self._tx.fetchall(
            "SELECT * FROM performance_snapshots WHERE episode_id = %s "
            "ORDER BY platform_post_id, snapshot_window",
            (episode_id,),
        )


__all__ = [
    "DueWindow",
    "SnapshotStore",
    "WINDOW_BOUNDARY_HOURS",
    "window_boundary",
]

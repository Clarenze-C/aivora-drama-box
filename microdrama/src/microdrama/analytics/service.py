"""Analytics service facade (T027): snapshots, ledgers, cost, qualification.

One object the integrator (T029) and the worker runtime (T028) talk to; every
method opens its own transaction unless a ``Tx`` is handed in. Routers are NOT
provided — composition stays integrator-owned (house rule since T020).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.catalog import MetricSnapshot, QualificationResult
from microdrama.contracts.enums import SnapshotWindow
from microdrama.contracts.errors import NotFound
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.jobs import MetricWindowInput, SeasonStepInput
from microdrama.persistence.db import Database

from . import cost as cost_module
from . import ledger as ledger_module
from .cost import SeasonCost
from .ledger import CohortRow, TrafficRow
from .qualification import QualificationEvaluator
from .snapshots import DueWindow, SnapshotStore


class AnalyticsService:
    def __init__(self, db: Database, clock: Clock, ids: IdGenerator) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self.qualification = QualificationEvaluator(db, clock, ids)

    # --- snapshots (24h/72h/7d schedules) --------------------------------------------

    def due_windows(
        self, platform_post_id: UUID, *, now: datetime | None = None
    ) -> list[DueWindow]:
        with self._db.transaction(readonly=True) as tx:
            return SnapshotStore(tx).due_windows(platform_post_id, now=now or self._clock.now())

    def record_snapshot(self, snapshot: MetricSnapshot, *, now: datetime | None = None) -> UUID:
        with self._db.transaction() as tx:
            return SnapshotStore(tx).record(snapshot, now=now or self._clock.now())

    def snapshot_row(self, platform_post_id: UUID, window: SnapshotWindow) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return SnapshotStore(tx).snapshot_row(platform_post_id, window)

    # --- ledgers ---------------------------------------------------------------------

    def hook_ledger(self, episode_id: UUID, *, metric: str = "views") -> list[CohortRow]:
        with self._db.transaction(readonly=True) as tx:
            return ledger_module.hook_ledger(tx, episode_id, metric=metric)

    def traffic_ledger(self, episode_id: UUID) -> list[TrafficRow]:
        with self._db.transaction(readonly=True) as tx:
            return ledger_module.traffic_ledger(tx, episode_id)

    def metric_series(self, platform_post_id: UUID, metric: str):
        with self._db.transaction(readonly=True) as tx:
            return ledger_module.metric_series(tx, platform_post_id, metric)

    # --- cost and qualification --------------------------------------------------------

    def season_cost(self, season_id: UUID) -> SeasonCost:
        with self._db.transaction(readonly=True) as tx:
            return cost_module.season_cost(tx, season_id)

    def evaluate_qualification(
        self, season_id: UUID, *, now: datetime | None = None
    ) -> QualificationResult:
        return self.qualification.evaluate(season_id, now=now)

    # --- job entry points (registered by workers/, T028) --------------------------------

    def run_snapshot_job(self, payload: MetricWindowInput) -> dict[str, Any]:
        """Check one post/window: recorded summary, due-ness, or waiting on data.

        Offline there is no insights provider (a live adapter arrives with T032),
        so a due-but-unrecorded window waits for external data instead of
        fabricating numbers. A window whose boundary has not been reached is a
        schema error — the schedule is not a suggestion.
        """
        now = self._clock.now()
        due = {w.window: w for w in self.due_windows(payload.platform_post_id, now=now)}
        target = due.get(payload.window)
        if target is None:
            raise NotFound(
                "window is not one of this post's windows",
                window=payload.window.value,
            )
        if target.recorded:
            row = self.snapshot_row(payload.platform_post_id, payload.window)
            metrics = row["metrics"] if row is not None else {}
            return {
                "status": "RECORDED",
                "window": payload.window.value,
                "definitions_version": row["definitions_version"] if row else None,
                "metrics": {
                    name: (entry or {}).get("value") for name, entry in (metrics or {}).items()
                },
            }
        if now < target.boundary:
            raise ValueError("window boundary not reached; snapshot job is early")
        return {
            "status": "WAITING_EXTERNAL",
            "window": payload.window.value,
            "boundary": target.boundary.isoformat(),
        }

    def run_qualification_job(self, payload: SeasonStepInput) -> QualificationResult:
        return self.qualification.evaluate(payload.season_id)


def build_analytics_service(db: Database, clock: Clock, ids: IdGenerator) -> AnalyticsService:
    """Offline-safe factory for the integrator (T029) and worker runtime (T028)."""
    return AnalyticsService(db, clock, ids)


__all__ = ["AnalyticsService", "build_analytics_service"]

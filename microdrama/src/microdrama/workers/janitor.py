"""The independently scheduled queue janitor (T028, IMP-06, MD-013).

Separately invokable (``python -m microdrama.workers.janitor``): like the
rendering lane's GPU janitor it needs only the database, the budget service and
configuration — never a worker process, a queue or the main service. One
``sweep()``:

1. requeues expired job leases (``JobService.requeue_expired``): a job whose
   in-flight provider operation went ambiguous moves to NEEDS_RECONCILIATION,
   never a blind rerun;
2. expires stale budget holds (``BudgetService.expire_stale``): crashed
   reservations stop shielding money;
3. reports the queue depth and quarantine (NEEDS_RECONCILIATION) population so
   operators see backlog and stuck work after every sweep.

Every action appends a ``workers.janitor`` evidence event. A failing step is
recorded and does not block the rest of the sweep.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import QueueName
from microdrama.contracts.errors import MicrodramaError
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.events import append_event
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database

JANITOR_NAMESPACE = UUID("f81d4fae-7dec-11d0-a765-00a0c91e6bf6")  # uuid5 ns for workers.janitor


@dataclass(frozen=True)
class JanitorStep:
    name: str
    done: int
    error: str | None = None


@dataclass(frozen=True)
class JanitorReport:
    swept_at: datetime
    steps: tuple[JanitorStep, ...] = ()
    queue_depths: dict[str, int] = field(default_factory=dict)
    quarantined: tuple[dict[str, Any], ...] = ()

    @property
    def failures(self) -> tuple[JanitorStep, ...]:
        return tuple(step for step in self.steps if step.error is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "swept_at": self.swept_at.isoformat(),
            "steps": [
                {"name": step.name, "done": step.done, "error": step.error} for step in self.steps
            ],
            "queue_depths": self.queue_depths,
            "quarantined": list(self.quarantined),
            "failures": len(self.failures),
        }


class WorkersJanitor:
    """One sweep over expired leases, stale holds and queue telemetry."""

    def __init__(
        self,
        db: Database,
        jobs: JobService,
        budget: BudgetService,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._db = db
        self._jobs = jobs
        self._budget = budget
        self._clock = clock
        self._ids = ids

    def sweep(self, *, now: datetime | None = None) -> JanitorReport:
        instant = now or self._clock.now()
        steps: list[JanitorStep] = []

        steps.append(self._step("requeue_expired", lambda: self._jobs.requeue_expired(now=instant)))
        steps.append(self._step("expire_stale_holds", self._budget.expire_stale))

        depths: dict[str, int] = {}
        quarantined: list[dict[str, Any]] = []
        try:
            with self._db.transaction(readonly=True) as tx:
                for queue in QueueName:
                    depths[queue.value] = int(
                        tx.fetchval(
                            "SELECT count(*) FROM jobs WHERE queue = %s "
                            "AND status IN ('QUEUED','RETRY_WAIT','RUNNING')",
                            (queue.value,),
                        )
                        or 0
                    )
                quarantined = [
                    {
                        "job_id": str(row["id"]),
                        "job_type": row["job_type"],
                        "queue": row["queue"],
                        "attempt": row["attempt"],
                    }
                    for row in tx.fetchall(
                        "SELECT id, job_type, queue, attempt FROM jobs "
                        "WHERE status = 'NEEDS_RECONCILIATION' ORDER BY updated_at LIMIT 100"
                    )
                ]
            steps.append(JanitorStep(name="telemetry", done=len(depths) + len(quarantined)))
        except MicrodramaError as error:
            steps.append(JanitorStep(name="telemetry", done=0, error=error.message))

        report = JanitorReport(
            swept_at=instant,
            steps=tuple(steps),
            queue_depths=depths,
            quarantined=tuple(quarantined),
        )
        self._record(report)
        return report

    def _step(self, name: str, action) -> JanitorStep:
        try:
            return JanitorStep(name=name, done=int(action()))
        except MicrodramaError as error:
            return JanitorStep(name=name, done=0, error=error.message)

    def _record(self, report: JanitorReport) -> None:
        sweep_id = uuid5(JANITOR_NAMESPACE, f"sweep:{report.swept_at.isoformat()}")
        with self._db.transaction() as tx:
            append_event(
                tx,
                event_type="workers.janitor.swept",
                aggregate_type="workers_janitor",
                aggregate_id=JANITOR_NAMESPACE,
                payload=report.to_dict(),
                correlation_id=sweep_id,
                occurred_at=report.swept_at,
                event_id=sweep_id,
            )


def build_janitor(
    db: Database,
    jobs: JobService,
    budget: BudgetService,
    clock: Clock,
    ids: IdGenerator,
) -> WorkersJanitor:
    """Composition factory for the integrator / scheduler registration."""
    return WorkersJanitor(db, jobs, budget, clock, ids)


def main(argv: list[str] | None = None) -> int:
    """``python -m microdrama.workers.janitor --dsn ...`` (one sweep).

    Exits 0 when the sweep had no failures, 2 on a configuration error.
    """
    parser = argparse.ArgumentParser(
        prog="microdrama-workers-janitor",
        description="Independent queue hygiene: expired leases, stale holds, telemetry.",
    )
    parser.add_argument(
        "--dsn", default=os.environ.get("MICRODRAMA_DATABASE_URL"), help="PostgreSQL DSN"
    )
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn or MICRODRAMA_DATABASE_URL is required")
    try:
        settings = Settings.from_env()
        db = Database(args.dsn).open()
        try:
            clock, ids = SystemClock(), UuidIds()
            janitor = build_janitor(
                db,
                JobService(db, clock, ids),
                BudgetService(db, clock, ids, settings),
                clock,
                ids,
            )
            report = janitor.sweep()
        finally:
            db.close()
    except MicrodramaError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}), file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if report.failures else 0


__all__ = ["JanitorReport", "JanitorStep", "WorkersJanitor", "build_janitor", "main"]

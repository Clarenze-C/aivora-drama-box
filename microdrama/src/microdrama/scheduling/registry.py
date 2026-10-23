"""The declarative W01–W12 schedule registry (T029; replaces the n8n exports).

Every automated trigger of the delivery architecture as one versioned,
code-native registry. Firing is a pure function of (registry, now): a schedule
due at an instant enqueues its durable job(s) through the frozen
``JobService`` — nothing else. No business rule lives here; the registry only
owns *when* work is proposed, never *whether* it may run (gates, budgets,
capabilities and idempotency all stay in the services).

Idempotency: each schedule's enqueues carry semantic keys derived from the
schedule id and the current period bucket, so a restarted or double-invoked
scheduler cannot double-fire a period (ON CONFLICT DO NOTHING, same as every
other producer).

Two schedules are special by design (W12): the janitors are independently
scheduled *actions*, not jobs — they sweep directly so a blocked queue can
never stop cleanup (SPEC §6/§8, T028).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

SCHEDULES_VERSION = "1"

# --- registry ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    workflow: str  # W01..W12 surface it belongs to
    interval: timedelta
    description: str


class ScheduleCatalog:
    """The registry plus due-ness and semantic-key derivation (pure, no I/O)."""

    def __init__(self, schedules: tuple[Schedule, ...]) -> None:
        self._schedules = schedules

    @property
    def schedules(self) -> tuple[Schedule, ...]:
        return self._schedules

    def due(self, now: datetime, *, last_fired: dict[str, datetime]) -> list[Schedule]:
        """Schedules whose interval elapsed since their last firing (never in the future)."""
        due: list[Schedule] = []
        for schedule in self._schedules:
            last = last_fired.get(schedule.schedule_id)
            if last is None or now - last >= schedule.interval:
                due.append(schedule)
        return due

    def period_key(self, schedule: Schedule, now: datetime) -> str:
        """Stable per-period bucket: re-firing inside one period is a no-op."""
        bucket = int(now.timestamp() // schedule.interval.total_seconds())
        return f"sched:{schedule.schedule_id}:{bucket}"


def default_catalog() -> ScheduleCatalog:
    """The standard pilot cadence (the automation plan's W01–W12 triggers)."""
    return ScheduleCatalog(
        (
            Schedule(
                "w01-research",
                "W01",
                timedelta(days=7),
                "Weekly bounded source research → season proposals (pre-Gate-1).",
            ),
            Schedule(
                "w02-compile-backstop",
                "W02",
                timedelta(days=7),
                "Reconciliation backstop: compile seasons whose Gate 1 approval did "
                "not enqueue it (the approval itself is the primary trigger).",
            ),
            Schedule(
                "w03-write",
                "W03",
                timedelta(days=1),
                "Daily cadence check: write the next episode inside the buffer rules.",
            ),
            Schedule(
                "w04-references",
                "W04",
                timedelta(days=1),
                "Daily reference/voice preparation for episodes with CURRENT scripts.",
            ),
            Schedule(
                "w05-render-poll",
                "W05",
                timedelta(minutes=15),
                "Reconcile in-flight render operations (submit/poll/recover).",
            ),
            Schedule(
                "w06-edit",
                "W06",
                timedelta(hours=1),
                "Assemble episodes whose accepted shot set is complete.",
            ),
            Schedule(
                "w07-qa",
                "W07",
                timedelta(hours=1),
                "Run technical QA on assembled masters; observation/compare follow.",
            ),
            Schedule(
                "w09-publish-poll",
                "W09",
                timedelta(minutes=5),
                "Poll processing platform posts; reconcile ambiguous submissions.",
            ),
            Schedule(
                "w11-analytics",
                "W11",
                timedelta(hours=1),
                "Record due 24h/72h/7d windows; missing external data stays waiting.",
            ),
            Schedule(
                "w12-workers-janitor",
                "W12",
                timedelta(minutes=10),
                "Independent queue/budget-hold sweep (action, not a job).",
            ),
            Schedule(
                "w12-gpu-janitor",
                "W12",
                timedelta(minutes=10),
                "Independent orphan-pod/lease sweep (action, not a job).",
            ),
        )
    )


__all__ = ["SCHEDULES_VERSION", "Schedule", "ScheduleCatalog", "default_catalog"]

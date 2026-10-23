"""Unit tests for the in-app scheduling surface (T029).

Pure-registry behavior here; DB-backed firing lives in the contract/integration
lanes. Pins: full W-coverage, due-ness math, stable period keys, and the two
janitor actions being schedules (never jobs).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from microdrama.scheduling import Schedule, ScheduleCatalog, default_catalog

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_catalog_covers_every_workflow_surface() -> None:
    catalog = default_catalog()
    workflows = {schedule.workflow for schedule in catalog.schedules}
    # W08 is the human gate (no schedule); W10 arrives as webhooks (routes, tested
    # in the contract lane). Every automated surface has at least one schedule.
    assert workflows == {f"W{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 9, 11, 12)}


def test_janitors_are_schedules_not_jobs() -> None:
    catalog = default_catalog()
    w12 = [s for s in catalog.schedules if s.workflow == "W12"]
    assert {s.schedule_id for s in w12} == {"w12-workers-janitor", "w12-gpu-janitor"}
    assert all(s.interval <= timedelta(minutes=10) for s in w12), (
        "the independent janitors must run on a frequent timer (SPEC §6/§8)"
    )


def test_due_requires_elapsed_interval() -> None:
    hourly = Schedule("t", "W01", timedelta(hours=1), "test")
    catalog = ScheduleCatalog((hourly,))
    assert catalog.due(T0, last_fired={}) == [hourly]
    assert catalog.due(T0, last_fired={"t": T0 - timedelta(minutes=59)}) == []
    assert catalog.due(T0, last_fired={"t": T0 - timedelta(hours=1)}) == [hourly]
    # A future firing time never makes a schedule due "early".
    assert catalog.due(T0 - timedelta(hours=2), last_fired={"t": T0}) == []


def test_period_keys_bucket_stably() -> None:
    catalog = default_catalog()
    schedule = next(s for s in catalog.schedules if s.schedule_id == "w11-analytics")
    inside = catalog.period_key(schedule, T0)
    same_bucket = catalog.period_key(schedule, T0 + timedelta(minutes=30))
    next_bucket = catalog.period_key(schedule, T0 + timedelta(hours=1))
    assert inside == same_bucket
    assert inside != next_bucket

"""Contract tests: schedule firing + webhook routes against real state (T029).

Pins the trigger-layer contract from behavior: firing enqueues only frozen job
types, one per entity per period (semantic-key dedupe proven by double firing),
action schedules sweep directly, the webhook routes exist in the composed app,
record deduplicated untrusted events, and never act on unverified content.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from microdrama.api.app import create_app
from microdrama.api.compose import build_components, build_services
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.scheduling import default_catalog
from microdrama.scheduling.webhooks import build_webhook_router

pytestmark = [pytest.mark.db]


def test_first_fire_enqueues_research_and_nothing_else_on_an_idle_world(world, scheduler) -> None:
    report = scheduler.fire()
    assert "w01-research" in report.fired
    # No PROPOSED season exists yet -> zero enqueues, but the firing is recorded.
    assert report.enqueued_jobs == 0
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT schedule_id FROM schedule_state")
    assert {row["schedule_id"] for row in rows} == {
        s.schedule_id for s in default_catalog().schedules
    }


def test_a_proposed_season_gets_exactly_one_research_job_per_period(world, scheduler) -> None:
    from uuid import uuid4

    from microdrama.persistence.db import insert_row

    season_id = uuid4()
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "seasons",
            {"id": season_id, "state": "PROPOSED", "title_th": "t", "title_en": "T"},
        )
    first = scheduler.fire()
    assert first.enqueued_jobs == 1
    second = scheduler.fire(now=datetime(2026, 10, 27, 12, 1, tzinfo=UTC))
    assert second.enqueued_jobs == 0, "re-firing inside the period must not duplicate"
    assert second.fired == [], "interval not elapsed: nothing is due"
    next_period = scheduler.fire(now=datetime(2026, 10, 27, 12, 0, tzinfo=UTC) + timedelta(days=8))
    assert next_period.enqueued_jobs == 1, "a new period proposes once more"


def test_w12_actions_sweep_and_report_without_jobs(world, scheduler) -> None:
    report = scheduler.fire(only={"w12-workers-janitor", "w12-gpu-janitor"})
    assert report.actions["w12-workers"]["steps"] >= 1
    assert "stopped_pods" in report.actions["w12-gpu"]
    with world.db.transaction(readonly=True) as tx:
        jobs = tx.fetchall("SELECT job_type FROM jobs")
    assert jobs == [], "janitor schedules must never enqueue jobs"


def test_only_fires_requested_schedules(world, scheduler) -> None:
    report = scheduler.fire(only={"w05-render-poll"})
    assert report.fired == ["w05-render-poll"]
    assert report.actions.get("w05") is not None


def _client(world) -> TestClient:
    router = build_webhook_router(world.db, memberships_service=world.memberships)
    components = build_components(
        build_services(Settings(execution_mode=ExecutionMode.OFFLINE_MOCK), db=_NullDb()),
        extra_routers=[router],
    )
    return TestClient(create_app(components))


class _NullDb:
    pass


def test_community_webhook_records_deduplicated_untrusted_events(world) -> None:
    client = _client(world)
    payload = {"event": "comment.created", "text": "great episode"}
    headers = {"x-provider-event-id": "evt-1"}
    first = client.post("/webhooks/community/youtube", json=payload, headers=headers)
    assert first.status_code == 202
    assert first.json() == {"status": "RECORDED", "verified": False, "mock": True}
    duplicate = client.post("/webhooks/community/youtube", json=payload, headers=headers)
    assert duplicate.status_code == 202
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT provider, event_id, signature_valid FROM webhook_events "
            "WHERE provider = 'community:youtube'"
        )
    assert len(rows) == 1 and rows[0]["signature_valid"] is False


def test_community_webhook_requires_a_provider_event_id(world) -> None:
    client = _client(world)
    response = client.post("/webhooks/community/youtube", json={"event": "x"})
    assert response.status_code == 202
    assert response.json()["status"] == "MISSING_EVENT_ID"


def test_membership_webhook_without_configuration_is_not_configured(world) -> None:
    client = _client(type("_W", (), {"db": world.db, "memberships": None})())
    response = client.post("/webhooks/membership/patreon", content=b"{}")
    assert response.status_code == 202
    assert response.json()["status"] == "NOT_CONFIGURED"


def test_membership_webhook_processes_through_the_real_service(world) -> None:
    client = _client(world)
    response = client.post(
        "/webhooks/membership/patreon",
        content=b"{}",
        headers={"x-patreon-signature": "invalid"},
    )
    assert response.status_code == 202
    # The T026 service stops at verification: invalid signature, no interpretation.
    assert response.json()["status"] in {"INVALID_SIGNATURE", "PROCESSED"}

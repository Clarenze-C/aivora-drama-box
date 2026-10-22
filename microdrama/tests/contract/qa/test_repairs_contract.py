"""Contract tests for the repair lane (T019).

Real module outputs (real database, real planning) checked against the FROZEN
contracts at 1.5.0: every persisted plan body validates as ``contracts.RepairPlan``
and honors its invariants (round cap, cost consistency, returns-to-Gate-2, shot
steps consume attempts); the durable lane events stay inside the 16 KiB payload
bound; and the ``repair_plans`` body is immutable in storage.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from qa_support import QAWorld
from repairs_support import RepairsWorld

from microdrama.contracts.errors import Conflict
from microdrama.contracts.qa import RepairPlan, RepairStep
from microdrama.qa.repairs import (
    EXECUTED_EVENT,
    PLAN_EVENT,
    RETURN_EVENT,
)

MAX_EVENT_PAYLOAD_BYTES = 16_384


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


@pytest.fixture
def planned(world: RepairsWorld):
    episode_id, thai, english, _package = world.episode_with_tracks()
    finding = world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    outcome = world.repairs().plan_from_findings(episode_id)
    return world, episode_id, finding, outcome


def test_persisted_plan_body_validates_as_the_frozen_contract(planned) -> None:
    world, episode_id, _finding, outcome = planned
    row = world.row("SELECT * FROM repair_plans WHERE id = %s", (outcome.plan.plan_id,))
    assert row is not None
    stored = RepairPlan.model_validate(row["body"])
    assert stored == outcome.plan
    assert row["trigger"] == stored.trigger.value
    assert row["round_number"] == stored.round_number
    assert row["total_estimated_micro_usd"] == stored.total_estimated_micro_usd


def test_repair_step_contract_forces_shot_steps_to_consume_attempts() -> None:
    with pytest.raises(ValidationError, match="consume an ordinary attempt"):
        RepairStep(
            step_id="shot.free",
            target="SHOT",
            target_ids=["sh1"],
            action="re-render",
            category="GPU_GENERATION",
            estimated_cost_micro_usd=0,
            consumes_shot_attempt=False,
        )


def test_repair_plan_events_stay_inside_the_payload_bound(planned) -> None:
    world, episode_id, _finding, outcome = planned
    execution = world.repairs().execute_plan(outcome.plan.plan_id)
    assert execution.status == "COMPLETED"
    for event_type in (PLAN_EVENT, EXECUTED_EVENT, RETURN_EVENT):
        rows = world.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
            (episode_id, event_type),
        )
        assert rows
        for row in rows:
            assert len(json.dumps(row["payload"]).encode()) <= MAX_EVENT_PAYLOAD_BYTES


def test_repair_plan_body_is_immutable_in_storage(planned) -> None:
    world, _episode, _finding, outcome = planned
    with pytest.raises(Conflict, match="immutable"):
        with world.db.transaction() as tx:
            tx.execute(
                "UPDATE repair_plans SET body = '{\"tampered\": true}'::jsonb WHERE id = %s",
                (outcome.plan.plan_id,),
            )


def test_executed_plan_step_receipts_reference_real_reservations(planned) -> None:
    world, _episode, _finding, outcome = planned
    execution = world.repairs().execute_plan(outcome.plan.plan_id)
    # unpriced offline steps reserve nothing — and say so honestly
    assert execution.settled_micro_usd == 0
    assert execution.steps[0].reservation_id is None
    assert world.rows("SELECT * FROM reservations") == []

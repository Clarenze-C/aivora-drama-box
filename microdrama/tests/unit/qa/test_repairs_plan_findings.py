"""Repair planning from QA findings (T019 acceptance 1/2, plan side).

A subtitle defect plans a caption-only repair; a wrong-voice finding targets the
correct line plus exactly its derivative cues — never a blanket re-render. Findings
whose evidence cannot be root-caused to a targeted scope are typed-unknown refusals,
and identical planning replays the durable plan.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from repairs_support import L1, L2, RecordingShotDispatch, RepairsWorld

from microdrama.contracts.enums import RepairTarget, RepairTrigger
from microdrama.qa.repairs import (
    PLAN_EVENT,
    RepairCauseUnknown,
)

pytestmark = pytest.mark.db


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


def test_subtitle_defect_plans_a_caption_only_repair(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    finding = world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    dispatch = RecordingShotDispatch()
    outcome = world.repairs(shot_dispatch=dispatch).plan_from_findings(episode_id)

    assert outcome.replayed is False
    assert outcome.status == "PLANNED"
    assert [step.target for step in outcome.plan.steps] == [RepairTarget.CAPTION]
    step = outcome.plan.steps[0]
    # both locales' cues for the affected line ONLY — cue-level scope
    assert sorted(step.target_ids) == [f"{L1}.enus", f"{L1}.thth"]
    assert f"{L2}.thth" not in step.target_ids and f"{L2}.enus" not in step.target_ids
    assert step.consumes_shot_attempt is False
    assert outcome.plan.trigger is RepairTrigger.QA_FINDING
    assert outcome.plan.finding_ids == [finding]
    # planning touched no render-side operation at all
    assert dispatch.count_calls == 0 and dispatch.dispatch_calls == []
    row = world.row("SELECT * FROM repair_plans WHERE id = %s", (outcome.plan.plan_id,))
    assert row is not None and row["status"] == "PLANNED" and row["trigger"] == "QA_FINDING"
    event = world.row(
        "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
        (episode_id, PLAN_EVENT),
    )
    assert event is not None and event["payload"]["steps"][0]["target"] == "CAPTION"


def test_wrong_voice_finding_targets_the_line_and_its_derivative_cues(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="asr.speaker_match",
        repair_targets=["LINE"],
        start_ms=10_500,  # strictly inside L1's cue window, outside L2's
        end_ms=12_000,
        observed="lek's voice",
        expected="fon's voice",
    )
    dispatch = RecordingShotDispatch()
    outcome = world.repairs(shot_dispatch=dispatch).plan_from_findings(episode_id)

    targets = [(step.target, list(step.target_ids)) for step in outcome.plan.steps]
    assert targets == [
        (RepairTarget.LINE, [L1]),  # the CORRECT line only
        (RepairTarget.CAPTION, [f"{L1}.enus", f"{L1}.thth"]),  # its derivative cues only
    ]
    # no SHOT step: a wrong voice never plans a blanket re-render
    assert all(step.target is not RepairTarget.SHOT for step in outcome.plan.steps)
    assert dispatch.count_calls == 0 and dispatch.dispatch_calls == []
    # dependency order: the line (upstream) repairs before its derivative cues
    assert [step.step_id for step in outcome.plan.steps] == ["lines", "captions"]


def test_line_finding_with_no_resolvable_line_is_a_typed_unknown(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="asr.speaker_match",
        repair_targets=["LINE"],
        start_ms=100_000,  # overlaps no cue: the repair cannot be targeted
        end_ms=101_000,
    )
    with pytest.raises(RepairCauseUnknown, match="cannot be targeted"):
        world.repairs().plan_from_findings(episode_id)
    assert world.rows("SELECT * FROM repair_plans WHERE episode_id = %s", (episode_id,)) == []


def test_identical_planning_replays_the_stored_plan(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    service = world.repairs()
    first = service.plan_from_findings(episode_id)
    second = service.plan_from_findings(episode_id)
    assert second.replayed is True
    assert second.plan.plan_id == first.plan.plan_id
    assert len(world.rows("SELECT * FROM repair_plans WHERE episode_id = %s", (episode_id,))) == 1


def test_plan_honors_the_frozen_cost_consistency_contract(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    plan = world.repairs().plan_from_findings(episode_id).plan
    assert plan.total_estimated_micro_usd == sum(
        step.estimated_cost_micro_usd for step in plan.steps
    )
    assert plan.total_estimated_micro_usd <= plan.remaining_budget_micro_usd
    assert plan.returns_to_gate2 is True

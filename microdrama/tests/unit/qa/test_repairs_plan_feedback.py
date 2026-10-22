"""Repair planning from timecoded Gate 2 human feedback (T019, IMP-05).

Feedback rows come from a REAL Gate 2 REVISE decision (``core.approvals`` is the
only ``feedback_events`` writer). The planner resolves each note's timecodes to the
affected cues/lines/shots — smallest scope, never blanket — and refuses typed when
the note cannot be targeted or its category has no root-cause mapping.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from repairs_support import L1, L2, RecordingShotDispatch, RepairsWorld

from microdrama.contracts.enums import (
    FeedbackCategory,
    FeedbackScope,
    RepairTarget,
    RepairTrigger,
)
from microdrama.contracts.season import TimecodedFeedback
from microdrama.qa.repairs import RepairCauseUnknown

pytestmark = pytest.mark.db


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


def test_subtitle_feedback_plans_a_cue_level_repair(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.SUBTITLES,
                start_ms=10_500,  # strictly inside L1's cues, outside L2's
                end_ms=12_000,
                comment="Subtitle says 5,000 baht; Fon says 50,000.",
            )
        ],
    )
    outcome = world.repairs().plan_from_feedback(episode_id, approval)

    assert outcome.plan.trigger is RepairTrigger.HUMAN_FEEDBACK
    assert outcome.plan.feedback_event_ids == [row["id"] for row in world.feedback_rows(approval)]
    # the note's timecodes [10.5, 12.0) overlap exactly L1's cue in each locale
    assert [step.target for step in outcome.plan.steps] == [RepairTarget.CAPTION]
    assert outcome.plan.steps[0].target_ids == [f"{L1}.enus", f"{L1}.thth"]
    assert f"{L2}.thth" not in outcome.plan.steps[0].target_ids
    row = world.row("SELECT * FROM repair_plans WHERE id = %s", (outcome.plan.plan_id,))
    assert row is not None
    assert row["source_approval_event_id"] == approval


def test_identity_voice_feedback_targets_the_line_and_derivative_cues(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.IDENTITY_VOICE,
                start_ms=10_500,
                end_ms=12_000,
                comment="This line sounds like Lek, but Fon speaks it.",
            )
        ],
    )
    outcome = world.repairs(shot_dispatch=RecordingShotDispatch()).plan_from_feedback(
        episode_id, approval
    )
    targets = [(step.target, list(step.target_ids)) for step in outcome.plan.steps]
    assert targets == [
        (RepairTarget.LINE, [L1]),
        (RepairTarget.CAPTION, [f"{L1}.enus", f"{L1}.thth"]),
    ]
    assert f"{L2}.thth" not in outcome.plan.steps[1].target_ids


def test_continuity_feedback_repairs_the_named_shot_as_an_ordinary_attempt(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.CONTINUITY_PROPS,
                start_ms=10_000,
                end_ms=13_000,
                shot_id="sh1",
                comment="The ledger disappears mid-shot.",
                scope=FeedbackScope.SHOT,
            )
        ],
    )
    outcome = world.repairs(shot_dispatch=RecordingShotDispatch(attempts=1)).plan_from_feedback(
        episode_id, approval
    )
    (step,) = outcome.plan.steps
    assert step.target is RepairTarget.SHOT
    assert step.target_ids == ["sh1"]
    # the frozen contract itself forces shot re-renders to consume an attempt
    assert step.consumes_shot_attempt is True


def test_feedback_with_no_cue_in_its_timecodes_is_a_typed_unknown(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.SUBTITLES,
                start_ms=200_000,
                end_ms=201_000,
                comment="Subtitle wrong here",
            )
        ],
    )
    with pytest.raises(RepairCauseUnknown, match="cannot be targeted"):
        world.repairs().plan_from_feedback(episode_id, approval)
    assert world.rows("SELECT * FROM repair_plans WHERE episode_id = %s", (episode_id,)) == []


def test_unmapped_feedback_category_is_a_typed_unknown(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.OTHER,
                start_ms=0,
                end_ms=1_000,
                comment="Something feels off",
            )
        ],
    )
    with pytest.raises(RepairCauseUnknown, match="triage"):
        world.repairs().plan_from_feedback(episode_id, approval)


def test_identical_feedback_planning_replays(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    approval = world.revise_feedback(
        episode_id,
        [
            TimecodedFeedback(
                category=FeedbackCategory.SUBTITLES,
                start_ms=12_000,
                end_ms=15_500,
                comment="English subtitle says 5,000 baht; Fon says 50,000.",
            )
        ],
    )
    service = world.repairs()
    first = service.plan_from_feedback(episode_id, approval)
    second = service.plan_from_feedback(episode_id, approval)
    assert second.replayed is True and second.plan.plan_id == first.plan.plan_id

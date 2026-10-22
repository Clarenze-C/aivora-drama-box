"""Scoped feedback memory (T019; IMP-05, AT-07 scope half).

Feedback rows come from REAL Gate 2 REVISE decisions through the review service
(T008 owns that writer). A local comment becomes exactly a local preference
version; the series scope exists only from an explicit recurring instruction (the
service refuses inference typed, and the database CHECK refuses it again under
both); versions supersede and roll back.
"""

from __future__ import annotations

import uuid

import pytest
from review_support import World

from microdrama.contracts.enums import (
    ApprovalAction,
    FeedbackCategory,
    FeedbackScope,
    GateType,
)
from microdrama.contracts.errors import Conflict, NotFound
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import insert_row
from microdrama.review.feedback import (
    RECORDED_EVENT,
    FeedbackMemory,
    ScopePromotionDenied,
)

pytestmark = pytest.mark.db


def _revise(
    world: World,
    episode_id,
    package,
    feedback,
) -> uuid.UUID:
    human = world.human()
    revision = world.episode_revision(episode_id)
    command = world.gate2_command(
        episode_id,
        package,
        ApprovalAction.REVISE,
        revision=revision,
        feedback=feedback,
    )
    world.service.decide_episode(human, episode_id, command)
    approval = world.approvals(episode_id)[-1]
    return approval["id"]


def _feedback_rows(world: World, episode_id) -> list:
    return world.row_all(
        "SELECT * FROM feedback_events WHERE episode_id = %s ORDER BY id", (episode_id,)
    )


@pytest.fixture
def memory(world: World) -> FeedbackMemory:
    return FeedbackMemory(world.db, world.clock, world.ids)


@pytest.fixture
def revised(world: World):
    """A Gate 2 REVISE with one local (EPISODE-scoped) subtitle note at 10.5-12s."""
    season_id, episode_id, package = world.ready_episode()
    _approval_id = _revise(
        world,
        episode_id,
        package,
        feedback=[
            {
                "category": FeedbackCategory.SUBTITLES,
                "start_ms": 10_500,
                "end_ms": 12_000,
                "comment": "Subtitle says 5,000 baht; Fon says 50,000.",
            }
        ],
    )
    return world, season_id, episode_id, _approval_id


def test_local_feedback_becomes_exactly_an_episode_scoped_rule(revised, memory) -> None:
    world, season_id, episode_id, _approval_id = revised
    (row,) = _feedback_rows(world, episode_id)

    rule = memory.remember(row["id"], instruction="always match subtitle amounts to the audio")

    assert rule.scope is FeedbackScope.EPISODE
    assert rule.episode_id == episode_id
    assert rule.explicit_recurring is False
    assert rule.state == "ACTIVE"
    assert rule.rule_key == f"subtitles.episode.{episode_id}"
    # nothing series-wide exists: local feedback never widens by itself
    active = memory.active_rules(season_id)
    assert [r.rule_key for r in active] == [rule.rule_key]
    assert all(r.scope is not FeedbackScope.SERIES for r in active)
    assert (
        world.row_all(
            "SELECT * FROM preference_rules WHERE season_id = %s AND scope = 'SERIES'",
            (season_id,),
        )
        == []
    )


def test_local_feedback_cannot_be_promoted_to_series_by_inference(revised, memory) -> None:
    world, season_id, episode_id, _approval = revised
    (row,) = _feedback_rows(world, episode_id)
    memory.remember(row["id"], instruction="match subtitle amounts")

    with pytest.raises(ScopePromotionDenied, match="cannot become a global season rule"):
        memory.promote_to_series(row["id"], instruction="match subtitle amounts")
    assert (
        world.row_all(
            "SELECT * FROM preference_rules WHERE season_id = %s AND scope = 'SERIES'",
            (season_id,),
        )
        == []
    )

    # the database CHECK refuses it again underneath (surfaced as a typed
    # Conflict by the persistence layer), whatever the caller does
    with pytest.raises(Conflict) as excinfo:
        with world.db.transaction() as tx:
            insert_row(
                tx,
                "preference_rules",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "rule_key": "subtitles:series",
                    "version": 1,
                    "scope": "SERIES",
                    "episode_id": None,
                    "category": "subtitles",
                    "instruction": "smuggled series rule",
                    "source_feedback_event_id": row["id"],
                    "explicit_recurring": False,
                    "state": "ACTIVE",
                },
            )
    assert "preference_rules" in str(excinfo.value.details.get("constraint", ""))


def test_series_rule_requires_explicit_recurring_instruction(world: World, memory) -> None:
    season_id, episode_id, package = world.ready_episode()
    _approval_id = _revise(
        world,
        episode_id,
        package,
        feedback=[
            {
                "category": FeedbackCategory.SUBTITLES,
                "start_ms": 10_500,
                "end_ms": 12_000,
                "comment": "From now on, always spell amounts with Arabic numerals.",
                "scope": FeedbackScope.SERIES,
                "explicit_recurring_instruction": True,
            }
        ],
    )
    (row,) = _feedback_rows(world, episode_id)
    rule = memory.remember(row["id"], instruction="spell amounts with Arabic numerals")
    assert rule.scope is FeedbackScope.SERIES
    assert rule.explicit_recurring is True
    assert rule.episode_id is None
    assert memory.active_rules(season_id) == [rule]


def test_shot_scoped_feedback_becomes_a_shot_rule(world: World, memory) -> None:
    season_id, episode_id, package = world.ready_episode()
    _revise(
        world,
        episode_id,
        package,
        feedback=[
            {
                "category": FeedbackCategory.CONTINUITY_PROPS,
                "start_ms": 10_500,
                "end_ms": 12_000,
                "shot_id": "sh3",
                "comment": "ledger must stay visible in this shot",
                "scope": FeedbackScope.SHOT,
            }
        ],
    )
    (row,) = _feedback_rows(world, episode_id)
    rule = memory.remember(row["id"], instruction="keep the ledger in frame")
    assert rule.scope is FeedbackScope.SHOT
    assert rule.shot_key == "sh3"
    assert rule.rule_key == "continuity_props.shot.sh3"


def test_preference_versions_supersede_and_roll_back(revised, memory) -> None:
    world, season_id, episode_id, _approval = revised
    (row,) = _feedback_rows(world, episode_id)

    v1 = memory.remember(row["id"], instruction="match amounts to the audio")
    # the same scope, refined instruction: a NEW version supersedes the ACTIVE one
    v2 = memory.remember(row["id"], instruction="use Arabic numerals for amounts")
    assert v2.version == v1.version + 1
    assert v2.rule_id != v1.rule_id
    assert [r.version for r in memory.active_rules(season_id)] == [v2.version]
    assert (
        world.row("SELECT state FROM preference_rules WHERE id = %s", (v1.rule_id,))["state"]
        == "SUPERSEDED"
    )

    rolled = memory.rollback(season_id, v2.rule_key)
    assert rolled.version == v1.version and rolled.state == "ACTIVE"
    assert (
        world.row("SELECT state FROM preference_rules WHERE id = %s", (v2.rule_id,))["state"]
        == "ROLLED_BACK"
    )
    assert [r.version for r in memory.active_rules(season_id)] == [v1.version]

    with pytest.raises(NotFound):
        memory.rollback(season_id, "unknown-key.1")


def test_remember_is_idempotent_per_version(revised, memory) -> None:
    world, _season, episode_id, _approval = revised
    (row,) = _feedback_rows(world, episode_id)
    first = memory.remember(row["id"], instruction="same instruction")
    second = memory.remember(row["id"], instruction="same instruction")
    assert second == first
    assert (
        len(
            world.row_all(
                "SELECT * FROM preference_rules WHERE season_id = %s AND rule_key = %s",
                (first.season_id, first.rule_key),
            )
        )
        == 1
    )


def test_preference_events_are_recorded(revised, memory) -> None:
    world, season_id, episode_id, _approval = revised
    (row,) = _feedback_rows(world, episode_id)
    memory.remember(row["id"], instruction="match amounts")
    events = world.row_all(
        "SELECT * FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
        (season_id, RECORDED_EVENT),
    )
    assert events and events[-1]["payload"]["scope"] == "EPISODE"


def test_gate2_command_binding_is_enforced(world: World, memory) -> None:
    """Sanity: the REVISE decision really is the review lane's own contract."""
    season_id, episode_id, package = world.ready_episode()
    human = world.human()
    command = world.gate2_command(episode_id, package, ApprovalAction.REVISE)
    assert command.gate is GateType.EPISODE_FINAL
    assert command.feedback[0].explicit_recurring_instruction is False
    world.service.decide_episode(human, episode_id, command)
    assert world.episode_state(episode_id)[0] == "ASSEMBLING"
    assert canonical_hash(command)  # the decision is hash-bound, not anonymous

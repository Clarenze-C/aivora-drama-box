"""Gate 1 (season concept): approve or reject a proposal, with replay, stale and mismatch refusal."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from review_support import World

from microdrama.contracts.enums import ApprovalAction, GateType, PrincipalKind
from microdrama.contracts.errors import (
    IdempotencyConflict,
    InvalidTransition,
    SchemaInvalid,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.season import ApprovalCommand

pytestmark = pytest.mark.db


def _proposal_row(world: World, season_id):
    return world.row("SELECT * FROM season_proposals WHERE season_id = %s", (season_id,))


def test_gate1_approve_queues_the_story_job_and_binds_the_scope_hash(world: World) -> None:
    season_id, scope = world.season(approved=False)
    scope_hash = canonical_hash(scope)
    command = world.gate1_command(season_id, scope_hash, revision=0)

    result = world.service.decide_season(world.human(), season_id, command)

    assert result.status_code == 202
    assert result.replayed is False
    assert result.body["status"] == "QUEUED"
    season = world.row("SELECT * FROM seasons WHERE id = %s", (season_id,))
    assert season["state"] == "SEASON_APPROVED"
    assert season["approved_scope_hash"] == scope_hash
    assert season["approved_scope_version"] == 1
    assert season["approval_event_id"] == UUID(result.body["event_id"])
    assert _proposal_row(world, season_id)["status"] == "APPROVED"
    jobs = world.jobs_of("story.compile_season")
    assert len(jobs) == 1
    assert jobs[0]["semantic_key"] == f"story.compile_season:{season_id}:1"
    assert jobs[0]["season_id"] == season_id
    assert jobs[0]["causation_id"] == UUID(result.body["event_id"])


def test_gate1_replay_with_the_same_key_returns_the_stored_answer_without_a_second_effect(
    world: World,
) -> None:
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), revision=0)
    human = world.human()
    first = world.service.decide_season(human, season_id, command)
    second = world.service.decide_season(human, season_id, command)

    assert second.replayed is True
    assert second.status_code == 202
    assert second.body["job_id"] == first.body["job_id"]
    assert len(world.jobs_of("story.compile_season")) == 1
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (season_id,)) == 1
    )


def test_same_key_with_a_different_body_is_a_conflict(world: World) -> None:
    season_id, scope = world.season(approved=False)
    scope_hash = canonical_hash(scope)
    key = "gate1-same-key-0001"
    human = world.human()
    world.service.decide_season(
        human, season_id, world.gate1_command(season_id, scope_hash, 0, idempotency_key=key)
    )
    different = world.gate1_command(season_id, scope_hash, 0, idempotency_key=key, reason="changed")
    with pytest.raises(IdempotencyConflict):
        world.service.decide_season(human, season_id, different)


def test_stale_revision_is_refused_and_leaves_no_trace(world: World) -> None:
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), revision=7)
    with pytest.raises(StaleRevision):
        world.service.decide_season(world.human(), season_id, command)
    assert world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == "PROPOSED"
    assert world.approvals(season_id) == []
    assert world.jobs_of("story.compile_season") == []


def test_a_scope_hash_that_is_not_the_current_proposal_is_refused(world: World) -> None:
    season_id, _scope = world.season(approved=False)
    command = world.gate1_command(season_id, "9" * 64, revision=0)
    with pytest.raises(StaleRevision, match="proposal changed"):
        world.service.decide_season(world.human(), season_id, command)
    assert world.approvals(season_id) == []


def test_revise_is_not_a_gate1_action(world: World) -> None:
    """The schema refuses Revise at Gate 1 before any service code runs (HTTP: 422)."""
    season_id, scope = world.season(approved=False)
    with pytest.raises(ValidationError, match="not a valid action"):
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.REVISE,
            entity_id=season_id,
            expected_revision=0,
            package_hash=canonical_hash(scope),
            idempotency_key="gate1-revise-attempt",
            feedback=[],
        )


def test_gate1_reject_marks_the_season_and_queues_nothing(world: World) -> None:
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), 0, action=ApprovalAction.REJECT)
    result = world.service.decide_season(world.human(), season_id, command)

    assert result.status_code == 202
    assert result.body["status"] == "RECORDED"
    assert world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == "REJECTED"
    assert _proposal_row(world, season_id)["status"] == "REJECTED"
    assert world.jobs_of("story.compile_season") == []


def test_an_approved_season_takes_no_further_gate1_decision(world: World) -> None:
    season_id, scope = world.season(approved=True)
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    with pytest.raises(InvalidTransition, match="only a PROPOSED season"):
        world.service.decide_season(world.human(), season_id, command)


def test_gate_and_entity_must_match_the_route(world: World) -> None:
    season_id, scope = world.season(approved=False)
    other = world.gate1_command(season_id, canonical_hash(scope), 0, entity_id=uuid4())
    with pytest.raises(SchemaInvalid, match="entity_id does not match"):
        world.service.decide_season(world.human(), season_id, other)


@pytest.mark.parametrize(
    "kind",
    [
        PrincipalKind.SERVICE_WORKER,
        PrincipalKind.SCHEDULER,
        PrincipalKind.RUNTIME_MODEL,
        PrincipalKind.PROVIDER_WEBHOOK,
    ],
)
def test_non_human_principals_cannot_decide_gate1(world: World, kind: PrincipalKind) -> None:
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    with pytest.raises(Unauthorized):
        world.service.decide_season(world.service_principal(kind), season_id, command)
    assert world.approvals(season_id) == []
    assert world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == "PROPOSED"


def test_the_season_list_and_view_show_the_proposal_without_secrets(world: World) -> None:
    season_id, scope = world.season(approved=False)
    rows = world.service.season_proposals()
    row = next(r for r in rows if r.season_id == season_id)
    assert row.scope_hash == canonical_hash(scope)
    assert row.state.value == "PROPOSED"
    view = world.service.season_view(season_id)
    assert view.scope.title_en == scope.title_en
    assert view.summary.revision == 0

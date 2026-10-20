"""Season and episode state enforcement against the frozen tables (real database)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from core_support import (
    CRITIC,
    NON_HUMAN,
    SCHEDULER,
    T0,
    WEBHOOK,
    WORKER,
    H,
    approve_package,
    count,
    episode_state,
    fresh_episode,
    gate1,
    gate2,
    make_human,
    ready_package,
    season_row,
)

from microdrama.contracts.enums import (
    ApprovalAction,
    EpisodeOutcome,
    EpisodeState,
    PrincipalKind,
    RuntimeRole,
    SeasonState,
)
from microdrama.contracts.errors import (
    IdentityLockRequired,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.principals import Principal
from microdrama.contracts.states import EPISODE_TRANSITIONS, SEASON_TRANSITIONS
from microdrama.core.approvals import record_approval_event
from microdrama.core.events import list_events
from microdrama.core.state_machine import (
    clear_episode_outcome,
    set_episode_outcome,
    transition_episode,
    transition_season,
)
from microdrama.persistence import Database
from microdrama.persistence.db import Tx
from microdrama.testing.seed import seed_gate1_approval, seed_season

pytestmark = pytest.mark.db
SERVICE_WORKER = WORKER  # the deterministic service-worker principal used by these tests

PRE_RELEASE = (
    EpisodeState.PLANNED,
    EpisodeState.SCRIPTING,
    EpisodeState.REFERENCES,
    EpisodeState.RENDERING,
    EpisodeState.ASSEMBLING,
    EpisodeState.AI_REVIEW,
    EpisodeState.AWAITING_FINAL_REVIEW,
)
REPAIR_STAGES = {
    EpisodeState.SCRIPTING,
    EpisodeState.REFERENCES,
    EpisodeState.RENDERING,
    EpisodeState.ASSEMBLING,
}


def _record(db: Database, principal, command) -> uuid.UUID:
    with db.transaction() as tx:
        return record_approval_event(
            tx, principal=principal, command=command, now=T0, correlation_id=uuid.uuid4()
        )


def _season_approval(db: Database, season_id, scope_hash: str, *, action=ApprovalAction.APPROVE):
    """A real Gate 1 decision by a live human owner, recorded at the season's current revision."""
    with db.transaction() as tx:
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM seasons WHERE id = %s", (season_id,))
    return human, _record(db, human, gate1(season_id, scope_hash, revision=revision, action=action))


# --- seasons ----------------------------------------------------------------------------


def test_season_transition_matrix_matches_the_frozen_table(db: Database, clock) -> None:
    """Every (from, to) pair: table-forbidden -> InvalidTransition; human-only -> Unauthorized
    without approval; allowed automatic moves succeed. Any deviation is reported together."""
    problems: list[str] = []
    for source in SeasonState:
        for target in SeasonState:
            with db.transaction() as tx:
                season = seed_season(tx, state=source.value)
            try:
                with db.transaction() as tx:
                    transition_season(
                        tx,
                        season_id=season,
                        to=target,
                        expected_revision=0,
                        actor=WORKER,
                        now=clock.now(),
                        correlation_id=uuid.uuid4(),
                    )
                outcome = "ok"
            except InvalidTransition:
                outcome = "invalid"
            except Unauthorized:
                outcome = "unauthorized"
            except Exception as exc:  # pragma: no cover - reported below
                outcome = f"unexpected {type(exc).__name__}: {exc}"
            allowed = target in SEASON_TRANSITIONS[source]
            human_only = (source, target) in {
                (SeasonState.PROPOSED, SeasonState.SEASON_APPROVED),
                (SeasonState.PROPOSED, SeasonState.REJECTED),
            }
            if not allowed:
                expected = "invalid"
            elif human_only:
                expected = "unauthorized"
            else:
                expected = "ok"
            if outcome != expected:
                problems.append(
                    f"{source.value}->{target.value}: expected {expected}, got {outcome}"
                )
    assert problems == []


def test_automatic_season_moves_advance_revision_and_append_events(db: Database, clock) -> None:
    with db.transaction() as tx:
        season = _approved_season(tx)
    with db.transaction() as tx:
        revision = transition_season(
            tx,
            season_id=season,
            to=SeasonState.ACTIVE,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            reason="schedule opened",
        )
    assert revision == 1
    row = season_row(db, season)
    assert row["state"] == "ACTIVE" and row["revision"] == 1
    with db.transaction(readonly=True) as tx:
        events = list_events(tx, season)
    assert [e.event_type for e in events][-1] == "season.state_changed"
    assert events[-1].payload == {
        "from": "SEASON_APPROVED",
        "to": "ACTIVE",
        "actor_kind": "SERVICE_WORKER",
        "approval_event_id": None,
        "reason": "schedule opened",
    }


def _approved_season(tx: Tx) -> uuid.UUID:
    return seed_season(tx, state=SeasonState.SEASON_APPROVED.value)


def test_season_approval_by_a_human_binds_scope_hash_version_and_approval(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    scope_hash = "a" * 64
    with db.transaction() as tx:
        human = make_human(tx)
        approval = record_approval_event(
            tx,
            principal=human,
            command=gate1(season, scope_hash, revision=0),
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    with db.transaction() as tx:
        revision = transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
            scope_version=1,
        )
    assert revision == 1
    row = season_row(db, season)
    assert row["state"] == "SEASON_APPROVED"
    assert row["approval_event_id"] == approval
    assert row["approved_scope_hash"] == scope_hash
    assert row["approved_scope_version"] == 1
    assert row["approved_at"] is not None
    with db.transaction(readonly=True) as tx:
        event = list_events(tx, season)[-1]
    assert event.payload["approval_event_id"] == str(approval)
    assert event.payload["actor_kind"] == "HUMAN_OWNER"


@pytest.mark.parametrize("principal_index", range(len(NON_HUMAN)))
def test_non_human_principals_cannot_approve_a_season_even_with_a_real_approval(
    db: Database, clock, principal_index: int
) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    human, approval = _season_approval(db, season, "b" * 64)
    principal = NON_HUMAN[principal_index]
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=principal,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
            scope_version=1,
        )
    assert season_row(db, season)["state"] == "PROPOSED"


def test_human_without_an_approval_event_cannot_approve_or_reject_a_season(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    for target, kwargs in (
        (SeasonState.SEASON_APPROVED, {"scope_version": 1}),
        (SeasonState.REJECTED, {}),
    ):
        with pytest.raises(Unauthorized), db.transaction() as tx:
            transition_season(
                tx,
                season_id=season,
                to=target,
                expected_revision=0,
                actor=human,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                **kwargs,
            )
    assert season_row(db, season)["state"] == "PROPOSED"


def test_approval_for_another_season_or_wrong_action_is_refused(db: Database, clock) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        other = seed_season(tx)
    human, other_approval = _season_approval(db, other, "c" * 64)
    _, reject_here = _season_approval(db, season, "c" * 64, action=ApprovalAction.REJECT)
    with (
        pytest.raises(Unauthorized),
        db.transaction() as tx,
    ):  # approval belongs to a different season
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=other_approval,
            scope_version=1,
        )
    with pytest.raises(Unauthorized), db.transaction() as tx:  # a REJECT cannot approve
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=reject_here,
            scope_version=1,
        )
    with pytest.raises(Unauthorized), db.transaction() as tx:  # an APPROVE cannot reject
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.REJECTED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=other_approval,
        )


def test_rejecting_a_season_records_the_decision_without_binding_it(db: Database, clock) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    human, reject = _season_approval(db, season, "d" * 64, action=ApprovalAction.REJECT)
    with db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.REJECTED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=reject,
        )
    row = season_row(db, season)
    assert row["state"] == "REJECTED"
    assert row["approval_event_id"] is None  # a rejection never binds an approval


def test_scope_version_is_required_for_approval_and_refused_otherwise(db: Database, clock) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    human, approval = _season_approval(db, season, "e" * 64)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.CANCELLED,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            scope_version=1,
        )


def test_stale_season_revision_and_stale_approval_are_refused(db: Database, clock) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    human, approval = _season_approval(db, season, "f" * 64)
    with pytest.raises(StaleRevision), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=7,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
            scope_version=1,
        )
    # The season is edited after the decision: the approval is for an older revision.
    with db.transaction() as tx:
        tx.execute("UPDATE seasons SET revision = revision + 1 WHERE id = %s", (season,))
    with pytest.raises(StaleRevision), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=1,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
            scope_version=1,
        )
    assert season_row(db, season)["state"] == "PROPOSED"


def test_unknown_season_is_not_found(db: Database, clock) -> None:
    with pytest.raises(NotFound), db.transaction() as tx:
        transition_season(
            tx,
            season_id=uuid.uuid4(),
            to=SeasonState.CANCELLED,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )


def test_database_refuses_an_approved_season_bound_to_another_scope(db: Database) -> None:
    """Defence in depth: the trigger refuses a raw SQL approval that does not match its decision."""
    with db.transaction() as tx:
        season = seed_season(tx)
        approval = seed_gate1_approval(tx, season, "1" * 64)
    with pytest.raises(Unauthorized), db.transaction() as tx:
        tx.execute(
            "UPDATE seasons SET state = 'SEASON_APPROVED', approval_event_id = %s, "
            "approved_scope_hash = %s, approved_scope_version = 1, approved_at = now() WHERE id = %s",
            (approval, "2" * 64, season),
        )


# --- episodes ---------------------------------------------------------------------------


def test_episode_transition_matrix_matches_the_frozen_table(db: Database, clock) -> None:
    """Pre-release states x every target. Table-forbidden -> InvalidTransition; human-only or
    revision-gated moves -> Unauthorized without an approval; automatic allowed moves succeed."""
    problems: list[str] = []
    for source in PRE_RELEASE:
        for target in EpisodeState:
            with db.transaction() as tx:
                episode = fresh_episode(tx, state=source.value)
            try:
                with db.transaction() as tx:
                    transition_episode(
                        tx,
                        episode_id=episode,
                        to=target,
                        expected_revision=0,
                        actor=WORKER,
                        now=clock.now(),
                        correlation_id=uuid.uuid4(),
                    )
                outcome = "ok"
            except InvalidTransition:
                outcome = "invalid"
            except Unauthorized:
                outcome = "unauthorized"
            allowed = target in EPISODE_TRANSITIONS[source]
            gated = (source, target) == (
                EpisodeState.AWAITING_FINAL_REVIEW,
                EpisodeState.RELEASE_APPROVED,
            ) or (source is EpisodeState.AWAITING_FINAL_REVIEW and target in REPAIR_STAGES)
            if not allowed:
                expected = "invalid"
            elif gated:
                expected = "unauthorized"
            else:
                expected = "ok"
            if outcome != expected:
                problems.append(
                    f"{source.value}->{target.value}: expected {expected}, got {outcome}"
                )
    assert problems == []


def test_ai_review_repair_is_automatic_and_needs_no_approval(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with db.transaction() as tx:
        revision = transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            reason="shot 4 failed QA",
        )
    assert revision == 1
    assert episode_state(db, episode)[0] == "RENDERING"


def test_episode_release_needs_a_recorded_gate2_approve_bound_to_the_package(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    with db.transaction() as tx:
        approve_package(tx, package, approval)
    with db.transaction() as tx:
        new_revision = transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    assert new_revision == revision + 1
    assert episode_state(db, episode)[0] == "RELEASE_APPROVED"


def test_worker_cannot_release_even_with_a_real_gate2_approve(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    with db.transaction() as tx:
        approve_package(tx, package, approval)
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    assert episode_state(db, episode)[0] == "AWAITING_FINAL_REVIEW"


def test_release_transition_is_refused_by_the_database_without_an_approved_package(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    # The package is still READY: the decision is recorded but the package is not APPROVED.
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    assert episode_state(db, episode)[0] == "AWAITING_FINAL_REVIEW"


def test_gate2_approval_for_another_episode_or_action_is_refused(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        other = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        other_package, other_hash = ready_package(tx, other, tag="other")
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approve_other = _record(db, human, gate2(other, other_hash, revision=0))
    revise_here = _record(
        db, human, gate2(episode, package_hash, revision=revision, action=ApprovalAction.REVISE)
    )
    for approval in (approve_other, revise_here):
        with pytest.raises(Unauthorized), db.transaction() as tx:
            transition_episode(
                tx,
                episode_id=episode,
                to=EpisodeState.RELEASE_APPROVED,
                expected_revision=revision,
                actor=human,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                approval_event_id=approval,
            )


def test_stale_gate2_approval_is_refused_after_the_episode_changes(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    with db.transaction() as tx:
        approve_package(tx, package, approval)
        # Material change after the decision (a recut or outcome bumps the revision).
        tx.execute("UPDATE episodes SET revision = revision + 1 WHERE id = %s", (episode,))
    with pytest.raises(StaleRevision), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision + 1,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    assert episode_state(db, episode)[0] == "AWAITING_FINAL_REVIEW"


def test_revise_returns_the_episode_to_a_repair_stage_once(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    revise = _record(
        db, human, gate2(episode, package_hash, revision=revision, action=ApprovalAction.REVISE)
    )
    with db.transaction() as tx:
        new_revision = transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=revision,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=revise,
            reason="pacing feedback",
        )
    assert episode_state(db, episode)[0] == "RENDERING"
    # Replaying the same revise decision against the old revision is a stale decision.
    with pytest.raises(StaleRevision), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.SCRIPTING,
            expected_revision=revision,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=revise,
        )
    assert new_revision == revision + 1


def test_repair_from_gate2_without_a_revise_decision_is_refused(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approve_like = _record(
        db, human, gate2(episode, package_hash, revision=revision, action=ApprovalAction.REJECT)
    )
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.SCRIPTING,
            expected_revision=revision,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=approve_like,
        )
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.SCRIPTING,
            expected_revision=revision,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )


def test_release_chain_walks_forward_and_terminal_states_stay_terminal(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    with db.transaction() as tx:
        approve_package(tx, package, approval)
    rev = revision
    for target in (
        EpisodeState.RELEASE_APPROVED,
        EpisodeState.SCHEDULED,
        EpisodeState.PUBLISHING,
        EpisodeState.PUBLISHED_VERIFIED,
        EpisodeState.MANAGED,
    ):
        with db.transaction() as tx:
            rev = transition_episode(
                tx,
                episode_id=episode,
                to=target,
                expected_revision=rev,
                actor=human if target is EpisodeState.RELEASE_APPROVED else WORKER,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                approval_event_id=approval if target is EpisodeState.RELEASE_APPROVED else None,
            )
    assert episode_state(db, episode)[0] == "MANAGED"
    for backwards in (
        EpisodeState.PUBLISHED_VERIFIED,
        EpisodeState.SCHEDULED,
        EpisodeState.PLANNED,
    ):
        with pytest.raises(InvalidTransition), db.transaction() as tx:
            transition_episode(
                tx,
                episode_id=episode,
                to=backwards,
                expected_revision=rev,
                actor=WORKER,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
            )


def test_guard_can_refuse_a_transition_and_nothing_is_written(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.REFERENCES.value)
    seen: list[tuple[str, str]] = []

    def identity_guard(tx_, row, target):
        seen.append((row["state"], target.value))
        raise IdentityLockRequired("episode-one identity lock is not created yet")

    with pytest.raises(IdentityLockRequired), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            guards={EpisodeState.RENDERING: [identity_guard]},
        )
    assert seen == [("REFERENCES", "RENDERING")]
    state, _, revision = episode_state(db, episode)
    assert (state, revision) == ("REFERENCES", 0)
    with db.transaction(readonly=True) as tx:
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (episode,)) == 0
        )


def test_guard_for_another_target_is_not_consulted(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.REFERENCES.value)

    def never(tx_, row, target):  # pragma: no cover - must not run
        raise AssertionError("guard for another target ran")

    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            guards={EpisodeState.ASSEMBLING: [never]},
        )
    assert episode_state(db, episode)[0] == "RENDERING"


# --- outcomes ---------------------------------------------------------------------------


def test_recoverable_outcome_holds_progress_until_cleared_with_evidence(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.RENDERING.value)
    with db.transaction() as tx:
        rev = set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.FAILED_INFRA,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="pod create timed out",
        )
    assert rev == 1
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.ASSEMBLING,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    for bad in ("", "   "):
        with pytest.raises(SchemaInvalid), db.transaction() as tx:
            clear_episode_outcome(
                tx,
                episode_id=episode,
                expected_revision=rev,
                actor=WORKER,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                evidence=bad,
            )
    with db.transaction() as tx:
        rev = clear_episode_outcome(
            tx,
            episode_id=episode,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            evidence="pod reconciled: none exists, budget reserve released",
        )
    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.ASSEMBLING,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    state, outcome, _ = episode_state(db, episode)
    assert (state, outcome) == ("ASSEMBLING", None)
    with db.transaction(readonly=True) as tx:
        types = [e.event_type for e in list_events(tx, episode)]
    assert types == ["episode.outcome_set", "episode.outcome_cleared", "episode.state_changed"]


@pytest.mark.parametrize(
    "terminal",
    [EpisodeOutcome.BUDGET_EXHAUSTED, EpisodeOutcome.FAILED_QA, EpisodeOutcome.CANCELLED],
)
def test_terminal_outcome_blocks_transitions_clearing_and_replacement(
    db: Database, clock, terminal
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with db.transaction() as tx:
        rev = set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=terminal,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="terminal for test",
        )
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.AWAITING_FINAL_REVIEW,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        clear_episode_outcome(
            tx,
            episode_id=episode,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            evidence="looks fine now",
        )
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.FAILED_INFRA,
            expected_revision=rev,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="retry",
        )
    assert episode_state(db, episode)[1] == terminal.value


def test_rejected_outcome_needs_a_human_gate2_reject(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    reject = _record(
        db, human, gate2(episode, package_hash, revision=revision, action=ApprovalAction.REJECT)
    )
    for actor, approval in ((WORKER, reject), (human, None)):
        with pytest.raises(Unauthorized), db.transaction() as tx:
            set_episode_outcome(
                tx,
                episode_id=episode,
                outcome=EpisodeOutcome.REJECTED,
                expected_revision=revision,
                actor=actor,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                detail="rejected at gate",
                approval_event_id=approval,
            )
    with db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.REJECTED,
            expected_revision=revision,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="rejected at gate",
            approval_event_id=reject,
        )
    assert episode_state(db, episode)[1] == "REJECTED"


def test_gate2_approve_on_another_revision_is_not_a_rejection(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
    approve = _record(db, human, gate2(episode, package_hash, revision=0))
    with pytest.raises(Unauthorized), db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.REJECTED,
            expected_revision=0,
            actor=human,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="rejected at gate",
            approval_event_id=approve,
        )
    assert episode_state(db, episode)[1] is None


def test_human_only_outcome_must_not_be_set_with_a_stray_approval(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.FAILED_QA,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="qa",
            approval_event_id=uuid.uuid4(),
        )


@pytest.mark.parametrize("detail", ["", "  ", "x" * 2001])
def test_outcome_detail_must_be_a_bounded_non_empty_text(db: Database, clock, detail: str) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.FAILED_INFRA,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail=detail,
        )


def test_clearing_a_non_recoverable_or_missing_outcome_is_refused(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        clear_episode_outcome(
            tx,
            episode_id=episode,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            evidence="nothing to clear",
        )


def test_oversized_event_refuses_the_state_change_and_writes_nothing(db: Database, clock) -> None:
    """The state update and its outbox event are one unit: a rejected event leaves no change."""
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            reason="r" * 20_000,
        )
    state, _, revision = episode_state(db, episode)
    assert (state, revision) == ("AI_REVIEW", 0)
    with db.transaction(readonly=True) as tx:
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (episode,)) == 0
        )


def test_episode_state_change_and_event_commit_or_roll_back_together(db: Database, clock) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
        raise Boom("crash after the update and the event")
    state, _, revision = episode_state(db, episode)
    assert (state, revision) == ("AI_REVIEW", 0)
    with db.transaction(readonly=True) as tx:
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (episode,)) == 0
        )
    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    assert episode_state(db, episode)[0] == "RENDERING"
    with db.transaction(readonly=True) as tx:
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (episode,)) == 1
        )


def test_stale_episode_revision_is_refused_and_unknown_episode_is_not_found(
    db: Database, clock
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with pytest.raises(StaleRevision), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=3,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    with pytest.raises(NotFound), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=uuid.uuid4(),
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )


def test_two_transitions_racing_on_one_revision_let_exactly_one_win(db: Database, clock) -> None:
    import threading

    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def attempt(target: EpisodeState) -> None:
        barrier.wait()
        try:
            with db.transaction() as tx:
                transition_episode(
                    tx,
                    episode_id=episode,
                    to=target,
                    expected_revision=0,
                    actor=WORKER,
                    now=clock.now(),
                    correlation_id=uuid.uuid4(),
                )
            outcome = "won"
        except StaleRevision:
            outcome = "stale"
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=attempt, args=(EpisodeState.RENDERING,)),
        threading.Thread(target=attempt, args=(EpisodeState.AWAITING_FINAL_REVIEW,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == ["stale", "won"]
    state, _, revision = episode_state(db, episode)
    assert revision == 1 and state in {"RENDERING", "AWAITING_FINAL_REVIEW"}


# --- F-1: runtime models and provider webhooks never drive state or outcomes -------------
# The refusal happens before any lock or write. Each refusal test snapshots the rows and the
# whole outbox, then asserts nothing changed.

OBSERVER_MODEL = Principal(
    principal_id="model:observer-01",
    kind=PrincipalKind.RUNTIME_MODEL,
    runtime_role=RuntimeRole.OBSERVER,
)
REFUSED_STATE_ACTORS = pytest.mark.parametrize(
    "actor", [CRITIC, OBSERVER_MODEL, WEBHOOK], ids=["model-critic", "model-observer", "webhook"]
)


def _season_snapshot(db: Database, season) -> tuple:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state, approval_event_id, approved_scope_hash, revision, updated_at "
            "FROM seasons WHERE id = %s",
            (season,),
        )
        own = count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (season,))
        total = count(tx, "SELECT count(*) FROM domain_events")
    return (
        row["state"],
        row["approval_event_id"],
        row["approved_scope_hash"],
        row["revision"],
        row["updated_at"],
        own,
        total,
    )


def _episode_snapshot(db: Database, episode) -> tuple:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state, outcome, outcome_detail, revision, updated_at FROM episodes WHERE id = %s",
            (episode,),
        )
        own = count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (episode,))
        total = count(tx, "SELECT count(*) FROM domain_events")
    return (
        row["state"],
        row["outcome"],
        row["outcome_detail"],
        row["revision"],
        row["updated_at"],
        own,
        total,
    )


def _season_transition(db: Database, clock):
    with db.transaction() as tx:
        season = seed_season(tx, state=SeasonState.SEASON_APPROVED.value)

    def attempt(actor):
        with db.transaction() as tx:
            return transition_season(
                tx,
                season_id=season,
                to=SeasonState.ACTIVE,
                expected_revision=0,
                actor=actor,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                reason="auto",
            )

    return attempt, lambda: _season_snapshot(db, season)


def _episode_transition(db: Database, clock):
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)

    def attempt(actor):
        with db.transaction() as tx:
            return transition_episode(
                tx,
                episode_id=episode,
                to=EpisodeState.RENDERING,
                expected_revision=0,
                actor=actor,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
            )

    return attempt, lambda: _episode_snapshot(db, episode)


def _set_outcome(db: Database, clock):
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.ASSEMBLING.value)

    def attempt(actor):
        with db.transaction() as tx:
            return set_episode_outcome(
                tx,
                episode_id=episode,
                outcome=EpisodeOutcome.RIGHTS_UNCLEARED,
                expected_revision=0,
                actor=actor,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                detail="voice rights unclear",
            )

    return attempt, lambda: _episode_snapshot(db, episode)


def _clear_outcome(db: Database, clock):
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.RENDERING.value)
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.CAPABILITY_UNAVAILABLE,
            expected_revision=0,
            actor=SCHEDULER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="preset not enabled",
        )

    def attempt(actor):
        with db.transaction() as tx:
            return clear_episode_outcome(
                tx,
                episode_id=episode,
                expected_revision=1,
                actor=actor,
                now=clock.now(),
                correlation_id=uuid.uuid4(),
                evidence="model claims the preset is back",
            )

    return attempt, lambda: _episode_snapshot(db, episode)


STATE_WRITERS = {
    "transition_season": _season_transition,
    "transition_episode": _episode_transition,
    "set_episode_outcome": _set_outcome,
    "clear_episode_outcome": _clear_outcome,
}


@pytest.mark.parametrize("writer", list(STATE_WRITERS))
@REFUSED_STATE_ACTORS
def test_models_and_webhooks_are_refused_by_every_state_writer_before_any_write(
    db: Database, clock, writer: str, actor
) -> None:
    attempt, snapshot = STATE_WRITERS[writer](db, clock)
    before = snapshot()
    with pytest.raises(Unauthorized):
        attempt(actor)
    assert snapshot() == before  # state, outcome, revision, updated_at and the outbox are unchanged


@REFUSED_STATE_ACTORS
def test_models_and_webhooks_cannot_reject_a_season_even_with_a_real_gate1_reject(
    db: Database, clock, actor
) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    reject = _record(db, human, gate1(season, "9" * 64, revision=0, action=ApprovalAction.REJECT))
    before = _season_snapshot(db, season)
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.REJECTED,
            expected_revision=0,
            actor=actor,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=reject,
        )
    assert _season_snapshot(db, season) == before


@REFUSED_STATE_ACTORS
def test_models_and_webhooks_cannot_drive_a_gated_repair_even_with_a_revise(
    db: Database, clock, actor
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    revise = _record(
        db, human, gate2(episode, package_hash, revision=revision, action=ApprovalAction.REVISE)
    )
    before = _episode_snapshot(db, episode)
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=revision,
            actor=actor,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            approval_event_id=revise,
        )
    assert _episode_snapshot(db, episode) == before


@pytest.mark.parametrize("operator", [SERVICE_WORKER, SCHEDULER], ids=["worker", "scheduler"])
def test_operators_may_move_a_season_automatically(db: Database, clock, operator) -> None:
    with db.transaction() as tx:
        season = seed_season(tx, state=SeasonState.SEASON_APPROVED.value)
    with db.transaction() as tx:
        revision = transition_season(
            tx,
            season_id=season,
            to=SeasonState.ACTIVE,
            expected_revision=0,
            actor=operator,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    assert revision == 1 and season_row(db, season)["state"] == "ACTIVE"


@pytest.mark.parametrize("operator", [SERVICE_WORKER, SCHEDULER], ids=["worker", "scheduler"])
def test_operators_may_move_an_episode_and_set_and_clear_outcomes(
    db: Database, clock, operator
) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.AI_REVIEW.value)
    with db.transaction() as tx:
        rev = transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=operator,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
        )
    with db.transaction() as tx:
        rev = set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=EpisodeOutcome.FAILED_INFRA,
            expected_revision=rev,
            actor=operator,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="pod create timed out",
        )
    assert episode_state(db, episode)[1] == "FAILED_INFRA"
    with db.transaction() as tx:
        rev = clear_episode_outcome(
            tx,
            episode_id=episode,
            expected_revision=rev,
            actor=operator,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            evidence="pod reconciled: none exists",
        )
    assert episode_state(db, episode) == ("RENDERING", None, rev)


# --- V-6: clearing an outcome needs more than a string -----------------------------------
# RIGHTS_UNCLEARED and CAPABILITY_UNAVAILABLE need a registry recheck with no blockers.
# NEEDS_RECONCILIATION needs no in-flight provider operation linked to the episode.
# FAILED_INFRA clears on evidence alone. Every case is run for both operator kinds.

from microdrama.contracts.cost import ProviderOperationResult  # noqa: E402
from microdrama.contracts.enums import Provenance, ProviderOperationState  # noqa: E402
from microdrama.contracts.errors import GateNotReady  # noqa: E402
from microdrama.contracts.jobs import EpisodeStepInput  # noqa: E402
from microdrama.core.jobs import JobService  # noqa: E402
from microdrama.core.provider_ops import begin as begin_op  # noqa: E402
from microdrama.core.provider_ops import record_result as record_op  # noqa: E402
from microdrama.testing.fakes import SequentialIds  # noqa: E402

OPERATORS = pytest.mark.parametrize(
    "operator", [SERVICE_WORKER, SCHEDULER], ids=["worker", "scheduler"]
)
REGISTRY_OUTCOMES = pytest.mark.parametrize(
    "outcome",
    [EpisodeOutcome.RIGHTS_UNCLEARED, EpisodeOutcome.CAPABILITY_UNAVAILABLE],
    ids=["rights", "capability"],
)


def _outcome_episode(db: Database, clock, outcome: EpisodeOutcome) -> uuid.UUID:
    """An episode holding ``outcome`` (set by the scheduler), at revision 1."""
    with db.transaction() as tx:
        episode = fresh_episode(tx, state=EpisodeState.RENDERING.value)
    with db.transaction() as tx:
        set_episode_outcome(
            tx,
            episode_id=episode,
            outcome=outcome,
            expected_revision=0,
            actor=SCHEDULER,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            detail="set by the scheduler for the test",
        )
    return episode


def _job_for_episode(db: Database, clock, episode: uuid.UUID) -> uuid.UUID:
    jobs = JobService(db, clock, SequentialIds(uuid.uuid4().hex))
    with db.transaction() as tx:
        return jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"v6:{uuid.uuid4().hex}",
            payload=EpisodeStepInput(episode_id=episode),
        ).job_id


def _op_for_episode(
    db, clock, job, *, state: ProviderOperationState | None, episode=None
) -> uuid.UUID:
    with db.transaction() as tx:
        op = begin_op(
            tx,
            provider="fake-comfy",
            operation_kind="comfy.queue_prompt",
            client_token=f"v6-{uuid.uuid4().hex}",
            request_hash=H,
            deadline_at=clock.now() + timedelta(minutes=10),
            job_id=job,
            episode_id=episode,
            now=clock.now(),
        )
    if state is not None:
        result = ProviderOperationResult(
            operation_id=op.operation_id,
            state=state,
            error_code="FAKE_REJECTED" if state is ProviderOperationState.FAILED else None,
            provenance=Provenance.FAKE_SYNTHETIC,
        )
        with db.transaction() as tx:
            record_op(tx, op.operation_id, result, now=clock.now())
    return op.operation_id


def _clear(db, clock, episode, *, actor, evidence="ok", recheck=None):
    with db.transaction() as tx:
        return clear_episode_outcome(
            tx,
            episode_id=episode,
            expected_revision=1,
            actor=actor,
            now=clock.now(),
            correlation_id=uuid.uuid4(),
            evidence=evidence,
            recheck=recheck,
        )


@OPERATORS
@REGISTRY_OUTCOMES
def test_registry_outcome_without_a_recheck_is_refused_and_nothing_is_written(
    db, clock, outcome, operator
) -> None:
    episode = _outcome_episode(db, clock, outcome)
    before = _episode_snapshot(db, episode)
    with pytest.raises(SchemaInvalid, match="recheck"):
        _clear(db, clock, episode, actor=operator, evidence="ok")  # the evidence-only probe
    assert _episode_snapshot(db, episode) == before


@OPERATORS
@REGISTRY_OUTCOMES
def test_registry_outcome_with_blockers_is_gate_not_ready_and_nothing_is_written(
    db, clock, outcome, operator
) -> None:
    episode = _outcome_episode(db, clock, outcome)
    before = _episode_snapshot(db, episode)
    blockers = ["voice clone licence expired", "preset not measured"]
    with pytest.raises(GateNotReady) as err:
        _clear(db, clock, episode, actor=operator, evidence="ok", recheck=lambda tx, row: blockers)
    assert err.value.http_status == 409 and err.value.details["blockers"] == blockers
    assert _episode_snapshot(db, episode) == before


@OPERATORS
@REGISTRY_OUTCOMES
def test_registry_outcome_clears_when_the_recheck_reports_no_blockers(
    db, clock, outcome, operator
) -> None:
    episode = _outcome_episode(db, clock, outcome)
    seen: list[tuple[str, dict]] = []

    def clean_recheck(tx, row):
        seen.append((type(tx).__name__, row))
        return []

    revision = _clear(
        db, clock, episode, actor=operator, evidence="registry rows verified", recheck=clean_recheck
    )
    assert revision == 2
    assert episode_state(db, episode) == ("RENDERING", None, 2)
    ((tx_name, row),) = seen
    assert tx_name == "Tx" and row["outcome"] == outcome.value  # the recheck saw the locked row
    with db.transaction(readonly=True) as tx:
        assert [e.event_type for e in list_events(tx, episode)][-1] == "episode.outcome_cleared"


@OPERATORS
@pytest.mark.parametrize(
    "state",
    [
        ProviderOperationState.PENDING_SUBMIT,
        ProviderOperationState.SUBMITTED,
        ProviderOperationState.RUNNING,
        ProviderOperationState.UNKNOWN,
    ],
    ids=["pending", "submitted", "running", "unknown"],
)
@pytest.mark.parametrize("linked_by", ["episode_id", "job"])
def test_needs_reconciliation_is_held_while_a_linked_operation_is_in_flight(
    db, clock, operator, state, linked_by
) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.NEEDS_RECONCILIATION)
    job = _job_for_episode(db, clock, episode)
    _op_for_episode(
        db,
        clock,
        job,
        state=None if state is ProviderOperationState.PENDING_SUBMIT else state,
        episode=episode if linked_by == "episode_id" else None,
    )
    before = _episode_snapshot(db, episode)
    with pytest.raises(InvalidTransition, match="in flight"):
        _clear(db, clock, episode, actor=operator, evidence="ok")
    assert _episode_snapshot(db, episode) == before


@OPERATORS
@pytest.mark.parametrize(
    "state",
    [
        ProviderOperationState.SUCCEEDED,
        ProviderOperationState.FAILED,
        ProviderOperationState.NOT_FOUND,
    ],
    ids=["succeeded", "failed", "not_found"],
)
def test_needs_reconciliation_clears_once_linked_operations_are_settled(
    db, clock, operator, state
) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.NEEDS_RECONCILIATION)
    _op_for_episode(db, clock, _job_for_episode(db, clock, episode), state=state, episode=episode)
    assert _clear(db, clock, episode, actor=operator, evidence="provider state reconciled") == 2
    assert episode_state(db, episode)[1] is None


@OPERATORS
def test_needs_reconciliation_clears_with_no_linked_operation(db, clock, operator) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.NEEDS_RECONCILIATION)
    assert _clear(db, clock, episode, actor=operator, evidence="nothing was ever submitted") == 2


@OPERATORS
def test_failed_infra_clears_on_evidence_for_operators(db, clock, operator) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.FAILED_INFRA)
    assert _clear(db, clock, episode, actor=operator, evidence="pod reconciled") == 2


@OPERATORS
@pytest.mark.parametrize("evidence", ["", "  "])
def test_failed_infra_refuses_empty_evidence(db, clock, operator, evidence: str) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.FAILED_INFRA)
    with pytest.raises(SchemaInvalid):
        _clear(db, clock, episode, actor=operator, evidence=evidence)
    assert episode_state(db, episode)[1] == "FAILED_INFRA"


def test_an_owner_may_clear_failed_infra_with_evidence(db, clock) -> None:
    episode = _outcome_episode(db, clock, EpisodeOutcome.FAILED_INFRA)
    with db.transaction() as tx:
        owner = make_human(tx)
    assert _clear(db, clock, episode, actor=owner, evidence="owner verified the pod is gone") == 2

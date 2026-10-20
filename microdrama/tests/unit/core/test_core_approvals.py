"""Approval recording (record_approval_event) against the real database."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from core_support import (
    NON_HUMAN,
    T0,
    H,
    count,
    fresh_episode,
    gate1,
    gate2,
    make_human,
    new_key,
    ready_package,
)

from microdrama.contracts.enums import ApprovalAction, FeedbackCategory, PrincipalKind
from microdrama.contracts.errors import (
    NotFound,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.core.approvals import record_approval_event
from microdrama.core.events import list_events
from microdrama.persistence import Database
from microdrama.testing.seed import seed_season

pytestmark = pytest.mark.db


def _record(db: Database, principal, command) -> uuid.UUID:
    with db.transaction() as tx:
        return record_approval_event(
            tx, principal=principal, command=command, now=T0, correlation_id=uuid.uuid4()
        )


def test_every_non_human_principal_is_refused_and_nothing_is_written(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
    for principal in NON_HUMAN:
        with pytest.raises(Unauthorized), db.transaction() as tx:
            record_approval_event(
                tx,
                principal=principal,
                command=gate1(season, "3" * 64, revision=0),
                now=T0,
                correlation_id=uuid.uuid4(),
            )
        with pytest.raises(Unauthorized), db.transaction() as tx:
            record_approval_event(
                tx,
                principal=principal,
                command=gate2(episode, package_hash, revision=0),
                now=T0,
                correlation_id=uuid.uuid4(),
            )
    with db.transaction(readonly=True) as tx:
        assert count(tx, "SELECT count(*) FROM approval_events") == 0
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE event_type = 'approval.recorded'")
            == 0
        )


def test_stale_expected_revision_is_refused_before_anything_is_written(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    with pytest.raises(StaleRevision), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=human,
            command=gate1(season, "4" * 64, revision=5),
            now=T0,
            correlation_id=uuid.uuid4(),
        )
    with db.transaction(readonly=True) as tx:
        assert count(tx, "SELECT count(*) FROM approval_events") == 0


def test_a_second_decision_on_the_same_revision_is_a_409_not_a_success(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    first = _record(db, human, gate1(season, "5" * 64, revision=0))
    with pytest.raises(StaleRevision) as err, db.transaction() as tx:
        record_approval_event(
            tx,
            principal=human,
            command=gate1(season, "5" * 64, revision=0, action=ApprovalAction.REJECT),
            now=T0,
            correlation_id=uuid.uuid4(),
        )
    assert err.value.http_status == 409
    assert err.value.details["constraint"] == "approval_events_one_per_revision"
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT id, action FROM approval_events WHERE entity_id = %s", (season,))
    assert [(r["id"], r["action"]) for r in rows] == [(first, "APPROVE")]


def test_reusing_an_idempotency_key_for_another_decision_is_refused(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        other = seed_season(tx)
        human = make_human(tx)
    command = gate1(season, "6" * 64, revision=0)
    _record(db, human, command)
    reused = ApprovalCommand(
        gate=command.gate,
        action=command.action,
        entity_id=other,
        expected_revision=0,
        package_hash="6" * 64,
        idempotency_key=command.idempotency_key,
    )
    with pytest.raises(Exception) as err, db.transaction() as tx:
        record_approval_event(
            tx, principal=human, command=reused, now=T0, correlation_id=uuid.uuid4()
        )
    assert err.value.http_status == 409


def test_a_revoked_session_is_refused_by_the_database(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        revoked = make_human(tx, revoked=True)
    with pytest.raises(Unauthorized), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=revoked,
            command=gate1(season, "7" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
        )


def test_an_expired_session_is_refused_by_the_database(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        from microdrama.contracts.enums import PrincipalKind
        from microdrama.contracts.principals import Principal
        from microdrama.testing.seed import now_utc, seed_human_session, seed_owner

        owner = seed_owner(tx)
        session = seed_human_session(
            tx, owner, expires_in=timedelta(seconds=1), created_at=now_utc() - timedelta(hours=2)
        )
        expired = Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )
    with pytest.raises(Unauthorized), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=expired,
            command=gate1(season, "8" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
        )


def test_a_principal_bound_to_someone_elses_session_is_refused(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        owner_a = make_human(tx)
        owner_b = make_human(tx)
    forged = Principal(
        principal_id=owner_b.principal_id,
        kind=PrincipalKind.HUMAN_OWNER,
        session_id=owner_a.session_id,
    )
    with pytest.raises(Unauthorized), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=forged,
            command=gate1(season, "9" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
        )


def test_hooks_run_inside_the_same_transaction_and_see_the_decision(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    calls: list[dict] = []

    class Hook:
        def on_recorded(self, tx, *, approval_event_id, command, principal):
            visible = tx.fetchval(
                "SELECT count(*) FROM approval_events WHERE id = %s", (approval_event_id,)
            )
            calls.append(
                {"visible_in_tx": visible, "action": command.action, "who": principal.kind}
            )

    approval = None
    with db.transaction() as tx:
        approval = record_approval_event(
            tx,
            principal=human,
            command=gate1(season, "a" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
            hooks=[Hook()],
        )
    assert calls == [{"visible_in_tx": 1, "action": ApprovalAction.APPROVE, "who": human.kind}]
    with db.transaction(readonly=True) as tx:
        assert count(tx, "SELECT count(*) FROM approval_events WHERE id = %s", (approval,)) == 1


def test_a_failing_hook_rolls_back_the_approval_and_its_event(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)

    class IdentityLockFailed(RuntimeError):
        pass

    class FailingHook:
        def on_recorded(self, tx, **_):
            raise IdentityLockFailed("identity lock could not be created")

    with pytest.raises(IdentityLockFailed), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=human,
            command=gate1(season, "b" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
            hooks=[FailingHook()],
        )
    with db.transaction(readonly=True) as tx:
        assert (
            count(tx, "SELECT count(*) FROM approval_events WHERE entity_id = %s", (season,)) == 0
        )
        assert (
            count(tx, "SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (season,)) == 0
        )
    # The decision can be recorded again once the hook is healthy.
    _record(db, human, gate1(season, "b" * 64, revision=0))


def test_revise_writes_one_feedback_row_per_item_and_an_outbox_event(db: Database) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
    feedback = [
        TimecodedFeedback(
            category=FeedbackCategory.SUBTITLES,
            start_ms=12_000,
            end_ms=15_500,
            comment="subtitle says 5,000 baht; dialogue says 50,000",
        ),
        TimecodedFeedback(
            category=FeedbackCategory.PACING,
            start_ms=0,
            end_ms=800,
            comment="slow open",
            shot_id="sh-03",
        ),
    ]
    command = ApprovalCommand(
        gate=gate2(episode, package_hash, revision=0).gate,
        action=ApprovalAction.REVISE,
        entity_id=episode,
        expected_revision=0,
        package_hash=package_hash,
        idempotency_key=new_key("revise"),
        feedback=feedback,
    )
    approval = _record(db, human, command)
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT category, start_ms, end_ms, shot_key FROM feedback_events "
            "WHERE approval_event_id = %s ORDER BY start_ms",
            (approval,),
        )
        events = list_events(tx, episode)
    assert [(r["category"], r["start_ms"], r["shot_key"]) for r in rows] == [
        ("pacing", 0, "sh-03"),
        ("subtitles", 12_000, None),
    ]
    recorded = [e for e in events if e.event_type == "approval.recorded"]
    assert len(recorded) == 1
    assert recorded[0].payload["approval_event_id"] == str(approval)
    assert recorded[0].payload["action"] == "REVISE"


def test_approval_rows_store_the_command_hash_and_bound_hashes(db: Database) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        _, package_hash = ready_package(tx, episode)
        human = make_human(tx)
    command = gate2(episode, package_hash, revision=0)
    approval = _record(db, human, command)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM approval_events WHERE id = %s", (approval,))
    assert row["command_hash"] == canonical_hash(command)
    assert row["package_hash"] == package_hash
    assert row["media_hashes"] == [H]
    assert row["management_policy_hash"] == H and row["release_scope_hash"] == H
    assert row["actor_owner_id"] is not None and row["actor_session_id"] == human.session_id
    assert row["entity_type"] == "episode"


def test_recording_does_not_move_the_entity_revision(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    _record(db, human, gate1(season, "c" * 64, revision=0))
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT revision FROM seasons WHERE id = %s", (season,)) == 0


def test_unknown_entity_is_not_found(db: Database) -> None:
    with db.transaction() as tx:
        human = make_human(tx)
    with pytest.raises(NotFound), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=human,
            command=gate1(uuid.uuid4(), "d" * 64, revision=0),
            now=T0,
            correlation_id=uuid.uuid4(),
        )


def test_gate2_decisions_need_a_matching_decidable_package(db: Database) -> None:
    """The database binds each Gate 2 decision to a package of the episode in a decidable state."""
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        blocked_package, blocked_hash = ready_package(tx, episode, status="BLOCKED", tag="blocked")
        human = make_human(tx)
    # An APPROVE needs a READY package with no blockers: a BLOCKED one is refused.
    with pytest.raises(Unauthorized):
        _record(db, human, gate2(episode, blocked_hash, revision=0))
    # A hash that names no package of this episode is refused.
    with pytest.raises(Unauthorized):
        _record(db, human, gate2(episode, "f" * 64, revision=0))
    # A REVISE may target a BLOCKED package: the review can still ask for changes.
    revise = _record(
        db, human, gate2(episode, blocked_hash, revision=0, action=ApprovalAction.REVISE)
    )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM approval_events WHERE id = %s", (revise,)) == 1
        assert (
            tx.fetchval("SELECT status FROM release_packages WHERE id = %s", (blocked_package,))
            == "BLOCKED"
        )

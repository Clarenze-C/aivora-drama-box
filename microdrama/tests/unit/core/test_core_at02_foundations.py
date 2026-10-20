"""AT-02 foundations (T004 scope): principals, replays, stale and changed approvals, uncertainty.

The gate-specific readiness rules belong to T008. These tests cover what core guarantees: workers
and models never approve; a decision binds one revision; a media change needs a fresh Gate 2;
ambiguous external work never becomes success.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from core_support import (
    NON_HUMAN,
    T0,
    WORKER,
    H,
    approve_package,
    episode_state,
    fresh_episode,
    gate1,
    gate2,
    make_human,
    make_reservation,
    ready_package,
)

from microdrama.contracts.cost import ProviderOperationResult
from microdrama.contracts.enums import (
    EpisodeState,
    JobStatus,
    Provenance,
    ProviderOperationState,
    QueueName,
    SeasonState,
)
from microdrama.contracts.errors import Conflict, InvalidTransition, StaleRevision, Unauthorized
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.core.approvals import record_approval_event
from microdrama.core.jobs import JobService, NeedsReconciliation, Succeeded
from microdrama.core.provider_ops import begin, record_result, resubmit_allowed
from microdrama.core.state_machine import transition_episode, transition_season
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.seed import seed_season

pytestmark = pytest.mark.db


def _record(db: Database, principal, command) -> uuid.UUID:
    with db.transaction() as tx:
        return record_approval_event(
            tx, principal=principal, command=command, now=T0, correlation_id=uuid.uuid4()
        )


@pytest.mark.parametrize("principal", NON_HUMAN, ids=lambda p: p.kind.value)
def test_workers_and_models_cannot_approve_or_move_a_gated_episode(db: Database, principal) -> None:
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
            actor=principal,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    with pytest.raises(Unauthorized), db.transaction() as tx:
        record_approval_event(
            tx,
            principal=principal,
            command=gate2(episode, package_hash, revision=revision + 1),
            now=T0,
            correlation_id=uuid.uuid4(),
        )
    assert episode_state(db, episode)[0] == "AWAITING_FINAL_REVIEW"


def test_a_worker_cannot_approve_a_season_even_with_a_real_gate1_decision(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        human = make_human(tx)
    approval = _record(db, human, gate1(season, "e" * 64, revision=0))
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_season(
            tx,
            season_id=season,
            to=SeasonState.SEASON_APPROVED,
            expected_revision=0,
            actor=NON_HUMAN[0],
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
            scope_version=1,
        )


def test_a_replayed_final_approval_cannot_release_twice(db: Database) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    approval = _record(db, human, gate2(episode, package_hash, revision=revision))
    with db.transaction() as tx:
        approve_package(tx, package, approval)
    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    with pytest.raises(StaleRevision), db.transaction() as tx:  # the same decision, replayed
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )
    with pytest.raises(InvalidTransition), db.transaction() as tx:  # and the episode has moved on
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision + 1,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=approval,
        )


def test_a_material_media_change_requires_the_same_gate2_again(db: Database) -> None:
    """Package A is decided; the media changes. A is superseded, B is ready, and the episode
    revision moves (a material change is a new revision). A's decision is stale and cannot release
    B; A cannot be re-approved; B needs its own Gate 2 decision at the new revision."""
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package_a, hash_a = ready_package(tx, episode, tag="media-a")
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    decision_a = _record(db, human, gate2(episode, hash_a, revision=revision))
    with db.transaction() as tx:
        tx.execute("UPDATE release_packages SET status = 'SUPERSEDED' WHERE id = %s", (package_a,))
        package_b, hash_b = ready_package(tx, episode, version=2, tag="media-b")
        tx.execute("UPDATE episodes SET revision = revision + 1 WHERE id = %s", (episode,))
    changed = revision + 1
    assert hash_a != hash_b
    with pytest.raises(StaleRevision), db.transaction() as tx:  # the old decision is stale
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=changed,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=decision_a,
        )
    with pytest.raises(Conflict), db.transaction() as tx:  # a superseded package cannot be approved
        approve_package(tx, package_a, decision_a)
    decision_b = _record(db, human, gate2(episode, hash_b, revision=changed))
    with db.transaction() as tx:
        approve_package(tx, package_b, decision_b)
    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=changed,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
            approval_event_id=decision_b,
        )
    assert episode_state(db, episode)[0] == "RELEASE_APPROVED"


def test_uncertain_external_work_is_never_reported_as_success(db: Database) -> None:
    """Free text cannot turn an uncertain provider operation into success. A recorded provider
    success can, and only then."""
    clock = FakeClock(T0)
    jobs = JobService(db, clock, SequentialIds("at02"))
    with db.transaction() as tx:
        queued = jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key="at02:uncertain",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    claimed = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=60_000, now=T0)
    with db.transaction() as tx:
        op = begin(
            tx,
            provider="fake-comfy",
            operation_kind="comfy.queue_prompt",
            client_token="at02-op",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=1),
            job_id=claimed.id,
            now=T0,
            reservation_id=make_reservation(db),
        )
    jobs.finish(claimed.id, worker_id="w", outcome=NeedsReconciliation(detail="no reply"), now=T0)
    assert jobs.get(queued.job_id).status is JobStatus.NEEDS_RECONCILIATION
    with pytest.raises(InvalidTransition), db.transaction() as tx:  # no blind resubmission
        resubmit_allowed(tx, op.operation_id, now=T0)
    with pytest.raises(Conflict):  # the old holder cannot declare success
        jobs.finish(claimed.id, worker_id="w", outcome=Succeeded(result={"guess": 1}), now=T0)
    # Free-text success is refused while the provider operation is still PENDING_SUBMIT.
    with pytest.raises(InvalidTransition, match="not all recorded successes"):
        jobs.resolve_reconciliation(
            queued.job_id,
            resolution="SUCCEEDED",
            evidence="provider receipt present",
            actor=WORKER,
            now=T0,
        )
    assert jobs.get(queued.job_id).status is JobStatus.NEEDS_RECONCILIATION
    # Only a success the provider reported through record_result makes success possible.
    with db.transaction() as tx:
        record_result(
            tx,
            op.operation_id,
            ProviderOperationResult(
                operation_id=op.operation_id,
                state=ProviderOperationState.SUCCEEDED,
                provenance=Provenance.FAKE_SYNTHETIC,
            ),
            now=T0,
        )
    resolved = jobs.resolve_reconciliation(
        queued.job_id,
        resolution="SUCCEEDED",
        evidence="provider receipt present",
        actor=WORKER,
        now=T0,
    )
    assert resolved.status is JobStatus.SUCCEEDED and resolved.outcome["reconciled"] is True


def test_a_human_without_a_decision_cannot_release_an_episode(db: Database) -> None:
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        ready_package(tx, episode)
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    with pytest.raises(Unauthorized), db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RELEASE_APPROVED,
            expected_revision=revision,
            actor=human,
            now=T0,
            correlation_id=uuid.uuid4(),
        )
    assert episode_state(db, episode)[0] == "AWAITING_FINAL_REVIEW"

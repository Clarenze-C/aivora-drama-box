"""Durable jobs: idempotent enqueue, leased claims, outcomes, recovery and reconciliation (real DB)."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest

from microdrama.contracts.cost import ProviderOperationState
from microdrama.contracts.enums import JobStatus, QueueName
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE, EpisodeStepInput, PlatformPostRef
from microdrama.contracts.routes import JobStatusView
from microdrama.core.events import list_events
from microdrama.core.jobs import (
    Failed,
    JobService,
    NeedsReconciliation,
    RetryLater,
    Succeeded,
    WaitExternal,
)
from microdrama.core.provider_ops import begin as begin_provider_op
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = pytest.mark.db
LEASE = 60_000  # 60 s
H = canonical_hash({"request": "fixture"})


@pytest.fixture
def jobs(db: Database, clock: FakeClock, ids: SequentialIds) -> JobService:
    return JobService(db, clock, ids)


def _enqueue(db: Database, jobs: JobService, key: str, *, episode=None, **kwargs):
    payload = EpisodeStepInput(episode_id=episode or uuid.uuid4())
    with db.transaction() as tx:
        return jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=key,
            payload=payload,
            **kwargs,
        )


def _job_events(db: Database, job_id) -> list[str]:
    with db.transaction(readonly=True) as tx:
        return [e.event_type for e in list_events(tx, job_id)]


# --- enqueue ----------------------------------------------------------------------------


def test_enqueue_takes_queue_and_type_from_the_spec_and_emits_an_event(db, jobs) -> None:
    result = _enqueue(db, jobs, "qa:ep1:cycle1", max_attempts=3)
    assert result.created is True
    job = jobs.get(result.job_id)
    spec = JOB_SPECS_BY_TYPE["qa.technical"]
    assert (job.queue, job.job_type, job.job_version) == (spec.queue, spec.job_type, spec.version)
    assert job.status is JobStatus.QUEUED and job.attempt == 0 and job.max_attempts == 3
    assert job.input_hash == canonical_hash(
        EpisodeStepInput(episode_id=uuid.UUID(job.input["episode_id"]))
    )
    assert _job_events(db, job.id) == ["job.enqueued"]


def test_same_semantic_key_and_same_input_returns_the_existing_job(db, jobs) -> None:
    episode = uuid.uuid4()
    first = _enqueue(db, jobs, "qa:ep2:cycle1", episode=episode)
    again = _enqueue(db, jobs, "qa:ep2:cycle1", episode=episode)
    assert again.created is False and again.job_id == first.job_id
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM jobs WHERE semantic_key = 'qa:ep2:cycle1'") == 1
    assert _job_events(db, first.job_id) == ["job.enqueued"]  # no duplicate work recorded


def test_same_semantic_key_with_different_input_is_an_idempotency_conflict(db, jobs) -> None:
    _enqueue(db, jobs, "qa:ep3:cycle1", episode=uuid.uuid4())
    with pytest.raises(IdempotencyConflict) as err, db.transaction() as tx:
        jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key="qa:ep3:cycle1",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    assert err.value.http_status == 409


def test_same_semantic_key_for_a_different_job_type_is_a_conflict(db, jobs) -> None:
    episode = uuid.uuid4()
    _enqueue(db, jobs, "shared:key:1", episode=episode)
    with pytest.raises(IdempotencyConflict), db.transaction() as tx:
        jobs.enqueue(
            tx,
            job_type="publish.schedule_release",
            semantic_key="shared:key:1",
            payload=EpisodeStepInput(episode_id=episode),
        )


def test_enqueue_refuses_unknown_types_and_mismatched_payloads(db, jobs) -> None:
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        jobs.enqueue(
            tx,
            job_type="no.such.job",
            semantic_key="k:1",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key="k:2",
            payload=PlatformPostRef(platform_post_id=uuid.uuid4()),
        )


@pytest.mark.parametrize("max_attempts", [0, 11])
def test_enqueue_bounds_max_attempts(db, jobs, max_attempts: int) -> None:
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"k:max:{max_attempts}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
            max_attempts=max_attempts,
        )


def test_the_queue_is_chosen_by_the_spec_so_a_publication_job_lands_on_publication(
    db, jobs
) -> None:
    with db.transaction() as tx:
        result = jobs.enqueue(
            tx,
            job_type="publish.poll_status",
            semantic_key="poll:post-1",
            payload=PlatformPostRef(platform_post_id=uuid.uuid4()),
        )
    assert jobs.get(result.job_id).queue is QueueName.PUBLICATION


# --- claims -----------------------------------------------------------------------------


def test_claim_leases_one_due_job_and_bumps_attempt(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "claim:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=LEASE)
    assert job is not None and job.id == result.job_id
    assert job.status is JobStatus.RUNNING and job.attempt == 1
    assert job.lease_owner == "w-1" and job.lease_expires_at == clock.now() + timedelta(
        milliseconds=LEASE
    )
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w-2", lease_ms=LEASE) is None
    assert "job.claimed" in _job_events(db, job.id)


def test_claims_respect_queue_priority_and_run_after(db, jobs, clock) -> None:
    later = _enqueue(
        db, jobs, "order:late", priority=100, run_after=clock.now() + timedelta(seconds=30)
    )
    low = _enqueue(db, jobs, "order:low", priority=200)
    high = _enqueue(db, jobs, "order:high", priority=50)
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE).id == high.job_id
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE).id == low.job_id
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE) is None  # not due yet
    clock.advance(seconds=31)
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE).id == later.job_id


def test_claims_never_cross_queues(db, jobs) -> None:
    _enqueue(db, jobs, "queue:prod")
    assert jobs.claim(QueueName.PUBLICATION, worker_id="w", lease_ms=LEASE) is None


def test_concurrent_claimers_never_share_a_job(db, jobs) -> None:
    total = 24
    for i in range(total):
        _enqueue(db, jobs, f"race:{i}")
    claimed: list[uuid.UUID] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def claimer(worker: int) -> None:
        barrier.wait()
        while True:
            job = jobs.claim(QueueName.PRODUCTION, worker_id=f"w-{worker}", lease_ms=LEASE)
            if job is None:
                return
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=claimer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(claimed) == total
    assert len(set(claimed)) == total


def test_polling_a_waiting_job_is_not_a_new_attempt(db, jobs, clock) -> None:
    _enqueue(db, jobs, "poll:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    waiting = jobs.finish(
        job.id, worker_id="w", outcome=WaitExternal(external_id="prov-42", poll_after_ms=5_000)
    )
    assert waiting.status is JobStatus.WAITING_EXTERNAL and waiting.external_id == "prov-42"
    assert waiting.attempt == 1
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE) is None  # poll not due
    clock.advance(ms=5_000)
    polled = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    assert polled.id == job.id and polled.attempt == 1 and polled.status is JobStatus.RUNNING
    done = jobs.finish(job.id, worker_id="w", outcome=Succeeded(result={"verified": True}))
    assert done.status is JobStatus.SUCCEEDED and done.attempt == 1


# --- leases and the zombie worker -------------------------------------------------------


def test_heartbeat_extends_only_the_holders_live_lease(db, jobs, clock) -> None:
    _enqueue(db, jobs, "hb:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w-a", lease_ms=LEASE)
    clock.advance(ms=LEASE - 1_000)
    extended = jobs.heartbeat(job.id, worker_id="w-a", lease_ms=LEASE)
    assert extended.lease_expires_at == clock.now() + timedelta(milliseconds=LEASE)
    with pytest.raises(Conflict):
        jobs.heartbeat(job.id, worker_id="w-b", lease_ms=LEASE)


def test_an_expired_lease_cannot_be_revived_by_heartbeat(db, jobs, clock) -> None:
    _enqueue(db, jobs, "hb:expired")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w-a", lease_ms=LEASE)
    clock.advance(ms=LEASE)
    with pytest.raises(Conflict, match="lease lost"):
        jobs.heartbeat(job.id, worker_id="w-a", lease_ms=LEASE)


def test_expired_lease_requeues_the_job_and_a_zombie_cannot_finish_it(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "zombie:1")
    first = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=LEASE)
    clock.advance(ms=LEASE + 1)  # w-1 hangs, then wakes up after its lease expired
    assert jobs.requeue_expired() == 1
    assert jobs.get(result.job_id).status is JobStatus.QUEUED
    second = jobs.claim(QueueName.PRODUCTION, worker_id="w-2", lease_ms=LEASE)
    assert second.attempt == 2
    with pytest.raises(Conflict, match="lease lost"):
        jobs.finish(first.id, worker_id="w-1", outcome=Succeeded(result={"stale": True}))
    with pytest.raises(Conflict):
        jobs.heartbeat(first.id, worker_id="w-1", lease_ms=LEASE)
    with pytest.raises(Conflict):
        jobs.finish(second.id, worker_id="w-1", outcome=Succeeded(result={"hijack": True}))
    done = jobs.finish(second.id, worker_id="w-2", outcome=Succeeded(result={"ok": 1}))
    assert done.status is JobStatus.SUCCEEDED and done.outcome == {
        "kind": "SUCCEEDED",
        "result": {"ok": 1},
    }
    assert _job_events(db, first.id).count("job.succeeded") == 1


def test_crash_then_recovery_completes_the_job_exactly_once(db, jobs, clock) -> None:
    """Worker 1 claims and dies before finishing. Worker 2 completes it once; no duplicate terminal."""
    result = _enqueue(db, jobs, "crash:1")
    jobs.claim(QueueName.PRODUCTION, worker_id="dead-worker", lease_ms=LEASE)
    clock.advance(ms=LEASE + 500)
    assert jobs.requeue_expired() == 1
    job = jobs.claim(QueueName.PRODUCTION, worker_id="live-worker", lease_ms=LEASE)
    assert job.id == result.job_id
    jobs.finish(job.id, worker_id="live-worker", outcome=Succeeded(result={"step": "done"}))
    assert jobs.requeue_expired() == 0  # nothing left to recover
    assert jobs.claim(QueueName.PRODUCTION, worker_id="x", lease_ms=LEASE) is None
    final = jobs.get(result.job_id)
    assert final.status is JobStatus.SUCCEEDED and final.attempt == 2
    assert _job_events(db, result.job_id).count("job.succeeded") == 1


def test_expired_lease_without_attempts_left_fails_with_lease_expired(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "last:attempt", max_attempts=1)
    jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    clock.advance(ms=LEASE + 1)
    assert jobs.requeue_expired() == 1
    job = jobs.get(result.job_id)
    assert job.status is JobStatus.FAILED and job.error_code == "LEASE_EXPIRED"


def test_finishing_after_the_lease_expired_is_refused_even_before_recovery(db, jobs, clock) -> None:
    _enqueue(db, jobs, "late:finish")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    clock.advance(ms=LEASE)
    with pytest.raises(Conflict, match="lease lost"):
        jobs.finish(job.id, worker_id="w", outcome=Succeeded(result={}))


def test_lease_guard_proves_ownership_inside_a_transaction(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "guard:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    with db.transaction() as tx:
        jobs.lease_guard(tx, job.id, worker_id="w")
    with pytest.raises(Conflict), db.transaction() as tx:
        jobs.lease_guard(tx, job.id, worker_id="someone-else")
    with pytest.raises(NotFound), db.transaction() as tx:
        jobs.lease_guard(tx, uuid.uuid4(), worker_id="w")
    clock.advance(ms=LEASE)
    with pytest.raises(Conflict), db.transaction() as tx:
        jobs.lease_guard(tx, result.job_id, worker_id="w")


# --- retries and failures ---------------------------------------------------------------


def test_retry_later_waits_then_is_promoted_by_claim(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "retry:1", max_attempts=3)
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    retry = jobs.finish(
        job.id, worker_id="w", outcome=RetryLater(error_code="RATE_LIMITED", retry_after_ms=2_000)
    )
    assert retry.status is JobStatus.RETRY_WAIT and retry.error_code == "RATE_LIMITED"
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE) is None
    clock.advance(seconds=2)
    again = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    assert again.id == result.job_id and again.attempt == 2


def test_retry_later_exhausts_max_attempts_into_failed(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "retry:exhaust", max_attempts=3)
    statuses = []
    for _ in range(3):
        job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
        assert job is not None
        outcome = jobs.finish(
            job.id,
            worker_id="w",
            outcome=RetryLater(error_code="PROVIDER_TRANSIENT", retry_after_ms=0),
        )
        statuses.append(outcome.status)
        clock.advance(ms=1)
    assert statuses == [JobStatus.RETRY_WAIT, JobStatus.RETRY_WAIT, JobStatus.FAILED]
    final = jobs.get(result.job_id)
    assert final.attempt == 3
    assert final.error_code == "MAX_ATTEMPTS:PROVIDER_TRANSIENT"
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE) is None


def test_failed_outcome_is_terminal(db, jobs) -> None:
    result = _enqueue(db, jobs, "failed:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    failed = jobs.finish(
        job.id, worker_id="w", outcome=Failed(error_code="INVALID_SCRIPT", detail="no speakers")
    )
    assert failed.status is JobStatus.FAILED and failed.error_code == "INVALID_SCRIPT"
    assert failed.outcome["detail"] == "no speakers"
    with pytest.raises(InvalidTransition):
        jobs.cancel(result.job_id, reason="too late")


def test_outcomes_are_validated(db, jobs) -> None:
    _enqueue(db, jobs, "validate:outcomes")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    with pytest.raises(SchemaInvalid):
        jobs.finish(job.id, worker_id="w", outcome=Succeeded(result=["not", "an", "object"]))  # type: ignore[arg-type]
    with pytest.raises(SchemaInvalid):
        jobs.finish(job.id, worker_id="w", outcome=WaitExternal(external_id="", poll_after_ms=1))
    with pytest.raises(SchemaInvalid):
        jobs.finish(job.id, worker_id="w", outcome=RetryLater(error_code="X", retry_after_ms=-1))
    with pytest.raises(SchemaInvalid):
        jobs.finish(
            job.id, worker_id="w", outcome=Succeeded(result={"ratio": 0.5})
        )  # floats refused
    assert jobs.get(job.id).status is JobStatus.RUNNING  # nothing was written


# --- ambiguous external effects ---------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        ProviderOperationState.PENDING_SUBMIT,
        ProviderOperationState.SUBMITTED,
        ProviderOperationState.RUNNING,
        ProviderOperationState.UNKNOWN,
    ],
)
def test_expired_lease_with_an_in_flight_provider_operation_needs_reconciliation(
    db, jobs, clock, state
) -> None:
    result = _enqueue(db, jobs, f"inflight:{state.value}")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    with db.transaction() as tx:
        op = begin_provider_op(
            tx,
            provider="fake-comfy",
            operation_kind="comfy.queue_prompt",
            client_token=f"tok-{state.value}-{job.id}",
            request_hash=H,
            deadline_at=clock.now() + timedelta(minutes=10),
            job_id=job.id,
        )
        if state is not ProviderOperationState.PENDING_SUBMIT:
            tx.execute(
                "UPDATE provider_operations SET state = %s WHERE id = %s",
                (state.value, op.operation_id),
            )
    clock.advance(ms=LEASE + 1)
    assert jobs.requeue_expired() == 1
    after = jobs.get(result.job_id)
    assert after.status is JobStatus.NEEDS_RECONCILIATION and after.error_code == "LEASE_EXPIRED"
    assert after.attempt == 1  # not blindly requeued
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w2", lease_ms=LEASE) is None
    assert "job.needs_reconciliation" in _job_events(db, result.job_id)


def test_needs_reconciliation_is_never_silently_succeeded(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "uncertain:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(
        job.id,
        worker_id="w",
        outcome=NeedsReconciliation(detail="upload timed out", external_id="prov-9"),
    )
    state = jobs.get(result.job_id)
    assert state.status is JobStatus.NEEDS_RECONCILIATION and state.external_id == "prov-9"
    # Neither the old holder, nor a claim, nor a cancel, nor a requeue may complete it.
    with pytest.raises(Conflict):
        jobs.finish(job.id, worker_id="w", outcome=Succeeded(result={"guess": True}))
    assert jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE) is None
    assert jobs.requeue_expired(now=clock.now() + timedelta(days=1)) == 0
    with pytest.raises(InvalidTransition):
        jobs.cancel(result.job_id, reason="give up")
    assert jobs.get(result.job_id).status is JobStatus.NEEDS_RECONCILIATION


@pytest.mark.parametrize("evidence", ["", "   "])
def test_reconciliation_needs_evidence(db, jobs, evidence: str) -> None:
    result = _enqueue(db, jobs, f"evidence:{evidence!r}")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(job.id, worker_id="w", outcome=NeedsReconciliation(detail="ambiguous"))
    with pytest.raises(SchemaInvalid):
        jobs.resolve_reconciliation(result.job_id, resolution="SUCCEEDED", evidence=evidence)


def test_reconciliation_resolutions_are_explicit_and_evidenced(db, jobs, clock) -> None:
    result = _enqueue(db, jobs, "resolve:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(job.id, worker_id="w", outcome=NeedsReconciliation(detail="ambiguous"))
    with pytest.raises(SchemaInvalid):
        jobs.resolve_reconciliation(result.job_id, resolution="GUESS", evidence="x")
    with pytest.raises(SchemaInvalid):  # RESUME needs a worker and a lease
        jobs.resolve_reconciliation(
            result.job_id, resolution="RESUME", evidence="provider lists the upload"
        )
    resumed = jobs.resolve_reconciliation(
        result.job_id,
        resolution="RESUME",
        evidence="provider lists the upload",
        worker_id="w-2",
        lease_ms=LEASE,
    )
    assert resumed.status is JobStatus.RUNNING and resumed.lease_owner == "w-2"
    assert resumed.attempt == 1  # resuming is not a new attempt
    with pytest.raises(InvalidTransition):  # not reconciling anymore
        jobs.resolve_reconciliation(result.job_id, resolution="FAILED", evidence="again")
    done = jobs.finish(result.job_id, worker_id="w-2", outcome=Succeeded(result={"resumed": True}))
    assert done.status is JobStatus.SUCCEEDED


def test_reconciled_success_and_failure_are_recorded_with_evidence(db, jobs) -> None:
    ok = _enqueue(db, jobs, "resolve:ok")
    bad = _enqueue(db, jobs, "resolve:bad")
    for _ in range(2):
        claimed = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
        jobs.finish(claimed.id, worker_id="w", outcome=NeedsReconciliation(detail="unknown"))
    succeeded = jobs.resolve_reconciliation(
        ok.job_id, resolution="SUCCEEDED", evidence="provider receipt 7731"
    )
    failed = jobs.resolve_reconciliation(
        bad.job_id, resolution="FAILED", evidence="provider says never accepted"
    )
    assert succeeded.status is JobStatus.SUCCEEDED and succeeded.outcome["reconciled"] is True
    assert succeeded.outcome["evidence"] == "provider receipt 7731"
    assert failed.status is JobStatus.FAILED and failed.error_code == "RECONCILED_FAILED"


# --- cancel, reads and contexts ---------------------------------------------------------


def test_cancel_a_queued_job_and_a_running_job_stops_its_holder(db, jobs) -> None:
    queued = _enqueue(db, jobs, "cancel:queued")
    assert jobs.cancel(queued.job_id, reason="superseded by a recut").status is JobStatus.CANCELLED
    running = _enqueue(db, jobs, "cancel:running")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.cancel(running.job_id, reason="operator stop")
    with pytest.raises(Conflict):
        jobs.finish(job.id, worker_id="w", outcome=Succeeded(result={}))
    with pytest.raises(InvalidTransition):
        jobs.cancel(running.job_id, reason="again")
    with pytest.raises(SchemaInvalid):
        jobs.cancel(queued.job_id, reason="   ")


def test_status_view_and_unknown_job_lookup(db, jobs) -> None:
    result = _enqueue(db, jobs, "view:1")
    view = jobs.status_view(result.job_id)
    assert isinstance(view, JobStatusView)
    assert (view.status, view.attempt, view.queue) == (JobStatus.QUEUED, 0, QueueName.PRODUCTION)
    with pytest.raises(NotFound):
        jobs.get(uuid.uuid4())
    with pytest.raises(NotFound):
        jobs.status_view(uuid.uuid4())


def test_context_hands_the_handler_a_validated_payload(db, jobs) -> None:
    episode = uuid.uuid4()
    result = _enqueue(db, jobs, "context:1", episode=episode)
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    ctx = JobService.context(job, "w")
    assert ctx.job.id == result.job_id and ctx.worker_id == "w"
    assert isinstance(ctx.payload, EpisodeStepInput) and ctx.payload.episode_id == episode


def test_job_semantics_hold_for_a_long_running_sequence(db, jobs, clock) -> None:
    """Enqueue, wait, poll, retry and finish: each phase emits one event and no phase repeats work."""
    result = _enqueue(db, jobs, "sequence:1", max_attempts=3)
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(job.id, worker_id="w", outcome=RetryLater(error_code="TRANSIENT", retry_after_ms=0))
    clock.advance(ms=1)
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(job.id, worker_id="w", outcome=WaitExternal(external_id="p-1", poll_after_ms=0))
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=LEASE)
    jobs.finish(job.id, worker_id="w", outcome=Succeeded(result={"ok": True}))
    types = _job_events(db, result.job_id)
    assert types == [
        "job.enqueued",
        "job.claimed",
        "job.retry_wait",
        "job.queued",
        "job.claimed",
        "job.waiting_external",
        "job.claimed",
        "job.succeeded",
    ]
    assert jobs.get(result.job_id).attempt == 2


def test_recovery_skips_a_job_whose_holder_is_recording_an_external_submission(
    db, jobs, clock
) -> None:
    """Lease fence: a holder that proves its lease while recording a provider operation keeps a
    shared lock. A sweep that runs after the lease expired skips the job instead of requeueing it;
    once the submission is committed, the sweep sees the in-flight operation and reconciles."""
    result = _enqueue(db, jobs, "fence:1")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=LEASE)
    claimed_at = job.lease_expires_at - timedelta(milliseconds=LEASE)
    valid_at = claimed_at + timedelta(milliseconds=LEASE - 1_000)
    expired_at = claimed_at + timedelta(milliseconds=LEASE + 1)
    holding = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def worker_submission() -> None:
        try:
            with db.transaction() as tx:
                jobs.lease_guard(tx, job.id, worker_id="w-1", now=valid_at)
                begin_provider_op(
                    tx,
                    provider="fake-comfy",
                    operation_kind="comfy.queue_prompt",
                    client_token="tok-fence",
                    request_hash=H,
                    deadline_at=clock.now() + timedelta(minutes=5),
                    job_id=job.id,
                )
                holding.set()
                release.wait(timeout=30)
        except BaseException as exc:  # pragma: no cover - reported by the assertions below
            errors.append(exc)
            holding.set()

    writer = threading.Thread(target=worker_submission)
    writer.start()
    assert holding.wait(timeout=30)
    assert errors == []
    recovered: list[int] = []
    sweeper = threading.Thread(
        target=lambda: recovered.append(jobs.requeue_expired(now=expired_at))
    )
    sweeper.start()
    sweeper.join(timeout=30)
    assert recovered == [0]  # skipped while the submission is being recorded, not requeued
    release.set()
    writer.join(timeout=30)
    assert errors == []
    assert jobs.requeue_expired(now=expired_at) == 1
    after = jobs.get(result.job_id)
    assert after.status is JobStatus.NEEDS_RECONCILIATION
    assert after.attempt == 1


def test_lease_guard_alone_fences_recovery_even_without_a_provider_row(db, jobs, clock) -> None:
    """The guard's own shared lock keeps a sweep from requeueing a job whose holder is mid-step,
    independently of any foreign-key lock taken by an inserted provider operation."""
    _enqueue(db, jobs, "fence:guard-only")
    job = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=LEASE)
    claimed_at = job.lease_expires_at - timedelta(milliseconds=LEASE)
    valid_at = claimed_at + timedelta(milliseconds=LEASE - 1_000)
    expired_at = claimed_at + timedelta(milliseconds=LEASE + 1)
    holding = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with db.transaction() as tx:
            jobs.lease_guard(tx, job.id, worker_id="w-1", now=valid_at)
            holding.set()
            release.wait(timeout=30)

    writer = threading.Thread(target=holder)
    writer.start()
    assert holding.wait(timeout=30)
    recovered: list[int] = []
    sweeper = threading.Thread(
        target=lambda: recovered.append(jobs.requeue_expired(now=expired_at))
    )
    sweeper.start()
    sweeper.join(timeout=30)
    release.set()
    writer.join(timeout=30)
    assert recovered == [0]
    assert jobs.requeue_expired(now=expired_at) == 1  # nothing was in flight: requeued
    assert jobs.get(job.id).status is JobStatus.QUEUED


def test_a_recovered_job_replays_its_committed_step_without_repeating_the_effect(
    db, jobs, clock
) -> None:
    """A step's effect and its idempotency record commit together. The worker dies before finishing
    the job; the recovered attempt replays the step from the stored response and writes nothing new."""
    from microdrama.core.idempotency import IdempotencyService

    idempotency = IdempotencyService(db)
    effects: list[str] = []

    def run_step(job) -> dict:
        def action(tx):
            effects.append(job.id.hex)  # the semantic effect (written in this transaction)
            return 202, {"step": "render-shot-01", "written": True}

        outcome = idempotency.execute(
            scope="job-step",
            key=f"{job.id}:render-shot-01",
            principal_id="worker:render",
            request_hash=H,
            action=action,
        )
        return {"replayed": outcome.replayed, **outcome.body}

    result = _enqueue(db, jobs, "replay:step:1")
    first = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=LEASE)
    assert run_step(first)["replayed"] is False  # effect committed, then the worker dies
    clock.advance(ms=LEASE + 1)
    assert jobs.requeue_expired() == 1
    second = jobs.claim(QueueName.PRODUCTION, worker_id="w-2", lease_ms=LEASE)
    assert second.id == result.job_id
    assert run_step(second)["replayed"] is True  # the replay reads the stored response
    jobs.finish(second.id, worker_id="w-2", outcome=Succeeded(result={"ok": True}))
    assert len(effects) == 1

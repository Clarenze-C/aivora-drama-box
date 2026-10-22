"""Provider operations: idempotent begin, the state machine, reconciliation before resubmission."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core_support import WORKER, linked_job, make_reservation

from microdrama.contracts.cost import (
    UNMETERED_OPERATION_KINDS,
    ProviderOperation,
    ProviderOperationResult,
)
from microdrama.contracts.enums import JobStatus, Provenance, QueueName
from microdrama.contracts.enums import ProviderOperationState as S
from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.core.events import list_events
from microdrama.core.provider_ops import (
    ALLOWED_MOVES,
    begin,
    load,
    needs_reconcile,
    record_result,
    resubmit_allowed,
)
from microdrama.persistence import Database

pytestmark = pytest.mark.db
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
H = canonical_hash({"request": "render sh1 attempt 1"})
H2 = canonical_hash({"request": "a different render"})


def _begin(
    db: Database,
    token: str = "tok-1",
    *,
    request_hash: str = H,
    kind: str = "comfy.queue_prompt",
    deadline: datetime | None = None,
    job_id=None,
    provider: str = "fake-comfy",
):
    job = job_id or linked_job(db)
    with db.transaction() as tx:
        return begin(
            tx,
            provider=provider,
            operation_kind=kind,
            client_token=token,
            request_hash=request_hash,
            deadline_at=deadline or T0 + timedelta(minutes=10),
            job_id=job,
            now=T0,
            reservation_id=make_reservation(db),
        )


def _force_state(db: Database, operation_id, state: S, external: str | None = None) -> None:
    with db.transaction() as tx:
        tx.execute(
            "UPDATE provider_operations SET state = %s, external_id = COALESCE(%s, external_id) WHERE id = %s",
            (state.value, external, operation_id),
        )


def _result(operation_id, state: S, external: str | None = None) -> ProviderOperationResult:
    return ProviderOperationResult(
        operation_id=operation_id,
        state=state,
        external_id=external,
        error_code="FAKE_REJECTED" if state is S.FAILED else None,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


def test_begin_is_idempotent_on_provider_and_client_token(db: Database) -> None:
    first = _begin(db, "tok-same")
    again = _begin(db, "tok-same")
    assert again.operation_id == first.operation_id
    assert first.state is S.PENDING_SUBMIT and first.attempt == 1
    assert first.request_sha256 == H
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval("SELECT count(*) FROM provider_operations WHERE client_token = 'tok-same'")
            == 1
        )
        events = [e.event_type for e in list_events(tx, first.operation_id)]
    assert events == ["provider_operation.state_changed"]  # the replay wrote nothing new


def test_the_same_token_with_a_different_request_is_an_idempotency_conflict(db: Database) -> None:
    _begin(db, "tok-clash")
    with pytest.raises(IdempotencyConflict):
        _begin(db, "tok-clash", request_hash=H2)
    with pytest.raises(IdempotencyConflict):
        _begin(db, "tok-clash", kind="comfy.get_history")


def test_the_same_token_on_another_provider_is_a_different_operation(db: Database) -> None:
    a = _begin(db, "tok-shared", provider="fake-comfy")
    b = _begin(db, "tok-shared", provider="fake-pods")
    assert a.operation_id != b.operation_id


def test_concurrent_begin_with_one_token_creates_exactly_one_operation(db: Database) -> None:
    ids: list[uuid.UUID] = []
    lock = threading.Lock()
    barrier = threading.Barrier(6)
    job = linked_job(db)
    reservation = make_reservation(db)

    def go() -> None:
        barrier.wait()
        op = _begin_on(db, reservation, "tok-race", job)
        with lock:
            ids.append(op.operation_id)

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(ids) == 6 and len(set(ids)) == 1


def test_begin_refuses_bad_inputs(db: Database) -> None:
    with pytest.raises(SchemaInvalid):
        _begin(db, "tok-x", request_hash="short")
    job = linked_job(db)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        begin(
            tx,
            provider="fake",
            operation_kind="k",
            client_token="t",
            request_hash=H,
            deadline_at=datetime(2026, 10, 20, 9, 0),  # naive deadline
            job_id=job,
            now=T0,
            reservation_id=make_reservation(db),
        )


def test_external_id_is_persisted_as_soon_as_known_and_cannot_change(db: Database) -> None:
    op = _begin(db, "tok-ext")
    with db.transaction() as tx:
        recorded = record_result(
            tx, op.operation_id, _result(op.operation_id, S.SUBMITTED, "prompt-1"), now=T0
        )
    assert recorded.state is S.SUBMITTED and recorded.external_id == "prompt-1"
    assert recorded.submitted_at == T0
    with pytest.raises(Conflict), db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.RUNNING, "prompt-2"), now=T0)
    with db.transaction() as tx:  # a later report without an id keeps the stored one
        kept = record_result(tx, op.operation_id, _result(op.operation_id, S.RUNNING), now=T0)
    assert kept.external_id == "prompt-1"


def test_one_external_id_belongs_to_one_operation_per_provider(db: Database) -> None:
    a = _begin(db, "tok-dup-a")
    b = _begin(db, "tok-dup-b")
    with db.transaction() as tx:
        record_result(tx, a.operation_id, _result(a.operation_id, S.SUBMITTED, "same-id"), now=T0)
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        record_result(tx, b.operation_id, _result(b.operation_id, S.SUBMITTED, "same-id"), now=T0)


def test_result_must_belong_to_the_operation_and_the_operation_must_exist(db: Database) -> None:
    op = _begin(db, "tok-belong")
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        record_result(tx, uuid.uuid4(), _result(op.operation_id, S.SUBMITTED), now=T0)
    missing = uuid.uuid4()
    with pytest.raises(NotFound), db.transaction() as tx:
        record_result(tx, missing, _result(missing, S.SUBMITTED), now=T0)


def test_the_full_transition_matrix_matches_the_documented_moves(db: Database) -> None:
    """All 8 x 8 (from, to) pairs. Table moves succeed; every other move is InvalidTransition."""
    problems: list[str] = []
    for source in S:
        for target in S:
            op = _begin(db, f"matrix-{source.value}-{target.value}")
            _force_state(db, op.operation_id, source)
            allowed = target in ALLOWED_MOVES[source]
            try:
                with db.transaction() as tx:
                    record_result(tx, op.operation_id, _result(op.operation_id, target), now=T0)
                outcome = "ok"
            except InvalidTransition:
                outcome = "invalid"
            expected = "ok" if allowed else "invalid"
            if outcome != expected:
                problems.append(
                    f"{source.value}->{target.value}: expected {expected}, got {outcome}"
                )
    assert problems == []
    assert ALLOWED_MOVES[S.PENDING_SUBMIT] == frozenset(
        {S.SUBMITTED, S.RUNNING, S.SUCCEEDED, S.FAILED, S.UNKNOWN, S.NOT_FOUND}
    )


@pytest.mark.parametrize("terminal", [S.SUCCEEDED, S.FAILED, S.CANCELLED])
def test_terminal_operations_never_change(db: Database, terminal: S) -> None:
    op = _begin(db, f"terminal-{terminal.value}")
    _force_state(db, op.operation_id, terminal)
    for target in (S.RUNNING, S.UNKNOWN, S.SUCCEEDED, S.FAILED):
        with pytest.raises(InvalidTransition), db.transaction() as tx:
            record_result(tx, op.operation_id, _result(op.operation_id, target), now=T0)


def test_record_result_keeps_the_last_result_and_emits_a_state_event(db: Database) -> None:
    op = _begin(db, "tok-last")
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.SUCCEEDED), now=T0)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state, last_result FROM provider_operations WHERE id = %s", (op.operation_id,)
        )
        types = [e.payload["to"] for e in list_events(tx, op.operation_id)]
    assert row["state"] == "SUCCEEDED"
    assert row["last_result"]["provenance"] == "FAKE_SYNTHETIC"
    assert types == ["PENDING_SUBMIT", "SUCCEEDED"]


def test_unknown_is_never_resubmitted(db: Database) -> None:
    op = _begin(db, "tok-unknown")
    _force_state(db, op.operation_id, S.UNKNOWN, external=None)
    with pytest.raises(InvalidTransition, match="NOT_FOUND"), db.transaction() as tx:
        resubmit_allowed(tx, op.operation_id, now=T0)
    with db.transaction(readonly=True) as tx:
        assert load(tx, op.operation_id).state is S.UNKNOWN  # still waiting for reconciliation


def test_not_found_may_be_resubmitted_with_a_new_attempt(db: Database) -> None:
    op = _begin(db, "tok-notfound")
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.UNKNOWN), now=T0)
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.NOT_FOUND), now=T0)
    new_deadline = T0 + timedelta(hours=1)
    with db.transaction() as tx:
        again = resubmit_allowed(tx, op.operation_id, deadline_at=new_deadline, now=T0)
    assert again.state is S.PENDING_SUBMIT and again.attempt == 2
    assert again.deadline_at == new_deadline
    assert again.client_token == "tok-notfound"  # same token: the provider can still dedupe


@pytest.mark.parametrize(
    "state", [S.PENDING_SUBMIT, S.SUBMITTED, S.RUNNING, S.SUCCEEDED, S.FAILED, S.CANCELLED]
)
def test_only_not_found_can_be_resubmitted(db: Database, state: S) -> None:
    op = _begin(db, f"no-resubmit-{state.value}")
    _force_state(db, op.operation_id, state)
    with pytest.raises(InvalidTransition), db.transaction() as tx:
        resubmit_allowed(tx, op.operation_id, now=T0)


def test_needs_reconcile_rules_follow_state_and_deadline(db: Database) -> None:
    op = _begin(db, "tok-rule", deadline=T0 + timedelta(minutes=5))
    base = load_snapshot(db, op.operation_id)
    before = T0 + timedelta(minutes=4)
    after = T0 + timedelta(minutes=6)
    assert needs_reconcile(base.model_copy(update={"state": S.UNKNOWN}), now=before) is True
    assert needs_reconcile(base.model_copy(update={"state": S.SUBMITTED}), now=before) is False
    assert needs_reconcile(base.model_copy(update={"state": S.SUBMITTED}), now=after) is True
    assert needs_reconcile(base.model_copy(update={"state": S.RUNNING}), now=after) is True
    assert needs_reconcile(base.model_copy(update={"state": S.PENDING_SUBMIT}), now=after) is True
    assert needs_reconcile(base.model_copy(update={"state": S.SUCCEEDED}), now=after) is False
    assert needs_reconcile(base.model_copy(update={"state": S.NOT_FOUND}), now=after) is False


def load_snapshot(db: Database, operation_id) -> ProviderOperation:
    with db.transaction(readonly=True) as tx:
        return load(tx, operation_id)


def test_begin_links_the_operation_to_its_job(db: Database, clock_at_t0) -> None:
    from microdrama.contracts.jobs import EpisodeStepInput
    from microdrama.core.jobs import JobService
    from microdrama.testing.fakes import SequentialIds

    jobs = JobService(db, clock_at_t0, SequentialIds("provider-link"))
    with db.transaction() as tx:
        queued = jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key="link:qa:1",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    op = _begin(db, "tok-linked", job_id=queued.job_id)
    assert op.job_id == queued.job_id
    with db.transaction(readonly=True) as tx:
        assert load(tx, op.operation_id).job_id == queued.job_id


@pytest.fixture
def clock_at_t0():
    from microdrama.testing.fakes import FakeClock

    return FakeClock(T0)


# --- V-14: every operation belongs to a job, so recovery can always see it -----------------


def test_begin_requires_a_job_link_as_a_keyword(db: Database) -> None:
    """Without job_id the call is a TypeError; an explicit None is refused. Both fail before any
    write, so no unlinked (recovery-invisible) operation can exist."""
    with db.transaction(readonly=True) as tx:
        before = tx.fetchval("SELECT count(*) FROM provider_operations")
    with pytest.raises(TypeError), db.transaction() as tx:
        begin(
            tx,
            provider="fake",
            operation_kind="k",
            client_token="no-job",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=5),
            now=T0,
            reservation_id=make_reservation(db),
        )
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        begin(
            tx,
            provider="fake",
            operation_kind="k",
            client_token="null-job",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=5),
            job_id=None,
            now=T0,
            reservation_id=make_reservation(db),
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM provider_operations") == before


@pytest.mark.parametrize("state", [S.PENDING_SUBMIT, S.SUBMITTED, S.RUNNING, S.UNKNOWN])
def test_recovery_finds_every_operation_because_each_is_linked_to_its_job(
    db: Database, state: S
) -> None:
    """An operation begun for a job is found by the in-flight scan that expiry recovery runs."""
    from microdrama.contracts.enums import QueueName
    from microdrama.contracts.jobs import EpisodeStepInput
    from microdrama.core.jobs import JobService
    from microdrama.testing.fakes import FakeClock, SequentialIds

    clock = FakeClock(T0)
    jobs = JobService(db, clock, SequentialIds(f"v14-{state.value}"))
    with db.transaction() as tx:
        queued = jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"v14:{state.value}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    claimed = jobs.claim(QueueName.PRODUCTION, worker_id="w", lease_ms=60_000, now=T0)
    op = _begin(db, f"v14-{state.value}", job_id=claimed.id)
    _force_state(db, op.operation_id, state)
    assert jobs.requeue_expired(now=T0 + timedelta(minutes=2)) == 1
    assert jobs.get(queued.job_id).status.value == "NEEDS_RECONCILIATION"


# --- V-18: the caller's injected clock is the only time source --------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda tx, op: record_result(tx, op, _result(op, S.SUBMITTED)),
        lambda tx, op: resubmit_allowed(tx, op),
    ],
    ids=["record_result", "resubmit_allowed"],
)
def test_provider_functions_require_now(db: Database, call) -> None:
    op = _begin(db, f"v18-{uuid.uuid4().hex[:8]}")
    with pytest.raises(TypeError), db.transaction() as tx:
        call(tx, op.operation_id)


def test_needs_reconcile_requires_now(db: Database) -> None:
    op = _begin(db, f"v18-nr-{uuid.uuid4().hex[:8]}")
    with pytest.raises(TypeError):
        needs_reconcile(op)  # type: ignore[call-arg]


def test_provider_events_are_stamped_with_the_injected_instant(db: Database) -> None:
    """The outbox time is exactly the instant the caller injected, not the wall clock."""
    injected = datetime(2031, 3, 4, 5, 6, 7, tzinfo=UTC)
    job = linked_job(db)
    with db.transaction() as tx:
        op = begin(
            tx,
            provider="fake-comfy",
            operation_kind="k",
            client_token="v18-clock",
            request_hash=H,
            deadline_at=injected + timedelta(minutes=5),
            job_id=job,
            now=injected,
            reservation_id=make_reservation(db),
        )
    with db.transaction() as tx:
        record_result(
            tx,
            op.operation_id,
            _result(op.operation_id, S.SUBMITTED),
            now=injected + timedelta(seconds=9),
        )
    with db.transaction(readonly=True) as tx:
        events = list_events(tx, op.operation_id)
    assert [e.occurred_at for e in events] == [injected, injected + timedelta(seconds=9)]


# --- reservation gate: an operation never starts on a reservation that is not ACTIVE ----------


def _begin_on(
    db: Database, reservation: uuid.UUID, token: str, job: uuid.UUID | None = None
) -> ProviderOperation:
    job_id = job or linked_job(db)
    with db.transaction() as tx:
        return begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=token,
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job_id,
            reservation_id=reservation,
            now=T0,
        )


@pytest.mark.parametrize("state", ["RELEASED", "SETTLED", "EXPIRED"])
def test_begin_is_refused_on_a_closed_reservation(db: Database, state: str) -> None:
    reservation = make_reservation(db, state)
    token = f"closed-{state}-{uuid.uuid4().hex[:6]}"
    with pytest.raises(Conflict, match="not ACTIVE"), db.transaction() as tx:
        begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=token,
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=linked_job(db),
            reservation_id=reservation,
            now=T0,
        )
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM provider_operations WHERE client_token = %s", (token,)
            )
            == 0
        )


def test_begin_on_an_active_reservation_is_allowed(db: Database) -> None:
    reservation = make_reservation(db)
    op = _begin_on(db, reservation, f"active-{uuid.uuid4().hex[:6]}")
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT reservation_id FROM provider_operations WHERE id = %s", (op.operation_id,)
            )
            == reservation
        )


def test_begin_refuses_an_unknown_reservation(db: Database) -> None:
    with pytest.raises(NotFound), db.transaction() as tx:
        begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=f"ghost-{uuid.uuid4().hex[:6]}",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=linked_job(db),
            reservation_id=uuid.uuid4(),
            now=T0,
        )


def test_begin_holds_a_shared_lock_that_blocks_an_exclusive_release_until_it_commits(
    db: Database,
) -> None:
    """While begin's transaction is open, a FOR UPDATE NOWAIT (what release takes) cannot get the
    reservation. After begin commits, the same lock succeeds."""
    from microdrama.contracts.errors import ServiceUnavailable

    reservation = make_reservation(db)
    job = linked_job(db)
    token = f"shared-{uuid.uuid4().hex[:6]}"
    with db.transaction() as tx:
        begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=token,
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job,
            reservation_id=reservation,
            now=T0,
        )
        # still inside begin's transaction: an exclusive lock from another transaction must fail
        with pytest.raises(ServiceUnavailable), db.transaction() as other:
            other.execute(
                "SELECT 1 FROM reservations WHERE id = %s FOR UPDATE NOWAIT", (reservation,)
            )
    with db.transaction() as tx:
        assert (
            tx.fetchval(
                "SELECT 1 FROM reservations WHERE id = %s FOR UPDATE NOWAIT", (reservation,)
            )
            == 1
        )


def _release_like_budget(db: Database, reservation: uuid.UUID) -> str:
    """Mirrors the budget lane's release discipline: lock the reservation, refuse while any linked
    provider operation is in flight, otherwise close it."""
    in_flight = ["PENDING_SUBMIT", "SUBMITTED", "RUNNING", "UNKNOWN"]
    with db.transaction() as tx:
        row = tx.fetchone("SELECT state FROM reservations WHERE id = %s FOR UPDATE", (reservation,))
        if row["state"] != "ACTIVE":
            return "not-active"
        busy = tx.fetchval(
            "SELECT count(*) FROM provider_operations WHERE reservation_id = %s AND state = ANY(%s)",
            (reservation, in_flight),
        )
        if busy:
            return "refused"
        tx.execute(
            "UPDATE reservations SET state = 'RELEASED', closed_at = %s, closed_reason = %s, "
            "revision = revision + 1 WHERE id = %s",
            (T0, "released before the operation began", reservation),
        )
        return "released"


def _race_round(db: Database, reservation: uuid.UUID, job: uuid.UUID, token: str) -> dict[str, str]:
    """One begin-versus-release race on ``reservation``. Returns each side's outcome."""
    import threading

    barrier = threading.Barrier(2)
    results: dict[str, str] = {}
    errors: list[BaseException] = []

    def begin_side() -> None:
        barrier.wait()
        try:
            _begin_on(db, reservation, token, job)
            results["begin"] = "operation"
        except Conflict:
            results["begin"] = "refused"
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    def release_side() -> None:
        barrier.wait()
        try:
            results["release"] = _release_like_budget(db, reservation)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=begin_side), threading.Thread(target=release_side)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    return results


def test_release_and_begin_race_never_leaves_released_with_an_operation(db: Database) -> None:
    """Either (released, no operation) or (operation in flight, reservation ACTIVE); never both."""
    from collections import Counter

    seen: Counter = Counter()
    for _ in range(15):
        reservation = make_reservation(db)
        job = linked_job(db)
        results = _race_round(db, reservation, job, f"race-{uuid.uuid4().hex}")
        with db.transaction(readonly=True) as tx:
            state = tx.fetchval("SELECT state FROM reservations WHERE id = %s", (reservation,))
            operations = tx.fetchval(
                "SELECT count(*) FROM provider_operations WHERE reservation_id = %s", (reservation,)
            )
        assert (state, operations) in {("RELEASED", 0), ("ACTIVE", 1)}, (state, operations, results)
        if state == "RELEASED":
            assert results["begin"] == "refused"
        else:
            assert results["release"] == "refused" and results["begin"] == "operation"
        seen[(state, operations)] += 1
    assert sum(seen.values()) == 15


# --- V-23: one in-flight provider operation per job or per reservation --------------------

IN_FLIGHT_STATES = [S.PENDING_SUBMIT, S.SUBMITTED, S.RUNNING, S.UNKNOWN]


def _record(db: Database, operation_id: uuid.UUID, state: S) -> None:
    with db.transaction() as tx:
        record_result(tx, operation_id, _result(operation_id, state), now=T0)


def _refused_tokens(db: Database, token: str) -> int:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval(
            "SELECT count(*) FROM provider_operations WHERE client_token = %s", (token,)
        )


@pytest.mark.parametrize("state", IN_FLIGHT_STATES)
def test_a_new_operation_is_refused_while_another_on_the_same_job_is_in_flight(
    db: Database, state: S
) -> None:
    first = _begin(db, f"v23-job-{state.value}")
    _force_state(db, first.operation_id, state)
    with pytest.raises(Conflict, match="still in flight") as refused:
        _begin(db, f"v23-job-new-{state.value}", job_id=first.job_id)
    assert refused.value.details["operations"] == [
        {"id": str(first.operation_id), "state": state.value}
    ]
    assert _refused_tokens(db, f"v23-job-new-{state.value}") == 0  # nothing was written


@pytest.mark.parametrize("state", IN_FLIGHT_STATES)
def test_a_new_operation_is_refused_while_another_on_the_same_reservation_is_in_flight(
    db: Database, state: S
) -> None:
    reservation = make_reservation(db)
    first = _begin_on(db, reservation, f"v23-rsv-{state.value}", linked_job(db))
    _force_state(db, first.operation_id, state)
    with pytest.raises(Conflict, match="still in flight") as refused:
        _begin_on(db, reservation, f"v23-rsv-new-{state.value}", linked_job(db))
    assert refused.value.details["operations"] == [
        {"id": str(first.operation_id), "state": state.value}
    ]
    assert _refused_tokens(db, f"v23-rsv-new-{state.value}") == 0


@pytest.mark.parametrize("terminal", [S.SUCCEEDED, S.FAILED, S.CANCELLED])
def test_terminal_operations_do_not_block_a_new_one_on_the_same_job(
    db: Database, terminal: S
) -> None:
    job = linked_job(db)
    first = _begin(db, f"v23-done-{terminal.value}", job_id=job)
    _force_state(db, first.operation_id, terminal)
    second = _begin(db, f"v23-next-{terminal.value}", job_id=job)
    assert second.operation_id != first.operation_id
    assert second.state is S.PENDING_SUBMIT


def test_a_replay_is_never_blocked_by_an_operation_in_flight(db: Database) -> None:
    job = linked_job(db)
    old = _begin(db, "v23-replay-old", job_id=job)
    _force_state(db, old.operation_id, S.SUCCEEDED)
    in_flight = _begin(db, "v23-replay-new", job_id=job)
    # the finished token replays cleanly while the new operation is in flight
    replay = _begin(db, "v23-replay-old", job_id=job)
    assert replay.operation_id == old.operation_id and replay.state is S.SUCCEEDED
    # and the in-flight token replays too: no second external call for it
    again = _begin(db, "v23-replay-new", job_id=job)
    assert again.operation_id == in_flight.operation_id


def test_operations_on_unrelated_jobs_and_reservations_do_not_block_each_other(
    db: Database,
) -> None:
    first = _begin(db, "v23-indep-a")
    second = _begin(db, "v23-indep-b")
    assert first.job_id != second.job_id and first.reservation_id != second.reservation_id
    assert first.state is second.state is S.PENDING_SUBMIT


def test_racing_new_tokens_on_one_job_admit_exactly_one_operation(db: Database) -> None:
    """Six different tokens, one job, one reservation: the advisory locks make exactly one pass the
    in-flight check. Without them two could both see an empty job and both insert."""
    import threading

    job = linked_job(db)
    reservation = make_reservation(db)
    barrier = threading.Barrier(6)
    lock = threading.Lock()
    admitted: list[uuid.UUID] = []
    refused: list[str] = []
    errors: list[BaseException] = []

    def go(index: int) -> None:
        barrier.wait()
        try:
            op = _begin_on(db, reservation, f"v23-race-{index}", job)
            with lock:
                admitted.append(op.operation_id)
        except Conflict:
            with lock:
                refused.append(f"v23-race-{index}")
        except BaseException as exc:  # pragma: no cover - reported below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    assert len(admitted) == 1 and len(refused) == 5
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval("SELECT count(*) FROM provider_operations WHERE job_id = %s", (job,)) == 1
        )


def test_resuming_a_reconciled_job_does_not_clear_an_unknown_operation_for_a_new_begin(
    db: Database,
) -> None:
    """RESUME moves the job back to RUNNING, but the UNKNOWN operation is still in flight, so a new
    submission on that job is refused and the operator must still reconcile it."""
    from microdrama.contracts.jobs import EpisodeStepInput
    from microdrama.core.jobs import JobService, NeedsReconciliation
    from microdrama.testing.fakes import FakeClock, SequentialIds

    jobs = JobService(db, FakeClock(T0), SequentialIds(f"v23-resume-{uuid.uuid4().hex}"))
    with db.transaction() as tx:
        queued = jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"v23:resume:{uuid.uuid4().hex}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    claimed = jobs.claim(QueueName.PRODUCTION, worker_id="w-1", lease_ms=60_000, now=T0)
    op = _begin(db, "v23-resume-op", job_id=claimed.id)
    _force_state(db, op.operation_id, S.UNKNOWN)
    jobs.finish(claimed.id, worker_id="w-1", outcome=NeedsReconciliation(detail="unknown"), now=T0)
    resumed = jobs.resolve_reconciliation(
        queued.job_id,
        resolution="RESUME",
        evidence="provider lists nothing for this request yet",
        actor=WORKER,
        worker_id="w-2",
        lease_ms=60_000,
        now=T0,
    )
    assert resumed.status is JobStatus.RUNNING
    with pytest.raises(Conflict, match="still in flight") as refused:
        _begin(db, "v23-resume-new", job_id=queued.job_id)
    assert refused.value.details["operations"] == [{"id": str(op.operation_id), "state": "UNKNOWN"}]
    assert _begin(db, "v23-resume-op", job_id=queued.job_id).operation_id == op.operation_id


def test_a_not_found_operation_blocks_a_new_token_until_it_is_resubmitted_and_settled(
    db: Database,
) -> None:
    job = linked_job(db)
    first = _begin(db, "v23-nf-token", job_id=job)
    _record(db, first.operation_id, S.UNKNOWN)
    _record(db, first.operation_id, S.NOT_FOUND)
    with pytest.raises(Conflict, match="NOT_FOUND") as refused:
        _begin(db, "v23-nf-new", job_id=job)
    assert refused.value.details["operations"] == [
        {"id": str(first.operation_id), "state": "NOT_FOUND"}
    ]
    with db.transaction() as tx:
        resubmitted = resubmit_allowed(tx, first.operation_id, now=T0)
    assert resubmitted.state is S.PENDING_SUBMIT and resubmitted.client_token == "v23-nf-token"
    with pytest.raises(Conflict, match="still in flight"):
        _begin(db, "v23-nf-new", job_id=job)
    _record(db, first.operation_id, S.SUCCEEDED)
    settled = _begin(db, "v23-nf-new", job_id=job)
    assert settled.operation_id != first.operation_id and settled.state is S.PENDING_SUBMIT


def test_resubmit_is_refused_while_another_operation_on_the_same_reservation_is_in_flight(
    db: Database,
) -> None:
    reservation = make_reservation(db)
    first = _begin_on(db, reservation, "v23-rs-first", linked_job(db))
    _record(db, first.operation_id, S.UNKNOWN)
    _record(db, first.operation_id, S.NOT_FOUND)
    other = _begin_on(db, reservation, "v23-rs-other", linked_job(db))  # NOT_FOUND does not block
    with pytest.raises(Conflict, match="in flight") as refused, db.transaction() as tx:
        resubmit_allowed(tx, first.operation_id, now=T0)
    assert refused.value.details["operations"] == [
        {"id": str(other.operation_id), "state": "PENDING_SUBMIT"}
    ]
    assert load_snapshot(db, first.operation_id).state is S.NOT_FOUND
    _record(db, other.operation_id, S.SUCCEEDED)
    with db.transaction() as tx:
        assert resubmit_allowed(tx, first.operation_id, now=T0).state is S.PENDING_SUBMIT


# --- V-24: every metered operation is reserved; the unmetered list is empty -------------------


def test_begin_without_a_reservation_is_refused_for_a_metered_kind(db: Database) -> None:
    job = linked_job(db)
    with pytest.raises(SchemaInvalid, match="budget reservation"), db.transaction() as tx:
        begin(
            tx,
            provider="fake-comfy",
            operation_kind="comfy.queue_prompt",
            client_token="v24-no-reservation",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job,
            now=T0,
        )
    assert _refused_tokens(db, "v24-no-reservation") == 0


def test_the_unmetered_kind_list_is_exactly_the_publish_kinds() -> None:
    """Free platform API calls only (T020, contract 1.6.0): the four publish kinds and nothing
    else — every other provider operation stays reservation-gated at both layers."""
    assert UNMETERED_OPERATION_KINDS == frozenset(
        {
            "publish.submit_slot",
            "publish.poll_status",
            "publish.reconcile_slot",
            "publish.update_metadata",
        }
    )


def test_a_listed_unmetered_kind_passes_the_application_guard_but_the_database_refuses_it(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two layers. Listing a kind in UNMETERED_OPERATION_KINDS lets begin() past its application
    guard, but migration 0013's CHECK ``provider_operations_linked`` still refuses the row (Conflict)
    until a migration relaxes that check for exactly that kind. A metered kind is refused by the
    application guard first (SchemaInvalid) before any SQL runs."""
    monkeypatch.setattr(
        "microdrama.core.provider_ops.UNMETERED_OPERATION_KINDS", frozenset({"status.probe"})
    )
    job = linked_job(db)
    with pytest.raises(Conflict) as refused, db.transaction() as tx:
        begin(
            tx,
            provider="fake-comfy",
            operation_kind="status.probe",
            client_token="v24-unmetered",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job,
            now=T0,
        )
    assert refused.value.details["constraint"] == "provider_operations_linked"
    assert (
        _refused_tokens(db, "v24-unmetered") == 0
    )  # the database refused the row: nothing written

    with (
        pytest.raises(SchemaInvalid, match="budget reservation") as metered,
        db.transaction() as tx,
    ):
        begin(
            tx,
            provider="fake-comfy",
            operation_kind="comfy.queue_prompt",
            client_token="v24-still-metered",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job,
            now=T0,
        )
    assert not isinstance(metered.value, Conflict)  # refused by the application, not the database
    assert _refused_tokens(db, "v24-still-metered") == 0


def test_a_begin_on_a_job_waits_for_an_uncommitted_begin_on_that_job(db: Database) -> None:
    """Deterministic form of the V-23 race. While the first begin's transaction is open (holding the
    job's advisory lock, with its operation uncommitted), a second begin on the same job blocks. It
    is refused once the first commits. Without the lock it would pass the in-flight check unseen."""
    import threading
    from contextlib import ExitStack

    job = linked_job(db)
    reservation = make_reservation(db)
    outcome: dict[str, object] = {}
    stack = ExitStack()
    try:
        tx_first = stack.enter_context(db.transaction())
        first = begin(
            tx_first,
            provider="fake-runpod",
            operation_kind="pod",
            client_token="v23-held-first",
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=job,
            reservation_id=reservation,
            now=T0,
        )

        def second() -> None:
            try:
                outcome["op"] = _begin_on(db, reservation, "v23-held-second", job)
            except Conflict as exc:
                outcome["refused"] = exc

        worker = threading.Thread(target=second)
        worker.start()
        worker.join(timeout=0.5)
        blocked_while_first_is_open = worker.is_alive()
    finally:
        stack.close()  # commits the first begin
    worker.join(timeout=60)
    assert blocked_while_first_is_open is True
    assert "op" not in outcome and isinstance(outcome.get("refused"), Conflict)
    assert outcome["refused"].details["operations"] == [
        {"id": str(first.operation_id), "state": "PENDING_SUBMIT"}
    ]


# --- V-31: a reservation bound to one job never pays for another job's operation -------------


def test_begin_refuses_a_reservation_bound_to_a_different_job(db: Database) -> None:
    """reservations.job_id names the job whose operation the hold pays for (budget.reserve binds
    it today). An operation begun for a different job is refused before anything is written; the
    release guard still protects the money, but the job-reservation binding must not lie."""
    bound_job = linked_job(db)
    other_job = linked_job(db)
    reservation = make_reservation(db, job_id=bound_job)
    token = f"v31-cross-{uuid.uuid4().hex[:6]}"
    with pytest.raises(Conflict, match="bound to a different job"), db.transaction() as tx:
        begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=token,
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=other_job,
            reservation_id=reservation,
            now=T0,
        )
    assert _refused_tokens(db, token) == 0  # nothing was written


def test_begin_allows_a_reservation_bound_to_no_job(db: Database) -> None:
    """Older rows and external integrations carry job_id = NULL; begin must not break them."""
    op = _begin_on(db, make_reservation(db), f"v31-null-{uuid.uuid4().hex[:6]}")
    assert op.state is S.PENDING_SUBMIT


def test_begin_allows_the_reservation_bound_to_its_own_job(db: Database) -> None:
    """The normal budget.flow shape: the hold was reserved for this job, so begin proceeds."""
    job = linked_job(db)
    reservation = make_reservation(db, job_id=job)
    op = _begin_on(db, reservation, f"v31-same-{uuid.uuid4().hex[:6]}", job)
    assert op.reservation_id == reservation and op.job_id == job


def test_a_replay_from_the_bound_job_still_returns_the_stored_operation(db: Database) -> None:
    """The binding check runs before the replay lookup, so replaying the original begin (same
    token, same bound job) still returns the stored operation instead of a fresh conflict."""
    job = linked_job(db)
    reservation = make_reservation(db, job_id=job)
    token = f"v31-replay-{uuid.uuid4().hex[:6]}"
    first = _begin_on(db, reservation, token, job)
    replay = _begin_on(db, reservation, token, job)
    assert replay.operation_id == first.operation_id and replay.state is S.PENDING_SUBMIT

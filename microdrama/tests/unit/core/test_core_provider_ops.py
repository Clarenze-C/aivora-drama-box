"""Provider operations: idempotent begin, the state machine, reconciliation before resubmission."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from microdrama.contracts.cost import ProviderOperation, ProviderOperationResult
from microdrama.contracts.enums import Provenance
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


def _linked_job(db: Database) -> uuid.UUID:
    """A real job for operations to belong to (``job_id`` is required)."""
    from microdrama.contracts.jobs import EpisodeStepInput
    from microdrama.core.jobs import JobService
    from microdrama.testing.fakes import FakeClock, SequentialIds

    jobs = JobService(db, FakeClock(T0), SequentialIds(f"ops-{uuid.uuid4().hex}"))
    with db.transaction() as tx:
        return jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"ops:{uuid.uuid4().hex}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        ).job_id


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
    job = job_id or _linked_job(db)
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

    def go() -> None:
        barrier.wait()
        op = _begin(db, "tok-race")
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
    job = _linked_job(db)
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
    job = _linked_job(db)
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


def _reservation(db: Database, state: str = "ACTIVE") -> uuid.UUID:
    """A budget reservation in ``state`` (raw rows; the budget lane owns the real lifecycle)."""
    from microdrama.persistence.db import jsonb
    from microdrama.testing.seed import seed_episode, seed_season

    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, category, "
            "queue, provider, operation_kind, price, ceilings, reserved_micro_usd, state, expires_at, closed_at, "
            "closed_reason) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', 'fake-runpod', 'pod', %s, %s, "
            "100, %s, %s, %s, %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"res:{reservation}",
                H,
                jsonb({}),
                jsonb({}),
                state,
                T0 + timedelta(hours=1),
                None if state == "ACTIVE" else T0,
                None if state == "ACTIVE" else f"test fixture: {state.lower()}",
            ),
        )
    return reservation


def _begin_on(
    db: Database, reservation: uuid.UUID, token: str, job: uuid.UUID | None = None
) -> ProviderOperation:
    job_id = job or _linked_job(db)
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
    reservation = _reservation(db, state)
    token = f"closed-{state}-{uuid.uuid4().hex[:6]}"
    with pytest.raises(Conflict, match="not ACTIVE"), db.transaction() as tx:
        begin(
            tx,
            provider="fake-runpod",
            operation_kind="pod",
            client_token=token,
            request_hash=H,
            deadline_at=T0 + timedelta(minutes=10),
            job_id=_linked_job(db),
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
    reservation = _reservation(db)
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
            job_id=_linked_job(db),
            reservation_id=uuid.uuid4(),
            now=T0,
        )


def test_begin_holds_a_shared_lock_that_blocks_an_exclusive_release_until_it_commits(
    db: Database,
) -> None:
    """While begin's transaction is open, a FOR UPDATE NOWAIT (what release takes) cannot get the
    reservation. After begin commits, the same lock succeeds."""
    from microdrama.contracts.errors import ServiceUnavailable

    reservation = _reservation(db)
    job = _linked_job(db)
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
        reservation = _reservation(db)
        job = _linked_job(db)
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

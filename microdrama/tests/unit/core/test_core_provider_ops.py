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
    with db.transaction() as tx:
        return begin(
            tx,
            provider=provider,
            operation_kind=kind,
            client_token=token,
            request_hash=request_hash,
            deadline_at=deadline or T0 + timedelta(minutes=10),
            job_id=job_id,
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
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        begin(
            tx,
            provider="fake",
            operation_kind="k",
            client_token="t",
            request_hash=H,
            deadline_at=datetime(2026, 10, 20, 9, 0),  # naive
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
        record_result(tx, op.operation_id, _result(op.operation_id, S.RUNNING, "prompt-2"))
    with db.transaction() as tx:  # a later report without an id keeps the stored one
        kept = record_result(tx, op.operation_id, _result(op.operation_id, S.RUNNING))
    assert kept.external_id == "prompt-1"


def test_one_external_id_belongs_to_one_operation_per_provider(db: Database) -> None:
    a = _begin(db, "tok-dup-a")
    b = _begin(db, "tok-dup-b")
    with db.transaction() as tx:
        record_result(tx, a.operation_id, _result(a.operation_id, S.SUBMITTED, "same-id"))
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        record_result(tx, b.operation_id, _result(b.operation_id, S.SUBMITTED, "same-id"))


def test_result_must_belong_to_the_operation_and_the_operation_must_exist(db: Database) -> None:
    op = _begin(db, "tok-belong")
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        record_result(tx, uuid.uuid4(), _result(op.operation_id, S.SUBMITTED))
    missing = uuid.uuid4()
    with pytest.raises(NotFound), db.transaction() as tx:
        record_result(tx, missing, _result(missing, S.SUBMITTED))


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
                    record_result(tx, op.operation_id, _result(op.operation_id, target))
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
            record_result(tx, op.operation_id, _result(op.operation_id, target))


def test_record_result_keeps_the_last_result_and_emits_a_state_event(db: Database) -> None:
    op = _begin(db, "tok-last")
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.SUCCEEDED))
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
        resubmit_allowed(tx, op.operation_id)
    with db.transaction(readonly=True) as tx:
        assert load(tx, op.operation_id).state is S.UNKNOWN  # still waiting for reconciliation


def test_not_found_may_be_resubmitted_with_a_new_attempt(db: Database) -> None:
    op = _begin(db, "tok-notfound")
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.UNKNOWN))
    with db.transaction() as tx:
        record_result(tx, op.operation_id, _result(op.operation_id, S.NOT_FOUND))
    new_deadline = T0 + timedelta(hours=1)
    with db.transaction() as tx:
        again = resubmit_allowed(tx, op.operation_id, deadline_at=new_deadline)
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
        resubmit_allowed(tx, op.operation_id)


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

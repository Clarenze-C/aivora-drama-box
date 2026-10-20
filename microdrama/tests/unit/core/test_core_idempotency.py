"""Command idempotency against the real database: replay, conflict, rollback and concurrency."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

import pytest

from microdrama.contracts.errors import IdempotencyConflict, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.core.events import append_event, list_events
from microdrama.core.idempotency import IdempotencyService
from microdrama.persistence import Database

pytestmark = pytest.mark.db
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _action_appending(aggregate, counter: list[int], body: dict | None = None):
    def action(tx):
        counter[0] += 1
        append_event(
            tx,
            aggregate_type="season",
            aggregate_id=aggregate,
            event_type="season.state_changed",
            payload={"n": counter[0]},
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )
        return 202, body or {"status": "QUEUED", "n": counter[0]}

    return action


def _hash(payload: dict) -> str:
    return canonical_hash(payload)


def test_first_execution_runs_the_action_and_a_replay_returns_the_stored_response(
    db: Database,
) -> None:
    svc = IdempotencyService(db)
    aggregate, counter = uuid.uuid4(), [0]
    key, request = "key-replay-001", _hash({"job": "a"})
    first = svc.execute(
        scope="POST /x",
        key=key,
        principal_id="worker:1",
        request_hash=request,
        action=_action_appending(aggregate, counter),
    )
    second = svc.execute(
        scope="POST /x",
        key=key,
        principal_id="worker:1",
        request_hash=request,
        action=_action_appending(aggregate, counter),
    )
    assert (first.status_code, first.replayed) == (202, False)
    assert (second.status_code, second.replayed) == (202, True)
    assert second.body == first.body
    assert counter == [1]  # the action ran once
    with db.transaction(readonly=True) as tx:
        assert len(list_events(tx, aggregate)) == 1


def test_the_same_key_with_different_content_is_an_idempotency_conflict(db: Database) -> None:
    svc = IdempotencyService(db)
    counter = [0]
    svc.execute(
        scope="POST /x",
        key="key-conflict-1",
        principal_id="w",
        request_hash=_hash({"a": 1}),
        action=_action_appending(uuid.uuid4(), counter),
    )
    with pytest.raises(IdempotencyConflict) as err:
        svc.execute(
            scope="POST /x",
            key="key-conflict-1",
            principal_id="w",
            request_hash=_hash({"a": 2}),
            action=_action_appending(uuid.uuid4(), counter),
        )
    assert err.value.http_status == 409
    assert counter == [1]


def test_the_same_key_used_by_another_principal_is_refused(db: Database) -> None:
    svc = IdempotencyService(db)
    counter = [0]
    svc.execute(
        scope="POST /x",
        key="key-principal-1",
        principal_id="worker:1",
        request_hash=_hash({"a": 1}),
        action=_action_appending(uuid.uuid4(), counter),
    )
    with pytest.raises(IdempotencyConflict):
        svc.execute(
            scope="POST /x",
            key="key-principal-1",
            principal_id="scheduler:9",
            request_hash=_hash({"a": 1}),
            action=_action_appending(uuid.uuid4(), counter),
        )


def test_keys_are_scoped_per_command(db: Database) -> None:
    svc = IdempotencyService(db)
    counter = [0]
    req = _hash({"a": 1})
    svc.execute(
        scope="POST /one",
        key="key-scope-1",
        principal_id="w",
        request_hash=req,
        action=_action_appending(uuid.uuid4(), counter),
    )
    other = svc.execute(
        scope="POST /two",
        key="key-scope-1",
        principal_id="w",
        request_hash=req,
        action=_action_appending(uuid.uuid4(), counter),
    )
    assert other.replayed is False and counter == [2]


def test_an_action_that_raises_leaves_no_record_so_a_retry_runs_cleanly(db: Database) -> None:
    svc = IdempotencyService(db)
    aggregate, counter = uuid.uuid4(), [0]

    def failing(tx):
        counter[0] += 1
        append_event(
            tx,
            aggregate_type="season",
            aggregate_id=aggregate,
            event_type="season.state_changed",
            payload={},
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )
        raise RuntimeError("downstream rejected the job")

    with pytest.raises(RuntimeError):
        svc.execute(
            scope="POST /x",
            key="key-fail-1",
            principal_id="w",
            request_hash=_hash({"a": 1}),
            action=failing,
        )
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM idempotency_records WHERE idempotency_key = 'key-fail-1'"
            )
            == 0
        )
        assert (
            tx.fetchval("SELECT count(*) FROM domain_events WHERE aggregate_id = %s", (aggregate,))
            == 0
        )
    ok = svc.execute(
        scope="POST /x",
        key="key-fail-1",
        principal_id="w",
        request_hash=_hash({"a": 1}),
        action=_action_appending(aggregate, counter),
    )
    assert ok.replayed is False and counter == [2]
    with db.transaction(readonly=True) as tx:
        assert len(list_events(tx, aggregate)) == 1  # the failed attempt's event was rolled back


def test_a_semantic_collision_inside_the_action_rolls_back_the_record(db: Database) -> None:
    from microdrama.contracts.errors import DuplicateSemanticKey

    svc = IdempotencyService(db)

    def collides(tx):
        raise DuplicateSemanticKey("semantic key already used", constraint="jobs_semantic_key_key")

    with pytest.raises(DuplicateSemanticKey):
        svc.execute(
            scope="POST /x",
            key="key-collide-1",
            principal_id="w",
            request_hash=_hash({"a": 1}),
            action=collides,
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM idempotency_records") == 0


def test_concurrent_executions_with_one_key_run_the_action_exactly_once(db: Database) -> None:
    svc = IdempotencyService(db)
    aggregate, counter = uuid.uuid4(), [0]
    counter_lock = threading.Lock()
    results = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def action(tx):
        with counter_lock:
            counter[0] += 1
        return _action_appending(aggregate, [0], {"status": "QUEUED", "shared": True})(tx)

    def go() -> None:
        barrier.wait()
        try:
            results.append(
                svc.execute(
                    scope="POST /race",
                    key="key-race-0001",
                    principal_id="w",
                    request_hash=_hash({"x": 1}),
                    action=action,
                )
            )
        except BaseException as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    assert counter == [1]
    assert len(results) == 8
    assert sum(1 for r in results if not r.replayed) == 1
    assert {tuple(sorted(r.body.items())) for r in results} == {
        (("shared", True), ("status", "QUEUED"))
    }
    with db.transaction(readonly=True) as tx:
        assert len(list_events(tx, aggregate)) == 1


def test_concurrent_executions_with_conflicting_content_settle_on_one_outcome(db: Database) -> None:
    svc = IdempotencyService(db)
    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def go(request: dict) -> None:
        barrier.wait()
        try:
            svc.execute(
                scope="POST /race2",
                key="key-race-0002",
                principal_id="w",
                request_hash=_hash(request),
                action=_action_appending(uuid.uuid4(), [0]),
            )
            result = "ok"
        except IdempotencyConflict:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=go, args=({"v": 1},)),
        threading.Thread(target=go, args=({"v": 2},)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(outcomes) == ["conflict", "ok"]


def test_invalid_arguments_are_schema_errors(db: Database) -> None:
    svc = IdempotencyService(db)
    with pytest.raises(SchemaInvalid):
        svc.execute(
            scope="", key="k", principal_id="w", request_hash=_hash({}), action=lambda tx: (202, {})
        )
    with pytest.raises(SchemaInvalid):
        svc.execute(
            scope="s",
            key="k",
            principal_id="w",
            request_hash="not-a-hash",
            action=lambda tx: (202, {}),
        )
    with pytest.raises(SchemaInvalid):
        svc.execute(
            scope="s",
            key="k2",
            principal_id="w",
            request_hash=_hash({}),
            action=lambda tx: (500, {}),
        )
    with pytest.raises(SchemaInvalid):
        svc.execute(
            scope="s",
            key="k3",
            principal_id="w",
            request_hash=_hash({}),
            action=lambda tx: (202, []),
        )  # type: ignore[arg-type,return-value]
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM idempotency_records") == 0


def test_stored_responses_never_hold_floats(db: Database) -> None:
    svc = IdempotencyService(db)
    with pytest.raises(SchemaInvalid):
        svc.execute(
            scope="s",
            key="key-float-1",
            principal_id="w",
            request_hash=_hash({}),
            action=lambda tx: (202, {"price": 0.25}),
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM idempotency_records") == 0

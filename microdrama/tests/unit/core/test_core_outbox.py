"""Transactional outbox: sequences, atomicity, at-least-once dispatch and consumer dedupe (real DB)."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import pytest

from microdrama.contracts.enums import EpisodeState
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.core.events import OutboxDispatcher, append_event, consume_once, list_events
from microdrama.persistence import Database

pytestmark = pytest.mark.db
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class _Crash(BaseException):
    """Simulates the process dying: not an Exception, so the dispatcher cannot catch it."""


def _append(
    db: Database, aggregate: uuid.UUID, n: int = 1, *, aggregate_type: str = "episode"
) -> list:
    out = []
    with db.transaction() as tx:
        for i in range(n):
            out.append(
                append_event(
                    tx,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate,
                    event_type="episode.state_changed",
                    payload={"step": i},
                    correlation_id=uuid.uuid4(),
                    occurred_at=T0,
                )
            )
    return out


def test_sequences_are_monotonic_and_list_in_order(db: Database) -> None:
    aggregate = uuid.uuid4()
    events = _append(db, aggregate, 3)
    assert [e.sequence for e in events] == [1, 2, 3]
    with db.transaction(readonly=True) as tx:
        listed = list_events(tx, aggregate)
    assert [e.sequence for e in listed] == [1, 2, 3]
    assert listed[0].event_id == events[0].event_id
    assert listed[0].payload == {"step": 0}
    assert listed[0].schema_version == "1.0"
    assert listed[0].occurred_at == T0


def test_sequences_are_per_aggregate(db: Database) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    _append(db, a, 2)
    first_b = _append(db, b, 1)[0]
    _append(db, a, 1)
    assert first_b.sequence == 1
    with db.transaction(readonly=True) as tx:
        assert [e.sequence for e in list_events(tx, a)] == [1, 2, 3]


def test_payload_is_stored_as_canonical_json_with_typed_values_normalised(db: Database) -> None:
    class Gate(StrEnum):
        APPROVE = "APPROVE"

    aggregate = uuid.uuid4()
    with db.transaction() as tx:
        event = append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=aggregate,
            event_type="approval.recorded",
            payload={
                "gate": Gate.APPROVE,
                "episode": EpisodeState.AWAITING_FINAL_REVIEW,
                "ref": aggregate,
            },
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )
    assert event.payload == {
        "gate": "APPROVE",
        "episode": "AWAITING_FINAL_REVIEW",
        "ref": str(aggregate),
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"ratio": 0.5},  # floats are refused everywhere
        {"blob": "x" * 20_000},  # over the 16 KiB contract bound
        {"nested": {"when": "not-a-timestamp-object"}, "f": [1.25]},
    ],
)
def test_invalid_payloads_are_refused_and_leave_no_sequence_gap(db: Database, payload) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 1)
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=aggregate,
            event_type="episode.state_changed",
            payload=payload,
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )
    (follow_up,) = _append(db, aggregate, 1)
    assert follow_up.sequence == 2


@pytest.mark.parametrize(
    "event_type, occurred_at",
    [("EpisodeChanged", T0), ("episode.state_changed", datetime(2026, 10, 20, 9, 0))],
)
def test_bad_event_type_or_naive_time_is_schema_invalid(
    db: Database, event_type, occurred_at
) -> None:
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=uuid.uuid4(),
            event_type=event_type,
            payload={},
            correlation_id=uuid.uuid4(),
            occurred_at=occurred_at,
        )


def test_an_aggregate_cannot_switch_type_midstream(db: Database) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 1, aggregate_type="episode")
    with pytest.raises(Conflict), db.transaction() as tx:
        append_event(
            tx,
            aggregate_type="season",
            aggregate_id=aggregate,
            event_type="season.state_changed",
            payload={},
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )


def test_rolled_back_appends_do_not_consume_sequence_numbers(db: Database) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 1)
    with pytest.raises(RuntimeError), db.transaction() as tx:
        append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=aggregate,
            event_type="episode.state_changed",
            payload={},
            correlation_id=uuid.uuid4(),
            occurred_at=T0,
        )
        raise RuntimeError("business rule failed after the append")
    (second,) = _append(db, aggregate, 1)
    assert second.sequence == 2


def test_concurrent_appenders_get_unique_gapless_sequences(db: Database) -> None:
    aggregate = uuid.uuid4()
    errors: list[BaseException] = []
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(20):
                for event in _append(db, aggregate, 1):
                    with lock:
                        seen.append(event.sequence)
        except BaseException as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    assert sorted(seen) == list(range(1, 161))
    with db.transaction(readonly=True) as tx:
        stored = [e.sequence for e in list_events(tx, aggregate)]
    assert stored == list(range(1, 161))


def test_dispatcher_publishes_in_global_order_once_and_records_the_transport(db: Database) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    _append(db, a, 2)
    _append(db, b, 2)
    published: list[tuple[str, int]] = []
    dispatcher = OutboxDispatcher(
        db, transport="test-bus", publish=lambda e: published.append((e.event_type, e.sequence))
    )
    assert dispatcher.dispatch_pending(limit=100) == 4
    assert dispatcher.dispatch_pending(limit=100) == 0
    assert len(published) == 4
    with db.transaction(readonly=True) as tx:
        transports = tx.fetchall("SELECT DISTINCT transport FROM event_dispatches")
    assert [r["transport"] for r in transports] == ["test-bus"]


def test_dispatcher_is_at_least_once_when_the_process_dies_before_commit(db: Database) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 2)
    seen: list[int] = []

    def crash_after_publish(event) -> None:
        seen.append(event.sequence)  # the external effect happened ...
        raise _Crash()  # ... but the dispatch record was never committed

    with pytest.raises(_Crash):
        OutboxDispatcher(db, transport="bus", publish=crash_after_publish).dispatch_pending()
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM event_dispatches") == 0

    recovered: list[int] = []
    assert (
        OutboxDispatcher(
            db, transport="bus", publish=lambda e: recovered.append(e.sequence)
        ).dispatch_pending()
        == 2
    )
    assert seen == [1]
    assert recovered == [1, 2]  # expected: event 1 is delivered again (at-least-once)
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM event_dispatches") == 2


def test_publish_error_keeps_earlier_progress_and_retries_the_failing_event(db: Database) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 4)
    calls: list[int] = []
    broker_up = {"value": False}

    def publish(event) -> None:
        calls.append(event.sequence)
        if event.sequence == 3 and not broker_up["value"]:
            raise RuntimeError("broker unavailable")

    dispatcher = OutboxDispatcher(db, transport="bus", publish=publish)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch_pending()
    assert calls == [1, 2, 3]
    with db.transaction(readonly=True) as tx:
        dispatched = [r["event_id"] for r in tx.fetchall("SELECT event_id FROM event_dispatches")]
        assert len(dispatched) == 2  # events 1 and 2 committed; 3 stays pending
    broker_up["value"] = True
    calls.clear()
    assert dispatcher.dispatch_pending() == 2
    assert calls == [3, 4]  # the failing event is retried first, then the rest
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM event_dispatches") == 4


def test_concurrent_dispatchers_never_publish_the_same_event_twice(db: Database) -> None:
    aggregate = uuid.uuid4()
    _append(db, aggregate, 200)
    published: list[uuid.UUID] = []
    lock = threading.Lock()

    def publish(event) -> None:
        with lock:
            published.append(event.event_id)

    def drain() -> None:
        dispatcher = OutboxDispatcher(db, transport="bus", publish=publish)
        while dispatcher.dispatch_pending(limit=10):
            pass

    threads = [threading.Thread(target=drain) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    assert len(published) == 200
    assert len(set(published)) == 200


def test_consume_once_is_true_only_the_first_time(db: Database) -> None:
    (event,) = _append(db, uuid.uuid4(), 1)
    with db.transaction() as tx:
        assert consume_once(tx, "projection.episode", event.event_id) is True
    with db.transaction() as tx:
        assert consume_once(tx, "projection.episode", event.event_id) is False
    with db.transaction() as tx:
        assert consume_once(tx, "projection.other", event.event_id) is True  # per consumer


def test_consume_once_races_admit_exactly_one_winner(db: Database) -> None:
    (event,) = _append(db, uuid.uuid4(), 1)
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def race() -> None:
        barrier.wait()
        with db.transaction() as tx:
            won = consume_once(tx, "notifier", event.event_id)
        with lock:
            results.append(won)

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert results.count(True) == 1 and results.count(False) == 7


def test_consume_once_refuses_an_unknown_event(db: Database) -> None:
    with pytest.raises(Conflict), db.transaction() as tx:
        consume_once(tx, "projection.episode", uuid.uuid4())


def test_dispatcher_rejects_a_zero_limit(db: Database) -> None:
    with pytest.raises(SchemaInvalid):
        OutboxDispatcher(db, transport="bus", publish=lambda e: None).dispatch_pending(limit=0)

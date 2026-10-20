"""Transactional outbox: domain events, per-aggregate sequences, dispatch and consumer dedupe.

Rules:
- ``append_event`` runs inside the caller's transaction, so a state change and its event
  commit or roll back together.
- Sequences are per aggregate and monotonic. ``aggregate_sequences`` is incremented with an
  upsert, which serialises concurrent appenders on the aggregate's row.
- Delivery is at least once. ``OutboxDispatcher`` may publish an event again after a crash
  between publish and commit; consumers dedupe with ``consume_once`` (same transaction as
  their effect).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.events import DomainEvent
from microdrama.contracts.hashing import CanonicalizationError, canonical_json
from microdrama.persistence.db import Database, Tx, jsonb

_CONSUMER_MAX = 200


def _normalized_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-only copy of ``payload`` (sorted keys; UUID/datetime/enum as canonical strings)."""
    try:
        return json.loads(canonical_json(dict(payload)))
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise SchemaInvalid(f"event payload is not canonical JSON: {exc}") from exc


def _build_event(
    *,
    event_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    sequence: int,
    correlation_id: UUID,
    causation_id: UUID | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    try:
        return DomainEvent(
            event_id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            sequence=sequence,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload=payload,
        )
    except ValidationError as exc:
        raise SchemaInvalid(
            "domain event failed validation", errors=[e["msg"] for e in exc.errors()]
        ) from exc


def append_event(
    tx: Tx,
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: Mapping[str, Any],
    correlation_id: UUID,
    occurred_at: datetime,
    causation_id: UUID | None = None,
    event_id: UUID | None = None,
) -> DomainEvent:
    """Append one event to the outbox inside ``tx`` and return it.

    The payload bound (16 KiB, contract) and every field are validated before the sequence
    counter moves, so a rejected event leaves no gap in the aggregate's sequence.
    """
    event_id = event_id or uuid.uuid4()
    body = _normalized_payload(payload)
    # Validate with a placeholder sequence first; nothing has been written yet.
    _build_event(
        event_id=event_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        sequence=1,
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
        payload=body,
    )
    row = tx.fetchone(
        "INSERT INTO aggregate_sequences (aggregate_id, aggregate_type, last_sequence) "
        "VALUES (%s, %s, 1) "
        "ON CONFLICT (aggregate_id) DO UPDATE "
        "SET last_sequence = aggregate_sequences.last_sequence + 1 "
        "RETURNING last_sequence, aggregate_type",
        (aggregate_id, aggregate_type),
    )
    assert row is not None
    if row["aggregate_type"] != aggregate_type:
        raise Conflict(
            "aggregate already has events of another type",
            aggregate_id=str(aggregate_id),
            existing_type=row["aggregate_type"],
        )
    sequence = int(row["last_sequence"])
    event = _build_event(
        event_id=event_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        sequence=sequence,
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
        payload=body,
    )
    tx.execute(
        "INSERT INTO domain_events (event_id, schema_version, event_type, aggregate_type, "
        "aggregate_id, sequence, correlation_id, causation_id, occurred_at, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            event.event_id,
            event.schema_version,
            event.event_type,
            event.aggregate_type,
            event.aggregate_id,
            event.sequence,
            event.correlation_id,
            event.causation_id,
            event.occurred_at,
            jsonb(body),
        ),
    )
    return event


def _event_from_row(row: Mapping[str, Any]) -> DomainEvent:
    return _build_event(
        event_id=row["event_id"],
        event_type=row["event_type"],
        aggregate_type=row["aggregate_type"],
        aggregate_id=row["aggregate_id"],
        sequence=row["sequence"],
        correlation_id=row["correlation_id"],
        causation_id=row["causation_id"],
        occurred_at=row["occurred_at"],
        payload=row["payload"],
    ).model_copy(update={"schema_version": row["schema_version"]})


def list_events(tx: Tx, aggregate_id: UUID) -> list[DomainEvent]:
    """Every event of one aggregate, in sequence order."""
    rows = tx.fetchall(
        "SELECT * FROM domain_events WHERE aggregate_id = %s ORDER BY sequence",
        (aggregate_id,),
    )
    return [_event_from_row(row) for row in rows]


class OutboxDispatcher:
    """Publishes undispatched events in global order; records each dispatch.

    ``dispatch_pending`` runs one transaction: rows are locked with ``FOR UPDATE SKIP LOCKED``
    so concurrent dispatchers never hold the same event, and each event is re-checked after its
    lock is acquired (a concurrent dispatcher may have committed it meanwhile). If ``publish``
    raises, the events already published in the batch are committed and the error is re-raised;
    the failing event stays pending and is retried on the next call.
    """

    def __init__(
        self,
        db: Database,
        *,
        transport: str,
        publish: Callable[[DomainEvent], None],
    ) -> None:
        if not transport:
            raise SchemaInvalid("dispatcher transport name is required")
        self._db = db
        self._transport = transport
        self._publish = publish

    def dispatch_pending(self, limit: int = 100) -> int:
        if limit < 1:
            raise SchemaInvalid("limit must be at least 1")
        dispatched = 0
        failure: BaseException | None = None
        with self._db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT * FROM domain_events e "
                "WHERE NOT EXISTS (SELECT 1 FROM event_dispatches d WHERE d.event_id = e.event_id) "
                "ORDER BY e.global_position LIMIT %s FOR UPDATE SKIP LOCKED",
                (limit,),
            )
            for row in rows:
                already = tx.fetchone(
                    "SELECT 1 AS present FROM event_dispatches WHERE event_id = %s",
                    (row["event_id"],),
                )
                if already is not None:
                    continue
                try:
                    self._publish(_event_from_row(row))
                except Exception as exc:  # re-raised after committing earlier progress
                    failure = exc
                    break
                tx.execute(
                    "INSERT INTO event_dispatches (event_id, transport) VALUES (%s, %s)",
                    (row["event_id"], self._transport),
                )
                dispatched += 1
        if failure is not None:
            raise failure
        return dispatched


def consume_once(tx: Tx, consumer: str, event_id: UUID) -> bool:
    """True the first time ``consumer`` sees ``event_id``; False on every replay.

    Call it inside the same transaction as the consumer's effect so the effect and the
    dedupe record commit together. An unknown event id is a foreign-key ``Conflict``.
    """
    if not consumer or len(consumer) > _CONSUMER_MAX:
        raise SchemaInvalid("consumer name must be 1..200 characters")
    row = tx.fetchone(
        "INSERT INTO event_consumptions (consumer, event_id) VALUES (%s, %s) "
        "ON CONFLICT (consumer, event_id) DO NOTHING RETURNING consumer",
        (consumer, event_id),
    )
    return row is not None


__all__ = [
    "OutboxDispatcher",
    "append_event",
    "consume_once",
    "list_events",
]

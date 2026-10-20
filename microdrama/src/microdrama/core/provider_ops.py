"""Durable provider operations: the shared discipline for ambiguous external effects.

Every external call (submit, poll, cancel) is first recorded with ``begin`` under a client token,
so a crash can never create an untracked external request. The state machine allows:

    PENDING_SUBMIT -> SUBMITTED | RUNNING | SUCCEEDED | FAILED | UNKNOWN | NOT_FOUND
    SUBMITTED / RUNNING -> RUNNING | SUCCEEDED | FAILED | UNKNOWN | CANCELLED
    UNKNOWN -> NOT_FOUND | SUBMITTED | RUNNING | SUCCEEDED | FAILED
    NOT_FOUND -> PENDING_SUBMIT only through ``resubmit_allowed`` (reconciliation proved the
                 provider never accepted the request)
    SUCCEEDED / FAILED / CANCELLED are terminal

UNKNOWN is never resubmitted: it must be reconciled first.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.cost import (
    UNMETERED_OPERATION_KINDS,
    ProviderOperation,
    ProviderOperationResult,
)
from microdrama.contracts.enums import ProviderOperationState
from microdrama.contracts.errors import (
    Conflict,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    SchemaInvalid,
)
from microdrama.core.events import append_event
from microdrama.persistence.db import Tx, update_with_revision

_S = ProviderOperationState
ALLOWED_MOVES: Mapping[ProviderOperationState, frozenset[ProviderOperationState]] = {
    _S.PENDING_SUBMIT: frozenset(
        {_S.SUBMITTED, _S.RUNNING, _S.SUCCEEDED, _S.FAILED, _S.UNKNOWN, _S.NOT_FOUND}
    ),
    _S.SUBMITTED: frozenset({_S.RUNNING, _S.SUCCEEDED, _S.FAILED, _S.UNKNOWN, _S.CANCELLED}),
    _S.RUNNING: frozenset({_S.RUNNING, _S.SUCCEEDED, _S.FAILED, _S.UNKNOWN, _S.CANCELLED}),
    _S.UNKNOWN: frozenset({_S.NOT_FOUND, _S.SUBMITTED, _S.RUNNING, _S.SUCCEEDED, _S.FAILED}),
    _S.SUCCEEDED: frozenset(),
    _S.FAILED: frozenset(),
    _S.CANCELLED: frozenset(),
    _S.NOT_FOUND: frozenset(),
}
_IN_FLIGHT = frozenset({_S.PENDING_SUBMIT, _S.SUBMITTED, _S.RUNNING, _S.UNKNOWN})
_SUBMISSION_STATES = frozenset({_S.SUBMITTED, _S.RUNNING, _S.SUCCEEDED})


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _operation(row: Mapping[str, Any]) -> ProviderOperation:
    return ProviderOperation(
        operation_id=row["id"],
        provider=row["provider"],
        operation_kind=row["operation_kind"],
        client_token=row["client_token"],
        request_sha256=row["request_hash"],
        job_id=row["job_id"],
        reservation_id=row["reservation_id"],
        state=ProviderOperationState(row["state"]),
        external_id=row["external_id"],
        attempt=row["attempt"],
        submitted_at=row["submitted_at"],
        deadline_at=row["deadline_at"],
    )


def _emit(tx: Tx, row: Mapping[str, Any], now: datetime, previous: str | None, target: str) -> None:
    append_event(
        tx,
        aggregate_type="provider_operation",
        aggregate_id=row["id"],
        event_type="provider_operation.state_changed",
        payload={"from": previous, "to": target, "operation_kind": row["operation_kind"]},
        correlation_id=row["job_id"] or row["id"],
        occurred_at=now,
    )


def _lock(tx: Tx, operation_id: UUID) -> dict[str, Any]:
    row = tx.fetchone("SELECT * FROM provider_operations WHERE id = %s FOR UPDATE", (operation_id,))
    if row is None:
        raise NotFound(f"provider operation {operation_id} not found")
    return row


def load(tx: Tx, operation_id: UUID) -> ProviderOperation:
    row = tx.fetchone("SELECT * FROM provider_operations WHERE id = %s", (operation_id,))
    if row is None:
        raise NotFound(f"provider operation {operation_id} not found")
    return _operation(row)


_IN_FLIGHT_VALUES = [
    ProviderOperationState.PENDING_SUBMIT.value,
    ProviderOperationState.SUBMITTED.value,
    ProviderOperationState.RUNNING.value,
    ProviderOperationState.UNKNOWN.value,
]


def _lock_linked(tx: Tx, job_id: UUID, reservation_id: UUID | None) -> None:
    """Serialise operation starts per job, then per reservation (always in this order).

    Transaction-level advisory locks: two begins (or a begin and a resubmit) on the same job or the
    same reservation cannot both pass the in-flight check before either has committed. The
    reservation row lock taken by begin (shared) still serialises it with budget release.
    """
    tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"md-job:{job_id}",))
    if reservation_id is not None:
        tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"md-reservation:{reservation_id}",),
        )


def _linked_in_flight(
    tx: Tx, *, job_id: UUID, reservation_id: UUID | None, exclude: UUID
) -> list[dict[str, Any]]:
    """Other operations on the same job or reservation that are still in flight (oldest first)."""
    return tx.fetchall(
        "SELECT id, state, job_id, reservation_id FROM provider_operations "
        "WHERE state = ANY(%s) AND (job_id = %s OR reservation_id = %s) AND id <> %s "
        "ORDER BY created_at, id",
        (_IN_FLIGHT_VALUES, job_id, reservation_id, exclude),
    )


def _summary(rows: list[dict[str, Any]]) -> str:
    return ", ".join(f"{row['id']}={row['state']}" for row in rows)


def begin(
    tx: Tx,
    *,
    provider: str,
    operation_kind: str,
    client_token: str,
    request_hash: str,
    deadline_at: datetime,
    job_id: UUID,
    now: datetime,
    reservation_id: UUID | None = None,
    episode_id: UUID | None = None,
) -> ProviderOperation:
    """Record an intended external call (idempotent on ``(provider, client_token)``).

    Rules, all enforced before anything is written:
    - ``job_id`` is required: recovery finds in-flight operations through their job.
    - ``reservation_id`` is required unless ``operation_kind`` is in ``UNMETERED_OPERATION_KINDS``
      (empty in this build). Every paid call is budgeted.
    - The reservation must be ACTIVE. A shared row lock on it serialises this begin with budget
      release (which takes FOR UPDATE): if begin wins, release sees the operation and refuses; if
      release wins, begin sees the closed reservation and refuses.
    - A replay of an existing ``client_token`` returns that operation (the same request is never
      sent twice). A new operation is refused while any *other* operation linked to the same job or
      the same reservation is PENDING_SUBMIT, SUBMITTED, RUNNING or UNKNOWN. The only route to a
      second submission is reconciliation to NOT_FOUND followed by ``resubmit_allowed``. A NOT_FOUND
      operation on the same job also refuses a new token, so the resubmission keeps its token.
    """
    if job_id is None:
        raise SchemaInvalid("provider operations must be linked to the job that owns them")
    for name, value in (
        ("provider", provider),
        ("operation_kind", operation_kind),
        ("client_token", client_token),
    ):
        if not isinstance(value, str) or not value or len(value) > 500:
            raise SchemaInvalid(f"{name} must be a non-empty string of at most 500 characters")
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        raise SchemaInvalid("request_hash must be a 64-character SHA-256 hex digest")
    if reservation_id is None and operation_kind not in UNMETERED_OPERATION_KINDS:
        raise SchemaInvalid(
            "every provider operation needs a budget reservation; "
            f"{operation_kind} is not a registered unmetered kind",
            operation_kind=operation_kind,
        )
    deadline = _aware(deadline_at, "deadline_at")
    instant = _aware(now, "now")
    if reservation_id is not None:
        reservation = tx.fetchone(
            "SELECT state FROM reservations WHERE id = %s FOR SHARE", (reservation_id,)
        )
        if reservation is None:
            raise NotFound(f"reservation {reservation_id} not found")
        if reservation["state"] != "ACTIVE":
            raise Conflict(
                "reservation is not ACTIVE",
                reservation_id=str(reservation_id),
                state=reservation["state"],
            )

    _lock_linked(tx, job_id, reservation_id)
    existing = tx.fetchone(
        "SELECT * FROM provider_operations WHERE provider = %s AND client_token = %s",
        (provider, client_token),
    )
    if existing is not None:  # a replay: no new external call, whatever else is in flight
        return _same_request(existing, operation_kind, request_hash)

    operation_id = uuid.uuid4()
    blocking = _linked_in_flight(
        tx, job_id=job_id, reservation_id=reservation_id, exclude=operation_id
    )
    if blocking:
        raise Conflict(
            "a provider operation on this job or reservation is still in flight; "
            "reconcile it before starting another",
            operations=[{"id": str(row["id"]), "state": row["state"]} for row in blocking],
            summary=_summary(blocking),
        )
    not_found = tx.fetchall(
        "SELECT id, state FROM provider_operations WHERE job_id = %s AND state = 'NOT_FOUND' "
        "ORDER BY created_at, id",
        (job_id,),
    )
    if not_found:
        raise Conflict(
            "this job has a NOT_FOUND provider operation; resubmit it with resubmit_allowed "
            "(same client token) instead of starting a new one",
            operations=[{"id": str(row["id"]), "state": row["state"]} for row in not_found],
            summary=_summary(not_found),
        )
    inserted = tx.fetchone(
        "INSERT INTO provider_operations (id, provider, operation_kind, client_token, request_hash, "
        "job_id, reservation_id, state, attempt, deadline_at, episode_id, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING_SUBMIT', 1, %s, %s, %s, %s) "
        "ON CONFLICT (provider, client_token) DO NOTHING RETURNING *",
        (
            operation_id,
            provider,
            operation_kind,
            client_token,
            request_hash,
            job_id,
            reservation_id,
            deadline,
            episode_id,
            instant,
            instant,
        ),
    )
    if inserted is None:  # pragma: no cover - the advisory lock makes this unreachable
        existing = tx.fetchone(
            "SELECT * FROM provider_operations WHERE provider = %s AND client_token = %s",
            (provider, client_token),
        )
        if existing is None:
            raise Conflict("provider operation changed during begin; retry")
        return _same_request(existing, operation_kind, request_hash)
    _emit(tx, inserted, instant, None, _S.PENDING_SUBMIT.value)
    return _operation(inserted)


def _same_request(
    row: Mapping[str, Any], operation_kind: str, request_hash: str
) -> ProviderOperation:
    if row["request_hash"] != request_hash or row["operation_kind"] != operation_kind:
        raise IdempotencyConflict(
            "client token was already used for a different provider request",
            provider=row["provider"],
        )
    return _operation(row)


def record_result(
    tx: Tx,
    operation_id: UUID,
    result: ProviderOperationResult,
    *,
    now: datetime,
) -> ProviderOperation:
    """Record what the provider reported. Persists ``external_id`` as soon as it is known."""
    if not isinstance(result, ProviderOperationResult):
        raise SchemaInvalid("a ProviderOperationResult is required")
    if result.operation_id != operation_id:
        raise SchemaInvalid("result belongs to a different operation")
    instant = _aware(now, "now")
    row = _lock(tx, operation_id)
    current = ProviderOperationState(row["state"])
    target = result.state
    if target not in ALLOWED_MOVES[current]:
        raise InvalidTransition(
            f"provider operation {current.value} -> {target.value} is not allowed",
            from_state=current.value,
            to_state=target.value,
        )
    if result.external_id is not None and row["external_id"] not in (None, result.external_id):
        raise Conflict(
            "provider external id changed for this operation", operation_id=str(operation_id)
        )

    changes: dict[str, Any] = {
        "state": target.value,
        "last_result": result,
    }
    if result.external_id is not None:
        changes["external_id"] = result.external_id
    if row["submitted_at"] is None and target in _SUBMISSION_STATES:
        changes["submitted_at"] = instant
    updated = update_with_revision(
        tx, "provider_operations", operation_id, row["revision"], changes, now=instant
    )
    _emit(tx, updated, instant, current.value, target.value)
    return _operation(updated)


def needs_reconcile(op: ProviderOperation, *, now: datetime) -> bool:
    """True when the outcome of an external call is unknown and must be reconciled first.

    UNKNOWN always qualifies. A call still SUBMITTED or RUNNING past its deadline qualifies. A
    PENDING_SUBMIT call past its deadline also qualifies: the request may have left before the
    crash, so it is treated as ambiguous rather than as never sent.
    """
    instant = _aware(now, "now")
    if op.state is ProviderOperationState.UNKNOWN:
        return True
    if op.state in _IN_FLIGHT:
        return instant >= op.deadline_at.astimezone(UTC)
    return False


def resubmit_allowed(
    tx: Tx,
    operation_id: UUID,
    *,
    now: datetime,
    deadline_at: datetime | None = None,
) -> ProviderOperation:
    """Re-arm a NOT_FOUND operation for one more submission. UNKNOWN is refused."""
    instant = _aware(now, "now")
    peek = tx.fetchone(
        "SELECT job_id, reservation_id FROM provider_operations WHERE id = %s", (operation_id,)
    )
    if peek is None:
        raise NotFound(f"provider operation {operation_id} not found")
    _lock_linked(tx, peek["job_id"], peek["reservation_id"])
    row = _lock(tx, operation_id)
    current = ProviderOperationState(row["state"])
    if current is not ProviderOperationState.NOT_FOUND:
        raise InvalidTransition(
            f"only a NOT_FOUND operation may be resubmitted; this one is {current.value}",
            state=current.value,
        )
    blocking = _linked_in_flight(
        tx, job_id=row["job_id"], reservation_id=row["reservation_id"], exclude=operation_id
    )
    if blocking:
        raise Conflict(
            "another provider operation on this job or reservation is in flight; "
            "reconcile it before resubmitting",
            operations=[{"id": str(op["id"]), "state": op["state"]} for op in blocking],
            summary=_summary(blocking),
        )
    changes: dict[str, Any] = {
        "state": ProviderOperationState.PENDING_SUBMIT.value,
        "attempt": row["attempt"] + 1,
    }
    if deadline_at is not None:
        changes["deadline_at"] = _aware(deadline_at, "deadline_at")
    updated = update_with_revision(
        tx, "provider_operations", operation_id, row["revision"], changes, now=instant
    )
    _emit(tx, updated, instant, current.value, ProviderOperationState.PENDING_SUBMIT.value)
    return _operation(updated)


__all__ = [
    "ALLOWED_MOVES",
    "begin",
    "load",
    "needs_reconcile",
    "record_result",
    "resubmit_allowed",
]

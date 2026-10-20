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

from microdrama.contracts.cost import ProviderOperation, ProviderOperationResult
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

    ``job_id`` is required: recovery (``JobService.requeue_expired``, ``claim``, ``finish``) finds
    in-flight operations through their job, so an operation without one would be invisible to it.
    ``now`` comes from the caller's injected clock; this module never reads the wall clock.
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
    deadline = _aware(deadline_at, "deadline_at")
    instant = _aware(now, "now")
    if reservation_id is not None:
        # A shared lock on the reservation serialises this begin with budget release (which takes
        # FOR UPDATE): if begin wins, release sees this operation in flight and refuses; if release
        # wins, begin sees the closed reservation and refuses. An operation never starts on a
        # reservation that is not ACTIVE.
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

    existing = tx.fetchone(
        "SELECT * FROM provider_operations WHERE provider = %s AND client_token = %s",
        (provider, client_token),
    )
    if existing is not None:
        return _same_request(existing, operation_kind, request_hash)

    operation_id = uuid.uuid4()
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
    if inserted is None:  # a concurrent begin with the same token committed first
        existing = tx.fetchone(
            "SELECT * FROM provider_operations WHERE provider = %s AND client_token = %s",
            (provider, client_token),
        )
        if existing is None:  # pragma: no cover - defensive
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
    row = _lock(tx, operation_id)
    current = ProviderOperationState(row["state"])
    if current is not ProviderOperationState.NOT_FOUND:
        raise InvalidTransition(
            f"only a NOT_FOUND operation may be resubmitted; this one is {current.value}",
            state=current.value,
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

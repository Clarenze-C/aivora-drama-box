"""Human gate decisions (Gate 1 season concept, Gate 2 episode final) as append-only events.

``record_approval_event`` is the only writer of ``approval_events``. It:
- refuses every principal that is not a human owner with a session (``Unauthorized``);
- locks the entity and requires ``command.expected_revision`` to equal its revision
  (``StaleRevision``); the entity revision is not changed by an approval;
- inserts the decision (the DB trigger also judges the session against the server clock, so a
  revoked or expired session is ``Unauthorized``), one ``feedback_events`` row per REVISE item, and
  an ``approval.recorded`` outbox event;
- runs each ``ApprovalHook`` in the same transaction; a hook that raises rolls the decision back.

A second decision for the same entity revision hits ``approval_events_one_per_revision`` and is
reported as ``StaleRevision`` (HTTP 409). Gate readiness and package binding are checked by the
review module on top of this function, and by the database triggers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import psycopg

from microdrama.contracts.enums import GateType
from microdrama.contracts.errors import (
    DuplicateSemanticKey,
    NotFound,
    SchemaInvalid,
    StaleRevision,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand
from microdrama.core.auth import owner_id_in_tx, require_human_owner
from microdrama.core.events import append_event
from microdrama.core.hooks import ApprovalHook
from microdrama.persistence.db import Tx, insert_row, jsonb, translate_db_error

_ONE_PER_REVISION = "approval_events_one_per_revision"


def _entity(command: ApprovalCommand) -> tuple[str, str]:
    if command.gate is GateType.SEASON_CONCEPT:
        return "season", "seasons"
    return "episode", "episodes"


def record_approval_event(
    tx: Tx,
    *,
    principal: Principal,
    command: ApprovalCommand,
    now: datetime,
    correlation_id: UUID,
    hooks: Sequence[ApprovalHook] = (),
) -> UUID:
    """Record one human decision inside ``tx`` and return its approval event id."""
    require_human_owner(principal)
    if not isinstance(command, ApprovalCommand):
        raise SchemaInvalid("an ApprovalCommand is required")
    entity_type, table = _entity(command)
    row = tx.fetchone(
        f"SELECT id, revision FROM {table} WHERE id = %s FOR UPDATE", (command.entity_id,)
    )
    if row is None:
        raise NotFound(f"{entity_type} {command.entity_id} not found")
    if row["revision"] != command.expected_revision:
        raise StaleRevision(
            f"{entity_type} is at revision {row['revision']}, decision was made at "
            f"{command.expected_revision}",
            current_revision=row["revision"],
            expected_revision=command.expected_revision,
        )

    approval_id = uuid.uuid4()
    owner_id = owner_id_in_tx(tx, principal)
    try:
        insert_row(
            tx,
            "approval_events",
            {
                "id": approval_id,
                "gate_type": command.gate.value,
                "action": command.action.value,
                "entity_type": entity_type,
                "entity_id": command.entity_id,
                "expected_revision": command.expected_revision,
                "package_hash": command.package_hash,
                "media_hashes": jsonb(list(command.media_hashes)),
                "management_policy_hash": command.management_policy_hash,
                "release_scope_hash": command.release_scope_hash,
                "actor_owner_id": owner_id,
                "actor_session_id": principal.session_id,
                "idempotency_key": command.idempotency_key,
                "command_hash": canonical_hash(command),
                "feedback": jsonb([item.model_dump(mode="json") for item in command.feedback]),
                "reason": command.reason,
            },
            returning="id",
        )
    except psycopg.Error as exc:
        # Inside a transaction the driver error is still raw; translate it here so the one-
        # decision-per-revision index is reported as a stale decision, not a generic conflict.
        translated = translate_db_error(exc)
        if (
            isinstance(translated, DuplicateSemanticKey)
            and translated.details.get("constraint") == _ONE_PER_REVISION
        ):
            raise StaleRevision(
                "a decision was already recorded for this entity revision",
                expected_revision=command.expected_revision,
                constraint=_ONE_PER_REVISION,
            ) from exc
        raise translated from exc

    for item in command.feedback:
        insert_row(
            tx,
            "feedback_events",
            {
                "id": uuid.uuid4(),
                "episode_id": command.entity_id,
                "approval_event_id": approval_id,
                "category": item.category.value,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "asset_id": item.asset_id,
                "shot_key": item.shot_id,
                "comment": item.comment,
                "scope": item.scope.value,
                "explicit_recurring": item.explicit_recurring_instruction,
            },
            returning="id",
        )

    append_event(
        tx,
        aggregate_type=entity_type,
        aggregate_id=command.entity_id,
        event_type="approval.recorded",
        payload={
            "approval_event_id": approval_id,
            "gate": command.gate.value,
            "action": command.action.value,
            "package_hash": command.package_hash,
            "expected_revision": command.expected_revision,
        },
        correlation_id=correlation_id,
        occurred_at=now,
    )
    for hook in hooks:
        hook.on_recorded(tx, approval_event_id=approval_id, command=command, principal=principal)
    return approval_id


__all__ = ["record_approval_event"]

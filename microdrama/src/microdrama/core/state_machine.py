"""Season and episode state enforcement against the frozen tables in ``contracts.states``.

Every function:
- locks the entity row (``SELECT ... FOR UPDATE``) and rejects a stale ``expected_revision``
  with ``StaleRevision``;
- rejects a move that is not in the table with ``InvalidTransition``;
- for human-only moves, requires an authenticated human owner and a matching approval event for
  this entity (``Unauthorized`` otherwise; a stale approval is ``StaleRevision``);
- writes the state change (``revision + 1``) and its outbox event in the same transaction.

Interpretations recorded in the handoff:
- An episode with a recoverable outcome is held: no transition until the outcome is cleared with
  evidence. An episode with a terminal outcome can never transition or be cleared.
- A Gate 2 REVISE approval moves the episode from AWAITING_FINAL_REVIEW to a repair stage; the
  executing actor may be automatic, the decision itself must be human.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import (
    ApprovalAction,
    EpisodeOutcome,
    EpisodeState,
    GateType,
    SeasonState,
)
from microdrama.contracts.errors import (
    InvalidTransition,
    NotFound,
    SchemaInvalid,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.principals import Principal
from microdrama.contracts.states import (
    EPISODE_HUMAN_ONLY,
    EPISODE_REVISION_TARGETS,
    EPISODE_TRANSITIONS,
    HUMAN_ONLY_OUTCOMES,
    RECOVERABLE_OUTCOMES,
    SEASON_HUMAN_ONLY,
    SEASON_TRANSITIONS,
    TERMINAL_OUTCOMES,
)
from microdrama.core.auth import require_human_owner, require_state_actor
from microdrama.core.events import append_event
from microdrama.core.hooks import TransitionGuard
from microdrama.persistence.db import Tx, update_with_revision

_DETAIL_MAX = 2000


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid(f"{name} must be timezone-aware")
    return value


def _lock(tx: Tx, table: str, row_id: UUID, expected_revision: int) -> dict[str, Any]:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise SchemaInvalid("expected_revision must be an integer")
    row = tx.fetchone(f"SELECT * FROM {table} WHERE id = %s FOR UPDATE", (row_id,))
    if row is None:
        raise NotFound(f"{table} {row_id} not found")
    if row["revision"] != expected_revision:
        raise StaleRevision(
            f"{table} {row_id} is at revision {row['revision']}, expected {expected_revision}",
            current_revision=row["revision"],
            expected_revision=expected_revision,
        )
    return row


def _require_gate_approval(
    tx: Tx,
    *,
    approval_event_id: UUID | None,
    gate: GateType,
    action: ApprovalAction,
    entity_type: str,
    entity_id: UUID,
    expected_revision: int,
) -> dict[str, Any]:
    """The approval must exist, match gate/action/entity, and be for the current revision."""
    if approval_event_id is None:
        raise Unauthorized(
            f"this transition requires a {gate.value} {action.value} approval event",
            gate=gate.value,
            action=action.value,
        )
    row = tx.fetchone("SELECT * FROM approval_events WHERE id = %s", (approval_event_id,))
    if (
        row is None
        or row["gate_type"] != gate.value
        or row["action"] != action.value
        or row["entity_type"] != entity_type
        or row["entity_id"] != entity_id
    ):
        raise Unauthorized(
            "approval event does not authorise this transition",
            approval_event_id=str(approval_event_id),
        )
    if row["expected_revision"] != expected_revision:
        raise StaleRevision(
            "approval event was recorded for a different entity revision",
            approval_revision=row["expected_revision"],
            expected_revision=expected_revision,
        )
    return row


def _reject_unused_approval(approval_event_id: UUID | None) -> None:
    if approval_event_id is not None:
        raise SchemaInvalid("approval_event_id is not used by this transition")


def _event_payload(
    *,
    from_state: str,
    to_state: str,
    actor: Principal,
    approval_event_id: UUID | None,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "from": from_state,
        "to": to_state,
        "actor_kind": actor.kind.value,
        "approval_event_id": approval_event_id,
        "reason": reason,
    }


def transition_season(
    tx: Tx,
    *,
    season_id: UUID,
    to: SeasonState,
    expected_revision: int,
    actor: Principal,
    now: datetime,
    correlation_id: UUID,
    approval_event_id: UUID | None = None,
    scope_version: int | None = None,
    reason: str | None = None,
) -> int:
    """Move a season along ``SEASON_TRANSITIONS``; return the new revision."""
    require_state_actor(actor)  # models and webhooks never write state (first, before any write)
    target = SeasonState(to)
    _aware(now, "now")
    row = _lock(tx, "seasons", season_id, expected_revision)
    current = SeasonState(row["state"])
    if target not in SEASON_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(
            f"season {current.value} -> {target.value} is not allowed",
            from_state=current.value,
            to_state=target.value,
        )

    changes: dict[str, Any] = {"state": target.value}
    recorded_approval: UUID | None = None
    if (current, target) in SEASON_HUMAN_ONLY:
        require_human_owner(actor)
        action = (
            ApprovalAction.APPROVE
            if target is SeasonState.SEASON_APPROVED
            else ApprovalAction.REJECT
        )
        approval = _require_gate_approval(
            tx,
            approval_event_id=approval_event_id,
            gate=GateType.SEASON_CONCEPT,
            action=action,
            entity_type="season",
            entity_id=season_id,
            expected_revision=expected_revision,
        )
        recorded_approval = approval["id"]
        if target is SeasonState.SEASON_APPROVED:
            if scope_version is None or scope_version < 1:
                raise SchemaInvalid("approving a season requires its scope_version (>= 1)")
            # The DB binds approved_scope_hash to the approval; the season row records the
            # decision it was approved by. A rejection does not bind the season row.
            changes.update(
                approval_event_id=approval["id"],
                approved_scope_hash=approval["package_hash"],
                approved_scope_version=scope_version,
                approved_at=now,
            )
    else:
        _reject_unused_approval(approval_event_id)
        if scope_version is not None:
            raise SchemaInvalid("scope_version is only accepted when approving a season")

    updated = update_with_revision(tx, "seasons", season_id, expected_revision, changes, now=now)
    append_event(
        tx,
        aggregate_type="season",
        aggregate_id=season_id,
        event_type="season.state_changed",
        payload=_event_payload(
            from_state=current.value,
            to_state=target.value,
            actor=actor,
            approval_event_id=recorded_approval,
            reason=reason,
        ),
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return int(updated["revision"])


def transition_episode(
    tx: Tx,
    *,
    episode_id: UUID,
    to: EpisodeState,
    expected_revision: int,
    actor: Principal,
    now: datetime,
    correlation_id: UUID,
    approval_event_id: UUID | None = None,
    reason: str | None = None,
    guards: Mapping[EpisodeState, Sequence[TransitionGuard]] | None = None,
) -> int:
    """Move an episode along ``EPISODE_TRANSITIONS``; return the new revision."""
    require_state_actor(actor)  # models and webhooks never write state (first, before any write)
    target = EpisodeState(to)
    _aware(now, "now")
    row = _lock(tx, "episodes", episode_id, expected_revision)
    current = EpisodeState(row["state"])
    if row["outcome"] is not None:
        outcome = EpisodeOutcome(row["outcome"])
        if outcome in TERMINAL_OUTCOMES:
            raise InvalidTransition(
                f"episode has terminal outcome {outcome.value}; it cannot transition",
                outcome=outcome.value,
            )
        raise InvalidTransition(
            f"episode is held by recoverable outcome {outcome.value}; clear it with evidence first",
            outcome=outcome.value,
        )
    if target not in EPISODE_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(
            f"episode {current.value} -> {target.value} is not allowed",
            from_state=current.value,
            to_state=target.value,
        )

    recorded_approval: UUID | None = None
    if (current, target) in EPISODE_HUMAN_ONLY:
        require_human_owner(actor)
        approval = _require_gate_approval(
            tx,
            approval_event_id=approval_event_id,
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_type="episode",
            entity_id=episode_id,
            expected_revision=expected_revision,
        )
        recorded_approval = approval["id"]
    elif current is EpisodeState.AWAITING_FINAL_REVIEW and target in EPISODE_REVISION_TARGETS:
        approval = _require_gate_approval(
            tx,
            approval_event_id=approval_event_id,
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.REVISE,
            entity_type="episode",
            entity_id=episode_id,
            expected_revision=expected_revision,
        )
        recorded_approval = approval["id"]
    else:
        # AI_REVIEW -> repair stage is automatic; other moves need no approval at all.
        _reject_unused_approval(approval_event_id)

    for guard in (guards or {}).get(target, ()):
        guard(tx, dict(row), target)

    updated = update_with_revision(
        tx, "episodes", episode_id, expected_revision, {"state": target.value}, now=now
    )
    append_event(
        tx,
        aggregate_type="episode",
        aggregate_id=episode_id,
        event_type="episode.state_changed",
        payload=_event_payload(
            from_state=current.value,
            to_state=target.value,
            actor=actor,
            approval_event_id=recorded_approval,
            reason=reason,
        ),
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return int(updated["revision"])


def set_episode_outcome(
    tx: Tx,
    *,
    episode_id: UUID,
    outcome: EpisodeOutcome,
    expected_revision: int,
    actor: Principal,
    now: datetime,
    correlation_id: UUID,
    detail: str,
    approval_event_id: UUID | None = None,
) -> int:
    """Record a typed outcome beside the last valid stage; return the new revision."""
    require_state_actor(actor)  # models and webhooks never write state (first, before any write)
    value = EpisodeOutcome(outcome)
    _aware(now, "now")
    if not isinstance(detail, str) or not detail.strip() or len(detail) > _DETAIL_MAX:
        raise SchemaInvalid("outcome detail must be a non-empty string of at most 2000 characters")
    row = _lock(tx, "episodes", episode_id, expected_revision)
    if row["outcome"] is not None:
        existing = EpisodeOutcome(row["outcome"])
        if existing in TERMINAL_OUTCOMES:
            raise InvalidTransition(
                f"episode already has terminal outcome {existing.value}",
                outcome=existing.value,
            )
        raise InvalidTransition(
            f"episode already has outcome {existing.value}; clear it before recording another",
            outcome=existing.value,
        )

    recorded_approval: UUID | None = None
    if value in HUMAN_ONLY_OUTCOMES:
        require_human_owner(actor)
        approval = _require_gate_approval(
            tx,
            approval_event_id=approval_event_id,
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.REJECT,
            entity_type="episode",
            entity_id=episode_id,
            expected_revision=expected_revision,
        )
        recorded_approval = approval["id"]
    else:
        _reject_unused_approval(approval_event_id)

    updated = update_with_revision(
        tx,
        "episodes",
        episode_id,
        expected_revision,
        {"outcome": value.value, "outcome_detail": detail},
        now=now,
    )
    append_event(
        tx,
        aggregate_type="episode",
        aggregate_id=episode_id,
        event_type="episode.outcome_set",
        payload={
            "outcome": value.value,
            "state": row["state"],
            "actor_kind": actor.kind.value,
            "approval_event_id": recorded_approval,
            "reason": detail,
        },
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return int(updated["revision"])


def clear_episode_outcome(
    tx: Tx,
    *,
    episode_id: UUID,
    expected_revision: int,
    actor: Principal,
    now: datetime,
    correlation_id: UUID,
    evidence: str,
) -> int:
    """Clear a recoverable outcome with written evidence; return the new revision."""
    require_state_actor(actor)  # models and webhooks never write state (first, before any write)
    _aware(now, "now")
    if not isinstance(evidence, str) or not evidence.strip():
        raise SchemaInvalid("clearing an outcome requires non-empty evidence")
    if len(evidence) > _DETAIL_MAX:
        raise SchemaInvalid("evidence must be at most 2000 characters")
    row = _lock(tx, "episodes", episode_id, expected_revision)
    if row["outcome"] is None:
        raise InvalidTransition("episode has no outcome to clear")
    cleared = EpisodeOutcome(row["outcome"])
    if cleared in TERMINAL_OUTCOMES:
        raise InvalidTransition(
            f"terminal outcome {cleared.value} can never be cleared", outcome=cleared.value
        )
    if cleared not in RECOVERABLE_OUTCOMES:  # pragma: no cover - the tables partition outcomes
        raise InvalidTransition(f"outcome {cleared.value} is not recoverable")

    updated = update_with_revision(
        tx,
        "episodes",
        episode_id,
        expected_revision,
        {"outcome": None, "outcome_detail": None},
        now=now,
    )
    append_event(
        tx,
        aggregate_type="episode",
        aggregate_id=episode_id,
        event_type="episode.outcome_cleared",
        payload={
            "outcome": cleared.value,
            "state": row["state"],
            "actor_kind": actor.kind.value,
            "approval_event_id": None,
            "reason": evidence,
        },
        correlation_id=correlation_id,
        occurred_at=now,
    )
    return int(updated["revision"])


__all__ = [
    "clear_episode_outcome",
    "set_episode_outcome",
    "transition_episode",
    "transition_season",
]

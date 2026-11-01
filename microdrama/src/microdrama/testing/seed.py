"""Test-only seed helpers that insert minimal valid rows (integrator-owned).

They bypass services on purpose (to set up preconditions quickly) and must never
be used by runtime code. Human sessions created here are test owner sessions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from microdrama.contracts.examples import season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence.db import Tx, insert_row, jsonb


def now_utc() -> datetime:
    return datetime.now(UTC)


def seed_owner(tx: Tx, *, username: str | None = None, active: bool = True) -> UUID:
    owner_id = uuid.uuid4()
    insert_row(
        tx,
        "owners",
        {
            "id": owner_id,
            "username": username or f"owner-{owner_id.hex[:8]}",
            "password_hash": "test-only-not-a-real-hash",
            "active": active,
        },
        returning="id",
    )
    return owner_id


def seed_human_session(
    tx: Tx,
    owner_id: UUID,
    *,
    expires_in: timedelta = timedelta(hours=1),
    revoked: bool = False,
    created_at: datetime | None = None,
) -> UUID:
    session_id = uuid.uuid4()
    created = created_at or now_utc()
    insert_row(
        tx,
        "human_sessions",
        {
            "id": session_id,
            "owner_id": owner_id,
            "token_hash": hashlib.sha256(secrets.token_bytes(16)).hexdigest(),
            "csrf_token_hash": hashlib.sha256(secrets.token_bytes(16)).hexdigest(),
            "created_at": created,
            "expires_at": created + expires_in,
            "revoked_at": created if revoked else None,
        },
        returning="id",
    )
    return session_id


def seed_gate1_approval(
    tx: Tx, season_id: UUID, scope_hash: str, *, owner_id: UUID | None = None
) -> UUID:
    """A real Gate 1 APPROVE recorded by a live test owner session (no fabricated ids).

    With ``owner_id`` the approval's actor is exactly that owner (a session is
    seeded for it), so a season-owner link can cite this event.
    """
    owner = owner_id or seed_owner(tx)
    session_id = seed_human_session(tx, owner)
    approval_id = uuid.uuid4()
    payload = {"season_id": str(season_id), "scope_hash": scope_hash}
    insert_row(
        tx,
        "approval_events",
        {
            "id": approval_id,
            "gate_type": "SEASON_CONCEPT",
            "action": "APPROVE",
            "entity_type": "season",
            "entity_id": season_id,
            "expected_revision": 0,
            "package_hash": scope_hash,
            "actor_owner_id": owner,
            "actor_session_id": session_id,
            "idempotency_key": f"seed-gate1-{approval_id.hex}",
            "command_hash": canonical_hash(payload),
        },
        returning="id",
    )
    return approval_id


def link_season_owner(
    tx: Tx,
    season_id: UUID,
    owner_id: UUID,
    *,
    source: str = "CREATOR_AT_CREATION",
    approval_event_id: UUID | None = None,
) -> None:
    """Insert a ``season_owners`` row with real provenance (T044a).

    A ``GATE1_APPROVAL_BACKFILL`` link must cite the season's own human Gate 1
    approval whose actor is this owner — the database trigger enforces it.
    """
    insert_row(
        tx,
        "season_owners",
        {
            "season_id": season_id,
            "owner_id": owner_id,
            "source": source,
            "approval_event_id": approval_event_id,
        },
    )


def seed_season(
    tx: Tx,
    *,
    state: str = "PROPOSED",
    approved_scope_hash: str | None = None,
    owner_id: UUID | None = None,
) -> UUID:
    """A season row; with ``owner_id`` the season is linked to that owner at creation.

    Without ``owner_id`` the season stays UNASSIGNED — the legacy shape the
    review reads must hide until an audited assignment links it.
    """
    season_id = uuid.uuid4()
    approved = state in ("SEASON_APPROVED", "ACTIVE", "COMPLETE")
    scope_hash = approved_scope_hash or canonical_hash(season_scope())
    if approved:
        approval_id = seed_gate1_approval(tx, season_id, scope_hash, owner_id=owner_id)
    else:
        approval_id = None
    insert_row(
        tx,
        "seasons",
        {
            "id": season_id,
            "state": state,
            "title_th": "ฤดูกาลทดสอบ",
            "title_en": "Test season",
            "approved_scope_version": 1 if approved else None,
            "approved_scope_hash": scope_hash if approved else None,
            "approval_event_id": approval_id,
            "approved_at": now_utc() if approved else None,
        },
        returning="id",
    )
    if owner_id is not None:
        link_season_owner(
            tx,
            season_id,
            owner_id,
            source="GATE1_APPROVAL_BACKFILL" if approved else "CREATOR_AT_CREATION",
            approval_event_id=approval_id,
        )
    return season_id


def seed_episode(tx: Tx, season_id: UUID, *, number: int = 1, state: str = "PLANNED") -> UUID:
    episode_id = uuid.uuid4()
    insert_row(
        tx,
        "episodes",
        {
            "id": episode_id,
            "season_id": season_id,
            "episode_number": number,
            "state": state,
            "approved_scope_hash": canonical_hash(season_scope()),
        },
        returning="id",
    )
    return episode_id


def seed_job(
    tx: Tx, *, semantic_key: str, queue: str = "production", job_type: str = "qa.technical"
) -> UUID:
    job_id = uuid.uuid4()
    payload = {"semantic_key": semantic_key}
    insert_row(
        tx,
        "jobs",
        {
            "id": job_id,
            "job_type": job_type,
            "queue": queue,
            "semantic_key": semantic_key,
            "input_hash": canonical_hash(payload),
            "input": jsonb(payload),
            "status": "QUEUED",
        },
        returning="id",
    )
    return job_id

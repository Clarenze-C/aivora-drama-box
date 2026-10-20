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


def seed_season(tx: Tx, *, state: str = "PROPOSED", approved_scope_hash: str | None = None) -> UUID:
    season_id = uuid.uuid4()
    approved = state in ("SEASON_APPROVED", "ACTIVE", "COMPLETE")
    scope_hash = approved_scope_hash or canonical_hash(season_scope())
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
            "approval_event_id": uuid.uuid4() if approved else None,
            "approved_at": now_utc() if approved else None,
        },
        returning="id",
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

"""Shared builders for the core tests (T004). Plain helpers; fixtures live in conftest.py.

All rows are created through real SQL against the migrated test database. Principals for workers,
models, webhooks and schedulers are plain objects; human principals are backed by a seeded owner
and a live review session so the database approval triggers see the real thing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from microdrama.contracts.enums import (
    ApprovalAction,
    FeedbackCategory,
    FeedbackScope,
    GateType,
    PrincipalKind,
    RuntimeRole,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.persistence.db import Database, Tx, insert_row, jsonb
from microdrama.testing.seed import seed_episode, seed_human_session, seed_owner, seed_season

H = canonical_hash({"fixture": "core"})
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def new_key(prefix: str = "key") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# --- principals ------------------------------------------------------------------------------


def make_human(tx: Tx, *, expires_in=None, revoked: bool = False, created_at=None) -> Principal:
    """A live human owner with a review session (or a revoked/expired one for negative tests)."""
    owner = seed_owner(tx)
    kwargs = {"revoked": revoked, "created_at": created_at}
    if expires_in is not None:
        kwargs["expires_in"] = expires_in
    session = seed_human_session(tx, owner, **kwargs)
    return Principal(
        principal_id=f"owner:{owner}",
        kind=PrincipalKind.HUMAN_OWNER,
        session_id=session,
    )


WORKER = Principal(principal_id="worker:ingest-01", kind=PrincipalKind.SERVICE_WORKER)
SCHEDULER = Principal(principal_id="scheduler:cron-01", kind=PrincipalKind.SCHEDULER)
WEBHOOK = Principal(principal_id="webhook:provider-a", kind=PrincipalKind.PROVIDER_WEBHOOK)
CRITIC = Principal(
    principal_id="model:critic-01",
    kind=PrincipalKind.RUNTIME_MODEL,
    runtime_role=RuntimeRole.CRITIC,
)
NON_HUMAN = (WORKER, SCHEDULER, WEBHOOK, CRITIC)


# --- Gate commands ---------------------------------------------------------------------------


def gate1(season_id, scope_hash: str, *, revision: int, action=ApprovalAction.APPROVE):
    return ApprovalCommand(
        gate=GateType.SEASON_CONCEPT,
        action=action,
        entity_id=season_id,
        expected_revision=revision,
        package_hash=scope_hash,
        idempotency_key=new_key("gate1"),
        reason=None if action is ApprovalAction.APPROVE else "not this season",
    )


def gate2(episode_id, package_hash: str, *, revision: int, action=ApprovalAction.APPROVE):
    if action is ApprovalAction.REVISE:
        return ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=action,
            entity_id=episode_id,
            expected_revision=revision,
            package_hash=package_hash,
            idempotency_key=new_key("gate2-revise"),
            feedback=[
                TimecodedFeedback(
                    category=FeedbackCategory.PACING,
                    start_ms=1_000,
                    end_ms=4_000,
                    comment="the reveal lands late",
                    scope=FeedbackScope.EPISODE,
                )
            ],
        )
    if action is ApprovalAction.REJECT:
        return ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=action,
            entity_id=episode_id,
            expected_revision=revision,
            package_hash=package_hash,
            idempotency_key=new_key("gate2-reject"),
            reason="unfixable continuity break",
        )
    return ApprovalCommand(
        gate=GateType.EPISODE_FINAL,
        action=ApprovalAction.APPROVE,
        entity_id=episode_id,
        expected_revision=revision,
        package_hash=package_hash,
        media_hashes=[H],
        management_policy_hash=H,
        release_scope_hash=H,
        idempotency_key=new_key("gate2-approve"),
    )


# --- release packages (Gate 2 prerequisites) -------------------------------------------------


def current_caption(tx: Tx, episode) -> uuid.UUID:
    """The episode's CURRENT actual-audio-aligned Thai caption track (created on first use)."""
    track = tx.fetchval(
        "SELECT id FROM caption_tracks WHERE episode_id = %s AND locale = 'th-TH' AND state = 'CURRENT'",
        (episode,),
    )
    if track is None:
        track = uuid.uuid4()
        insert_row(
            tx,
            "caption_tracks",
            {
                "id": track,
                "episode_id": episode,
                "locale": "th-TH",
                "version": 1,
                "timing_source": "ACTUAL_AUDIO_ALIGNMENT",
                "body": jsonb({}),
                "body_hash": canonical_hash({"track": str(track)}),
                "state": "CURRENT",
            },
        )
    return track


def ready_package(
    tx: Tx, episode, *, version: int = 1, status: str = "READY", tag: str = ""
) -> tuple[uuid.UUID, str]:
    """A release package in ``status`` that lists the episode's CURRENT aligned caption track."""
    package_id = uuid.uuid4()
    package_hash = canonical_hash({"package": str(episode), "version": version, "tag": tag})
    track = current_caption(tx, episode)
    insert_row(
        tx,
        "release_packages",
        {
            "id": package_id,
            "episode_id": episode,
            "version": version,
            "package_hash": package_hash,
            "body": jsonb({"caption_track_ids": [str(track)]}),
            "media_hashes": jsonb([H]),
            "management_policy_hash": H,
            "release_scope_hash": H,
            "status": status,
            "gate_blockers": jsonb(["blocked for test"] if status == "BLOCKED" else []),
        },
    )
    return package_id, package_hash


def approve_package(tx: Tx, package_id: uuid.UUID, approval_id: uuid.UUID) -> None:
    tx.execute(
        "UPDATE release_packages SET status = 'APPROVED', approval_event_id = %s WHERE id = %s",
        (approval_id, package_id),
    )


def fresh_season(tx: Tx, state: str = "PROPOSED") -> uuid.UUID:
    return seed_season(tx, state=state)


def fresh_episode(tx: Tx, state: str = "AWAITING_FINAL_REVIEW", season=None) -> uuid.UUID:
    season_id = season or seed_season(tx)
    return seed_episode(tx, season_id, state=state)


def count(tx: Tx, sql: str, params=()) -> int:
    value = tx.fetchval(sql, params)
    return int(value or 0)


def episode_state(db: Database, episode_id) -> tuple[str, str | None, int]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state, outcome, revision FROM episodes WHERE id = %s", (episode_id,)
        )
    return row["state"], row["outcome"], row["revision"]


def season_row(db: Database, season_id) -> dict:
    with db.transaction(readonly=True) as tx:
        return tx.fetchone("SELECT * FROM seasons WHERE id = %s", (season_id,))


# --- budget reservations (every provider operation needs one: contract 1.4.0, V-24) -------------


def make_reservation(db: Database, state: str = "ACTIVE", *, expires_hours: int = 1) -> uuid.UUID:
    """A reservation row in ``state`` on a fresh episode budget account.

    Raw rows: the budget lane owns the real lifecycle. ``closed_reason`` is set for every closed state,
    as migration 0012 requires.
    """
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        reservation = uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, category, "
            "queue, provider, operation_kind, price, ceilings, reserved_micro_usd, state, expires_at, "
            "closed_at, closed_reason) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
            "'fake-runpod', 'pod', %s, %s, 100, %s, %s, %s, %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"res:{reservation}",
                canonical_hash({"reservation": str(reservation)}),
                jsonb({}),
                jsonb({}),
                state,
                T0 + timedelta(hours=expires_hours),
                None if state == "ACTIVE" else T0,
                None if state == "ACTIVE" else f"test fixture: {state.lower()}",
            ),
        )
    return reservation


def linked_job(db: Database) -> uuid.UUID:
    """A real queued job for provider operations to belong to (``job_id`` is required)."""
    from microdrama.contracts.jobs import EpisodeStepInput
    from microdrama.core.jobs import JobService
    from microdrama.testing.fakes import FakeClock, SequentialIds

    jobs = JobService(db, FakeClock(T0), SequentialIds(f"linked-{uuid.uuid4().hex}"))
    with db.transaction() as tx:
        return jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"linked:{uuid.uuid4().hex}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        ).job_id

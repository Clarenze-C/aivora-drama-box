"""Shared builders for the T045 billing tests (R1-R8).

Real PostgreSQL, real budget service, lease/bucket fixtures seeded directly through
SQL and the canonical contract models so allocation, evidence and finality behaviour
is tested against durable state exactly as the services write it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from microdrama.contracts.cost import (
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    runpod_bucket_identity_sha256,
)
from microdrama.persistence.db import Tx
from microdrama.testing.seed import seed_episode, seed_season

T0 = datetime(2026, 11, 2, tzinfo=UTC)
ACCOUNT_REF = "acct:runpod-t045"
SETTLE_LAG = timedelta(minutes=15)


def open_episode_account(tx: Tx, *, number: int = 1) -> tuple[UUID, UUID, UUID]:
    """(season_id, episode_id, account_id) with a fully allocated GPU category."""
    season = seed_season(tx)
    episode = seed_episode(tx, season, number=number)
    account = uuid.uuid4()
    tx.execute(
        "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
        "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
        (account, season, episode),
    )
    for category in (
        "RESEARCH_SCRIPT_PROMPTS_METADATA",
        "REFERENCES_DIALOGUE",
        "QA_CAPTIONS",
        "CPU_STORAGE_TRANSFER",
        "RECOVERY_HEADROOM",
    ):
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
            "protected) VALUES (%s, %s, 0, true)",
            (account, category),
        )
    tx.execute(
        "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
        "protected) VALUES (%s, 'GPU_GENERATION', 9000000, true)",
        (account,),
    )
    tx.execute(
        "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
        "protected) VALUES (%s, 'METERED_MANAGEMENT', 0, false)",
        (account,),
    )
    return season, episode, account


def insert_runpod_lease(
    tx: Tx,
    episode: UUID,
    *,
    pod_id: str | None,
    client_token: str | None = None,
    lease_state: str = "ACTIVE",
    pod_state: str = "RUNNING",
    create_requested_at: datetime | None = None,
    compute_window_start_at: datetime | None = None,
    compute_window_end_at: datetime | None = None,
    stop_verified_at: datetime | None = None,
    terminate_verified_at: datetime | None = None,
    transferred_from: UUID | None = None,
    reservation_micro_usd: int = 900_000,
    provider_account_ref: str | None = None,
) -> tuple[UUID, UUID]:
    """A runpod pod_leases row (plus its reservation) with explicit timing columns."""
    account = tx.fetchval(
        "SELECT id FROM budget_accounts WHERE episode_id=%s AND scope_kind='EPISODE'",
        (episode,),
    )
    assert account is not None, "call open_episode_account first"
    reservation = uuid.uuid4()
    tx.execute(
        "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, "
        "category, queue, provider, operation_kind, price, ceilings, reserved_micro_usd, "
        "state, expires_at) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
        "'runpod', 'pod.lease', '{}', '{}', %s, 'ACTIVE', %s)",
        (
            reservation,
            account,
            uuid.uuid4(),
            f"t045:{reservation}",
            "0" * 64,
            reservation_micro_usd,
            T0 + timedelta(hours=6),
        ),
    )
    tx.execute(
        "UPDATE budget_accounts SET reserved_outstanding_micro_usd = "
        "reserved_outstanding_micro_usd + %s WHERE id = %s",
        (reservation_micro_usd, account),
    )
    tx.execute(
        "UPDATE budget_category_allocations SET reserved_outstanding_micro_usd = "
        "reserved_outstanding_micro_usd + %s WHERE account_id = %s AND category = 'GPU_GENERATION'",
        (reservation_micro_usd, account),
    )
    lease = uuid.uuid4()
    token = client_token or f"tok-{lease}"
    tx.execute(
        "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
        "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
        "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
        "compute_window_start_at, compute_window_end_at, stop_verified_at, "
        "terminate_verified_at, transferred_from, provider_account_ref) "
        "VALUES (%s, 'runpod', %s, 'microdrama-owned:t045', %s, %s, %s, %s, %s, "
        "'NVIDIA RTX A40', 263000, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            lease,
            pod_id,
            token,
            episode,
            reservation,
            lease_state,
            pod_state,
            T0 + timedelta(hours=6),
            create_requested_at,
            compute_window_start_at,
            compute_window_end_at,
            stop_verified_at,
            terminate_verified_at,
            transferred_from,
            provider_account_ref,
        ),
    )
    return lease, reservation


def closed_bucket(
    *,
    pod_id: str,
    start: datetime,
    end: datetime,
    gpu: int,
    cpu: int,
    disk: int,
    observed_at: datetime | None = None,
    revision: int = 1,
    prior_observation_id: UUID | None = None,
    prior_raw: str | None = None,
    raw: str | None = None,
    finality: str = "ALLOCATED_PROVIDER_REPORTED",
    account_ref: str = ACCOUNT_REF,
    query_window: tuple[datetime, datetime] | None = None,
) -> tuple[RunpodBillingQueryObservation, RunpodBillingBucketObservation]:
    """A settled (closed) bucket observation plus its query, at least one settle-lag old."""
    size = int((end - start).total_seconds())
    identity = runpod_bucket_identity_sha256(account_ref, pod_id, start, end, size)
    raw_hash = raw or sha256(f"t045:{identity}:{revision}".encode()).hexdigest()
    window = query_window or (start, end)
    query = RunpodBillingQueryObservation(
        query_id=uuid.uuid4(),
        provider_account_ref=account_ref,
        requested_window_start=window[0],
        requested_window_end=window[1],
        provider_resolved_window_start=window[0],
        provider_resolved_window_end=window[1],
        bucket_size_seconds=size,
        raw_response_sha256=raw_hash,
        observed_at=observed_at or (end + SETTLE_LAG + timedelta(minutes=5)),
        result_state="BUCKETS",
        bucket_observation_ids=[uuid.uuid4()],
    )
    bucket = RunpodBillingBucketObservation(
        observation_id=query.bucket_observation_ids[0],
        query_id=query.query_id,
        provider_account_ref=account_ref,
        pod_id=pod_id,
        bucket_start=start,
        bucket_end=end,
        bucket_size_seconds=size,
        bucket_identity_sha256=identity,
        revision=revision,
        prior_observation_id=prior_observation_id,
        prior_raw_response_sha256=prior_raw,
        provider_resolved_window_start=window[0],
        provider_resolved_window_end=window[1],
        raw_response_sha256=raw_hash,
        observed_at=query.observed_at,
        currency="USD",
        total_amount_micro_usd=gpu + cpu + disk,
        gpu_amount_micro_usd=gpu,
        cpu_amount_micro_usd=cpu,
        disk_amount_micro_usd=disk,
        finality_state=finality,
    )
    return query, bucket


def insert_storage_ownership(
    tx: Tx,
    episode: UUID,
    *,
    pod_id: str,
    valid_from: datetime,
    valid_until: datetime | None = None,
    creating_lease: UUID | None = None,
) -> UUID:
    ownership = uuid.uuid4()
    tx.execute(
        "INSERT INTO pod_storage_ownership (id, provider, pod_id, owner_episode_id, valid_from, "
        "valid_until, creating_lease_id) VALUES (%s, 'runpod', %s, %s, %s, %s, %s)",
        (ownership, pod_id, episode, valid_from, valid_until, creating_lease),
    )
    return ownership

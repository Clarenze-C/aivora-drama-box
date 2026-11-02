"""Tiny probe helper for the persistence billing tests: a runpod lease row whose
readiness is evaluated against the ingested fixture bucket (T045 R7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from microdrama.budget.billing import lease_billing_readiness
from microdrama.testing.seed import seed_episode, seed_season


def probe_lease_readiness(db, bucket) -> object:
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
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, "
            "category, queue, provider, operation_kind, price, ceilings, reserved_micro_usd, "
            "state, expires_at) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
            "'runpod', 'pod.lease', '{}', '{}', 100, 'ACTIVE', %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"probe:{reservation}",
                "0" * 64,
                datetime.now(UTC),
            ),
        )
        lease = uuid.uuid4()
        start = bucket.bucket_start
        end = bucket.bucket_end
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "compute_window_start_at, compute_window_end_at) VALUES (%s, 'runpod', %s, "
            "'microdrama-owned:t045', %s, %s, %s, 'RELEASED', 'TERMINATED', 'NVIDIA RTX A40', "
            "263000, %s, %s, %s, %s)",
            (
                lease,
                bucket.pod_id,
                f"tok-{lease}",
                episode,
                reservation,
                datetime.now(UTC) + timedelta(hours=1),
                start,
                start,
                end,
            ),
        )
    return lease_billing_readiness(db, lease)

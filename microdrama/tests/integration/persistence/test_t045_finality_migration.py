"""T045 R0: migration 0025 — lease timing columns, close-once ownership, replay keys.

Isolated-PG upgrade and readback, plus the set-once and close-once triggers rejecting a
second write and the widened bucket replay key allowing the internal INVOICE_VERIFIED
revision that repeats the provider's raw hash.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from microdrama.contracts.errors import Conflict, DuplicateSemanticKey
from microdrama.persistence import Database, migrate
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 2, tzinfo=UTC)


def _insert_lease(tx, *, provider: str = "runpod", pod_id: str | None = None) -> uuid.UUID:
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
        "state, expires_at) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', %s, "
        "'pod.lease', '{}', '{}', 100, 'ACTIVE', %s)",
        (reservation, account, uuid.uuid4(), f"gpu:{reservation}", "0" * 64, provider, T0),
    )
    lease = uuid.uuid4()
    tx.execute(
        "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
        "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
        "hourly_price_micro_usd, lease_expires_at) VALUES (%s, %s, %s, 'md-owned', %s, %s, "
        "%s, 'ACTIVE', 'RUNNING', 'FAKE', 900000, %s)",
        (lease, provider, pod_id, f"tok-{lease}", episode, reservation, T0 + timedelta(hours=1)),
    )
    return lease


def test_migration_0025_upgrades_and_reads_back(pg_server_dsn: str) -> None:
    name = f"md_t045_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(pg_server_dsn, dbname=name)
    try:
        assert migrate(dsn, target="0024") == [f"{n:04d}" for n in range(1, 25)]
        with psycopg.connect(dsn) as conn:
            lease_columns = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'pod_leases'"
                )
            }
            assert (
                not {
                    "create_requested_at",
                    "compute_window_start_at",
                    "compute_window_end_at",
                    "terminate_verified_at",
                    "provider_account_ref",
                    "next_finality_check_at",
                }
                & lease_columns
            )
        assert migrate(dsn) == ["0025"]
        with psycopg.connect(dsn) as conn:
            assert {
                "create_requested_at",
                "compute_window_start_at",
                "compute_window_end_at",
                "terminate_verified_at",
                "provider_account_ref",
                "next_finality_check_at",
            } <= {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'pod_leases'"
                )
            }
            assert "creating_lease_id" in {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'pod_storage_ownership'"
                )
            }
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                )
            }
            assert {
                "runpod_billing_period_evidence",
                "runpod_billing_query_skipped_buckets",
            } <= tables
    finally:
        with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_pod_lease_timestamps_are_set_once(db: Database) -> None:
    with db.transaction() as tx:
        lease = _insert_lease(tx, pod_id="pod-once")
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET create_requested_at=%s, compute_window_start_at=%s, "
            "compute_window_end_at=%s, terminate_verified_at=%s WHERE id=%s",
            (T0, T0, T0 + timedelta(hours=1), T0 + timedelta(hours=1), lease),
        )
        tx.execute(
            "UPDATE pod_leases SET next_finality_check_at=%s WHERE id=%s",
            (T0 + timedelta(minutes=5), lease),
        )
    # The backoff column is freely rewritable; the four timestamps are not.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET next_finality_check_at=%s WHERE id=%s",
            (T0 + timedelta(minutes=10), lease),
        )
    for column, value in (
        ("create_requested_at", T0 + timedelta(seconds=1)),
        ("compute_window_start_at", T0 + timedelta(seconds=1)),
        ("compute_window_end_at", T0 + timedelta(seconds=1)),
        ("terminate_verified_at", T0 + timedelta(seconds=1)),
    ):
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(
                f"UPDATE pod_leases SET {column}=%s WHERE id=%s",
                (value, lease),  # noqa: B608
            )
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(f"UPDATE pod_leases SET {column}=NULL WHERE id=%s", (lease,))  # noqa: B608
    # Rewriting the identical value is not a second write.
    with db.transaction() as tx:
        tx.execute("UPDATE pod_leases SET create_requested_at=%s WHERE id=%s", (T0, lease))


def test_storage_ownership_closes_once_and_records_creating_lease(db: Database) -> None:
    with db.transaction() as tx:
        lease = _insert_lease(tx, pod_id="pod-storage")
        episode = tx.fetchval("SELECT owner_episode_id FROM pod_leases WHERE id=%s", (lease,))
        ownership = uuid.uuid4()
        tx.execute(
            "INSERT INTO pod_storage_ownership (id, provider, pod_id, owner_episode_id, "
            "valid_from, creating_lease_id) VALUES (%s, 'runpod', 'pod-storage', %s, %s, %s)",
            (ownership, episode, T0, lease),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE pod_storage_ownership SET creating_lease_id=%s WHERE id=%s",
            (uuid.uuid4(), ownership),
        )
    closed = T0 + timedelta(hours=2)
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_storage_ownership SET valid_until=%s WHERE id=%s", (closed, ownership)
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE pod_storage_ownership SET valid_until=%s WHERE id=%s",
            (closed + timedelta(seconds=1), ownership),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute("UPDATE pod_storage_ownership SET valid_until=NULL WHERE id=%s", (ownership,))


def _bucket_row(
    tx,
    observation_id: uuid.UUID,
    identity: str,
    raw: str,
    finality: str,
    *,
    revision: int = 1,
    prior: uuid.UUID | None = None,
) -> None:
    query_id = tx.fetchval(
        "INSERT INTO runpod_billing_queries (query_id, provider_account_ref, observed_at, "
        "result_state, payload) VALUES (%s, 'acct:t045', %s, 'BUCKETS', '{}') RETURNING query_id",
        (uuid.uuid4(), T0),
    )
    tx.execute(
        "INSERT INTO runpod_billing_buckets (observation_id, bucket_identity_sha256, revision, "
        "prior_observation_id, query_id, provider_account_ref, pod_id, bucket_start, bucket_end, "
        "bucket_size_seconds, raw_response_sha256, observed_at, currency, "
        "total_amount_micro_usd, gpu_amount_micro_usd, cpu_amount_micro_usd, "
        "disk_amount_micro_usd, finality_state, payload) VALUES (%s, %s, %s, %s, %s, "
        "'acct:t045', 'pod-bucket', %s, %s, 3600, %s, %s, 'USD', 0, 0, 0, 0, %s, '{}')",
        (
            observation_id,
            identity,
            revision,
            prior,
            query_id,
            T0,
            T0 + timedelta(hours=1),
            raw,
            T0,
            finality,
        ),
    )


def test_bucket_replay_key_widens_to_finality_and_verifications_are_unique(
    db: Database,
) -> None:
    identity = "i" * 64
    first = uuid.uuid4()
    second = uuid.uuid4()
    with db.transaction() as tx:
        _bucket_row(tx, first, identity, "r" * 64, "ALLOCATED_PROVIDER_REPORTED")
        # The internal INVOICE_VERIFIED revision (R5) repeats the provider's raw hash on a
        # new revision: rejected by 0022's key, storable under the widened 0025 key.
        _bucket_row(tx, second, identity, "r" * 64, "INVOICE_VERIFIED", revision=2, prior=first)
        verification = uuid.uuid4()
        tx.execute(
            "INSERT INTO runpod_billing_invoice_verifications (verification_id, "
            "bucket_observation_id, bucket_identity_sha256, evidence_sha256, verified_at, "
            "result, payload) VALUES (%s, %s, %s, %s, %s, 'MATCHED', '{}')",
            (verification, second, identity, "e" * 64, T0),
        )
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        _bucket_row(tx, uuid.uuid4(), identity, "r" * 64, "ALLOCATED_PROVIDER_REPORTED")
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        # The same raw hash under the same finality is still a duplicate, on any revision.
        _bucket_row(
            tx, uuid.uuid4(), identity, "r" * 64, "INVOICE_VERIFIED", revision=3, prior=second
        )
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        tx.execute(
            "INSERT INTO runpod_billing_invoice_verifications (verification_id, "
            "bucket_observation_id, bucket_identity_sha256, evidence_sha256, verified_at, "
            "result, payload) VALUES (%s, %s, %s, %s, %s, 'MATCHED', '{}')",
            (uuid.uuid4(), first, identity, "f" * 64, T0),
        )
        tx.execute(
            "INSERT INTO runpod_billing_invoice_verifications (verification_id, "
            "bucket_observation_id, bucket_identity_sha256, evidence_sha256, verified_at, "
            "result, payload) VALUES (%s, %s, %s, %s, %s, 'MATCHED', '{}')",
            (uuid.uuid4(), first, identity, "f" * 64, T0),
        )


def test_migration_0025_backfills_verification_identity_and_drops_the_default(
    pg_server_dsn: str,
) -> None:
    """T045-FIX A-N6: the identity column is backfilled from the bucket row, and no
    blanket ``''`` default remains for future inserts to fall back on."""
    name = f"md_t045n6_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(pg_server_dsn, dbname=name)
    try:
        assert migrate(dsn, target="0024") == [f"{n:04d}" for n in range(1, 25)]
        identity = "b" * 64
        with psycopg.connect(dsn) as conn:
            query_id = uuid.uuid4()
            observation_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO runpod_billing_queries (query_id, provider_account_ref, "
                "observed_at, result_state, payload) VALUES (%s, 'acct:t045', %s, "
                "'BUCKETS', '{}')",
                (query_id, T0),
            )
            conn.execute(
                "INSERT INTO runpod_billing_buckets (observation_id, "
                "bucket_identity_sha256, revision, query_id, provider_account_ref, "
                "pod_id, bucket_start, bucket_end, bucket_size_seconds, "
                "raw_response_sha256, observed_at, currency, total_amount_micro_usd, "
                "gpu_amount_micro_usd, cpu_amount_micro_usd, disk_amount_micro_usd, "
                "finality_state, payload) VALUES (%s, %s, 1, %s, 'acct:t045', "
                "'pod-n6', %s, %s, 3600, %s, %s, 'USD', 0, 0, 0, 0, "
                "'ALLOCATED_PROVIDER_REPORTED', '{}')",
                (
                    observation_id,
                    identity,
                    query_id,
                    T0,
                    T0 + timedelta(hours=1),
                    "r" * 64,
                    T0,
                ),
            )
            conn.execute(
                "INSERT INTO runpod_billing_invoice_verifications (verification_id, "
                "bucket_observation_id, evidence_sha256, verified_at, result, payload) "
                "VALUES (%s, %s, %s, %s, 'MATCHED', '{}')",
                (uuid.uuid4(), observation_id, "e" * 64, T0),
            )
        assert migrate(dsn) == ["0025"]
        with psycopg.connect(dsn) as conn:
            stored = conn.execute(
                "SELECT bucket_identity_sha256 FROM runpod_billing_invoice_verifications"
            ).fetchone()
            assert stored is not None and stored[0] == identity
            default = conn.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'runpod_billing_invoice_verifications' "
                "AND column_name = 'bucket_identity_sha256'"
            ).fetchone()
            assert default is not None and default[0] is None
    finally:
        with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_matched_zero_period_evidence_must_carry_a_zero_amount(db: Database) -> None:
    """T045-FIX A-N6: MATCHED_ZERO is a zero-amount outcome by definition."""
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "INSERT INTO runpod_billing_period_evidence (period_evidence_id, "
            "provider_account_ref, pod_id, period_start, period_end, amount_micro_usd, "
            "currency, evidence_sha256, evidence_source, observed_at, outcome, "
            "bucket_sum_micro_usd) VALUES (%s, 'acct:t045', 'pod-mz', %s, %s, 1, 'USD', "
            "%s, 'INVOICE', %s, 'MATCHED_ZERO', 0)",
            (uuid.uuid4(), T0, T0 + timedelta(hours=1), "a" * 64, T0),
        )
    with db.transaction() as tx:  # a zero amount is exactly what MATCHED_ZERO means
        tx.execute(
            "INSERT INTO runpod_billing_period_evidence (period_evidence_id, "
            "provider_account_ref, pod_id, period_start, period_end, amount_micro_usd, "
            "currency, evidence_sha256, evidence_source, observed_at, outcome, "
            "bucket_sum_micro_usd) VALUES (%s, 'acct:t045', 'pod-mz', %s, %s, 0, 'USD', "
            "%s, 'INVOICE', %s, 'MATCHED_ZERO', 0)",
            (uuid.uuid4(), T0, T0 + timedelta(hours=1), "b" * 64, T0),
        )


def test_migration_0025_adds_fix_round_columns_and_tables(db: Database) -> None:
    """T045-FIX schema: the podless-create resolution (A-S1), the finality attempt
    count (A-S2) and the per-Pod ingest backoff (B-S4)."""
    with db.transaction(readonly=True) as tx:
        assert "finality_attempts" in {
            row["column_name"]
            for row in tx.fetchall(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'pod_leases'"
            )
        }
        tables = {
            row["table_name"]
            for row in tx.fetchall(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert "runpod_podless_create_resolutions" in tables
        assert "runpod_billing_ingest_backoff" in tables
        backoff_columns = {
            row["column_name"]
            for row in tx.fetchall(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'runpod_billing_ingest_backoff'"
            )
        }
        assert {
            "pod_id",
            "provider_account_ref",
            "next_ingest_at",
            "attempts",
            "post_terminate_ingest_done",
            "last_outcome",
            "last_detail",
        } <= backoff_columns
    # The resolution is append-only and one per lease.
    with db.transaction() as tx:
        lease = _insert_lease(tx, pod_id=None)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO runpod_podless_create_resolutions (resolution_id, lease_id, "
            "actor_ref, reason, evidence_sha256, resolved_at) VALUES (%s, %s, "
            "'owner:test', 'console shows no pod', %s, %s)",
            (uuid.uuid4(), lease, "c" * 64, T0),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute("UPDATE runpod_podless_create_resolutions SET reason='rewritten'")
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute("DELETE FROM runpod_podless_create_resolutions")
    # T045-FIX RR-S4: the contradiction columns are set exactly once, never rewritten
    # or cleared, and a contradiction names its Pod.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE runpod_podless_create_resolutions SET contradicted_at=%s, "
            "contradicted_pod_id='pod-late' WHERE lease_id=%s",
            (T0 + timedelta(hours=1), lease),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE runpod_podless_create_resolutions SET contradicted_at=%s WHERE lease_id=%s",
            (T0 + timedelta(hours=2), lease),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE runpod_podless_create_resolutions SET contradicted_at=NULL, "
            "contradicted_pod_id=NULL WHERE lease_id=%s",
            (lease,),
        )
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT contradicted_at, contradicted_pod_id "
            "FROM runpod_podless_create_resolutions WHERE lease_id=%s",
            (lease,),
        )
    assert row is not None
    assert row["contradicted_at"] == T0 + timedelta(hours=1)
    assert row["contradicted_pod_id"] == "pod-late"
    with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
        tx.execute(
            "INSERT INTO runpod_podless_create_resolutions (resolution_id, lease_id, "
            "actor_ref, reason, evidence_sha256, resolved_at) VALUES (%s, %s, "
            "'owner:test', 'second resolution', %s, %s)",
            (uuid.uuid4(), lease, "d" * 64, T0),
        )


def test_period_evidence_supersede_audit_is_structural(db: Database) -> None:
    first = uuid.uuid4()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO runpod_billing_period_evidence (period_evidence_id, "
            "provider_account_ref, pod_id, period_start, period_end, amount_micro_usd, "
            "currency, evidence_sha256, evidence_source, observed_at, outcome, "
            "bucket_sum_micro_usd) VALUES (%s, 'acct:t045', 'pod-period', %s, %s, 0, 'USD', "
            "%s, 'INVOICE', %s, 'MISMATCHED', 0)",
            (first, T0, T0 + timedelta(hours=1), "a" * 64, T0),
        )
        # A supersede names the row it replaces and carries an actor and reason.
        tx.execute(
            "INSERT INTO runpod_billing_period_evidence (period_evidence_id, "
            "provider_account_ref, pod_id, period_start, period_end, amount_micro_usd, "
            "currency, evidence_sha256, evidence_source, observed_at, outcome, "
            "bucket_sum_micro_usd, supersedes_evidence_id, actor_ref, reason) VALUES (%s, "
            "'acct:t045', 'pod-period', %s, %s, 0, 'USD', %s, 'INVOICE', %s, 'MATCHED', 0, "
            "%s, 'owner:test', 'corrected invoice')",
            (uuid.uuid4(), T0, T0 + timedelta(hours=1), "b" * 64, T0, first),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        # Naming a prior row without an actor and reason is refused by the schema itself.
        tx.execute(
            "INSERT INTO runpod_billing_period_evidence (period_evidence_id, "
            "provider_account_ref, pod_id, period_start, period_end, amount_micro_usd, "
            "currency, evidence_sha256, evidence_source, observed_at, outcome, "
            "bucket_sum_micro_usd, supersedes_evidence_id) VALUES (%s, 'acct:t045', "
            "'pod-period', %s, %s, 0, 'USD', %s, 'INVOICE', %s, 'MATCHED', 0, %s)",
            (uuid.uuid4(), T0, T0 + timedelta(hours=1), "c" * 64, T0, first),
        )

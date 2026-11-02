"""T045 R4 (G4): the repository derives bucket state — only closed buckets are stored.

API ingest keeps buckets whose end is at least ``settle_lag`` old, refuses
INVOICE_VERIFIED, records open buckets in the skipped table, and records an
all-open query as UNKNOWN. EMPTY and UNKNOWN are never coverage and never zero.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from t045_support import T0, closed_bucket

from microdrama.budget.billing import BillingRepository
from microdrama.contracts.cost import BillingFinalityState
from microdrama.contracts.errors import SchemaInvalid
from microdrama.persistence import Database

pytestmark = pytest.mark.db

HOUR = timedelta(hours=1)


def _counts(db: Database) -> tuple[int, int, int, str | None]:
    with db.transaction(readonly=True) as tx:
        return (
            tx.fetchval("SELECT count(*) FROM runpod_billing_buckets"),
            tx.fetchval("SELECT count(*) FROM runpod_billing_query_skipped_buckets"),
            tx.fetchval("SELECT count(*) FROM runpod_billing_queries"),
            tx.fetchval("SELECT result_state FROM runpod_billing_queries ORDER BY created_at DESC"),
        )


def test_open_bucket_is_skipped_and_only_closed_buckets_are_stored(db: Database) -> None:
    import uuid

    closed = closed_bucket(pod_id="pod-mixed", start=T0, end=T0 + HOUR, gpu=10, cpu=0, disk=0)
    open_bucket = closed_bucket(
        pod_id="pod-mixed",
        start=T0 + HOUR,
        end=T0 + 2 * HOUR,
        gpu=10,
        cpu=0,
        disk=0,
        observed_at=T0 + HOUR + timedelta(minutes=5),  # younger than the settle lag
    )
    shared_query_id = uuid.uuid4()
    query = closed[0].model_copy(
        update={
            "query_id": shared_query_id,
            "bucket_observation_ids": [closed[1].observation_id, open_bucket[1].observation_id],
        }
    )
    closed_model = closed[1].model_copy(update={"query_id": shared_query_id})
    open_model = open_bucket[1].model_copy(update={"query_id": shared_query_id})
    BillingRepository(db).ingest(query, [closed_model, open_model])
    buckets, skipped, queries, state = _counts(db)
    assert buckets == 1
    assert skipped == 1
    assert queries == 1
    assert state == "BUCKETS"
    with db.transaction(readonly=True) as tx:
        stored_ids = tx.fetchval(
            "SELECT payload->'bucket_observation_ids' FROM runpod_billing_queries "
            "WHERE query_id=%s",
            (query.query_id,),
        )
        skip = tx.fetchone("SELECT * FROM runpod_billing_query_skipped_buckets")
    assert set(stored_ids) == {str(closed[1].observation_id)}
    assert skip["pod_id"] == "pod-mixed"
    assert skip["bucket_start"] == T0 + HOUR


def test_all_open_buckets_record_the_query_as_unknown(db: Database) -> None:
    fresh = closed_bucket(pod_id="pod-fresh", start=T0, end=T0 + HOUR, gpu=10, cpu=0, disk=0)
    query, bucket = fresh
    observed = T0 + timedelta(minutes=10)  # the whole hour is still open
    query = query.model_copy(update={"observed_at": observed})
    bucket = bucket.model_copy(update={"observed_at": observed})
    BillingRepository(db).ingest(query, [bucket])
    buckets, skipped, queries, state = _counts(db)
    assert buckets == 0
    assert skipped == 1
    assert queries == 1
    assert state == "UNKNOWN"
    with db.transaction(readonly=True) as tx:
        payload = tx.fetchval("SELECT payload FROM runpod_billing_queries")
    assert payload["bucket_observation_ids"] == []


def test_ingest_refuses_invoice_verified_buckets(db: Database) -> None:
    query, bucket = closed_bucket(
        pod_id="pod-verified", start=T0, end=T0 + HOUR, gpu=1, cpu=0, disk=0
    )
    pre_verified = bucket.model_copy(
        update={
            "finality_state": BillingFinalityState.INVOICE_VERIFIED,
            "invoice_verification_id": bucket.observation_id,
        }
    )
    with pytest.raises(SchemaInvalid, match="INVOICE_VERIFIED"):
        BillingRepository(db).ingest(query, [pre_verified])
    buckets, _skipped, queries, _state = _counts(db)
    assert (buckets, queries) == (0, 0)


def test_settle_lag_is_configurable(db: Database) -> None:
    from datetime import timedelta as td

    query, bucket = closed_bucket(pod_id="pod-lag", start=T0, end=T0 + HOUR, gpu=1, cpu=0, disk=0)
    observed = T0 + HOUR + td(minutes=1)
    query = query.model_copy(update={"observed_at": observed})
    bucket = bucket.model_copy(update={"observed_at": observed})
    BillingRepository(db, settle_lag=td(minutes=5)).ingest(query, [bucket])
    buckets, skipped, _queries, _state = _counts(db)
    assert (buckets, skipped) == (0, 1)
    # The same bucket is storable once a later observation ages past the lag.
    later = observed + td(minutes=10)
    aged_query, aged_bucket = closed_bucket(
        pod_id="pod-lag", start=T0, end=T0 + HOUR, gpu=1, cpu=0, disk=0, observed_at=later
    )
    BillingRepository(db, settle_lag=td(minutes=5)).ingest(aged_query, [aged_bucket])
    buckets, _skipped, _queries, _state = _counts(db)
    assert buckets == 1

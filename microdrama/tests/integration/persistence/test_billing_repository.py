from concurrent.futures import ThreadPoolExecutor

import pytest

from microdrama.budget.billing import BillingRepository
from microdrama.contracts.examples import (
    runpod_billing_bucket_observation,
    runpod_billing_query_observation,
)
from microdrama.persistence import Database

pytestmark = pytest.mark.db


def test_ingest_is_idempotent_concurrent_and_survives_pool_restart(db_dsn: str) -> None:
    query = runpod_billing_query_observation()
    bucket = runpod_billing_bucket_observation()

    def ingest_once() -> None:
        with Database(db_dsn) as db:
            BillingRepository(db).ingest(query, [bucket])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: ingest_once(), range(4)))

    with Database(db_dsn) as db, db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_queries") == 1
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_buckets") == 1
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_allocations") == 3
        amounts = tx.fetchall(
            "SELECT component, sum(delta_micro_usd) AS amount FROM runpod_billing_allocations GROUP BY component"
        )
        assert {row["component"]: row["amount"] for row in amounts} == {
            "GPU": bucket.gpu_amount_micro_usd,
            "CPU": bucket.cpu_amount_micro_usd,
            "DISK": bucket.disk_amount_micro_usd,
        }
        readiness = BillingRepository(db).accounting_readiness(
            "acct:runpod-fixture", bucket.pod_id, bucket.bucket_start, bucket.bucket_end
        )
        assert readiness.state == "RECOVERY_REQUIRED"
        assert readiness.covered is True
        assert readiness.provider_reported_micro_usd == bucket.total_amount_micro_usd
        assert readiness.invoice_verified_micro_usd == 0
        assert readiness.pending_exposure_held is True
        assert readiness.unresolved_recovery is True

    # A fresh pool represents process restart/readback; durable rows remain canonical JSON.
    with Database(db_dsn) as restarted, restarted.transaction(readonly=True) as tx:
        persisted = tx.fetchone(
            "SELECT payload FROM runpod_billing_buckets WHERE observation_id=%s",
            (bucket.observation_id,),
        )
        assert persisted is not None
        assert persisted["payload"]["observation_id"] == str(bucket.observation_id)

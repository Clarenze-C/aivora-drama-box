from concurrent.futures import ThreadPoolExecutor

import pytest

from microdrama.budget import BudgetService
from microdrama.budget.billing import BillingRepository
from microdrama.config import Settings
from microdrama.contracts.errors import BudgetExhausted
from microdrama.contracts.examples import (
    T0,
    budget_reservation_request,
    runpod_billing_bucket_observation,
    runpod_billing_query_observation,
)
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = pytest.mark.db


def test_ingest_is_idempotent_concurrent_and_survives_pool_restart(db_dsn: str) -> None:
    query = runpod_billing_query_observation()
    bucket = runpod_billing_bucket_observation()

    # T045-FIX A-S7: the first ingest runs with the budget service attached, so the
    # recovery exposure is posted (RECOVERY_PENDING), exactly as production ingests.
    clock = FakeClock(T0)
    with Database(db_dsn) as db:
        BillingRepository(
            db, budget_service=BudgetService(db, clock, SequentialIds("t045-fix-a7"), Settings())
        ).ingest(query, [bucket])

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
        # T045-FIX A-S7 (restored strength): the provider-reported sum is asserted
        # exactly — every micro-USD of the bucket is allocated to someone.
        assert (
            tx.fetchval(
                "SELECT sum(delta_micro_usd) FROM runpod_billing_allocations "
                "WHERE bucket_observation_id=%s",
                (bucket.observation_id,),
            )
            == bucket.total_amount_micro_usd
        )
        # T045-FIX A-S7: the uncovered bucket's RECOVERY allocation exists and its
        # pending posting row holds the exposure (nothing is quietly dropped).
        recovery = tx.fetchall(
            "SELECT a.delta_micro_usd, p.posting_state FROM runpod_billing_allocations a "
            "LEFT JOIN runpod_billing_budget_postings p USING (allocation_id) "
            "WHERE a.owner_kind='RECOVERY' AND a.delta_micro_usd > 0"
        )
        assert recovery, "an uncovered bucket must produce RECOVERY allocations"
        assert sum(row["delta_micro_usd"] for row in recovery) == bucket.total_amount_micro_usd
        assert all(row["posting_state"] == "RECOVERY_PENDING" for row in recovery)
        # T045 R7 replaced accounting_readiness with per-lease readiness: a recovery
        # allocation on the covering bucket keeps any lease RECOVERY_REQUIRED.
        from t045_lease_probe import probe_lease_readiness

        readiness = probe_lease_readiness(db, bucket)
        assert readiness.state == "RECOVERY_REQUIRED"
        assert readiness.pending_since is not None

    # T045-FIX A-S7: the unresolved recovery exposure blocks a new Runpod reservation.
    request = budget_reservation_request().model_copy(update={"provider": "runpod"})
    with Database(db_dsn) as db:
        with pytest.raises(BudgetExhausted, match="recovery"):
            BudgetService(db, clock, SequentialIds("t045-fix-a7"), Settings()).reserve(request)

    # A fresh pool represents process restart/readback; durable rows remain canonical JSON.
    with Database(db_dsn) as restarted, restarted.transaction(readonly=True) as tx:
        persisted = tx.fetchone(
            "SELECT payload FROM runpod_billing_buckets WHERE observation_id=%s",
            (bucket.observation_id,),
        )
        assert persisted is not None
        assert persisted["payload"]["observation_id"] == str(bucket.observation_id)

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from budget_support import GPU, World, request_for

from microdrama.budget.billing import BillingRepository
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BillingInvoiceVerification,
    BillingVerificationResult,
    RunpodBillingAllocation,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
)
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import BudgetExhausted, PolicyDenied
from microdrama.contracts.examples import (
    billing_invoice_verification,
    runpod_billing_bucket_disputed,
    runpod_billing_bucket_invoice_verified,
    runpod_billing_bucket_observation,
    runpod_billing_query_observation,
)
from microdrama.persistence import Database

pytestmark = pytest.mark.db


def test_recovery_allocation_blocks_new_runpod_reservations(world: World, db: Database) -> None:
    episode = world.episode()
    bucket = runpod_billing_bucket_observation()
    query = runpod_billing_query_observation()
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket])

    request = request_for(
        key="billing-recovery-blocked",
        episode_id=episode.episode_id,
        provider="runpod",
        category=GPU,
    )
    with pytest.raises(BudgetExhausted, match="unresolved provider billing recovery"):
        world.service.reserve(request)

    # Cleanup remains available so recovery does not prevent stopping owned compute.
    cleanup = request_for(
        key="billing-recovery-cleanup",
        episode_id=episode.episode_id,
        provider="runpod",
        category=GPU,
        cleanup=True,
    )
    assert world.service.reserve(cleanup).reserved_micro_usd > 0


def test_provider_reported_allocations_are_idempotent_and_negative_revision_never_restores(
    world: World, db: Database
) -> None:
    episode = world.episode()
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    bucket = runpod_billing_bucket_observation()
    query = runpod_billing_query_observation()
    from microdrama.contracts.cost import BillingAllocationBasis, BillingComponent

    amounts = {
        BillingComponent.GPU: bucket.gpu_amount_micro_usd,
        BillingComponent.CPU: bucket.cpu_amount_micro_usd,
        BillingComponent.DISK: bucket.disk_amount_micro_usd,
    }
    allocations = [
        RunpodBillingAllocation(
            allocation_id=uuid4(),
            bucket_identity_sha256=bucket.bucket_identity_sha256,
            bucket_observation_id=bucket.observation_id,
            bucket_revision=bucket.revision,
            component=component,
            owner_kind="EPISODE",
            owner_id=episode.episode_id,
            allocation_basis=(
                BillingAllocationBasis.STORAGE_OWNER
                if component is BillingComponent.DISK
                else BillingAllocationBasis.MEASURED_OVERLAP
            ),
            delta_micro_usd=amount,
            allocated_at=bucket.observed_at,
        )
        for component, amount in amounts.items()
    ]
    repository = BillingRepository(db, budget_service=world.service)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: repository.ingest(query, [bucket], allocations), range(4)))
    allocation = allocations[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: world.service.reconcile_provider_allocation(bucket, allocation), range(4)
            )
        )
    assert all(result is not None for result in results)
    other_results = [
        world.service.reconcile_provider_allocation(bucket, item) for item in allocations[1:]
    ]
    assert all(result is not None and result.replayed for result in other_results)
    after = world.counters(episode.account_id)
    assert after["settled"] == bucket.total_amount_micro_usd
    assert after["committed"] == bucket.total_amount_micro_usd
    assert (
        world.count("SELECT count(*) FROM charges WHERE receipt_id=%s", (results[0].receipt_id,))
        == 1
    )

    replays = [
        world.service.reconcile_provider_allocation(bucket, allocation)
        for allocation in allocations
    ]
    assert all(result is not None and result.replayed for result in replays)
    assert world.counters(episode.account_id) == after

    revision_query = RunpodBillingQueryObservation.model_validate(
        query.model_dump(mode="python")
        | {
            "query_id": uuid4(),
            "raw_response_sha256": sha256(b"billing-revision").hexdigest(),
            "bucket_observation_ids": [uuid4()],
        }
    )
    revision_id = revision_query.bucket_observation_ids[0]
    revised_payload = bucket.model_dump(mode="python")
    revised_payload.update(
        observation_id=revision_id,
        query_id=revision_query.query_id,
        revision=2,
        prior_observation_id=bucket.observation_id,
        prior_raw_response_sha256=bucket.raw_response_sha256,
        raw_response_sha256=revision_query.raw_response_sha256,
        total_amount_micro_usd=bucket.total_amount_micro_usd - 100_000,
        gpu_amount_micro_usd=bucket.gpu_amount_micro_usd - 100_000,
    )
    revised = RunpodBillingBucketObservation.model_validate(revised_payload)
    revised_allocations = [
        allocation.model_copy(
            update={
                "allocation_id": uuid4(),
                "bucket_observation_id": revised.observation_id,
                "bucket_revision": revised.revision,
                "bucket_identity_sha256": revised.bucket_identity_sha256,
                "delta_micro_usd": -100_000 if allocation.component is BillingComponent.GPU else 0,
            }
        )
        for allocation in allocations
    ]
    # Ensure the updated assignment contract is revalidated after the copy.
    revised_allocations = [
        RunpodBillingAllocation.model_validate(item.model_dump(mode="python"))
        for item in revised_allocations
    ]
    BillingRepository(db, budget_service=world.service).ingest(
        revision_query, [revised], revised_allocations
    )
    assert world.counters(episode.account_id) == after


def test_invoice_finality_is_durable_and_recovery_reassignment_is_audited(
    world: World, db: Database
) -> None:
    episode = world.episode()
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    bucket = runpod_billing_bucket_invoice_verified()
    query = runpod_billing_query_observation()
    verification = billing_invoice_verification()
    repository = BillingRepository(db, budget_service=world.service)
    repository.ingest(query, [bucket])
    repository.verify_invoice(bucket, verification)
    world.service.record_provider_invoice_verification(bucket, verification)
    world.service.record_provider_invoice_verification(bucket, verification)
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations") == 1
        recovery_ids = tx.fetchall(
            "SELECT allocation_id FROM runpod_billing_allocations WHERE owner_kind='RECOVERY'"
        )
    assert len(recovery_ids) == 3
    for row in recovery_ids:
        world.service.resolve_billing_recovery(
            row["allocation_id"],
            assigned_episode_id=episode.episode_id,
            actor_ref="owner:test",
            reason="Fixture owner assignment for reconciliation test",
        )
        world.service.resolve_billing_recovery(
            row["allocation_id"],
            assigned_episode_id=episode.episode_id,
            actor_ref="owner:test",
            reason="Fixture owner assignment for reconciliation test",
        )
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_recovery_resolutions") == 3
    assert world.counters(episode.account_id)["settled"] == bucket.total_amount_micro_usd


def test_mismatched_invoice_evidence_is_durable_and_never_finalizes_budget(
    world: World, db: Database
) -> None:
    verification_id = uuid4()
    payload = runpod_billing_bucket_disputed().model_dump(mode="python")
    payload["invoice_verification_id"] = verification_id
    bucket = RunpodBillingBucketObservation.model_validate(payload)
    verification = BillingInvoiceVerification(
        verification_id=verification_id,
        provider_account_ref=bucket.provider_account_ref,
        bucket_identity_sha256=bucket.bucket_identity_sha256,
        bucket_observation_id=bucket.observation_id,
        bucket_revision=bucket.revision,
        evidence_source="INVOICE",
        evidence_sha256=sha256(b"runpod-invoice-mismatch-evidence").hexdigest(),
        evidence_observed_at=bucket.observed_at + timedelta(hours=1),
        verified_at=bucket.observed_at + timedelta(hours=1, minutes=5),
        currency="USD",
        amount_micro_usd=999_000,
        result=BillingVerificationResult.MISMATCHED,
        mismatch_reason="Provider invoice total differs from the allocated bucket total.",
    )
    repository = BillingRepository(db, budget_service=world.service)
    repository.ingest(runpod_billing_query_observation(), [bucket])
    # The mismatch evidence must commit; nothing in the budget may finalize from it.
    repository.verify_invoice(bucket, verification)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT result FROM runpod_billing_invoice_verifications WHERE verification_id=%s",
            (verification.verification_id,),
        )
        assert row is not None and row["result"] == "MISMATCHED"
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations") == 0
        assert tx.fetchval("SELECT count(*) FROM charges") == 0


def test_budget_policy_refusal_rolls_back_bucket_allocation_and_charge_together(
    world: World, db: Database
) -> None:
    episode = world.episode()
    bucket = runpod_billing_bucket_observation()
    query = runpod_billing_query_observation()
    from microdrama.contracts.cost import BillingAllocationBasis, BillingComponent

    allocations = [
        RunpodBillingAllocation(
            allocation_id=uuid4(),
            bucket_identity_sha256=bucket.bucket_identity_sha256,
            bucket_observation_id=bucket.observation_id,
            bucket_revision=bucket.revision,
            component=component,
            owner_kind="EPISODE",
            owner_id=episode.episode_id,
            allocation_basis=(
                BillingAllocationBasis.STORAGE_OWNER
                if component is BillingComponent.DISK
                else BillingAllocationBasis.MEASURED_OVERLAP
            ),
            delta_micro_usd=amount,
            allocated_at=bucket.observed_at,
        )
        for component, amount in (
            (BillingComponent.GPU, bucket.gpu_amount_micro_usd),
            (BillingComponent.CPU, bucket.cpu_amount_micro_usd),
            (BillingComponent.DISK, bucket.disk_amount_micro_usd),
        )
    ]
    with pytest.raises(PolicyDenied, match="refused in OFFLINE_MOCK"):
        BillingRepository(db, budget_service=world.service).ingest(query, [bucket], allocations)
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_queries") == 0
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_buckets") == 0
        assert tx.fetchval("SELECT count(*) FROM runpod_billing_allocations") == 0
        assert tx.fetchval("SELECT count(*) FROM charges") == 0
    world.service._settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    BillingRepository(db, budget_service=world.service).ingest(query, [bucket], allocations)
    assert world.counters(episode.account_id)["settled"] == bucket.total_amount_micro_usd

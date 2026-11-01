from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from microdrama.contracts.cost import (
    BillingComponent,
    RunpodBillingAllocation,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    validate_billing_invoice_verification,
    validate_runpod_billing_allocations,
    validate_runpod_billing_query,
    validate_runpod_billing_revision,
)
from microdrama.contracts.examples import (
    billing_invoice_verification,
    runpod_billing_allocation,
    runpod_billing_bucket_invoice_verified,
    runpod_billing_bucket_observation,
    runpod_billing_query_empty,
    runpod_billing_query_observation,
    runpod_billing_query_unknown,
)


def test_query_bucket_and_component_allocations_link_exactly() -> None:
    query = runpod_billing_query_observation()
    bucket = runpod_billing_bucket_observation()
    allocations = [runpod_billing_allocation(component) for component in BillingComponent]
    validate_runpod_billing_query(query, [bucket], allocations)
    validate_runpod_billing_allocations(bucket, allocations)


@pytest.mark.parametrize(
    "query_builder", [runpod_billing_query_empty, runpod_billing_query_unknown]
)
def test_empty_or_unknown_query_never_completes_zero_cost(query_builder) -> None:
    query = query_builder()
    validate_runpod_billing_query(query, [])
    with pytest.raises(ValueError, match="cannot produce buckets or allocations"):
        validate_runpod_billing_query(query, [], [runpod_billing_allocation()])


def test_revision_allocations_sum_only_component_deltas() -> None:
    prior = runpod_billing_bucket_observation()
    current_payload = prior.model_dump(mode="python")
    current_payload.update(
        observation_id=uuid5(NAMESPACE_URL, "runpod-billing-bucket-r2"),
        revision=2,
        prior_observation_id=prior.observation_id,
        prior_raw_response_sha256=prior.raw_response_sha256,
        raw_response_sha256="b" * 64,
        total_amount_micro_usd=1_100_000,
        gpu_amount_micro_usd=600_000,
    )
    current = RunpodBillingBucketObservation.model_validate(current_payload)
    validate_runpod_billing_revision(prior, current)

    deltas = {
        BillingComponent.GPU: 100_000,
        BillingComponent.CPU: 0,
        BillingComponent.DISK: 0,
    }
    allocations = []
    for component, delta in deltas.items():
        allocation = runpod_billing_allocation(component).model_dump(mode="python")
        allocation.update(
            allocation_id=uuid5(NAMESPACE_URL, f"runpod-r2-{component.value}"),
            bucket_observation_id=current.observation_id,
            bucket_revision=current.revision,
            delta_micro_usd=delta,
        )
        allocations.append(RunpodBillingAllocation.model_validate(allocation))
    validate_runpod_billing_allocations(current, allocations, prior=prior)

    query_payload = runpod_billing_query_observation().model_dump(mode="python")
    query_payload.update(
        bucket_observation_ids=[current.observation_id],
        raw_response_sha256=current.raw_response_sha256,
    )
    query = RunpodBillingQueryObservation.model_validate(query_payload)
    validate_runpod_billing_query(
        query,
        [current],
        allocations,
        prior_observations={current.observation_id: prior},
    )
    with pytest.raises(ValueError, match="requires its exact prior observation"):
        validate_runpod_billing_query(query, [current], allocations)
    wrong_prior = prior.model_copy(update={"raw_response_sha256": "c" * 64})
    with pytest.raises(ValueError, match="exact prior observation"):
        validate_runpod_billing_query(
            query,
            [current],
            allocations,
            prior_observations={current.observation_id: wrong_prior},
        )

    bad_gpu = allocations[0].model_copy(update={"delta_micro_usd": 99_999})
    with pytest.raises(ValueError, match="GPU allocation deltas"):
        validate_runpod_billing_allocations(current, [bad_gpu, *allocations[1:]], prior=prior)


def test_invoice_evidence_is_required_for_invoice_verified_finality() -> None:
    bucket = runpod_billing_bucket_invoice_verified()
    verification = billing_invoice_verification()
    validate_billing_invoice_verification(bucket, verification)

    mismatch = verification.model_copy(
        update={"amount_micro_usd": verification.amount_micro_usd - 1}
    )
    with pytest.raises(ValueError, match="does not match its invoice evidence"):
        validate_billing_invoice_verification(bucket, mismatch)

    payload = bucket.model_dump(mode="python")
    payload["invoice_verification_id"] = None
    with pytest.raises(ValidationError, match="invoice verification link"):
        RunpodBillingBucketObservation.model_validate(payload)

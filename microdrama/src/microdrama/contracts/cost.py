"""Budget reservation/usage, pod leases, render requests and provider operations."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    ControlKind,
    CostBasis,
    LeaseState,
    PodState,
    PriceSource,
    PriceUnit,
    Provenance,
    ProviderOperationState,
    QueueName,
    ReceiptKind,
    RenderTier,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    CurrencyCode,
    DurationMs,
    Identifier,
    MicroUSD,
    ObjectKey,
    PositiveInt,
    PositiveMs,
    SemanticKey,
    Sha256Hex,
    ShortText,
    SignedMicroUSD,
    UtcDateTime,
    VersionedPayload,
)


class PriceQuote(ContractModel):
    """Unit price for a paid operation. Non-USD currency means unknown price (no FX)."""

    currency: CurrencyCode
    unit: PriceUnit
    unit_price_micro_usd: MicroUSD
    source: PriceSource
    price_table_version: ShortText
    as_of: UtcDateTime


class ExposureCeilings(ContractModel):
    """Hard ceilings that bound worst-case exposure. A timeout is always required."""

    timeout_ms: PositiveMs
    max_units: PositiveInt
    max_input_tokens: PositiveInt | None = None
    max_output_tokens: PositiveInt | None = None
    max_duration_ms: PositiveMs | None = None
    max_width: PositiveInt | None = None
    max_height: PositiveInt | None = None


_TOKEN_UNITS = {
    PriceUnit.INPUT_TOKEN_1K: "max_input_tokens",
    PriceUnit.OUTPUT_TOKEN_1K: "max_output_tokens",
}
_MEDIA_SECOND_UNITS = frozenset({PriceUnit.AUDIO_SECOND, PriceUnit.VIDEO_SECOND})

# Categories whose shutdown/cleanup work may use the protected shutdown reserve (production only).
CLEANUP_CATEGORIES: frozenset[BudgetCategory] = frozenset(
    {
        BudgetCategory.GPU_GENERATION,
        BudgetCategory.RECOVERY_HEADROOM,
        BudgetCategory.CPU_STORAGE_TRANSFER,
    }
)


# The only operations that may draw on the shutdown reserve: stopping/terminating owned pods and
# cleaning up storage. A flag on any other operation (for example a render) is refused (V-19).
CLEANUP_OPERATION_KINDS: frozenset[str] = frozenset(
    {"pod.stop", "pod.terminate", "storage.cleanup"}
)

# Provider operation kinds that need no budget reservation. Publishing calls are free platform
# API requests: no provider bills them, so a reservation would be a fabricated hold (reserve()
# already refuses zero-exposure prices). They still carry job linkage for crash recovery. The
# database CHECK (relaxed per kind by migration 0016) is the second layer of this rule (V-24).
UNMETERED_OPERATION_KINDS: frozenset[str] = frozenset(
    {
        "publish.submit_slot",
        "publish.poll_status",
        "publish.reconcile_slot",
        "publish.update_metadata",
    }
)


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def exposure_units(unit: PriceUnit, ceilings: ExposureCeilings) -> int:
    """Billable units the ceilings allow for this price unit (the worst case, never less).

    Token prices need the matching token ceiling and media-second prices need
    ``max_duration_ms``: without them the maximum exposure is uncertain and the request is
    invalid. GPU time is bounded by the timeout. The result is never below ``max_units``.
    """
    derived = 0
    if unit in _TOKEN_UNITS:
        tokens = getattr(ceilings, _TOKEN_UNITS[unit])
        if tokens is None:
            raise ValueError(f"{unit.value} pricing needs ceilings.{_TOKEN_UNITS[unit]}")
        derived = _ceil_div(tokens, 1000)
    elif unit in _MEDIA_SECOND_UNITS:
        if ceilings.max_duration_ms is None:
            raise ValueError(f"{unit.value} pricing needs ceilings.max_duration_ms")
        derived = _ceil_div(ceilings.max_duration_ms, 1000)
    elif unit is PriceUnit.GPU_SECOND:
        derived = _ceil_div(ceilings.timeout_ms, 1000)
    return max(ceilings.max_units, derived)


class BudgetReservationRequest(VersionedPayload):
    """Ask the budget service to reserve worst-case exposure before paid dispatch.

    ``price`` is None when the price is unknown; the budget service must then
    refuse with ``UnknownPrice`` (never assume zero).
    """

    request_id: UUID
    semantic_key: SemanticKey = Field(description="Unique per logical paid step; retries reuse it")
    scope_kind: BudgetScopeKind
    episode_id: UUID | None = None
    season_id: UUID | None = None
    category: BudgetCategory
    queue: QueueName
    job_id: UUID | None = None
    provider: Identifier
    operation_kind: Identifier
    price: PriceQuote | None
    ceilings: ExposureCeilings
    worst_case_micro_usd: MicroUSD
    is_shutdown_or_cleanup: bool = Field(
        default=False,
        description="Only production GPU/recovery/storage shutdown or cleanup may draw on the "
        "shutdown reserve",
    )
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def _scope_and_bound(self) -> BudgetReservationRequest:
        if self.scope_kind is BudgetScopeKind.EPISODE and self.episode_id is None:
            raise ValueError("episode reservations must name episode_id")
        if self.scope_kind is BudgetScopeKind.SEASON_RESEARCH and self.season_id is None:
            raise ValueError("season research reservations must name season_id")
        if self.price is not None and self.price.unit_price_micro_usd == 0:
            raise ValueError("a zero unit price is not a known price; paid dispatch needs one")
        if (
            self.price is not None
            and self.category is BudgetCategory.GPU_GENERATION
            and self.price.unit is not PriceUnit.GPU_SECOND
        ):
            raise ValueError("GPU generation is priced per GPU_SECOND so the timeout bounds it")
        if self.price is not None and self.price.currency == "USD":
            computed = self.price.unit_price_micro_usd * exposure_units(
                self.price.unit, self.ceilings
            )
            if self.worst_case_micro_usd < computed:
                raise ValueError(
                    "worst_case_micro_usd is below unit_price x the units its ceilings allow"
                )
        if self.is_shutdown_or_cleanup and (
            self.queue is not QueueName.PRODUCTION
            or self.category not in CLEANUP_CATEGORIES
            or self.operation_kind not in CLEANUP_OPERATION_KINDS
        ):
            raise ValueError(
                "only production GPU/recovery/storage shutdown or cleanup operations "
                f"({', '.join(sorted(CLEANUP_OPERATION_KINDS))}) may draw on the shutdown reserve"
            )
        return self


class UsageReceipt(VersionedPayload):
    """Observed usage. Fakes emit SYNTHETIC_FAKE; only PROVIDER_REPORTED/BILLED are measured."""

    receipt_id: UUID
    provider: Identifier
    provider_receipt_id: ShortText = Field(description="Provider-side dedupe key")
    kind: ReceiptKind
    cost_basis: CostBasis
    reservation_id: UUID | None = None
    episode_id: UUID | None = None
    season_id: UUID | None = None
    job_id: UUID | None = None
    category: BudgetCategory
    amount_micro_usd: MicroUSD
    currency: CurrencyCode = "USD"
    units: Count
    unit: PriceUnit
    interval_start: UtcDateTime | None = None
    interval_end: UtcDateTime | None = None
    observed_at: UtcDateTime
    provenance: Provenance

    @model_validator(mode="after")
    def _labelled(self) -> UsageReceipt:
        if self.cost_basis is CostBasis.ESTIMATED:
            raise ValueError("an estimate is not a receipt")
        fake = self.provenance is Provenance.FAKE_SYNTHETIC
        if fake != (self.cost_basis is CostBasis.SYNTHETIC_FAKE):
            raise ValueError(
                "fake provenance must use SYNTHETIC_FAKE cost basis (and only fakes may)"
            )
        if self.measured and self.provenance is not Provenance.LIVE_PROVIDER:
            raise ValueError("measured cost bases come only from live providers")
        if (self.interval_start is None) != (self.interval_end is None):
            raise ValueError("interval_start and interval_end go together")
        if self.interval_start and self.interval_end and self.interval_end < self.interval_start:
            raise ValueError("interval_end before interval_start")
        return self

    @property
    def measured(self) -> bool:
        return self.cost_basis in (CostBasis.PROVIDER_REPORTED, CostBasis.BILLED)


class BillingQueryState(StrEnum):
    BUCKETS = "BUCKETS"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class BillingFinalityState(StrEnum):
    PENDING_PROVIDER_FINALITY = "PENDING_PROVIDER_FINALITY"
    ALLOCATED_PROVIDER_REPORTED = "ALLOCATED_PROVIDER_REPORTED"
    INVOICE_VERIFIED = "INVOICE_VERIFIED"
    DISPUTED = "DISPUTED"


class BillingComponent(StrEnum):
    GPU = "GPU"
    CPU = "CPU"
    DISK = "DISK"


class BillingAllocationBasis(StrEnum):
    MEASURED_OVERLAP = "MEASURED_OVERLAP"
    STORAGE_OWNER = "STORAGE_OWNER"
    UNCOVERED = "UNCOVERED"


class BillingVerificationResult(StrEnum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


def runpod_bucket_identity_sha256(
    account_ref: str,
    pod_id: str,
    bucket_start: UtcDateTime,
    bucket_end: UtcDateTime,
    bucket_size_seconds: PositiveInt,
) -> str:
    """Stable bucket identity excludes amount/revision so updates append to one lineage."""
    return canonical_hash(
        {
            "provider": "RUNPOD",
            "account_ref": account_ref,
            "pod_id": pod_id,
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "bucket_size_seconds": bucket_size_seconds,
        }
    )


class RunpodBillingQueryObservation(VersionedPayload):
    query_id: UUID
    provider_account_ref: AccountRef
    requested_window_start: UtcDateTime
    requested_window_end: UtcDateTime
    provider_resolved_window_start: UtcDateTime
    provider_resolved_window_end: UtcDateTime
    bucket_size_seconds: PositiveInt
    raw_response_sha256: Sha256Hex
    observed_at: UtcDateTime
    result_state: BillingQueryState
    bucket_observation_ids: list[UUID] = Field(default_factory=list)
    unknown_reason: ShortText | None = None

    @model_validator(mode="after")
    def _query_shape(self):
        if self.requested_window_end <= self.requested_window_start:
            raise ValueError("requested billing query window must be non-empty")
        if self.provider_resolved_window_end <= self.provider_resolved_window_start:
            raise ValueError("provider-resolved billing query window must be non-empty")
        if len(set(self.bucket_observation_ids)) != len(self.bucket_observation_ids):
            raise ValueError("duplicate bucket observation ID in billing query")
        if self.result_state is BillingQueryState.BUCKETS and not self.bucket_observation_ids:
            raise ValueError("BUCKETS query state requires at least one observation")
        if self.result_state is not BillingQueryState.BUCKETS and self.bucket_observation_ids:
            raise ValueError("EMPTY/UNKNOWN query state cannot contain bucket observations")
        if self.result_state is BillingQueryState.UNKNOWN and self.unknown_reason is None:
            raise ValueError("UNKNOWN billing query needs an explicit reason")
        if self.result_state is not BillingQueryState.UNKNOWN and self.unknown_reason is not None:
            raise ValueError("unknown_reason only applies to UNKNOWN billing query state")
        return self


class RunpodBillingBucketObservation(VersionedPayload):
    observation_id: UUID
    query_id: UUID
    provider_account_ref: AccountRef
    pod_id: ShortText
    bucket_start: UtcDateTime
    bucket_end: UtcDateTime
    bucket_size_seconds: PositiveInt
    bucket_identity_sha256: Sha256Hex
    revision: PositiveInt
    prior_observation_id: UUID | None = None
    prior_raw_response_sha256: Sha256Hex | None = None
    provider_resolved_window_start: UtcDateTime
    provider_resolved_window_end: UtcDateTime
    raw_response_sha256: Sha256Hex
    observed_at: UtcDateTime
    currency: CurrencyCode
    total_amount_micro_usd: MicroUSD
    gpu_amount_micro_usd: MicroUSD
    cpu_amount_micro_usd: MicroUSD
    disk_amount_micro_usd: MicroUSD
    finality_state: BillingFinalityState
    invoice_verification_id: UUID | None = None
    dispute_reason: ShortText | None = None

    @model_validator(mode="after")
    def _bucket_shape(self):
        if self.bucket_end <= self.bucket_start:
            raise ValueError("billing bucket interval must be non-empty")
        if self.provider_resolved_window_end <= self.provider_resolved_window_start:
            raise ValueError("provider-resolved billing window must be non-empty")
        if not (
            self.bucket_start < self.provider_resolved_window_end
            and self.bucket_end > self.provider_resolved_window_start
        ):
            raise ValueError("billing bucket must overlap its provider-resolved query window")
        expected_identity = runpod_bucket_identity_sha256(
            self.provider_account_ref,
            self.pod_id,
            self.bucket_start,
            self.bucket_end,
            self.bucket_size_seconds,
        )
        if self.bucket_identity_sha256 != expected_identity:
            raise ValueError("billing bucket identity hash does not match account/pod/window/size")
        if (self.prior_observation_id is None) != (self.prior_raw_response_sha256 is None):
            raise ValueError("prior bucket observation ID and raw hash must be provided together")
        if self.revision == 1 and self.prior_observation_id is not None:
            raise ValueError("first billing bucket revision cannot have a prior observation")
        if self.revision > 1 and self.prior_observation_id is None:
            raise ValueError("later billing bucket revision requires its prior observation link")
        components_match = self.total_amount_micro_usd == (
            self.gpu_amount_micro_usd + self.cpu_amount_micro_usd + self.disk_amount_micro_usd
        )
        if (self.currency != "USD" or not components_match) and (
            self.finality_state is not BillingFinalityState.DISPUTED
        ):
            raise ValueError("non-USD or component-mismatched billing bucket must be DISPUTED")
        if self.finality_state is BillingFinalityState.DISPUTED and self.dispute_reason is None:
            raise ValueError("DISPUTED billing bucket needs a reason")
        if self.finality_state is not BillingFinalityState.DISPUTED and self.dispute_reason:
            raise ValueError("dispute reason only applies to DISPUTED billing bucket")
        if self.finality_state is BillingFinalityState.INVOICE_VERIFIED:
            if self.invoice_verification_id is None:
                raise ValueError(
                    "INVOICE_VERIFIED billing bucket needs an invoice verification link"
                )
        elif (
            self.invoice_verification_id is not None
            and self.finality_state is not BillingFinalityState.DISPUTED
        ):
            raise ValueError("invoice verification link requires verified or disputed finality")
        return self


class RunpodBillingAllocation(VersionedPayload):
    allocation_id: UUID
    bucket_identity_sha256: Sha256Hex
    bucket_observation_id: UUID
    bucket_revision: PositiveInt
    component: BillingComponent
    owner_kind: Literal["EPISODE", "RECOVERY"]
    owner_id: UUID | Literal["recovery_pool"]
    allocation_basis: BillingAllocationBasis
    delta_micro_usd: SignedMicroUSD
    allocated_at: UtcDateTime

    @model_validator(mode="after")
    def _allocation_shape(self):
        is_recovery = self.owner_kind == "RECOVERY"
        if is_recovery != (self.owner_id == "recovery_pool"):
            raise ValueError(
                "RECOVERY owner must use recovery_pool ID; EPISODE owner must use UUID"
            )
        if is_recovery != (self.allocation_basis is BillingAllocationBasis.UNCOVERED):
            raise ValueError("UNCOVERED allocation basis is only valid for recovery-pool owner")
        if not is_recovery:
            expected_basis = (
                BillingAllocationBasis.STORAGE_OWNER
                if self.component is BillingComponent.DISK
                else BillingAllocationBasis.MEASURED_OVERLAP
            )
            if self.allocation_basis is not expected_basis:
                raise ValueError(
                    "allocation basis does not match GPU/CPU overlap or disk ownership"
                )
        return self


class BillingInvoiceVerification(VersionedPayload):
    verification_id: UUID
    provider_account_ref: AccountRef
    bucket_identity_sha256: Sha256Hex
    bucket_observation_id: UUID
    bucket_revision: PositiveInt
    evidence_source: Literal["INVOICE", "CONSOLE"]
    evidence_sha256: Sha256Hex
    evidence_observed_at: UtcDateTime
    verified_at: UtcDateTime
    currency: CurrencyCode
    amount_micro_usd: MicroUSD
    result: BillingVerificationResult
    mismatch_reason: ShortText | None = None

    @model_validator(mode="after")
    def _verification_shape(self):
        if self.result is BillingVerificationResult.MATCHED:
            if self.currency != "USD":
                raise ValueError("matched invoice verification must be denominated in USD")
            if self.mismatch_reason is not None:
                raise ValueError("matched invoice verification cannot carry a mismatch reason")
        elif self.mismatch_reason is None:
            raise ValueError("mismatched invoice verification needs a reason")
        return self


def validate_runpod_billing_query(
    query: RunpodBillingQueryObservation,
    buckets: list[RunpodBillingBucketObservation],
    allocations: list[RunpodBillingAllocation] | None = None,
    *,
    prior_observations: Mapping[UUID, RunpodBillingBucketObservation] | None = None,
) -> None:
    """Verify query/bucket linkage; EMPTY and UNKNOWN responses never settle zero."""
    allocations = allocations or []
    prior_observations = prior_observations or {}
    if query.result_state is not BillingQueryState.BUCKETS:
        if buckets or allocations:
            raise ValueError("EMPTY/UNKNOWN billing query cannot produce buckets or allocations")
        return
    by_id = {bucket.observation_id: bucket for bucket in buckets}
    if len(by_id) != len(buckets) or set(by_id) != set(query.bucket_observation_ids):
        raise ValueError("query bucket observation IDs do not match supplied bucket records")
    for allocation in allocations:
        if allocation.bucket_observation_id not in by_id:
            raise ValueError("allocation is not attached to a bucket in its query")
    for bucket in buckets:
        if (
            bucket.query_id != query.query_id
            or bucket.provider_account_ref != query.provider_account_ref
            or bucket.bucket_size_seconds != query.bucket_size_seconds
            or bucket.provider_resolved_window_start != query.provider_resolved_window_start
            or bucket.provider_resolved_window_end != query.provider_resolved_window_end
        ):
            raise ValueError("billing bucket does not match its provider-resolved query")
        prior = prior_observations.get(bucket.observation_id)
        if bucket.revision > 1 and prior is None:
            raise ValueError("later billing bucket revision requires its exact prior observation")
        validate_runpod_billing_revision(prior, bucket)
        bucket_allocations = [
            allocation
            for allocation in allocations
            if allocation.bucket_observation_id == bucket.observation_id
        ]
        if bucket_allocations:
            validate_runpod_billing_allocations(bucket, bucket_allocations, prior=prior)
        elif bucket.finality_state in (
            BillingFinalityState.ALLOCATED_PROVIDER_REPORTED,
            BillingFinalityState.INVOICE_VERIFIED,
        ):
            raise ValueError("allocated bucket query is missing component allocations")


def validate_runpod_billing_revision(
    prior: RunpodBillingBucketObservation | None,
    current: RunpodBillingBucketObservation,
) -> None:
    """Require monotonic, same-bucket revision links and exact prior response hash."""
    if prior is None:
        if current.revision != 1 or current.prior_observation_id is not None:
            raise ValueError("first billing bucket revision must be revision 1 without a prior")
        return
    if current.revision != prior.revision + 1:
        raise ValueError("billing bucket revision must increase monotonically by one")
    if current.bucket_identity_sha256 != prior.bucket_identity_sha256:
        raise ValueError("billing bucket revision identity changed")
    if (
        current.prior_observation_id != prior.observation_id
        or current.prior_raw_response_sha256 != prior.raw_response_sha256
    ):
        raise ValueError("billing bucket revision does not link its exact prior observation")


def validate_runpod_billing_allocations(
    current: RunpodBillingBucketObservation,
    allocations: list[RunpodBillingAllocation],
    *,
    prior: RunpodBillingBucketObservation | None = None,
) -> None:
    """Require signed component deltas to sum exactly to new-minus-prior amounts."""
    validate_runpod_billing_revision(prior, current)
    if current.finality_state not in (
        BillingFinalityState.ALLOCATED_PROVIDER_REPORTED,
        BillingFinalityState.INVOICE_VERIFIED,
    ):
        if allocations:
            raise ValueError("pending or disputed bucket cannot be allocated")
        return
    if len({item.allocation_id for item in allocations}) != len(allocations):
        raise ValueError("duplicate billing allocation ID")
    if len(
        {
            (item.component, item.owner_kind, item.owner_id, item.allocation_basis)
            for item in allocations
        }
    ) != len(allocations):
        raise ValueError("duplicate owner/component allocation for bucket revision")
    component_fields = {
        BillingComponent.GPU: "gpu_amount_micro_usd",
        BillingComponent.CPU: "cpu_amount_micro_usd",
        BillingComponent.DISK: "disk_amount_micro_usd",
    }
    for allocation in allocations:
        if (
            allocation.bucket_observation_id != current.observation_id
            or allocation.bucket_identity_sha256 != current.bucket_identity_sha256
            or allocation.bucket_revision != current.revision
        ):
            raise ValueError("allocation does not reference the exact bucket revision")
    for component, field_name in component_fields.items():
        if not any(item.component is component for item in allocations):
            raise ValueError(f"{component.value} component needs an explicit allocation")
        prior_amount = getattr(prior, field_name) if prior is not None else 0
        expected_delta = getattr(current, field_name) - prior_amount
        actual_delta = sum(
            item.delta_micro_usd for item in allocations if item.component is component
        )
        if actual_delta != expected_delta:
            raise ValueError(
                f"{component.value} allocation deltas do not match bucket revision delta"
            )


def validate_billing_invoice_verification(
    bucket: RunpodBillingBucketObservation,
    verification: BillingInvoiceVerification,
) -> None:
    if (
        verification.provider_account_ref != bucket.provider_account_ref
        or verification.bucket_identity_sha256 != bucket.bucket_identity_sha256
        or verification.bucket_observation_id != bucket.observation_id
        or verification.bucket_revision != bucket.revision
    ):
        raise ValueError("invoice verification does not bind the exact bucket revision")
    if verification.result is BillingVerificationResult.MATCHED:
        if (
            bucket.finality_state is not BillingFinalityState.INVOICE_VERIFIED
            or bucket.invoice_verification_id != verification.verification_id
            or verification.amount_micro_usd != bucket.total_amount_micro_usd
            or verification.currency != bucket.currency
        ):
            raise ValueError("INVOICE_VERIFIED bucket does not match its invoice evidence")
    else:
        if (
            bucket.finality_state is not BillingFinalityState.DISPUTED
            or bucket.invoice_verification_id != verification.verification_id
        ):
            raise ValueError("mismatched invoice evidence must link a DISPUTED bucket")


class PodLease(VersionedPayload):
    """Ownership of a GPU pod by exactly one episode/job at a time (pilot rule)."""

    lease_id: UUID
    provider: Identifier
    pod_id: ShortText | None = Field(default=None, description="Unknown until create is confirmed")
    owned_tag: ShortText = Field(description="Pipeline ownership tag; janitor only touches these")
    client_token: ShortText = Field(description="Idempotent create token used for reconciliation")
    owner_episode_id: UUID
    owner_job_id: UUID | None = None
    reservation_id: UUID
    lease_state: LeaseState
    pod_state: PodState
    gpu_type: ShortText
    hourly_price_micro_usd: MicroUSD
    heartbeat_at: UtcDateTime | None = None
    lease_expires_at: UtcDateTime
    accrued_until: UtcDateTime | None = Field(
        default=None, description="Paid interval already allocated (each interval once)"
    )
    transferred_from: UUID | None = Field(
        default=None,
        description="Warm-pod handover: the lease this one replaced, else None",
    )
    created_at: UtcDateTime


class RenderRequest(VersionedPayload):
    """One paid shot-generation attempt. Required controls cannot be dropped."""

    render_id: UUID
    semantic_key: SemanticKey
    episode_id: UUID
    episode_number: PositiveInt
    shot_id: Identifier
    manifest_version: PositiveInt
    attempt_number: PositiveInt
    preset_id: Identifier
    tier: RenderTier
    required_controls: list[ControlKind] = Field(min_length=1)
    reference_asset_ids: list[UUID] = Field(default_factory=list)
    audio_asset_id: UUID | None = None
    identity_lock_id: UUID | None = None
    workflow_sha256: Sha256Hex
    seed: Count
    width: PositiveInt
    height: PositiveInt
    fps: PositiveInt
    duration_ms: PositiveMs
    reservation_id: UUID
    prompt_manifest_id: UUID | None = None
    prompt_manifest_sha256: Sha256Hex | None = None
    semantic_workflow_sha256: Sha256Hex | None = None
    prompt_text: str = Field(
        max_length=4000, description="Data passed to the graph, never executed"
    )
    negative_prompt_text: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _rules(self) -> RenderRequest:
        if (self.prompt_manifest_id is None) != (self.prompt_manifest_sha256 is None):
            raise ValueError("prompt manifest ID and hash must be provided together")
        prompt_bound = self.prompt_manifest_id is not None
        if prompt_bound != (self.semantic_workflow_sha256 is not None):
            raise ValueError(
                "semantic workflow hash is required exactly with the prompt manifest locator"
            )
        if self.attempt_number > 3:
            raise ValueError("maximum three paid generation attempts per shot")
        if self.duration_ms > 15_000:
            raise ValueError("render unit exceeds supported 15 seconds")
        if self.episode_number > 1 and self.identity_lock_id is None:
            raise ValueError("IMP-01: later-episode render requires the episode-one identity lock")
        if len(set(self.required_controls)) != len(self.required_controls):
            raise ValueError("duplicate required control")
        return self


def validate_render_request_prompt_binding(
    request: RenderRequest,
    *,
    prompt_manifest_id: UUID,
    prompt_manifest_sha256: str,
    semantic_workflow_sha256: str,
) -> None:
    """Fail closed unless the request matches its loaded manifest and pinned mapping."""
    if request.prompt_manifest_id is None or request.prompt_manifest_sha256 is None:
        raise ValueError("V2 render request requires a PromptManifest locator")
    if request.semantic_workflow_sha256 is None:
        raise ValueError("V2 render request requires a pinned semantic workflow hash")
    if (request.prompt_manifest_id, request.prompt_manifest_sha256) != (
        prompt_manifest_id,
        prompt_manifest_sha256,
    ):
        raise ValueError("render request does not match the exact loaded PromptManifest")
    if request.semantic_workflow_sha256 != semantic_workflow_sha256:
        raise ValueError("render request semantic workflow hash differs from the pinned mapping")


class OutputRef(ContractModel):
    """A provider output not yet copied into durable storage."""

    name: ShortText
    media_type: ShortText
    provider_ref: ShortText
    sha256: Sha256Hex | None = None
    size_bytes: Count | None = None
    complete: bool = Field(description="True only when the provider reports a finished file")


class ProviderOperation(VersionedPayload):
    """Durable record of one external call (submit → status → reconcile)."""

    operation_id: UUID
    provider: Identifier
    operation_kind: Identifier
    client_token: ShortText = Field(description="Idempotency token sent to the provider")
    request_sha256: Sha256Hex
    job_id: UUID | None = None
    reservation_id: UUID | None = None
    state: ProviderOperationState
    external_id: ShortText | None = None
    attempt: PositiveInt = 1
    submitted_at: UtcDateTime | None = None
    deadline_at: UtcDateTime


class ProviderOperationResult(VersionedPayload):
    """Result of submit/status/reconcile. UNKNOWN means reconcile, never blind resubmit."""

    operation_id: UUID
    state: ProviderOperationState
    external_id: ShortText | None = None
    outputs: list[OutputRef] = Field(default_factory=list)
    usage: list[UsageReceipt] = Field(default_factory=list)
    error_code: ShortText | None = None
    transient: bool = False
    retry_after_ms: DurationMs | None = None
    raw_response_key: ObjectKey | None = Field(default=None, description="Private raw response")
    provenance: Provenance

    @model_validator(mode="after")
    def _shape(self) -> ProviderOperationResult:
        if self.state is ProviderOperationState.SUCCEEDED and self.error_code:
            raise ValueError("a succeeded operation cannot carry an error code")
        if self.state is ProviderOperationState.FAILED and not self.error_code:
            raise ValueError("a failed operation must carry an error code")
        for receipt in self.usage:
            if (receipt.provenance is Provenance.FAKE_SYNTHETIC) != (
                self.provenance is Provenance.FAKE_SYNTHETIC
            ):
                raise ValueError("usage provenance must match the result provenance")
        return self

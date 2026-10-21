"""Budget reservation/usage, pod leases, render requests and provider operations."""

from __future__ import annotations

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
from microdrama.contracts.primitives import (
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

# Provider operation kinds that need no budget reservation. Empty in this build: every provider
# operation is treated as paid until the guardian adds a reviewed unmetered kind (V-24).
UNMETERED_OPERATION_KINDS: frozenset[str] = frozenset()


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
    prompt_text: str = Field(
        max_length=4000, description="Data passed to the graph, never executed"
    )
    negative_prompt_text: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _rules(self) -> RenderRequest:
        if self.attempt_number > 3:
            raise ValueError("maximum three paid generation attempts per shot")
        if self.duration_ms > 15_000:
            raise ValueError("render unit exceeds supported 15 seconds")
        if self.episode_number > 1 and self.identity_lock_id is None:
            raise ValueError("IMP-01: later-episode render requires the episode-one identity lock")
        if len(set(self.required_controls)) != len(self.required_controls):
            raise ValueError("duplicate required control")
        return self


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

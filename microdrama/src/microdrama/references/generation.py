"""Paid image/voice generation against the frozen ``GenerationProvider`` protocol (T011).

One paid generation = one real ``BudgetService.reserve()`` whose worst case fits
before anything is dispatched, followed by submit → (reconcile on ambiguity) →
status → fetch → byte verification, then the provider's own receipts settle the
hold. House rules honoured here:

- idempotency: deterministic request/operation ids, semantic budget keys and a
  client token equal to the semantic key, so a replay re-submits nothing (the
  provider answers from its cache and is never billed twice);
- an ambiguous submit is reconciled by token; only a reconciled NOT_FOUND ever
  makes resubmission safe (UNKNOWN/ambiguity is never retried blind);
- failed attempts keep whatever was billed; a call that never billed releases its
  hold (there is no spend to retain);
- a SUCCEEDED operation whose output bytes do not verify is a typed failure with
  the charge kept (the provider did the work; MD-008);
- no network code exists here: the provider is the injected T007 fake offline, and
  a live adapter may only be wired in after T031 records rights/cost evidence.

Durability is the caller's transaction: this module returns verified bytes; the
service registers the asset and the reference version together.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    OutputRef,
    PriceQuote,
    ProviderOperation,
    ProviderOperationResult,
)
from microdrama.contracts.enums import (
    AssetKind,
    BudgetCategory,
    BudgetScopeKind,
    Provenance,
    ProviderOperationState,
    QueueName,
    RightsSubjectKind,
)
from microdrama.contracts.errors import (
    MicrodramaError,
    NeedsReconciliation,
    ProviderError,
    RightsUncleared,
    ServiceUnavailable,
    TransientProviderError,
)
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.infra import Clock
from microdrama.contracts.media import MediaInfo
from microdrama.contracts.primitives import Sha256Hex
from microdrama.contracts.providers import (
    GenerationProvider,
    ImageRequest,
    VoiceRequest,
)
from microdrama.core.registry.rights import RightsRegistry
from microdrama.references.anchors import ref_id_for
from microdrama.references.config import ReferencesConfig
from microdrama.references.media import verify_generated
from microdrama.references.models import AnchorSpec

IMAGE_OPERATION = "references.image_anchor"
VOICE_ANCHOR_OPERATION = "references.voice_anchor"
VOICE_LINE_OPERATION = "references.voice_line"

_GPU_CATEGORY = BudgetCategory.GPU_GENERATION  # forced pairing: see config.py docstring
_VOICE_CATEGORY = BudgetCategory.REFERENCES_DIALOGUE


@dataclass(frozen=True)
class CallPlan:
    """One prospective paid step with concrete budget keys and worst case."""

    semantic_key: str
    provider_id: str
    operation_kind: str
    category: BudgetCategory
    price: PriceQuote
    units: int
    timeout_ms: int

    @property
    def worst_case_micro_usd(self) -> int:
        return self.price.unit_price_micro_usd * self.units

    @property
    def ceilings(self) -> ExposureCeilings:
        return ExposureCeilings(timeout_ms=self.timeout_ms, max_units=self.units)


@dataclass(frozen=True)
class GeneratedBytes:
    """One verified provider output, not yet registered durably."""

    data: bytes
    sha256: Sha256Hex
    media: MediaInfo | None
    external_id: str
    settled_micro_usd: int


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def image_call_plan(
    semantic_key: str, provider_id: str, config: ReferencesConfig
) -> CallPlan | None:
    """GPU-second-bounded reservation for one image anchor (the forced pairing).

    None when the image price is unknown: the step cannot dispatch (typed, zero spend).
    """
    price = config.image_price
    if price is None:
        return None
    units = max(1, _ceil_div(config.generation_timeout_ms, 1000))
    return CallPlan(
        semantic_key=semantic_key,
        provider_id=provider_id,
        operation_kind=IMAGE_OPERATION,
        category=_GPU_CATEGORY,
        price=price,
        units=units,
        timeout_ms=config.generation_timeout_ms,
    )


def voice_call_plan(
    semantic_key: str,
    provider_id: str,
    config: ReferencesConfig,
    *,
    characters: int,
    operation_kind: str = VOICE_LINE_OPERATION,
) -> CallPlan | None:
    """Character-bounded reservation for one synthesis (anchor sample or dialogue line).

    None when the voice price is unknown: the step cannot dispatch (typed, zero spend).
    """
    price = config.voice_price
    if price is None:
        return None
    units = max(1, _ceil_div(max(1, characters), 1000))
    return CallPlan(
        semantic_key=semantic_key,
        provider_id=provider_id,
        operation_kind=operation_kind,
        category=_VOICE_CATEGORY,
        price=price,
        units=units,
        timeout_ms=config.generation_timeout_ms,
    )


def check_rights(
    rights: RightsRegistry | None,
    *,
    rights_route_id: str,
    model_config_ref: str,
    now: datetime,
) -> str | None:
    """Fail-closed rights gate (MD-015/AT-13). Returns the licence hash when eligible.

    A missing route/registry configuration is a blocker, never a fabricated licence.
    """
    if rights is None:
        raise RightsUncleared(
            "no rights registry configured; eligible-route evidence is required before "
            "any paid reference generation",
            rights_route_id=rights_route_id,
        )
    decision = rights.evaluate(
        rights_route_id=rights_route_id,
        subjects=[
            (RightsSubjectKind.MODEL, model_config_ref),
            (RightsSubjectKind.MODEL_OUTPUT, model_config_ref),
        ],
        territories=["WORLDWIDE"],
        at=now,
    )
    if not decision.eligible:
        raise RightsUncleared(
            "reference generation route is not rights-cleared; the provider is blocked",
            rights_route_id=rights_route_id,
            status=decision.status.value,
            blockers=decision.blockers[:5],
        )
    return sha256_hex(f"{rights_route_id}|{model_config_ref}|{decision.status.value}".encode())


class GenerationAdapter:
    """Drives paid generations for the references service. Construct once per process."""

    def __init__(
        self,
        *,
        budget: BudgetService,
        clock: Clock,
        settings: Settings,
        config: ReferencesConfig,
    ) -> None:
        self._budget = budget
        self._clock = clock
        self._settings = settings
        self._config = config

    @property
    def provenance(self) -> Provenance:
        return (
            Provenance.FAKE_SYNTHETIC
            if self._settings.is_offline_mock
            else Provenance.LIVE_PROVIDER
        )

    def _now(self) -> datetime:
        return self._clock.now()

    # --- reservation -----------------------------------------------------------------------

    def reserve(self, plan: CallPlan, *, episode_id: UUID, expires_at: datetime):
        request = BudgetReservationRequest(
            request_id=ref_id_for("genreq", plan.semantic_key),
            semantic_key=plan.semantic_key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=episode_id,
            category=plan.category,
            queue=QueueName.PRODUCTION,
            provider=plan.provider_id,
            operation_kind=plan.operation_kind,
            price=plan.price,
            ceilings=plan.ceilings,
            worst_case_micro_usd=plan.worst_case_micro_usd,
            expires_at=expires_at,
        )
        return self._budget.reserve(request)

    # --- the provider discipline -------------------------------------------------------------

    def generate(
        self,
        provider: GenerationProvider,
        plan: CallPlan,
        request_builder: Callable[[UUID], ImageRequest | VoiceRequest],
        *,
        asset_kind: AssetKind,
        episode_id: UUID,
    ) -> GeneratedBytes:
        """Reserve, dispatch, poll, fetch and verify one output. Charges for failed
        attempts are kept; an attempt that never billed releases its hold."""
        now = self._now()
        reservation = self.reserve(
            plan,
            episode_id=episode_id,
            expires_at=now + timedelta(milliseconds=self._config.reservation_ttl_ms),
        )
        request = request_builder(reservation.id)
        billed = False
        try:
            result, settled = self._submit_and_poll(provider, plan, request, now)
            if result.usage:
                billed = True
            outputs = self._usable_outputs(result, plan)
            if len(outputs) != 1:
                raise ProviderError(
                    "generation did not return exactly one usable output",
                    operation_kind=plan.operation_kind,
                    outputs=len(outputs),
                )
            data = provider.fetch_output(outputs[0])
            media = verify_generated(data, kind=asset_kind)
            return GeneratedBytes(
                data=data,
                sha256=sha256_hex(data),
                media=media,
                external_id=result.external_id or "",
                settled_micro_usd=settled,
            )
        except MicrodramaError:
            if not billed:
                # The provider never billed this attempt: there is no spend to retain.
                try:
                    self._budget.release(
                        reservation.id,
                        reason=f"references generation never billed: {plan.semantic_key}",
                    )
                except MicrodramaError:
                    pass  # the typed error is the caller's answer
            raise

    def _operation(
        self,
        provider: GenerationProvider,
        plan: CallPlan,
        request: ImageRequest | VoiceRequest,
        now: datetime,
    ) -> ProviderOperation:
        return ProviderOperation(
            operation_id=ref_id_for("genop", plan.semantic_key),
            provider=provider.provider_id,
            operation_kind=plan.operation_kind,
            client_token=plan.semantic_key,
            request_sha256=canonical_hash(request),
            state=ProviderOperationState.PENDING_SUBMIT,
            deadline_at=now + timedelta(milliseconds=plan.timeout_ms),
        )

    def _submit_and_poll(
        self,
        provider: GenerationProvider,
        plan: CallPlan,
        request: ImageRequest | VoiceRequest,
        now: datetime,
    ) -> tuple[ProviderOperationResult, int]:
        """Submit with bounded transport attempts; reconcile ambiguity by token; poll to a
        terminal state. UNKNOWN is never resubmitted (typed NeedsReconciliation)."""
        operation = self._operation(provider, plan, request, now)
        result: ProviderOperationResult | None = None
        for _attempt in range(self._config.transport_attempts):
            try:
                result = provider.submit(operation, request)
                break
            except NeedsReconciliation:
                reconciled = provider.reconcile(operation)
                if reconciled.state is ProviderOperationState.NOT_FOUND:
                    continue  # proven never accepted: resubmission is safe
                result = reconciled
                break
            except TransientProviderError:
                continue
        if result is None:
            raise ServiceUnavailable(
                "generation provider did not accept the request within the transport budget",
                operation_kind=plan.operation_kind,
            )
        if result.state is ProviderOperationState.SUCCEEDED and not result.outputs:
            # A submit replay of an already-finished job answers from the provider's
            # cache without outputs: re-read them through status (never a re-submit).
            op = operation.model_copy(
                update={"external_id": result.external_id or operation.external_id}
            )
            result = provider.status(op)
        polled = self._poll(provider, operation, result, plan)
        settled = self._record_usage(polled)
        return polled, settled

    def _poll(
        self,
        provider: GenerationProvider,
        operation: ProviderOperation,
        first: ProviderOperationResult,
        plan: CallPlan,
    ) -> ProviderOperationResult:
        current = first
        for _poll in range(self._config.max_status_polls):
            state = current.state
            if state is ProviderOperationState.SUCCEEDED:
                return current
            if state is ProviderOperationState.FAILED:
                if current.error_code == "RIGHTS_UNCLEARED":
                    raise RightsUncleared(
                        "generation provider refused the request on rights grounds",
                        operation_kind=plan.operation_kind,
                    )
                raise ProviderError(
                    "generation provider reported a failed job",
                    operation_kind=plan.operation_kind,
                    error_code=current.error_code or "PROVIDER_FAILED",
                )
            if state is ProviderOperationState.UNKNOWN:
                raise NeedsReconciliation(
                    "generation outcome is unknown; reconcile before any resubmission",
                    operation_kind=plan.operation_kind,
                )
            op = operation.model_copy(
                update={"external_id": current.external_id or operation.external_id}
            )
            current = provider.status(op)
        raise ProviderError(
            "generation did not reach a terminal state within the poll budget",
            operation_kind=plan.operation_kind,
            last_state=current.state.value,
        )

    @staticmethod
    def _usable_outputs(result: ProviderOperationResult, plan: CallPlan) -> list[OutputRef]:
        if result.state is not ProviderOperationState.SUCCEEDED:
            raise ProviderError(
                "generation ended in a non-succeeded state",
                operation_kind=plan.operation_kind,
                state=result.state.value,
                error_code=result.error_code,
            )
        return [output for output in result.outputs if output.complete]

    def _record_usage(self, result: ProviderOperationResult) -> int:
        settled = 0
        for receipt in result.usage:
            charge = self._budget.record_usage(receipt)
            if not charge.replayed:
                settled += receipt.amount_micro_usd
        return settled


def build_image_request(
    spec: AnchorSpec,
    *,
    config: ReferencesConfig,
    rights_route_id: str,
    reservation_id: UUID,
    client_token: str,
) -> ImageRequest:
    return ImageRequest(
        request_id=ref_id_for("genreq", client_token),
        model_config_ref=config.image_model_config_ref,
        rights_route_id=rights_route_id,
        prompt_text=spec.prompt[:4000],
        reference_asset_ids=list(spec.lineage_asset_ids),
        width=spec.width,
        height=spec.height,
        seed=spec.seed,
        client_token=client_token,
        reservation_id=reservation_id,
    )


def build_voice_request(
    *,
    voice_id: str,
    line_id: str,
    text_th: str,
    config: ReferencesConfig,
    rights_route_id: str,
    reservation_id: UUID,
    client_token: str,
) -> VoiceRequest:
    return VoiceRequest(
        request_id=ref_id_for("genreq", client_token),
        model_config_ref=config.voice_model_config_ref,
        rights_route_id=rights_route_id,
        voice_id=voice_id,
        line_id=line_id,
        text_th=text_th,
        locale="th-TH",
        max_characters=config.max_line_characters,
        client_token=client_token,
        reservation_id=reservation_id,
    )


__all__ = [
    "CallPlan",
    "GeneratedBytes",
    "GenerationAdapter",
    "IMAGE_OPERATION",
    "VOICE_ANCHOR_OPERATION",
    "VOICE_LINE_OPERATION",
    "build_image_request",
    "build_voice_request",
    "check_rights",
    "image_call_plan",
    "voice_call_plan",
]

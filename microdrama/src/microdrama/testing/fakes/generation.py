"""Fake image/voice generation provider (T007): submit -> status -> reconcile -> fetch.

Jobs are keyed by ``client_token``; the external id is derived from it, so a repeated submit
returns the same external id and is never billed twice. Outputs are real small media files
(PNG via zlib/struct, WAV via ``wave``) generated from the request, so ``fetch_output`` bytes
decode. Scenarios:

- AMBIGUOUS_SUBMIT: the job is accepted but the response is lost (NeedsReconciliation);
  ``reconcile`` finds it by token with the same external id.
- NOT_ACCEPTED: the provider never accepted the job (NeedsReconciliation); ``reconcile``
  returns NOT_FOUND, which is the only state that makes resubmission safe.
- DENIED_RIGHTS: FAILED with error_code RIGHTS_UNCLEARED (non-transient).
- LATE_BILLING: first settlement is an ACCRUAL; the next status adds an ADJUSTMENT.
- PARTIAL_OUTPUT: status says SUCCEEDED but the output is marked complete=False and only the
  first half of the bytes is served; the advertised sha256 and size are the full file's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from microdrama.contracts.cost import (
    OutputRef,
    ProviderOperation,
    ProviderOperationResult,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    PriceUnit,
    Provenance,
    ProviderOperationState,
    ReceiptKind,
)
from microdrama.contracts.errors import NeedsReconciliation, NotFound
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.providers import ImageRequest, VoiceRequest
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    priced,
    stable_digest,
    synthetic_receipt,
)
from microdrama.testing.media import make_png_bytes, make_wav_bytes

MS_PER_CHARACTER = 40  # deterministic stand-in for speaking time: 40 ms per Thai character
MIN_VOICE_MS = 200
MAX_IMAGE_SIDE = 64
PROVIDER_ID = "fake-generation"


class GenerationScenario(StrEnum):
    HAPPY = "HAPPY"
    AMBIGUOUS_SUBMIT = "AMBIGUOUS_SUBMIT"
    NOT_ACCEPTED = "NOT_ACCEPTED"
    DENIED_RIGHTS = "DENIED_RIGHTS"
    LATE_BILLING = "LATE_BILLING"
    PARTIAL_OUTPUT = "PARTIAL_OUTPUT"


def voice_duration_ms(text_th: str) -> int:
    """Duration of the fake voice WAV, derived only from the Thai text length."""
    return max(MIN_VOICE_MS, MS_PER_CHARACTER * len(text_th))


@dataclass
class _Job:
    external_id: str
    client_token: str
    is_voice: bool
    scenario: GenerationScenario
    state: ProviderOperationState
    error_code: str | None = None
    status_calls: int = 0
    settled: bool = False
    late_adjusted: bool = False
    outputs: list[OutputRef] = field(default_factory=list)
    base_units: int = 1
    base_unit: PriceUnit = PriceUnit.IMAGE
    category: BudgetCategory = BudgetCategory.GPU_GENERATION
    reservation_id: UUID | None = None


class FakeGenerationProvider(FakeBase):
    provider_id: str = PROVIDER_ID
    default_scenario: ClassVar[GenerationScenario] = GenerationScenario.HAPPY

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        scenarios: tuple[GenerationScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self._jobs: dict[str, _Job] = {}
        self._served: dict[str, bytes] = {}

    @staticmethod
    def external_id_for(client_token: str) -> str:
        return f"fake-gen-{stable_digest(client_token)}"

    def _result(
        self,
        op: ProviderOperation,
        state: ProviderOperationState,
        *,
        external_id: str | None = None,
        outputs: list[OutputRef] | None = None,
        usage: list[UsageReceipt] | None = None,
        error_code: str | None = None,
    ) -> ProviderOperationResult:
        return ProviderOperationResult(
            operation_id=op.operation_id,
            state=state,
            external_id=external_id,
            outputs=outputs or [],
            usage=usage or [],
            error_code=error_code,
            transient=False,
            provenance=Provenance.FAKE_SYNTHETIC,
        )

    def _build_job(
        self, request: ImageRequest | VoiceRequest, scenario: GenerationScenario
    ) -> _Job:
        external_id = self.external_id_for(request.client_token)
        is_voice = isinstance(request, VoiceRequest)
        if is_voice:
            payload = make_wav_bytes(voice_duration_ms(request.text_th))
            name, media_type = f"{request.line_id}.wav", "audio/wav"
            base_unit, units = PriceUnit.CHARACTER_1K, -(-len(request.text_th) // 1000) or 1
            category = BudgetCategory.REFERENCES_DIALOGUE
        else:
            side_w = min(request.width, MAX_IMAGE_SIDE)
            side_h = min(request.height, MAX_IMAGE_SIDE)
            payload = make_png_bytes(side_w, side_h)
            name, media_type = f"{request.request_id}.png", "image/png"
            base_unit, units = PriceUnit.IMAGE, 1
            category = BudgetCategory.GPU_GENERATION
        served = (
            payload[: len(payload) // 2]
            if scenario is GenerationScenario.PARTIAL_OUTPUT
            else payload
        )
        provider_ref = f"fake-output/{external_id}/{name}"
        self._served[provider_ref] = served
        output = OutputRef(
            name=name,
            media_type=media_type,
            provider_ref=provider_ref,
            sha256=sha256_hex(payload),
            size_bytes=len(payload),
            complete=scenario is not GenerationScenario.PARTIAL_OUTPUT,
        )
        return _Job(
            external_id=external_id,
            client_token=request.client_token,
            is_voice=is_voice,
            scenario=scenario,
            state=ProviderOperationState.SUBMITTED,
            outputs=[output],
            base_units=units,
            base_unit=base_unit,
            category=category,
            reservation_id=request.reservation_id,
        )

    def submit(
        self, op: ProviderOperation, request: ImageRequest | VoiceRequest
    ) -> ProviderOperationResult:
        existing = self._jobs.get(self.external_id_for(request.client_token))
        if existing is not None:
            self._log_replay("submit", request.client_token)
            return self._result(
                op,
                existing.state,
                external_id=existing.external_id,
                error_code=existing.error_code,
            )
        step = self._step("submit", key=request.client_token)
        if step is GenerationScenario.NOT_ACCEPTED:
            raise NeedsReconciliation(
                "fake generation submit timed out; provider state unknown",
                client_token=request.client_token,
            )
        job = self._build_job(request, step)
        if step is GenerationScenario.DENIED_RIGHTS:
            job.state = ProviderOperationState.FAILED
            job.error_code = "RIGHTS_UNCLEARED"
            self._jobs[job.external_id] = job
            return self._result(op, ProviderOperationState.FAILED, error_code="RIGHTS_UNCLEARED")
        self._jobs[job.external_id] = job
        if step is GenerationScenario.AMBIGUOUS_SUBMIT:
            raise NeedsReconciliation(
                "fake generation accepted the job but the response was lost",
                client_token=request.client_token,
            )
        return self._result(op, ProviderOperationState.SUBMITTED, external_id=job.external_id)

    def _lookup(self, op: ProviderOperation) -> _Job | None:
        return self._jobs.get(op.external_id or self.external_id_for(op.client_token))

    def status(self, op: ProviderOperation) -> ProviderOperationResult:
        self._note("status", key=op.client_token)
        job = self._lookup(op)
        if job is None:
            return self._result(op, ProviderOperationState.NOT_FOUND)
        if job.state is ProviderOperationState.FAILED:
            return self._result(
                op, ProviderOperationState.FAILED, external_id=job.external_id,
                error_code=job.error_code,
            )  # fmt: skip
        job.status_calls += 1
        if job.status_calls == 1:
            job.state = ProviderOperationState.RUNNING
            return self._result(op, ProviderOperationState.RUNNING, external_id=job.external_id)

        job.state = ProviderOperationState.SUCCEEDED
        usage: list[UsageReceipt] = []
        base_amount = priced(job.base_unit, job.base_units)
        if not job.settled:
            job.settled = True
            kind = (
                ReceiptKind.ACCRUAL
                if job.scenario is GenerationScenario.LATE_BILLING
                else ReceiptKind.SETTLEMENT
            )
            usage.append(
                synthetic_receipt(
                    provider=self.provider_id,
                    provider_receipt_id=f"gen:{job.external_id}:base",
                    kind=kind,
                    category=job.category,
                    unit=job.base_unit,
                    units=job.base_units,
                    amount_micro_usd=base_amount,
                    observed_at=self.clock.now(),
                    reservation_id=job.reservation_id,
                )
            )
        elif job.scenario is GenerationScenario.LATE_BILLING and not job.late_adjusted:
            job.late_adjusted = True
            usage.append(
                synthetic_receipt(
                    provider=self.provider_id,
                    provider_receipt_id=f"gen:{job.external_id}:late-adjustment",
                    kind=ReceiptKind.ADJUSTMENT,
                    category=job.category,
                    unit=job.base_unit,
                    units=1,
                    amount_micro_usd=max(1, base_amount // 2),
                    observed_at=self.clock.now(),
                    reservation_id=job.reservation_id,
                )
            )
        self._bill(usage)
        return self._result(
            op,
            ProviderOperationState.SUCCEEDED,
            external_id=job.external_id,
            outputs=job.outputs,
            usage=usage,
        )

    def reconcile(self, op: ProviderOperation) -> ProviderOperationResult:
        self._note("reconcile", key=op.client_token)
        job = self._jobs.get(self.external_id_for(op.client_token))
        if job is None:
            return self._result(op, ProviderOperationState.NOT_FOUND)
        if job.state is ProviderOperationState.FAILED:
            return self._result(
                op, ProviderOperationState.FAILED, external_id=job.external_id,
                error_code=job.error_code,
            )  # fmt: skip
        if job.status_calls == 0:
            state = ProviderOperationState.SUBMITTED
        elif job.status_calls == 1:
            state = ProviderOperationState.RUNNING
        else:
            state = ProviderOperationState.SUCCEEDED
        outputs = job.outputs if state is ProviderOperationState.SUCCEEDED else []
        return self._result(op, state, external_id=job.external_id, outputs=outputs)

    def fetch_output(self, output: OutputRef) -> bytes:
        self._note("fetch_output", key=output.provider_ref)
        if output.provider_ref not in self._served:
            raise NotFound("fake generation output not found", provider_ref=output.provider_ref)
        return self._served[output.provider_ref]


__all__ = [
    "FakeGenerationProvider",
    "GenerationScenario",
    "MS_PER_CHARACTER",
    "voice_duration_ms",
]

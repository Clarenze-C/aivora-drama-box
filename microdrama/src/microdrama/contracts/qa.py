"""Observation-first QA payloads, findings and repair plans (SPEC §9, IMP-04/05).

``ObservationRequest`` (Pass A) is closed and has *no field* for intended
script, expected dialogue, plot outcome or writer rationale; extra fields are
rejected. Content-level leakage (e.g. a question quoting an intended line) is
checked by the QA input builder (T018) against the script.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    BudgetCategory,
    CheckFamily,
    CoverageStatus,
    Provenance,
    QAOutcome,
    QAPass,
    RepairTarget,
    RepairTrigger,
    Severity,
)
from microdrama.contracts.primitives import (
    BasisPoints,
    ContractModel,
    Count,
    DurationMs,
    EvidenceRef,
    Identifier,
    LocaleTag,
    MicroUSD,
    PositiveInt,
    PositiveMs,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)


class NeutralQuestion(ContractModel):
    question_id: Identifier
    text: str = Field(min_length=1, max_length=500)


class SamplingPlan(ContractModel):
    window_ms: PositiveMs = 2_000
    frames_per_window: PositiveInt = 2
    dense_ranges: list[tuple[DurationMs, DurationMs]] = Field(
        default_factory=list, description="Ranges needing dense local review (e.g. lip-sync)"
    )


class MediaUnderReview(ContractModel):
    asset_id: UUID
    asset_sha256: Sha256Hex
    duration_ms: PositiveMs


class ObservationRequest(VersionedPayload):
    """Pass A input: actual media + neutral questions only."""

    request_id: UUID
    episode_id: UUID
    media: list[MediaUnderReview] = Field(min_length=1)
    questions: list[NeutralQuestion] = Field(min_length=1)
    transcript_locale: LocaleTag = "th-TH"
    asr_vocabulary: list[ShortText] = Field(
        default_factory=list,
        description="Neutral vocabulary assistance (names/places); logged; never expected lines",
    )
    sampling: SamplingPlan = Field(default_factory=SamplingPlan)
    reservation_id: UUID | None = None


class TranscriptSegment(ContractModel):
    start_ms: DurationMs
    end_ms: DurationMs
    text: str = Field(max_length=2000)
    speaker_label: ShortText | None = None
    confidence_bp: BasisPoints | None = None


class Observation(ContractModel):
    observation_id: Identifier
    question_id: Identifier | None = None
    asset_id: UUID
    start_ms: DurationMs
    end_ms: DurationMs
    description: str = Field(min_length=1, max_length=4000)
    confidence_bp: BasisPoints | None = None


class CoverageWindow(ContractModel):
    asset_id: UUID
    check_family: CheckFamily
    start_ms: DurationMs
    end_ms: DurationMs
    status: CoverageStatus
    note: ShortText | None = None


class ObservationReport(VersionedPayload):
    """Frozen Pass A output. Persisted (immutable) with input hashes before Pass B."""

    report_id: UUID
    request_id: UUID
    request_sha256: Sha256Hex
    episode_id: UUID
    media_sha256: list[Sha256Hex] = Field(min_length=1)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(min_length=1)
    model_config_ref: ShortText
    provenance: Provenance
    frozen_at: UtcDateTime


class ComparisonRequest(VersionedPayload):
    """Pass B input: references to the frozen report plus intended script/canon/anchors."""

    request_id: UUID
    episode_id: UUID
    observation_report_id: UUID
    observation_report_sha256: Sha256Hex
    script_id: UUID
    script_version: PositiveInt
    script_sha256: Sha256Hex
    canon_version: Count
    canon_sha256: Sha256Hex
    identity_lock_id: UUID | None = None
    acceptance_criteria: list[ShortText] = Field(default_factory=list)
    reservation_id: UUID | None = None


class QAFinding(VersionedPayload):
    """Timecoded finding. Unchecked coverage can never be a PASS."""

    finding_id: UUID
    episode_id: UUID
    asset_id: UUID
    start_ms: DurationMs
    end_ms: DurationMs
    check_id: Identifier
    check_family: CheckFamily
    source_pass: QAPass
    expected: str | None = Field(default=None, max_length=2000)
    observed: str | None = Field(default=None, max_length=2000)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    severity: Severity
    confidence_bp: BasisPoints | None = None
    coverage: CoverageStatus
    outcome: QAOutcome
    repair_targets: list[RepairTarget] = Field(default_factory=list)
    repair_dependency_ids: list[Identifier] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def _honest(self) -> QAFinding:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        if self.coverage in (CoverageStatus.UNSAMPLED, CoverageStatus.UNAVAILABLE):
            if self.outcome is not QAOutcome.UNKNOWN:
                raise ValueError("unsampled/unavailable coverage must be UNKNOWN, never PASS")
        if self.outcome is QAOutcome.PASS and self.coverage is not CoverageStatus.CHECKED:
            raise ValueError("PASS requires CHECKED coverage")
        if self.outcome is QAOutcome.REPAIRABLE and not self.repair_targets:
            raise ValueError("REPAIRABLE findings must name repair targets")
        return self

    @property
    def blocks_release(self) -> bool:
        if self.outcome is QAOutcome.PASS:
            return False
        return self.severity is Severity.CRITICAL or self.outcome is QAOutcome.BLOCKED


class RepairStep(ContractModel):
    step_id: Identifier
    target: RepairTarget
    target_ids: list[Identifier] = Field(min_length=1)
    action: ShortText
    category: BudgetCategory
    estimated_cost_micro_usd: MicroUSD
    invalidates_asset_ids: list[UUID] = Field(default_factory=list)
    recheck_check_ids: list[Identifier] = Field(default_factory=list)
    consumes_shot_attempt: bool = False

    @model_validator(mode="after")
    def _attempt(self) -> RepairStep:
        if self.target is RepairTarget.SHOT and not self.consumes_shot_attempt:
            raise ValueError("shot re-renders (incl. tier promotion) consume an ordinary attempt")
        return self


class RepairPlan(VersionedPayload):
    plan_id: UUID
    episode_id: UUID
    trigger: RepairTrigger
    finding_ids: list[UUID] = Field(default_factory=list)
    feedback_event_ids: list[UUID] = Field(default_factory=list)
    round_number: PositiveInt
    steps: list[RepairStep] = Field(min_length=1)
    total_estimated_micro_usd: MicroUSD
    remaining_budget_micro_usd: MicroUSD
    returns_to_gate2: bool = True
    created_at: UtcDateTime

    @model_validator(mode="after")
    def _consistent(self) -> RepairPlan:
        if self.trigger is RepairTrigger.QA_FINDING and not self.finding_ids:
            raise ValueError("QA-triggered plans must reference findings")
        if self.trigger is RepairTrigger.HUMAN_FEEDBACK and not self.feedback_event_ids:
            raise ValueError("feedback-triggered plans must reference feedback events")
        if self.trigger is RepairTrigger.QA_FINDING and self.round_number > 2:
            raise ValueError("maximum two automatic final-QA repair rounds")
        if sum(s.estimated_cost_micro_usd for s in self.steps) != self.total_estimated_micro_usd:
            raise ValueError("total_estimated_micro_usd must equal the sum of step estimates")
        if self.total_estimated_micro_usd > self.remaining_budget_micro_usd:
            raise ValueError("repair plan exceeds remaining episode budget")
        if not self.returns_to_gate2:
            raise ValueError("changed final media must return to Gate 2")
        return self

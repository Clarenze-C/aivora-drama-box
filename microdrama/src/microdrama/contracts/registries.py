"""Rights and render-preset registry records (contract 1.1.0, additive).

Registry records hold *evidence*; importing a policy or a vendor claim does not
make a route eligible. Unknown rights block exactly like ineligible rights. A
preset stays disabled until measured, reproducible benchmark evidence exists.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    ControlKind,
    DisclosureKind,
    RenderTier,
    RightsStatus,
    RightsSubjectKind,
)
from microdrama.contracts.primitives import (
    BasisPoints,
    ContractModel,
    EvidenceRef,
    Identifier,
    MicroUSD,
    PositiveInt,
    PositiveMs,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)


class RightsRecord(VersionedPayload):
    record_id: UUID
    rights_route_id: Identifier
    version: PositiveInt
    subject_kind: RightsSubjectKind
    subject_ref: ShortText
    territories: list[str] = Field(default_factory=list, description="Empty = unknown")
    commercial_use: bool | None = Field(default=None, description="None = unknown (blocks)")
    output_release_allowed: bool | None = Field(default=None, description="None = unknown (blocks)")
    required_disclosures: list[DisclosureKind] = Field(default_factory=list)
    expires_at: UtcDateTime | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    status: RightsStatus
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _eligible_needs_evidence(self) -> RightsRecord:
        for t in self.territories:
            if t != "WORLDWIDE" and not re.fullmatch(r"[A-Z]{2}", t):
                raise ValueError(f"invalid territory {t!r}")
        if self.status is RightsStatus.ELIGIBLE:
            if not (self.commercial_use and self.output_release_allowed):
                raise ValueError("ELIGIBLE requires confirmed commercial use and output release")
            if not self.evidence or not self.territories:
                raise ValueError("ELIGIBLE requires evidence and named territories")
            if self.expires_at is not None and self.expires_at <= self.recorded_at:
                raise ValueError("a record that is already expired cannot be ELIGIBLE")
        return self


class PresetMeasurements(ContractModel):
    """Measured on the intended settings. Text-only speed results never qualify."""

    sample_count: PositiveInt
    cold_start_ms: PositiveMs
    warm_full_job_ms: PositiveMs
    cost_per_accepted_shot_micro_usd: MicroUSD
    cost_per_retained_second_micro_usd: MicroUSD
    downstream_repair_cost_micro_usd: MicroUSD = 0
    acceptance_bp_by_shot_class: dict[Identifier, BasisPoints] = Field(min_length=1)
    critical_quality_pass_bp: BasisPoints
    measured_with_references: bool = Field(
        description="Benchmarked with the reference controls it claims"
    )
    measured_at: UtcDateTime


class PresetRecord(VersionedPayload):
    preset_id: Identifier
    version: PositiveInt
    tier: RenderTier
    workflow_sha256: Sha256Hex
    base_model_sha256: Sha256Hex | None = None
    lora_sha256: list[Sha256Hex] = Field(default_factory=list)
    node_pack_sha256: dict[Identifier, Sha256Hex] = Field(default_factory=dict)
    model_mode: Identifier
    gpu_type: ShortText
    min_vram_gb: PositiveInt
    host_ram_gb: PositiveInt
    precision: Identifier
    width: PositiveInt
    height: PositiveInt
    frames: PositiveInt
    fps: PositiveInt
    steps: PositiveInt
    attention_backend: Identifier
    supported_controls: list[ControlKind] = Field(min_length=1)
    supports_thai_dialogue: bool | None = Field(default=None, description="None = unknown")
    rights_route_id: Identifier | None = None
    max_attempt_cost_micro_usd: MicroUSD | None = None
    measured: PresetMeasurements | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    enabled: bool = False
    notes: list[ShortText] = Field(default_factory=list)
    included_speedups: list[Identifier] = Field(
        default_factory=list, description="Speedups already in the measurement; never stack again"
    )

    @model_validator(mode="after")
    def _enabled_needs_measurement(self) -> PresetRecord:
        if len(set(self.supported_controls)) != len(self.supported_controls):
            raise ValueError("duplicate supported control")
        if self.enabled:
            if self.measured is None or not self.evidence:
                raise ValueError("a preset stays disabled until measured benchmark evidence exists")
            if self.rights_route_id is None:
                raise ValueError("an enabled preset needs a rights route")
            references = {
                ControlKind.CHARACTER_REFERENCE,
                ControlKind.FIRST_FRAME,
                ControlKind.VOICE_REFERENCE,
            } & set(self.supported_controls)
            if references and not self.measured.measured_with_references:
                raise ValueError("reference-capable presets must be benchmarked with references")
            dialogue = {ControlKind.VOICE_REFERENCE, ControlKind.AUDIO_DRIVEN_LIPSYNC}
            if dialogue & set(self.supported_controls) and self.supports_thai_dialogue is not True:
                raise ValueError("an enabled dialogue preset needs measured Thai dialogue support")
            if (
                self.measured.critical_quality_pass_bp == 0
                or 0 in self.measured.acceptance_bp_by_shot_class.values()
            ):
                raise ValueError("an enabled preset needs non-zero measured quality and acceptance")
        return self

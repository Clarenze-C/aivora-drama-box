"""Module-local payloads for the editing lane (T015).

Contracts are frozen at 1.5.0 and this module adds no cross-module schema: everything
extends ``ContractModel`` the same way the story/references lanes' payloads do. A
promotion proposal is recorded in evidence/T015.md if a later lane needs them
cross-module (T016/T017 are the likely consumers).

Rules encoded here (SPEC §9, task packet T015):
- Findings are typed and always surfaced: the wrong-audio defect appears as a
  ``caption.audio_content_mismatch`` finding, never as a silently "fixed" caption.
- Unknowns stay typed: an unavailable speech observation is an uncertainty note,
  a missing Thai font is a finding plus a skipped burn, never a green claim.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from microdrama.contracts.enums import QAOutcome, Severity
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    DurationMs,
    Identifier,
    MicroUSD,
    Sha256Hex,
    ShortText,
)


class AssemblyStatus(StrEnum):
    """Typed outcome of one ``assemble_episode`` call (never a silent failure)."""

    ASSEMBLED = "ASSEMBLED"  # new EDL + exports rendered and checked
    REPLAYED = "REPLAYED"  # identical EDL and outputs already exist; nothing re-exported


class EditingFinding(ContractModel):
    """One defect surfaced by the assembly. Never hidden behind a green score.

    Known codes (stable): ``caption.audio_content_mismatch`` (the audio for a line
    does not speak the intended text — the cue carries what was actually spoken and
    the mismatch is reported), ``edit.duration_drift`` (measured audio duration
    differs from the script's recorded actual duration), ``font.thai_unavailable``
    (no installed font covers the caption text; the burn is skipped, not faked).
    """

    code: Identifier
    severity: Severity
    detail: str = Field(min_length=1, max_length=1000)
    line_id: Identifier | None = None
    cue_id: Identifier | None = None
    asset_id: UUID | None = None


class TechnicalCheck(ContractModel):
    """One technical inspection over the actual exported media or the EDL.

    ``outcome`` uses the contract QA outcomes: a check that could not run (no font,
    no observation) is ``UNKNOWN``, never ``PASS``.
    """

    check_id: Identifier
    outcome: QAOutcome
    detail: str = Field(min_length=1, max_length=500)


class FontResolution(ContractModel):
    """Result of the Thai-safe font search. Deterministic for the same config."""

    family: ShortText
    path: str | None = Field(default=None, description="None when no candidate covered the text")
    coverage_ok: bool
    searched: Count = Field(description="How many candidate font files were inspected")


class ObservedSpeech(ContractModel):
    """What was actually spoken in one audio asset, as observed from the media.

    In OFFLINE_MOCK this comes from the T007 fixture truth; the ASR-backed observer
    arrives with T017. The text is an observation, never the intended line.
    """

    text_th: str = Field(min_length=1, max_length=2000)
    speaker_id: str | None = None


class AssemblyOutcome(ContractModel):
    """What ``assemble_episode`` returns. Failed attempts keep their spend."""

    episode_id: UUID
    edl_id: UUID
    edl_version: Count
    status: AssemblyStatus
    duration_ms: DurationMs
    clean_asset_id: UUID
    clean_sha256: Sha256Hex
    burned_asset_id: UUID | None = None
    burned_sha256: Sha256Hex | None = None
    caption_track_ids: list[UUID] = Field(default_factory=list)
    burned_caption_track_id: UUID | None = None
    findings: list[EditingFinding] = Field(default_factory=list)
    checks: list[TechnicalCheck] = Field(default_factory=list)
    invalidated_cue_ids: list[Identifier] = Field(default_factory=list)
    settled_micro_usd: MicroUSD = 0
    reservation_ids: list[UUID] = Field(default_factory=list)
    uncertainty_notes: list[ShortText] = Field(default_factory=list)


__all__ = [
    "AssemblyOutcome",
    "AssemblyStatus",
    "EditingFinding",
    "FontResolution",
    "ObservedSpeech",
    "TechnicalCheck",
]

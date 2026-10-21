"""Module-local payloads for the technical/audio/visual QA lane (T017).

Contracts are frozen at 1.5.0 and this module adds no cross-module schema: everything
extends ``ContractModel`` the same way the editing lane's payloads do (the promotion
proposal lives in evidence/T017.md). The frozen ``QAFinding`` contract carries the
honesty rules — UNSAMPLED/UNAVAILABLE coverage is UNKNOWN, never PASS — and
``build_finding`` derives deterministic finding ids so an identical run replays
instead of duplicating rows.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import Field

from microdrama.contracts.enums import (
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    QAPass,
    RepairTarget,
    Severity,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.primitives import (
    ContractModel,
    DurationMs,
    Identifier,
    MicroUSD,
    Sha256Hex,
    ShortText,
)
from microdrama.contracts.qa import CoverageWindow, QAFinding, TranscriptSegment
from microdrama.contracts.season import CriticalTerm

QA_NAMESPACE = uuid5(UUID(int=0), "https://microdrama.invalid/ns/qa-technical")


class QARunStatus(StrEnum):
    """Typed outcome of one technical QA run (never a silent failure)."""

    COMPLETED = "COMPLETED"
    REPLAYED = "REPLAYED"


class ObservedIdentity(ContractModel):
    """One visible identity observed in the media (offline: fixture truth)."""

    start_ms: DurationMs
    end_ms: DurationMs
    character_id: Identifier


class MediaObservation(ContractModel):
    """What the observation step actually saw in the media — never the script.

    ``source_label`` records where the observation came from: ``fixture-truth`` (the
    T007 registry keyed by the media's own sha256, the offline ASR/vision stand-in) or
    ``unregistered`` (no observation source knows this media; every dependent finding
    is a typed unknown, and nothing turns green).
    """

    segments: list[TranscriptSegment] = Field(default_factory=list)
    identities: list[ObservedIdentity] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(min_length=1)
    provenance: Provenance
    source_label: ShortText
    fixture_id: ShortText | None = None
    model_ref: ShortText = "offline-fixture-observer-v1"


class LineAlignment(ContractModel):
    """One script line aligned against the observed transcript.

    ``segment`` is what the media actually says for this line (None when no observed
    segment matches). Expected values live on the line; observed values live on the
    segment — they are never copied across.
    """

    line_id: Identifier
    speaker_character_id: Identifier
    text_th: str = Field(min_length=1, max_length=2000)
    critical_terms: list[CriticalTerm] = Field(default_factory=list)
    segment: TranscriptSegment | None = None
    ratio: float = Field(ge=0.0, le=1.0)


class TechnicalQARun(ContractModel):
    """What one ``run_episode_qa`` call returns. Failed attempts keep their spend."""

    episode_id: UUID
    asset_id: UUID
    asset_sha256: Sha256Hex
    run_key: str = Field(min_length=8, max_length=64)
    qa_cycle: int = Field(ge=1)
    status: QARunStatus
    duration_ms: DurationMs
    findings: list[QAFinding] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(default_factory=list)
    all_checks_green: bool
    blocking_check_ids: list[Identifier] = Field(default_factory=list)
    unknown_check_ids: list[Identifier] = Field(default_factory=list)
    reservation_id: UUID | None = None
    settled_micro_usd: MicroUSD = 0
    notes: list[ShortText] = Field(default_factory=list)


class QAReportView(ContractModel):
    """Persisted QA state for an episode (T018/T030 consume this read-only view)."""

    episode_id: UUID
    cycles: list[int] = Field(default_factory=list)
    findings: list[QAFinding] = Field(default_factory=list)
    critical_check_ids: list[Identifier] = Field(default_factory=list)
    all_checks_green: bool = False
    blocking_check_ids: list[Identifier] = Field(default_factory=list)
    unknown_check_ids: list[Identifier] = Field(default_factory=list)


def build_finding(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    start_ms: int,
    end_ms: int,
    check_id: str,
    family: CheckFamily,
    severity: Severity,
    outcome: QAOutcome,
    coverage: CoverageStatus,
    expected: str | None,
    observed: str | None,
    evidence_source: EvidenceSource,
    evidence_ref: str,
    evidence_note: str,
    provenance: Provenance,
    repair_targets: list[RepairTarget] | None = None,
) -> QAFinding:
    """Build one finding with a deterministic id derived from the run and its content.

    The id binds the run key (episode + asset sha + script sha + config fingerprint),
    so identical runs replay onto the same rows and any change in media, script or
    config mints new findings instead of silently overwriting old ones.
    """
    if outcome is QAOutcome.REPAIRABLE and not repair_targets:
        raise ValueError(f"REPAIRABLE finding {check_id} must name repair targets")
    body = {
        "run_key": run_key,
        "check_id": check_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "expected": expected,
        "observed": observed,
        "coverage": coverage.value,
    }
    return QAFinding(
        finding_id=uuid5(QA_NAMESPACE, f"{run_key}:{canonical_hash(body)}"),
        episode_id=episode_id,
        asset_id=asset_id,
        start_ms=start_ms,
        end_ms=max(start_ms, end_ms),
        check_id=check_id,
        check_family=family,
        source_pass=QAPass.TECHNICAL,
        expected=expected,
        observed=observed,
        evidence=[
            {
                "source": evidence_source,
                "ref": evidence_ref,
                "sha256": None,
                "note": evidence_note[:2000],
                "recorded_at": None,
            }
        ],
        severity=severity,
        confidence_bp=None,
        coverage=coverage,
        outcome=outcome,
        repair_targets=repair_targets or [],
        repair_dependency_ids=[],
        provenance=provenance,
    )


__all__ = [
    "QA_NAMESPACE",
    "QARunStatus",
    "QAReportView",
    "LineAlignment",
    "MediaObservation",
    "ObservedIdentity",
    "TechnicalQARun",
    "build_finding",
]

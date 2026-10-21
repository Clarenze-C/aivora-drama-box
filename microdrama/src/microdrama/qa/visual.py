"""Visual QA: identity/prop checks over observed identities (T017).

The identity check compares who the media actually shows in each aligned speech
window (identities come from the observation seam — fixture truth offline) with the
speaker the script intends. A swapped identity is CRITICAL and repairs the shot, not
the caption: no caption edit may paper over the wrong person being on screen.

Prop verification has no offline observation source, so it is a typed UNKNOWN with
UNAVAILABLE coverage — known unavailable coverage is UNKNOWN, never PASS (SPEC §9),
and a real labeled visual evaluation is T031 evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from microdrama.contracts.enums import (
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    RepairTarget,
    Severity,
)
from microdrama.contracts.qa import QAFinding
from microdrama.qa.audio import SOURCE_FIXTURE
from microdrama.qa.coverage import coverage_for
from microdrama.qa.models import LineAlignment, MediaObservation, build_finding

PROP_NOTE = (
    "no prop observation source configured offline; prop presence is UNAVAILABLE, not verified"
)


def identity_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    asset_sha256: str,
    alignments: Sequence[LineAlignment],
    observation: MediaObservation,
) -> list[QAFinding]:
    """visual_identity.match per aligned line: observed identities vs intended speaker."""
    fixture = observation.source_label == SOURCE_FIXTURE
    evidence_note = (
        f"fixture-truth:{observation.fixture_id} (identities observed in the actual media)"
        if fixture
        else "no observation source registered; identities were not observed"
    )
    out: list[QAFinding] = []

    def add(**kwargs: object) -> None:
        out.append(
            build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                evidence_source=(
                    EvidenceSource.FAKE_FIXTURE if fixture else EvidenceSource.MEASURED_BENCHMARK
                ),
                evidence_ref=f"identity:{asset_sha256[:16]}",
                evidence_note=evidence_note,
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                **kwargs,  # type: ignore[arg-type]
            )
        )

    for alignment in alignments:
        segment = alignment.segment
        if segment is None:
            continue  # no speech alignment: identity cannot be attributed to this line
        start, end = segment.start_ms, segment.end_ms
        status = coverage_for(observation.coverage, CheckFamily.VISUAL_IDENTITY, start, end)
        visible = [
            identity
            for identity in observation.identities
            if identity.start_ms < end and start < identity.end_ms
        ]
        if not visible:
            add(
                check_id="visual_identity.match",
                family=CheckFamily.VISUAL_IDENTITY,
                start_ms=start,
                end_ms=end,
                severity=Severity.MAJOR,
                outcome=QAOutcome.UNKNOWN,
                coverage=status,
                expected=alignment.speaker_character_id,
                observed="no identity observed in range",
            )
            continue
        labels = [identity.character_id for identity in visible]
        mismatch = any(label != alignment.speaker_character_id for label in labels)
        if mismatch:
            add(
                check_id="visual_identity.match",
                family=CheckFamily.VISUAL_IDENTITY,
                start_ms=start,
                end_ms=end,
                severity=Severity.CRITICAL,
                outcome=QAOutcome.REPAIRABLE,
                coverage=status,
                expected=alignment.speaker_character_id,
                observed=", ".join(labels),
                repair_targets=[RepairTarget.SHOT],
            )
        else:
            add(
                check_id="visual_identity.match",
                family=CheckFamily.VISUAL_IDENTITY,
                start_ms=start,
                end_ms=end,
                severity=Severity.INFO,
                outcome=(QAOutcome.PASS if status is CoverageStatus.CHECKED else QAOutcome.UNKNOWN),
                coverage=status,
                expected=alignment.speaker_character_id,
                observed=", ".join(labels),
            )
    return out


def prop_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    duration_ms: int,
) -> list[QAFinding]:
    """visual_identity.prop_match: typed UNKNOWN — there is no offline prop observer."""
    return [
        build_finding(
            run_key=run_key,
            episode_id=episode_id,
            asset_id=asset_id,
            start_ms=0,
            end_ms=duration_ms,
            check_id="visual_identity.prop_match",
            family=CheckFamily.VISUAL_IDENTITY,
            severity=Severity.MAJOR,
            outcome=QAOutcome.UNKNOWN,
            coverage=CoverageStatus.UNAVAILABLE,
            expected=None,
            observed=PROP_NOTE,
            evidence_source=EvidenceSource.MEASURED_BENCHMARK,
            evidence_ref=f"props:{asset_id.hex[:16]}",
            evidence_note="no prop observation configured; this check never passes offline",
            provenance=Provenance.DERIVED_LOCAL,
        )
    ]


__all__ = ["PROP_NOTE", "identity_findings", "prop_findings"]

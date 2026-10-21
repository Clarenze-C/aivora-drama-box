"""Audio/ASR QA: the observation seam and the speech checks (T017).

The seam is ``MediaObserver.observe(...)``: it looks at the ACTUAL staged media file
and reports what is there — segments (speech), identities and coverage — and never
receives the script. Offline (OFFLINE_MOCK, the only mode this lane ships) the
observer is ``OfflineMediaObserver`` backed by the T007 fixture-truth registry keyed
by the media's own sha256: tone fixtures cannot carry Thai speech, so the registry is
the declared truth of what the fixture contains, and every finding derived from it
carries that provenance (``fixture-truth``). Media the registry does not know yields
an UNAVAILABLE observation and typed UNKNOWN findings — a pristine script on the
expected side can never turn that green (the media is the only evidence).

``as_speech_observer`` adapts the observer to T015's ``SpeechObserver`` protocol so
the editing lane's assembly can consume the same seam.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    RepairTarget,
    Severity,
)
from microdrama.contracts.errors import EffectDenied
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.media import CaptionCue
from microdrama.contracts.qa import CoverageWindow, QAFinding, TranscriptSegment
from microdrama.contracts.season import Script
from microdrama.qa.coverage import coverage_for, partition_coverage
from microdrama.qa.models import (
    LineAlignment,
    MediaObservation,
    ObservedIdentity,
    build_finding,
)
from microdrama.testing.media import FixtureTruthRegistry

OBSERVER_MODEL_REF = "offline-fixture-observer-v1"
SOURCE_FIXTURE = "fixture-truth"
SOURCE_UNREGISTERED = "unregistered"
MISMATCH_CODE = "caption.audio_content_mismatch"  # stable id shared with T015


class MediaObserver(Protocol):
    """Observes one staged media file. The script is never an input here."""

    def observe(
        self,
        *,
        asset_id: UUID,
        asset_sha256: str,
        media_path: Path,
        duration_ms: int,
    ) -> MediaObservation: ...


class OfflineMediaObserver:
    """The OFFLINE_MOCK observer: declared fixture truth, keyed by the media's sha256.

    This is the offline ASR/vision stand-in, not a quality claim: a real labeled-Thai
    ASR evaluation is T031 evidence. Refuses to run outside OFFLINE_MOCK.
    """

    def __init__(self, registry: FixtureTruthRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    def observe(
        self,
        *,
        asset_id: UUID,
        asset_sha256: str,
        media_path: Path,
        duration_ms: int,
    ) -> MediaObservation:
        if not self._settings.is_offline_mock:
            raise EffectDenied(
                "the offline fixture observer runs only in OFFLINE_MOCK; a live ASR "
                "provider must be configured for other execution modes"
            )
        actual_sha = file_sha256(str(media_path))
        if actual_sha != asset_sha256:
            return self._unregistered(
                asset_id,
                duration_ms,
                f"staged bytes hash to {actual_sha[:12]}, not the registered asset sha",
            )
        truth = self._registry.get(asset_sha256)
        if truth is None:
            return self._unregistered(
                asset_id, duration_ms, "no fixture truth registered for this sha256"
            )
        covered = list(truth.covered_ranges_ms)
        segments = [
            TranscriptSegment(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                text=s.text_th,
                speaker_label=s.speaker_id,
                confidence_bp=None,
            )
            for s in truth.spoken
            if truth.has_audio and any(lo <= s.start_ms and s.end_ms <= hi for lo, hi in covered)
        ]
        identities = [
            ObservedIdentity(start_ms=i.start_ms, end_ms=i.end_ms, character_id=i.character_id)
            for i in truth.identities
            if truth.has_video and any(lo <= i.start_ms < hi for lo, hi in covered)
        ]
        coverage: list[CoverageWindow] = partition_coverage(
            asset_id,
            CheckFamily.ASR,
            truth.duration_ms,
            covered if truth.has_audio else (),
            outside=CoverageStatus.UNSAMPLED if truth.has_audio else CoverageStatus.UNAVAILABLE,
            note=None if truth.has_audio else "no audio stream in media",
        )
        coverage += partition_coverage(
            asset_id,
            CheckFamily.VISUAL_IDENTITY,
            truth.duration_ms,
            covered if truth.has_video else (),
            outside=CoverageStatus.UNSAMPLED if truth.has_video else CoverageStatus.UNAVAILABLE,
            note=None if truth.has_video else "no video stream in media",
        )
        return MediaObservation(
            segments=segments,
            identities=identities,
            coverage=coverage,
            provenance=Provenance.ORIGINAL_FIXTURE,
            source_label=SOURCE_FIXTURE,
            fixture_id=truth.fixture_id,
            model_ref=OBSERVER_MODEL_REF,
        )

    def _unregistered(self, asset_id: UUID, duration_ms: int, reason: str) -> MediaObservation:
        coverage = [
            window
            for family in (CheckFamily.ASR, CheckFamily.VISUAL_IDENTITY)
            for window in partition_coverage(
                asset_id,
                family,
                max(duration_ms, 1),
                (),
                outside=CoverageStatus.UNAVAILABLE,
                note=reason,
            )
        ]
        return MediaObservation(
            coverage=coverage,
            provenance=Provenance.DERIVED_LOCAL,
            source_label=SOURCE_UNREGISTERED,
            fixture_id=None,
            model_ref=OBSERVER_MODEL_REF,
        )


class SpeechObserverAdapter:
    """Adapts a MediaObserver to T015's SpeechObserver (per-audio-asset observation).

    ``bytes_for_sha`` resolves an audio asset's bytes from its sha256 (composition
    root wires the assets-table lookup plus object-store read); staging happens on a
    tmp path, as everywhere in this pipeline.
    """

    def __init__(
        self, observer: OfflineMediaObserver, bytes_for_sha: Callable[[str], bytes]
    ) -> None:
        self._observer = observer
        self._bytes_for_sha = bytes_for_sha

    def observe(self, audio_sha256: str):  # -> ObservedSpeech | None (editing models)
        from tempfile import TemporaryDirectory

        from microdrama.editing.models import ObservedSpeech

        with TemporaryDirectory(prefix="md-qa-speech-") as tmp:
            staged = Path(tmp) / "audio.bin"
            staged.write_bytes(self._bytes_for_sha(audio_sha256))
            observation = self._observer.observe(
                asset_id=UUID(int=0),
                asset_sha256=audio_sha256,
                media_path=staged,
                duration_ms=1,
            )
            if observation.source_label != SOURCE_FIXTURE or not observation.segments:
                return None
            first = observation.segments[0]
            return ObservedSpeech(text_th=first.text, speaker_id=first.speaker_label)


def as_speech_observer(
    observer: OfflineMediaObserver, bytes_for_sha: Callable[[str], bytes]
) -> SpeechObserverAdapter:
    """T015's editing assembly can consume this adapter as its SpeechObserver."""
    return SpeechObserverAdapter(observer, bytes_for_sha)


# --- alignment ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return "".join(text.split())


def align_best[T](items: Sequence[T], text: str, key: Callable[[T], str]) -> tuple[T | None, float]:
    """Best text-similarity match (ratio in [0, 1]); observed vs expected text only."""
    best: T | None = None
    best_ratio = 0.0
    needle = _norm(text)
    for item in items:
        ratio = difflib.SequenceMatcher(None, needle, _norm(key(item)), autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return best, best_ratio


def align_lines(
    script: Script, observation: MediaObservation, *, align_min_ratio: float
) -> list[LineAlignment]:
    """Align each script line against observed segments by text similarity."""
    alignments: list[LineAlignment] = []
    for scene in script.scenes:
        for line in scene.lines:
            segment, ratio = align_best(
                observation.segments, line.text_th, key=lambda seg: seg.text
            )
            alignments.append(
                LineAlignment(
                    line_id=line.line_id,
                    speaker_character_id=line.speaker_character_id,
                    text_th=line.text_th,
                    critical_terms=list(line.critical_terms),
                    segment=segment if ratio >= align_min_ratio else None,
                    ratio=ratio,
                )
            )
    return alignments


def overall_asr_status(observation: MediaObservation, duration_ms: int) -> CoverageStatus:
    return coverage_for(observation.coverage, CheckFamily.ASR, 0, max(duration_ms, 1))


# --- speech findings ---------------------------------------------------------------------


def speech_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    asset_sha256: str,
    alignments: Sequence[LineAlignment],
    observation: MediaObservation,
    duration_ms: int,
) -> list[QAFinding]:
    """Critical-term/speaker/line-present checks. Observed side is the transcript only."""
    fixture = observation.source_label == SOURCE_FIXTURE
    evidence_note = (
        f"fixture-truth:{observation.fixture_id} (offline observation of the actual media)"
        if fixture
        else "no observation source registered; speech was not observed"
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
                evidence_ref=f"observation:{asset_sha256[:16]}",
                evidence_note=evidence_note,
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                **kwargs,  # type: ignore[arg-type]
            )
        )

    for alignment in alignments:
        segment = alignment.segment
        if segment is None:
            status = overall_asr_status(observation, duration_ms)
            if status is CoverageStatus.CHECKED:
                add(
                    check_id="asr.line_present",
                    family=CheckFamily.ASR,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.CRITICAL,
                    outcome=QAOutcome.REPAIRABLE,
                    coverage=status,
                    expected=alignment.text_th,
                    observed="no spoken segment matches this script line",
                    repair_targets=[RepairTarget.LINE],
                )
            else:
                add(
                    check_id="asr.line_present",
                    family=CheckFamily.ASR,
                    start_ms=0,
                    end_ms=duration_ms,
                    severity=Severity.MAJOR,
                    outcome=QAOutcome.UNKNOWN,
                    coverage=status,
                    expected=alignment.text_th,
                    observed="speech not checked for this media",
                )
            continue
        status = coverage_for(
            observation.coverage, CheckFamily.ASR, segment.start_ms, segment.end_ms
        )
        checked_pass = QAOutcome.PASS if status is CoverageStatus.CHECKED else QAOutcome.UNKNOWN
        add(
            check_id="asr.line_present",
            family=CheckFamily.ASR,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            severity=Severity.INFO,
            outcome=checked_pass,
            coverage=status,
            expected=alignment.text_th,
            observed="a spoken segment matches this line",
        )
        for term in alignment.critical_terms:
            present = _norm(term.value_th) in _norm(segment.text)
            expected = (
                term.value_th if term.value_en is None else f"{term.value_th} ({term.value_en})"
            )
            add(
                check_id="asr.critical_term_match",
                family=CheckFamily.ASR,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                severity=Severity.INFO if present else Severity.CRITICAL,
                outcome=checked_pass if present else QAOutcome.REPAIRABLE,
                coverage=status,
                expected=expected,
                observed=term.value_th if present else segment.text,
                repair_targets=None if present else [RepairTarget.LINE],
            )
        if segment.speaker_label == alignment.speaker_character_id:
            add(
                check_id="asr.speaker_match",
                family=CheckFamily.ASR,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                severity=Severity.INFO,
                outcome=checked_pass,
                coverage=status,
                expected=alignment.speaker_character_id,
                observed=segment.speaker_label,
            )
        else:
            add(
                check_id="asr.speaker_match",
                family=CheckFamily.ASR,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                severity=Severity.CRITICAL,
                outcome=QAOutcome.REPAIRABLE,
                coverage=status,
                expected=alignment.speaker_character_id,
                observed=segment.speaker_label,
                repair_targets=[RepairTarget.LINE],
            )
    return out


def caption_speech_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    asset_sha256: str,
    cues: Sequence[CaptionCue],
    observation: MediaObservation,
    source_label: str,
) -> list[QAFinding]:
    """Caption-vs-speech agreement (Thai cues only): the T015 mismatch code, re-checked.

    A Thai caption that overlaps observed Thai speech must agree with what was
    actually said; writing the intended words over wrong audio would conceal the
    defect, so a disagreement is a CRITICAL ``caption.audio_content_mismatch``
    (the stable code T015's assembly also emits). Translation locales are skipped —
    comparing an English cue to Thai speech is not this check's call.
    """
    fixture = observation.source_label == SOURCE_FIXTURE
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
                evidence_ref=f"caption-vs-speech:{asset_sha256[:16]}",
                evidence_note=(
                    f"caption text ({source_label}) compared with observed speech; "
                    "intended script text is not an input"
                ),
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                **kwargs,  # type: ignore[arg-type]
            )
        )

    thai_segments = [seg for seg in observation.segments if _has_thai(seg.text)]
    for cue in cues:
        if not _has_thai(cue.text):
            continue
        overlapping = [
            seg for seg in thai_segments if seg.start_ms < cue.end_ms and cue.start_ms < seg.end_ms
        ]
        for seg in overlapping:
            agree = _norm(seg.text) == _norm(cue.text)
            add(
                check_id=MISMATCH_CODE,
                family=CheckFamily.CAPTION,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                severity=Severity.INFO if agree else Severity.CRITICAL,
                outcome=QAOutcome.PASS if agree else QAOutcome.REPAIRABLE,
                coverage=CoverageStatus.CHECKED,
                expected=seg.text if not agree else "caption agrees with observed speech",
                observed=cue.text if not agree else seg.text,
                repair_targets=None if agree else [RepairTarget.CAPTION, RepairTarget.LINE],
            )
    return out


def _has_thai(text: str) -> bool:
    return any("฀" <= ch <= "๿" for ch in text)


__all__ = [
    "MISMATCH_CODE",
    "OBSERVER_MODEL_REF",
    "SOURCE_FIXTURE",
    "SOURCE_UNREGISTERED",
    "MediaObserver",
    "OfflineMediaObserver",
    "SpeechObserverAdapter",
    "align_best",
    "align_lines",
    "as_speech_observer",
    "caption_speech_findings",
    "overall_asr_status",
    "speech_findings",
]

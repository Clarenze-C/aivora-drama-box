"""Fake ASR and media-review providers (T007). They report what is in the media, not the script.

Both read ``FixtureTruthRegistry`` (keyed by the file's sha256). Unknown media yields no segments and
UNAVAILABLE coverage, never invented text. Coverage outside the declared truth is UNSAMPLED or
UNAVAILABLE, and findings there are UNKNOWN, never PASS.

``observe(request, media)`` takes no script and never sees one: it builds the frozen report from
truth plus the neutral questions (which only pick ``question_id`` links). Observation descriptions use
fixed prefixes (``identity: ``, ``caption: ``, ``on-screen: ``, ``temporal: ``); the fake's compare
step reads them with those prefixes only.

``compare(request, materials)`` aligns script lines with the frozen transcript and captions by text
similarity and checks critical terms (money, names, negation, date), speaker, visible identity and
release claims. Every finding is FAKE_SYNTHETIC evidence from a deterministic rule, not a quality claim.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    PriceUnit,
    Provenance,
    QAOutcome,
    QAPass,
    ReceiptKind,
    RepairTarget,
    Severity,
)
from microdrama.contracts.errors import NotFound, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash, file_sha256
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.providers import (
    ASRRequest,
    ASRResult,
    ComparisonMaterials,
    ComparisonResult,
    ObservationResult,
)
from microdrama.contracts.qa import (
    ComparisonRequest,
    CoverageWindow,
    Observation,
    ObservationReport,
    ObservationRequest,
    QAFinding,
    TranscriptSegment,
)
from microdrama.testing.fakes.common import (
    FakeBase,
    FakeClock,
    SequentialIds,
    priced,
    synthetic_receipt,
)
from microdrama.testing.media import (
    FixtureTruth,
    FixtureTruthRegistry,
    MediaToolError,
    SpokenTruth,
    probe,
)

PREFIX_IDENTITY = "identity: "
PREFIX_CAPTION = "caption: "
PREFIX_ONSCREEN = "on-screen: "
PREFIX_TEMPORAL = "temporal: "
ALIGN_MIN_RATIO = 0.6
OBSERVER_MODEL_REF = "fake-observer-v1"
_STATUS_RANK = {
    CoverageStatus.CHECKED: 0,
    CoverageStatus.PARTIAL: 1,
    CoverageStatus.UNSAMPLED: 2,
    CoverageStatus.UNAVAILABLE: 3,
}
_QUESTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "asr": ("say", "spoken", "speak", "dialogue"),
    "identity": ("who", "visible", "face", "identity"),
    "caption": ("shown", "screen", "caption", "text", "amount", "number"),
    "temporal": ("frame", "black", "frozen", "freeze", "visual"),
}


class ReviewScenario(StrEnum):
    """Outcomes come from the fixture truth, so the only scripted step is HAPPY."""

    HAPPY = "HAPPY"


def coverage_windows(
    asset_id: UUID,
    family: CheckFamily,
    duration_ms: int,
    covered: Sequence[tuple[int, int]],
    *,
    inside: CoverageStatus = CoverageStatus.CHECKED,
    outside: CoverageStatus = CoverageStatus.UNSAMPLED,
    note: str | None = None,
) -> list[CoverageWindow]:
    """Partition ``[0, duration)`` into covered windows and gap windows with a status each."""
    windows: list[CoverageWindow] = []
    cursor = 0
    for start, end in sorted(covered):
        if start > cursor:
            windows.append(CoverageWindow(asset_id=asset_id, check_family=family, start_ms=cursor,
                                          end_ms=start, status=outside, note=note))  # fmt: skip
        windows.append(CoverageWindow(asset_id=asset_id, check_family=family, start_ms=start,
                                      end_ms=end, status=inside))  # fmt: skip
        cursor = end
    if cursor < duration_ms or not windows:
        windows.append(CoverageWindow(asset_id=asset_id, check_family=family, start_ms=cursor,
                                      end_ms=duration_ms, status=outside, note=note))  # fmt: skip
    return windows


def _covers(intervals: Sequence[tuple[int, int]], start: int, end: int) -> bool:
    cursor = start
    for lo, hi in sorted(intervals):
        if lo > cursor:
            return False
        cursor = max(cursor, hi)
    return cursor >= end


def status_for(
    report: ObservationReport, family: CheckFamily, start: int, end: int
) -> CoverageStatus:
    """Coverage of ``[start, end)`` for one check family, from the frozen report's windows."""
    overlapping = [
        w
        for w in report.coverage
        if w.check_family is family and w.start_ms < end and start < w.end_ms
    ]
    if not overlapping:
        return CoverageStatus.UNAVAILABLE
    checked = [
        (max(w.start_ms, start), min(w.end_ms, end))
        for w in overlapping
        if w.status is CoverageStatus.CHECKED
    ]
    if _covers(checked, start, end):
        return CoverageStatus.CHECKED
    if checked:
        return CoverageStatus.PARTIAL
    statuses = {w.status for w in overlapping}
    if CoverageStatus.UNAVAILABLE in statuses:
        return CoverageStatus.UNAVAILABLE
    if CoverageStatus.UNSAMPLED in statuses:
        return CoverageStatus.UNSAMPLED
    return CoverageStatus.PARTIAL


def _norm(text: str) -> str:
    return "".join(text.split())


def _best[T](items: Sequence[T], text: str, key: Any) -> tuple[T | None, float]:
    best: T | None = None
    best_ratio = 0.0
    needle = _norm(text)
    for item in items:
        ratio = difflib.SequenceMatcher(None, needle, _norm(key(item)), autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return best, best_ratio


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _spoken_within(truth: FixtureTruth) -> tuple[SpokenTruth, ...]:
    """Speech is reported only when a whole segment lies inside checked coverage."""
    return tuple(
        s
        for s in truth.spoken
        if truth.has_audio
        and any(lo <= s.start_ms and s.end_ms <= hi for lo, hi in truth.covered_ranges_ms)
    )


def _inside(truth: FixtureTruth, start: int) -> bool:
    return any(lo <= start < hi for lo, hi in truth.covered_ranges_ms)


def _probe_duration(path: Path) -> int:
    try:
        return probe(path).duration_ms
    except MediaToolError:
        return 0


class FakeASRProvider(FakeBase):
    provider_id: str = "fake-asr"
    default_scenario: ClassVar[ReviewScenario] = ReviewScenario.HAPPY

    def __init__(self, *, clock: FakeClock, ids: SequentialIds, truth: FixtureTruthRegistry,
                 scenarios: tuple[ReviewScenario, ...] = ()) -> None:  # fmt: skip
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.truth = truth

    def transcribe(self, request: ASRRequest, media_path: Path) -> ASRResult:
        self._step("transcribe", key=str(request.request_id))
        path = Path(media_path)
        if not path.is_file():
            raise NotFound("media file for ASR not found", request_id=str(request.request_id))
        actual_sha = file_sha256(str(path))
        now = self.clock.now()
        known = self.truth.get(request.asset_sha256) if actual_sha == request.asset_sha256 else None
        if known is None:
            reason = (
                "file sha256 differs from request"
                if actual_sha != request.asset_sha256
                else "no fixture truth registered for this sha256"
            )
            duration = _probe_duration(path)
            return ASRResult(
                request_id=request.request_id,
                segments=[],
                coverage=coverage_windows(
                    request.asset_id, CheckFamily.ASR, duration, (),
                    outside=CoverageStatus.UNAVAILABLE, note=reason,
                ),  # fmt: skip
                usage=[],
                provenance=Provenance.FAKE_SYNTHETIC,
            )  # fmt: skip

        duration = known.duration_ms
        covered = known.covered_ranges_ms if known.has_audio else ()
        note = None if known.has_audio else "no audio stream in media"
        segments = [
            TranscriptSegment(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                text=s.text_th,
                speaker_label=s.speaker_id,
                confidence_bp=None,
            )
            for s in _spoken_within(known)
        ]
        units = -(-duration // 1000) or 1
        usage: list[UsageReceipt] = [
            synthetic_receipt(
                provider=self.provider_id,
                provider_receipt_id=f"asr:{request.request_id}",
                kind=ReceiptKind.SETTLEMENT,
                category=BudgetCategory.QA_CAPTIONS,
                unit=PriceUnit.AUDIO_SECOND,
                units=units,
                amount_micro_usd=priced(PriceUnit.AUDIO_SECOND, units),
                observed_at=now,
                reservation_id=request.reservation_id,
            )
        ]
        self._bill(usage)
        return ASRResult(
            request_id=request.request_id,
            segments=segments,
            coverage=coverage_windows(
                request.asset_id, CheckFamily.ASR, duration, covered,
                outside=CoverageStatus.UNSAMPLED if known.has_audio else CoverageStatus.UNAVAILABLE,
                note=note,
            ),  # fmt: skip
            usage=usage,
            provenance=Provenance.FAKE_SYNTHETIC,
        )  # fmt: skip


class FakeMediaReviewProvider(FakeBase):
    provider_id: str = "fake-media-review"
    default_scenario: ClassVar[ReviewScenario] = ReviewScenario.HAPPY

    def __init__(
        self,
        *,
        clock: FakeClock,
        ids: SequentialIds,
        truth: FixtureTruthRegistry,
        unreleased_claim_phrases: Sequence[str] = (),
        scenarios: tuple[ReviewScenario, ...] = (),
    ) -> None:
        super().__init__(clock=clock, ids=ids, scenarios=scenarios)
        self.truth = truth
        # Release state is configuration (from the catalog), never read from script or model output.
        self.unreleased_claim_phrases = tuple(unreleased_claim_phrases)

    @staticmethod
    def _question(request: ObservationRequest, category: str) -> str | None:
        for question in request.questions:
            text = question.text.lower()
            if any(word in text for word in _QUESTION_KEYWORDS[category]):
                return question.question_id
        return None

    def observe(
        self, request: ObservationRequest, media: list[AssetDescriptor]
    ) -> ObservationResult:
        """Pass A. Takes only the request and the media; a script is not an input here."""
        self._note("observe", key=str(request.request_id))
        expected = {m.asset_id: m for m in request.media}
        now = self.clock.now()
        transcript: list[TranscriptSegment] = []
        observations: list[Observation] = []
        coverage: list[CoverageWindow] = []
        media_sha: list[str] = []
        usage_units = 0
        for asset in media:
            if (
                asset.asset_id not in expected
                or expected[asset.asset_id].asset_sha256 != asset.sha256
            ):
                raise SchemaInvalid("media is not part of this observation request")
            media_sha.append(asset.sha256)
            requested = expected[asset.asset_id].duration_ms
            truth = self.truth.get(asset.sha256)
            if truth is None or truth.duration_ms != requested:
                reason = (
                    "no fixture truth registered for this sha256"
                    if truth is None
                    else "truth duration differs from requested duration"
                )
                for family in CheckFamily:
                    if family in (
                        CheckFamily.ASR,
                        CheckFamily.CAPTION,
                        CheckFamily.VISUAL_IDENTITY,
                        CheckFamily.TEMPORAL,
                    ):
                        coverage += coverage_windows(
                            asset.asset_id, family, requested, (),
                            outside=CoverageStatus.UNAVAILABLE, note=reason,
                        )  # fmt: skip
                usage_units += -(-requested // 1000) or 1
                continue
            transcript += [
                TranscriptSegment(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text_th,
                                  speaker_label=s.speaker_id, confidence_bp=None)
                for s in _spoken_within(truth)
            ]  # fmt: skip
            for ident in truth.identities:
                if _inside(truth, ident.start_ms) and truth.has_video:
                    observations.append(self._obs(request, asset, ident.start_ms, ident.end_ms,
                                                  f"{PREFIX_IDENTITY}{ident.character_id}", "identity", len(observations)))  # fmt: skip
            for text in truth.text_items:
                if _inside(truth, text.start_ms):
                    prefix = PREFIX_CAPTION if text.kind == "caption" else PREFIX_ONSCREEN
                    observations.append(self._obs(request, asset, text.start_ms, text.end_ms,
                                                  f"{prefix}{text.text}", "caption", len(observations)))  # fmt: skip
            for defect in truth.video_defects:
                label = "black frames" if defect.kind == "black" else "frozen frames"
                observations.append(self._obs(request, asset, defect.start_ms, defect.end_ms,
                                              f"{PREFIX_TEMPORAL}{label}", "temporal", len(observations)))  # fmt: skip
            coverage += self._coverage(asset.asset_id, truth)
            usage_units += -(-truth.duration_ms // 1000) or 1

        usage = [
            synthetic_receipt(
                provider=self.provider_id,
                provider_receipt_id=f"observe:{request.request_id}",
                kind=ReceiptKind.SETTLEMENT,
                category=BudgetCategory.QA_CAPTIONS,
                unit=PriceUnit.VIDEO_SECOND,
                units=usage_units,
                amount_micro_usd=priced(PriceUnit.VIDEO_SECOND, usage_units),
                observed_at=now,
                reservation_id=request.reservation_id,
            )
        ]
        self._bill(usage)
        report = ObservationReport(
            report_id=self.ids.new_id(),
            request_id=request.request_id,
            request_sha256=canonical_hash(request),
            episode_id=request.episode_id,
            media_sha256=media_sha,
            transcript=transcript,
            observations=observations,
            coverage=coverage,
            model_config_ref=OBSERVER_MODEL_REF,
            provenance=Provenance.FAKE_SYNTHETIC,
            frozen_at=now,
        )
        return ObservationResult(report=report, usage=usage)

    def _obs(self, request: ObservationRequest, asset: AssetDescriptor, start: int, end: int,
             description: str, category: str, index: int) -> Observation:  # fmt: skip
        return Observation(
            observation_id=f"o{index + 1}",
            question_id=self._question(request, category),
            asset_id=asset.asset_id,
            start_ms=start,
            end_ms=end,
            description=description,
            confidence_bp=None,
        )

    def _coverage(self, asset_id: UUID, truth: FixtureTruth) -> list[CoverageWindow]:
        d, cov = truth.duration_ms, truth.covered_ranges_ms
        windows = coverage_windows(asset_id, CheckFamily.ASR, d, cov if truth.has_audio else (),
                                   outside=CoverageStatus.UNSAMPLED if truth.has_audio else CoverageStatus.UNAVAILABLE,
                                   note=None if truth.has_audio else "no audio stream in media")  # fmt: skip
        windows += coverage_windows(asset_id, CheckFamily.CAPTION, d, cov)
        for family in (CheckFamily.VISUAL_IDENTITY, CheckFamily.TEMPORAL):
            windows += coverage_windows(asset_id, family, d, cov if truth.has_video else (),
                                        outside=CoverageStatus.UNSAMPLED if truth.has_video else CoverageStatus.UNAVAILABLE,
                                        note=None if truth.has_video else "no video stream in media")  # fmt: skip
        return windows

    # --- Pass B -----------------------------------------------------------------------

    def compare(
        self, request: ComparisonRequest, materials: ComparisonMaterials
    ) -> ComparisonResult:
        self._note("compare", key=str(request.request_id))
        report = materials.frozen_report
        if canonical_hash(report) != request.observation_report_sha256:
            raise SchemaInvalid("comparison materials do not match the frozen report hash")
        if canonical_hash(materials.script) != request.script_sha256:
            raise SchemaInvalid("comparison materials do not match the script hash")
        asset_id = report.coverage[0].asset_id
        duration = max(w.end_ms for w in report.coverage if w.asset_id == asset_id)
        findings: list[QAFinding] = []

        def finding(start: int, end: int, check_id: str, family: CheckFamily, severity: Severity,
                    outcome: QAOutcome, coverage: CoverageStatus, expected: str | None,
                    observed: str | None, repairs: list[RepairTarget], at: UUID = asset_id) -> None:  # fmt: skip
            findings.append(
                QAFinding(
                    finding_id=self.ids.new_id(),
                    episode_id=request.episode_id,
                    asset_id=at,
                    start_ms=start,
                    end_ms=max(start, end),
                    check_id=check_id,
                    check_family=family,
                    source_pass=QAPass.PASS_B_COMPARISON,
                    expected=expected,
                    observed=observed,
                    evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE,
                                          ref=f"observation-report:{report.report_id}")],
                    severity=severity,
                    coverage=coverage,
                    outcome=outcome,
                    repair_targets=repairs,
                    provenance=Provenance.FAKE_SYNTHETIC,
                )
            )  # fmt: skip

        def checked_outcome(positive: bool, status: CoverageStatus) -> QAOutcome:
            if positive:
                return QAOutcome.PASS if status is CoverageStatus.CHECKED else QAOutcome.UNKNOWN
            return QAOutcome.UNKNOWN

        transcript = list(report.transcript)
        captions = [o for o in report.observations if o.description.startswith(PREFIX_CAPTION)]
        identities = [o for o in report.observations if o.description.startswith(PREFIX_IDENTITY)]
        asr_overall = status_for(report, CheckFamily.ASR, 0, duration)

        for scene in materials.script.scenes:
            for line in scene.lines:
                seg, ratio = _best(transcript, line.text_th, lambda s: s.text)
                if seg is not None and ratio >= ALIGN_MIN_RATIO:
                    status = status_for(report, CheckFamily.ASR, seg.start_ms, seg.end_ms)
                    for term in line.critical_terms:
                        expected = (
                            term.value_th
                            if term.value_en is None
                            else f"{term.value_th} ({term.value_en})"
                        )
                        present = _norm(term.value_th) in _norm(seg.text)
                        if present:
                            finding(seg.start_ms, seg.end_ms, "asr.critical_term_match", CheckFamily.ASR,
                                    Severity.INFO, checked_outcome(True, status), status, expected,
                                    term.value_th, [])  # fmt: skip
                        else:
                            finding(seg.start_ms, seg.end_ms, "asr.critical_term_match", CheckFamily.ASR,
                                    Severity.CRITICAL, QAOutcome.REPAIRABLE, status, expected,
                                    seg.text, [RepairTarget.LINE])  # fmt: skip
                    if seg.speaker_label == line.speaker_character_id:
                        finding(seg.start_ms, seg.end_ms, "asr.speaker_match", CheckFamily.ASR, Severity.INFO,
                                checked_outcome(True, status), status, line.speaker_character_id,
                                seg.speaker_label, [])  # fmt: skip
                    else:
                        finding(seg.start_ms, seg.end_ms, "asr.speaker_match", CheckFamily.ASR, Severity.CRITICAL,
                                QAOutcome.REPAIRABLE, status, line.speaker_character_id, seg.speaker_label,
                                [RepairTarget.LINE])  # fmt: skip
                    visible = [i for i in identities
                               if _overlaps(i.start_ms, i.end_ms, seg.start_ms, seg.end_ms)]  # fmt: skip
                    v_status = status_for(
                        report, CheckFamily.VISUAL_IDENTITY, seg.start_ms, seg.end_ms
                    )
                    if not visible:
                        finding(seg.start_ms, seg.end_ms, "visual_identity.match", CheckFamily.VISUAL_IDENTITY,
                                Severity.MAJOR, QAOutcome.UNKNOWN, v_status, line.speaker_character_id,
                                "no identity observed in range", [])  # fmt: skip
                    else:
                        labels = [i.description[len(PREFIX_IDENTITY) :] for i in visible]
                        mismatch = any(lbl != line.speaker_character_id for lbl in labels)
                        if mismatch:
                            finding(seg.start_ms, seg.end_ms, "visual_identity.match", CheckFamily.VISUAL_IDENTITY,
                                    Severity.CRITICAL, QAOutcome.REPAIRABLE, v_status,
                                    line.speaker_character_id, ", ".join(labels), [RepairTarget.SHOT])  # fmt: skip
                        else:
                            finding(seg.start_ms, seg.end_ms, "visual_identity.match", CheckFamily.VISUAL_IDENTITY,
                                    Severity.INFO, checked_outcome(True, v_status), v_status,
                                    line.speaker_character_id, ", ".join(labels), [])  # fmt: skip
                elif asr_overall is CoverageStatus.CHECKED:
                    finding(0, duration, "asr.line_present", CheckFamily.ASR, Severity.CRITICAL,
                            QAOutcome.REPAIRABLE, asr_overall, line.text_th,
                            "no spoken segment matches this script line", [RepairTarget.LINE])  # fmt: skip
                else:
                    finding(0, duration, "asr.line_present", CheckFamily.ASR, Severity.MAJOR,
                            QAOutcome.UNKNOWN, asr_overall, line.text_th,
                            "speech not checked for this media", [])  # fmt: skip

                cap, cap_ratio = _best(
                    captions, line.text_th, lambda o: o.description[len(PREFIX_CAPTION) :]
                )
                if cap is not None and cap_ratio >= ALIGN_MIN_RATIO:
                    cap_text = cap.description[len(PREFIX_CAPTION) :]
                    c_status = status_for(report, CheckFamily.CAPTION, cap.start_ms, cap.end_ms)
                    for term in line.critical_terms:
                        if _norm(term.value_th) in _norm(cap_text):
                            finding(cap.start_ms, cap.end_ms, "caption.critical_term_match", CheckFamily.CAPTION,
                                    Severity.INFO, checked_outcome(True, c_status), c_status,
                                    term.value_th, term.value_th, [], asset_id)  # fmt: skip
                        else:
                            finding(cap.start_ms, cap.end_ms, "caption.critical_term_match", CheckFamily.CAPTION,
                                    Severity.CRITICAL, QAOutcome.REPAIRABLE, c_status, term.value_th,
                                    cap_text, [RepairTarget.CAPTION], asset_id)  # fmt: skip

        for obs in report.observations:
            text = obs.description
            if text.startswith((PREFIX_CAPTION, PREFIX_ONSCREEN)):
                body = text.split(": ", 1)[1]
                if obs.end_ms > duration:
                    finding(obs.start_ms, obs.end_ms, "caption.cue_within_media", CheckFamily.CAPTION,
                            Severity.MAJOR, QAOutcome.REPAIRABLE,
                            status_for(report, CheckFamily.CAPTION, obs.start_ms, obs.end_ms),
                            f"end <= {duration} ms", f"cue ends at {obs.end_ms} ms",
                            [RepairTarget.CAPTION], asset_id)  # fmt: skip
                if any(phrase in body for phrase in self.unreleased_claim_phrases):
                    finding(obs.start_ms, obs.end_ms, "caption.release_claim", CheckFamily.CAPTION,
                            Severity.CRITICAL, QAOutcome.REPAIRABLE,
                            status_for(report, CheckFamily.CAPTION, obs.start_ms, obs.end_ms),
                            "no claim of an unreleased episode", body, [RepairTarget.CAPTION], asset_id)  # fmt: skip
            elif text.startswith(PREFIX_TEMPORAL):
                label = text[len(PREFIX_TEMPORAL) :]
                check = (
                    "temporal.black_frames"
                    if label.startswith("black")
                    else "temporal.frozen_frames"
                )
                finding(obs.start_ms, obs.end_ms, check, CheckFamily.TEMPORAL, Severity.MAJOR,
                        QAOutcome.REPAIRABLE,
                        status_for(report, CheckFamily.TEMPORAL, obs.start_ms, obs.end_ms),
                        "no unintended black or frozen frames", label, [RepairTarget.EDIT], asset_id)  # fmt: skip

        usage = [
            synthetic_receipt(
                provider=self.provider_id,
                provider_receipt_id=f"compare:{request.request_id}",
                kind=ReceiptKind.SETTLEMENT,
                category=BudgetCategory.QA_CAPTIONS,
                unit=PriceUnit.REQUEST,
                units=1,
                amount_micro_usd=priced(PriceUnit.REQUEST, 1),
                observed_at=self.clock.now(),
                reservation_id=request.reservation_id,
            )
        ]
        self._bill(usage)
        return ComparisonResult(
            request_id=request.request_id,
            findings=findings,
            usage=usage,
            provenance=Provenance.FAKE_SYNTHETIC,
        )


__all__ = [
    "ALIGN_MIN_RATIO",
    "FakeASRProvider",
    "FakeMediaReviewProvider",
    "PREFIX_CAPTION",
    "PREFIX_IDENTITY",
    "PREFIX_ONSCREEN",
    "PREFIX_TEMPORAL",
    "ReviewScenario",
    "coverage_windows",
    "status_for",
]

"""Actual-media continuity QA (T042b): timecoded continuity findings over exported bytes.

The lane mirrors the two-pass discipline of the rest of QA: an independent
media-only observation of the ACTUAL staged exported media (keyed by the media's
sha256, the evaluator's identity/configuration and the sampled time ranges) is
frozen first; only then do typed continuity expectations — wardrobe assignments,
prop holders, location layouts, directing eyeline/handoff, proof-text layers,
character voices and subtitle expectations — enter the comparison. No intended
script/canon fact ever reaches the observer call.

Findings are separate timecoded check ids per dimension (identity, assigned
outfit, prop/holder, location/space, eyeline/action handoff, proof text, Thai
voice, phone-safe subtitles) with per-check coverage evidence. The canonical
``CoverageWindow`` carries only ``check_family`` — it cannot distinguish checks
inside one family — so per-check coverage is persisted as a bounded QA-local
record on the run event (see ``summarize_check_coverage`` and the guardian
proposal in ``microdrama/evidence/T042.md``). The family-level windows are NOT
claimed to distinguish checks.

Honesty rules (the frozen ``QAFinding`` contract): ``PASS`` requires ``CHECKED``
coverage; unobserved, unsampled, uncalibrated or unavailable dimensions are
``UNKNOWN`` — never ``PASS``. A keyframe (still-frame) PASS from the T042a
preflight can never certify these motion checks: every finding here cites an
observed media window of the exported video/audio itself.

Mismatches name the earliest correct repair target: rendered visual defects
repair the SHOT (never a caption); Thai voice repairs the LINE or AUDIO_MIX;
subtitle safe-area/readability repairs CAPTION or EDIT. Source sheet/outfit
defects belong to the T042a keyframe preflight BEFORE render — this lane only
sees them after they have been rendered, and says so in the evidence note.

The offline fixture observer refuses to run outside OFFLINE_MOCK, and the
calibration runner is labeled ``OFFLINE_FIXTURE_ONLY``: fixture-truth scores
verify software behavior only. Live detector activation stays disabled until
T031 supplies real-model evidence; nothing in this module gates live release on
a real detector.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
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
from microdrama.contracts.errors import Conflict, EffectDenied, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash, file_sha256, sha256_hex
from microdrama.contracts.qa import QAFinding
from microdrama.qa.models import CheckCoverageWindow, build_finding

#: Offline observation source labels (mirrors ``qa.audio``).
SOURCE_FIXTURE = "fixture-truth"
SOURCE_UNREGISTERED = "unregistered"

#: Default phone-safe subtitle area (x0, y0, x1, y1 in basis points of the
#: frame): 2% side margins, 3% top and 12% bottom margins for vertical phone
#: video with platform UI overlays. Configuration, never code.
DEFAULT_SUBTITLE_SAFE_AREA_BP: tuple[int, int, int, int] = (200, 300, 9_800, 8_800)


class ContinuityDimension(StrEnum):
    """Continuity dimensions checked over the actual exported media."""

    IDENTITY = "identity"
    OUTFIT = "outfit"
    PROP_HOLDER = "prop_holder"
    LOCATION_SPACE = "location_space"
    EYELINE_HANDOFF = "eyeline_handoff"
    PROOF_TEXT = "proof_text"
    THAI_VOICE = "thai_voice"
    SUBTITLE_SAFE_AREA = "subtitle_safe_area"


@dataclass(frozen=True)
class CheckSpec:
    """Emission policy of one continuity check id."""

    check_id: str
    family: CheckFamily
    severity: Severity
    repair_targets: tuple[RepairTarget, ...]


#: Check ids this lane emits, with family/severity/earliest repair targets.
#: A rendered visual defect repairs the SHOT (never a caption); Thai voice
#: repairs LINE/AUDIO_MIX; subtitle readability repairs CAPTION or EDIT.
CHECK_SPECS: dict[ContinuityDimension, CheckSpec] = {
    ContinuityDimension.IDENTITY: CheckSpec(
        check_id="continuity.identity_match",
        family=CheckFamily.VISUAL_IDENTITY,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.OUTFIT: CheckSpec(
        check_id="continuity.outfit_match",
        family=CheckFamily.VISUAL_IDENTITY,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.PROP_HOLDER: CheckSpec(
        check_id="continuity.prop_holder_match",
        family=CheckFamily.VISUAL_IDENTITY,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.LOCATION_SPACE: CheckSpec(
        check_id="continuity.location_space_match",
        family=CheckFamily.VISUAL_IDENTITY,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.EYELINE_HANDOFF: CheckSpec(
        check_id="continuity.eyeline_handoff_match",
        family=CheckFamily.TEMPORAL,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.PROOF_TEXT: CheckSpec(
        check_id="continuity.proof_text_match",
        family=CheckFamily.VISUAL_IDENTITY,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.SHOT,),
    ),
    ContinuityDimension.THAI_VOICE: CheckSpec(
        check_id="continuity.thai_voice_match",
        family=CheckFamily.AUDIO,
        severity=Severity.CRITICAL,
        repair_targets=(RepairTarget.LINE, RepairTarget.AUDIO_MIX),
    ),
    ContinuityDimension.SUBTITLE_SAFE_AREA: CheckSpec(
        check_id="continuity.subtitle_safe_area",
        family=CheckFamily.CAPTION,
        severity=Severity.MAJOR,
        repair_targets=(RepairTarget.CAPTION, RepairTarget.EDIT),
    ),
}

CONTINUITY_CHECK_IDS: tuple[str, ...] = tuple(
    spec.check_id for spec in sorted(CHECK_SPECS.values(), key=lambda s: s.check_id)
)

#: Evidence note for visual mismatches: the source-sheet variant of the defect
#: belongs to the T042a keyframe preflight before render (earliest correct stage).
SOURCE_STAGE_NOTE = (
    "rendered visual defect; if the source sheet/outfit/reference itself is wrong "
    "the T042a keyframe preflight owns catching it before render"
)


# --- observation side (media-only; no intended fact may reach it) ----------------------


@dataclass(frozen=True)
class ObservedContinuityWindow:
    """What the observer actually saw in one sampled window of the exported media.

    ``None`` means the dimension was not observed in this window. Rectangles are
    in basis points of the frame (0..10000 per axis).
    """

    start_ms: int
    end_ms: int
    visible_character_ids: frozenset[str] | None = None
    outfit_by_character: Mapping[str, str] | None = None
    holder_by_prop: Mapping[str, str] | None = None
    location_id: str | None = None
    geometry_token: str | None = None
    eyeline: str | None = None
    action_handoff: str | None = None
    proof_text: str | None = None
    voice_ids: frozenset[str] | None = None
    subtitle_rect_bp: tuple[int, int, int, int] | None = None
    subtitle_text: str | None = None
    confidence_bp: Mapping[ContinuityDimension, int] = field(default_factory=dict)

    def _mapping_payload(self, value: Mapping[str, str] | None) -> dict[str, str] | None:
        return None if value is None else dict(sorted(value.items()))

    def as_payload(self) -> dict[str, object]:
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "visible_character_ids": None
            if self.visible_character_ids is None
            else sorted(self.visible_character_ids),
            "outfit_by_character": self._mapping_payload(self.outfit_by_character),
            "holder_by_prop": self._mapping_payload(self.holder_by_prop),
            "location_id": self.location_id,
            "geometry_token": self.geometry_token,
            "eyeline": self.eyeline,
            "action_handoff": self.action_handoff,
            "proof_text": self.proof_text,
            "voice_ids": None if self.voice_ids is None else sorted(self.voice_ids),
            "subtitle_rect_bp": self.subtitle_rect_bp,
            "subtitle_text": self.subtitle_text,
            "confidence_bp": {
                dimension.value: confidence
                for dimension, confidence in sorted(
                    self.confidence_bp.items(), key=lambda item: item[0].value
                )
            },
        }


@dataclass(frozen=True)
class ContinuityEvaluator:
    """Evaluator identity plus its declared calibration (mirrors T042a's inspector).

    ``calibrated_threshold_bp`` maps each dimension this evaluator is calibrated
    for to the minimum confidence (basis points) an observation must carry to
    clear a check. A dimension absent from the map is ``UNAVAILABLE``; an
    observed value below the threshold is ``UNKNOWN`` — neither can ever pass.
    The calibration table is part of the capability hash, so changing a
    threshold invalidates every cached result bound to the old evaluator.
    """

    evaluator_id: str
    evaluator_version: str
    source_label: str
    calibrated_threshold_bp: Mapping[ContinuityDimension, int]

    def __post_init__(self) -> None:
        if not self.evaluator_id or not self.evaluator_version or not self.source_label:
            raise SchemaInvalid(
                "continuity evaluator must declare an explicit identity and source label"
            )
        thresholds = dict(self.calibrated_threshold_bp)
        for dimension, threshold in thresholds.items():
            if not 0 <= threshold <= 10_000:
                raise SchemaInvalid(
                    "continuity calibration threshold must be 0..10000 basis points",
                    dimension=dimension.value,
                )
        object.__setattr__(self, "calibrated_threshold_bp", MappingProxyType(thresholds))

    def capability_sha256(self) -> str:
        return canonical_hash(
            {
                "evaluator_id": self.evaluator_id,
                "evaluator_version": self.evaluator_version,
                "source_label": self.source_label,
                "calibrated_threshold_bp": {
                    dimension.value: threshold
                    for dimension, threshold in sorted(
                        self.calibrated_threshold_bp.items(), key=lambda item: item[0].value
                    )
                },
            }
        )

    def is_calibrated(self, dimension: ContinuityDimension) -> bool:
        return dimension in self.calibrated_threshold_bp

    def clears(self, dimension: ContinuityDimension, confidence_bp: int | None) -> bool:
        threshold = self.calibrated_threshold_bp.get(dimension)
        return threshold is not None and confidence_bp is not None and confidence_bp >= threshold


@dataclass(frozen=True)
class ContinuityObservation:
    """Frozen media-only observation of the actual exported media.

    Keyed by the media's own sha256, the evaluator identity/configuration and
    the sampled time ranges; hashed by :meth:`observation_sha256` before any
    comparison runs. Windows lie inside the sampled ranges; an unregistered or
    unreadable media yields no windows and ``source_label=unregistered``.
    """

    media_sha256: str
    evaluator: ContinuityEvaluator
    sampled_ranges_ms: tuple[tuple[int, int], ...]
    windows: tuple[ObservedContinuityWindow, ...]
    source_label: str
    fixture_id: str | None = None

    def __post_init__(self) -> None:
        previous_end = -1
        for start, end in self.sampled_ranges_ms:
            if not 0 <= start < end or start < previous_end:
                raise SchemaInvalid(
                    "sampled ranges must be ordered, disjoint and non-negative",
                )
            previous_end = end
        for window in self.windows:
            if not self.sampled_ranges_ms:
                raise SchemaInvalid("an observation without sampled ranges carries no windows")
            if not any(
                lo <= window.start_ms and window.end_ms <= hi for lo, hi in self.sampled_ranges_ms
            ):
                raise SchemaInvalid("every observed window must lie inside one sampled range")
        if self.source_label == SOURCE_UNREGISTERED and self.windows:
            raise SchemaInvalid("an unregistered observation cannot carry observed windows")

    def observation_sha256(self) -> str:
        """Digest of the frozen content (evaluator identity/config included)."""
        return canonical_hash(
            {
                "media_sha256": self.media_sha256,
                "evaluator": self.evaluator.capability_sha256(),
                "sampled_ranges_ms": [list(span) for span in self.sampled_ranges_ms],
                "windows": [window.as_payload() for window in self.windows],
                "source_label": self.source_label,
                "fixture_id": self.fixture_id,
            }
        )


class ContinuityObserver(Protocol):
    """Observes the actual staged exported media. Expectations never enter here.

    ``evaluator`` exposes the observer's identity and calibration so callers can
    bind results to it (a changed capability hash invalidates cached results).
    """

    evaluator: ContinuityEvaluator

    def observe_continuity(
        self,
        *,
        asset_id: UUID,
        asset_sha256: str,
        media_path: Path,
        duration_ms: int,
    ) -> ContinuityObservation: ...


class FixtureContinuityObserver:
    """The OFFLINE_MOCK continuity observer: declared fixture truth by media sha256.

    The registry is keyed by the media's own sha256 — the declared truth of what
    the fixture actually contains (the offline vision/ASR stand-in), never a
    script-derived expectation. Media the registry does not know, or whose staged
    bytes do not hash to the registered sha, observes nothing: every dependent
    finding is a typed UNKNOWN and nothing turns green. Refuses to run outside
    OFFLINE_MOCK; this is not a real-model quality claim (T031 owns that).
    """

    def __init__(
        self,
        registry,  # FixtureTruthRegistry (typed loosely to avoid an import cycle)
        settings: Settings,
        evaluator: ContinuityEvaluator,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self.evaluator = evaluator

    def observe_continuity(
        self,
        *,
        asset_id: UUID,
        asset_sha256: str,
        media_path: Path,
        duration_ms: int,
    ) -> ContinuityObservation:
        if not self._settings.is_offline_mock:
            raise EffectDenied(
                "the offline fixture continuity observer runs only in OFFLINE_MOCK; "
                "a real vision/ASR provider must be qualified by T031 evidence first"
            )
        actual_sha = file_sha256(str(media_path))
        if actual_sha != asset_sha256:
            return ContinuityObservation(
                media_sha256=actual_sha,
                evaluator=self.evaluator,
                sampled_ranges_ms=(),
                windows=(),
                source_label=SOURCE_UNREGISTERED,
            )
        truth = self._registry.get(asset_sha256)
        if truth is None or not truth.continuity:
            return ContinuityObservation(
                media_sha256=asset_sha256,
                evaluator=self.evaluator,
                sampled_ranges_ms=(),
                windows=(),
                source_label=SOURCE_UNREGISTERED,
            )
        return observation_from_truth(truth, asset_sha256, self.evaluator)


def observation_from_truth(
    truth, actual_sha: str, evaluator: ContinuityEvaluator
) -> ContinuityObservation:
    """Map declared fixture truth into a frozen observation (the offline stand-in).

    ``truth`` is a ``testing.media.FixtureTruth`` keyed by the media's own
    sha256 (typed loosely here to keep the QA module free of a hard testing
    import); the mapping is deliberately total: a ``None`` field on a truth
    window is an unobserved dimension on the observed window.
    """
    windows = tuple(
        ObservedContinuityWindow(
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            visible_character_ids=(
                None
                if item.visible_character_ids is None
                else frozenset(item.visible_character_ids)
            ),
            outfit_by_character=(
                None if item.outfit_by_character is None else dict(item.outfit_by_character)
            ),
            holder_by_prop=(None if item.holder_by_prop is None else dict(item.holder_by_prop)),
            location_id=item.location_id,
            geometry_token=item.geometry_token,
            eyeline=item.eyeline,
            action_handoff=item.action_handoff,
            proof_text=item.proof_text,
            voice_ids=None if item.voice_ids is None else frozenset(item.voice_ids),
            subtitle_rect_bp=item.subtitle_rect_bp,
            subtitle_text=item.subtitle_text,
            confidence_bp={
                dimension: item.confidence_bp
                for dimension in ContinuityDimension
                if item.confidence_bp is not None
            },
        )
        for item in truth.continuity
    )
    return ContinuityObservation(
        media_sha256=actual_sha,
        evaluator=evaluator,
        sampled_ranges_ms=tuple(truth.covered_ranges_ms),
        windows=windows,
        source_label=SOURCE_FIXTURE,
        fixture_id=truth.fixture_id,
    )


# --- expected side (typed records; never enters the observer call) ---------------------


@dataclass(frozen=True)
class ExpectedContinuityWindow:
    """What the current typed records say one media time window must show.

    Time windows come from the current edit manifest (shot spans on the
    exported timeline); every other field comes from the typed V2 records
    (wardrobe assignments, prop sheets, location layouts, directing shots) and
    the script (speaking characters). A dimension with no expectation here is
    not applicable in this window.
    """

    start_ms: int
    end_ms: int
    scene_id: str
    visible_character_ids: frozenset[str]
    outfit_by_character: Mapping[str, str]
    holder_by_prop: Mapping[str, str]
    location_id: str
    geometry_token: str
    eyeline: str | None
    action_handoff: str | None
    proof_text_sha256_by_prop: Mapping[str, str]
    speaking_character_ids: frozenset[str]
    voice_by_character: Mapping[str, str]
    expects_subtitles: bool
    shot_class: str = "UNSPECIFIED"
    shot_id: str | None = None


@dataclass(frozen=True)
class EpisodeContinuityExpectations:
    """Typed continuity expectations for one episode, hashed for run binding."""

    episode_id: UUID
    windows: tuple[ExpectedContinuityWindow, ...]

    def __post_init__(self) -> None:
        previous_end = -1
        for window in self.windows:
            if not 0 <= window.start_ms < window.end_ms:
                raise SchemaInvalid("expected windows must be ordered positive ranges")
            if window.start_ms < previous_end:
                raise SchemaInvalid("expected windows must not overlap")
            previous_end = window.end_ms

    def validate_binding(self, episode_id: UUID, media_duration_ms: int) -> None:
        """Reject expectations of another episode or windows beyond the media.

        Called before the run key is derived: a seam that returns another
        episode's payload — or windows that outlive the measured exported-media
        duration — must never reach comparison or be hashed into a cached run.
        """

        if self.episode_id != episode_id:
            raise Conflict(
                "continuity expectations belong to a different episode",
                expected_episode_id=str(episode_id),
                expectations_episode_id=str(self.episode_id),
            )
        for window in self.windows:
            if window.end_ms > media_duration_ms:
                raise Conflict(
                    "continuity expectations window lies outside the measured "
                    "exported-media duration",
                    window_start_ms=window.start_ms,
                    window_end_ms=window.end_ms,
                    duration_ms=media_duration_ms,
                )

    def expectations_sha256(self) -> str:
        return canonical_hash(
            {
                "episode_id": str(self.episode_id),
                "windows": [
                    {
                        "start_ms": w.start_ms,
                        "end_ms": w.end_ms,
                        "scene_id": w.scene_id,
                        "visible_character_ids": sorted(w.visible_character_ids),
                        "outfit_by_character": dict(sorted(w.outfit_by_character.items())),
                        "holder_by_prop": dict(sorted(w.holder_by_prop.items())),
                        "location_id": w.location_id,
                        "geometry_token": w.geometry_token,
                        "eyeline": w.eyeline,
                        "action_handoff": w.action_handoff,
                        "proof_text_sha256_by_prop": dict(
                            sorted(w.proof_text_sha256_by_prop.items())
                        ),
                        "speaking_character_ids": sorted(w.speaking_character_ids),
                        "voice_by_character": dict(sorted(w.voice_by_character.items())),
                        "expects_subtitles": w.expects_subtitles,
                        "shot_class": w.shot_class,
                        "shot_id": w.shot_id,
                    }
                    for w in self.windows
                ],
            }
        )


class ContinuityExpectations(Protocol):
    """Read-only seam: the typed continuity expectations of one episode."""

    def continuity_expectations(self, episode_id: UUID) -> EpisodeContinuityExpectations | None: ...


def dimension_applies(dimension: ContinuityDimension, window: ExpectedContinuityWindow) -> bool:
    """Whether the typed expectations define this dimension for this window."""
    if dimension is ContinuityDimension.IDENTITY:
        return bool(window.visible_character_ids)
    if dimension is ContinuityDimension.OUTFIT:
        return bool(window.outfit_by_character)
    if dimension is ContinuityDimension.PROP_HOLDER:
        return bool(window.holder_by_prop)
    if dimension is ContinuityDimension.LOCATION_SPACE:
        return bool(window.location_id)
    if dimension is ContinuityDimension.EYELINE_HANDOFF:
        return window.eyeline is not None or window.action_handoff is not None
    if dimension is ContinuityDimension.PROOF_TEXT:
        return bool(window.proof_text_sha256_by_prop)
    if dimension is ContinuityDimension.THAI_VOICE:
        voices = {window.voice_by_character.get(c) for c in window.speaking_character_ids}
        return None not in voices and len(voices - {None}) > 0
    return window.expects_subtitles


# --- comparison (runs against the frozen observation only) -----------------------------


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _text_matches(observed: str | None, expected: str) -> bool | None:
    if observed is None:
        return None
    return _normalize_text(observed) == _normalize_text(expected)


@dataclass(frozen=True)
class _DimensionVerdict:
    outcome: QAOutcome
    coverage: CoverageStatus
    checked_ranges: tuple[tuple[int, int], ...]
    expected: str | None
    observed: str | None
    note: str | None = None


def _clip(ranges: Sequence[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in ranges:
        start, end = max(start, lo), min(end, hi)
        if start < end:
            out.append((start, end))
    return out


def _merge(ranges: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _verdict(
    *,
    expected_window: ExpectedContinuityWindow,
    observed_windows: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
    dimension: ContinuityDimension,
    extract_expected,  # () -> str | None
    extract_observed,  # (ObservedContinuityWindow) -> str | None
    matches,  # (observed_payload: str | None) -> bool | None
) -> _DimensionVerdict:
    """Fold one dimension of one expected window into a verdict + checked ranges."""
    if not evaluator.is_calibrated(dimension):
        return _DimensionVerdict(
            outcome=QAOutcome.UNKNOWN,
            coverage=CoverageStatus.UNAVAILABLE,
            checked_ranges=(),
            expected=extract_expected(),
            observed=None,
            note="evaluator is not calibrated for this dimension",
        )
    checked: list[tuple[int, int]] = []
    observed_payloads: list[str] = []
    mismatch: str | None = None
    for window in observed_windows:
        payload = extract_observed(window)
        confidence = window.confidence_bp.get(dimension)
        if payload is None or not evaluator.clears(dimension, confidence):
            continue
        checked.append((window.start_ms, window.end_ms))
        observed_payloads.append(payload)
        verdict = matches(payload)
        if verdict is False:
            mismatch = payload
    span = (expected_window.start_ms, expected_window.end_ms)
    checked_span = _merge(_clip(checked, *span))
    if mismatch is not None:
        fully = (
            bool(checked_span) and checked_span[0][0] <= span[0] and checked_span[-1][1] >= span[1]
        )
        return _DimensionVerdict(
            outcome=QAOutcome.REPAIRABLE,
            coverage=CoverageStatus.CHECKED if fully else CoverageStatus.PARTIAL,
            checked_ranges=checked_span,
            expected=extract_expected(),
            observed=mismatch,
        )
    if not observed_payloads:
        return _DimensionVerdict(
            outcome=QAOutcome.UNKNOWN,
            coverage=CoverageStatus.UNSAMPLED,
            checked_ranges=(),
            expected=extract_expected(),
            observed=None,
            note="dimension not observed in any sampled window overlapping this one",
        )
    fully = bool(checked_span) and checked_span[0][0] <= span[0] and checked_span[-1][1] >= span[1]
    return _DimensionVerdict(
        outcome=QAOutcome.PASS if fully else QAOutcome.UNKNOWN,
        coverage=CoverageStatus.CHECKED if fully else CoverageStatus.PARTIAL,
        checked_ranges=checked_span,
        expected=extract_expected(),
        observed="; ".join(sorted(set(observed_payloads))[:4]),
    )


def _identity_verdict(
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
) -> _DimensionVerdict:
    expected = ",".join(sorted(window.visible_character_ids))

    def extract(w: ObservedContinuityWindow) -> str | None:
        return (
            None if w.visible_character_ids is None else ",".join(sorted(w.visible_character_ids))
        )

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=ContinuityDimension.IDENTITY,
        extract_expected=lambda: expected,
        extract_observed=extract,
        matches=lambda payload: payload == expected,
    )


def _mapping_verdict(
    *,
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
    dimension: ContinuityDimension,
    expected_map: Mapping[str, str],
    observed_map_of,  # (ObservedContinuityWindow) -> Mapping[str, str] | None
    unobserved_note: str,
) -> _DimensionVerdict:
    expected_token = ",".join(f"{k}={v}" for k, v in sorted(expected_map.items()))

    def extract(w: ObservedContinuityWindow) -> str | None:
        mapping = observed_map_of(w)
        if mapping is None:
            return None
        parts = [f"{k}={mapping.get(k) or '?'}" for k in sorted(expected_map)]
        return ",".join(parts)

    def matches(payload: str) -> bool | None:
        observed_pairs = dict(pair.split("=", 1) for pair in payload.split(",") if "=" in pair)
        if any(observed_pairs.get(key) in (None, "?") for key in expected_map):
            return None  # an assigned key was not observed: cannot certify
        # Extra observed keys (an outfit for a character not assigned in this
        # window) are not this check's verdict — identity owns who is visible.
        return all(observed_pairs[key] == value for key, value in expected_map.items())

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=dimension,
        extract_expected=lambda: expected_token,
        extract_observed=extract,
        matches=matches,
    )


def _location_verdict(
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
) -> _DimensionVerdict:
    expected = f"{window.location_id}:{window.geometry_token}"

    def extract(w: ObservedContinuityWindow) -> str | None:
        if w.location_id is None and w.geometry_token is None:
            return None
        return f"{w.location_id or '?'}:{w.geometry_token or '?'}"

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=ContinuityDimension.LOCATION_SPACE,
        extract_expected=lambda: expected,
        extract_observed=extract,
        matches=lambda payload: payload == expected,
    )


def _pair_text_verdict(
    *,
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
    dimension: ContinuityDimension,
    expected_eyeline: str | None,
    expected_handoff: str | None,
) -> _DimensionVerdict:
    """Eyeline and action handoff compared as one motion-continuum dimension.

    ``eyeline|handoff`` encode the pair; ``-`` marks an expected sub-field the
    window did not observe (cannot certify), and a single observed mismatch on
    either sub-field is a dimension mismatch.
    """
    expected_parts: list[str] = []
    if expected_eyeline is not None:
        expected_parts.append(f"eyeline={_normalize_text(expected_eyeline)}")
    if expected_handoff is not None:
        expected_parts.append(f"handoff={_normalize_text(expected_handoff)}")
    expected_token = "|".join(expected_parts)

    def extract(w: ObservedContinuityWindow) -> str | None:
        parts: list[str] = []
        if expected_eyeline is not None:
            parts.append("eyeline=-" if w.eyeline is None else f"eyeline={w.eyeline}")
        if expected_handoff is not None:
            parts.append("handoff=-" if w.action_handoff is None else f"handoff={w.action_handoff}")
        return "|".join(parts) if parts else None

    def matches(payload: str) -> bool | None:
        result: bool | None = True
        observed_fields = dict(part.split("=", 1) for part in payload.split("|") if "=" in part)
        for part in expected_parts:
            key, expected_value = part.split("=", 1)
            observed_value = observed_fields.get(key)
            if observed_value is None or observed_value == "-":
                result = None  # expected sub-field not observed: cannot certify
                continue
            if _normalize_text(observed_value) != expected_value:
                return False
        return result

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=dimension,
        extract_expected=lambda: expected_token,
        extract_observed=extract,
        matches=matches,
    )


def _proof_text_verdict(
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
) -> _DimensionVerdict:
    expected_layers = sorted(window.proof_text_sha256_by_prop.items())
    expected_token = ",".join(f"{prop}={layer[:16]}" for prop, layer in expected_layers)

    def extract(w: ObservedContinuityWindow) -> str | None:
        return w.proof_text

    def matches(payload: str) -> bool | None:
        if len(expected_layers) > 1:
            return None  # per-layer observation required; single text cannot certify
        return sha256_hex(_normalize_text(payload).encode("utf-8")) == expected_layers[0][1]

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=ContinuityDimension.PROOF_TEXT,
        extract_expected=lambda: expected_token,
        extract_observed=extract,
        matches=matches,
    )


def _voice_verdict(
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
) -> _DimensionVerdict:
    valid_voices = sorted(
        {
            window.voice_by_character[c]
            for c in window.speaking_character_ids
            if c in window.voice_by_character
        }
    )
    expected = ",".join(valid_voices)

    def extract(w: ObservedContinuityWindow) -> str | None:
        return None if w.voice_ids is None else ",".join(sorted(w.voice_ids))

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=ContinuityDimension.THAI_VOICE,
        extract_expected=lambda: expected,
        extract_observed=extract,
        matches=lambda payload: all(voice in valid_voices for voice in payload.split(",")),
    )


def _subtitle_verdict(
    window: ExpectedContinuityWindow,
    observed: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
    safe_area_bp: tuple[int, int, int, int],
) -> _DimensionVerdict:
    x0, y0, x1, y1 = safe_area_bp

    def extract(w: ObservedContinuityWindow) -> str | None:
        if w.subtitle_rect_bp is None:
            return None
        rx0, ry0, rx1, ry1 = w.subtitle_rect_bp
        return f"rect=({rx0},{ry0},{rx1},{ry1})"

    def matches(payload: str) -> bool | None:
        numbers = payload[len("rect=(") : -1].split(",")
        rx0, ry0, rx1, ry1 = (int(n) for n in numbers)
        return rx0 >= x0 and ry0 >= y0 and rx1 <= x1 and ry1 <= y1

    return _verdict(
        expected_window=window,
        observed_windows=observed,
        evaluator=evaluator,
        dimension=ContinuityDimension.SUBTITLE_SAFE_AREA,
        extract_expected=lambda: f"subtitle inside safe area bp=({x0},{y0},{x1},{y1})",
        extract_observed=extract,
        matches=matches,
    )


#: The emitted evidence note prefixes visual-defect findings whose root cause may
#: live in a source sheet (owned by the T042a preflight, before render).
_VISUAL_NOTE = "actual-media continuity window; " + SOURCE_STAGE_NOTE


def continuity_findings(
    *,
    run_key: str,
    episode_id: UUID,
    asset_id: UUID,
    asset_sha256: str,
    duration_ms: int,
    observation: ContinuityObservation | None,
    frozen_sha256: str | None,
    expectations: EpisodeContinuityExpectations | None,
    safe_area_bp: tuple[int, int, int, int] = DEFAULT_SUBTITLE_SAFE_AREA_BP,
) -> tuple[list[QAFinding], list[CheckCoverageWindow], dict[str, object]]:
    """Emit per-check timecoded continuity findings plus per-check coverage.

    ``observation``/``frozen_sha256`` must come from the frozen observation
    (``frozen_sha256`` is verified against the observation's own digest, so a
    mutated observation cannot slip into comparison). ``expectations`` is the
    typed expected side. Either side may be missing: every dependent finding is
    then a typed UNKNOWN with non-CHECKED coverage — never a PASS.
    """
    evidence: dict[str, object]
    findings: list[QAFinding] = []
    coverage: list[CheckCoverageWindow] = []

    if observation is not None:
        if observation.media_sha256 != asset_sha256:
            raise SchemaInvalid(
                "the frozen observation describes different media bytes than the "
                "asset under review; it can never certify this asset",
                observed_media_sha256=observation.media_sha256[:16],
                asset_sha256=asset_sha256[:16],
            )
        if frozen_sha256 is None or frozen_sha256 != observation.observation_sha256():
            raise SchemaInvalid("continuity comparison requires the frozen observation digest")
        fixture = observation.source_label == SOURCE_FIXTURE
        evidence = {
            "observation_sha256": frozen_sha256,
            "media_sha256": observation.media_sha256,
            "evaluator": {
                "id": observation.evaluator.evaluator_id,
                "version": observation.evaluator.evaluator_version,
                "source_label": observation.evaluator.source_label,
                "capability_sha256": observation.evaluator.capability_sha256(),
            },
            "sampled_ranges_ms": [list(span) for span in observation.sampled_ranges_ms[:16]],
            "window_count": len(observation.windows),
            "fixture_id": observation.fixture_id,
            "source_label": observation.source_label,
            "registered": fixture,
        }
    else:
        fixture = False
        evidence = {
            "observation_sha256": None,
            "media_sha256": asset_sha256,
            "evaluator": None,
            "sampled_ranges_ms": [],
            "window_count": 0,
            "fixture_id": None,
            "source_label": None,
            "registered": False,
        }

    def add(
        spec: CheckSpec,
        start_ms: int,
        end_ms: int,
        outcome: QAOutcome,
        cov: CoverageStatus,
        expected: str | None,
        observed: str | None,
        note: str | None,
    ) -> None:
        visual = spec.family in (CheckFamily.VISUAL_IDENTITY, CheckFamily.TEMPORAL)
        if outcome is QAOutcome.REPAIRABLE:
            severity = spec.severity
        elif outcome is QAOutcome.PASS:
            severity = Severity.INFO
        else:
            severity = Severity.MAJOR
        source_note = note or ""
        if visual and outcome is not QAOutcome.UNKNOWN:
            source_note = f"{source_note}; {_VISUAL_NOTE}" if source_note else _VISUAL_NOTE
        prefix = f"fixture-truth:{observation.fixture_id}; " if fixture else ""
        findings.append(
            build_finding(
                run_key=run_key,
                episode_id=episode_id,
                asset_id=asset_id,
                start_ms=start_ms,
                end_ms=end_ms,
                check_id=spec.check_id,
                family=spec.family,
                severity=severity,
                outcome=outcome,
                coverage=cov,
                expected=expected,
                observed=observed,
                evidence_source=(
                    EvidenceSource.FAKE_FIXTURE if fixture else EvidenceSource.MEASURED_BENCHMARK
                ),
                evidence_ref=f"continuity:{asset_sha256[:16]}:{start_ms}",
                evidence_note=(prefix + source_note)[:2000],
                provenance=(Provenance.ORIGINAL_FIXTURE if fixture else Provenance.DERIVED_LOCAL),
                repair_targets=(
                    list(spec.repair_targets) if outcome is QAOutcome.REPAIRABLE else None
                ),
            )
        )

    span = (0, max(duration_ms, 1))

    # No observation source at all: one typed UNKNOWN per check, whole media.
    if observation is None:
        for spec in sorted(CHECK_SPECS.values(), key=lambda spec: spec.check_id):
            add(
                spec,
                *span,
                QAOutcome.UNKNOWN,
                CoverageStatus.UNAVAILABLE,
                None,
                None,
                "no continuity observation source configured; this check never passes",
            )
            coverage.append(
                _unavailable_window(
                    asset_id, spec.check_id, span, "no continuity observation source configured"
                )
            )
        return findings, coverage, evidence

    registered = observation.source_label != SOURCE_UNREGISTERED
    # No typed expectations: the media was observed but nothing was compared.
    if expectations is None:
        note = "no typed continuity expectations configured; observed media was not compared"
        for spec in sorted(CHECK_SPECS.values(), key=lambda spec: spec.check_id):
            add(spec, *span, QAOutcome.UNKNOWN, CoverageStatus.UNAVAILABLE, None, None, note)
            coverage.append(_unavailable_window(asset_id, spec.check_id, span, note))
        return findings, coverage, evidence

    evaluator = observation.evaluator
    for window in expectations.windows:
        overlapping = [
            w
            for w in observation.windows
            if w.start_ms < window.end_ms and window.start_ms < w.end_ms
        ]
        for dimension, spec in sorted(CHECK_SPECS.items(), key=lambda item: item[1].check_id):
            if not dimension_applies(dimension, window):
                continue
            if not registered:
                add(
                    spec,
                    window.start_ms,
                    window.end_ms,
                    QAOutcome.UNKNOWN,
                    CoverageStatus.UNAVAILABLE,
                    None,
                    None,
                    "media is not registered with any continuity observation source",
                )
                coverage.append(
                    _unavailable_window(
                        asset_id,
                        spec.check_id,
                        (window.start_ms, window.end_ms),
                        "media not registered with a continuity observation source",
                    )
                )
                continue
            verdict = _verdict_for(dimension, window, overlapping, evaluator, safe_area_bp)
            start = verdict.checked_ranges[0][0] if verdict.checked_ranges else window.start_ms
            end = verdict.checked_ranges[-1][1] if verdict.checked_ranges else window.end_ms
            add(
                spec,
                start,
                end,
                verdict.outcome,
                verdict.coverage,
                verdict.expected,
                verdict.observed,
                verdict.note,
            )
            coverage.extend(
                _check_coverage_windows(asset_id, spec.check_id, window, verdict.checked_ranges)
            )
    return findings, coverage, evidence


def _verdict_for(
    dimension: ContinuityDimension,
    window: ExpectedContinuityWindow,
    overlapping: Sequence[ObservedContinuityWindow],
    evaluator: ContinuityEvaluator,
    safe_area_bp: tuple[int, int, int, int],
) -> _DimensionVerdict:
    if dimension is ContinuityDimension.IDENTITY:
        return _identity_verdict(window, overlapping, evaluator)
    if dimension is ContinuityDimension.OUTFIT:
        return _mapping_verdict(
            window=window,
            observed=overlapping,
            evaluator=evaluator,
            dimension=dimension,
            expected_map=window.outfit_by_character,
            observed_map_of=lambda w: w.outfit_by_character,
            unobserved_note="assigned outfit not observed",
        )
    if dimension is ContinuityDimension.PROP_HOLDER:
        return _mapping_verdict(
            window=window,
            observed=overlapping,
            evaluator=evaluator,
            dimension=dimension,
            expected_map=window.holder_by_prop,
            observed_map_of=lambda w: w.holder_by_prop,
            unobserved_note="prop holder not observed",
        )
    if dimension is ContinuityDimension.LOCATION_SPACE:
        return _location_verdict(window, overlapping, evaluator)
    if dimension is ContinuityDimension.EYELINE_HANDOFF:
        return _pair_text_verdict(
            window=window,
            observed=overlapping,
            evaluator=evaluator,
            dimension=dimension,
            expected_eyeline=window.eyeline,
            expected_handoff=window.action_handoff,
        )
    if dimension is ContinuityDimension.PROOF_TEXT:
        return _proof_text_verdict(window, overlapping, evaluator)
    if dimension is ContinuityDimension.THAI_VOICE:
        return _voice_verdict(window, overlapping, evaluator)
    return _subtitle_verdict(window, overlapping, evaluator, safe_area_bp)


def _unavailable_window(
    asset_id: UUID, check_id: str, span: tuple[int, int], note: str
) -> CheckCoverageWindow:
    return CheckCoverageWindow(
        asset_id=asset_id,
        check_id=check_id,
        start_ms=span[0],
        end_ms=span[1],
        status=CoverageStatus.UNAVAILABLE,
        note=note[:200],
    )


def _check_coverage_windows(
    asset_id: UUID,
    check_id: str,
    window: ExpectedContinuityWindow,
    checked_ranges: Sequence[tuple[int, int]],
) -> list[CheckCoverageWindow]:
    """Per-check coverage inside one expected window: CHECKED spans + UNSAMPLED gaps."""
    out: list[CheckCoverageWindow] = []
    cursor = window.start_ms
    for start, end in _merge(_clip(checked_ranges, window.start_ms, window.end_ms)):
        if start > cursor:
            out.append(
                CheckCoverageWindow(
                    asset_id=asset_id,
                    check_id=check_id,
                    start_ms=cursor,
                    end_ms=start,
                    status=CoverageStatus.UNSAMPLED,
                    note="window not sampled for this check",
                )
            )
        out.append(
            CheckCoverageWindow(
                asset_id=asset_id,
                check_id=check_id,
                start_ms=start,
                end_ms=end,
                status=CoverageStatus.CHECKED,
            )
        )
        cursor = end
    if cursor < window.end_ms or not checked_ranges:
        out.append(
            CheckCoverageWindow(
                asset_id=asset_id,
                check_id=check_id,
                start_ms=cursor,
                end_ms=window.end_ms,
                status=CoverageStatus.UNSAMPLED,
                note="window not sampled for this check",
            )
        )
    return out


def summarize_check_coverage(
    windows: Sequence[CheckCoverageWindow], *, max_entries: int = 24
) -> dict[str, object]:
    """Bounded per-check coverage summary for run-event payloads (16 KiB cap)."""
    by_check: dict[str, list[CheckCoverageWindow]] = {}
    for window in windows:
        by_check.setdefault(window.check_id, []).append(window)
    summary: dict[str, object] = {}
    for check_id, check_windows in sorted(by_check.items()):
        entries = [
            [w.start_ms, w.end_ms, w.status.value]
            for w in sorted(check_windows, key=lambda w: (w.start_ms, w.end_ms))
        ]
        summary[check_id] = {
            "window_count": len(entries),
            "checked_ms": sum(
                w.end_ms - w.start_ms for w in check_windows if w.status is CoverageStatus.CHECKED
            ),
            "windows": entries[:max_entries],
            "truncated": len(entries) > max_entries,
        }
    return summary


# --- offline calibration (OFFLINE_FIXTURE_ONLY) ----------------------------------------


@dataclass(frozen=True)
class LabeledContinuityCase:
    """One labeled offline fixture: media, its declared truth, expectations, labels.

    ``defect_check_ids`` names the checks the fixture is designed to trip (its
    ground truth). Applicability by shot class is derived from the expectation
    windows' own ``shot_class`` values (a check applies where the typed
    expectations define it), never from the labels. Fixture labels verify
    software behavior only — never a real-model score.
    """

    case_id: str
    media_path: Path
    asset_sha256: str
    duration_ms: int
    expectations: EpisodeContinuityExpectations
    defect_check_ids: frozenset[str]


@dataclass
class CheckCalibration:
    """Confusion counts plus coverage for one check id over the labeled set.

    Mutable by design: the calibration runner is the only writer and folds one
    case at a time; the finished report is frozen.
    """

    applicable_cases: int = 0
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    unknown_cases: int = 0
    coverage_counts: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, object]:
        return {
            "applicable_cases": self.applicable_cases,
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "unknown_cases": self.unknown_cases,
            "coverage": dict(sorted(self.coverage_counts.items())),
        }


CALIBRATION_LABEL = "OFFLINE_FIXTURE_ONLY"


@dataclass(frozen=True)
class ContinuityCalibrationReport:
    """Deterministic report over the labeled offline set.

    ``label`` is ``OFFLINE_FIXTURE_ONLY`` and ``live_activation_enabled`` is
    ``False`` by construction: these scores verify the software's behavior on
    declared fixture truth. They cannot qualify a real vision/ASR model or
    claim measured real-world accuracy (T031 owns that evidence), and no live
    release gating may be derived from them.
    """

    label: str = CALIBRATION_LABEL
    live_activation_enabled: bool = False
    case_count: int = 0
    per_check: dict[str, CheckCalibration] = field(default_factory=dict)
    applicability_by_shot_class: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_payload(self) -> dict[str, object]:
        return {
            "label": self.label,
            "live_activation_enabled": self.live_activation_enabled,
            "case_count": self.case_count,
            "per_check": {
                check_id: calibration.as_payload()
                for check_id, calibration in sorted(self.per_check.items())
            },
            "applicability_by_shot_class": {
                shot_class: dict(sorted(checks.items()))
                for shot_class, checks in sorted(self.applicability_by_shot_class.items())
            },
        }


def _case_run_key(case: LabeledContinuityCase) -> str:
    return canonical_hash(
        {
            "case": case.case_id,
            "asset": case.asset_sha256,
            "expectations": case.expectations.expectations_sha256(),
            "lane": "qa.continuity.calibration",
        }
    )


def run_continuity_calibration(
    cases: Sequence[LabeledContinuityCase],
    observer: ContinuityObserver,
    *,
    safe_area_bp: tuple[int, int, int, int] = DEFAULT_SUBTITLE_SAFE_AREA_BP,
    asset_id: UUID | None = None,
) -> ContinuityCalibrationReport:
    """Run the continuity evaluator over a labeled offline set, deterministically.

    Determinism: cases are processed in given order, counts keyed by check id;
    the same inputs always produce the same report. TP = flagged and labeled
    defective; FP = flagged but not labeled; TN = PASS and not labeled; FN =
    labeled but not flagged; applicable-but-unobserved cases count as
    ``unknown_cases`` (never as TN — an unobserved dimension is not a pass).
    Applicability by shot class comes from each expectation window's own
    ``shot_class`` (where the typed expectations define the check), not from
    the case labels. Coverage counts are per emitted coverage window
    (CHECKED/UNSAMPLED/...); they are evidence of what ran, never a score.
    """
    probe_asset = asset_id or UUID(int=0)
    per_check: dict[str, CheckCalibration] = {
        spec.check_id: CheckCalibration() for spec in CHECK_SPECS.values()
    }
    applicability: dict[str, dict[str, int]] = {}
    for case in cases:
        observation = observer.observe_continuity(
            asset_id=probe_asset,
            asset_sha256=case.asset_sha256,
            media_path=case.media_path,
            duration_ms=case.duration_ms,
        )
        frozen = observation.observation_sha256()
        findings, coverage, _evidence = continuity_findings(
            run_key=_case_run_key(case),
            episode_id=case.expectations.episode_id,
            asset_id=probe_asset,
            asset_sha256=case.asset_sha256,
            duration_ms=case.duration_ms,
            observation=observation,
            frozen_sha256=frozen,
            expectations=case.expectations,
            safe_area_bp=safe_area_bp,
        )
        flagged = {
            finding.check_id
            for finding in findings
            if finding.outcome in (QAOutcome.REPAIRABLE, QAOutcome.BLOCKED)
        }
        passed = {finding.check_id for finding in findings if finding.outcome is QAOutcome.PASS}
        unknown = {finding.check_id for finding in findings if finding.outcome is QAOutcome.UNKNOWN}
        # Which checks each shot class can even apply to (typed expectations).
        for window in case.expectations.windows:
            shot_counts = applicability.setdefault(window.shot_class, {})
            for dimension, spec in CHECK_SPECS.items():
                if dimension_applies(dimension, window):
                    shot_counts[spec.check_id] = shot_counts.get(spec.check_id, 0) + 1
        for check_id, calibration in per_check.items():
            if check_id not in (flagged | passed | unknown):
                continue
            calibration.applicable_cases += 1
            if check_id in flagged:
                if check_id in case.defect_check_ids:
                    calibration.tp += 1
                else:
                    calibration.fp += 1
            elif check_id in unknown:
                calibration.unknown_cases += 1
            elif check_id in case.defect_check_ids:
                calibration.fn += 1
            else:
                calibration.tn += 1
        for window in coverage:
            calibration = per_check[window.check_id]
            calibration.coverage_counts[window.status.value] = (
                calibration.coverage_counts.get(window.status.value, 0) + 1
            )
    return ContinuityCalibrationReport(
        label=CALIBRATION_LABEL,
        live_activation_enabled=False,
        case_count=len(cases),
        per_check=per_check,
        applicability_by_shot_class=applicability,
    )


__all__ = [
    "CALIBRATION_LABEL",
    "CONTINUITY_CHECK_IDS",
    "CHECK_SPECS",
    "DEFAULT_SUBTITLE_SAFE_AREA_BP",
    "SOURCE_FIXTURE",
    "SOURCE_STAGE_NOTE",
    "SOURCE_UNREGISTERED",
    "CheckCalibration",
    "CheckSpec",
    "ContinuityCalibrationReport",
    "ContinuityDimension",
    "ContinuityEvaluator",
    "ContinuityExpectations",
    "ContinuityObservation",
    "ContinuityObserver",
    "EpisodeContinuityExpectations",
    "ExpectedContinuityWindow",
    "FixtureContinuityObserver",
    "LabeledContinuityCase",
    "ObservedContinuityWindow",
    "continuity_findings",
    "dimension_applies",
    "observation_from_truth",
    "run_continuity_calibration",
    "summarize_check_coverage",
]

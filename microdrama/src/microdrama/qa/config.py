"""Bounded knobs for the technical/audio/visual QA lane (T017).

Detector thresholds are configuration, not code. Prices are configuration too: the
offline fixture observer is free by default, so nothing is reserved; ``observer_price``
is the QA_CAPTIONS budget hook — when a price is configured the full discipline runs
(a real reservation is held BEFORE the observation step and the usage is settled after
it, and a failed observation keeps its charge rather than being released as unbilled).
"""

from __future__ import annotations

from dataclasses import dataclass

from microdrama.contracts.cost import PriceQuote

# Check ids that must be PASS (not REPAIRABLE/BLOCKED/UNKNOWN) before a QA run can be
# called green. Anything not listed here is surfaced but does not gate the summary.
CRITICAL_CHECK_IDS: tuple[str, ...] = (
    "technical.decode",
    "technical.audio_present",
    "asr.critical_term_match",
    "asr.speaker_match",
    "asr.line_present",
    "visual_identity.match",
    "caption.critical_term_match",
    "caption.cue_within_media",
    "caption.release_claim",
    "temporal.black_frames",
    "temporal.frozen_frames",
)

# Default release-availability claim phrases a caption must not make while the claimed
# episode is not released (the wrong-CTA seeded defect). Configuration, never script.
DEFAULT_UNRELEASED_CLAIM_PHRASES: tuple[str, ...] = ("ดูได้แล้วตอนนี้",)


@dataclass(frozen=True)
class QAConfig:
    """Bounded knobs. Defaults are fixture-scale so detector runs stay CPU-cheap."""

    # ffmpeg analysis bounds.
    ffmpeg_timeout_ms: int = 60_000
    max_media_duration_ms: int = 320_000
    probe_tolerance_ms: int = 250
    # Silence / peaks (actual audio measured through ffmpeg).
    silence_min_ms: int = 200
    silence_noise_db: int = -50
    max_silence_ms: int = 2_000
    peak_max_db: float = -0.1
    # Temporal detectors.
    black_min_ms: int = 200
    black_pix_th: float = 0.10
    freeze_min_ms: int = 300
    freeze_noise_db: int = -40
    # Caption content policy.
    unreleased_claim_phrases: tuple[str, ...] = DEFAULT_UNRELEASED_CLAIM_PHRASES
    # Text alignment between an observed segment/cue and an intended script line.
    align_min_ratio: float = 0.6
    # Budget hook: price a paid observation/ASR step would be charged. None (default)
    # means the offline fixture observer is free and nothing is reserved.
    observer_price: PriceQuote | None = None
    reservation_ttl_ms: int = 900_000
    # Check ids gating the green summary (subset of the ids this lane emits).
    critical_check_ids: tuple[str, ...] = CRITICAL_CHECK_IDS

    def __post_init__(self) -> None:
        if self.ffmpeg_timeout_ms < 1_000:
            raise ValueError("ffmpeg_timeout_ms must be at least 1 s")
        if self.max_media_duration_ms < 1_000:
            raise ValueError("max_media_duration_ms must allow at least a 1 s media")
        if self.silence_min_ms < 50 or self.freeze_min_ms < 50 or self.black_min_ms < 50:
            raise ValueError("detector minimum durations must be at least 50 ms")
        if self.max_silence_ms < self.silence_min_ms:
            raise ValueError("max_silence_ms must be at least silence_min_ms")
        if self.peak_max_db > 0:
            raise ValueError("peak_max_db is a dB ceiling and cannot be positive")
        if not 0.0 < self.align_min_ratio <= 1.0:
            raise ValueError("align_min_ratio must be in (0, 1]")
        if self.reservation_ttl_ms < 60_000:
            raise ValueError("reservation_ttl_ms must be at least one minute")
        unknown = set(self.critical_check_ids) - set(CRITICAL_CHECK_IDS)
        if unknown:
            raise ValueError(f"unknown critical check ids: {sorted(unknown)}")

    @property
    def duration_tolerance_ms(self) -> int:
        return self.probe_tolerance_ms


__all__ = ["CRITICAL_CHECK_IDS", "DEFAULT_UNRELEASED_CLAIM_PHRASES", "QAConfig"]

"""Bounded knobs for the editing lane (T015).

Prices are configuration, not code: the export pipeline itself is local FFmpeg and
free, so no price is configured by default. ``transfer_price`` is the budget hook —
the CPU_STORAGE_TRANSFER reservation a future paid storage/transfer step must hold
before dispatch; a None price means no paid step exists and nothing is reserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from microdrama.contracts.cost import PriceQuote

# Thai-capable font families tried in this order (deterministic fallback chain).
THAI_FONT_CANDIDATES: tuple[str, ...] = (
    "Loma",
    "Garuda",
    "Norasi",
    "Waree",
    "Sarabun",
    "Noto Sans Thai",
)


@dataclass(frozen=True)
class EditingConfig:
    """Bounded knobs. Defaults are fixture-scale so exports stay CPU-cheap."""

    output_width: int = 360
    output_height: int = 640
    fps_num: int = 24
    fps_den: int = 1
    sample_rate_hz: int = 48_000
    channels: int = 2
    # Deterministic room-tone bed (continuous ambience under the whole timeline).
    room_seed: int = 42
    room_amplitude: float = 0.02
    room_gain_millibel: int = -1_800
    # Dialogue placement inside a shot.
    dialogue_lead_in_ms: int = 200
    inter_line_gap_ms: int = 150
    # Caption spotting.
    cue_tail_pad_ms: int = 120
    min_cue_ms: int = 500
    caption_locales: tuple[str, ...] = ("th-TH", "en-US")
    burn_locale: str = "th-TH"
    burn_font_size: int = 18
    # Thai-safe font handling.
    font_candidates: tuple[str, ...] = THAI_FONT_CANDIDATES
    font_dirs: tuple[str, ...] = field(default_factory=tuple)
    # CPU bounding: refuse to export anything longer than this (no stress loops).
    max_export_duration_ms: int = 320_000
    ffmpeg_timeout_ms: int = 120_000
    probe_tolerance_ms: int = 120
    # Duration/technical-check tolerance for one frame plus mux rounding.
    reservation_ttl_ms: int = 900_000
    # Budget hook: price a paid CPU/storage/transfer step would be charged. None
    # (default) means the pipeline runs no paid step and reserves nothing.
    transfer_price: PriceQuote | None = None

    def __post_init__(self) -> None:
        if self.output_width < 16 or self.output_height < 16:
            raise ValueError("output frame must be at least 16x16")
        if self.output_width % 2 or self.output_height % 2:
            raise ValueError("output frame sides must be even")
        if self.fps_num < 1 or self.fps_den < 1:
            raise ValueError("fps numerator and denominator must be positive")
        if self.burn_locale not in self.caption_locales:
            raise ValueError("burn_locale must be one of caption_locales")
        if self.max_export_duration_ms < 1_000:
            raise ValueError("max_export_duration_ms must allow at least a 1 s export")
        if self.ffmpeg_timeout_ms < 1_000:
            raise ValueError("ffmpeg_timeout_ms must be at least 1 s")
        if not self.font_candidates:
            raise ValueError("at least one font candidate family is required")

    @property
    def frame_ms(self) -> int:
        return round(1_000 * self.fps_den / self.fps_num)

    @property
    def duration_tolerance_ms(self) -> int:
        return self.frame_ms + self.probe_tolerance_ms


__all__ = ["EditingConfig", "THAI_FONT_CANDIDATES"]

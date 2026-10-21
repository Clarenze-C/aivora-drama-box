"""Capability-aware static cover derivation from accepted master assets (T016).

A cover is one still frame pulled from the episode's actually-assembled review
master (the burned export when present, the clean master otherwise) at a
deterministic timestamp, center-cropped to each destination account's tested
aspect ratios. The only FFmpeg involved is a single-frame extract through T015's
argument-safe ``FFmpegRunner`` (explicit argv, tmp paths only, bounded timeout) —
reused by import, never duplicated. No provider, no job, no reservation.

Measured image facts: the shared runner's prober requires a stream duration,
which a still image does not have, so cover assets are registered without
``MediaInfo`` (contract-legal for IMAGE assets) and the derivation record carries
the intended frame dimensions instead — noted honestly, not papered over.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from microdrama.contracts.enums import Platform
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.media import CropSpec, OutputFormat
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Identifier,
    PositiveInt,
    ShortText,
)
from microdrama.contracts.release import CapabilityRecord
from microdrama.editing.ffmpeg import FFmpegRunner
from microdrama.editing.variants import DEFAULT_RATIO, center_crop, variant_frame


class CoverSpec(ContractModel):
    """One planned cover: destination ratio, frame size and source timestamp."""

    variant_key: Identifier
    ratio: str = Field(pattern=r"^\d+:\d+$")
    width: PositiveInt
    height: PositiveInt
    timestamp_ms: int = Field(ge=0)
    crop: CropSpec | None


class CoverBlocker(ContractModel):
    platform: Platform
    account_ref: AccountRef
    reason: ShortText


class CoverPlan(ContractModel):
    specs: list[CoverSpec] = Field(default_factory=list)
    blockers: list[CoverBlocker] = Field(default_factory=list)
    notes: list[ShortText] = Field(default_factory=list)


def plan_cover_specs(
    record: CapabilityRecord,
    *,
    master: OutputFormat,
    master_duration_ms: int,
) -> CoverPlan:
    """One cover per tested aspect ratio, at the master's midpoint frame.

    Unknown limits stay typed: a record without aspect ratios falls back to 9:16
    with a note; a malformed ratio token is a blocker, never a crash.
    """
    notes: list[str] = []
    ratios = list(record.limits.aspect_ratios)
    if not ratios:
        ratios = [DEFAULT_RATIO]
        notes.append(
            f"{record.platform.value}/{record.account_ref}: no aspect ratios recorded; "
            f"cover defaults to {DEFAULT_RATIO}"
        )
    timestamp = master_duration_ms // 2
    specs: list[CoverSpec] = []
    blockers: list[CoverBlocker] = []
    seen: set[str] = set()
    for ratio in ratios:
        if ratio in seen:
            continue
        seen.add(ratio)
        try:
            width, height = variant_frame(master.width, master.height, ratio)
            crop = center_crop(master.width, master.height, ratio)
        except SchemaInvalid:
            blockers.append(
                CoverBlocker(
                    platform=record.platform,
                    account_ref=record.account_ref,
                    reason=f"unsupported aspect ratio token {ratio!r}",
                )
            )
            continue
        specs.append(
            CoverSpec(
                variant_key=f"{record.platform.value.lower()}-{ratio.replace(':', 'x')}",
                ratio=ratio,
                width=width,
                height=height,
                timestamp_ms=timestamp,
                crop=crop,
            )
        )
    return CoverPlan(specs=specs, blockers=blockers, notes=notes)


def run_cover_extract(
    runner: FFmpegRunner,
    *,
    master_name: str,
    spec: CoverSpec,
    output: str,
) -> Path:
    """Extract one deterministic cover frame (input-seek, crop, scale, single frame)."""
    crop = ""
    if spec.crop is not None:
        crop = f"crop={spec.crop.width}:{spec.crop.height}:{spec.crop.x}:{spec.crop.y},"
    runner.export(
        [
            "-ss",
            f"{spec.timestamp_ms / 1000:.3f}",
            "-i",
            master_name,
            "-frames:v",
            "1",
            "-vf",
            f"{crop}scale={spec.width}:{spec.height},setsar=1",
            "-q:v",
            "2",
        ],
        output=runner.workdir / output,
    )
    return runner.workdir / output


__all__ = [
    "CoverBlocker",
    "CoverPlan",
    "CoverSpec",
    "plan_cover_specs",
    "run_cover_extract",
]

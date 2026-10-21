"""Capability-aware platform variants and crop-aware exports (T016).

Variants are EDL re-cuts of the episode's ALREADY ACCEPTED assets: the same clips
the assembled master was built from, re-framed for a destination account's tested
capability limits (aspect ratios, duration bounds) with captions burned in the
configured locale. Nothing here renders new video through a provider: the only
FFmpeg work is the same local, free export discipline T015 established, reusing
``editing.ffmpeg.FFmpegRunner`` by import.

Planning is pure and deterministic:

- ``plan_variant_specs`` turns one ``CapabilityRecord`` (T006) into concrete
  ``VariantSpec``s — one per tested aspect ratio — or into typed blockers when the
  account's duration limits cannot carry this episode. Unknown limits (no aspect
  ratios recorded) fall back to 9:16 with a typed note, never silently.
- ``build_variant_edl`` re-cuts the accepted main EDL into a variant EDL: same
  timeline, same dialogue/ambience placement, video clips carrying a source-space
  center ``CropSpec`` computed from EACH source asset's measured dimensions (mixed
  source sizes crop correctly), or no crop when a source already matches the ratio.
- ``plan_cropped_master``/``run_cropped_export`` extend T015's export graph with
  the crop stage. The audio graph mirrors ``export.plan_master``'s logic verbatim
  (that file is frozen this wave); this is the documented consequence, not a fork.
- ``FramingChange`` records what a crop removes — a re-framed cut changes what the
  viewer sees, so the lost pixels are logged, never implied (packet acceptance).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import Field

from microdrama.contracts.enums import Platform, TrackKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import CropSpec, EditDecisionList, EdlClip, OutputFormat
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    Identifier,
    LocaleTag,
    PositiveInt,
    ShortText,
)
from microdrama.contracts.release import CapabilityRecord
from microdrama.editing.config import EditingConfig
from microdrama.editing.edl import EDITING_NAMESPACE, edl_id_for
from microdrama.editing.export import MasterPlan
from microdrama.editing.ffmpeg import FFmpegRunner

DEFAULT_RATIO = "9:16"


# --- geometry ---------------------------------------------------------------------------


def parse_ratio(text: str) -> tuple[int, int]:
    """Parse a capability-record ratio token ("9:16") into (numerator, denominator)."""
    try:
        width_text, _, height_text = text.partition(":")
        num, den = int(width_text), int(height_text)
    except ValueError:
        raise SchemaInvalid("unsupported aspect ratio token", ratio=text) from None
    if num < 1 or den < 1:
        raise SchemaInvalid("aspect ratio sides must be positive", ratio=text)
    return num, den


def round_even(value: float, *, minimum: int = 16) -> int:
    """Deterministic even pixel rounding with the contract's 16px floor."""
    return max(minimum, int(value / 2 + 0.5) * 2)


def variant_frame(master_w: int, master_h: int, ratio: str) -> tuple[int, int]:
    """Target frame for one ratio: the largest even fit inside the master frame."""
    num, den = parse_ratio(ratio)
    if master_w * den > master_h * num:  # master is wider than the target ratio
        height = round_even(master_h)
        return round_even(master_h * num / den), height
    width = round_even(master_w)
    return width, round_even(master_w * den / num)


def _even(value: int) -> int:
    return value - value % 2


def center_crop(src_w: int, src_h: int, ratio: str) -> CropSpec | None:
    """Center crop of one source frame to a target ratio; None when it already fits.

    Dimensions are even (encoder-safe) and stay inside the source frame.
    """
    num, den = parse_ratio(ratio)
    if src_w * den == src_h * num:
        return None
    if src_w * den > src_h * num:  # source wider than the target: trim the sides
        crop_w = min(round_even(src_h * num / den), _even(src_w))
        return CropSpec(x=(src_w - crop_w) // 2, y=0, width=crop_w, height=_even(src_h))
    crop_h = min(round_even(src_w * den / num), _even(src_h))
    return CropSpec(x=0, y=(src_h - crop_h) // 2, width=_even(src_w), height=crop_h)


def punch_in_crop(src_w: int, src_h: int, *, keep: float = 0.85) -> CropSpec:
    """Center punch-in crop (a tighter framing of the same footage)."""
    crop_w = min(round_even(src_w * keep), _even(src_w))
    crop_h = min(round_even(src_h * keep), _even(src_h))
    return CropSpec(x=(src_w - crop_w) // 2, y=(src_h - crop_h) // 2, width=crop_w, height=crop_h)


def uuid5_name(kind: str, key: str) -> UUID:
    """Deterministic editing-namespace id (the house idempotency pattern)."""
    return uuid5(EDITING_NAMESPACE, f"{kind}:{key}")


# --- planning ---------------------------------------------------------------------------


class VariantSpec(ContractModel):
    """One planned destination variant: ratio + frame + caption treatment."""

    platform: Platform
    account_ref: AccountRef
    provider_route: Identifier | None = None
    variant_key: Identifier
    ratio: str = Field(pattern=r"^\d+:\d+$")
    width: PositiveInt
    height: PositiveInt
    burn_locale: LocaleTag
    cover: bool = True


class VariantBlocker(ContractModel):
    """Why one account gets no variant. Typed and surfaced, never silently dropped."""

    platform: Platform
    account_ref: AccountRef
    reason: ShortText


class VariantPlan(ContractModel):
    specs: list[VariantSpec] = Field(default_factory=list)
    blockers: list[VariantBlocker] = Field(default_factory=list)
    notes: list[ShortText] = Field(default_factory=list)


def plan_variant_specs(
    record: CapabilityRecord,
    *,
    master: OutputFormat,
    episode_duration_ms: int,
    burn_locale: str,
) -> VariantPlan:
    """Turn one tested capability record into variant specs (or typed blockers).

    Duration limits gate the whole account: a max duration under the episode's
    length means this route cannot carry the full episode, and a min duration over
    it means the episode is too short for the route — both are blockers, because a
    silent trim would destroy the episode and a silent pad would fabricate content.
    """
    notes: list[str] = []
    ratios = list(record.limits.aspect_ratios)
    if not ratios:
        ratios = [DEFAULT_RATIO]
        notes.append(
            f"{record.platform.value}/{record.account_ref}: no aspect ratios recorded; "
            f"defaulting to {DEFAULT_RATIO}"
        )
    max_ms = record.limits.max_duration_ms
    if max_ms is not None and episode_duration_ms > max_ms:
        return VariantPlan(
            blockers=[
                VariantBlocker(
                    platform=record.platform,
                    account_ref=record.account_ref,
                    reason=(
                        f"account max duration {max_ms} ms < episode {episode_duration_ms} ms; "
                        "a full-episode variant would need a destructive trim"
                    ),
                )
            ],
            notes=notes,
        )
    min_ms = record.limits.min_duration_ms
    if min_ms is not None and episode_duration_ms < min_ms:
        return VariantPlan(
            blockers=[
                VariantBlocker(
                    platform=record.platform,
                    account_ref=record.account_ref,
                    reason=(
                        f"account min duration {min_ms} ms > episode {episode_duration_ms} ms; "
                        "the episode is too short for this route"
                    ),
                )
            ],
            notes=notes,
        )
    specs: list[VariantSpec] = []
    blockers: list[VariantBlocker] = []
    seen: set[str] = set()
    for ratio in ratios:
        if ratio in seen:
            continue
        seen.add(ratio)
        try:
            width, height = variant_frame(master.width, master.height, ratio)
        except SchemaInvalid:
            blockers.append(
                VariantBlocker(
                    platform=record.platform,
                    account_ref=record.account_ref,
                    reason=f"unsupported aspect ratio token {ratio!r}",
                )
            )
            continue
        specs.append(
            VariantSpec(
                platform=record.platform,
                account_ref=record.account_ref,
                provider_route=record.provider_route,
                variant_key=f"{record.platform.value.lower()}-{ratio.replace(':', 'x')}",
                ratio=ratio,
                width=width,
                height=height,
                burn_locale=burn_locale,
            )
        )
    return VariantPlan(specs=specs, blockers=blockers, notes=notes)


# --- variant EDL construction --------------------------------------------------------------


def variant_semantic_hash(edl: EditDecisionList, *, variant_key: str) -> str:
    """Crop- and variant-aware semantic hash (T015's ``edl_semantic_hash`` omits crops)."""
    return canonical_hash(
        {
            "variant_key": variant_key,
            "purpose": edl.purpose.value,
            "output": edl.output.model_dump(mode="json"),
            "clips": [
                [
                    c.clip_id,
                    str(c.source_asset_id),
                    c.source_in_ms,
                    c.source_out_ms,
                    c.timeline_in_ms,
                    None if c.crop is None else c.crop.model_dump(mode="json"),
                    c.gain_millibel,
                ]
                for c in sorted(edl.clips, key=lambda c: (c.timeline_in_ms, c.clip_id))
            ],
        }
    )


def variant_edl_id(episode_id: UUID, vhash: str) -> UUID:
    return edl_id_for(episode_id, vhash)


def variant_asset_id_for(vhash: str) -> UUID:
    """Content-addressed clean variant asset id (identical re-cuts replay)."""
    return uuid5_name("variant", vhash)


def variant_burned_asset_id_for(vhash: str, caption_body_hash: str) -> UUID:
    return uuid5_name("variant-burned", f"{vhash}:{caption_body_hash[:32]}")


def build_variant_edl(
    main_edl: EditDecisionList,
    spec: VariantSpec,
    *,
    source_dims: Mapping[UUID, tuple[int, int]],
) -> EditDecisionList:
    """Re-cut the accepted main EDL into one variant EDL (same timeline, new frame).

    Video clips gain a per-source center crop unless the source already matches the
    target ratio; dialogue and ambience placement is untouched (audio does not
    change with framing). The id/hash are deterministic in the inputs, so identical
    plans replay instead of re-exporting.
    """
    clips = [_reclip(clip, _crop_for(clip, spec.ratio, source_dims)) for clip in main_edl.clips]
    output = _output_for(main_edl, spec)
    vhash = variant_semantic_hash(
        EditDecisionList(
            edl_id=main_edl.edl_id,  # placeholder; the hash covers decisions, not ids
            episode_id=main_edl.episode_id,
            version=main_edl.version,
            purpose=main_edl.purpose,
            output=output,
            clips=clips,
        ),
        variant_key=spec.variant_key,
    )
    return EditDecisionList(
        edl_id=variant_edl_id(main_edl.episode_id, vhash),
        episode_id=main_edl.episode_id,
        version=1,
        purpose=main_edl.purpose,
        output=output,
        clips=clips,
    )


def _crop_for(
    clip: EdlClip, ratio: str, source_dims: Mapping[UUID, tuple[int, int]]
) -> CropSpec | None:
    if clip.track is not TrackKind.VIDEO:
        return clip.crop
    dims = source_dims.get(clip.source_asset_id)
    if dims is None:
        raise SchemaInvalid(
            "variant planning needs measured dimensions for every video source",
            asset_id=str(clip.source_asset_id),
        )
    return center_crop(dims[0], dims[1], ratio)


def _reclip(clip: EdlClip, crop: CropSpec | None) -> EdlClip:
    return EdlClip(
        clip_id=clip.clip_id,
        track=clip.track,
        source_asset_id=clip.source_asset_id,
        source_in_ms=clip.source_in_ms,
        source_out_ms=clip.source_out_ms,
        timeline_in_ms=clip.timeline_in_ms,
        crop=crop,
        gain_millibel=clip.gain_millibel,
        dialogue_line_ids=list(clip.dialogue_line_ids),
        transition_in=clip.transition_in,
        transition_ms=clip.transition_ms,
    )


def _output_for(main_edl: EditDecisionList, spec: VariantSpec) -> OutputFormat:
    return OutputFormat(
        width=spec.width,
        height=spec.height,
        fps_num=main_edl.output.fps_num,
        fps_den=main_edl.output.fps_den,
        sample_rate_hz=main_edl.output.sample_rate_hz,
        channels=main_edl.output.channels,
    )


class FramingChange(ContractModel):
    """What the re-frame does to what the viewer sees (logged, never implied)."""

    from_width: PositiveInt
    from_height: PositiveInt
    to_width: PositiveInt
    to_height: PositiveInt
    cropped: bool
    lost_pixels: Count
    lost_area_bp: int = Field(ge=0, le=10_000, strict=True)
    detail: ShortText


def framing_change(
    master: OutputFormat, spec: VariantSpec, crops: Sequence[CropSpec | None]
) -> FramingChange:
    """Summarize the framing change across a variant's video clips."""
    applied = [crop for crop in crops if crop is not None]
    if not applied:
        return FramingChange(
            from_width=master.width,
            from_height=master.height,
            to_width=spec.width,
            to_height=spec.height,
            cropped=False,
            lost_pixels=0,
            lost_area_bp=0,
            detail=(
                f"{master.width}x{master.height} -> {spec.width}x{spec.height} "
                "with framing preserved (sources already match the ratio)"
            ),
        )
    worst = max(applied, key=lambda crop: crop.width * crop.height)
    src_w = worst.width + 2 * worst.x
    src_h = worst.height + 2 * worst.y
    lost = src_w * src_h - worst.width * worst.height
    return FramingChange(
        from_width=src_w,
        from_height=src_h,
        to_width=spec.width,
        to_height=spec.height,
        cropped=True,
        lost_pixels=lost,
        lost_area_bp=round(10_000 * lost / (src_w * src_h)),
        detail=(
            f"center crop {src_w}x{src_h} -> {worst.width}x{worst.height} for {spec.ratio} "
            f"(loses {lost} px, {round(100 * lost / (src_w * src_h))}% of the frame), "
            f"scaled to {spec.width}x{spec.height}"
        ),
    )


# --- crop-aware export graph ---------------------------------------------------------------


def _sec(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _fps(config: EditingConfig) -> str:
    return str(config.fps_num) if config.fps_den == 1 else f"{config.fps_num}/{config.fps_den}"


def plan_cropped_master(
    edl: EditDecisionList, config: EditingConfig, *, names: Mapping[UUID, str]
) -> MasterPlan:
    """T015's master graph with a crop stage: the EDL's explicit crops are honored.

    Video: trim -> (crop) -> scale/pad to the output frame -> fps/pixel format, then
    concat. Audio: identical discipline to ``export.plan_master`` — dialogue delayed
    to its exact timeline position over the room bed, one continuous mix.
    """
    video = sorted(
        (c for c in edl.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
    )
    dialogue = sorted(
        (c for c in edl.clips if c.track is TrackKind.DIALOGUE), key=lambda c: c.timeline_in_ms
    )
    room = sorted(
        (c for c in edl.clips if c.track is TrackKind.AMBIENCE), key=lambda c: c.timeline_in_ms
    )
    if not video:
        raise SchemaInvalid("an export needs at least one video clip")
    if not room:
        raise SchemaInvalid("an export needs the continuous room-tone bed")
    inputs: list[str] = []
    filters: list[str] = []
    audio_labels: list[str] = []
    index = 0
    width, height = edl.output.width, edl.output.height
    for clip in video:
        name = names.get(clip.source_asset_id)
        if name is None:
            raise SchemaInvalid("video clip source was not staged", clip_id=clip.clip_id)
        inputs += ["-i", name]
        crop = (
            f"crop={clip.crop.width}:{clip.crop.height}:{clip.crop.x}:{clip.crop.y},"
            if clip.crop is not None
            else ""
        )
        filters.append(
            f"[{index}:v]trim=start={_sec(clip.source_in_ms)}:end={_sec(clip.source_out_ms)},"
            f"setpts=PTS-STARTPTS,{crop}"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={_fps(config)},"
            f"format=yuv420p[v{index}]"
        )
        index += 1
    filters.append(
        f"{''.join(f'[v{i}]' for i in range(len(video)))}concat=n={len(video)}:v=1:a=0[vcut]"
    )
    for clip in dialogue:
        name = names.get(clip.source_asset_id)
        if name is None:
            raise SchemaInvalid("dialogue clip source was not staged", clip_id=clip.clip_id)
        inputs += ["-i", name]
        gain = f"volume={clip.gain_millibel / 1000:.2f}dB," if clip.gain_millibel else ""
        filters.append(
            f"[{index}:a]atrim=start={_sec(clip.source_in_ms)}:end={_sec(clip.source_out_ms)},"
            f"asetpts=PTS-STARTPTS,aresample={config.sample_rate_hz},"
            f"aformat=channel_layouts=stereo,"
            f"{gain}adelay={clip.timeline_in_ms}|{clip.timeline_in_ms}[a{index}]"
        )
        audio_labels.append(f"[a{index}]")
        index += 1
    for clip in room:
        name = names.get(clip.source_asset_id)
        if name is None:
            raise SchemaInvalid("room-tone source was not staged", clip_id=clip.clip_id)
        inputs += ["-i", name]
        filters.append(
            f"[{index}:a]atrim=start={_sec(clip.source_in_ms)}:end={_sec(clip.source_out_ms)},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={clip.gain_millibel / 1000:.2f}dB,"
            f"aresample={config.sample_rate_hz},aformat=channel_layouts=stereo,"
            f"adelay={clip.timeline_in_ms}|{clip.timeline_in_ms}[a{index}]"
        )
        audio_labels.append(f"[a{index}]")
        index += 1
    filters.append(
        f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:normalize=0:duration=longest,"
        f"atrim=start=0:end={_sec(edl.duration_ms)},asetpts=PTS-STARTPTS,"
        f"aresample={config.sample_rate_hz},aformat=channel_layouts=stereo[aout]"
    )
    return MasterPlan(inputs=inputs, filter_complex=";".join(filters))


def run_cropped_export(
    runner: FFmpegRunner,
    *,
    edl: EditDecisionList,
    config: EditingConfig,
    names: Mapping[UUID, str],
    output: str,
) -> Path:
    """Export one EDL through the argument-safe runner (codec args mirror T015)."""
    plan = plan_cropped_master(edl, config, names=names)
    runner.export(
        [
            *plan.inputs,
            "-filter_complex",
            plan.filter_complex,
            "-map",
            plan.video_map,
            "-map",
            plan.audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "35",
            "-pix_fmt",
            "yuv420p",
            "-r",
            _fps(config),
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ar",
            str(config.sample_rate_hz),
            "-ac",
            str(config.channels),
            "-t",
            _sec(edl.duration_ms),
        ],
        output=runner.workdir / output,
    )
    return runner.workdir / output


__all__ = [
    "DEFAULT_RATIO",
    "FramingChange",
    "VariantBlocker",
    "VariantPlan",
    "VariantSpec",
    "build_variant_edl",
    "center_crop",
    "framing_change",
    "parse_ratio",
    "plan_cropped_master",
    "plan_variant_specs",
    "punch_in_crop",
    "round_even",
    "run_cropped_export",
    "uuid5_name",
    "variant_asset_id_for",
    "variant_burned_asset_id_for",
    "variant_edl_id",
    "variant_frame",
    "variant_semantic_hash",
]

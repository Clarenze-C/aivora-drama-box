"""Normalization, continuous mix and clean/burned exports from an EDL (T015).

The export is a pure function of the EDL plus the staged source bytes:

- normalization: every video clip is trimmed to its explicit source in/out, scaled
  with letterbox padding to the output frame, conformed to the output fps/pixel
  format; every audio stream is conformed to the output sample rate and channel
  layout (SPEC §9 "normalize timebases/frame rate/dimensions/audio");
- continuous room/audio mix: dialogue clips are delayed to their exact timeline
  positions and mixed over one room-tone bed that spans the whole timeline, so
  ambience never drops out between lines;
- clean master and burned caption exports run through the argument-safe
  ``FFmpegRunner``; the burn goes through the libass ``subtitles`` filter with the
  explicitly resolved Thai font staged into the workdir (proper Thai shaping; plain
  ``drawtext`` cannot stack combining marks and is never used for Thai).

All filter graphs are built from typed EDL fields — script text never enters an
argument list; caption bytes travel in an SRT file inside the tmp workdir.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from microdrama.contracts.enums import TrackKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.media import EditDecisionList
from microdrama.editing.config import EditingConfig
from microdrama.editing.ffmpeg import FFmpegRunner


def _sec(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _fps(config: EditingConfig) -> str:
    return str(config.fps_num) if config.fps_den == 1 else f"{config.fps_num}/{config.fps_den}"


@dataclass(frozen=True)
class MasterPlan:
    """The argv pieces of the clean-master export (pure; unit-testable)."""

    inputs: list[str]  # "-i <staged name>" flattened as ["-i", name, ...]
    filter_complex: str
    video_map: str = "[vcut]"
    audio_map: str = "[aout]"


def plan_master(
    edl: EditDecisionList, config: EditingConfig, *, names: dict[UUID, str]
) -> MasterPlan:
    """Build the filter graph that realizes the EDL. Deterministic for one EDL."""
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
        filters.append(
            f"[{index}:v]trim=start={_sec(clip.source_in_ms)}:end={_sec(clip.source_out_ms)},"
            f"setpts=PTS-STARTPTS,"
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
            f"[{index}:a]atrim=start=0:end={_sec(clip.source_out_ms)},asetpts=PTS-STARTPTS,"
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


def plan_burn(*, srt_name: str, font_family: str, config: EditingConfig) -> list[str]:
    """Video-filter arguments that burn one SRT through libass with the Thai font."""
    style = (
        f"FontName={font_family},FontSize={config.burn_font_size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,"
        "Shadow=0,Alignment=2,MarginV=40"
    )
    return [
        "-vf",
        f"subtitles=filename={srt_name}:fontsdir=.:force_style='{style}'",
    ]


def render_room_tone(
    runner: FFmpegRunner, *, output: str, duration_ms: int, config: EditingConfig
) -> Path:
    """Deterministic room-tone WAV (seeded noise) spanning the whole timeline."""
    src = (
        f"anoisesrc=color=pink:seed={config.room_seed}:"
        f"sample_rate={config.sample_rate_hz}:amplitude={config.room_amplitude}"
    )
    runner.export(
        [
            "-f",
            "lavfi",
            "-i",
            src,
            "-t",
            _sec(duration_ms),
            "-c:a",
            "pcm_s16le",
            "-ar",
            str(config.sample_rate_hz),
            "-ac",
            "2",
        ],
        output=runner.workdir / output,
    )
    return runner.workdir / output


def run_master_export(
    runner: FFmpegRunner,
    *,
    edl: EditDecisionList,
    config: EditingConfig,
    names: dict[UUID, str],
    output: str,
) -> Path:
    plan = plan_master(edl, config, names=names)
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


def run_burned_export(
    runner: FFmpegRunner,
    *,
    master_name: str,
    srt_name: str,
    font_family: str,
    config: EditingConfig,
    output: str,
) -> Path:
    args = [
        "-i",
        master_name,
        *plan_burn(srt_name=srt_name, font_family=font_family, config=config),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "35",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
    ]
    runner.export(args, output=runner.workdir / output)
    return runner.workdir / output


__all__ = [
    "MasterPlan",
    "plan_burn",
    "plan_master",
    "render_room_tone",
    "run_burned_export",
    "run_master_export",
]

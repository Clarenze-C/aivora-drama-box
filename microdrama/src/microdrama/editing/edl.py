"""Deterministic EDL construction from the story manifest and measured assets (T015).

The EDL is explicit source/timeline cuts (SPEC §9): every video clip names its source
asset, source in/out and timeline in; every dialogue clip places one measured line
audio asset; one continuous ambience clip spans the whole timeline so the room never
drops out between lines. Nothing is inferred from text: shot order comes from the
manifest's ``sequence``, durations from measured media (ffprobe), and the whole EDL
hash is derived from the shot prompt digests plus the source asset hashes — so the
same inputs always produce the same EDL, and any story or source change produces a
different one (which is what drives invalidation).

Placement rules are strict and typed: dialogue that would run past its shot's end is
a typed ``Conflict`` (no silent squeeze or truncation), and a video timeline that
does not tile [0, duration] exactly is rejected by the frozen contract validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.contracts.enums import SlotKind, TrackKind
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import EditDecisionList, EdlClip, OutputFormat
from microdrama.contracts.season import DialogueLine, Script, Shot, ShotManifest
from microdrama.editing.config import EditingConfig
from microdrama.story.prompts import build_shot_prompt

EDITING_NAMESPACE = uuid5(NAMESPACE_URL, "https://microdrama.invalid/editing/v1")

MAIN_VARIANT = "main"


def edl_id_for(episode_id: UUID, edl_hash: str) -> UUID:
    return uuid5(EDITING_NAMESPACE, f"edl:{episode_id}:{edl_hash[:32]}")


def master_asset_id_for(edl_hash: str) -> UUID:
    """Content-addressed clean-master asset id (byte-stable exports replay)."""
    return uuid5(EDITING_NAMESPACE, f"master:{edl_hash}")


def burned_asset_id_for(edl_hash: str, caption_body_hash: str) -> UUID:
    return uuid5(EDITING_NAMESPACE, f"burned:{edl_hash}:{caption_body_hash[:32]}")


def caption_track_id_for(episode_id: UUID, locale: str, body_hash: str) -> UUID:
    return uuid5(EDITING_NAMESPACE, f"captions:{episode_id}:{locale}:{body_hash[:32]}")


def caption_asset_id_for(track_id: UUID) -> UUID:
    return uuid5(EDITING_NAMESPACE, f"caption-file:{track_id}")


def room_asset_id_for(episode_id: UUID, prompt_digest: str) -> UUID:
    """Deterministic id of the locally generated continuous room-tone bed."""
    return uuid5(EDITING_NAMESPACE, f"room:{episode_id}:{prompt_digest[:32]}")


@dataclass(frozen=True)
class ShotSource:
    """One accepted shot video asset the EDL cuts from (measured by ffprobe)."""

    shot_id: str
    asset_id: UUID
    asset_sha256: str
    duration_ms: int


@dataclass(frozen=True)
class LineSource:
    """One measured dialogue audio asset (T011's LineAudio persisted as an asset)."""

    line_id: str
    asset_id: UUID
    asset_sha256: str
    duration_ms: int


def shot_prompt_digest(
    manifest: ShotManifest, script: Script, *, episode_number: int, title_th: str
) -> str:
    """Hash of every shot's ``build_shot_prompt`` output, in sequence order.

    Binding the EDL to this digest makes it sensitive to ANY story change (pattern,
    purpose, exact Thai lines, staging) — not just to asset bytes — while staying
    deterministic: the same inputs always hash identically.
    """
    lines_by_id: dict[str, DialogueLine] = {
        line.line_id: line for scene in script.scenes for line in scene.lines
    }
    parts = []
    for shot in sorted(manifest.shots, key=lambda s: s.sequence):
        lines = [lines_by_id[line_id] for line_id in shot.line_ids]
        parts.append(
            build_shot_prompt(shot, lines, episode_number=episode_number, title_th=title_th)
        )
    return canonical_hash({"prompts": parts})


def build_edl(
    *,
    episode_id: UUID,
    manifest: ShotManifest,
    script: Script,
    shot_sources: dict[str, ShotSource],
    line_sources: dict[str, LineSource],
    room_asset_id: UUID,
    config: EditingConfig,
    prompt_digest: str,
) -> EditDecisionList:
    """Deterministically lay the episode's shots, dialogue and room tone on a timeline.

    Video: shots in ``sequence`` order, each trimmed to its measured duration (or its
    target duration when the render came out longer), tiling [0, total] exactly.
    Dialogue: each shot's lines placed sequentially from the shot start with the
    configured lead-in and inter-line gap, using the measured audio durations.
    Ambience: one clip over the locally generated room-tone bed, spanning the whole
    timeline so the room is continuous under and between every line.
    """
    missing = sorted(shot.shot_id for shot in manifest.shots if shot.shot_id not in shot_sources)
    if missing:
        raise SchemaInvalid("manifest shots without an accepted video asset", missing=missing)
    clips: list[EdlClip] = []
    timeline_ms = 0
    for shot in sorted(manifest.shots, key=lambda s: s.sequence):
        source = shot_sources[shot.shot_id]
        if source.duration_ms <= 0:
            raise SchemaInvalid("shot source has no measured duration", shot_id=shot.shot_id)
        length = min(source.duration_ms, shot.target_duration_ms)
        clips.append(
            EdlClip(
                clip_id=f"{shot.shot_id}.v",
                track=TrackKind.VIDEO,
                source_asset_id=source.asset_id,
                source_in_ms=0,
                source_out_ms=length,
                timeline_in_ms=timeline_ms,
            )
        )
        clips.extend(_place_dialogue(shot, script, line_sources, timeline_ms, length, config))
        timeline_ms += length
    if timeline_ms <= 0:
        raise SchemaInvalid("the manifest has no shots to assemble")
    clips.append(
        EdlClip(
            clip_id="room.main",
            track=TrackKind.AMBIENCE,
            source_asset_id=room_asset_id,
            source_in_ms=0,
            source_out_ms=timeline_ms,
            timeline_in_ms=0,
            gain_millibel=config.room_gain_millibel,
        )
    )
    edl_hash = canonical_hash(
        {
            "episode_id": str(episode_id),
            "prompt_digest": prompt_digest,
            "clips": [
                [c.clip_id, str(c.source_asset_id), c.source_in_ms, c.source_out_ms]
                for c in sorted(clips, key=lambda c: (c.timeline_in_ms, c.clip_id))
            ],
            "output": [
                config.output_width,
                config.output_height,
                config.fps_num,
                config.fps_den,
            ],
        }
    )
    return EditDecisionList(
        edl_id=edl_id_for(episode_id, edl_hash),
        episode_id=episode_id,
        version=1,
        purpose=SlotKind.FULL_EPISODE,
        output=OutputFormat(
            width=config.output_width,
            height=config.output_height,
            fps_num=config.fps_num,
            fps_den=config.fps_den,
            sample_rate_hz=config.sample_rate_hz,
            channels=config.channels,
        ),
        clips=clips,
    )


def _place_dialogue(
    shot: Shot,
    script: Script,
    line_sources: dict[str, LineSource],
    shot_timeline_in: int,
    shot_length: int,
    config: EditingConfig,
) -> list[EdlClip]:
    lines_by_id = {line.line_id: line for scene in script.scenes for line in scene.lines}
    placed: list[EdlClip] = []
    cursor = shot_timeline_in + config.dialogue_lead_in_ms
    for line_id in shot.line_ids:
        line_source = line_sources.get(line_id)
        if line_source is None:
            raise SchemaInvalid(
                "dialogue line has no measured audio asset (references step not run?)",
                line_id=line_id,
            )
        if line_id not in lines_by_id:
            raise SchemaInvalid("shot names a line the script does not contain", line_id=line_id)
        end = cursor + line_source.duration_ms
        if end > shot_timeline_in + shot_length:
            raise Conflict(
                "dialogue overflows its shot; refusing to squeeze or truncate audio",
                shot_id=shot.shot_id,
                line_id=line_id,
                shot_end_ms=shot_timeline_in + shot_length,
                line_end_ms=end,
            )
        placed.append(
            EdlClip(
                clip_id=f"{shot.shot_id}.d.{line_id}",
                track=TrackKind.DIALOGUE,
                source_asset_id=line_source.asset_id,
                source_in_ms=0,
                source_out_ms=line_source.duration_ms,
                timeline_in_ms=cursor,
                dialogue_line_ids=[line_id],
            )
        )
        cursor = end + config.inter_line_gap_ms
    return placed


def edl_semantic_hash(edl: EditDecisionList) -> str:
    """Stable hash of the EDL's semantic content (ids excluded, decisions included)."""
    return canonical_hash(
        {
            "purpose": edl.purpose.value,
            "output": edl.output.model_dump(mode="json"),
            "clips": [
                [
                    c.clip_id,
                    str(c.source_asset_id),
                    c.source_in_ms,
                    c.source_out_ms,
                    c.timeline_in_ms,
                    c.gain_millibel,
                    c.transition_in.value,
                ]
                for c in sorted(edl.clips, key=lambda c: (c.timeline_in_ms, c.clip_id))
            ],
        }
    )


def video_gap_ranges(edl: EditDecisionList) -> list[tuple[int, int]]:
    """Timeline ranges not covered by any video clip (gap detection)."""
    video = sorted(
        (c for c in edl.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
    )
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for clip in video:
        if clip.timeline_in_ms > cursor:
            gaps.append((cursor, clip.timeline_in_ms))
        cursor = max(cursor, clip.timeline_out_ms)
    total = edl.duration_ms
    if cursor < total:
        gaps.append((cursor, total))
    return gaps


def ambience_covers_timeline(edl: EditDecisionList) -> bool:
    """True when ambience clips together cover [0, duration] (continuous room)."""
    spans = sorted(
        (c.timeline_in_ms, c.timeline_out_ms) for c in edl.clips if c.track is TrackKind.AMBIENCE
    )
    if not spans:
        return False
    cursor = 0
    for start, end in spans:
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor >= edl.duration_ms


__all__ = [
    "EDITING_NAMESPACE",
    "MAIN_VARIANT",
    "LineSource",
    "ShotSource",
    "ambience_covers_timeline",
    "build_edl",
    "burned_asset_id_for",
    "caption_asset_id_for",
    "caption_track_id_for",
    "edl_id_for",
    "edl_semantic_hash",
    "master_asset_id_for",
    "room_asset_id_for",
    "shot_prompt_digest",
    "video_gap_ranges",
]

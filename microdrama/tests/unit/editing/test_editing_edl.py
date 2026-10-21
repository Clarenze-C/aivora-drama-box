"""EDL construction tests (T015): explicit cuts, determinism, typed refusals.

Builder-level: no FFmpeg, no database — the EDL is a pure function of the manifest,
script, measured sources and config.
"""

from __future__ import annotations

import uuid

import pytest
from editing_support import LINES, SHOT_OF_LINE, SHOT_TARGETS, build_manifest, build_script

from microdrama.contracts.enums import TrackKind
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.editing.config import EditingConfig
from microdrama.editing.edl import (
    LineSource,
    ShotSource,
    ambience_covers_timeline,
    build_edl,
    edl_semantic_hash,
    room_asset_id_for,
    shot_prompt_digest,
    video_gap_ranges,
)

CONFIG = EditingConfig()


def _sources(lines=None):
    lines = lines if lines is not None else LINES
    episode_id = uuid.uuid4()
    script = build_script(episode_id, list(lines))
    manifest = build_manifest(episode_id, script)
    shot_sources = {
        shot_id: ShotSource(
            shot_id=shot_id,
            asset_id=uuid.uuid5(uuid.NAMESPACE_URL, shot_id),
            asset_sha256=f"{index:064x}",
            duration_ms=5_000,  # measured render longer than every target
        )
        for index, shot_id in enumerate(sorted(SHOT_TARGETS))
    }
    line_sources = {
        line_id: LineSource(
            line_id=line_id,
            asset_id=uuid.uuid5(uuid.NAMESPACE_URL, line_id),
            asset_sha256=f"{sha:064x}",
            duration_ms=actual_ms,
        )
        for index, (line_id, _speaker, _text, actual_ms) in enumerate(lines)
        for sha in [index]
    }
    digest = shot_prompt_digest(manifest, script, episode_number=1, title_th="ฤดูกาลทดสอบ")
    return episode_id, script, manifest, shot_sources, line_sources, digest


def _build(lines=None):
    episode_id, script, manifest, shots, line_sources, digest = _sources(lines)
    edl = build_edl(
        episode_id=episode_id,
        manifest=manifest,
        script=script,
        shot_sources=shots,
        line_sources=line_sources,
        room_asset_id=room_asset_id_for(episode_id, digest),
        config=CONFIG,
        prompt_digest=digest,
    )
    return edl, shots, line_sources


def test_same_inputs_produce_the_identical_edl() -> None:
    episode_id, script, manifest, shots, lines, digest = _sources()
    kwargs = dict(
        episode_id=episode_id,
        manifest=manifest,
        script=script,
        shot_sources=shots,
        line_sources=lines,
        room_asset_id=room_asset_id_for(episode_id, digest),
        config=CONFIG,
        prompt_digest=digest,
    )
    first = build_edl(**kwargs)
    second = build_edl(**kwargs)
    assert first.edl_id == second.edl_id
    assert first == second
    assert edl_semantic_hash(first) == edl_semantic_hash(second)
    assert [c.clip_id for c in first.clips] == [c.clip_id for c in second.clips]


def test_story_text_change_changes_the_edl() -> None:
    # Same asset bytes, different Thai line: the shot-prompt digest must move the EDL.
    episode_id, script, manifest, shots, lines, digest = _sources()
    kwargs = dict(
        episode_id=episode_id,
        manifest=manifest,
        shot_sources=shots,
        line_sources=lines,
        room_asset_id=room_asset_id_for(episode_id, digest),
        config=CONFIG,
        prompt_digest=digest,
    )
    baseline = build_edl(script=script, **kwargs)
    mutated_script = build_script(
        episode_id,
        [(lid, spk, text + "ค่ะ" if lid == "sc1-l3" else text, ms) for lid, spk, text, ms in LINES],
    )
    mutated_digest = shot_prompt_digest(
        build_manifest(episode_id, mutated_script),
        mutated_script,
        episode_number=1,
        title_th="ฤดูกาลทดสอบ",
    )
    changed = build_edl(
        script=mutated_script,
        prompt_digest=mutated_digest,
        room_asset_id=room_asset_id_for(episode_id, mutated_digest),
        **{
            k: v for k, v in kwargs.items() if k not in ("script", "prompt_digest", "room_asset_id")
        },
    )
    assert baseline.edl_id != changed.edl_id
    assert edl_semantic_hash(baseline) != edl_semantic_hash(changed)


def test_source_asset_change_changes_the_edl() -> None:
    episode_id, script, manifest, shots, lines, digest = _sources()
    kwargs = dict(
        episode_id=episode_id,
        manifest=manifest,
        script=script,
        line_sources=lines,
        room_asset_id=room_asset_id_for(episode_id, digest),
        config=CONFIG,
        prompt_digest=digest,
    )
    first = build_edl(shot_sources=shots, **kwargs)
    replaced = {
        shot_id: ShotSource(
            shot_id=shot_id,
            asset_id=uuid.uuid4(),
            asset_sha256="b" * 64,
            duration_ms=source.duration_ms,
        )
        for shot_id, source in shots.items()
    }
    second = build_edl(shot_sources=replaced, **kwargs)
    assert first.edl_id != second.edl_id
    assert edl_semantic_hash(first) != edl_semantic_hash(second)


def test_video_clips_tile_the_timeline_with_explicit_cuts() -> None:
    edl, shots, _ = _build()
    video = sorted(
        (c for c in edl.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
    )
    assert [c.source_asset_id for c in video] == [
        shots[shot_id].asset_id for shot_id in sorted(SHOT_TARGETS)
    ]
    assert video[0].timeline_in_ms == 0
    assert video[0].source_in_ms == 0
    # Measured render (5 s) longer than target: trimmed to the target, explicitly.
    assert video[0].duration_ms == SHOT_TARGETS["sh1"]
    assert video[1].timeline_in_ms == SHOT_TARGETS["sh1"]
    assert video[1].duration_ms == SHOT_TARGETS["sh2"]
    assert edl.duration_ms == sum(SHOT_TARGETS.values())
    assert video_gap_ranges(edl) == []


def test_dialogue_is_placed_from_measured_durations() -> None:
    edl, _, lines = _build()
    dialogue = sorted(
        (c for c in edl.clips if c.track is TrackKind.DIALOGUE), key=lambda c: c.timeline_in_ms
    )
    by_id = {ls.line_id: ls for ls in lines.values()}
    sh1_lines = [c for c in dialogue if SHOT_OF_LINE[c.dialogue_line_ids[0]] == "sh1"]
    # First line: shot start + lead-in; every clip's length is the MEASURED audio ms.
    assert sh1_lines[0].timeline_in_ms == CONFIG.dialogue_lead_in_ms
    assert all(c.duration_ms == by_id[c.dialogue_line_ids[0]].duration_ms for c in dialogue)
    # Second line starts after first line's audio plus the inter-line gap.
    gap = sh1_lines[1].timeline_in_ms - (sh1_lines[0].timeline_in_ms + sh1_lines[0].duration_ms)
    assert gap == CONFIG.inter_line_gap_ms


def test_room_bed_is_continuous_over_the_whole_timeline() -> None:
    edl, _, _ = _build()
    assert ambience_covers_timeline(edl)
    room = [c for c in edl.clips if c.track is TrackKind.AMBIENCE]
    assert len(room) == 1
    assert room[0].timeline_in_ms == 0
    assert room[0].duration_ms == edl.duration_ms


def test_dialogue_overflow_is_a_typed_conflict_never_squeezed() -> None:
    # 4 s target shot, but the two lines now measure far beyond it.
    long_lines = [
        ("sc1-l1", "fon", "หนี้ห้าหมื่นบาท", 2_500),
        ("sc1-l2", "lek", "แม่หนูไม่อยากให้หนูรู้", 2_200),
        ("sc1-l3", "fon", "ทำไมลุงถึงเคร่งเครียดแบบนี้คะ", 1_000),
    ]
    with pytest.raises(Conflict, match="overflows its shot") as exc:
        _build(long_lines)
    assert exc.value.details["line_id"] == "sc1-l2"


def test_missing_shot_source_is_a_typed_schema_error() -> None:
    episode_id, script, manifest, shots, lines, digest = _sources()
    shots.pop("sh2")
    with pytest.raises(SchemaInvalid, match="without an accepted video asset") as exc:
        build_edl(
            episode_id=episode_id,
            manifest=manifest,
            script=script,
            shot_sources=shots,
            line_sources=lines,
            room_asset_id=room_asset_id_for(episode_id, digest),
            config=CONFIG,
            prompt_digest=digest,
        )
    assert exc.value.details["missing"] == ["sh2"]


def test_missing_line_audio_is_a_typed_schema_error() -> None:
    episode_id, script, manifest, shots, lines, digest = _sources()
    lines.pop("sc1-l3")
    with pytest.raises(SchemaInvalid, match="no measured audio asset"):
        build_edl(
            episode_id=episode_id,
            manifest=manifest,
            script=script,
            shot_sources=shots,
            line_sources=lines,
            room_asset_id=room_asset_id_for(episode_id, digest),
            config=CONFIG,
            prompt_digest=digest,
        )


def test_edl_validates_against_the_frozen_contract() -> None:
    # EditDecisionList's own validators run on construction: overlap, ordering,
    # burn-in binding. A valid build passes; a gapped/overlapping one cannot exist.
    edl, _, _ = _build()
    assert edl.purpose.value == "FULL_EPISODE"
    assert edl.output.width == CONFIG.output_width
    assert {c.track for c in edl.clips} == {TrackKind.VIDEO, TrackKind.DIALOGUE, TrackKind.AMBIENCE}

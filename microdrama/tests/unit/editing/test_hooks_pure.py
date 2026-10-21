"""Pure hook planning tests (T016): payoff, treatments, reading load, typed refusals.

No database, no FFmpeg: an in-memory 32 s main EDL (the long fixture's shape) is
re-cut by the three treatments, proving payoff preservation, distinctness, the
20-40 s bounds and the honest counting of boundary-sliced lines.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from editing_support import build_script
from test_variants_support import LONG_LINES, LONG_SHOT_MS, build_long_manifest

from microdrama.contracts.enums import SlotKind, TrackKind
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.media import EditDecisionList, EdlClip, OutputFormat
from microdrama.editing.hooks import (
    HOOK_MAX_MS,
    HOOK_MIN_MS,
    TREATMENTS,
    build_hook_edl,
    payoff_window,
    plan_hook_candidates,
    reading_load,
    select_windows,
)

EPISODE = uuid4()
SHOT_ASSETS = {f"ksh{index + 1}": uuid4() for index in range(8)}
LINE_ASSETS = {line_id: uuid4() for line_id, *_rest in LONG_LINES}
ROOM = uuid4()
DIMS = {asset: (360, 640) for asset in SHOT_ASSETS.values()}


def main_edl() -> EditDecisionList:
    clips: list[EdlClip] = []
    for index, (line_id, _speaker, _text, actual_ms) in enumerate(LONG_LINES):
        start = index * LONG_SHOT_MS
        clips.append(
            EdlClip(
                clip_id=f"ksh{index + 1}.v",
                track=TrackKind.VIDEO,
                source_asset_id=SHOT_ASSETS[f"ksh{index + 1}"],
                source_in_ms=0,
                source_out_ms=LONG_SHOT_MS,
                timeline_in_ms=start,
            )
        )
        clips.append(
            EdlClip(
                clip_id=f"ksh{index + 1}.d.{line_id}",
                track=TrackKind.DIALOGUE,
                source_asset_id=LINE_ASSETS[line_id],
                source_in_ms=0,
                source_out_ms=actual_ms,
                timeline_in_ms=start + 200,
                dialogue_line_ids=[line_id],
            )
        )
    clips.append(
        EdlClip(
            clip_id="room.main",
            track=TrackKind.AMBIENCE,
            source_asset_id=ROOM,
            source_in_ms=0,
            source_out_ms=8 * LONG_SHOT_MS,
            timeline_in_ms=0,
        )
    )
    return EditDecisionList(
        edl_id=uuid4(),
        episode_id=EPISODE,
        version=1,
        purpose=SlotKind.FULL_EPISODE,
        output=OutputFormat(width=360, height=640, fps_num=24, fps_den=1),
        clips=clips,
    )


def plan(targets: tuple[int, int, int] = (24_000, 28_000, 32_000)):
    return plan_hook_candidates(
        main_edl=main_edl(),
        manifest=build_long_manifest(EPISODE),
        script=build_script(EPISODE, LONG_LINES),
        target_durations_ms=targets,
        source_dims=DIMS,
    )


def test_payoff_is_the_highest_importance_shot_with_dialogue() -> None:
    payoff = payoff_window(build_long_manifest(EPISODE), main_edl())
    assert payoff.shot_id == "ksh8"  # the only HIGH shot
    assert payoff.line_ids == ["kl8"]
    assert payoff.start_ms == 7 * LONG_SHOT_MS + 200
    assert payoff.duration_ms == LONG_LINES[7][3]


def test_payoff_ties_break_to_the_later_sequence() -> None:
    base = build_long_manifest(EPISODE)
    shots = [
        shot.model_copy(
            update={
                "dramatic_importance": ("HIGH" if shot.shot_id in {"ksh3", "ksh8"} else "MEDIUM")
            }
        )
        for shot in base.shots
    ]
    payoff = payoff_window(base.model_copy(update={"shots": shots}), main_edl())
    assert payoff.shot_id == "ksh8"  # tie between ksh3/ksh8 -> the later beat wins


def test_three_candidates_are_distinct_and_inside_the_bounds() -> None:
    result = plan()
    ids = [c.candidate.edl_id for c in result.candidates]
    assert len(set(ids)) == 3
    assert [c.candidate.treatment for c in result.candidates] == list(TREATMENTS)
    for candidate in result.candidates:
        assert HOOK_MIN_MS <= candidate.candidate.duration_ms <= HOOK_MAX_MS
        assert candidate.edl.purpose is SlotKind.HOOK
        assert candidate.edl.duration_ms == candidate.candidate.duration_ms
        assert candidate.candidate.source_asset_ids  # lineage back to accepted sources


def test_every_candidate_keeps_the_payoff_lines() -> None:
    result = plan()
    for candidate in result.candidates:
        spoken = {
            clip.dialogue_line_ids[0] for clip in candidate.edl.clips if clip.dialogue_line_ids
        }
        assert "kl8" in spoken, candidate.candidate.treatment


def test_treatments_really_differ_in_window_order() -> None:
    payoff = payoff_window(build_long_manifest(EPISODE), main_edl())
    cold = select_windows(
        "payoff_first_cold_open", timeline_ms=32_000, payoff=payoff, target_ms=24_000
    )
    chrono = select_windows(
        "chronological_tease", timeline_ms=32_000, payoff=payoff, target_ms=28_000
    )
    punch = select_windows(
        "punch_in_reaction",
        timeline_ms=32_000,
        payoff=payoff,
        target_ms=32_000,
        anchor_ms=16_000,
    )
    assert cold[0] == (payoff.start_ms, payoff.end_ms)  # payoff leads
    assert chrono[0][0] == 0  # opening first
    assert chrono[-1] == (payoff.start_ms, payoff.end_ms)
    assert punch[-1] == (payoff.start_ms, payoff.end_ms)
    assert punch[0][1] <= payoff.start_ms  # centered beat stays out of the payoff


def test_punch_in_candidate_crops_and_flags_changed_framing() -> None:
    result = plan()
    by_treatment = {c.candidate.treatment: c for c in result.candidates}
    punch = by_treatment["punch_in_reaction"]
    assert punch.candidate.changed_framing is True
    video = [c for c in punch.edl.clips if c.track is TrackKind.VIDEO]
    assert video and all(c.crop is not None for c in video)
    for name in ("payoff_first_cold_open", "chronological_tease"):
        assert by_treatment[name].candidate.changed_framing is False
        plain = [c for c in by_treatment[name].edl.clips if c.track is TrackKind.VIDEO]
        assert all(c.crop is None for c in plain)


def test_short_accepted_footage_is_a_typed_refusal() -> None:
    payoff = payoff_window(build_long_manifest(EPISODE), main_edl())
    with pytest.raises(SchemaInvalid, match="20 s hook floor"):
        select_windows("chronological_tease", timeline_ms=10_000, payoff=payoff, target_ms=24_000)


def test_oversized_payoff_is_a_typed_refusal_not_a_split() -> None:
    payoff = payoff_window(build_long_manifest(EPISODE), main_edl()).model_copy(
        update={"end_ms": 70_000}
    )
    with pytest.raises(SchemaInvalid, match="40 s hook ceiling"):
        select_windows(
            "payoff_first_cold_open", timeline_ms=80_000, payoff=payoff, target_ms=24_000
        )


def test_boundary_sliced_lines_are_dropped_and_counted_never_half_spoken() -> None:
    edl = main_edl()
    # kl1 lives at [200, 1600); a window slicing through its middle must drop it.
    windows = [(1_000, 6_000)]
    hook, dropped = build_hook_edl(
        main_edl=edl, windows=windows, candidate_id="hook-x", punch_in=False, source_dims=DIMS
    )
    assert dropped == 1
    spoken = {clip.dialogue_line_ids[0] for clip in hook.clips if clip.dialogue_line_ids}
    assert "kl1" not in spoken
    assert "kl2" in spoken  # [4200, 5500) sits fully inside the window


def test_windows_reorder_footage_on_the_hook_timeline() -> None:
    edl = main_edl()
    payoff = payoff_window(build_long_manifest(EPISODE), edl)
    hook, _dropped = build_hook_edl(
        main_edl=edl,
        windows=[(payoff.start_ms, payoff.end_ms), (0, 4_000)],
        candidate_id="hook-x",
        punch_in=False,
        source_dims=DIMS,
    )
    video = sorted(
        (c for c in hook.clips if c.track is TrackKind.VIDEO), key=lambda c: c.timeline_in_ms
    )
    # The payoff shot's frames play FIRST (window 0), the opening second.
    assert video[0].source_asset_id == SHOT_ASSETS["ksh8"]
    assert video[-1].source_asset_id == SHOT_ASSETS["ksh1"]
    assert hook.duration_ms == payoff.duration_ms + 4_000


def test_reading_load_compares_against_the_master() -> None:
    result = plan()
    for candidate in result.candidates:
        reading = candidate.reading
        assert reading.cue_count >= 1
        assert reading.chars_per_second >= 0
        assert "chars/s" in reading.note and "master" in reading.note
        assert candidate.candidate.reading_load_note == reading.note
    lighter = [c for c in result.candidates if c.reading.dropped_boundary_lines > 0]
    assert any("boundary line(s) dropped" in c.reading.note for c in result.candidates) or lighter


def test_reading_load_is_a_pure_measurement() -> None:
    edl = main_edl()
    hook, dropped = build_hook_edl(
        main_edl=edl,
        windows=[(0, 24_000)],
        candidate_id="hook-x",
        punch_in=False,
        source_dims=DIMS,
    )
    reading = reading_load(
        script=build_script(EPISODE, LONG_LINES),
        main_edl=edl,
        hook_edl=hook,
        dropped_boundary_lines=dropped,
    )
    included = {clip.dialogue_line_ids[0] for clip in hook.clips if clip.dialogue_line_ids}
    expected_chars = sum(len(text) for line_id, _s, text, _ms in LONG_LINES if line_id in included)
    assert reading.characters == expected_chars
    assert reading.duration_ms == hook.duration_ms


def test_plan_needs_exactly_three_targets() -> None:
    with pytest.raises(SchemaInvalid, match="exactly three"):
        plan((24_000, 28_000))


def test_hook_edl_tiles_video_and_keeps_one_room_bed() -> None:
    result = plan()
    for candidate in result.candidates:
        video = sorted(
            (c for c in candidate.edl.clips if c.track is TrackKind.VIDEO),
            key=lambda c: c.timeline_in_ms,
        )
        cursor = 0
        for clip in video:
            assert clip.timeline_in_ms == cursor  # contiguously re-tiled
            cursor = clip.timeline_out_ms
        assert cursor == candidate.edl.duration_ms
        room = [c for c in candidate.edl.clips if c.track is TrackKind.AMBIENCE]
        assert len(room) == 1
        assert room[0].timeline_in_ms == 0
        assert room[0].timeline_out_ms == candidate.edl.duration_ms
        assert room[0].source_asset_id == ROOM


def test_source_lineage_names_only_used_assets() -> None:
    result = plan()
    used = {clip.source_asset_id for candidate in result.candidates for clip in candidate.edl.clips}
    assert ROOM in used
    for candidate in result.candidates:
        assert set(candidate.candidate.source_asset_ids) <= used
        assert all(isinstance(a, UUID) for a in candidate.candidate.source_asset_ids)

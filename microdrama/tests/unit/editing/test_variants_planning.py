"""Pure planning tests (T016): capability-driven specs, crops, framing, determinism.

No database, no FFmpeg: these pin the deterministic planning layer — what the
capability record says becomes specs or typed blockers, and the variant EDL is a
pure function of the main EDL plus the spec.
"""

from __future__ import annotations

from uuid import uuid4

from test_variants_support import capability_record

from microdrama.contracts.enums import Platform, SlotKind, TrackKind
from microdrama.contracts.media import EditDecisionList, EdlClip, OutputFormat
from microdrama.editing.variants import (
    build_variant_edl,
    center_crop,
    framing_change,
    parse_ratio,
    plan_variant_specs,
    punch_in_crop,
    variant_frame,
    variant_semantic_hash,
)

SHOT_A = uuid4()
SHOT_B = uuid4()
LINE_A = uuid4()
ROOM = uuid4()


def _main_edl(width: int = 360, height: int = 640) -> EditDecisionList:
    return EditDecisionList(
        edl_id=uuid4(),
        episode_id=uuid4(),
        version=1,
        purpose=SlotKind.FULL_EPISODE,
        output=OutputFormat(width=width, height=height, fps_num=24, fps_den=1),
        clips=[
            EdlClip(
                clip_id="s1.v",
                track=TrackKind.VIDEO,
                source_asset_id=SHOT_A,
                source_in_ms=0,
                source_out_ms=4_000,
                timeline_in_ms=0,
            ),
            EdlClip(
                clip_id="s2.v",
                track=TrackKind.VIDEO,
                source_asset_id=SHOT_B,
                source_in_ms=0,
                source_out_ms=2_500,
                timeline_in_ms=4_000,
            ),
            EdlClip(
                clip_id="s1.d.l1",
                track=TrackKind.DIALOGUE,
                source_asset_id=LINE_A,
                source_in_ms=0,
                source_out_ms=1_400,
                timeline_in_ms=200,
                dialogue_line_ids=["l1"],
            ),
            EdlClip(
                clip_id="room.main",
                track=TrackKind.AMBIENCE,
                source_asset_id=ROOM,
                source_in_ms=0,
                source_out_ms=6_500,
                timeline_in_ms=0,
            ),
        ],
    )


def _specs(ratios: tuple[str, ...] = ("16:9", "1:1")):
    record = capability_record(ratios=ratios)
    return plan_variant_specs(
        record,
        master=OutputFormat(width=360, height=640, fps_num=24, fps_den=1),
        episode_duration_ms=240_000,
        burn_locale="th-TH",
    )


def test_ratios_from_the_capability_record_drive_the_specs() -> None:
    plan = _specs(("16:9", "1:1"))
    assert [s.variant_key for s in plan.specs] == ["tiktok-16x9", "tiktok-1x1"]
    assert [(s.width, s.height) for s in plan.specs] == [(360, 202), (360, 360)]
    assert all(s.burn_locale == "th-TH" for s in plan.specs)
    assert plan.blockers == []


def test_unrecorded_limits_fall_back_with_a_typed_note() -> None:
    plan = _specs(())
    assert [s.ratio for s in plan.specs] == ["9:16"]
    assert plan.notes and "no aspect ratios recorded" in plan.notes[0]


def test_duration_limits_are_blockers_never_silent_trims() -> None:
    too_long = plan_variant_specs(
        capability_record(max_duration_ms=60_000),
        master=OutputFormat(width=360, height=640, fps_num=24, fps_den=1),
        episode_duration_ms=240_000,
        burn_locale="th-TH",
    )
    assert too_long.specs == []
    assert "destructive trim" in too_long.blockers[0].reason
    too_short = plan_variant_specs(
        capability_record(min_duration_ms=300_000),
        master=OutputFormat(width=360, height=640, fps_num=24, fps_den=1),
        episode_duration_ms=240_000,
        burn_locale="th-TH",
    )
    assert too_short.specs == []
    assert "too short" in too_short.blockers[0].reason


def test_malformed_ratio_tokens_block_typed() -> None:
    plan = _specs(("wide", "16:9"))
    assert [s.ratio for s in plan.specs] == ["16:9"]
    assert "unsupported aspect ratio token" in plan.blockers[0].reason


def test_variant_edl_is_deterministic_and_crop_aware() -> None:
    main = _main_edl()
    spec = _specs(("16:9",)).specs[0]
    dims = {SHOT_A: (360, 640), SHOT_B: (360, 640)}
    first = build_variant_edl(main, spec, source_dims=dims)
    second = build_variant_edl(main, spec, source_dims=dims)
    assert first.edl_id == second.edl_id
    assert first.purpose is SlotKind.FULL_EPISODE
    # Video clips carry the center crop; dialogue and ambience are untouched.
    video = [c for c in first.clips if c.track is TrackKind.VIDEO]
    audio = [c for c in first.clips if c.track is not TrackKind.VIDEO]
    assert all(c.crop is not None for c in video)
    assert all(c.crop is None for c in audio)
    assert (first.output.width, first.output.height) == (360, 202)
    # Same timeline: a re-frame is not a re-time.
    assert first.duration_ms == main.duration_ms
    assert [c.timeline_in_ms for c in video] == [0, 4_000]


def test_sources_already_matching_the_ratio_get_no_crop() -> None:
    main = _main_edl()
    spec = _specs(("9:16",)).specs[0]
    variant = build_variant_edl(main, spec, source_dims={SHOT_A: (360, 640), SHOT_B: (360, 640)})
    assert all(c.crop is None for c in variant.clips if c.track is TrackKind.VIDEO)
    assert (
        variant.edl_id
        != build_variant_edl(
            main, _specs(("16:9",)).specs[0], source_dims={SHOT_A: (360, 640), SHOT_B: (360, 640)}
        ).edl_id
    )


def test_mixed_source_sizes_crop_per_source() -> None:
    main = _main_edl()
    spec = _specs(("16:9",)).specs[0]
    variant = build_variant_edl(main, spec, source_dims={SHOT_A: (720, 1280), SHOT_B: (360, 640)})
    crops = {c.clip_id: c.crop for c in variant.clips if c.track is TrackKind.VIDEO}
    assert crops["s1.v"].width == 720 and crops["s1.v"].height == 406
    assert crops["s2.v"].width == 360 and crops["s2.v"].height == 202


def test_missing_source_dimensions_are_a_typed_refusal() -> None:
    import pytest

    from microdrama.contracts.errors import SchemaInvalid

    main = _main_edl()
    spec = _specs(("16:9",)).specs[0]
    with pytest.raises(SchemaInvalid, match="measured dimensions"):
        build_variant_edl(main, spec, source_dims={})


def test_variant_hash_separates_crops_t015s_hash_cannot() -> None:
    main = _main_edl()
    spec = _specs(("16:9",)).specs[0]
    variant = build_variant_edl(main, spec, source_dims={SHOT_A: (360, 640), SHOT_B: (360, 640)})
    nocrop = variant.model_copy(
        update={
            "clips": [
                clip.model_copy(update={"crop": None}) if clip.crop is not None else clip
                for clip in variant.clips
            ]
        }
    )
    assert variant_semantic_hash(variant, variant_key="k") != variant_semantic_hash(
        nocrop, variant_key="k"
    )
    assert variant_semantic_hash(variant, variant_key="a") != variant_semantic_hash(
        variant, variant_key="b"
    )


def test_framing_change_logs_lost_pixels_and_preserved_cases() -> None:
    spec = _specs(("16:9",)).specs[0]
    crop = center_crop(360, 640, "16:9")
    assert crop is not None
    changed = framing_change(
        OutputFormat(width=360, height=640, fps_num=24, fps_den=1), spec, [crop, crop]
    )
    assert changed.cropped is True
    assert changed.lost_pixels == 360 * 640 - 360 * 202
    assert "loses" in changed.detail and "16:9" in changed.detail
    preserved = framing_change(
        OutputFormat(width=360, height=640, fps_num=24, fps_den=1), spec, [None, None]
    )
    assert preserved.cropped is False and preserved.lost_pixels == 0
    assert "framing preserved" in preserved.detail


def test_geometry_stays_inside_the_source_and_even() -> None:
    assert parse_ratio("9:16") == (9, 16)
    assert variant_frame(360, 640, "9:16") == (360, 640)
    wide = center_crop(640, 360, "9:16")
    assert wide is not None and (wide.width, wide.height) == (202, 360)
    punch = punch_in_crop(360, 640)
    assert punch.width % 2 == 0 and punch.height % 2 == 0
    assert punch.x >= 0 and punch.y >= 0
    assert punch.width + 2 * punch.x <= 360 and punch.height + 2 * punch.y <= 640
    matching = center_crop(360, 640, "9:16")
    assert matching is None  # already the target ratio: nothing to remove


def test_variant_spec_platform_comes_from_the_record() -> None:
    yt = plan_variant_specs(
        capability_record(platform=Platform.YOUTUBE, ratios=("9:16",)),
        master=OutputFormat(width=360, height=640, fps_num=24, fps_den=1),
        episode_duration_ms=240_000,
        burn_locale="th-TH",
    )
    assert yt.specs[0].platform is Platform.YOUTUBE
    assert yt.specs[0].variant_key == "youtube-9x16"


def test_punch_in_crop_keeps_eighty_five_percent() -> None:
    punch = punch_in_crop(360, 640)
    assert round(punch.width / 360, 2) == 0.85
    assert round(punch.height / 640, 2) == 0.85

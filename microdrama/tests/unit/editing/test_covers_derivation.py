"""Cover derivation tests (T016): real DB + store + single-frame local FFmpeg.

Covers are stills pulled from the episode's accepted review master (the burned
export), center-cropped per the destination account's tested ratios. Every extract
is one frame through the argument-safe runner on tmp paths only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from editing_support import World
from test_variants_support import TT_ACCOUNT, capability_record, record_capability, variants_service

from microdrama.contracts.enums import Platform
from microdrama.contracts.errors import SchemaInvalid
from microdrama.editing.config import EditingConfig
from microdrama.editing.covers import CoverSpec, run_cover_extract
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes
from microdrama.editing.variants_service import VariantTarget

pytestmark = pytest.mark.ffmpeg


def _assembled(world: World):
    episode_id, _season, assets = world.seed_prepared_episode()
    world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    return episode_id


def _target() -> VariantTarget:
    return VariantTarget(platform=Platform.TIKTOK, account_ref=TT_ACCOUNT)


def test_covers_derive_from_the_burned_master_end_to_end(world: World) -> None:
    episode_id = _assembled(world)
    record_capability(world, capability_record(ratios=("9:16", "1:1")))
    outcome = variants_service(world).derive_covers(episode_id, targets=[_target()])
    assert outcome.status.value == "ASSEMBLED"
    assert outcome.blockers == []
    assert [c.variant_key for c in outcome.covers] == ["tiktok-1x1", "tiktok-9x16"]
    for cover in outcome.covers:
        row = world.row(
            "SELECT descriptor, provenance, state, object_key FROM assets WHERE id = %s",
            (cover.asset_id,),
        )
        assert row["provenance"] == "DERIVED_LOCAL"
        assert row["state"] == "ACCEPTED"
        assert row["descriptor"]["asset_kind"] == "IMAGE"
        assert len(row["descriptor"]["lineage"]) == 1  # the review master only
        data = world.store.get_bytes(row["object_key"])
        assert data[:2] == b"\xff\xd8"  # real JPEG bytes, not an empty placeholder
    assert outcome.covers[0].width == 360 and outcome.covers[0].height == 360
    assert outcome.covers[1].timestamp_ms == 3_250  # midpoint of the 6.5 s master
    assert world.events(episode_id, "editing.covers_built")


def test_cover_extraction_is_byte_stable(world: World) -> None:
    data, _media = world.clips.clip(2_000)
    spec = CoverSpec(
        variant_key="tiktok-9x16",
        ratio="9:16",
        width=360,
        height=640,
        timestamp_ms=1_000,
        crop=None,
    )
    hashes = []
    for run in range(2):
        with TemporaryDirectory(prefix="md-cover-stable-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
            stage_bytes(runner, name="master.mp4", data=data)
            path = run_cover_extract(
                runner, master_name="master.mp4", spec=spec, output=f"cover-{run}.jpg"
            )
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_cover_extraction_crops_to_the_tested_ratio(world: World) -> None:
    from microdrama.editing.variants import center_crop

    data, _media = world.clips.clip(2_000)
    crop = center_crop(360, 640, "1:1")
    assert crop is not None
    spec = CoverSpec(
        variant_key="tiktok-1x1", ratio="1:1", width=360, height=360, timestamp_ms=500, crop=crop
    )
    with TemporaryDirectory(prefix="md-cover-crop-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
        stage_bytes(runner, name="master.mp4", data=data)
        path = run_cover_extract(runner, master_name="master.mp4", spec=spec, output="cover.jpg")
        assert path.stat().st_size > 0
        # The single invocation is an explicit argv list (argument-safe runner).
        assert all(isinstance(argv, tuple) for argv in runner.invocations)
        assert any("crop=360:360:0:140" in arg for argv in runner.invocations for arg in argv)


def test_cover_replays_idempotently(world: World) -> None:
    episode_id = _assembled(world)
    record_capability(world, capability_record(ratios=("9:16",)))
    service = variants_service(world)
    first = service.derive_covers(episode_id, targets=[_target()])
    second = service.derive_covers(episode_id, targets=[_target()])
    assert second.status.value == "REPLAYED"
    assert second.covers[0].asset_id == first.covers[0].asset_id
    assert second.covers[0].replayed is True
    rows = world.rows(
        "SELECT id FROM assets WHERE episode_id = %s AND asset_kind = 'IMAGE'", (episode_id,)
    )
    assert len(rows) == 1  # no duplicate cover rows


def test_cover_cpu_ceiling_refuses_before_any_ffmpeg_run(world: World) -> None:
    episode_id = _assembled(world)
    record_capability(world, capability_record(ratios=("9:16",)))
    narrow = variants_service(world, config=EditingConfig(max_export_duration_ms=3_000))
    with pytest.raises(SchemaInvalid, match="export ceiling"):
        narrow.derive_covers(episode_id, targets=[_target()])
    rows = world.rows(
        "SELECT id FROM assets WHERE episode_id = %s AND asset_kind = 'IMAGE'", (episode_id,)
    )
    assert rows == []


def test_cover_without_a_capability_record_is_a_typed_blocker(world: World) -> None:
    episode_id = _assembled(world)
    outcome = variants_service(world).derive_covers(episode_id, targets=[_target()])
    assert outcome.covers == []
    assert "no current capability record" in outcome.blockers[0].reason

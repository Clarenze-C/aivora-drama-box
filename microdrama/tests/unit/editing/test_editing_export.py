"""Export pipeline tests (T015): fixture episode end-to-end, checks, determinism.

These run the REAL local FFmpeg on fixture-scale clips (CPU-bounded by
``EditingConfig.max_export_duration_ms`` and the 5 s fixture cap).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from editing_support import World

from microdrama.contracts.errors import SchemaInvalid
from microdrama.editing.config import EditingConfig
from microdrama.editing.export import render_room_tone, run_master_export
from microdrama.editing.ffmpeg import FFmpegRunner

pytestmark = pytest.mark.ffmpeg


def _assemble(world: World):
    episode_id, season_id, assets = world.seed_prepared_episode()
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    return episode_id, season_id, assets, outcome


def test_original_fixture_episode_completes_end_to_end(world: World) -> None:
    episode_id, _season, _assets, outcome = _assemble(world)
    assert outcome.status.value == "ASSEMBLED"
    assert outcome.duration_ms == 6_500
    assert world.episode_state(episode_id) == "AI_REVIEW"
    # Both exports exist in the store with measured media info.
    for asset_id, sha in (
        (outcome.clean_asset_id, outcome.clean_sha256),
        (outcome.burned_asset_id, outcome.burned_sha256),
    ):  # noqa: E501
        row = world.row("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
        assert row is not None
        assert row["descriptor"]["sha256"] == sha
        assert row["descriptor"]["media"]["has_video"] is True
        assert row["descriptor"]["media"]["has_audio"] is True
    assert not outcome.findings, outcome.findings
    failures = [c.check_id for c in outcome.checks if c.outcome == "FAIL"]
    unknowns = [c.check_id for c in outcome.checks if c.outcome == "UNKNOWN"]
    assert failures == []
    assert unknowns == [], "nothing may silently stay unknown on this host"


def test_technical_checks_inspect_duration_streams_tiling_and_room(
    world: World,
) -> None:
    _episode, _season, _assets, outcome = _assemble(world)
    by_id = {c.check_id: c for c in outcome.checks}
    assert by_id["export.duration"].outcome == "PASS"
    assert by_id["export.streams"].outcome == "PASS"
    assert by_id["export.decode"].outcome == "PASS"
    assert by_id["edit.video_tiling"].outcome == "PASS"
    assert by_id["edit.room_continuity"].outcome == "PASS"
    assert by_id["caption.cue_bounds"].outcome == "PASS"
    assert by_id["burn.rendered"].outcome == "PASS"
    # Duration detail carries the measured probe, not the requested numbers.
    assert "6500" in by_id["export.duration"].detail


def test_master_and_burn_are_byte_stable_for_identical_inputs(world: World) -> None:
    """Same staged inputs run twice -> identical export bytes (documented determinism)."""
    config = EditingConfig()
    data, _media = world.clips.clip(2_000)
    hashes = []
    for run in range(2):
        with TemporaryDirectory(prefix="md-stable-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
            source = runner.workdir / "src.mp4"
            source.write_bytes(data)
            room = render_room_tone(runner, output="room.wav", duration_ms=2_000, config=config)
            from microdrama.contracts.enums import SlotKind, TrackKind
            from microdrama.contracts.media import EditDecisionList, EdlClip, OutputFormat

            asset_id = uuid4()
            edl = EditDecisionList(
                edl_id=uuid4(),
                episode_id=uuid4(),
                version=1,
                purpose=SlotKind.FULL_EPISODE,
                output=OutputFormat(
                    width=config.output_width,
                    height=config.output_height,
                    fps_num=config.fps_num,
                    fps_den=config.fps_den,
                ),
                clips=[
                    EdlClip(
                        clip_id="sh1.v",
                        track=TrackKind.VIDEO,
                        source_asset_id=asset_id,
                        source_in_ms=0,
                        source_out_ms=2_000,
                        timeline_in_ms=0,
                    ),
                    EdlClip(
                        clip_id="room.main",
                        track=TrackKind.AMBIENCE,
                        source_asset_id=uuid4(),
                        source_in_ms=0,
                        source_out_ms=2_000,
                        timeline_in_ms=0,
                    ),
                ],
            )
            out = run_master_export(
                runner,
                edl=edl,
                config=config,
                names={asset_id: "src.mp4", edl.clips[1].source_asset_id: room.name},
                output=f"master-{run}.mp4",
            )
            hashes.append(hashlib.sha256(out.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_room_tone_generation_is_deterministic(world: World) -> None:
    config = EditingConfig()
    hashes = []
    for _run in range(2):
        with TemporaryDirectory(prefix="md-room-") as tmp:
            runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
            path = render_room_tone(runner, output="room.wav", duration_ms=1_500, config=config)
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_normalization_conforms_frame_rate_dimensions_and_audio(world: World) -> None:
    _episode, _season, _assets, outcome = _assemble(world)
    row = world.row("SELECT descriptor FROM assets WHERE id = %s", (outcome.clean_asset_id,))
    media = row["descriptor"]["media"]
    config = world.service.config
    assert (media["width"], media["height"]) == (config.output_width, config.output_height)
    assert media["fps_num"] == config.fps_num and media["fps_den"] == config.fps_den
    assert media["sample_rate_hz"] == config.sample_rate_hz
    assert media["channels"] == config.channels


def test_export_ceiling_blocks_long_edls_before_any_ffmpeg_run(world: World) -> None:
    config = EditingConfig(max_export_duration_ms=3_000)
    from editing_support import World as WorldCls

    narrow = WorldCls(
        world.db,
        world.store,
        world.settings,
        world.clips,
        world.truth,
        config=config,
    )
    episode_id, _season, assets = narrow.seed_prepared_episode()
    with pytest.raises(SchemaInvalid, match="export ceiling"):
        narrow.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    # Typed refusal happened before the claim: state and claim column untouched.
    assert narrow.episode_state(episode_id) == "RENDERING"
    row = narrow.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))
    assert row["correlation_id"] is None

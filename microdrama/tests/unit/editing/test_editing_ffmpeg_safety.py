"""Argument-safety tests (T015): explicit argv, tmp-paths-only, hostile text.

FFmpeg is only ever invoked with an explicit argument list (no shell, no string
interpolation). Caption text and file names carrying shell metacharacters must
survive verbatim — they travel inside files, never inside an argument.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from editing_support import LINES, World

from microdrama.contracts.errors import SchemaInvalid
from microdrama.editing.ffmpeg import FFmpegRunner, stage_bytes

pytestmark = pytest.mark.ffmpeg

HOSTILE = "หนี้ ; rm -rf / && $(echo pwned) `id` \"quotes\" 'single' | pipe > out"


def test_every_invocation_is_an_explicit_argv_list(world: World) -> None:
    seen: list[object] = []
    real_run = subprocess.run

    def spy_run(argv, *args, **kwargs):  # noqa: ANN001, ANN002
        seen.append(argv)
        return real_run(argv, *args, **kwargs)

    with patch("microdrama.editing.ffmpeg.subprocess.run", side_effect=spy_run):
        episode_id, _season, assets = world.seed_prepared_episode()
        world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert seen, "the assembly must actually invoke ffmpeg/ffprobe"
    for argv in seen:
        assert isinstance(argv, list), "invocations are argv lists, never strings"
        assert argv[0].endswith(("ffmpeg", "ffprobe"))
        assert "rm -rf" not in " ".join(argv)


def test_paths_outside_the_workdir_are_refused_before_any_run(tmp_path: Path) -> None:
    with TemporaryDirectory(prefix="md-safe-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=10_000)
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"x")
        with pytest.raises(SchemaInvalid, match="temporary workdir"):
            runner.export(["-i", str(outside)], output=runner.workdir / "o.mp4")
        with pytest.raises(SchemaInvalid, match="temporary workdir"):
            runner.probe(outside)
        assert runner.invocations == []  # refused before any process ran


def test_filter_paths_embedded_in_graphs_are_checked_too(tmp_path: Path) -> None:
    with TemporaryDirectory(prefix="md-safe-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=10_000)
        evil = f"subtitles=filename={tmp_path}/evil.srt"
        with pytest.raises(SchemaInvalid, match="temporary workdir"):
            runner.export(["-vf", evil], output=runner.workdir / "o.mp4")
        assert runner.invocations == []


def test_timeout_floor_is_enforced(tmp_path: Path) -> None:
    with TemporaryDirectory(prefix="md-safe-") as tmp:
        with pytest.raises(SchemaInvalid, match="at least one second"):
            FFmpegRunner(workdir=Path(tmp), timeout_ms=10)


def test_hostile_caption_text_survives_the_burn_untouched(world: World) -> None:
    """A line full of shell metacharacters burns fine: text lives in the SRT file."""
    hostile_lines = [
        (lid, spk, f"{text} {HOSTILE}" if lid == "sc1-l2" else text, ms)
        for lid, spk, text, ms in LINES
    ]
    episode_id, _season, assets = world.seed_prepared_episode(lines=hostile_lines)
    outcome = world.service.assemble_episode(episode_id, shot_assets=assets["shots"])
    assert outcome.burned_asset_id is not None
    burn = next(c for c in outcome.checks if c.check_id == "burn.rendered")
    assert burn.outcome == "PASS"
    assert not [f for f in outcome.findings], "the text is data, not an injection"


def test_staging_copies_bytes_into_the_workdir(tmp_path: Path) -> None:
    with TemporaryDirectory(prefix="md-safe-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=10_000)
        path = stage_bytes(runner, name="src.bin", data=b"payload")
        assert path.read_bytes() == b"payload"
        assert path.parent == runner.workdir

"""Seeded media fixtures: probes match, defects are detectable by ffmpeg, partial outputs are distinguishable."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import wave
from pathlib import Path

import pytest

from microdrama.contracts.enums import Provenance
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.media import CaptionTrack
from microdrama.testing.media import (
    FixtureTruth,
    FixtureTruthRegistry,
    MediaProbeError,
    decodes_cleanly,
    detect_black,
    detect_frozen,
    detect_silence,
    make_clip,
    make_png_bytes,
    make_wav_bytes,
    probe,
)

pytestmark = pytest.mark.ffmpeg

TOLERANCE_MS = 150  # AAC priming and frame rounding


def _subtitles(path: Path) -> str:
    """Text of the first embedded subtitle track, extracted by ffmpeg."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
         "-map", "0:s:0", "-f", "srt", "-"],
        check=True, capture_output=True,
    )  # fmt: skip
    return out.stdout.decode("utf-8")


def test_clean_fixture_probes_to_the_declared_streams_and_duration(defect_suite) -> None:
    suite, _ = defect_suite
    info = probe(suite["clean"].path)
    assert abs(info.duration_ms - 5_000) <= TOLERANCE_MS
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (360, 640)
    assert info.video_codec == "h264" and info.audio_codec == "aac"
    assert info.sample_rate_hz == 48_000


def test_missing_audio_has_no_audio_stream(defect_suite) -> None:
    suite, _ = defect_suite
    info = probe(suite["missing_audio"].path)
    assert info.has_audio is False and info.has_video is True
    assert info.audio_codec is None


def test_silence_gap_is_detected_where_the_line_was_removed(defect_suite) -> None:
    suite, _ = defect_suite
    gaps = detect_silence(suite["silence_gap"].path, min_ms=500)
    # The removed line leaves one silent run: the gaps either side of it merge (2.1 s to 3.9 s).
    assert any(abs(start - 2.1) < 0.15 and abs(end - 3.9) < 0.15 for start, end in gaps), gaps


def test_clean_media_has_no_long_silence(defect_suite) -> None:
    suite, _ = defect_suite
    assert detect_silence(suite["clean"].path, min_ms=500) == []


def test_black_frames_are_detected_at_the_seeded_range(defect_suite) -> None:
    suite, _ = defect_suite
    found = detect_black(suite["black_frames"].path)
    assert any(abs(start - 2.5) < 0.1 and abs(end - 3.3) < 0.1 for start, end in found), found
    assert detect_black(suite["clean"].path) == []


def test_frozen_frames_are_detected_at_the_seeded_range(defect_suite) -> None:
    suite, _ = defect_suite
    found = detect_frozen(suite["frozen_frames"].path)
    assert any(abs(start - 1.0) < 0.1 and abs(end - 1.8) < 0.1 for start, end in found), found
    assert detect_frozen(suite["clean"].path) == []


def test_bad_caption_track_carries_the_wrong_amount(defect_suite) -> None:
    suite, _ = defect_suite
    text = _subtitles(suite["bad_caption"].path)
    assert "ห้าพันบาท" in text and "ห้าหมื่นบาท" not in text


def test_clean_captions_match_the_script_amount(defect_suite) -> None:
    suite, _ = defect_suite
    assert "ห้าหมื่นบาท" in _subtitles(suite["clean"].path)


def test_wrong_cta_caption_promises_an_unreleased_episode(defect_suite) -> None:
    suite, _ = defect_suite
    assert "EP2 ดูได้แล้วตอนนี้" in _subtitles(suite["wrong_cta"].path)


def test_caption_out_of_bounds_cue_ends_after_the_media(defect_suite) -> None:
    suite, _ = defect_suite
    defect = suite["caption_out_of_bounds"]
    track = CaptionTrack.model_validate(json.loads(defect.path.read_text(encoding="utf-8")))
    assert max(c.end_ms for c in track.cues) > defect.truth.duration_ms
    assert defect.media_kind == "caption"


def test_complete_outputs_decode_and_the_truncated_one_does_not(defect_suite) -> None:
    suite, _ = defect_suite
    for name, defect in suite.items():
        if defect.media_kind != "video":
            continue
        if defect.complete:
            assert decodes_cleanly(defect.path), name
            probe(defect.path)  # must not raise
        else:
            assert not decodes_cleanly(defect.path), name
            with pytest.raises(MediaProbeError):
                probe(defect.path)


def test_every_defect_is_registered_as_synthetic_original_fixture(defect_suite) -> None:
    suite, registry = defect_suite
    assert set(suite) == {
        "clean", "wrong_amount", "wrong_speaker", "identity_swap", "missing_audio", "silence_gap",
        "black_frames", "frozen_frames", "bad_caption", "wrong_cta", "truncated_output",
        "caption_out_of_bounds",
    }  # fmt: skip
    for name, defect in suite.items():
        assert file_sha256(str(defect.path)) == defect.sha256, name
        truth = registry.get(defect.sha256)
        assert truth is not None and truth.provenance is Provenance.ORIGINAL_FIXTURE
        assert truth.synthetic is True and truth.measured_quality is False
        if name == "clean":
            assert defect.expected_check_ids == ()
        else:
            assert defect.expected_check_ids, name


def test_declared_truth_refuses_non_fixture_provenance() -> None:
    with pytest.raises(ValueError):
        FixtureTruth(
            fixture_id="x",
            duration_ms=1_000,
            has_audio=False,
            has_video=True,
            covered_ranges_ms=((0, 1_000),),
            provenance=Provenance.LIVE_PROVIDER,  # type: ignore[arg-type]
        )


def test_registry_refuses_conflicting_truth_for_one_hash(defect_suite) -> None:
    suite, registry = defect_suite
    sha = suite["clean"].sha256
    other = registry.get(suite["wrong_amount"].sha256)
    assert other is not None
    with pytest.raises(ValueError):
        registry.register(sha, other)


def test_clip_generation_is_reproducible_and_bounded(tmp_path: Path) -> None:
    first = make_clip(
        tmp_path / "a.mp4", duration_ms=1_000, with_audio=True, black_ranges=((200, 500),)
    )
    second = make_clip(
        tmp_path / "b.mp4", duration_ms=1_000, with_audio=True, black_ranges=((200, 500),)
    )
    assert file_sha256(str(first)) == file_sha256(str(second))
    with pytest.raises(ValueError):
        make_clip(tmp_path / "long.mp4", duration_ms=5_001)
    with pytest.raises(ValueError):
        make_clip(tmp_path / "big.mp4", duration_ms=1_000, width=720)
    with pytest.raises(ValueError):
        make_clip(tmp_path / "range.mp4", duration_ms=1_000, black_ranges=((900, 1_200),))


def test_wav_and_png_generators_are_real_files(tmp_path: Path) -> None:
    with wave.open(io.BytesIO(make_wav_bytes(500)), "rb") as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        assert round(wav.getnframes() / wav.getframerate() * 1000) == 500
    png = make_png_bytes(8, 4)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and png.endswith(b"IEND\xaeB`\x82")
    assert hashlib.sha256(png).hexdigest() == hashlib.sha256(make_png_bytes(8, 4)).hexdigest()


def test_registry_type_is_the_one_the_suite_populates() -> None:
    assert len(FixtureTruthRegistry()) == 0

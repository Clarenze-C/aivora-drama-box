"""Technical detector tests: decode/streams/duration/audio/silence/peaks/temporal (T017).

Every fact is measured through the real local ffmpeg on the staged tmp copy of the
media (T007 fixtures or purpose-built clips). Media that cannot decode produces a
BLOCKED decode finding and typed UNAVAILABLE coverage — never a green claim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from qa_support import QAWorld

from microdrama.contracts.enums import QAOutcome
from microdrama.contracts.errors import ServiceUnavailable
from microdrama.contracts.media import MediaInfo
from microdrama.qa import QAConfig, TechnicalQARun
from microdrama.qa.technical import (
    MediaFacts,
    parse_srt,
    technical_findings,
)
from microdrama.testing.media import make_clip


def _by_id(run: TechnicalQARun, check_id: str):
    return [f for f in run.findings if f.check_id == check_id]


def _run_clean(qa_world: QAWorld, defect_suite) -> TechnicalQARun:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    return qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)


def test_clean_media_technical_checks_pass(defect_suite, qa_world: QAWorld) -> None:
    run = _run_clean(qa_world, defect_suite)
    for check_id in (
        "technical.decode",
        "technical.streams",
        "technical.duration",
        "technical.audio_present",
        "audio.silence",
        "audio.peaks",
        "temporal.black_frames",
        "temporal.frozen_frames",
    ):
        fired = _by_id(run, check_id)
        assert fired and all(f.outcome is QAOutcome.PASS for f in fired), check_id
    assert not _by_id(run, "caption.cue_within_media") or all(
        f.outcome is QAOutcome.PASS for f in _by_id(run, "caption.cue_within_media")
    )


def test_truncated_media_blocks_decode_and_marks_the_rest_unavailable(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    truncated = defect_suite["truncated_output"]
    asset_id = qa_world.register_media(
        episode_id,
        data=truncated.path.read_bytes(),
        media=MediaInfo(duration_ms=5_000, has_video=True, has_audio=True),
    )
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    decode = _by_id(run, "technical.decode")
    assert decode and decode[0].outcome is QAOutcome.BLOCKED
    assert "moov" in (decode[0].observed or "")
    assert not run.all_checks_green
    for check_id in ("technical.streams", "audio.silence", "temporal.black_frames"):
        fired = _by_id(run, check_id)
        assert fired and fired[0].outcome is QAOutcome.UNKNOWN, check_id
        assert fired[0].coverage.value == "UNAVAILABLE"
    # unsampled/unavailable stays honest in the persisted coverage windows
    asr = [w for w in run.coverage if w.check_family.value == "ASR"]
    assert asr and all(w.status.value == "UNSAMPLED" for w in asr)


def test_missing_audio_is_critical_and_audio_checks_unavailable(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["missing_audio"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    audio_present = _by_id(run, "technical.audio_present")
    assert audio_present and audio_present[0].outcome is QAOutcome.REPAIRABLE
    assert audio_present[0].severity.value == "CRITICAL"
    for check_id in ("audio.silence", "audio.peaks"):
        fired = _by_id(run, check_id)
        assert fired and fired[0].outcome is QAOutcome.UNKNOWN
        assert fired[0].coverage.value == "UNAVAILABLE"
    assert not run.all_checks_green


def test_black_frames_are_timecoded_repairable_findings(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["black_frames"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "temporal.black_frames")
    assert len(fired) == 1
    finding = fired[0]
    assert finding.outcome is QAOutcome.REPAIRABLE
    assert 2_400 <= finding.start_ms <= 2_600  # seeded range 2500-3300 ms
    assert 3_200 <= finding.end_ms <= 3_400
    assert finding.evidence[0].note.startswith("local ffmpeg measurement")


def test_frozen_frames_are_timecoded_repairable_findings(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["frozen_frames"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "temporal.frozen_frames")
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.REPAIRABLE
    assert 900 <= fired[0].start_ms <= 1_100  # seeded range 1000-1800 ms
    assert "SHOT" not in {t.value for f in fired for t in f.repair_targets}


def test_duration_drift_against_registered_facts_flags_repair(
    defect_suite, qa_world: QAWorld, tmp_path: Path
) -> None:
    clip = make_clip(tmp_path / "drift.mp4", duration_ms=4_000, comment="qa-drift")
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    asset_id = qa_world.register_media(
        episode_id,
        data=clip.read_bytes(),
        media=MediaInfo(duration_ms=2_000, has_video=True, has_audio=True),  # wrong on purpose
    )
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "technical.duration")
    assert fired and fired[0].outcome is QAOutcome.REPAIRABLE
    assert "drift" in (fired[0].observed or "")


def test_long_silence_run_flags_audio_silence(qa_world: QAWorld, tmp_path: Path) -> None:
    clip = make_clip(
        tmp_path / "silent.mp4",
        duration_ms=4_000,
        silence_ranges=((0, 4_000),),
        comment="qa-all-silent",
    )
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    asset_id = qa_world.register_media(episode_id, data=clip.read_bytes())
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "audio.silence")
    assert fired and fired[0].outcome is QAOutcome.REPAIRABLE
    assert fired[0].observed and "0.00" in fired[0].observed


def test_peak_threshold_logic_is_argument_safe() -> None:
    """Peak outcome follows the measured value through the config threshold."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from microdrama.contracts.enums import AssetKind, AssetState, Provenance
    from microdrama.contracts.media import AssetDescriptor

    facts = MediaFacts(
        duration_ms=1_000,
        media=MediaInfo(duration_ms=1_000, has_video=True, has_audio=True),
        decode_ok=True,
        probe_error=None,
    )
    descriptor = AssetDescriptor(
        asset_id=uuid4(),
        asset_kind=AssetKind.VIDEO,
        object_key="qa/x.mp4",
        sha256="a" * 64,
        size_bytes=10,
        media_type="video/mp4",
        media=facts.media,
        state=AssetState.ACCEPTED,
        provenance=Provenance.ORIGINAL_FIXTURE,
        created_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    loud = technical_findings(
        run_key="k",
        episode_id=uuid4(),
        descriptor=descriptor,
        facts=facts,
        config=QAConfig(),
        black=[],
        frozen=[],
        silence=[],
        peak_db=-0.05,
    )
    quiet = technical_findings(
        run_key="k",
        episode_id=uuid4(),
        descriptor=descriptor,
        facts=facts,
        config=QAConfig(),
        black=[],
        frozen=[],
        silence=[],
        peak_db=-6.0,
    )
    assert one(loud, "audio.peaks").outcome is QAOutcome.REPAIRABLE
    assert one(quiet, "audio.peaks").outcome is QAOutcome.PASS


def test_missing_ffmpeg_detector_surfaces_as_service_unavailable(
    monkeypatch, defect_suite, qa_world: QAWorld
) -> None:
    import microdrama.qa.technical as technical

    def broken(*args, **kwargs):
        raise technical.MediaAnalysisError("ffmpeg vanished")

    monkeypatch.setattr(technical, "detect_black_windows", broken)
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = qa_world.service()
    # the service imports detectors into its own namespace; patch there too
    import microdrama.qa.service as service_mod

    monkeypatch.setattr(service_mod, "detect_black_windows", broken)
    with pytest.raises(ServiceUnavailable, match="detector"):
        service.run_episode_qa(episode_id, asset_id=asset_id)
    assert qa_world.findings_rows(episode_id) == []
    assert qa_world.run_events(episode_id) == []


def test_srt_parser_skips_malformed_blocks_without_inventing_cues() -> None:
    payload = (
        b"1\n00:00:00,100 --> 00:00:01,000\nhello\n\n"
        b"garbage block without timing\n\n"
        b"2\nnot-a-timestamp --> 00:00:02,000\nworld\n\n"
        + "3\n00:00:02,000 --> 00:00:03,500\nThai \u0e20\u0e32\u0e29\u0e32\n".encode()
    )
    cues = parse_srt(payload)
    # ids are assigned to the parsed cues only (the malformed block yielded nothing)
    assert [c.cue_id for c in cues] == ["embedded-1", "embedded-2"]
    assert cues[0].text == "hello"
    assert cues[1].start_ms == 2_000 and cues[1].end_ms == 3_500
    assert cues[1].text == "Thai ภาษา"  # Thai script survived the decode+parse


def one(findings, check_id):
    return next(f for f in findings if f.check_id == check_id)


def UUID_0():
    import uuid

    return uuid.UUID(int=0)

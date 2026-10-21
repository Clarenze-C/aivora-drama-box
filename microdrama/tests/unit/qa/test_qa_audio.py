"""ASR/speech check tests (T017): the never-green-from-a-correct-script rule.

The script (expected side) is the pristine examples script in every test here. A
defective media is flagged from what the media actually contains; an UNOBSERVED media
is a typed unknown and can never be green — being right on paper proves nothing.
"""

from __future__ import annotations

from pathlib import Path

from qa_support import QAWorld

from microdrama.contracts.enums import QAOutcome
from microdrama.qa import TechnicalQARun
from microdrama.testing.media import FixtureTruth, IdentityTruth, SpokenTruth, make_clip

SCRIPT_LINE_TEXTS = {
    "s1-l1": "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ",
    "s1-l2": "แม่หนูไม่อยากให้หนูรู้",
    "s2-l1": "ภายในวันศุกร์นะครับ",
}
WINDOWS = {"s1-l1": (100, 2_100), "s1-l2": (2_300, 3_700), "s2-l1": (3_900, 4_900)}
SPEAKERS = {"s1-l1": "fon", "s1-l2": "lek", "s2-l1": "nok"}


def _by_id(run: TechnicalQARun, check_id: str):
    return [f for f in run.findings if f.check_id == check_id]


def _truth(spoken_speaker: dict | None = None, covered=((0, 5_000),)) -> FixtureTruth:
    spoken = tuple(
        SpokenTruth(
            start_ms=start,
            end_ms=end,
            text_th=SCRIPT_LINE_TEXTS[line_id],
            speaker_id=(spoken_speaker or {}).get(line_id, SPEAKERS[line_id]),
        )
        for line_id, (start, end) in WINDOWS.items()
    )
    return FixtureTruth(
        fixture_id="qa-audio-custom",
        duration_ms=5_000,
        has_audio=True,
        has_video=True,
        spoken=spoken,
        identities=(
            IdentityTruth(start_ms=s, end_ms=e, character_id=SPEAKERS[line_id])
            for line_id, (s, e) in WINDOWS.items()
        ),
        covered_ranges_ms=covered,
    )


def test_clean_speech_passes_terms_speakers_and_lines(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    for check_id in ("asr.critical_term_match", "asr.speaker_match", "asr.line_present"):
        fired = _by_id(run, check_id)
        assert len(fired) == 3, check_id
        assert all(f.outcome is QAOutcome.PASS for f in fired), check_id


def test_wrong_amount_fails_qa_with_a_pristine_script(defect_suite, qa_world: QAWorld) -> None:
    """The acceptance rule: a correct prompt/script never makes defective media green."""
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["wrong_amount"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "asr.critical_term_match")
    assert len(fired) == 3
    bad = [f for f in fired if f.outcome is QAOutcome.REPAIRABLE]
    assert len(bad) == 1
    assert bad[0].severity.value == "CRITICAL"
    # expected comes from the script; observed is what the media actually says
    assert "ห้าหมื่นบาท" in (bad[0].expected or "")
    assert "ห้าพันบาท" in (bad[0].observed or "")
    assert bad[0].observed != bad[0].expected
    assert bad[0].blocks_release
    assert not run.all_checks_green


def test_wrong_speaker_observed_side_comes_from_the_media(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["wrong_speaker"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "asr.speaker_match")
    bad = [f for f in fired if f.outcome is QAOutcome.REPAIRABLE]
    assert len(bad) == 1
    assert bad[0].expected == "lek"  # the pristine script's intended speaker
    assert bad[0].observed == "fon"  # what the media actually speaks
    assert bad[0].evidence[0].note.startswith("fixture-truth:wrong_speaker")
    assert not run.all_checks_green


def test_silence_gap_flags_the_missing_line_as_critical(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["silence_gap"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "asr.line_present")
    assert [f.outcome for f in fired].count(QAOutcome.REPAIRABLE) == 1
    bad = next(f for f in fired if f.outcome is QAOutcome.REPAIRABLE)
    assert bad.expected == SCRIPT_LINE_TEXTS["s1-l2"]
    assert bad.severity.value == "CRITICAL"


def test_unregistered_media_is_typed_unknown_never_green(qa_world: QAWorld, tmp_path: Path) -> None:
    """No observation source knows this media: everything speech-shaped is UNKNOWN."""
    clip = make_clip(tmp_path / "unknown.mp4", duration_ms=5_000, comment="qa-unknown")
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    asset_id = qa_world.register_media(episode_id, data=clip.read_bytes())  # no truth
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    asr_windows = [w for w in run.coverage if w.check_family.value == "ASR"]
    assert asr_windows and all(w.status.value == "UNAVAILABLE" for w in asr_windows)
    for check_id in ("asr.critical_term_match", "asr.speaker_match", "asr.line_present"):
        fired = _by_id(run, check_id)
        if not fired:
            continue
        assert all(f.outcome is QAOutcome.UNKNOWN for f in fired), check_id
    line_findings = _by_id(run, "asr.line_present")
    assert line_findings and all(f.coverage.value == "UNAVAILABLE" for f in line_findings)
    assert "no fixture truth registered" in (asr_windows[0].note or "")


def test_unsampled_windows_are_not_checked(qa_world: QAWorld, tmp_path: Path) -> None:
    """Truth declares NO sampled ranges: coverage is UNSAMPLED and stays UNKNOWN."""
    clip = make_clip(tmp_path / "unsampled.mp4", duration_ms=5_000, comment="qa-unsampled")
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    asset_id = qa_world.register_media(episode_id, data=clip.read_bytes(), truth=_truth(covered=()))
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    asr_windows = [w for w in run.coverage if w.check_family.value == "ASR"]
    assert asr_windows and all(w.status.value == "UNSAMPLED" for w in asr_windows)
    fired = _by_id(run, "asr.line_present")
    assert len(fired) == 3
    assert all(f.outcome is QAOutcome.UNKNOWN for f in fired)
    assert all(f.coverage.value == "UNSAMPLED" for f in fired)


def test_partially_sampled_media_reports_partial_coverage(
    qa_world: QAWorld, tmp_path: Path
) -> None:
    clip = make_clip(tmp_path / "partial.mp4", duration_ms=5_000, comment="qa-partial")
    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    asset_id = qa_world.register_media(
        episode_id, data=clip.read_bytes(), truth=_truth(covered=((0, 1_000),))
    )
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    statuses = {
        (w.start_ms, w.end_ms): w.status.value
        for w in run.coverage
        if w.check_family.value == "ASR"
    }
    assert statuses[(0, 1_000)] == "CHECKED"
    assert statuses[(1_000, 5_000)] == "UNSAMPLED"
    assert not run.all_checks_green


def test_no_observer_configured_is_a_typed_unknown_not_a_pass(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    from microdrama.qa import build_technical_qa_service

    service = build_technical_qa_service(
        qa_world.db,
        qa_world.clock,
        qa_world.ids,
        qa_world.settings,
        budget=qa_world.budget,
        store=qa_world.store,
        observer=None,
    )
    run = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    fired = _by_id(run, "asr.line_present")
    assert fired and all(f.outcome is QAOutcome.UNKNOWN for f in fired)
    asr_windows = [w for w in run.coverage if w.check_family.value == "ASR"]
    assert asr_windows and all(w.status.value == "UNAVAILABLE" for w in asr_windows)


def test_offline_observer_refuses_to_run_outside_offline_mock(
    defect_suite, qa_world: QAWorld
) -> None:
    import pytest as _pytest

    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.qa import OfflineMediaObserver

    live = Settings(execution_mode=ExecutionMode.PRODUCTION)
    observer = OfflineMediaObserver(qa_world.truth, live)
    with _pytest.raises(Exception, match="OFFLINE_MOCK"):
        observer.observe(
            asset_id=episode0(),
            asset_sha256=defect_suite["clean"].sha256,
            media_path=defect_suite["clean"].path,
            duration_ms=5_000,
        )


def test_speech_observer_adapter_serves_t015s_seam(qa_world: QAWorld) -> None:
    """The adapter gives T015's editing assembly the same observation seam."""
    import hashlib

    from microdrama.qa import as_speech_observer

    truth = _truth()
    data = b"qa-adapter-bytes"
    sha = hashlib.sha256(data).hexdigest()
    qa_world.truth.register(sha, truth)
    adapter = as_speech_observer(qa_world.observer(), lambda s: data)
    observed = adapter.observe(sha)
    assert observed is not None
    assert observed.text_th == SCRIPT_LINE_TEXTS["s1-l1"]
    assert observed.speaker_id == "fon"


def episode0():
    import uuid

    return uuid.uuid4()

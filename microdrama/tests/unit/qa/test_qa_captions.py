"""Caption QA tests (T017): embedded extraction, terms, CTA claims, bounds, staleness.

Caption evidence comes out of the actual media (embedded mov_text pulled through
ffmpeg) or from T015's CURRENT caption tracks; the intended script supplies only the
expected side. Subtitles cannot conceal wrong spoken content: a caption that
disagrees with the observed speech re-fires T015's mismatch code.
"""

from __future__ import annotations

import uuid

from qa_support import QAWorld

from microdrama.contracts.enums import CaptionTimingSource, QAOutcome
from microdrama.contracts.media import CaptionCue, CaptionTrack
from microdrama.qa import MISMATCH_CODE, QAConfig, TechnicalQARun


def _by_id(run: TechnicalQARun, check_id: str):
    return [f for f in run.findings if f.check_id == check_id]


def test_embedded_captions_are_extracted_from_the_actual_media(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    bounds = _by_id(run, "caption.cue_bounds")
    assert bounds and bounds[0].outcome is QAOutcome.PASS
    assert "3 cues" in (bounds[0].observed or "")
    terms = _by_id(run, "caption.critical_term_match")
    assert len(terms) == 3 and all(f.outcome is QAOutcome.PASS for f in terms)


def test_bad_caption_flags_the_critical_term_from_the_media_side(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["bad_caption"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "caption.critical_term_match")
    bad = [f for f in fired if f.outcome is QAOutcome.REPAIRABLE]
    assert len(bad) == 1
    assert "ห้าหมื่นบาท" in (bad[0].expected or "")  # script side is pristine
    assert "ห้าพันบาท" in (bad[0].observed or "")  # the media's caption is wrong
    assert not run.all_checks_green


def test_wrong_cta_flags_release_claim_with_default_phrases(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["wrong_cta"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "caption.release_claim")
    assert any(f.outcome is QAOutcome.REPAIRABLE for f in fired)
    bad = next(f for f in fired if f.outcome is QAOutcome.REPAIRABLE)
    assert bad.severity.value == "CRITICAL"
    assert "ดูได้แล้วตอนนี้" in (bad.observed or "")
    assert not run.all_checks_green


def test_release_claims_are_typed_unknown_when_no_phrases_configured(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    config = QAConfig(unreleased_claim_phrases=())
    run = qa_world.service(config).run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "caption.release_claim")
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.UNKNOWN
    assert fired[0].coverage.value == "UNAVAILABLE"
    assert "not checked" in (fired[0].observed or "")
    assert not run.all_checks_green  # a critical check that never ran is not green


def test_out_of_bounds_cue_flagged_against_the_media_duration(
    defect_suite, qa_world: QAWorld
) -> None:
    from microdrama.contracts.examples import script as example_script

    fixture = defect_suite["caption_out_of_bounds"]
    track = CaptionTrack.model_validate_json(fixture.path.read_text(encoding="utf-8"))
    episode_id = qa_world.episode()
    run_key = "test-oob"
    from microdrama.qa.technical import caption_findings

    findings = caption_findings(
        run_key=run_key,
        episode_id=episode_id,
        asset_id=uuid.uuid4(),
        asset_sha256=fixture.sha256,
        cues=list(track.cues),
        duration_ms=fixture.truth.duration_ms,
        script=example_script().model_copy(update={"episode_id": episode_id}),
        config=QAConfig(),
        source_label="sidecar",
    )
    fired = [f for f in findings if f.check_id == "caption.cue_within_media"]
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.REPAIRABLE
    assert fired[0].start_ms == 4_500 and fired[0].end_ms == 6_200
    assert "6200" in (fired[0].observed or "")


def test_caption_disagreeing_with_speech_refires_the_t015_mismatch_code(
    defect_suite, qa_world: QAWorld
) -> None:
    """wrong_amount: captions are right, the SPEECH is wrong — the cue must not hide it."""
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["wrong_amount"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, MISMATCH_CODE)
    bad = [f for f in fired if f.outcome is QAOutcome.REPAIRABLE]
    assert len(bad) == 1
    assert bad[0].severity.value == "CRITICAL"
    # expected = what the audio actually speaks; observed = what the caption displays
    assert "ห้าพันบาท" in (bad[0].expected or "")  # the wrong amount that was spoken
    assert "ห้าหมื่นบาท" in (bad[0].observed or "")  # the caption claiming the right one
    assert not run.all_checks_green


def test_clean_captions_agree_with_speech(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, MISMATCH_CODE)
    assert len(fired) == 3
    assert all(f.outcome is QAOutcome.PASS for f in fired)


def _track(cues: list[CaptionCue]) -> CaptionTrack:
    return CaptionTrack(
        track_id=uuid.uuid4(),
        episode_id=uuid.uuid4(),
        version=1,
        locale="th-TH",
        timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
        derived_from_audio_sha256=["b" * 64],
        cues=cues,
    )


def test_editing_track_cues_are_checked_through_the_caption_source(
    defect_suite, qa_world: QAWorld
) -> None:
    from qa_support import StubCaptionSource

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    good = _track(
        [CaptionCue(cue_id="s1-l1.th", start_ms=100, end_ms=2_000, text="สวัสดี", line_id="s1-l1")]
    )
    out_of_bounds = _track(
        [CaptionCue(cue_id="s2-l1.th", start_ms=4_500, end_ms=9_999, text="ภายในวันศุกร์นะครับ")]
    )
    source = StubCaptionSource(tracks=[good, out_of_bounds])
    run = qa_world.service(caption_source=source).run_episode_qa(episode_id, asset_id=asset_id)
    within = _by_id(run, "caption.cue_within_media")
    assert any(f.outcome is QAOutcome.REPAIRABLE for f in within)
    assert any(f.outcome is QAOutcome.PASS for f in within)


def test_stale_cues_from_t015_are_flagged(defect_suite, qa_world: QAWorld) -> None:
    from qa_support import StubCaptionSource

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    source = StubCaptionSource(stale=["s1-l2.th", "s1-l2.en"])
    run = qa_world.service(caption_source=source).run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "caption.cue_stale")
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.REPAIRABLE
    assert "stale_caption_cues" in (fired[0].evidence[0].note or "")
    assert "s1-l2.th" in (fired[0].observed or "")
    # stale cues are MAJOR repair input for T019, not a release blocker by themselves
    assert fired[0].severity.value == "MAJOR"
    assert run.all_checks_green

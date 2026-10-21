"""Coverage honesty tests (T018): unsampled windows never count as checked.

A media whose observation covered only part of the timeline freezes UNSAMPLED gap
windows per window in the report row; Pass B findings over the gap are typed UNKNOWN
(PASS requires CHECKED coverage, enforced by the frozen contract AND the database),
and media with no observation source at all is UNKNOWN everywhere — never green.
"""

from __future__ import annotations

from qa_support import QAWorld
from test_observation_support import (
    CLEAN_LINE_TH,
    comparison_service,
    observation_service,
    partial_coverage_truth,
    partial_media_info,
)

from microdrama.contracts.enums import CoverageStatus, QAOutcome
from microdrama.contracts.qa import ObservationReport


def _partial_episode(qa_world: QAWorld):
    return qa_world.seeded_episode_with(
        media=b"t018-partial-coverage-media",
        media_info=partial_media_info(),
        truth=partial_coverage_truth(),
    )


def _unregistered_episode(qa_world: QAWorld):
    return qa_world.seeded_episode_with(
        media=b"t018-media-nobody-registered", media_info=partial_media_info()
    )


def test_unsampled_windows_persist_per_window_in_the_frozen_report(
    qa_world: QAWorld,
) -> None:
    episode_id, asset_id = _partial_episode(qa_world)
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    asr = [w for w in frozen.report.coverage if w.check_family.value == "ASR"]
    checked = [w for w in asr if w.status is CoverageStatus.CHECKED]
    unsampled = [w for w in asr if w.status is CoverageStatus.UNSAMPLED]
    assert [(w.start_ms, w.end_ms) for w in checked] == [(0, 2_000)]
    assert [(w.start_ms, w.end_ms) for w in unsampled] == [(2_000, 5_000)]
    # the same windows are on the persisted row and the freeze event
    stored = ObservationReport.model_validate(
        qa_world.row(
            "SELECT report FROM qa_observations WHERE id = %s", (frozen.report.report_id,)
        )["report"]
    )
    assert [w.status for w in stored.coverage] == [w.status for w in frozen.report.coverage]
    event = qa_world.rows(
        "SELECT payload FROM domain_events WHERE aggregate_id = %s "
        "AND event_type = 'qa.observation.frozen'",
        (episode_id,),
    )[0]["payload"]
    assert event["coverage"]["ASR"]["windows"] == [
        [0, 2_000, "CHECKED"],
        [2_000, 5_000, "UNSAMPLED"],
    ]


def test_findings_over_unsampled_windows_stay_unknown(qa_world: QAWorld) -> None:
    episode_id, asset_id = _partial_episode(qa_world)
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    run = comparison_service(qa_world).compare(episode_id)
    # the spoken line inside the checked window is fine…
    spoken = [f for f in run.findings if f.check_id == "asr.line_present" and f.start_ms < 2_000]
    assert any(f.outcome is QAOutcome.PASS for f in spoken)
    # …but lines whose only possible home is the unsampled gap are UNKNOWN, not green
    gap_lines = [f for f in run.findings if f.check_id == "asr.line_present" and f.end_ms > 2_000]
    assert gap_lines
    assert all(f.outcome is QAOutcome.UNKNOWN for f in gap_lines)
    assert all(f.coverage in (CoverageStatus.UNSAMPLED, CoverageStatus.PARTIAL) for f in gap_lines)
    assert not run.all_checks_green


def test_unsampled_never_becomes_a_pass(qa_world: QAWorld) -> None:
    episode_id, asset_id = _partial_episode(qa_world)
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    comparison_service(qa_world).compare(episode_id)
    bad_unknown = qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE coverage IN "
        "('UNSAMPLED','UNAVAILABLE') AND outcome <> 'UNKNOWN'"
    )["n"]
    bad_pass = qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE outcome = 'PASS' AND coverage <> 'CHECKED'"
    )["n"]
    overlap = qa_world.rows(
        "SELECT start_ms, end_ms, coverage FROM qa_findings "
        "WHERE outcome = 'PASS' AND start_ms >= 2000"
    )
    assert bad_unknown == 0
    assert bad_pass == 0
    assert overlap == []  # no PASS finding starts inside the unsampled gap


def test_transcript_only_covers_what_was_observed(qa_world: QAWorld) -> None:
    episode_id, asset_id = _partial_episode(qa_world)
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    assert [s.text for s in frozen.report.transcript] == [CLEAN_LINE_TH]
    assert all(s.end_ms <= 2_000 for s in frozen.report.transcript)


def test_no_observer_is_typed_unknown_never_green(qa_world: QAWorld) -> None:
    episode_id, asset_id = _partial_episode(qa_world)
    frozen = observation_service(qa_world, observer=None).observe_media(
        episode_id, asset_id=asset_id
    )
    assert frozen.report.transcript == []
    assert all(w.status is CoverageStatus.UNAVAILABLE for w in frozen.report.coverage)
    run = comparison_service(qa_world).compare(episode_id)
    assert run.findings
    assert all(f.outcome is QAOutcome.UNKNOWN for f in run.findings)
    assert not run.all_checks_green
    assert run.blocking_check_ids == []


def test_unregistered_media_is_typed_unknown_never_green(qa_world: QAWorld) -> None:
    episode_id, asset_id = _unregistered_episode(qa_world)
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    assert frozen.report.transcript == []
    run = comparison_service(qa_world).compare(episode_id)
    assert run.findings
    assert all(f.outcome is QAOutcome.UNKNOWN for f in run.findings)
    assert not run.all_checks_green

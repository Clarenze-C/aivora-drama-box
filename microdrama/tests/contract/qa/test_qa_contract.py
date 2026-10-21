"""Contract tests for the technical QA lane (T017).

Real service outputs (real ffmpeg, real database) checked against the FROZEN
contracts at 1.5.0: every persisted finding body validates as ``contracts.QAFinding``,
the honesty invariants hold on stored rows (unsampled/unavailable is UNKNOWN; PASS
requires CHECKED), run events are bounded and carry the coverage windows, and the
report view exposes the stable check ids T018/T019/T030 consume.
"""

from __future__ import annotations

import json

from microdrama.contracts.enums import QAOutcome
from microdrama.contracts.qa import CoverageWindow, QAFinding
from microdrama.qa import RUN_EVENT, QAConfig, TechnicalQARun, build_report_view
from microdrama.qa.config import CRITICAL_CHECK_IDS
from microdrama.qa.report import load_findings

MAX_EVENT_PAYLOAD_BYTES = 16_384


def _run(defect_suite, qa_world, kind: str = "clean") -> TechnicalQARun:
    fixture = defect_suite[kind]
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=fixture)
    return qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)


def test_persisted_findings_satisfy_the_frozen_qa_finding_contract(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world, "wrong_amount")
    rows = qa_world.findings_rows(run.episode_id)
    assert rows
    for row in rows:
        finding = QAFinding.model_validate(row["body"])
        assert str(finding.finding_id) == str(row["id"])
        assert finding.check_id == row["check_id"]
        assert finding.severity.value == row["severity"]
        assert finding.coverage.value == row["coverage"]
        assert finding.outcome.value == row["outcome"]
        assert finding.evidence, "every finding carries its provenance evidence"
        assert finding.provenance.value in ("ORIGINAL_FIXTURE", "DERIVED_LOCAL")


def test_db_honesty_constraints_hold_on_persisted_rows(defect_suite, qa_world) -> None:
    for kind in ("clean", "truncated_output", "missing_audio"):
        media_info = None
        if kind == "truncated_output":
            from microdrama.contracts.media import MediaInfo

            media_info = MediaInfo(duration_ms=5_000, has_video=True, has_audio=True)
        episode_id, asset_id = qa_world.seeded_episode_with(
            fixture=defect_suite[kind], media_info=media_info
        )
        qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    violations = qa_world.rows(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE coverage IN "
        "('UNSAMPLED','UNAVAILABLE') AND outcome <> 'UNKNOWN'"
    )
    assert violations[0]["n"] == 0
    bad_pass = qa_world.rows(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE outcome = 'PASS' AND coverage <> 'CHECKED'"
    )
    assert bad_pass[0]["n"] == 0


def test_run_event_payload_is_bounded_and_carries_coverage(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world)
    events = qa_world.rows(
        "SELECT * FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
        (run.episode_id, RUN_EVENT),
    )
    assert len(events) == 1
    payload = dict(events[0]["payload"])
    assert len(json.dumps(payload).encode()) <= MAX_EVENT_PAYLOAD_BYTES
    assert payload["run_key"] == run.run_key
    coverage = payload["coverage"]
    assert set(coverage) >= {"TECHNICAL", "AUDIO", "TEMPORAL", "ASR", "CAPTION"}
    for family, family_payload in coverage.items():
        assert family_payload["window_count"] >= 1
        for start_ms, end_ms, status in family_payload["windows"]:
            window = CoverageWindow(
                asset_id=run.asset_id,
                check_family=family,
                start_ms=start_ms,
                end_ms=end_ms,
                status=status,
            )
            assert window.end_ms > window.start_ms


def test_technical_qa_run_model_round_trips(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world)
    restored = TechnicalQARun.model_validate_json(run.model_dump_json())
    assert restored == run
    assert restored.run_key == run.run_key
    assert [f.finding_id for f in restored.findings] == [f.finding_id for f in run.findings]


def test_report_view_exposes_stable_check_ids(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world, "wrong_speaker")
    view = build_report_view(qa_world.db, run.episode_id, critical_check_ids=CRITICAL_CHECK_IDS)
    assert view.critical_check_ids == list(CRITICAL_CHECK_IDS)
    assert set(view.blocking_check_ids) <= {f.check_id for f in view.findings}
    assert set(view.unknown_check_ids) <= {f.check_id for f in view.findings}
    assert "asr.speaker_match" in view.blocking_check_ids
    # the stable ids the T007 suite promised and T018/T019/T030 rely on are all present
    emitted = {f.check_id for f in view.findings}
    for check_id in (
        "technical.decode",
        "asr.critical_term_match",
        "caption.cue_within_media",
        "temporal.black_frames",
        "visual_identity.match",
    ):
        assert check_id in emitted


def test_unknown_check_ids_are_explicit_not_hidden(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world)
    unknowns = {f.check_id for f in run.findings if f.outcome is QAOutcome.UNKNOWN}
    assert unknowns  # lip-sync/prop checks are always visible unknowns offline
    assert set(run.unknown_check_ids) == unknowns
    # and none of them is green-washed: green excludes them by configuration
    assert unknowns.isdisjoint(set(run.blocking_check_ids))


def test_load_findings_returns_contract_models(defect_suite, qa_world) -> None:
    run = _run(defect_suite, qa_world)
    stored = load_findings(qa_world.db, run.episode_id)
    assert stored
    assert all(isinstance(f, QAFinding) for f in stored)
    assert sorted(f.finding_id for f in stored) == sorted(f.finding_id for f in run.findings)


def test_config_is_part_of_the_run_identity(defect_suite, qa_world) -> None:
    """A config change is a different run: same media, new findings, no replay."""
    fixture = defect_suite["clean"]
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=fixture)
    first = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    stricter = QAConfig(unreleased_claim_phrases=())
    second = qa_world.service(stricter).run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "COMPLETED"
    assert second.run_key != first.run_key
    assert second.qa_cycle == first.qa_cycle + 1

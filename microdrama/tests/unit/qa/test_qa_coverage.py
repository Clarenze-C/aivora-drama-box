"""Coverage-window tests (T017): checked vs unsampled persistence and the never-PASS rule."""

from __future__ import annotations

import uuid

from microdrama.contracts.enums import CheckFamily, CoverageStatus, QAOutcome, Severity
from microdrama.contracts.qa import QAFinding
from microdrama.qa import coverage_for, green_summary, partition_coverage
from microdrama.qa.coverage import checked_ms, summarize_coverage
from microdrama.qa.report import load_run_coverage


def test_partition_coverage_marks_unsampled_gaps() -> None:
    asset_id = uuid.uuid4()
    windows = partition_coverage(asset_id, CheckFamily.ASR, 5_000, ((0, 2_000), (3_000, 5_000)))
    assert [(w.start_ms, w.end_ms, w.status) for w in windows] == [
        (0, 2_000, CoverageStatus.CHECKED),
        (2_000, 3_000, CoverageStatus.UNSAMPLED),
        (3_000, 5_000, CoverageStatus.CHECKED),
    ]
    assert checked_ms(windows) == 4_000


def test_partition_coverage_rejects_ranges_outside_the_media() -> None:
    import pytest

    with pytest.raises(ValueError, match="inside the media"):
        partition_coverage(uuid.uuid4(), CheckFamily.ASR, 5_000, ((4_000, 6_000),))


def test_coverage_for_requires_full_check_for_checked() -> None:
    asset_id = uuid.uuid4()
    windows = partition_coverage(asset_id, CheckFamily.TEMPORAL, 5_000, ((0, 2_000),))
    assert coverage_for(windows, CheckFamily.TEMPORAL, 0, 2_000) is CoverageStatus.CHECKED
    assert coverage_for(windows, CheckFamily.TEMPORAL, 0, 3_000) is CoverageStatus.PARTIAL
    assert coverage_for(windows, CheckFamily.TEMPORAL, 2_500, 4_000) is CoverageStatus.UNSAMPLED
    # a family with no windows at all is UNAVAILABLE, not silently fine
    assert coverage_for(windows, CheckFamily.ASR, 0, 100) is CoverageStatus.UNAVAILABLE


def test_unavailable_beats_unsampled_when_both_overlap() -> None:
    asset_id = uuid.uuid4()
    windows = partition_coverage(
        asset_id, CheckFamily.ASR, 5_000, ((0, 2_000),), outside=CoverageStatus.UNAVAILABLE
    ) + partition_coverage(
        asset_id, CheckFamily.ASR, 5_000, ((3_000, 5_000),), outside=CoverageStatus.UNSAMPLED
    )
    assert coverage_for(windows, CheckFamily.ASR, 0, 5_000) is CoverageStatus.PARTIAL
    assert coverage_for(windows, CheckFamily.ASR, 0, 4_000) is CoverageStatus.PARTIAL


def test_checked_windows_persist_on_the_run_event(defect_suite, qa_world) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    from microdrama.qa import load_findings

    stored = load_findings(qa_world.db, episode_id)
    assert stored and all(
        f.coverage is CoverageStatus.CHECKED for f in stored if f.outcome is QAOutcome.PASS
    )
    coverage = load_run_coverage(qa_world.db, episode_id, run.run_key)
    technical = [w for w in coverage if w.check_family is CheckFamily.TECHNICAL]
    assert technical and all(w.status is CoverageStatus.CHECKED for w in technical)
    assert (technical[0].start_ms, technical[0].end_ms) == (0, 5_000)


def test_event_coverage_summary_is_bounded(defect_suite, qa_world) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    payload = qa_world.run_events(episode_id)[0]
    summary = payload["coverage"]
    for family_payload in summary.values():
        assert len(family_payload["windows"]) <= 24
        assert family_payload["truncated"] is False
    import json

    assert len(json.dumps(payload).encode()) < 16_384


def test_unsampled_coverage_never_produces_a_pass_finding() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    from microdrama.qa import build_finding

    with _pytest.raises(ValidationError, match="UNKNOWN"):
        build_finding(
            run_key="k",
            episode_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            start_ms=0,
            end_ms=10,
            check_id="asr.line_present",
            family=CheckFamily.ASR,
            severity=Severity.MAJOR,
            outcome=QAOutcome.PASS,  # illegal: unchecked coverage cannot PASS
            coverage=CoverageStatus.UNSAMPLED,
            expected="x",
            observed="y",
            evidence_source="FAKE_FIXTURE",
            evidence_ref="r",
            evidence_note="n",
            provenance="ORIGINAL_FIXTURE",
        )


def test_green_summary_requires_every_critical_check_to_have_run_and_passed() -> None:
    def finding(check_id: str, outcome: QAOutcome, severity: Severity = Severity.INFO) -> QAFinding:
        from microdrama.qa import build_finding

        return build_finding(
            run_key="k",
            episode_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            start_ms=0,
            end_ms=10,
            check_id=check_id,
            family=CheckFamily.TECHNICAL,
            severity=severity,
            outcome=outcome,
            coverage=CoverageStatus.CHECKED
            if outcome is QAOutcome.PASS
            else CoverageStatus.PARTIAL
            if outcome is QAOutcome.UNKNOWN
            else CoverageStatus.CHECKED,
            expected=None,
            observed=None,
            evidence_source="FAKE_FIXTURE",
            evidence_ref="r",
            evidence_note="n",
            provenance="ORIGINAL_FIXTURE",
        )

    from microdrama.qa.config import CRITICAL_CHECK_IDS

    all_pass = [finding(cid, QAOutcome.PASS) for cid in CRITICAL_CHECK_IDS]
    green, blocking, _ = green_summary(all_pass, CRITICAL_CHECK_IDS)
    assert green and blocking == []

    missing_one = all_pass[:-1]  # one critical check never emitted anything
    green, _, _ = green_summary(missing_one, CRITICAL_CHECK_IDS)
    assert not green

    one_unknown = all_pass[:-1] + [finding(CRITICAL_CHECK_IDS[-1], QAOutcome.UNKNOWN)]
    green, _, unknown = green_summary(one_unknown, CRITICAL_CHECK_IDS)
    assert not green and CRITICAL_CHECK_IDS[-1] in unknown

    one_blocked = all_pass[:-1] + [
        finding(CRITICAL_CHECK_IDS[-1], QAOutcome.BLOCKED, Severity.CRITICAL)
    ]
    green, blocking, _ = green_summary(one_blocked, CRITICAL_CHECK_IDS)
    assert not green and CRITICAL_CHECK_IDS[-1] in blocking


def test_summarize_coverage_caps_window_entries() -> None:
    asset_id = uuid.uuid4()
    windows = partition_coverage(
        asset_id,
        CheckFamily.TEMPORAL,
        60_000,
        tuple((i * 1_000, i * 1_000 + 500) for i in range(40)),
    )
    summary = summarize_coverage(windows, max_entries=10)
    payload = summary["TEMPORAL"]
    assert payload["window_count"] == len(windows)
    assert len(payload["windows"]) == 10
    assert payload["truncated"] is True

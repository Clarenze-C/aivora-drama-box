"""Contract tests for the observation-first QA lane (T018).

Real module outputs (real database, T007 media) checked against the FROZEN contracts
at 1.5.0: the persisted frozen report validates as ``contracts.ObservationReport``
and its request as ``contracts.ObservationRequest`` — a schema that structurally
rejects any script-carrying field; every persisted comparison finding validates as
``contracts.QAFinding`` carrying ``source_pass=PASS_B_COMPARISON`` and is bound to
the frozen row; the honesty invariants hold on stored rows; and both lane events
stay inside the 16 KiB payload bound with their coverage windows.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from qa_support import QAWorld
from test_observation_support import (
    comparison_service,
    observation_service,
)

from microdrama.contracts.qa import (
    ComparisonRequest,
    ObservationReport,
    ObservationRequest,
    QAFinding,
)
from microdrama.qa.comparison import PASS_B_EVENT
from microdrama.qa.observation import PASS_A_EVENT

MAX_EVENT_PAYLOAD_BYTES = 16_384


@pytest.fixture
def observed_and_compared(defect_suite, qa_world: QAWorld):
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["wrong_amount"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    run = comparison_service(qa_world).compare(episode_id)
    return qa_world, episode_id, frozen, run


def test_frozen_report_and_request_satisfy_the_frozen_contracts(observed_and_compared) -> None:
    qa_world, _episode, frozen, _run = observed_and_compared
    row = qa_world.row(
        "SELECT report, request_id, request_sha256, report_sha256 FROM qa_observations "
        "WHERE id = %s",
        (frozen.report.report_id,),
    )
    assert row is not None
    stored = ObservationReport.model_validate(row["report"])
    assert stored == frozen.report
    assert str(stored.request_id) == str(row["request_id"])
    # the Pass A input validates as the closed ObservationRequest contract
    request = ObservationRequest.model_validate(frozen.request.model_dump(mode="json"))
    assert request.media and request.questions
    assert request.reservation_id is None  # unpriced offline run carries no reservation


def test_observation_request_schema_has_no_field_for_intended_answers(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    payload = frozen.request.model_dump(mode="json")
    # the schema is closed: a script-carrying field is rejected, not ignored
    with pytest.raises(ValidationError):
        ObservationRequest.model_validate(
            {**payload, "script_text": "ลุงเล็ก หนี้ห้าหมื่นบาท", "expected_terms": ["ห้าหมื่นบาท"]}
        )
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate(
            {
                "request_id": payload["request_id"],
                "episode_id": payload["episode_id"],
                "observation_report_id": str(frozen.report.report_id),
                "observation_report_sha256": "0" * 64,
                "script_id": "0" * 32,
                "script_version": 1,
                "script_sha256": "0" * 64,
                "canon_version": 1,
                "canon_sha256": "0" * 64,
                "script_body": {"scenes": []},  # Pass B references, never embeds
            }
        )


def test_persisted_comparison_findings_satisfy_the_frozen_contract(observed_and_compared) -> None:
    qa_world, episode_id, frozen, run = observed_and_compared
    rows = qa_world.rows(
        "SELECT * FROM qa_findings WHERE episode_id = %s AND qa_cycle = %s ORDER BY id",
        (episode_id, run.qa_cycle),
    )
    assert rows
    for row in rows:
        finding = QAFinding.model_validate(row["body"])
        assert str(finding.finding_id) == str(row["id"])
        assert finding.check_id == row["check_id"]
        assert finding.severity.value == row["severity"]
        assert finding.coverage.value == row["coverage"]
        assert finding.outcome.value == row["outcome"]
        assert finding.source_pass.value == row["source_pass"] == "PASS_B_COMPARISON"
        assert str(row["observation_id"]) == str(frozen.report.report_id)
        assert finding.evidence, "every finding carries its provenance evidence"
    # the wrong-amount defect fired through the comparison pass
    assert any(row["check_id"] == "asr.critical_term_match" for row in rows)


def test_honesty_invariants_hold_on_persisted_rows(observed_and_compared) -> None:
    qa_world, _episode, _frozen, _run = observed_and_compared
    bad_unknown = qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE coverage IN "
        "('UNSAMPLED','UNAVAILABLE') AND outcome <> 'UNKNOWN'"
    )["n"]
    bad_pass = qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE outcome = 'PASS' AND coverage <> 'CHECKED'"
    )["n"]
    assert bad_unknown == 0
    assert bad_pass == 0


def test_lane_events_are_bounded_and_carry_coverage(observed_and_compared) -> None:
    qa_world, episode_id, _frozen, _run = observed_and_compared
    for event_type in (PASS_A_EVENT, PASS_B_EVENT):
        events = qa_world.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
            (episode_id, event_type),
        )
        assert len(events) == 1
        payload = dict(events[0]["payload"])
        assert len(json.dumps(payload).encode()) <= MAX_EVENT_PAYLOAD_BYTES
        coverage = payload["coverage"]
        assert "ASR" in coverage
        for family_summary in coverage.values():
            assert family_summary["window_count"] >= 1
            for _start, _end, status in family_summary["windows"]:
                assert status in ("CHECKED", "PARTIAL", "UNSAMPLED", "UNAVAILABLE")

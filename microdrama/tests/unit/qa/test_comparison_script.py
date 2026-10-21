"""Pass B script-comparison tests (T018, AT-06): the frozen report meets the script.

The clean fixture compared against the pristine script is green; the seeded defects
(wrong amount, wrong speaker, identity swap, missing audio) break the comparison with
their expected check ids — and every persisted finding is bound to the frozen
observation row it came from, carries ``source_pass=PASS_B_COMPARISON``, and replays
idempotently. The frozen row itself is byte-identical before and after Pass B.
"""

from __future__ import annotations

import uuid

import pytest
from qa_support import QAWorld
from test_observation_support import (
    RecordingComparator,
    comparison_service,
    observation_service,
)

from microdrama.contracts.enums import QAOutcome, QAPass
from microdrama.contracts.errors import NotFound
from microdrama.qa.comparison import PASS_B_EVENT
from microdrama.qa.models import QARunStatus

_BAD = (QAOutcome.REPAIRABLE, QAOutcome.BLOCKED, QAOutcome.UNKNOWN)


def _observe_and_compare(qa_world: QAWorld, episode_id, asset_id, **kwargs):
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    run = comparison_service(qa_world).compare(episode_id, **kwargs)
    return frozen, run


def _defect_run(defect_suite, qa_world: QAWorld, kind: str):
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite[kind])
    return _observe_and_compare(qa_world, episode_id, asset_id)


def test_clean_media_comparison_is_green(defect_suite, qa_world: QAWorld) -> None:
    frozen, run = _defect_run(defect_suite, qa_world, "clean")
    assert run.status is QARunStatus.COMPLETED
    assert run.all_checks_green, [
        (f.check_id, f.outcome, f.coverage) for f in run.findings if f.blocks_release
    ]
    assert run.blocking_check_ids == []
    assert run.observation_report_id == frozen.report.report_id
    # the honest unknowns stay visible even on a green comparison
    assert "visual_identity.anchor_match" in run.unknown_check_ids
    assert "narrative.planned_reveal_absent" in run.unknown_check_ids
    assert all(f.source_pass is QAPass.PASS_B_COMPARISON for f in run.findings)


@pytest.mark.parametrize(
    ("kind", "expected_check"),
    [
        ("wrong_amount", "asr.critical_term_match"),
        ("wrong_speaker", "asr.speaker_match"),
        ("identity_swap", "visual_identity.match"),
        ("missing_audio", "asr.line_present"),
    ],
)
def test_seeded_defect_breaks_the_comparison(
    defect_suite, qa_world: QAWorld, kind: str, expected_check: str
) -> None:
    _frozen, run = _defect_run(defect_suite, qa_world, kind)
    fired = [f for f in run.findings if f.check_id == expected_check]
    assert fired, f"{kind}: expected a {expected_check} finding"
    assert any(f.outcome in _BAD for f in fired)
    assert not run.all_checks_green, f"{kind}: a seeded defect must break the comparison"


def test_observed_side_comes_from_the_media_not_the_script(defect_suite, qa_world: QAWorld) -> None:
    _frozen, run = _defect_run(defect_suite, qa_world, "wrong_amount")
    bad = [
        f
        for f in run.findings
        if f.check_id == "asr.critical_term_match" and f.outcome is QAOutcome.REPAIRABLE
    ]
    assert bad
    # expected: the pristine script term; observed: the words actually spoken
    assert all(f.expected and "50,000 baht" in f.expected for f in bad)
    assert all(f.observed and "50,000" not in f.observed for f in bad)


def test_findings_persist_bound_to_the_frozen_observation(defect_suite, qa_world: QAWorld) -> None:
    frozen, run = _defect_run(defect_suite, qa_world, "clean")
    rows = qa_world.rows(
        "SELECT * FROM qa_findings WHERE episode_id = %s AND qa_cycle = %s "
        "ORDER BY id",
        (run.episode_id, run.qa_cycle),
    )  # fmt: skip
    assert rows
    assert all(str(row["observation_id"]) == str(frozen.report.report_id) for row in rows)
    assert {row["source_pass"] for row in rows} == {"PASS_B_COMPARISON"}
    events = qa_world.rows(
        "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
        (run.episode_id, PASS_B_EVENT),
    )
    assert len(events) == 1
    payload = dict(events[0]["payload"])
    assert len(payload["run_key"]) == 64
    assert payload["observation_report_id"] == str(frozen.report.report_id)
    assert payload["all_checks_green"] is True
    assert "ASR" in payload["coverage"]


def test_identical_comparison_replays_without_new_rows(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    _frozen, first = _observe_and_compare(qa_world, episode_id, asset_id)
    second = comparison_service(qa_world).compare(episode_id)
    assert second.status is QARunStatus.REPLAYED
    # the same finding set (rows load ordered by id; construction order differs)
    assert sorted(f.finding_id for f in second.findings) == sorted(
        f.finding_id for f in first.findings
    )
    assert second.all_checks_green == first.all_checks_green
    assert second.settled_micro_usd == 0
    assert qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE episode_id = %s", (episode_id,)
    )["n"] == len(first.findings)
    assert (
        len(
            qa_world.rows(
                "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
                (episode_id, PASS_B_EVENT),
            )
        )
        == 1
    )


def test_comparison_leaves_the_frozen_row_byte_identical(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    before = qa_world.row(
        "SELECT report, report_sha256, created_at FROM qa_observations WHERE id = %s",
        (frozen.report.report_id,),
    )
    comparison_service(qa_world).compare(episode_id)
    comparison_service(qa_world).compare(episode_id)  # and again (replay)
    after = qa_world.row(
        "SELECT report, report_sha256, created_at FROM qa_observations WHERE id = %s",
        (frozen.report.report_id,),
    )
    assert before["report"] == after["report"]
    assert before["report_sha256"] == after["report_sha256"]
    assert (
        qa_world.row(
            "SELECT COUNT(*) AS n FROM qa_observations WHERE episode_id = %s", (episode_id,)
        )["n"]
        == 1
    )


def test_mutating_comparator_is_refused_typed_and_keeps_its_charge(
    defect_suite, qa_world: QAWorld
) -> None:
    from microdrama.contracts.enums import PriceUnit
    from microdrama.contracts.errors import Conflict
    from microdrama.qa import QAConfig
    from microdrama.testing.fakes.common import fake_price_quote

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)

    def mutate(report):
        report.transcript.append(report.transcript[0].model_copy())  # a rogue rewrite

    priced = QAConfig(observer_price=fake_price_quote(PriceUnit.REQUEST))
    mutating = RecordingComparator(mutate=mutate, config=priced)
    with pytest.raises(Conflict, match="modify the frozen observation"):
        comparison_service(qa_world, config=priced, comparator=mutating).compare(episode_id)
    # the charge for the dispatched (and refused) comparison is kept
    reservations = qa_world.rows("SELECT * FROM reservations WHERE episode_id = %s", (episode_id,))
    assert len(reservations) == 1
    assert reservations[0]["state"] == "SETTLED"
    # no findings persisted, and the frozen row is untouched
    assert qa_world.rows("SELECT * FROM qa_findings WHERE episode_id = %s", (episode_id,)) == []
    stored = qa_world.row(
        "SELECT report_sha256 FROM qa_observations WHERE id = %s", (frozen.report.report_id,)
    )
    assert stored["report_sha256"]


def test_frozen_attribute_assignment_is_refused_inside_the_comparator(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)

    def mutate(report):
        report.provenance = "DERIVED_LOCAL"  # type: ignore[misc]  # must refuse

    guarded = RecordingComparator(mutate=mutate)
    run = comparison_service(qa_world, comparator=guarded).compare(episode_id)
    assert guarded.calls == 1
    assert guarded.mutation_errors, "attribute assignment on the frozen report must refuse"
    assert run.status is QARunStatus.COMPLETED  # the refused mutation changed nothing


def test_compare_without_a_frozen_observation_is_a_typed_not_found(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, _asset = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    with pytest.raises(NotFound, match="Pass A"):
        comparison_service(qa_world).compare(episode_id)
    with pytest.raises(NotFound):
        comparison_service(qa_world).compare(episode_id, observation_report_id=uuid.uuid4())

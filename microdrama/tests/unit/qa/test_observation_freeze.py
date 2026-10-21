"""Freeze and immutability tests (T018, AT-06/IMP-04): the first report stands.

The frozen observation is an append-only ``qa_observations`` row: the database
rejects UPDATE/DELETE, a re-freeze with different content under the same request id
is a typed ``IdempotencyConflict``, a tampered body is detected on read by its
recorded hash, and the frozen payload model itself refuses attribute assignment.
An identical rerun replays the stored report without a second observer call.
"""

from __future__ import annotations

import uuid

import pytest
from qa_support import T0, QAWorld
from test_observation_support import observation_service

from microdrama.contracts.enums import CheckFamily, CoverageStatus, Provenance
from microdrama.contracts.errors import Conflict, IdempotencyConflict, NotFound
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.qa import CoverageWindow, ObservationReport
from microdrama.persistence import insert_row, jsonb
from microdrama.qa.observation import (
    default_neutral_questions,
    frozen_report,
    latest_frozen_report,
    observation_request_id,
    request_fingerprint,
)


def _row(qa_world: QAWorld, report_id: uuid.UUID) -> dict:
    return qa_world.row("SELECT * FROM qa_observations WHERE id = %s", (report_id,))


def _observe_clean(defect_suite, qa_world: QAWorld):
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    return episode_id, asset_id, frozen


def test_observation_freezes_and_persists_an_immutable_row(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset, frozen = _observe_clean(defect_suite, qa_world)
    row = _row(qa_world, frozen.report.report_id)
    assert row is not None
    assert row["episode_id"] == episode_id
    assert row["request_id"] == frozen.request.request_id
    assert row["report_sha256"] == canonical_hash(frozen.report)
    assert row["request_sha256"] == frozen.report.request_sha256
    # the persisted body IS the frozen contract report, hash-consistent
    stored = ObservationReport.model_validate(row["report"])
    assert stored == frozen.report
    # the run event records the freeze with its coverage windows
    events = qa_world.rows(
        "SELECT payload FROM domain_events WHERE aggregate_id = %s "
        "AND event_type = 'qa.observation.frozen'",
        (episode_id,),
    )
    assert len(events) == 1
    assert events[0]["payload"]["report_sha256"] == row["report_sha256"]
    assert "ASR" in events[0]["payload"]["coverage"]


def test_frozen_row_is_append_only(defect_suite, qa_world: QAWorld) -> None:
    _episode, _asset, frozen = _observe_clean(defect_suite, qa_world)
    with pytest.raises(Exception, match="append-only"):
        with qa_world.db.transaction() as tx:
            tx.execute(
                "UPDATE qa_observations SET report = '{\"tampered\": true}'::jsonb WHERE id = %s",
                (frozen.report.report_id,),
            )


def test_replay_returns_the_stored_report_without_a_second_call(
    defect_suite, qa_world: QAWorld
) -> None:
    from test_observation_support import SpyObserver

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    spy = SpyObserver(qa_world.observer())
    service = observation_service(qa_world, observer=spy)
    first = service.observe_media(episode_id, asset_id=asset_id)
    second = service.observe_media(episode_id, asset_id=asset_id)

    assert spy.calls == 1  # the observer ran exactly once
    assert second.replayed
    assert second.report == first.report
    assert second.settled_micro_usd == 0
    assert (
        qa_world.row(
            "SELECT COUNT(*) AS n FROM qa_observations WHERE episode_id = %s", (episode_id,)
        )["n"]
        == 1
    )


def test_refreeze_attempt_with_different_content_is_a_typed_conflict(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    # Pre-plant a row under the SAME deterministic request id the service will derive
    # (episode + media sha + default questions), but wearing a different input
    # identity: a rewrite attempt under an existing request id.
    descriptor = qa_world.row("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))[
        "descriptor"
    ]
    request_id = observation_request_id(
        episode_id, descriptor["sha256"][:16], request_fingerprint(default_neutral_questions(), "th-TH")
    )  # fmt: skip
    other = ObservationReport(
        report_id=uuid.uuid4(),
        request_id=request_id,
        request_sha256="f" * 64,
        episode_id=episode_id,
        media_sha256=["e" * 64],
        coverage=[
            CoverageWindow(
                asset_id=asset_id,
                check_family=CheckFamily.ASR,
                start_ms=0,
                end_ms=1,
                status=CoverageStatus.UNAVAILABLE,
            )
        ],
        model_config_ref="rogue",
        provenance=Provenance.DERIVED_LOCAL,
        frozen_at=T0,
    )
    with qa_world.db.transaction() as tx:
        insert_row(
            tx,
            "qa_observations",
            {
                "id": other.report_id,
                "episode_id": episode_id,
                "request_id": other.request_id,
                "request_sha256": other.request_sha256,
                "media_sha256": jsonb(other.media_sha256),
                "report": jsonb(other),
                "report_sha256": canonical_hash(other),
                "provenance": other.provenance.value,
                "frozen_at": other.frozen_at,
            },
        )
    with pytest.raises(IdempotencyConflict):
        observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    # the planted row is untouched: nothing was rewritten
    assert _row(qa_world, other.report_id)["report_sha256"] == canonical_hash(other)
    assert (
        qa_world.row(
            "SELECT COUNT(*) AS n FROM qa_observations WHERE episode_id = %s", (episode_id,)
        )["n"]
        == 1
    )


def test_tampered_report_body_is_detected_on_read(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    # A VALID report body stored under a recorded sha it does not hash to (inserted
    # directly; updates are forbidden) must refuse to load as evidence.
    valid_body = ObservationReport(
        report_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        request_sha256="0" * 64,
        episode_id=episode_id,
        media_sha256=["1" * 64],
        coverage=[
            CoverageWindow(
                asset_id=asset_id,
                check_family=CheckFamily.ASR,
                start_ms=0,
                end_ms=1,
                status=CoverageStatus.UNAVAILABLE,
            )
        ],
        model_config_ref="x",
        provenance=Provenance.ORIGINAL_FIXTURE,
        frozen_at=T0,
    )
    bad_id = valid_body.report_id
    with qa_world.db.transaction() as tx:
        insert_row(
            tx,
            "qa_observations",
            {
                "id": bad_id,
                "episode_id": episode_id,
                "request_id": valid_body.request_id,
                "request_sha256": "0" * 64,
                "media_sha256": jsonb(valid_body.media_sha256),
                "report": jsonb(valid_body),
                "report_sha256": "2" * 64,  # does not hash to the body above
                "provenance": "ORIGINAL_FIXTURE",
                "frozen_at": valid_body.frozen_at,
            },
        )
    with pytest.raises(Conflict, match="recorded hash"):
        frozen_report(qa_world.db, bad_id)
    with pytest.raises(NotFound):
        frozen_report(qa_world.db, uuid.uuid4())


def test_frozen_report_model_rejects_attribute_mutation(defect_suite, qa_world: QAWorld) -> None:
    from pydantic import ValidationError

    _episode, _asset, frozen = _observe_clean(defect_suite, qa_world)
    with pytest.raises(ValidationError):
        frozen.report.transcript = []  # type: ignore[misc]


def test_latest_frozen_report_reads_read_only(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset_id, frozen = _observe_clean(defect_suite, qa_world)
    latest = latest_frozen_report(qa_world.db, episode_id)
    assert latest == frozen.report
    assert latest_frozen_report(qa_world.db, uuid.uuid4()) is None
    # one freeze, one row, nothing changed by the read
    assert (
        qa_world.row(
            "SELECT COUNT(*) AS n FROM qa_observations WHERE episode_id = %s", (episode_id,)
        )["n"]
        == 1
    )

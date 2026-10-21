"""Pass B cost tests (T018): the comparison is its own reserved, metered call.

Default config: the offline comparator is free and nothing is reserved. With
``observer_price`` configured, every paid comparison holds its own real QA_CAPTIONS
reservation BEFORE the comparator is dispatched (probe snapshot taken inside the
compare call), one comparator call settles one unit, a failed comparison KEEPS its
charge (settled at the held worst case, never released), a retry is a new versioned
step, and a replay charges nothing. Pass A and Pass B hold separate reservations.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from test_observation_support import (
    RecordingComparator,
    comparison_service,
    observation_service,
)

from microdrama.contracts.enums import PriceUnit, ReceiptKind
from microdrama.contracts.errors import ProviderError
from microdrama.qa import QAConfig
from microdrama.testing.fakes.common import fake_price_quote


def _priced() -> QAConfig:
    return QAConfig(observer_price=fake_price_quote(PriceUnit.AUDIO_SECOND))


def _reservations(qa_world: QAWorld, episode_id, operation: str | None = None):
    rows = qa_world.rows(
        "SELECT * FROM reservations WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )
    return rows if operation is None else [r for r in rows if r["operation_kind"] == operation]


def _charges(qa_world: QAWorld, episode_id):
    return qa_world.rows(
        "SELECT * FROM charges WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )


def _observed(defect_suite, qa_world: QAWorld):
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    return episode_id, asset_id


def test_unpriced_comparison_reserves_nothing_and_says_so(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _observed(defect_suite, qa_world)
    run = comparison_service(qa_world).compare(episode_id)
    assert run.reservation_id is None
    assert run.settled_micro_usd == 0
    assert _reservations(qa_world, episode_id) == []
    assert any("free" in note for note in run.notes)


def test_priced_comparison_holds_its_reservation_before_dispatch_and_settles(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, _asset = _observed(defect_suite, qa_world)

    def probe():
        rows = _reservations(qa_world, episode_id, "qa.compare_intent")
        return [(row["state"], row["reserved_micro_usd"]) for row in rows]

    recording = RecordingComparator(probe=probe, config=_priced())
    run = comparison_service(qa_world, config=_priced(), comparator=recording).compare(episode_id)

    assert recording.calls == 1
    # at dispatch time exactly one ACTIVE comparison reservation was already held
    assert recording.snapshots == [[("ACTIVE", 500)]]
    assert run.reservation_id is not None
    assert run.settled_micro_usd == 500  # 5 s x 100 micro-USD, like Pass A
    rows = _reservations(qa_world, episode_id, "qa.compare_intent")
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"
    assert rows[0]["category"] == "QA_CAPTIONS"
    charges = _charges(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == 500
    assert charges[0]["provider"] == "qa-offline-comparator"
    assert charges[0]["kind"] == ReceiptKind.SETTLEMENT.value


def test_failed_comparison_keeps_its_charge(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _observed(defect_suite, qa_world)
    failing = RecordingComparator(raises=RuntimeError("comparator backend died"))
    with pytest.raises(ProviderError, match="charge is kept"):
        comparison_service(qa_world, config=_priced(), comparator=failing).compare(episode_id)
    assert failing.calls == 1
    rows = _reservations(qa_world, episode_id, "qa.compare_intent")
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"  # settled, never released
    charges = _charges(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == rows[0]["reserved_micro_usd"]
    assert charges[0]["provider_receipt_id"].startswith("qa-compare-failure:")
    # a failed attempt leaves no comparison findings behind
    assert qa_world.rows("SELECT * FROM qa_findings WHERE episode_id = %s", (episode_id,)) == []


def test_priced_failure_then_retry_is_a_new_versioned_step(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _observed(defect_suite, qa_world)
    with pytest.raises(ProviderError):
        comparison_service(
            qa_world, config=_priced(), comparator=RecordingComparator(raises=RuntimeError("x"))
        ).compare(episode_id)
    run = comparison_service(qa_world, config=_priced()).compare(episode_id)
    assert run.settled_micro_usd == 500
    rows = _reservations(qa_world, episode_id, "qa.compare_intent")
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {"SETTLED"}
    assert len({row["semantic_key"] for row in rows}) == 2
    assert len(_charges(qa_world, episode_id)) == 2


def test_replay_charges_nothing_and_passes_hold_separate_reservations(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observation_service(qa_world, config=_priced()).observe_media(episode_id, asset_id=asset_id)
    service = comparison_service(qa_world, config=_priced())
    service.compare(episode_id)
    second = service.compare(episode_id)
    assert second.status.value == "REPLAYED"
    assert second.settled_micro_usd == 0
    # Pass A and Pass B each held their own reservation; the replay added none
    all_rows = _reservations(qa_world, episode_id)
    assert len(all_rows) == 2
    assert {row["operation_kind"] for row in all_rows} == {
        "qa.observe_blind",
        "qa.compare_intent",
    }
    assert len(_charges(qa_world, episode_id)) == 2

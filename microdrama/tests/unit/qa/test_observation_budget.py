"""Pass A cost tests (T018): the blind observation is a reserved, metered step.

Default config: the offline observation is free and NOTHING is reserved — the run
says so. With ``observer_price`` configured the full discipline runs: a real
QA_CAPTIONS reservation is held BEFORE the observer is dispatched (proved by a probe
snapshot taken inside the observe call), actual usage settles it, a failed
observation KEEPS its charge (settled at the worst case, never released), a retry is
a new versioned step, and a replay charges nothing.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from test_observation_support import (
    RaisingObserver,
    SpyObserver,
    observation_service,
)

from microdrama.contracts.enums import PriceUnit, ReceiptKind
from microdrama.contracts.errors import ProviderError
from microdrama.qa import QAConfig
from microdrama.testing.fakes.common import fake_price_quote


def _priced() -> QAConfig:
    return QAConfig(observer_price=fake_price_quote(PriceUnit.AUDIO_SECOND))


def _reservations(qa_world: QAWorld, episode_id):
    return qa_world.rows(
        "SELECT * FROM reservations WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )


def _charges(qa_world: QAWorld, episode_id):
    return qa_world.rows(
        "SELECT * FROM charges WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )


def test_unpriced_observation_reserves_nothing_and_says_so(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    frozen = observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    assert frozen.reservation_id is None
    assert frozen.settled_micro_usd == 0
    assert _reservations(qa_world, episode_id) == []
    assert any("free" in note for note in frozen.notes)


def test_priced_observation_holds_the_reservation_before_dispatch_and_settles(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])

    def probe():
        rows = _reservations(qa_world, episode_id)
        return [(row["state"], row["reserved_micro_usd"]) for row in rows]

    spy = SpyObserver(qa_world.observer(), probe=probe)
    frozen = observation_service(qa_world, _priced(), observer=spy).observe_media(
        episode_id, asset_id=asset_id
    )

    assert spy.calls == 1
    # at dispatch time exactly one ACTIVE reservation was already held (5 s × 100)
    assert spy.snapshots == [[("ACTIVE", 500)]]
    assert frozen.reservation_id is not None
    assert frozen.settled_micro_usd == 500
    rows = _reservations(qa_world, episode_id)
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"
    assert rows[0]["category"] == "QA_CAPTIONS"
    charges = _charges(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == 500
    assert charges[0]["cost_basis"] == "SYNTHETIC_FAKE"
    assert charges[0]["kind"] == ReceiptKind.SETTLEMENT.value


def test_failed_observation_keeps_its_charge(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    failing = RaisingObserver()
    with pytest.raises(ProviderError, match="charge is kept"):
        observation_service(qa_world, _priced(), observer=failing).observe_media(
            episode_id, asset_id=asset_id
        )
    assert failing.calls == 1
    rows = _reservations(qa_world, episode_id)
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"  # settled, never released
    charges = _charges(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == rows[0]["reserved_micro_usd"]
    assert charges[0]["provider_receipt_id"].startswith("qa-observe-a-failure:")
    # a failed attempt leaves no frozen claim behind
    assert qa_world.rows("SELECT * FROM qa_observations WHERE episode_id = %s", (episode_id,)) == []


def test_priced_failure_then_retry_is_a_new_versioned_step(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    with pytest.raises(ProviderError):
        observation_service(qa_world, _priced(), observer=RaisingObserver()).observe_media(
            episode_id, asset_id=asset_id
        )
    # a later successful blind observation is a NEW paid step: its own reservation
    frozen = observation_service(qa_world, _priced(), observer=qa_world.observer()).observe_media(
        episode_id, asset_id=asset_id
    )
    assert frozen.settled_micro_usd == 500
    rows = _reservations(qa_world, episode_id)
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {"SETTLED"}
    assert len(_charges(qa_world, episode_id)) == 2
    assert len({row["semantic_key"] for row in rows}) == 2


def test_replay_charges_nothing(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = observation_service(qa_world, _priced())
    service.observe_media(episode_id, asset_id=asset_id)
    second = service.observe_media(episode_id, asset_id=asset_id)
    assert second.replayed
    assert second.settled_micro_usd == 0
    assert len(_charges(qa_world, episode_id)) == 1
    assert len(_reservations(qa_world, episode_id)) == 1

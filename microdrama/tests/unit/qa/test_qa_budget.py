"""Budget metering tests (T017): the QA_CAPTIONS hook on the observation step.

Default config: the offline observer is free and NOTHING is reserved — and the run
says so. With a price configured, the full discipline runs: a real reservation is
held BEFORE the observation is dispatched, actual usage settles it, a failed
observation KEEPS its charge (never released as unbilled), and a replay charges
nothing.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld, RecordingObserver

from microdrama.contracts.enums import PriceUnit, ReceiptKind
from microdrama.qa import QAConfig
from microdrama.testing.fakes.common import fake_price_quote


def _priced() -> QAConfig:
    return QAConfig(observer_price=fake_price_quote(PriceUnit.AUDIO_SECOND))


def _reservation_rows(qa_world: QAWorld, episode_id):
    return qa_world.rows(
        "SELECT * FROM reservations WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )


def _charge_rows(qa_world: QAWorld, episode_id):
    return qa_world.rows(
        "SELECT * FROM charges WHERE episode_id = %s ORDER BY created_at", (episode_id,)
    )


def test_default_config_reserves_nothing_and_says_so(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    assert run.reservation_id is None
    assert run.settled_micro_usd == 0
    assert _reservation_rows(qa_world, episode_id) == []
    assert any("free" in note for note in run.notes)


def test_priced_run_holds_the_reservation_before_dispatch_and_settles(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])

    def probe():
        rows = _reservation_rows(qa_world, episode_id)
        return [(row["state"], row["reserved_micro_usd"]) for row in rows]

    observer = RecordingObserver(probe=probe)
    run = qa_world.service(_priced(), observer=observer).run_episode_qa(
        episode_id, asset_id=asset_id
    )
    assert observer.calls == 1
    # at dispatch time exactly one ACTIVE reservation was already held
    assert observer.snapshots == [[("ACTIVE", 500)]]
    assert run.reservation_id is not None
    assert run.settled_micro_usd == 500  # 5 s x 100 micro-USD synthetic audio-second
    rows = _reservation_rows(qa_world, episode_id)
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"
    assert rows[0]["category"] == "QA_CAPTIONS"
    charges = _charge_rows(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == 500
    assert charges[0]["cost_basis"] == "SYNTHETIC_FAKE"
    assert charges[0]["kind"] == ReceiptKind.SETTLEMENT.value


def test_failed_observation_keeps_its_charge(defect_suite, qa_world: QAWorld) -> None:
    from microdrama.contracts.errors import ProviderError

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observer = RecordingObserver(raises=RuntimeError("asr backend exploded"))
    with pytest.raises(ProviderError, match="charge is kept"):
        qa_world.service(_priced(), observer=observer).run_episode_qa(episode_id, asset_id=asset_id)
    rows = _reservation_rows(qa_world, episode_id)
    assert len(rows) == 1
    assert rows[0]["state"] == "SETTLED"  # settled, never released
    charges = _charge_rows(qa_world, episode_id)
    assert len(charges) == 1
    assert charges[0]["amount_micro_usd"] == rows[0]["reserved_micro_usd"]
    assert charges[0]["provider_receipt_id"].startswith("qa-observe-failure:")
    # a failed attempt leaves no QA claim behind
    assert qa_world.findings_rows(episode_id) == []
    assert qa_world.run_events(episode_id) == []


def test_replay_charges_nothing(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = qa_world.service(_priced())
    service.run_episode_qa(episode_id, asset_id=asset_id)
    second = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status.value == "REPLAYED"
    assert second.settled_micro_usd == 0
    assert len(_charge_rows(qa_world, episode_id)) == 1
    assert len(_reservation_rows(qa_world, episode_id)) == 1


def test_priced_failure_then_retry_reserves_once_more_with_a_new_step(
    defect_suite, qa_world: QAWorld
) -> None:
    from microdrama.contracts.errors import ProviderError

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    failing = RecordingObserver(raises=RuntimeError("first attempt dies"))
    with pytest.raises(ProviderError):
        qa_world.service(_priced(), observer=failing).run_episode_qa(episode_id, asset_id=asset_id)
    # a later successful run is a NEW paid step: its own reservation, its own charge
    ok = RecordingObserver()
    run = qa_world.service(_priced(), observer=ok).run_episode_qa(episode_id, asset_id=asset_id)
    assert run.settled_micro_usd == 500
    rows = _reservation_rows(qa_world, episode_id)
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {"SETTLED"}
    assert len(_charge_rows(qa_world, episode_id)) == 2

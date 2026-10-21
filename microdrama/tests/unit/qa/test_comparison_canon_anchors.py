"""Canon and identity-anchor comparison tests (T018).

Pass B is where the intended answers finally enter: the compiled canon (planned
reveals must stay unspoken before their episode; a stale canon version refuses the
comparison typed) and the identity lock (an observed character needs a LOCKED face
anchor; a broken member is critical; without a lock the check is an honest UNKNOWN).
"""

from __future__ import annotations

import uuid

import pytest
from qa_support import QAWorld
from test_observation_support import (
    CLEAN_LINE_TH,
    comparison_service,
    observation_service,
    seed_canon,
    seed_identity_lock,
)

from microdrama.contracts.enums import QAOutcome, Severity
from microdrama.contracts.errors import Conflict, NotFound
from microdrama.qa.comparison import ANCHOR_CHECK, REVEAL_CHECK


def _prepare(defect_suite, qa_world: QAWorld):
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    observation_service(qa_world).observe_media(episode_id, asset_id=asset_id)
    return episode_id, asset_id


def test_anchor_check_is_unknown_without_a_lock(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    run = comparison_service(qa_world).compare(episode_id)
    anchors = [f for f in run.findings if f.check_id == ANCHOR_CHECK]
    assert len(anchors) == 1
    assert anchors[0].outcome is QAOutcome.UNKNOWN
    assert anchors[0].coverage.value == "UNAVAILABLE"
    assert ANCHOR_CHECK in run.unknown_check_ids


def test_observed_character_without_a_locked_anchor_is_critical(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = _prepare(defect_suite, qa_world)
    lock_id = seed_identity_lock(qa_world, episode_id, asset_id, [("fon", "LOCKED")])
    run = comparison_service(qa_world).compare(episode_id, identity_lock_id=lock_id)
    anchors = [f for f in run.findings if f.check_id == ANCHOR_CHECK]
    critical = [
        f for f in anchors if f.severity is Severity.CRITICAL and f.outcome is QAOutcome.REPAIRABLE
    ]
    # lek and nok appear on screen but carry no locked anchor in the lock
    assert {f.expected for f in critical} == {
        "a locked FACE anchor for lek",
        "a locked FACE anchor for nok",
    }
    assert all(f.observed and "no locked anchor" in f.observed for f in critical)
    assert not run.all_checks_green
    assert ANCHOR_CHECK in run.blocking_check_ids


def test_broken_lock_member_flags_the_identity(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = _prepare(defect_suite, qa_world)
    lock_id = seed_identity_lock(
        qa_world,
        episode_id,
        asset_id,
        [("fon", "SUPERSEDED"), ("lek", "LOCKED"), ("nok", "LOCKED")],
    )
    run = comparison_service(qa_world).compare(episode_id, identity_lock_id=lock_id)
    broken = [
        f
        for f in run.findings
        if f.check_id == ANCHOR_CHECK and "stays LOCKED" in (f.expected or "")
    ]
    assert len(broken) == 1
    assert "fon" in broken[0].expected
    assert "SUPERSEDED" in (broken[0].observed or "")
    assert not run.all_checks_green


def test_fully_locked_clean_media_passes_the_anchor_check(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = _prepare(defect_suite, qa_world)
    lock_id = seed_identity_lock(
        qa_world, episode_id, asset_id, [("fon", "LOCKED"), ("lek", "LOCKED"), ("nok", "LOCKED")]
    )
    run = comparison_service(qa_world).compare(episode_id, identity_lock_id=lock_id)
    anchors = [f for f in run.findings if f.check_id == ANCHOR_CHECK]
    assert anchors
    assert all(f.outcome is QAOutcome.PASS for f in anchors)
    assert run.all_checks_green
    assert ANCHOR_CHECK not in run.blocking_check_ids


def test_unknown_identity_lock_id_is_a_typed_not_found(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    with pytest.raises(NotFound):
        comparison_service(qa_world).compare(episode_id, identity_lock_id=uuid.uuid4())


def test_spoken_planned_reveal_is_a_critical_spoiler(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    seed_canon(qa_world, episode_id, reveals=(CLEAN_LINE_TH,))
    run = comparison_service(qa_world).compare(episode_id)
    reveals = [f for f in run.findings if f.check_id == REVEAL_CHECK]
    assert len(reveals) == 1
    assert reveals[0].severity is Severity.CRITICAL
    assert reveals[0].outcome is QAOutcome.REPAIRABLE
    assert reveals[0].observed and "planned reveal" in reveals[0].observed
    assert not run.all_checks_green
    assert REVEAL_CHECK in run.blocking_check_ids


def test_unspoken_reveal_passes_and_canon_binds_the_run(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    seed_canon(qa_world, episode_id, reveals=("ความลับที่ยังไม่เปิดเผย",))
    run = comparison_service(qa_world).compare(episode_id)
    reveals = [f for f in run.findings if f.check_id == REVEAL_CHECK]
    assert len(reveals) == 1
    assert reveals[0].outcome is QAOutcome.PASS
    assert run.request.canon_version == 1
    assert len(run.request.canon_sha256) == 64
    # the same intent again is the same comparison run (a replay)
    second = comparison_service(qa_world).compare(episode_id)
    assert second.status.value == "REPLAYED"


def test_stale_canon_version_refuses_the_comparison(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    seed_canon(qa_world, episode_id, version=2, reveals=())
    with pytest.raises(Conflict, match="different canon"):
        comparison_service(qa_world).compare(episode_id)


def test_comparison_without_canon_is_an_honest_unknown(defect_suite, qa_world: QAWorld) -> None:
    episode_id, _asset = _prepare(defect_suite, qa_world)
    run = comparison_service(qa_world).compare(episode_id)
    reveals = [f for f in run.findings if f.check_id == REVEAL_CHECK]
    assert len(reveals) == 1
    assert reveals[0].outcome is QAOutcome.UNKNOWN
    assert reveals[0].coverage.value == "UNSAMPLED"
    assert "no compiled canon" in (reveals[0].observed or "")
    assert REVEAL_CHECK in run.unknown_check_ids

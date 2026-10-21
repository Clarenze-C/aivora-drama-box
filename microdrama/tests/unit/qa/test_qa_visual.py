"""Visual QA tests (T017): identity swaps, typed-unknown prop and lip-sync checks."""

from __future__ import annotations

from qa_support import QAWorld

from microdrama.contracts.enums import QAOutcome
from microdrama.qa import TechnicalQARun


def _by_id(run: TechnicalQARun, check_id: str):
    return [f for f in run.findings if f.check_id == check_id]


def test_identity_swap_is_critical_and_repairs_the_shot(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["identity_swap"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "visual_identity.match")
    bad = [f for f in fired if f.outcome is QAOutcome.REPAIRABLE]
    assert len(bad) == 1
    assert bad[0].severity.value == "CRITICAL"
    assert bad[0].expected == "fon"  # the pristine script's speaker for s1-l1
    assert bad[0].observed == "lek"  # who the media actually shows
    assert [t.value for t in bad[0].repair_targets] == ["SHOT"]
    assert not run.all_checks_green


def test_clean_identities_pass(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "visual_identity.match")
    assert len(fired) == 3
    assert all(f.outcome is QAOutcome.PASS for f in fired)
    assert {f.observed for f in fired} == {"fon", "lek", "nok"}


def test_prop_check_is_a_typed_unknown_never_a_pass(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "visual_identity.prop_match")
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.UNKNOWN
    assert fired[0].coverage.value == "UNAVAILABLE"
    assert "prop observation source" in (fired[0].observed or "")
    assert "visual_identity.prop_match" in run.unknown_check_ids
    # green stays achievable only because prop checks are not in the critical set
    assert run.all_checks_green


def test_lip_sync_is_a_typed_unknown_with_the_dense_review_note(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    run = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    fired = _by_id(run, "temporal.lip_sync")
    assert len(fired) == 1
    assert fired[0].outcome is QAOutcome.UNKNOWN
    assert fired[0].coverage.value == "UNAVAILABLE"
    assert "dense local review" in (fired[0].observed or "")
    assert "temporal.lip_sync" in run.unknown_check_ids

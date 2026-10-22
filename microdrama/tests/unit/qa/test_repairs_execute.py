"""Repair execution (T019 acceptance 1/2/5, execution side).

A subtitle defect is repaired cue-level into new caption track versions with ZERO
render operations (no render.shot job, no GPU reservation, no shot-dispatch call);
other cues ride along byte-identical. Changed final media reopens the Gate 2 review
package path through typed state transitions — and past Gate 2 there is no path, so
the repair is refused typed instead of silently bypassing the gate.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from repairs_support import L1, L2, RecordingShotDispatch, RepairsWorld

from microdrama.contracts.errors import GateNotReady, InvalidTransition
from microdrama.contracts.media import CaptionTrack
from microdrama.qa.repairs import (
    EXECUTED_EVENT,
    RETURN_EVENT,
)

pytestmark = pytest.mark.db


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


def _current_track(world: RepairsWorld, episode_id, locale: str) -> CaptionTrack:
    row = world.row(
        "SELECT body FROM caption_tracks WHERE episode_id = %s AND locale = %s "
        "AND state = 'CURRENT'",
        (episode_id, locale),
    )
    assert row is not None
    return CaptionTrack.model_validate(row["body"])


def test_caption_defect_is_repaired_cue_level_with_zero_render_operations(
    world: RepairsWorld,
) -> None:
    episode_id, thai, english, package = world.episode_with_tracks()
    old_thai = _current_track(world, episode_id, "th-TH")
    finding = world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    dispatch = RecordingShotDispatch()
    service = world.repairs(shot_dispatch=dispatch)
    outcome = service.plan_from_findings(episode_id)
    execution = service.execute_plan(outcome.plan.plan_id)

    assert execution.status == "COMPLETED"
    assert execution.returns_to_gate2 is True
    assert execution.new_caption_track_ids and execution.settled_micro_usd == 0

    # THE render pipeline is never invoked: no shot-dispatch call, no render.shot
    # job, no GPU reservation anywhere in the database.
    assert dispatch.count_calls == 0
    assert dispatch.dispatch_calls == []
    assert world.rows("SELECT * FROM jobs WHERE job_type = 'render.shot'") == []
    assert world.rows("SELECT * FROM reservations WHERE category = 'GPU_GENERATION'") == []

    # cue-level fix: only L1's cues changed, and they now carry the script text
    new_thai = _current_track(world, episode_id, "th-TH")
    new_en = _current_track(world, episode_id, "en-US")
    l1_thai = next(c for c in new_thai.cues if c.cue_id == f"{L1}.thth")
    l1_en = next(c for c in new_en.cues if c.cue_id == f"{L1}.enus")
    assert l1_thai.text == "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ"
    assert l1_en.text == "Uncle Lek, what is this fifty-thousand-baht debt?"
    old_l2 = next(c for c in old_thai.cues if c.cue_id == f"{L2}.thth")
    new_l2 = next(c for c in new_thai.cues if c.cue_id == f"{L2}.thth")
    assert new_l2 == old_l2  # untouched cues ride along byte-identical
    assert new_thai.version == old_thai.version + 1
    for track_id in (thai, english):
        row = world.row("SELECT state FROM caption_tracks WHERE id = %s", (track_id,))
        assert row["state"] == "SUPERSEDED"

    # the finding the plan covered is resolved; the episode is back at Gate 2 with
    # the review package path reopened (old package superseded, new one prepared).
    assert (
        world.row("SELECT resolution FROM qa_findings WHERE id = %s", (finding,))["resolution"]
        == "RESOLVED"
    )
    assert (
        world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"]
        == "AWAITING_FINAL_REVIEW"
    )
    assert (
        world.row("SELECT status FROM release_packages WHERE id = %s", (package,))["status"]
        == "SUPERSEDED"
    )
    assert world.rows("SELECT * FROM jobs WHERE job_type = 'review.prepare_package'")
    for event_type in ("qa.repair.planned", EXECUTED_EVENT, RETURN_EVENT):
        assert world.rows(
            "SELECT * FROM domain_events WHERE aggregate_id = %s AND event_type = %s",
            (episode_id, event_type),
        )


def test_executing_a_completed_plan_is_an_idempotent_replay(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    service = world.repairs()
    plan_id = service.plan_from_findings(episode_id).plan.plan_id
    first = service.execute_plan(plan_id)
    second = service.execute_plan(plan_id)
    assert second.status == "COMPLETED"
    assert second.plan_id == first.plan_id
    assert "nothing re-executed" in " ".join(second.notes)
    # no duplicate effects: still exactly one CURRENT track per locale
    assert (
        len(
            world.rows(
                "SELECT * FROM caption_tracks WHERE episode_id = %s AND state = 'CURRENT'",
                (episode_id,),
            )
        )
        == 2
    )
    assert len(world.rows("SELECT * FROM jobs WHERE job_type = 'review.prepare_package'")) == 1


def test_final_media_repair_past_gate2_is_refused_typed_never_bypassed(
    world: RepairsWorld,
) -> None:
    # a REAL Gate 2 approval put this episode past the gate (RELEASE_APPROVED,
    # APPROVED package): a repair that would change final media has no path back
    # and must be refused typed — never a silent bypass of the review.
    episode_id, thai, _english, package = world.released_episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    service = world.repairs()
    plan_id = service.plan_from_findings(episode_id).plan.plan_id
    with pytest.raises(InvalidTransition, match="never silently bypassed"):
        service.execute_plan(plan_id)
    # nothing changed: tracks, package and state are exactly as they were
    assert (
        world.row("SELECT state FROM caption_tracks WHERE id = %s", (thai,))["state"] == "CURRENT"
    )
    assert (
        world.row("SELECT status FROM release_packages WHERE id = %s", (package,))["status"]
        == "APPROVED"
    )
    assert (
        world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"]
        == "RELEASE_APPROVED"
    )
    assert world.rows("SELECT * FROM jobs WHERE job_type = 'review.prepare_package'") == []


def test_line_repair_invalidates_only_that_lines_audio_and_requeues_references(
    world: RepairsWorld,
) -> None:
    from microdrama.contracts.examples import script as example_script

    episode_id, _thai, _english, package = world.episode_with_tracks()
    line = next(ln for sc in example_script().scenes for ln in sc.lines if ln.line_id == L1)
    world.line_audio_asset(episode_id, L1, line.text_th)
    world.finding(
        episode_id,
        check_id="asr.speaker_match",
        repair_targets=["LINE"],
        start_ms=10_500,
        end_ms=12_000,
        observed="lek's voice",
        expected="fon's voice",
    )
    dispatch = RecordingShotDispatch()
    service = world.repairs(shot_dispatch=dispatch)
    outcome = service.plan_from_findings(episode_id)
    execution = service.execute_plan(outcome.plan.plan_id)

    assert execution.status == "COMPLETED"
    assert execution.invalidated_asset_ids, "the wrong line's audio asset is invalidated"
    row = world.row(
        "SELECT state FROM assets WHERE id = ANY(%s)",
        ([str(a) for a in execution.invalidated_asset_ids],),
    )
    assert row["state"] == "SUPERSEDED"
    # the re-voicing is a selective stage requeue — not a render dispatch
    assert world.rows("SELECT * FROM jobs WHERE job_type = 'references.prepare_episode'")
    assert dispatch.dispatch_calls == []
    # async plan: the open package is superseded (media is changing) but the
    # episode is NOT teleported to the gate — the requeued stages own the climb.
    assert (
        world.row("SELECT status FROM release_packages WHERE id = %s", (package,))["status"]
        == "SUPERSEDED"
    )
    assert (
        world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == "AI_REVIEW"
    )


def test_partial_repair_fails_its_recheck_and_stays_out_of_gate2(
    world: RepairsWorld,
) -> None:
    # L2's cue is ALSO wrong but the finding window only covers L1: the repair
    # fixes L1 and the final-consistency recheck still fails — no gate return.
    episode_id, _thai, _english, package = world.episode_with_tracks(
        thai_l2_text="ผิดมาก",
        en_l2_text="Wrong text.",
    )
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    service = world.repairs()
    plan_id = service.plan_from_findings(episode_id).plan.plan_id
    with pytest.raises(GateNotReady, match="does NOT return to Gate 2"):
        service.execute_plan(plan_id)

    assert (
        world.row("SELECT status FROM repair_plans WHERE id = %s", (plan_id,))["status"] == "FAILED"
    )
    assert (
        world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == "AI_REVIEW"
    )
    assert (
        world.row("SELECT status FROM release_packages WHERE id = %s", (package,))["status"]
        == "READY"
    )
    # the L1 fix itself did land (per-step effects are real), L2 is still wrong
    new_thai = _current_track(world, episode_id, "th-TH")
    assert next(c for c in new_thai.cues if c.cue_id == f"{L1}.thth").text != "ผิดมาก"
    assert next(c for c in new_thai.cues if c.cue_id == f"{L2}.thth").text == "ผิดมาก"

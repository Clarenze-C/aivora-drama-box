"""Repair output rebuilding and deferred finding resolution (build-review F03).

A caption repair must regenerate the real outputs of the changed cues through
the CaptionRebuildPort before anything resolves or reopens; an unwired port
refuses typed instead of completing with unrebuilt media. Asynchronous repairs
(line/shot/stage) never resolve their findings at dispatch — only a fresh QA
cycle that proves the check passes resolves them, attributed to the plan.
"""

from __future__ import annotations

import pytest
from qa_support import QAWorld
from repairs_support import L1, RecordingCaptionRebuild, RecordingShotDispatch, RepairsWorld

from microdrama.contracts.errors import ProviderError
from microdrama.qa.repairs import RefusingCaptionRebuild

pytestmark = pytest.mark.db


@pytest.fixture
def world(qa_world: QAWorld) -> RepairsWorld:
    return RepairsWorld(qa_world.db, qa_world.store, qa_world.settings, qa_world.truth)


def test_caption_step_rebuilds_outputs_through_the_port(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    rebuild = RecordingCaptionRebuild()
    service = world.repairs(caption_rebuild=rebuild)
    execution = service.execute_plan(service.plan_from_findings(episode_id).plan.plan_id)

    assert execution.status == "COMPLETED"
    assert len(rebuild.calls) == 1, "one rebuild per caption step, never per track"
    assert rebuild.calls[0]["episode_id"] == episode_id
    # exactly the NEW track ids — the port rebuilds what the repair created
    assert rebuild.calls[0]["track_ids"] == execution.new_caption_track_ids


def test_unwired_caption_rebuild_refuses_and_resolves_nothing(world: RepairsWorld) -> None:
    episode_id, *_ = world.episode_with_tracks()
    finding = world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
    )
    service = world.repairs(caption_rebuild=RefusingCaptionRebuild())
    plan_id = service.plan_from_findings(episode_id).plan.plan_id
    with pytest.raises(ProviderError, match="charge is kept|repair step failed"):
        service.execute_plan(plan_id)
    assert world.row("SELECT status FROM repair_plans WHERE id = %s", (plan_id,))["status"] == (
        "FAILED"
    )
    # nothing resolved, no gate return, and the superseded-source truth stands
    assert (
        world.row("SELECT resolution FROM qa_findings WHERE id = %s", (finding,))["resolution"]
        == "OPEN"
    )
    assert world.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "AI_REVIEW"
    )


def test_line_repair_leaves_its_finding_open_until_reproof(world: RepairsWorld) -> None:
    from microdrama.contracts.examples import script as example_script

    episode_id, *_ = world.episode_with_tracks()
    line = next(ln for sc in example_script().scenes for ln in sc.lines if ln.line_id == L1)
    world.line_audio_asset(episode_id, L1, line.text_th)
    finding = world.finding(
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
    execution = service.execute_plan(service.plan_from_findings(episode_id).plan.plan_id)

    assert execution.status == "COMPLETED"
    assert execution.findings_resolved == [], "dispatch resolved nothing — no proof yet"
    assert (
        world.row("SELECT resolution FROM qa_findings WHERE id = %s", (finding,))["resolution"]
        == "OPEN"
    )


def test_resolve_repaired_findings_proves_each_check_on_the_new_cycle(
    world: RepairsWorld,
) -> None:
    episode_id, *_ = world.episode_with_tracks()
    fixed = world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=["CAPTION"],
        start_ms=10_000,
        end_ms=13_000,
        cycle=1,
    )
    still_broken = world.finding(
        episode_id,
        check_id="asr.line_present",
        repair_targets=["LINE"],
        start_ms=10_500,
        end_ms=12_000,
        cycle=1,
    )
    dispatch = RecordingShotDispatch()
    service = world.repairs(shot_dispatch=dispatch)
    plan = service.plan_from_findings(episode_id).plan
    execution = service.execute_plan(plan.plan_id)  # dispatched; nothing resolved yet
    assert execution.findings_resolved == []

    # A fresh QA cycle: the caption check now passes; the ASR check still fails.
    world.finding(
        episode_id,
        check_id="caption.critical_term_match",
        repair_targets=[],
        start_ms=10_000,
        end_ms=13_000,
        cycle=2,
        outcome="PASS",
        severity="MINOR",
        run_key="repairs-test-cycle2",
    )
    world.finding(
        episode_id,
        check_id="asr.line_present",
        repair_targets=["LINE"],
        start_ms=10_500,
        end_ms=12_000,
        cycle=2,
        outcome="REPAIRABLE",
        severity="MAJOR",
        run_key="repairs-test-cycle2",
    )

    resolved = service.resolve_repaired_findings(episode_id, latest_cycle=2)
    assert resolved >= 1
    fixed_row = world.row(
        "SELECT resolution, resolved_by_plan_id FROM qa_findings WHERE id = %s", (fixed,)
    )
    assert fixed_row["resolution"] == "RESOLVED"
    assert fixed_row["resolved_by_plan_id"] == plan.plan_id
    assert (
        world.row("SELECT resolution FROM qa_findings WHERE id = %s", (still_broken,))["resolution"]
        == "OPEN"
    )

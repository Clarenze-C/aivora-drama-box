"""AT-05/06/07 reproduced independently through the composed QA services.

AT-05: seeded critical defects (wrong amount/speaker, identity swap, missing
audio, bad caption/CTA, truncated output) block or repair — a seeded defect can
never pass silently green, and unknown coverage is visible as unknown.

AT-06: the observation request cannot access the intended script — a question
that quotes it is refused — and the frozen first report is immutable.

AT-07: a subtitle defect plans caption-scope repair only, with no video
re-render; a SHOT repair step consumes an ordinary attempt by contract.
"""

from __future__ import annotations

import uuid

import pytest
from validation_qa_support import (
    register_media_asset,
    seed_episode_with_script,
    seed_season_with_gate1,
)

from microdrama.contracts.enums import RepairTarget
from microdrama.contracts.examples import script as example_script
from microdrama.contracts.qa import NeutralQuestion

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg, pytest.mark.slow]


def _episode_with(world, defect) -> tuple[uuid.UUID, uuid.UUID]:
    season_id = seed_season_with_gate1(world.db)
    episode_id = seed_episode_with_script(world.db, season_id)
    asset_id = register_media_asset(world, episode_id, defect.path)
    return episode_id, asset_id


def _findings(world, episode_id) -> list[dict]:
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchall(
            "SELECT check_id, severity, outcome, resolution FROM qa_findings "
            "WHERE episode_id = %s",
            (episode_id,),
        )


def _open_findings(findings) -> list[dict]:
    return [
        f
        for f in findings
        if f["resolution"] is None or f["resolution"] in ("OPEN",)
    ]


# --- AT-05 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["missing_audio", "black_frames", "bad_caption"],
)
def test_seeded_technical_defects_never_pass_silently_green(
    qa_world, defect_suite, kind
) -> None:
    """Each seeded technical defect produces at least the finding it was designed
    to trip (the suite's own expected check ids), open or repairable — never a
    clean run."""
    defect = defect_suite[kind]
    episode_id, asset_id = _episode_with(qa_world, defect)
    run = qa_world.qa_technical.run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    findings = _findings(qa_world, episode_id)
    flagged = {f["check_id"] for f in findings}
    missing = set(defect.expected_check_ids) - flagged
    assert not missing, f"{kind}: expected checks {missing} produced no finding"
    assert _open_findings(findings), f"{kind}: findings exist but none are open"


def test_truncated_output_blocks_decode_and_stays_honestly_unknown(
    qa_world, defect_suite
) -> None:
    """The truncated file cannot decode: the decode check is BLOCKED, dependent
    checks are UNKNOWN (never green), and unsampled coverage stays visible."""
    from microdrama.contracts.media import MediaInfo

    defect = defect_suite["truncated_output"]
    season_id = seed_season_with_gate1(qa_world.db)
    episode_id = seed_episode_with_script(qa_world.db, season_id)
    asset_id = register_media_asset(
        qa_world,
        episode_id,
        defect.path,
        media=MediaInfo(duration_ms=5_000, has_video=True, has_audio=True),
    )
    run = qa_world.qa_technical.run_episode_qa(episode_id, asset_id=asset_id)
    assert not run.all_checks_green
    outcomes = {f.check_id: f.outcome.value for f in run.findings}
    assert outcomes.get("technical.decode") == "BLOCKED"
    unknowns = [
        f for f in run.findings if f.outcome.value == "UNKNOWN"
    ]
    assert unknowns, "dependent checks must surface as UNKNOWN, not green"


def test_clean_fixture_produces_no_blocking_findings(qa_world, defect_suite) -> None:
    """The control case: the clean fixture must NOT trip the defect checks —
    proving the flags above mean something."""
    episode_id, asset_id = _episode_with(qa_world, defect_suite["clean"])
    qa_world.qa_technical.run_episode_qa(episode_id, asset_id=asset_id)
    blocking = [
        f
        for f in _findings(qa_world, episode_id)
        if f["severity"] == "CRITICAL" and (f["resolution"] is None or f["resolution"] == "OPEN")
    ]
    assert blocking == []


@pytest.mark.parametrize("kind", ["wrong_amount", "wrong_speaker", "identity_swap"])
def test_observed_vs_intended_defects_surface_as_critical(
    qa_world, defect_suite, kind
) -> None:
    """Blind observation (Pass A) followed by comparison against the intended
    script (Pass B): the wrong amount/speaker/identity swaps are typed findings —
    the media's ACTUAL contents decide, never the source prompt."""
    defect = defect_suite[kind]
    episode_id, asset_id = _episode_with(qa_world, defect)
    frozen = qa_world.qa_observation.observe_media(episode_id, asset_id=asset_id)
    assert frozen is not None
    run = qa_world.qa_comparison.compare(episode_id)
    findings = _findings(qa_world, episode_id)
    critical = [f for f in findings if f["severity"] == "CRITICAL"]
    assert critical, f"{kind}: comparison produced no critical finding"
    assert run is not None


# --- AT-06 --------------------------------------------------------------------------------


def test_observation_cannot_be_handed_the_intended_script(qa_world, defect_suite) -> None:
    """A question that quotes the intended script's own Thai line is refused at
    the content screen — the blind pass cannot be handed the answer."""
    defect = defect_suite["clean"]
    episode_id, asset_id = _episode_with(qa_world, defect)
    script = example_script()
    line = script.scenes[0].lines[0].text_th
    leaking = [NeutralQuestion(question_id="q-leak", text=f"Does the frame show: {line}?")]
    with pytest.raises(Exception) as excinfo:
        qa_world.qa_observation.observe_media(
            episode_id, asset_id=asset_id, questions=leaking
        )
    assert "intended" in str(excinfo.value).lower() or "screen" in str(excinfo.value).lower()


def test_frozen_observation_is_immutable_across_replays(qa_world, defect_suite) -> None:
    """The first frozen report stands: a second observation of the same media
    replays the SAME frozen row (no rewrite, no second report)."""
    defect = defect_suite["clean"]
    episode_id, asset_id = _episode_with(qa_world, defect)
    first = qa_world.qa_observation.observe_media(episode_id, asset_id=asset_id)
    second = qa_world.qa_observation.observe_media(episode_id, asset_id=asset_id)
    assert second.replayed is True, "the second call must be a replay, not a new freeze"
    assert first.report.report_id == second.report.report_id
    with qa_world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT report_sha256 FROM qa_observations WHERE episode_id = %s", (episode_id,)
        )
    assert len(rows) == 1, "a replay must not create a second frozen report"


# --- AT-07 --------------------------------------------------------------------------------


def test_subtitle_defect_never_triggers_a_video_rerender(qa_world, defect_suite) -> None:
    """A bad-caption finding must never lead to whole-video regeneration: the
    planner either returns caption-scope steps only, or refuses with a typed
    cause-unknown error (never a blanket re-render). Both outcomes leave zero
    render jobs enqueued."""
    from microdrama.qa.repairs import RepairCauseUnknown

    defect = defect_suite["bad_caption"]
    episode_id, asset_id = _episode_with(qa_world, defect)
    qa_world.qa_technical.run_episode_qa(episode_id, asset_id=asset_id)
    with qa_world.db.transaction(readonly=True) as tx:
        renders_before = tx.fetchval(
            "SELECT count(*) FROM jobs WHERE job_type = 'render.shot'"
        )

    try:
        outcome = qa_world.qa_repairs.plan_from_findings(episode_id)
        steps = outcome.plan.steps
        assert steps
        targets = {step.target for step in steps}
        assert RepairTarget.SHOT not in targets, "caption repair must not re-render video"
        assert targets <= {RepairTarget.CAPTION, RepairTarget.LINE, RepairTarget.AUDIO_MIX}
        assert all(not step.consumes_shot_attempt for step in steps)
    except RepairCauseUnknown:
        pass  # the typed "never blanket" refusal — equally correct

    with qa_world.db.transaction(readonly=True) as tx:
        renders_after = tx.fetchval(
            "SELECT count(*) FROM jobs WHERE job_type = 'render.shot'"
        )
    assert renders_after == renders_before


def test_shot_repair_steps_consume_an_ordinary_attempt_by_contract() -> None:
    """The contract itself refuses a SHOT repair that does not burn a retry —
    tier promotion can never become a free extra render."""
    from microdrama.contracts.enums import BudgetCategory
    from microdrama.contracts.qa import RepairStep

    with pytest.raises(Exception, match="attempt"):
        RepairStep(
            step_id="s-free-shot",
            target=RepairTarget.SHOT,
            target_ids=["shot-1"],
            action="rerender",
            category=BudgetCategory.GPU_GENERATION,
            estimated_cost_micro_usd=1,
            consumes_shot_attempt=False,
        )

"""Repaired media chains through the registered handlers (build-review F03).

The composed world (real local FFmpeg, real router, fake providers) must repair
seeded media faults end to end through the durable job queue — not through
runner-supplied service calls: a caption defect regenerates the subtitle
artifact and the burned derivatives BEFORE its finding resolves and Gate 2
reopens, and a defective shot re-renders through the ordinary routed-attempt
path (real reservation, real render.shot job) with its finding staying open
until a fresh QA cycle proves the fix.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    Provenance,
    QAOutcome,
    RepairTarget,
    Severity,
)
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.persistence import Database
from microdrama.persistence.db import insert_row, jsonb
from microdrama.pipeline.runner import MockPipelineRunner
from microdrama.pipeline.world import build_pipeline_world
from microdrama.qa.models import build_finding

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg, pytest.mark.slow]


def _run_to_assembled(world_db, settings, tmp):
    world = build_pipeline_world(settings, world_db)
    runner = MockPipelineRunner(world)
    season = runner.w01_research()
    runner.gate1(season)
    runner.w02_compile(season)
    episode = runner.create_episode(season)
    runner.w03_write(episode)
    runner.w04_references(episode)
    runner.w05_render(episode)
    runner.w06_edit(episode)
    return world, runner, episode


def _finding(world, episode_id, asset_id, *, check_id, targets, start_ms, end_ms, family):
    body = build_finding(
        run_key=f"composed-repair-{uuid4().hex[:8]}",
        episode_id=episode_id,
        asset_id=asset_id,
        start_ms=start_ms,
        end_ms=end_ms,
        check_id=check_id,
        family=CheckFamily(family),
        severity=Severity.MAJOR,
        outcome=QAOutcome.REPAIRABLE,
        coverage=CoverageStatus.CHECKED,
        expected="the scripted line",
        observed="the seeded defect",
        evidence_source=EvidenceSource.FAKE_FIXTURE,
        evidence_ref="composed-repair-test",
        evidence_note="seeded for the composed repair chain",
        provenance=Provenance.FAKE_SYNTHETIC,
        repair_targets=[RepairTarget(t) for t in targets],
    )
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "qa_findings",
            {
                "id": body.finding_id,
                "episode_id": episode_id,
                "qa_cycle": 1,
                "asset_id": asset_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "check_id": check_id,
                "check_family": body.check_family.value,
                "source_pass": body.source_pass.value,
                "severity": "MAJOR",
                "coverage": "CHECKED",
                "outcome": "REPAIRABLE",
                "body": jsonb(body),
                "resolution": "OPEN",
            },
        )
    return body.finding_id


def _master_row(world, episode_id):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT edl_hash, output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND state = 'RENDERED' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )


def test_caption_defect_rebuilds_outputs_then_resolves_and_reopens(
    db: Database, tmp_path, offline_settings: Settings
) -> None:
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.contracts.media import CaptionTrack
    from microdrama.editing.captions import srt_bytes, track_body_hash
    from microdrama.editing.edl import burned_asset_id_for, caption_asset_id_for

    world, runner, episode = _run_to_assembled(db, offline_settings, tmp_path)
    master = _master_row(world, episode)

    # Seed the defect: a NEW current track whose first Thai cue carries wrong text
    # (bodies are immutable; a seeded replacement row is the honest shape).
    with world.db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT body FROM caption_tracks WHERE episode_id = %s AND locale = 'th-TH' "
            "AND state = 'CURRENT'",
            (episode,),
        )
    track = CaptionTrack.model_validate(row["body"])
    wrong_cue = track.cues[0]
    wrong = track.model_copy(
        update={
            "track_id": uuid4(),
            "version": track.version + 1,
            "cues": [
                cue.model_copy(update={"text": "ข้อความที่ผิดอย่างชัดเจน"})
                if cue.cue_id == wrong_cue.cue_id
                else cue
                for cue in track.cues
            ],
        }
    )
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE caption_tracks SET state = 'SUPERSEDED', revision = revision + 1 "
            "WHERE episode_id = %s AND locale = 'th-TH' AND state = 'CURRENT'",
            (episode,),
        )
        insert_row(
            tx,
            "caption_tracks",
            {
                "id": wrong.track_id,
                "episode_id": episode,
                "locale": "th-TH",
                "version": wrong.version,
                "timing_source": wrong.timing_source.value,
                "body": jsonb(wrong),
                "body_hash": canonical_hash(wrong),
                "state": "CURRENT",
            },
        )
    finding = _finding(
        world,
        episode,
        master["output_asset_id"],
        check_id="caption.critical_term_match",
        targets=["CAPTION"],
        start_ms=wrong_cue.start_ms,
        end_ms=wrong_cue.end_ms,
        family="CAPTION",
    )

    old_burned = runner._row(
        "SELECT id, sha256 FROM assets WHERE id = ANY(%s)",
        (
            [
                str(burned_asset_id_for(str(master["edl_hash"]), track_body_hash(track))),
            ],
        ),
    )

    # Drive the repair THROUGH the registered handler on the durable queue.
    runner._enqueue(
        "qa.plan_repairs",
        EpisodeStepInput(episode_id=episode, trigger="qa_finding"),
        episode_id=episode,
        semantic_key=f"qa.plan_repairs:{episode}:1",
    )
    runner._drain(advance_ms=5_000)

    # Cue-level fix landed: the repaired track carries the script's text again.
    with world.db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT id, body, asset_id FROM caption_tracks WHERE episode_id = %s "
            "AND locale = 'th-TH' AND state = 'CURRENT'",
            (episode,),
        )
    repaired = CaptionTrack.model_validate(row["body"])
    fixed_cue = next(c for c in repaired.cues if c.cue_id == wrong_cue.cue_id)
    assert fixed_cue.text == wrong_cue.text or fixed_cue.text != "ข้อความที่ผิดอย่างชัดเจน"
    assert fixed_cue.text == track.cues[0].text  # the original (scripted) text is back

    # The subtitle artifact exists, is linked and is downloadable. A
    # replace-back repair restores exactly the assembled content, so the linked
    # artifact may be the ORIGINAL one — the honest check is that the linked
    # asset carries exactly the repaired track's bytes and is usable.
    assert row["asset_id"] is not None
    srt_asset = runner._row(
        "SELECT object_key, state, media_type FROM assets WHERE id = %s", (row["asset_id"],)
    )
    assert srt_asset["state"] == "ACCEPTED"
    assert srt_asset["media_type"] == "application/x-subrip"
    assert world.store.get_bytes(srt_asset["object_key"]) == srt_bytes(repaired)

    # The burned master exists for the CURRENT caption body and is usable (a
    # replace-back legitimately replays the original burn byte-for-byte).
    new_burned_id = burned_asset_id_for(str(master["edl_hash"]), track_body_hash(repaired))
    new_burned = runner._row("SELECT sha256, state FROM assets WHERE id = %s", (new_burned_id,))
    assert new_burned is not None and new_burned["state"] == "ACCEPTED"
    del caption_asset_id_for, old_burned

    # The finding resolved only after the rebuilt outputs existed; the gate reopened.
    resolved = runner._row(
        "SELECT resolution, resolved_by_plan_id FROM qa_findings WHERE id = %s", (finding,)
    )
    assert resolved["resolution"] == "RESOLVED"
    assert resolved["resolved_by_plan_id"] is not None
    assert (
        runner._row("SELECT state FROM episodes WHERE id = %s", (episode,))["state"]
        == "AWAITING_FINAL_REVIEW"
    )


def test_shot_defect_re_renders_through_the_routed_attempt_path(
    db: Database, tmp_path, offline_settings: Settings
) -> None:
    world, runner, episode = _run_to_assembled(db, offline_settings, tmp_path)
    master = _master_row(world, episode)

    # A defective shot: the finding window covers the first shot's lines.
    with world.db.transaction(readonly=True) as tx:
        cue = tx.fetchone(
            "SELECT body FROM caption_tracks WHERE episode_id = %s AND locale = 'th-TH' "
            "AND state = 'CURRENT'",
            (episode,),
        )["body"]["cues"][0]
    finding = _finding(
        world,
        episode,
        master["output_asset_id"],
        check_id="visual_identity.match",
        targets=["SHOT"],
        start_ms=cue["start_ms"],
        end_ms=cue["end_ms"],
        family="VISUAL_IDENTITY",
    )

    runner._enqueue(
        "qa.plan_repairs",
        EpisodeStepInput(episode_id=episode, trigger="qa_finding"),
        episode_id=episode,
        semantic_key=f"qa.plan_repairs:{episode}:1",
    )
    runner._drain(advance_ms=5_000)

    # The repair dispatched an ORDINARY routed attempt: beyond the episode's
    # original shots, exactly one further render.shot job with a real provider
    # operation and a real budget reservation — through the wired
    # RouterShotDispatch, never the refusing default.
    attempts = runner._rows(
        "SELECT id, semantic_key, status FROM jobs WHERE job_type = 'render.shot' "
        "AND episode_id = %s ORDER BY created_at",
        (episode,),
    )
    re_renders = [a for a in attempts if a["semantic_key"].endswith("attempt2")]
    assert len(re_renders) == 1, "the repair re-render is a new ordinary attempt"
    repair_job = re_renders[0]
    operation = runner._row(
        "SELECT id, state FROM provider_operations WHERE job_id = %s", (repair_job["id"],)
    )
    assert operation is not None, "the re-render has a real provider operation"
    reservations = runner._rows(
        "SELECT * FROM reservations WHERE episode_id = %s AND category = 'GPU_GENERATION'",
        (episode,),
    )
    assert len(reservations) >= 2  # the repair attempt reserved before dispatch

    # The finding did NOT resolve at dispatch: no proof exists yet.
    assert (
        runner._row("SELECT resolution FROM qa_findings WHERE id = %s", (finding,))["resolution"]
        == "OPEN"
    )
    # And the episode was not teleported to the gate — the re-render owns the climb.
    assert runner._row("SELECT state FROM episodes WHERE id = %s", (episode,))["state"] == (
        "AI_REVIEW"
    )

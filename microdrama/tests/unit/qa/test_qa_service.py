"""Service-level QA runs over the T007 seeded-defect suite (T017).

The acceptance core: every seeded critical defect is flagged with its expected check
id (or is explicitly UNKNOWN) and breaks the green summary, while the clean fixture
is green — and none of that depends on the script side being wrong: the script is the
PRISTINE examples script in every run here; only the media differs.
"""

from __future__ import annotations

import uuid

import pytest
from qa_support import QAWorld

from microdrama.contracts.enums import QAOutcome
from microdrama.contracts.errors import NotFound, SchemaInvalid
from microdrama.contracts.media import MediaInfo
from microdrama.qa import QARunStatus

# (defect kind, expected check id) — the T007 seeded suite's own expectations.
DEFECT_EXPECTATIONS = [
    ("wrong_amount", "asr.critical_term_match"),
    ("wrong_speaker", "asr.speaker_match"),
    ("identity_swap", "visual_identity.match"),
    ("missing_audio", "technical.audio_present"),
    ("silence_gap", "asr.line_present"),
    ("black_frames", "temporal.black_frames"),
    ("frozen_frames", "temporal.frozen_frames"),
    ("bad_caption", "caption.critical_term_match"),
    ("wrong_cta", "caption.release_claim"),
    ("truncated_output", "technical.decode"),
]

_BAD = (QAOutcome.REPAIRABLE, QAOutcome.BLOCKED, QAOutcome.UNKNOWN)


def _truncated_media() -> MediaInfo:
    # The truncated fixture does not probe; register the declared facts instead.
    return MediaInfo(
        duration_ms=5_000, has_video=True, has_audio=True, width=360, height=640,
        fps_num=24, fps_den=1, sample_rate_hz=48_000, channels=1,
    )  # fmt: skip


def _run(world: QAWorld, defect_suite, kind: str):
    fixture = defect_suite[kind]
    episode_id, asset_id = world.seeded_episode_with(
        fixture=fixture,
        media_info=_truncated_media() if kind == "truncated_output" else None,
    )
    run = world.service().run_episode_qa(episode_id, asset_id=asset_id)
    return run


def test_clean_fixture_is_all_green(defect_suite, qa_world: QAWorld) -> None:
    run = _run(qa_world, defect_suite, "clean")
    assert run.status is QARunStatus.COMPLETED
    assert run.all_checks_green, [
        (f.check_id, f.outcome, f.coverage) for f in run.findings if f.blocks_release
    ] + [f.check_id for f in run.findings if f.outcome is QAOutcome.UNKNOWN]
    assert run.blocking_check_ids == []
    # the always-unknown detectors stay visible even on a green run
    assert "temporal.lip_sync" in run.unknown_check_ids
    assert "visual_identity.prop_match" in run.unknown_check_ids


@pytest.mark.parametrize(("kind", "expected_check"), DEFECT_EXPECTATIONS)
def test_seeded_defect_breaks_green_and_fires_expected_check(
    defect_suite, qa_world: QAWorld, kind: str, expected_check: str
) -> None:
    run = _run(qa_world, defect_suite, kind)
    fired = [f for f in run.findings if f.check_id == expected_check]
    assert fired, f"{kind}: expected a {expected_check} finding"
    assert any(f.outcome in _BAD for f in fired), (
        f"{kind}: {expected_check} must be flagged or UNKNOWN, never silently green"
    )
    assert not run.all_checks_green, f"{kind}: a seeded defect must break the green summary"
    # CRITICAL defects block; MAJOR-but-repairable defects (e.g. black frames) break
    # the configured-critical green summary instead — either way QA is not green.
    assert (
        expected_check in run.blocking_check_ids
        or any(f.outcome is QAOutcome.UNKNOWN for f in fired)
        or not run.all_checks_green
    )


def test_clean_and_defect_runs_on_one_episode_use_separate_cycles(
    defect_suite, qa_world: QAWorld
) -> None:
    fixture = defect_suite["clean"]
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=fixture)
    first = qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)
    defect = defect_suite["black_frames"]
    defect_asset = qa_world.register_media(episode_id, data=defect.path.read_bytes())
    second = qa_world.service().run_episode_qa(episode_id, asset_id=defect_asset)
    assert first.qa_cycle == 1
    assert second.qa_cycle == 2
    assert qa_world.row(
        "SELECT COUNT(*) AS n FROM qa_findings WHERE episode_id = %s", (episode_id,)
    )["n"] == len(first.findings) + len(second.findings)


def test_findings_and_coverage_persist_as_rows_and_event(defect_suite, qa_world: QAWorld) -> None:
    run = _run(qa_world, defect_suite, "clean")
    rows = qa_world.findings_rows(run.episode_id)
    assert len(rows) == len(run.findings)
    assert all(row["resolution"] == "OPEN" for row in rows)
    assert {row["check_id"] for row in rows} == {f.check_id for f in run.findings}
    events = qa_world.run_events(run.episode_id)
    assert len(events) == 1
    payload = events[0]
    assert payload["run_key"] == run.run_key
    assert payload["all_checks_green"] is True
    assert payload["qa_cycle"] == run.qa_cycle
    coverage = payload["coverage"]
    assert coverage["TECHNICAL"]["windows"] == [[0, 5_000, "CHECKED"]]
    assert coverage["ASR"]["checked_ms"] == 5_000
    assert coverage["CAPTION"]["window_count"] >= 1


def test_identical_rerun_replays_without_new_rows_or_charges(
    defect_suite, qa_world: QAWorld
) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = qa_world.service()
    first = service.run_episode_qa(episode_id, asset_id=asset_id)
    second = service.run_episode_qa(episode_id, asset_id=asset_id)
    assert second.status is QARunStatus.REPLAYED
    assert second.qa_cycle == first.qa_cycle
    assert sorted(f.finding_id for f in second.findings) == sorted(
        f.finding_id for f in first.findings
    )
    assert len(qa_world.findings_rows(episode_id)) == len(first.findings)
    assert len(qa_world.run_events(episode_id)) == 1
    assert second.settled_micro_usd == 0


def test_media_change_produces_new_findings_not_a_replay(defect_suite, qa_world: QAWorld) -> None:
    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    service = qa_world.service()
    first = service.run_episode_qa(episode_id, asset_id=asset_id)
    defect_asset = qa_world.register_media(
        episode_id, data=defect_suite["wrong_amount"].path.read_bytes()
    )
    second = service.run_episode_qa(episode_id, asset_id=defect_asset)
    assert second.status is QARunStatus.COMPLETED
    assert second.run_key != first.run_key
    assert second.qa_cycle == first.qa_cycle + 1


def test_qa_report_view_lists_blocking_and_unknowns(defect_suite, qa_world: QAWorld) -> None:
    run = _run(qa_world, defect_suite, "wrong_amount")
    view = qa_world.service().qa_report(run.episode_id)
    assert view.episode_id == run.episode_id
    assert view.cycles == [run.qa_cycle]
    assert sorted(f.finding_id for f in view.findings) == sorted(f.finding_id for f in run.findings)
    assert not view.all_checks_green
    assert "asr.critical_term_match" in view.blocking_check_ids
    assert "temporal.lip_sync" in view.unknown_check_ids


def test_cpu_ceiling_refuses_before_any_work(defect_suite, qa_world: QAWorld) -> None:
    from microdrama.qa import QAConfig

    episode_id, asset_id = qa_world.seeded_episode_with(fixture=defect_suite["clean"])
    config = QAConfig(max_media_duration_ms=2_000)
    with pytest.raises(SchemaInvalid, match="ceiling"):
        qa_world.service(config).run_episode_qa(episode_id, asset_id=asset_id)
    assert qa_world.findings_rows(episode_id) == []
    assert qa_world.run_events(episode_id) == []


def test_missing_episode_or_script_is_typed(defect_suite, qa_world: QAWorld) -> None:
    season_id = qa_world.season()
    episode_id = qa_world.episode(season_id)
    with pytest.raises(NotFound, match="script"):
        qa_world.service().run_episode_qa(episode_id, asset_id=uuid.uuid4())


def test_non_video_asset_is_refused(defect_suite, qa_world: QAWorld) -> None:
    from microdrama.contracts.enums import AssetKind, AssetState, Provenance
    from microdrama.contracts.media import AssetDescriptor
    from microdrama.persistence import register_asset
    from microdrama.testing.media import make_png_bytes

    episode_id = qa_world.episode()
    qa_world.seed_script(episode_id)
    stored = qa_world.store.put_bytes(
        "qa/cover.png", make_png_bytes(64, 64), media_type="image/png"
    )
    with qa_world.db.transaction() as tx:
        register_asset(
            tx,
            AssetDescriptor(
                asset_id=uuid.uuid4(),
                asset_kind=AssetKind.IMAGE,
                object_key=stored.key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="image/png",
                media=None,
                state=AssetState.ACCEPTED,
                provenance=Provenance.ORIGINAL_FIXTURE,
                episode_id=episode_id,
                season_id=qa_world.row(
                    "SELECT season_id FROM episodes WHERE id = %s", (episode_id,)
                )["season_id"],
                created_at=qa_world.clock.now(),
            ),
        )
        asset_id = tx.fetchone("SELECT id FROM assets WHERE object_key = %s", (stored.key,))["id"]
    with pytest.raises(SchemaInvalid, match="video"):
        qa_world.service().run_episode_qa(episode_id, asset_id=asset_id)

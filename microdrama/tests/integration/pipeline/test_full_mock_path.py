"""The complete two-gate mock path, end to end (T029 acceptance).

One test owns the whole story — the same sequence the demo command runs —
because the acceptance is about the WHOLE path behaving: exactly two human
decisions, real playable FFmpeg exports, fake-labeled posts, budget ledger
sane, GPU gone before the human wait, identity lock on episode one, no orphan
work after the janitors. Real PostgreSQL, real FFmpeg, T007 fake providers,
offline network guard active (autouse from tests/conftest.py).
"""

from __future__ import annotations

import pytest

from microdrama.config import Settings
from microdrama.persistence import Database
from microdrama.pipeline.runner import MockPipelineRunner
from microdrama.pipeline.world import build_pipeline_world
from microdrama.testing.media import probe

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg, pytest.mark.slow]


def test_full_mock_path_from_proposal_to_managed_fake_post(
    db: Database, tmp_path, offline_settings: Settings
) -> None:
    world = build_pipeline_world(offline_settings, db)
    runner = MockPipelineRunner(world)
    report = runner.run()

    # --- the whole W01–W12 sequence ran, with exactly two human gates -----------------
    stages = [stage.stage for stage in report.stages]
    assert stages == [
        "research",
        "season_approval",
        "compile_season",
        "write_episode",
        "prepare_references",
        "render_shots",
        "assemble_and_variants",
        "qa",
        "gate2_approval",
        "publish",
        "community_and_membership",
        "analytics",
        "janitors",
    ]
    assert report.human_decisions == 2, "exactly Gate 1 and Gate 2 — no third human gate"
    assert report.gate1_approval_id is not None
    assert report.gate2_approval_id is not None

    # --- episode one: identity lock created BY the Gate 2 approval ---------------------
    assert report.identity_lock_id is not None
    lock = _row(
        world,
        "SELECT approval_event_id FROM identity_locks WHERE id = %s",
        (report.identity_lock_id,),
    )
    assert str(lock["approval_event_id"]) == str(report.gate2_approval_id)
    episode = _row(world, "SELECT state FROM episodes WHERE id = %s", (report.episode_id,))
    assert episode["state"] == "PUBLISHED_VERIFIED"

    # --- real playable exports ----------------------------------------------------------
    exports = _rows(
        world,
        "SELECT object_key FROM assets WHERE episode_id = %s "
        "AND object_key LIKE 'edits/%%' ORDER BY object_key",
        (report.episode_id,),
    )
    assert exports, "no edited exports were produced"
    master_key = _row(
        world, "SELECT object_key FROM assets WHERE id = %s", (report.master_asset_id,)
    )["object_key"]
    staged = tmp_path / "master.mp4"
    staged.write_bytes(world.store.get_bytes(master_key))
    info = probe(staged)
    assert info.has_video and info.has_audio and info.duration_ms > 0

    # --- fake posts, visibly fake, verified through the fake adapters --------------------
    assert report.platform_post_ids, "no platform post reached PUBLISHED_VERIFIED"
    posts = _rows(
        world,
        "SELECT url FROM platform_posts WHERE id = ANY(%s)",
        ([str(p) for p in report.platform_post_ids],),
    )
    assert len(posts) == len(report.platform_post_ids)
    for post in posts:
        assert ".fake.invalid" in post["url"], f"post url not visibly fake: {post['url']}"

    # --- budget: settled under the cap, nothing left held ---------------------------------
    cost = world.budget.cost_view(report.episode_id)
    assert cost.summary.settled_micro_usd > 0, "fake providers must still price their work"
    assert cost.summary.settled_micro_usd <= cost.summary.episode_cap_micro_usd
    assert cost.summary.reserved_outstanding_micro_usd == 0

    # --- GPU off and queues drained after the janitors -------------------------------------
    assert (
        _count(
            world,
            "SELECT count(*) AS c FROM pod_leases WHERE owner_episode_id = %s "
            "AND lease_state IN ('CLAIMED','ACTIVE','TRANSFERRING')",
            (report.episode_id,),
        )
        == 0
    )
    assert (
        _count(
            world,
            "SELECT count(*) AS c FROM jobs WHERE status IN "
            "('QUEUED','RUNNING','WAITING_EXTERNAL','NEEDS_RECONCILIATION')",
        )
        == 0
    )
    janitors = next(stage for stage in report.stages if stage.stage == "janitors")
    assert janitors.status == "OK"

    # --- the run report is honestly labeled offline ------------------------------------------
    payload = report.as_dict()
    assert payload["mock_run"] is True
    assert payload["execution_mode"] == "OFFLINE_MOCK"
    assert all(stage["mock"] for stage in payload["stages"])


# --- helpers ---------------------------------------------------------------------------


def _row(world, sql, params=()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchone(sql, params)


def _rows(world, sql, params=()):
    with world.db.transaction(readonly=True) as tx:
        return tx.fetchall(sql, params)


def _count(world, sql, params=()) -> int:
    return _row(world, sql, params)["c"]

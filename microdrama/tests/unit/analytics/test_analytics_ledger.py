"""Hook/source/cohort/denominator ledger: explicit missing, honest denominators (T027)."""

from __future__ import annotations

import uuid

from analytics_support import AnalyticsWorld

from microdrama.analytics import NON_CAUSAL_DISCLAIMER
from microdrama.contracts.enums import Platform, SnapshotWindow
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import HookAssignment, HookCandidate, HookExperiment
from microdrama.persistence.db import insert_row


def _hook_world(world: AnalyticsWorld):
    """One published episode whose post carries a three-candidate hook experiment."""
    season = world.season()
    episode, post = world.published_episode(season, number=2)
    experiment_id = uuid.uuid4()
    candidates = [
        HookCandidate(
            candidate_id=f"hook-{i}",
            edl_id=uuid.uuid4(),
            duration_ms=30_000,
            source_asset_ids=[post["asset_id"]],
            treatment=f"treatment {i}",
            changed_framing=False,
            reading_load_note="light",
        )
        for i in (1, 2, 3)
    ]
    experiment = HookExperiment(
        experiment_id=experiment_id,
        episode_id=episode,
        candidates=candidates,
        assignments=[
            HookAssignment(
                candidate_id=c.candidate_id,
                platform=Platform(post["platform"]),
                account_ref=post["account_ref"],
                release_slot="hook",
                cohort=f"cohort-{i}",
                scheduled_utc=post["scheduled_utc"],
            )
            for i, c in enumerate(candidates, start=1)
        ],
    )
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "hook_experiments",
            {
                "id": experiment_id,
                "episode_id": episode,
                "body": experiment,
                "body_hash": canonical_hash(experiment),
            },
        )
        for assignment in experiment.assignments:
            insert_row(
                tx,
                "hook_exposures",
                {
                    "id": uuid.uuid4(),
                    "experiment_id": experiment_id,
                    "candidate_id": assignment.candidate_id,
                    "platform": assignment.platform.value,
                    "account_ref": assignment.account_ref,
                    "release_slot": assignment.release_slot,
                    "cohort": assignment.cohort,
                    "scheduled_utc": assignment.scheduled_utc,
                    "duration_ms": 30_000,
                    "traffic": "ORGANIC",
                    "platform_post_id": post["id"],
                },
            )
    return season, episode, post, experiment_id


class TestHookLedger:
    def test_cohort_rows_carry_metrics_and_exposures(self, world):
        _season, episode, post, _experiment = _hook_world(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(120, denominator=1_000)},
                traffic="ORGANIC",
            )
        )
        rows = world.analytics.hook_ledger(episode)
        assert len(rows) == 3  # one row per candidate/cohort
        for row in rows:
            assert row.exposures == 1
            assert row.platform == post["platform"]
            assert row.missing == ()
            (point,) = row.metrics
            assert point.value == 120
            assert point.denominator == 1_000  # denominators travel with values

    def test_missing_snapshot_is_explicit_missing_not_zero(self, world):
        _season, episode, _post, _experiment = _hook_world(world)
        rows = world.analytics.hook_ledger(episode)
        for row in rows:
            assert row.metrics == ()
            assert row.snapshots_present == 0
            assert row.missing == ()  # nothing recorded: no metric claims at all

    def test_metric_present_but_value_missing_is_listed_missing(self, world):
        _season, episode, post, _experiment = _hook_world(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(None)},  # platform omitted the number
            )
        )
        rows = world.analytics.hook_ledger(episode)
        for row in rows:
            assert row.metrics == ()
            assert "H24:views" in row.missing


class TestDisclaimers:
    def test_disclaimer_text_is_fixed_and_present(self, world):
        assert "not" in NON_CAUSAL_DISCLAIMER
        assert "causal" in NON_CAUSAL_DISCLAIMER

"""Snapshot schedule truth: boundaries, replay, divergence, null honesty (T027)."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import timedelta

import pytest
from analytics_support import AnalyticsWorld

from microdrama.contracts.enums import SnapshotWindow
from microdrama.contracts.errors import Conflict, NotFound, PolicyDenied


def _published_post(world: AnalyticsWorld):
    season = world.season()
    return world.published_episode(season, number=2)


class TestRecordSnapshots:
    def test_recorded_snapshot_is_readable_with_provenance(self, world):
        _season, post = _published_post(world)
        snapshot = world.snapshot(
            post,
            window=SnapshotWindow.H24,
            observed_at_hours=25,
            metrics={"views": world.metric(1_234)},
            traffic="ORGANIC",
        )
        snapshot_id = world.analytics.record_snapshot(snapshot)
        row = world.analytics.snapshot_row(post["id"], SnapshotWindow.H24)
        assert row is not None and row["id"] == snapshot_id
        assert row["definitions_version"] == "fake-metrics-v1"
        assert row["provenance"] == "FAKE_SYNTHETIC"
        assert row["metrics"]["views"]["value"] == 1_234
        assert row["traffic"] == "ORGANIC"

    def test_identical_replay_is_idempotent(self, world):
        _season, post = _published_post(world)
        snapshot = world.snapshot(
            post,
            window=SnapshotWindow.H24,
            observed_at_hours=25,
            metrics={"views": world.metric(10)},
        )
        first = world.analytics.record_snapshot(snapshot)
        second = world.analytics.record_snapshot(snapshot)
        assert first == second
        assert world.row("SELECT count(*) AS n FROM performance_snapshots")["n"] == 1

    def test_divergent_rerecord_is_conflict_table_stays_append_only(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(10)},
            )
        )
        with pytest.raises(Conflict):
            world.analytics.record_snapshot(
                world.snapshot(
                    post,
                    window=SnapshotWindow.H24,
                    observed_at_hours=26,
                    metrics={"views": world.metric(11)},
                )
            )

    def test_missing_metric_stays_null_never_zero(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(500), "watch_time": world.metric(None)},
            )
        )
        row = world.analytics.snapshot_row(post["id"], SnapshotWindow.H24)
        assert row["metrics"]["watch_time"]["value"] is None
        assert row["metrics"]["views"]["value"] == 500


class TestWindowBoundaries:
    @pytest.mark.parametrize(
        ("window", "hours", "refused"),
        [
            (SnapshotWindow.H24, 23, True),
            (SnapshotWindow.H24, 24, False),
            (SnapshotWindow.H72, 71, True),
            (SnapshotWindow.H72, 72, False),
            (SnapshotWindow.D7, 24 * 7 - 1, True),
            (SnapshotWindow.D7, 24 * 7, False),
        ],
    )
    def test_boundary_gate(self, world, window, hours, refused):
        _season, post = _published_post(world)
        snapshot = world.snapshot(
            post, window=window, observed_at_hours=hours, metrics={"views": world.metric(1)}
        )
        if refused:
            with pytest.raises(PolicyDenied):
                world.analytics.record_snapshot(snapshot)
        else:
            world.analytics.record_snapshot(snapshot)  # exactly at the boundary is on time

    def test_observed_early_but_submitted_late_is_still_refused(self, world):
        _season, post = _published_post(world)
        snapshot = world.snapshot(
            post,
            window=SnapshotWindow.H24,
            observed_at_hours=23,
            metrics={"views": world.metric(1)},
        )
        late = post["verified_at"] + timedelta(hours=30)
        with pytest.raises(PolicyDenied):
            world.analytics.record_snapshot(snapshot, now=late)

    def test_unknown_post_has_no_windows(self, world):
        with pytest.raises(NotFound):
            world.analytics.due_windows(uuid_mod.uuid4())


class TestDueWindows:
    def test_due_windows_lists_boundaries_and_recording(self, world):
        _season, post = _published_post(world)
        verified = post["verified_at"]
        due = {d.window: d for d in world.analytics.due_windows(post["id"])}
        assert set(due) == set(SnapshotWindow)
        assert due[SnapshotWindow.H24].boundary == verified + timedelta(hours=24)
        assert due[SnapshotWindow.D7].boundary == verified + timedelta(days=7)
        assert all(not d.recorded for d in due.values())

        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(1)},
            )
        )
        due = {d.window: d for d in world.analytics.due_windows(post["id"])}
        assert due[SnapshotWindow.H24].recorded
        assert not due[SnapshotWindow.H72].recorded

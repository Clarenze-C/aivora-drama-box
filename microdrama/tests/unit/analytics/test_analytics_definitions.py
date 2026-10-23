"""Incompatible view definitions never merge; cross-platform sums never happen (T027)."""

from __future__ import annotations

import pytest
from analytics_support import AnalyticsWorld

from microdrama.analytics import compare_series
from microdrama.contracts.enums import SnapshotWindow
from microdrama.contracts.errors import Conflict


def _published_post(world: AnalyticsWorld):
    season = world.season()
    return world.published_episode(season, number=2)


class TestSeriesDefinitions:
    def test_changed_definition_id_across_windows_refuses_merge(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100, definition="views-v1")},
            )
        )
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H72,
                observed_at_hours=73,
                metrics={"views": world.metric(150, definition="views-v2")},
            )
        )
        with pytest.raises(Conflict) as exc:
            world.analytics.metric_series(post["id"], "views")
        assert (
            "views-v1" in exc.value.details["definitions_versions"]
            and "views-v2" in exc.value.details["definitions_versions"]
        )

    def test_changed_definitions_version_refuses_merge(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100)},
                definitions_version="metrics-2026-10",
            )
        )
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H72,
                observed_at_hours=73,
                metrics={"views": world.metric(150)},
                definitions_version="metrics-2026-11",  # platform restated its rule set
            )
        )
        with pytest.raises(Conflict):
            world.analytics.metric_series(post["id"], "views")

    def test_matching_definitions_series_in_window_order(self, world):
        _season, post = _published_post(world)
        for window, hours, value in (
            (SnapshotWindow.H24, 25, 100),
            (SnapshotWindow.H72, 73, 150),
            (SnapshotWindow.D7, 24 * 7 + 1, 180),
        ):
            world.analytics.record_snapshot(
                world.snapshot(
                    post,
                    window=window,
                    observed_at_hours=hours,
                    metrics={"views": world.metric(value)},
                )
            )
        series = world.analytics.metric_series(post["id"], "views")
        assert [p.value for p in series.points] == [100, 150, 180]
        assert [p.window for p in series.points] == [
            SnapshotWindow.H24,
            SnapshotWindow.H72,
            SnapshotWindow.D7,
        ]


class TestComparisonRules:
    def test_cross_platform_same_metric_name_is_refused(self, world):
        _season, post = _published_post(world)
        left = world.analytics.metric_series(post["id"], "views")
        from microdrama.analytics import MetricPoint, MetricSeries

        right = MetricSeries(
            platform="tiktok",
            platform_post_id=post["id"],
            metric="views",
            points=(
                MetricPoint(
                    platform="tiktok",
                    metric="views",
                    value=99,
                    definition="views-def",
                    definitions_version="fake-metrics-v1",
                    window=SnapshotWindow.H24,
                ),
            ),
        )
        with pytest.raises(Conflict):
            compare_series(left, right)

    def test_same_definition_comparison_is_explicitly_non_causal(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100)},
            )
        )
        from microdrama.analytics import MetricPoint, MetricSeries

        left = world.analytics.metric_series(post["id"], "views")
        template = left.points[0]
        right = MetricSeries(
            platform=left.platform,
            platform_post_id=uuid_other(),
            metric="views",
            points=(
                MetricPoint(
                    platform=left.platform,
                    metric="views",
                    value=80,
                    definition=template.definition,
                    definitions_version=template.definitions_version,
                    denominator=template.denominator,
                    traffic=template.traffic,
                    window=template.window,
                ),
            ),
        )
        comparison = compare_series(left, right)
        assert comparison.causal is False
        from microdrama.analytics import NON_CAUSAL_DISCLAIMER as _DISCLAIMER

        assert comparison.disclaimer == _DISCLAIMER

    def test_divergent_definitions_comparison_is_conflict(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100, definition="views-v1")},
            )
        )
        from microdrama.analytics import MetricPoint, MetricSeries

        left = world.analytics.metric_series(post["id"], "views")
        right = MetricSeries(
            platform=left.platform,
            platform_post_id=uuid_other(),
            metric="views",
            points=(
                MetricPoint(
                    platform=left.platform,
                    metric="views",
                    value=80,
                    definition="views-v2",
                    definitions_version="fake-metrics-v1",
                    window=SnapshotWindow.H24,
                ),
            ),
        )
        with pytest.raises(Conflict):
            compare_series(left, right)


class TestTrafficGroups:
    def test_mixed_definitions_in_one_group_refuse_to_total(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100)},
                definitions_version="metrics-a",
            )
        )
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H72,
                observed_at_hours=73,
                metrics={"views": world.metric(150)},
                definitions_version="metrics-b",
            )
        )
        with pytest.raises(Conflict):
            world.analytics.traffic_ledger(post["episode_id"])

    def test_unknown_traffic_is_its_own_group_never_folded_into_organic(self, world):
        _season, post = _published_post(world)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100)},
                traffic="ORGANIC",
            )
        )
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H72,
                observed_at_hours=73,
                metrics={"views": world.metric(50)},
                traffic="UNKNOWN",
            )
        )
        rows = {r.traffic: r for r in world.analytics.traffic_ledger(post["episode_id"])}
        assert rows["ORGANIC"].totals["views"] == 100
        assert rows["UNKNOWN"].totals["views"] == 50


def uuid_other():
    import uuid

    return uuid.uuid4()

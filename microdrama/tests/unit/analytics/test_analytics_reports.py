"""Report templates: deterministic, honest missing markers, fixed disclaimer (T027)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from analytics_support import AnalyticsWorld

from microdrama.analytics import (
    NON_CAUSAL_DISCLAIMER,
    CohortRow,
    MetricPoint,
    render_cohort_comparison,
    render_scorecard,
    render_traffic_ledger,
)
from microdrama.analytics.ledger import CohortComparison
from microdrama.analytics.reports import MISSING
from microdrama.contracts.enums import SnapshotWindow


def _season_with_cost(world: AnalyticsWorld):
    season = world.season()
    episode, _post = world.published_episode(season, number=2)
    world.charge(episode, 400_000)
    world.failed_episode(season, number=3, outcome="FAILED_QA", spend_micro_usd=250_000)
    result = world.analytics.evaluate_qualification(
        season, now=world.clock.now() + timedelta(days=30)
    )
    cost = world.analytics.season_cost(season)
    return result, cost


class TestScorecard:
    def test_renders_statuses_costs_and_failures(self, world):
        result, cost = _season_with_cost(world)
        text = render_scorecard(result, cost)
        assert "Ten-episode qualification scorecard" in text
        assert "0/10 consecutive" in text  # the failed episode 3 is the trailing episode
        assert "$0.65" in text  # 650k µ$ total variable spend, failures retained
        assert "outcome=FAILED_QA" in text
        assert "reported separately" in text
        assert "One success is never enough" in text

    def test_missing_renders_as_em_dash_never_zero(self, world):
        result, cost = _season_with_cost(world)
        text = render_scorecard(result, cost)
        # human review minutes are unmeasured: rendered missing, not 0
        assert MISSING in text

    def test_deterministic_rendering(self, world):
        result, cost = _season_with_cost(world)
        assert render_scorecard(result, cost) == render_scorecard(result, cost)


class TestTrafficReport:
    def test_definitions_versions_are_shown(self, world):
        season = world.season()
        _episode, post = world.published_episode(season, number=2)
        world.analytics.record_snapshot(
            world.snapshot(
                post,
                window=SnapshotWindow.H24,
                observed_at_hours=25,
                metrics={"views": world.metric(100)},
                traffic="ORGANIC",
            )
        )
        rows = world.analytics.traffic_ledger(post["episode_id"])
        text = render_traffic_ledger(rows)
        assert "fake-metrics-v1" in text
        assert "views-def" in text
        assert "| YOUTUBE | ORGANIC | fake-metrics-v1 | views (views-def) | 100 |" in text


class TestComparisonReport:
    def test_disclaimer_is_verbatim(self, world):
        left = CohortRow(
            experiment_id=uuid.uuid4(),
            candidate_id="hook-1",
            cohort="cohort-1",
            platform="youtube",
            exposures=1,
            metrics=(
                MetricPoint(
                    platform="youtube",
                    metric="views",
                    value=120,
                    definition="views-def",
                    definitions_version="fake-metrics-v1",
                    window=SnapshotWindow.H24,
                ),
            ),
        )
        right = CohortRow(
            experiment_id=uuid.uuid4(),
            candidate_id="hook-2",
            cohort="cohort-2",
            platform="youtube",
            exposures=1,
            metrics=(
                MetricPoint(
                    platform="youtube",
                    metric="views",
                    value=80,
                    definition="views-def",
                    definitions_version="fake-metrics-v1",
                    window=SnapshotWindow.H24,
                ),
            ),
        )
        comparison = CohortComparison(left=left, right=right)
        assert comparison.causal is False
        text = render_cohort_comparison(comparison, metric="views")
        assert NON_CAUSAL_DISCLAIMER in text
        assert "hook-1" in text and "hook-2" in text

    def test_missing_values_render_missing_not_zero(self):
        left = CohortRow(
            experiment_id=uuid.uuid4(),
            candidate_id="hook-1",
            cohort="cohort-1",
            platform="youtube",
            exposures=1,
            missing=("H72:views",),
        )
        right = CohortRow(
            experiment_id=uuid.uuid4(),
            candidate_id="hook-2",
            cohort="cohort-2",
            platform="youtube",
            exposures=1,
        )
        text = render_cohort_comparison(CohortComparison(left=left, right=right), metric="views")
        assert "H72:views" in text
        assert MISSING in text

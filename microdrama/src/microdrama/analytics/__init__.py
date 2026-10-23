"""Analytics lane (T027): snapshots with provenance, hook/traffic ledgers,
effective cost and rolling ten-episode qualification (IMP-08, MD-017, AT-12).

Consumes only frozen surfaces: ``contracts.catalog.MetricSnapshot`` /
``QualificationResult`` / ``EpisodeQualification``, the migration-0005 tables
(``performance_snapshots``, ``qualification_runs``, ``platform_posts``) and the
real budget counters. No routers, no contracts changes, no migrations.
"""

from __future__ import annotations

from .cost import (
    EpisodeSpend,
    SeasonCost,
    effective_cost,
    published_minutes_ms,
    season_cost,
)
from .handlers import Handler, analytics_handlers
from .ledger import (
    NON_CAUSAL_DISCLAIMER,
    CohortComparison,
    CohortRow,
    MetricPoint,
    MetricSeries,
    TrafficRow,
    compare_series,
    hook_ledger,
    metric_series,
    traffic_ledger,
)
from .qualification import (
    MANAGEMENT_WINDOW_DAYS,
    REQUIRED_CONSECUTIVE,
    QualificationEvaluator,
)
from .reports import render_cohort_comparison, render_scorecard, render_traffic_ledger
from .service import AnalyticsService, build_analytics_service
from .snapshots import WINDOW_BOUNDARY_HOURS, DueWindow, SnapshotStore, window_boundary

__all__ = [
    "MANAGEMENT_WINDOW_DAYS",
    "NON_CAUSAL_DISCLAIMER",
    "REQUIRED_CONSECUTIVE",
    "AnalyticsService",
    "CohortComparison",
    "CohortRow",
    "DueWindow",
    "EpisodeSpend",
    "Handler",
    "MetricPoint",
    "MetricSeries",
    "QualificationEvaluator",
    "SeasonCost",
    "SnapshotStore",
    "TrafficRow",
    "WINDOW_BOUNDARY_HOURS",
    "analytics_handlers",
    "build_analytics_service",
    "compare_series",
    "effective_cost",
    "hook_ledger",
    "metric_series",
    "published_minutes_ms",
    "render_cohort_comparison",
    "render_scorecard",
    "render_traffic_ledger",
    "season_cost",
    "traffic_ledger",
    "window_boundary",
]

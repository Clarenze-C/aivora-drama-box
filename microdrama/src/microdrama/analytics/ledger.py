"""Hook/source/cohort/denominator ledger over snapshots and exposures (T027).

Read-only joins of ``performance_snapshots`` (this lane) with the frozen T016
``hook_experiments``/``hook_exposures`` tables. Truth rules this module owns:

- **Incompatible view definitions never merge.** Every aggregate carries the
  ``definitions_version`` it was computed under, and any comparison of the same
  metric name across different definitions (platform restated its counting rule)
  is a ``Conflict`` naming both versions. Summing the same metric name across
  platforms is likewise refused: a YouTube "view" and a TikTok "view" are
  different definitions even under one label.
- **Missing is explicit.** A hook exposure with no matching snapshot (or a metric
  absent from a snapshot) appears as ``missing``, never as zero.
- **Organic comparisons are not causal claims.** Every comparison structure this
  module returns carries ``causal=False`` and the fixed disclaimer string; there
  is no code path that emits a causal attribution for organic traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from microdrama.contracts.enums import SnapshotWindow
from microdrama.contracts.errors import Conflict
from microdrama.persistence.db import Tx

NON_CAUSAL_DISCLAIMER = (
    "Organic comparison only: cohorts were observed alongside each other, not "
    "assigned randomly; nothing here establishes a causal effect."
)


@dataclass(frozen=True)
class MetricPoint:
    """One metric under one platform definition: value may be None (missing)."""

    platform: str
    metric: str
    value: int | None
    definition: str
    definitions_version: str
    denominator: int | None = None
    traffic: str = "UNKNOWN"
    window: SnapshotWindow | None = None

    @property
    def missing(self) -> bool:
        return self.value is None


@dataclass(frozen=True)
class MetricSeries:
    """The same metric name for one post across windows, kept in window order."""

    platform: str
    platform_post_id: UUID
    metric: str
    points: tuple[MetricPoint, ...]


@dataclass(frozen=True)
class CohortRow:
    """One hook cohort's observed metrics; ``missing`` lists what was not reported."""

    experiment_id: UUID
    candidate_id: str
    cohort: str
    platform: str
    exposures: int
    metrics: tuple[MetricPoint, ...] = ()
    missing: tuple[str, ...] = ()
    snapshots_present: int = 0


@dataclass(frozen=True)
class CohortComparison:
    """Two cohorts' metrics side by side — explicitly not a causal claim."""

    left: CohortRow
    right: CohortRow
    causal: bool = False
    disclaimer: str = NON_CAUSAL_DISCLAIMER

    def __post_init__(self) -> None:
        if self.causal:
            raise ValueError("a cohort comparison is never causal; organic traffic only")


@dataclass(frozen=True)
class TrafficRow:
    """Metric totals for one platform and traffic kind, definitions included."""

    platform: str
    traffic: str
    definitions_version: str
    totals: dict[str, int | None] = field(default_factory=dict)
    definitions: dict[str, str] = field(default_factory=dict)


def _snapshot_metrics(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = row["metrics"]
    return metrics if isinstance(metrics, dict) else dict(metrics)


def metric_series(tx: Tx, platform_post_id: UUID, metric: str) -> MetricSeries:
    """All recorded windows of ``metric`` for one post, in H24/H72/D7 order.

    Refuses (``Conflict``) when the same metric name was recorded under different
    platform definitions — the caller is trying to merge incompatible views.
    """
    rows = tx.fetchall(
        "SELECT * FROM performance_snapshots WHERE platform_post_id = %s ORDER BY snapshot_window",
        (platform_post_id,),
    )
    order = {w.value: i for i, w in enumerate(SnapshotWindow)}
    rows = sorted(rows, key=lambda r: order[r["snapshot_window"]])
    points: list[MetricPoint] = []
    seen_definitions: set[tuple[str, str]] = set()
    platform = rows[0]["platform"] if rows else ""
    for row in rows:
        entry = _snapshot_metrics(row).get(metric)
        if entry is None:
            continue
        definition = (row["definitions_version"], entry["definition"])
        seen_definitions.add(definition)
        points.append(
            MetricPoint(
                platform=row["platform"],
                metric=metric,
                value=entry.get("value"),  # None stays None
                definition=entry["definition"],
                definitions_version=row["definitions_version"],
                denominator=entry.get("denominator"),
                traffic=row["traffic"],
                window=SnapshotWindow(row["snapshot_window"]),
            )
        )
    if len(seen_definitions) > 1:
        versions = ", ".join(
            sorted({f"{version}:{definition}" for version, definition in seen_definitions})
        )
        raise Conflict(
            "metric definition changed across windows; incompatible views do not merge",
            metric=metric,
            definitions_versions=versions,
        )
    return MetricSeries(
        platform=platform, platform_post_id=platform_post_id, metric=metric, points=tuple(points)
    )


def compare_series(left: MetricSeries, right: MetricSeries) -> CohortComparison:
    """Compare two series only when their definitions agree; else ``Conflict``."""
    if left.platform != right.platform or left.metric != right.metric:
        raise Conflict(
            "only the same metric on the same platform is comparable",
            left=f"{left.platform}:{left.metric}",
            right=f"{right.platform}:{right.metric}",
        )
    for a in left.points:
        for b in right.points:
            if a.window == b.window and (
                a.definition != b.definition or a.definitions_version != b.definitions_version
            ):
                raise Conflict(
                    "incompatible view definitions do not merge",
                    left=a.definitions_version,
                    right=b.definitions_version,
                    metric=left.metric,
                )
    return CohortComparison(
        left=_series_as_cohort(left),
        right=_series_as_cohort(right),
    )


def _series_as_cohort(series: MetricSeries) -> CohortRow:
    return CohortRow(
        experiment_id=series.platform_post_id,  # a plain series has no experiment
        candidate_id="",
        cohort="",
        platform=series.platform,
        exposures=0,
        metrics=series.points,
        snapshots_present=len(series.points),
    )


def hook_ledger(tx: Tx, episode_id: UUID, *, metric: str = "views") -> list[CohortRow]:
    """One row per (experiment, candidate, cohort) with that metric per platform.

    Exposures without a matching snapshot — or whose snapshot omits the metric —
    report ``missing`` explicitly. No cross-platform sums are produced.
    """
    exposures = tx.fetchall(
        "SELECT e.experiment_id, e.candidate_id, e.platform, e.cohort, e.platform_post_id "
        "FROM hook_exposures e WHERE e.platform_post_id IS NOT NULL "
        "ORDER BY e.experiment_id, e.candidate_id",
    )
    # One ledger row per (experiment, candidate): its post's snapshots, if any.
    cohorts: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in exposures:
        cohorts.setdefault(
            (row["experiment_id"], row["candidate_id"]),
            {
                "experiment_id": row["experiment_id"],
                "candidate_id": row["candidate_id"],
                "cohort": row["cohort"],
                "platform": row["platform"],
                "platform_post_id": row["platform_post_id"],
            },
        )
    rows: list[CohortRow] = []
    for cohort in cohorts.values():
        post_id = cohort["platform_post_id"]
        snapshots = tx.fetchall(
            "SELECT * FROM performance_snapshots WHERE platform_post_id = %s ORDER BY snapshot_window",
            (post_id,),
        )
        points: list[MetricPoint] = []
        missing: list[str] = []
        for snap in snapshots:
            entry = _snapshot_metrics(snap).get(metric)
            if entry is None or entry.get("value") is None:
                missing.append(f"{snap['snapshot_window']}:{metric}")
                continue
            points.append(
                MetricPoint(
                    platform=snap["platform"],
                    metric=metric,
                    value=entry["value"],
                    definition=entry["definition"],
                    definitions_version=snap["definitions_version"],
                    denominator=entry.get("denominator"),
                    traffic=snap["traffic"],
                    window=SnapshotWindow(snap["snapshot_window"]),
                )
            )
        count = tx.fetchval(
            "SELECT count(*) FROM hook_exposures WHERE experiment_id = %s AND candidate_id = %s",
            (cohort["experiment_id"], cohort["candidate_id"]),
        )
        rows.append(
            CohortRow(
                experiment_id=cohort["experiment_id"],
                candidate_id=cohort["candidate_id"],
                cohort=cohort["cohort"],
                platform=cohort["platform"],
                exposures=count or 0,
                metrics=tuple(points),
                missing=tuple(missing),
                snapshots_present=len(snapshots),
            )
        )
    return rows


def traffic_ledger(tx: Tx, episode_id: UUID) -> list[TrafficRow]:
    """Metric totals per (platform, traffic) with their definition versions.

    A metric any snapshot in the group reports as missing stays ``None`` for that
    group — a partially-reported total is not a total. UNKNOWN traffic is kept as
    its own group, never folded into ORGANIC.
    """
    snaps = tx.fetchall(
        "SELECT * FROM performance_snapshots WHERE episode_id = %s "
        "ORDER BY platform, traffic, snapshot_window",
        (episode_id,),
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for snap in snaps:
        grouped.setdefault((snap["platform"], snap["traffic"]), []).append(snap)
    rows: list[TrafficRow] = []
    for (platform, traffic), group in grouped.items():
        versions = {s["definitions_version"] for s in group}
        if len(versions) > 1:
            raise Conflict(
                "incompatible view definitions do not merge",
                platform=platform,
                definitions_versions=", ".join(sorted(versions)),
            )
        totals: dict[str, int | None] = {}
        definitions: dict[str, str] = {}
        for snap in group:
            for name, entry in _snapshot_metrics(snap).items():
                value = entry.get("value")
                if name not in totals:
                    totals[name] = value
                    definitions[name] = entry["definition"]
                elif value is None or totals[name] is None:
                    totals[name] = None  # any missing report keeps the total missing
                else:
                    totals[name] = totals[name] + value
        rows.append(
            TrafficRow(
                platform=platform,
                traffic=traffic,
                definitions_version=next(iter(versions)),
                totals=totals,
                definitions=definitions,
            )
        )
    return rows


__all__ = [
    "CohortComparison",
    "CohortRow",
    "MetricPoint",
    "MetricSeries",
    "NON_CAUSAL_DISCLAIMER",
    "TrafficRow",
    "compare_series",
    "hook_ledger",
    "metric_series",
    "traffic_ledger",
]

"""Deterministic report templates for the IMP-08 scorecard and ledgers (T027).

Every renderer is a pure function of its structured inputs — same inputs, same
bytes. Missing values render as ``—`` (unknown), never ``0``; organic
comparisons carry the fixed non-causal disclaimer verbatim; every metric table
shows the definitions version it was computed under.
"""

from __future__ import annotations

from microdrama.contracts.catalog import QualificationResult

from .cost import SeasonCost
from .ledger import NON_CAUSAL_DISCLAIMER, CohortComparison, CohortRow, TrafficRow

MISSING = "—"


def _fmt(value: int | None, *, micro: bool = False) -> str:
    if value is None:
        return MISSING
    if micro:
        return f"${value / 1_000_000:.2f}"
    return f"{value:,}"


def render_scorecard(result: QualificationResult, cost: SeasonCost) -> str:
    """The rolling qualification + effective-cost scorecard (IMP-08)."""
    lines: list[str] = []
    lines.append("# Ten-episode qualification scorecard")
    lines.append("")
    lines.append(
        f"- Production: **{result.production_status.value}** "
        f"({result.consecutive_qualifying_production}/{result.required_consecutive} consecutive)"
    )
    lines.append(f"- Management (7-day windows): **{result.management_status.value}**")
    if result.streak_resets:
        lines.append("- Streak resets:")
        lines.extend(f"  - {reason}" for reason in result.streak_resets)
    lines.append("")
    lines.append("## Episodes")
    lines.append("")
    lines.append(
        "| ep | production | management | window ends | published min | spend | failed cost | manual | review min |"
    )
    lines.append("|---:|---|---|---|---:|---:|---:|---:|---:|")
    for episode in result.episodes:
        qualifies = (
            MISSING if episode.production_qualifies is None else str(episode.production_qualifies)
        )
        ends = (
            MISSING
            if episode.management_window_ends_at is None
            else episode.management_window_ends_at.isoformat(timespec="minutes")
        )
        minutes = episode.published_minutes_ms // 60_000
        lines.append(
            f"| {episode.episode_number} | {qualifies} | {episode.management_window_status.value} "
            f"| {ends} | {minutes if minutes else MISSING} "
            f"| {_fmt(episode.variable_cost_micro_usd, micro=True)} "
            f"| {_fmt(episode.failed_attempt_cost_micro_usd, micro=True)} "
            f"| {episode.manual_interventions} | {_fmt(episode.human_review_minutes)} |"
        )
    lines.append("")
    lines.append("## Effective cost")
    lines.append("")
    lines.append(
        f"- Variable spend (all episodes, failures retained): {_fmt(cost.variable_micro_usd, micro=True)}"
    )
    lines.append(f"- Successful episodes: {result.successful_episodes}")
    lines.append(
        "- Effective cost per successful episode: "
        + (
            _fmt(result.effective_cost_per_successful_episode_micro_usd, micro=True)
            if result.successful_episodes
            else MISSING + " (no successful episode yet)"
        )
    )
    minutes = sum(e.published_minutes_ms for e in result.episodes) // 60_000
    lines.append(
        "- Effective cost per published minute: "
        + (
            _fmt(result.effective_cost_per_published_minute_micro_usd, micro=True)
            if minutes
            else MISSING + " (no published minute yet)"
        )
    )
    lines.append(f"- Recorded overruns (never erased): {_fmt(cost.overrun_micro_usd, micro=True)}")
    lines.append(
        f"- Fixed season research (reported separately): {_fmt(cost.fixed_research_micro_usd, micro=True)}"
    )
    lines.append("")
    lines.append(
        f"Required consecutive qualifying episodes: {result.required_consecutive}. One success is never enough."
    )
    return "\n".join(lines) + "\n"


def render_cohort_comparison(comparison: CohortComparison, *, metric: str) -> str:
    """Two hook cohorts side by side, with the non-causal disclaimer verbatim."""

    def row(cohort: CohortRow) -> str:
        values = " ".join(f"{p.window.value}={_fmt(p.value)}" for p in cohort.metrics if p.window)
        missing = ", ".join(cohort.missing) if cohort.missing else MISSING
        return (
            f"| {cohort.candidate_id} | {cohort.cohort} | {cohort.platform} "
            f"| {cohort.exposures} | {values or MISSING} | {missing} |"
        )

    versions = {
        p.definitions_version for c in (comparison.left, comparison.right) for p in c.metrics
    }
    lines = [
        f"## Hook cohort comparison — {metric}",
        "",
        "| candidate | cohort | platform | exposures | observed | missing |",
        "|---|---|---|---:|---|---|",
        row(comparison.left),
        row(comparison.right),
        "",
        NON_CAUSAL_DISCLAIMER,
    ]
    if len(versions) > 1:
        lines.append(f"Definitions versions in view: {', '.join(sorted(versions))}.")
    return "\n".join(lines) + "\n"


def render_traffic_ledger(rows: list[TrafficRow]) -> str:
    """Per-platform traffic totals with definitions versions; UNKNOWN stays its own row."""
    lines = [
        "## Traffic ledger",
        "",
        "| platform | traffic | definitions | metric | total |",
        "|---|---|---|---|---:|",
    ]
    for row in rows:
        for metric, total in sorted(row.totals.items()):
            lines.append(
                f"| {row.platform} | {row.traffic} | {row.definitions_version} "
                f"| {metric} ({row.definitions.get(metric, MISSING)}) | {_fmt(total)} |"
            )
    if len(rows) > 1:
        lines.append("")
        lines.append(
            "Totals are per platform: cross-platform sums of same-named metrics are not computed."
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "MISSING",
    "render_cohort_comparison",
    "render_scorecard",
    "render_traffic_ledger",
]

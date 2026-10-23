"""Effective cost: every real micro-dollar spent, including failures (T027, IMP-08).

Reads the REAL budget ledger counters maintained by ``BudgetService`` — never a
reconstruction from raw charge rows (an ACCRUAL and its SETTLEMENT are two
receipts for one reservation; only the service's counters net them). Truth rules:

- **Failed and rejected spend is retained.** An episode that never qualified
  still spent real money; its whole account spend counts toward the season's
  effective cost, and is surfaced per episode as ``failed_attempt_cost``. Credits
  never restore allowance, so nothing here subtracts them.
- **Committed is committed.** ``reserved_outstanding`` (holds still open) and
  recorded overruns count as spend; a cost report that hid them would understate
  the effective cost of the pipeline.
- **Season research is fixed, reported separately.** The season research account
  is not part of per-episode variable cost; it rides along in the breakdown for
  the report, flagged ``fixed_costs_reported_separately``.
- **Minutes come from what was actually published.** Published minutes are the
  full-episode master durations of qualifying episodes, read from the assets the
  posts published. An episode with no readable duration contributes nothing and
  is listed as unmeasured rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from microdrama.persistence.db import Tx

_PUBLISHED_SLOT_KINDS = ("FULL_EPISODE",)


def _account_spend(row: dict[str, Any]) -> int:
    return (
        row["settled_micro_usd"]
        + row["accrued_micro_usd"]
        + row["reserved_outstanding_micro_usd"]
        + row["overrun_micro_usd"]
    )


@dataclass(frozen=True)
class EpisodeSpend:
    episode_id: UUID
    episode_number: int
    spend_micro_usd: int
    overrun_micro_usd: int

    @property
    def overrun(self) -> bool:
        return self.overrun_micro_usd > 0


@dataclass(frozen=True)
class SeasonCost:
    """Effective variable cost of a season's episodes + fixed research, separate."""

    season_id: UUID
    variable_micro_usd: int = 0
    fixed_research_micro_usd: int = 0
    overrun_micro_usd: int = 0
    per_episode: tuple[EpisodeSpend, ...] = ()
    published_minutes_ms: int = 0

    @property
    def fixed_costs_reported_separately(self) -> bool:
        return True


def episode_spend(tx: Tx, episode_id: UUID) -> EpisodeSpend | None:
    row = tx.fetchone(
        "SELECT a.settled_micro_usd, a.accrued_micro_usd, a.reserved_outstanding_micro_usd, "
        "a.overrun_micro_usd, e.episode_number "
        "FROM budget_accounts a JOIN episodes e ON e.id = a.episode_id "
        "WHERE a.scope_kind = 'EPISODE' AND a.episode_id = %s",
        (episode_id,),
    )
    if row is None:
        return None
    return EpisodeSpend(
        episode_id=episode_id,
        episode_number=row["episode_number"],
        spend_micro_usd=_account_spend(row),
        overrun_micro_usd=row["overrun_micro_usd"],
    )


def season_cost(tx: Tx, season_id: UUID) -> SeasonCost:
    """Variable spend over every episode account + the season's fixed research."""
    episode_rows = tx.fetchall(
        "SELECT a.id, a.settled_micro_usd, a.accrued_micro_usd, a.reserved_outstanding_micro_usd, "
        "a.overrun_micro_usd, a.episode_id, e.episode_number "
        "FROM budget_accounts a JOIN episodes e ON e.id = a.episode_id "
        "WHERE a.scope_kind = 'EPISODE' AND a.season_id = %s ORDER BY e.episode_number",
        (season_id,),
    )
    per_episode = tuple(
        EpisodeSpend(
            episode_id=row["episode_id"],
            episode_number=row["episode_number"],
            spend_micro_usd=_account_spend(row),
            overrun_micro_usd=row["overrun_micro_usd"],
        )
        for row in episode_rows
    )
    research = tx.fetchone(
        "SELECT settled_micro_usd, accrued_micro_usd, reserved_outstanding_micro_usd, overrun_micro_usd "
        "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
        (season_id,),
    )
    return SeasonCost(
        season_id=season_id,
        variable_micro_usd=sum(spend.spend_micro_usd for spend in per_episode),
        fixed_research_micro_usd=_account_spend(research) if research else 0,
        overrun_micro_usd=sum(spend.overrun_micro_usd for spend in per_episode),
        per_episode=per_episode,
    )


def published_minutes_ms(tx: Tx, episode_ids: tuple[UUID, ...]) -> tuple[int, tuple[UUID, ...]]:
    """Sum the full-episode master durations of ``episode_ids``.

    Returns ``(total_ms, unmeasured)`` where ``unmeasured`` lists episodes whose
    published master has no readable duration — reported, never assumed as zero.
    """
    if not episode_ids:
        return 0, ()
    total = 0
    unmeasured: list[UUID] = []
    for episode_id in episode_ids:
        duration = tx.fetchval(
            "SELECT max(a.duration_ms) FROM platform_posts p JOIN assets a ON a.id = p.asset_id "
            "WHERE p.episode_id = %s AND p.slot_kind = ANY(%s) AND p.verified_at IS NOT NULL",
            (episode_id, list(_PUBLISHED_SLOT_KINDS)),
        )
        if duration is None:
            unmeasured.append(episode_id)
        else:
            total += int(duration)
    return total, tuple(unmeasured)


def effective_cost(
    *,
    total_variable_micro_usd: int,
    successful_episodes: int,
    published_minutes_ms: int,
) -> tuple[int | None, int | None]:
    """Per-successful-episode and per-published-minute cost; None when undividable."""
    per_episode = (
        total_variable_micro_usd // successful_episodes if successful_episodes > 0 else None
    )
    minutes = published_minutes_ms // 60_000
    per_minute = total_variable_micro_usd // minutes if minutes > 0 else None
    return per_episode, per_minute


__all__ = [
    "EpisodeSpend",
    "SeasonCost",
    "effective_cost",
    "episode_spend",
    "published_minutes_ms",
    "season_cost",
]

"""Rolling ten-episode qualification and management windows (T027, MD-017, IMP-08).

The frozen contract is ``contracts.catalog.QualificationResult`` (whose validator
already enforces episode order, the trailing-streak definition and
``required_consecutive == 10``) and the frozen table is ``qualification_runs``
(append-only; the database itself refuses a QUALIFIED row with fewer than ten
consecutive qualifying episodes). Truth rules this module owns:

- **One success is never enough.** Production qualifies only at ten consecutive
  qualifying episodes. A season with a clean record so far but fewer than ten is
  ``PENDING``; a season whose streak broke and is rebuilding is ``NOT_QUALIFIED``
  until it reaches ten again.
- **A qualifying episode earned it alone**: ``PUBLISHED_VERIFIED``/``MANAGED``
  state, no failure outcome, and **zero manual interventions**. A failed/rejected
  episode breaks the streak; so does an episode that was published only because a
  human fixed or uploaded something. An episode still in flight is ``None``
  (pending) and also stops the streak — the rolling count is trailing.
- **Management windows are per episode and start at publication.** The window is
  the first seven days after the episode's first verified post. Before day seven
  the window is ``PENDING`` (with its end recorded); after seven clean days it is
  ``QUALIFIED``; any manual intervention inside the window makes it
  ``NOT_QUALIFIED`` (unattended management was rescued by a human). An episode
  still in flight has not opened a window (``PENDING``); an episode that failed
  before publication never will (``NOT_QUALIFIED`` — the management track cannot
  complete around a production failure).
- **Costs travel with the verdict.** Every episode's spend — failed ones
  included — is read from the real budget counters (``analytics.cost``); the
  effective cost of a season counts every micro-dollar, and a non-qualifying
  episode's spend is exactly its ``failed_attempt_cost``. Human review time is
  not instrumented anywhere in the pipeline yet, so it stays ``None`` — unknown
  is null, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from microdrama.contracts.catalog import EpisodeQualification, QualificationResult
from microdrama.contracts.enums import EpisodeState, Provenance, QualificationStatus
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

from .cost import effective_cost, episode_spend, published_minutes_ms, season_cost

REQUIRED_CONSECUTIVE = 10
MANAGEMENT_WINDOW_DAYS = 7

_PUBLISHED_STATES = frozenset({EpisodeState.PUBLISHED_VERIFIED.value, EpisodeState.MANAGED.value})
_MANAGEMENT_INTERVENTION_KINDS = (
    "TECHNICAL_FIX",
    "MANUAL_EDIT",
    "MANUAL_UPLOAD",
    "DATA_CORRECTION",
    "OTHER",
)


@dataclass(frozen=True)
class EpisodeFacts:
    """Everything one episode contributes to a qualification run."""

    episode_id: UUID
    episode_number: int
    state: str
    outcome: str | None
    manual_interventions: int
    management_started_at: datetime | None
    spend_micro_usd: int


def _episode_facts(tx: Tx, season_id: UUID) -> list[EpisodeFacts]:
    episodes = tx.fetchall(
        "SELECT id, episode_number, state, outcome FROM episodes WHERE season_id = %s "
        "ORDER BY episode_number",
        (season_id,),
    )
    interventions = {
        row["episode_id"]: int(row["n"])
        for row in tx.fetchall(
            "SELECT episode_id, count(*) AS n FROM manual_interventions "
            "WHERE season_id = %s AND episode_id IS NOT NULL GROUP BY episode_id",
            (season_id,),
        )
    }
    starts = {
        row["episode_id"]: row["started_at"]
        for row in tx.fetchall(
            "SELECT episode_id, min(verified_at) AS started_at FROM platform_posts "
            "WHERE episode_id IS NOT NULL AND verified_at IS NOT NULL GROUP BY episode_id",
        )
    }
    facts: list[EpisodeFacts] = []
    for row in episodes:
        spend = episode_spend(tx, row["id"])
        facts.append(
            EpisodeFacts(
                episode_id=row["id"],
                episode_number=row["episode_number"],
                state=row["state"],
                outcome=row["outcome"],
                manual_interventions=interventions.get(row["id"], 0),
                management_started_at=starts.get(row["id"]),
                spend_micro_usd=spend.spend_micro_usd if spend else 0,
            )
        )
    return facts


def _window_interventions(tx: Tx, episode_id: UUID, started_at: datetime, ends_at: datetime) -> int:
    return int(
        tx.fetchval(
            "SELECT count(*) FROM manual_interventions WHERE episode_id = %s "
            "AND kind = ANY(%s) AND occurred_at >= %s AND occurred_at <= %s",
            (episode_id, list(_MANAGEMENT_INTERVENTION_KINDS), started_at, ends_at),
        )
        or 0
    )


def _production_qualifies(facts: EpisodeFacts) -> bool | None:
    if facts.outcome is not None:
        return False
    if facts.state in _PUBLISHED_STATES:
        # A published episode that needed a human is a manual-fixed episode.
        return facts.manual_interventions == 0
    return None  # still in flight


def _production_reason(facts: EpisodeFacts, qualifies: bool | None) -> str:
    if qualifies is None:
        return "pending: episode still in flight"
    if facts.outcome is not None:
        return f"outcome={facts.outcome}"
    if facts.manual_interventions:
        return f"manual_interventions={facts.manual_interventions}"
    return "published clean"


def _management_window(
    tx: Tx, facts: EpisodeFacts, *, now: datetime
) -> tuple[QualificationStatus, datetime | None]:
    if facts.outcome is not None:
        return QualificationStatus.NOT_QUALIFIED, None
    if facts.state not in _PUBLISHED_STATES:
        return QualificationStatus.PENDING, None  # in flight: window not opened
    started = facts.management_started_at
    if started is None:
        # Published state without any verified post: window cannot start; stay
        # pending rather than inventing a start.
        return QualificationStatus.PENDING, None
    ends_at = started + timedelta(days=MANAGEMENT_WINDOW_DAYS)
    if now < ends_at:
        return QualificationStatus.PENDING, ends_at
    if _window_interventions(tx, facts.episode_id, started, ends_at) > 0:
        return QualificationStatus.NOT_QUALIFIED, ends_at
    return QualificationStatus.QUALIFIED, ends_at


def _run_status(
    episodes: list[EpisodeQualification], consecutive: int
) -> tuple[QualificationStatus, QualificationStatus]:
    if not episodes:
        return QualificationStatus.PENDING, QualificationStatus.PENDING
    if consecutive >= REQUIRED_CONSECUTIVE:
        production = QualificationStatus.QUALIFIED
    elif any(e.production_qualifies is False for e in episodes):
        production = QualificationStatus.NOT_QUALIFIED  # a reset happened; rebuilding
    else:
        production = QualificationStatus.PENDING  # clean so far, fewer than ten
    # Management rolls over the last ten windows (the contract pins: QUALIFIED
    # needs ten corresponding qualified windows). A failed window inside the
    # tail is NOT_QUALIFIED; anything else still open or short of ten is PENDING.
    tail = episodes[-REQUIRED_CONSECUTIVE:]
    if len(tail) == REQUIRED_CONSECUTIVE and all(
        e.management_window_status is QualificationStatus.QUALIFIED for e in tail
    ):
        management = QualificationStatus.QUALIFIED
    elif any(e.management_window_status is QualificationStatus.NOT_QUALIFIED for e in tail):
        management = QualificationStatus.NOT_QUALIFIED
    else:
        management = QualificationStatus.PENDING
    return production, management


class QualificationEvaluator:
    """Evaluate and persist one qualification run for a season."""

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids

    def evaluate(self, season_id: UUID, *, now: datetime | None = None) -> QualificationResult:
        instant = now or self._clock.now()
        with self._db.transaction() as tx:
            result = self._build(tx, season_id, instant)
            insert_row(
                tx,
                "qualification_runs",
                {
                    "id": result.run_id,
                    "season_id": season_id,
                    "evaluated_at": result.evaluated_at,
                    "production_status": result.production_status.value,
                    "management_status": result.management_status.value,
                    "consecutive": result.consecutive_qualifying_production,
                    "body": jsonb(result.model_dump(mode="json")),
                },
            )
        return result

    def _build(self, tx: Tx, season_id: UUID, now: datetime) -> QualificationResult:
        facts = _episode_facts(tx, season_id)
        episode_rows: list[EpisodeQualification] = []
        streak_resets: list[str] = []
        total_minutes_ms = 0
        for fact in facts:
            qualifies = _production_qualifies(fact)
            management, ends_at = _management_window(tx, fact, now=now)
            episode_minutes = 0
            if qualifies is True:
                episode_minutes, _unmeasured = published_minutes_ms(tx, (fact.episode_id,))
                total_minutes_ms += episode_minutes
            episode_rows.append(
                EpisodeQualification(
                    episode_id=fact.episode_id,
                    episode_number=fact.episode_number,
                    production_qualifies=qualifies,
                    production_reasons=[_production_reason(fact, qualifies)],
                    management_window_status=management,
                    management_window_ends_at=ends_at,
                    variable_cost_micro_usd=fact.spend_micro_usd,
                    failed_attempt_cost_micro_usd=(
                        fact.spend_micro_usd if qualifies is not True else 0
                    ),
                    manual_interventions=fact.manual_interventions,
                    human_review_minutes=None,  # not instrumented; unknown stays null
                    published_minutes_ms=episode_minutes,
                )
            )
            # Only a failed or manual-fixed episode is a *reset*; an in-flight
            # episode is an open end, not a reset (the trailing streak still
            # stops there, which the contract validator enforces).
            if qualifies is False:
                streak_resets.append(
                    f"ep {fact.episode_number}: {_production_reason(fact, qualifies)}"
                )
        consecutive = 0
        for row in reversed(episode_rows):
            if row.production_qualifies is not True or row.manual_interventions:
                break
            consecutive += 1
        production, management_status = _run_status(episode_rows, consecutive)
        cost = season_cost(tx, season_id)
        successful = sum(1 for row in episode_rows if row.production_qualifies is True)
        per_episode_cost, per_minute_cost = effective_cost(
            total_variable_micro_usd=cost.variable_micro_usd,
            successful_episodes=successful,
            published_minutes_ms=total_minutes_ms,
        )
        return QualificationResult(
            run_id=self._ids.new_id(),
            season_id=season_id,
            evaluated_at=now,
            required_consecutive=REQUIRED_CONSECUTIVE,
            consecutive_qualifying_production=consecutive,
            production_status=production,
            management_status=management_status,
            episodes=episode_rows,
            streak_resets=streak_resets,
            total_variable_spend_micro_usd=cost.variable_micro_usd,
            successful_episodes=successful,
            effective_cost_per_successful_episode_micro_usd=per_episode_cost,
            effective_cost_per_published_minute_micro_usd=per_minute_cost,
            fixed_costs_reported_separately=True,
            provenance=Provenance.DERIVED_LOCAL,
        )


__all__ = [
    "MANAGEMENT_WINDOW_DAYS",
    "REQUIRED_CONSECUTIVE",
    "EpisodeFacts",
    "QualificationEvaluator",
]

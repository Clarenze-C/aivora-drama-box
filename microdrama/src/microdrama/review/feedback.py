"""Scoped feedback memory (T019; IMP-05).

Human revision notes (``feedback_events``, written only by Gate 2 REVISE through
``core.approvals``) become versioned ``preference_rules`` — but never by inference:

- a SHOT/EPISODE-scoped comment creates exactly a SHOT/EPISODE-scoped rule for that
  episode/shot. Nothing widens it;
- a SERIES-scoped rule exists only when the reviewer EXPLICITLY marked the feedback
  recurring (``explicit_recurring_instruction``), or when an approval package
  carries it (``source_approval_event_id`` route). ``promote_to_series`` refuses a
  local comment typed — the database CHECK refuses it again underneath.

Rules are versioned per ``(season_id, rule_key)`` with at most one ACTIVE version
(unique index), and every change is a new version: superseding writes
ACTIVE → SUPERSEDED, rollback writes ACTIVE → ROLLED_BACK and reactivates the
previous version. Rule ids are deterministic per (season, key, version), so a
replayed instruction is an idempotent replay, never a second row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from pydantic import Field

from microdrama.contracts.enums import (
    FeedbackCategory,
    FeedbackScope,
    PrincipalKind,
)
from microdrama.contracts.errors import NotFound, PolicyDenied, SchemaInvalid
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.primitives import ContractModel, Identifier, ShortText
from microdrama.contracts.principals import Principal
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, insert_row, update_with_revision

FEEDBACK_NAMESPACE = uuid5(UUID(int=0), "https://microdrama.invalid/ns/review-feedback")

RECORDED_EVENT = "review.preference.recorded"
ROLLED_BACK_EVENT = "review.preference.rolled_back"

RULE_STATES = ("ACTIVE", "SUPERSEDED", "ROLLED_BACK")

_FEEDBACK_PRINCIPAL = Principal(
    principal_id="svc:review-feedback", kind=PrincipalKind.SERVICE_WORKER
)


class ScopePromotionDenied(PolicyDenied):
    """A local comment cannot become a season rule without explicit instruction."""

    code = "SCOPE_PROMOTION_DENIED"


class PreferenceRuleView(ContractModel):
    """One stored preference version (module-local read view)."""

    rule_id: UUID
    season_id: UUID
    rule_key: Identifier
    version: int
    scope: FeedbackScope
    episode_id: UUID | None = None
    shot_key: ShortText | None = None
    category: FeedbackCategory
    instruction: str = Field(min_length=1, max_length=2000)
    source_feedback_event_id: UUID
    source_approval_event_id: UUID | None = None
    explicit_recurring: bool
    state: ShortText


def rule_key_for(
    category: FeedbackCategory,
    scope: FeedbackScope,
    *,
    episode_id: UUID | None,
    shot_key: str | None,
) -> str:
    """Deterministic rule key: the category plus its exact scope target.

    Dot-separated to satisfy the frozen ``Identifier`` pattern; the scope target is
    part of the key, so two episodes' local rules never collide.
    """
    if scope is FeedbackScope.SERIES:
        return f"{category.value}.series"
    if scope is FeedbackScope.SHOT:
        return f"{category.value}.shot.{shot_key}"
    return f"{category.value}.episode.{episode_id}"


class FeedbackMemory:
    """Scoped preference versions from human feedback. Construct once per process."""

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids

    # --- plumbing --------------------------------------------------------------------

    def _new_id(self) -> UUID:
        return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    # --- reads -----------------------------------------------------------------------

    def _feedback(self, feedback_event_id: UUID) -> dict[str, Any]:
        row = self._row("SELECT * FROM feedback_events WHERE id = %s", (feedback_event_id,))
        if row is None:
            raise NotFound("feedback event not found", feedback_event_id=str(feedback_event_id))
        return row

    def _season_of(self, episode_id: UUID) -> UUID:
        row = self._row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if row is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        return row["season_id"]

    def active_rules(self, season_id: UUID) -> list[PreferenceRuleView]:
        """Every ACTIVE preference version of the season (scoped memory others read)."""
        with self._db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT * FROM preference_rules WHERE season_id = %s AND state = 'ACTIVE' "
                "ORDER BY rule_key, version",
                (season_id,),
            )
        return [_view(row) for row in rows]

    # --- writes ----------------------------------------------------------------------

    def remember(self, feedback_event_id: UUID, *, instruction: str) -> PreferenceRuleView:
        """Record one feedback item as a preference version AT ITS OWN SCOPE.

        The scope is the reviewer's, never inferred: an EPISODE/SHOT comment becomes
        an EPISODE/SHOT rule; a SERIES rule only exists for feedback the reviewer
        explicitly marked recurring (the database CHECK enforces the same).
        """
        item = self._feedback(feedback_event_id)
        scope = FeedbackScope(item["scope"])
        recurring = bool(item["explicit_recurring"])
        if scope is FeedbackScope.SERIES and not recurring:
            raise ScopePromotionDenied(
                "series-wide feedback requires an explicit recurring instruction"
            )
        return self._insert_version(
            item,
            scope=scope,
            instruction=instruction,
            explicit_recurring=recurring,
        )

    def promote_to_series(self, feedback_event_id: UUID, *, instruction: str) -> PreferenceRuleView:
        """The explicit series-promotion route (IMP-05: no inference, ever).

        Refused typed unless the feedback event itself carries the reviewer's
        explicit recurring instruction; the DB CHECK refuses anything that slips
        past. The approval-package route (``source_approval_event_id`` on a SERIES
        row) is integrator wiring on top of the same table.
        """
        item = self._feedback(feedback_event_id)
        if not bool(item["explicit_recurring"]):
            raise ScopePromotionDenied(
                "a local comment cannot become a global season rule by inference; "
                "the series scope needs an explicit recurring instruction or an "
                "approval package",
                feedback_event_id=str(feedback_event_id),
            )
        return self._insert_version(
            item,
            scope=FeedbackScope.SERIES,
            instruction=instruction,
            explicit_recurring=True,
        )

    def rollback(self, season_id: UUID, rule_key: str) -> PreferenceRuleView:
        """Roll the rule back: ACTIVE → ROLLED_BACK, previous version reactivated."""
        now = self._now()
        with self._db.transaction() as tx:
            active = tx.fetchone(
                "SELECT * FROM preference_rules WHERE season_id = %s AND rule_key = %s "
                "AND state = 'ACTIVE' FOR UPDATE",
                (season_id, rule_key),
            )
            if active is None:
                raise NotFound(
                    "no ACTIVE preference rule to roll back",
                    season_id=str(season_id),
                    rule_key=rule_key,
                )
            update_with_revision(
                tx,
                "preference_rules",
                active["id"],
                int(active["revision"]),
                {"state": "ROLLED_BACK"},
                now=now,
            )
            previous = tx.fetchone(
                "SELECT * FROM preference_rules WHERE season_id = %s AND rule_key = %s "
                "AND version < %s AND state = 'SUPERSEDED' ORDER BY version DESC LIMIT 1",
                (season_id, rule_key, int(active["version"])),
            )
            reactivated: dict[str, Any] | None = None
            if previous is not None:
                update_with_revision(
                    tx,
                    "preference_rules",
                    previous["id"],
                    int(previous["revision"]),
                    {"state": "ACTIVE"},
                    now=now,
                )
                reactivated = tx.fetchone(
                    "SELECT * FROM preference_rules WHERE id = %s", (previous["id"],)
                )
            append_event(
                tx,
                aggregate_type="season",
                aggregate_id=season_id,
                event_type=ROLLED_BACK_EVENT,
                payload={
                    "rule_key": rule_key,
                    "rolled_back_version": int(active["version"]),
                    "reactivated_version": int(previous["version"]) if previous else None,
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        if reactivated is not None:
            return _view(reactivated)
        # Nothing to reactivate: the rule key is fully rolled back. The caller reads
        # the rolled-back row so the outcome is explicit.
        return _view(self._row("SELECT * FROM preference_rules WHERE id = %s", (active["id"],)))

    # --- versioning -----------------------------------------------------------------

    def _insert_version(
        self,
        item: dict[str, Any],
        *,
        scope: FeedbackScope,
        instruction: str,
        explicit_recurring: bool,
    ) -> PreferenceRuleView:
        if not instruction or not instruction.strip():
            raise SchemaInvalid("instruction must be a non-empty string")
        episode_id = item["episode_id"]
        season_id = self._season_of(episode_id)
        shot_key = item["shot_key"]
        if scope is FeedbackScope.SHOT and not shot_key:
            raise SchemaInvalid("a SHOT-scoped rule needs its shot key")
        rule_key = rule_key_for(
            FeedbackCategory(item["category"]),
            scope,
            episode_id=episode_id if scope is not FeedbackScope.SERIES else None,
            shot_key=str(shot_key) if shot_key else None,
        )
        now = self._now()
        with self._db.transaction() as tx:
            # Idempotency: the same feedback remembered again with the same
            # instruction and scope is a replay of the stored version, never a
            # second row. A different instruction is the next version.
            identical = tx.fetchone(
                "SELECT * FROM preference_rules WHERE season_id = %s AND rule_key = %s "
                "AND source_feedback_event_id = %s AND scope = %s AND instruction = %s "
                "ORDER BY version DESC LIMIT 1",
                (season_id, rule_key, item["id"], scope.value, instruction[:2000]),
            )
            if identical is not None:
                return _view(identical)
            version = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM preference_rules "
                    "WHERE season_id = %s AND rule_key = %s",
                    (season_id, rule_key),
                )
                or 1
            )
            rule_id = uuid5(FEEDBACK_NAMESPACE, f"{season_id}:{rule_key}:v{version}")
            existing = tx.fetchone("SELECT * FROM preference_rules WHERE id = %s", (rule_id,))
            if existing is not None:
                return _view(existing)  # deterministic replay: nothing re-recorded
            active = tx.fetchone(
                "SELECT id, revision FROM preference_rules WHERE season_id = %s "
                "AND rule_key = %s AND state = 'ACTIVE' FOR UPDATE",
                (season_id, rule_key),
            )
            if active is not None:
                update_with_revision(
                    tx,
                    "preference_rules",
                    active["id"],
                    int(active["revision"]),
                    {"state": "SUPERSEDED"},
                    now=now,
                )
            values = {
                "id": rule_id,
                "season_id": season_id,
                "rule_key": rule_key,
                "version": version,
                "scope": scope.value,
                "episode_id": episode_id if scope is not FeedbackScope.SERIES else None,
                "shot_key": str(shot_key) if scope is FeedbackScope.SHOT else None,
                "category": item["category"],
                "instruction": instruction[:2000],
                "source_feedback_event_id": item["id"],
                "source_approval_event_id": item["approval_event_id"],
                "explicit_recurring": explicit_recurring,
                "state": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
            insert_row(tx, "preference_rules", values, returning="id")
            append_event(
                tx,
                aggregate_type="season",
                aggregate_id=season_id,
                event_type=RECORDED_EVENT,
                payload={
                    "rule_id": str(rule_id),
                    "rule_key": rule_key,
                    "version": version,
                    "scope": scope.value,
                    "episode_id": str(episode_id) if scope is not FeedbackScope.SERIES else None,
                    "shot_key": str(shot_key) if scope is FeedbackScope.SHOT else None,
                    "category": item["category"],
                    "explicit_recurring": explicit_recurring,
                    "source_feedback_event_id": str(item["id"]),
                    "superseded_active": bool(active is not None),
                },
                correlation_id=self._new_id(),
                occurred_at=now,
            )
        return PreferenceRuleView(
            rule_id=rule_id,
            season_id=season_id,
            rule_key=rule_key,
            version=version,
            scope=scope,
            episode_id=episode_id if scope is not FeedbackScope.SERIES else None,
            shot_key=str(shot_key) if scope is FeedbackScope.SHOT else None,
            category=FeedbackCategory(item["category"]),
            instruction=instruction[:2000],
            source_feedback_event_id=item["id"],
            source_approval_event_id=item["approval_event_id"],
            explicit_recurring=explicit_recurring,
            state="ACTIVE",
        )


def _view(row: dict[str, Any]) -> PreferenceRuleView:
    return PreferenceRuleView(
        rule_id=row["id"],
        season_id=row["season_id"],
        rule_key=row["rule_key"],
        version=int(row["version"]),
        scope=FeedbackScope(row["scope"]),
        episode_id=row["episode_id"],
        shot_key=row["shot_key"],
        category=FeedbackCategory(row["category"]),
        instruction=row["instruction"],
        source_feedback_event_id=row["source_feedback_event_id"],
        source_approval_event_id=row["source_approval_event_id"],
        explicit_recurring=bool(row["explicit_recurring"]),
        state=row["state"],
    )


def build_feedback_memory(db: Database, clock: Clock, ids: IdGenerator) -> FeedbackMemory:
    """Composition-time factory (the integrator registers routes/jobs, not this module)."""
    return FeedbackMemory(db, clock, ids)


__all__ = [
    "FEEDBACK_NAMESPACE",
    "FeedbackMemory",
    "PreferenceRuleView",
    "RECORDED_EVENT",
    "ROLLED_BACK_EVENT",
    "ScopePromotionDenied",
    "build_feedback_memory",
    "rule_key_for",
]

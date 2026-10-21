"""Shared builders for the research tests (T009). Plain helpers; fixtures live in conftest.

Everything runs against real PostgreSQL (root ``db`` fixture) with the T007 fakes. The fake
source provider's fixture excerpts are fixed text, so theme keys mined from a default run
come from the source ids (``thai``, ``drama`` for ``src-thai-drama-1/2``); comparator
material is deliberately unrelated to the default concept so the CLEAR path is exercisable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.examples import season_scope
from microdrama.persistence import Database
from microdrama.research import (
    CommentIn,
    ComparatorCorpus,
    ConceptDraft,
    PersonaProfile,
    ResearchRequest,
    ResearchService,
    ResearchTrigger,
    build_research_service,
)
from microdrama.testing.fakes import FakeClock, FakeLLMProvider, FakeSourceProvider, SequentialIds
from microdrama.testing.seed import seed_season

T0 = datetime(2026, 10, 21, tzinfo=UTC)
ENVELOPE = 2_000_000
DEFAULT_KEY = "research.daily:v1"
DEFAULT_SOURCES = ("src-thai-drama-1", "src-thai-drama-2")

# Comparator material: unrelated to the default concept (chicken-rice family drama).
COMPARATOR_SCENE = (
    "A retired detective hunts a kidnapping syndicate through the flooded alleys of old "
    "Bangkok while his former partner covers for him."
)
COMPARATOR_PERSONA = PersonaProfile(
    name="Detective Somchai", traits=["stubborn", "lonely", "relentless"]
)


def default_corpus() -> ComparatorCorpus:
    return ComparatorCorpus(scenes=[COMPARATOR_SCENE], personas=[COMPARATOR_PERSONA])


def default_concepts() -> list[ConceptDraft]:
    """Two original concepts; the first ranks ahead (more theme support)."""
    base = season_scope()
    first = base.model_copy(
        update={
            "title_en": "River of Small Debts",
            "logline": "A young cook must save her aunt's noodle boat before the river rises.",
            "premise": "Original fiction about inheritance, pride and slow forgiveness.",
        }
    )
    second = base.model_copy(
        update={
            "title_en": "The Quiet Photographer",
            "logline": "A shy photographer documents a night market's last season.",
            "premise": "Original fiction about memory, gentrification and courage.",
        }
    )
    return [
        ConceptDraft(concept_id="concept-a", theme_keys=["thai", "drama"], scope=first),
        ConceptDraft(concept_id="concept-b", theme_keys=["drama"], scope=second),
    ]


def request(
    *,
    key: str = DEFAULT_KEY,
    trigger: ResearchTrigger = ResearchTrigger.SCHEDULED,
    queries: tuple[str, ...] = ("thai micro drama family trends",),
    source_ids: tuple[str, ...] = DEFAULT_SOURCES,
    provider_id: str = "fake-sources",
    comments: tuple[CommentIn, ...] = (),
    corpus: ComparatorCorpus | None = None,
    concepts: list[ConceptDraft] | None = None,
) -> ResearchRequest:
    return ResearchRequest(
        trigger=trigger,
        trigger_key=key,
        source_provider_id=provider_id,
        allowed_source_ids=list(source_ids),
        query_texts=list(queries),
        comments=list(comments),
        comparator_corpus=corpus if corpus is not None else default_corpus(),
        candidate_concepts=concepts if concepts is not None else default_concepts(),
    )


class World:
    """One research service wired to the real database and the T007 fakes."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("research-tests")
        self.budget = BudgetService(db, self.clock, SequentialIds("research-budget"), settings)
        self.sources = FakeSourceProvider(clock=self.clock, ids=SequentialIds("research-sources"))
        self.llm = FakeLLMProvider(clock=self.clock, ids=SequentialIds("research-llm"))
        self.service: ResearchService = build_research_service(
            db,
            self.clock,
            self.ids,
            settings,
            budget=self.budget,
            source_providers={"fake-sources": self.sources},
            llm=self.llm,
        )

    # --- seeds -----------------------------------------------------------------------

    def season(self, *, envelope: int | None = ENVELOPE, state: str = "PROPOSED") -> uuid.UUID:
        with self.db.transaction() as tx:
            season_id = seed_season(tx, state=state)
            if envelope is not None:
                self.budget.open_research_account(
                    tx, season_id=season_id, envelope_micro_usd=envelope
                )
        return season_id

    # --- reads -----------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def run_row(self, season_id: uuid.UUID, key: str = DEFAULT_KEY) -> dict[str, Any] | None:
        return self.row(
            "SELECT * FROM research_runs WHERE season_id = %s AND semantic_key = %s",
            (season_id, key),
        )

    def account(self, season_id: uuid.UUID) -> dict[str, Any]:
        row = self.row(
            "SELECT * FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
            (season_id,),
        )
        assert row is not None
        return row

    def committed(self, season_id: uuid.UUID) -> int:
        acct = self.account(season_id)
        return (
            acct["reserved_outstanding_micro_usd"]
            + acct["accrued_micro_usd"]
            + acct["settled_micro_usd"]
        )

    def reservations(self, season_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM reservations WHERE season_id = %s ORDER BY created_at, id",
            (season_id,),
        )

    def proposals(self, season_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM season_proposals WHERE season_id = %s ORDER BY scope_version",
            (season_id,),
        )


__all__ = [
    "COMPARATOR_PERSONA",
    "COMPARATOR_SCENE",
    "DEFAULT_KEY",
    "DEFAULT_SOURCES",
    "ENVELOPE",
    "T0",
    "World",
    "default_concepts",
    "default_corpus",
    "request",
]

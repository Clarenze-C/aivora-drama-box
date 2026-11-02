"""T044b2 composed owner path: three-step intake → bounded candidates+research → selection → Gate 1.

The whole owner Script Maker chain offline over real PostgreSQL with the T007
fakes: the owner submits only the three wizard answers, one durable job runs
candidate generation and the bounded research run behind the configured
envelope, the owner selects a candidate (rebinding the current Gate 1 proposal
to that exact scope hash), the existing Gate 1 stays the single human decision,
and retries/restarts add no duplicate season, candidate, reservation, proposal
or approval rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import (
    ApprovalAction,
    GateType,
    PrincipalKind,
    RuntimeRole,
)
from microdrama.contracts.examples import season_scope
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobContext, JobService, Succeeded
from microdrama.persistence import Database
from microdrama.pipeline.mocks import MOCK_COMPARATOR_SCENE, MOCK_SOURCES
from microdrama.research import (
    ComparatorCorpus,
    ResearchService,
    build_research_service,
    build_script_maker_service,
)
from microdrama.review import IntakeConfig, IntakeService, ReviewService
from microdrama.review.intake import INTAKE_JOB_TYPE, intake_record_id
from microdrama.story import build_story_service
from microdrama.testing.fakes import (
    FakeClock,
    FakeLLMProvider,
    FakeSourceProvider,
    SequentialIds,
)
from microdrama.testing.seed import seed_human_session, seed_owner

pytestmark = [pytest.mark.db]

T0 = datetime(2026, 10, 30, tzinfo=UTC)
EPISODES = 5
ENVELOPE = 2_000_000
IDEA = "ครอบครัวพยายามรักษาร้านอาหารเล็ก ๆ ของแม่จากหนี้ที่ไม่มีใครเคยพูดถึง"
TONE = "อบอุ่นแต่มีความลุ้น"


def _candidate_payload(title_th: str, title_en: str) -> dict[str, Any]:
    """Two materially distinct original candidates, Thai beats, one per episode."""

    def one(title_th: str, title_en: str) -> dict[str, Any]:
        return {
            "title_th": title_th,
            "title_en": title_en,
            "logline": f"An original season about {title_en.lower()} told in Thai.",
            "premise": "เรื่องเดิมที่แต่งขึ้นใหม่ทั้งหมดเกี่ยวกับครอบครัวและร้านอาหารของแม่",
            "genre_tags": ["family-drama"],
            "originality_statement": "Original fiction; no real persons or existing works imitated.",
            "arc": [
                {
                    "episode_number": episode,
                    "summary": f"จุดเปลี่ยนของเรื่องตอนที่ {episode}",
                    "planned_reveals": ["ความลับที่วางแผนไว้"] if episode == 2 else [],
                    "cliffhanger": "ใครบางคนมาถึง" if episode == EPISODES else None,
                }
                for episode in range(1, EPISODES + 1)
            ],
            "characters": [
                {
                    "character_id": "fon",
                    "name_th": "ฝน",
                    "name_en": "Fon",
                    "role": "daughter",
                    "description": "A resourceful daughter.",
                    "voice_direction": "Warm, quick delivery.",
                    "featured": True,
                },
                {
                    "character_id": "lek",
                    "name_th": "ลุงเล็ก",
                    "name_en": "Uncle Lek",
                    "role": "cook",
                    "description": "The stall cook hiding guilt.",
                    "voice_direction": "Low, gentle.",
                    "featured": True,
                },
            ],
        }

    return {
        "candidates": [
            one("ตลาดสุดท้าย", "The Last Market"),
            one("ร้านของลุงเล็ก", "Uncle Lek's Shop"),
        ]
    }


class OwnerPath:
    """The composed owner-intake world: fake providers, real services, one database."""

    def __init__(self, db: Database, settings: Settings, store: ObjectStore) -> None:
        self.db = db
        self.settings = settings
        self.store = store
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("t044b2")
        self.jobs = JobService(db, self.clock, self.ids)
        self.idempotency = IdempotencyService(db)
        self.budget = BudgetService(db, self.clock, SequentialIds("t044b2-budget"), settings)
        self.llm = FakeLLMProvider(clock=self.clock, ids=SequentialIds("t044b2-llm"))
        self.sources = FakeSourceProvider(clock=self.clock, ids=SequentialIds("t044b2-src"))
        self.script_maker = build_script_maker_service(
            self.clock, settings, budget=self.budget, llm=self.llm
        )
        self.research: ResearchService = build_research_service(
            db,
            self.clock,
            self.ids,
            settings,
            budget=self.budget,
            source_providers={"fake-sources": self.sources},
            llm=self.llm,
        )
        self.intake = IntakeService(
            db,
            self.clock,
            self.ids,
            settings,
            jobs=self.jobs,
            idempotency=self.idempotency,
            budget=self.budget,
            script_maker=self.script_maker,
            research=self.research,
            config=IntakeConfig(
                research_envelope_micro_usd=ENVELOPE,
                allowed_source_ids=tuple(MOCK_SOURCES),
                comparator_corpus=ComparatorCorpus(scenes=[MOCK_COMPARATOR_SCENE]),
                scope_template=season_scope(),
            ),
        )
        self.review = ReviewService(
            db,
            self.clock,
            self.ids,
            jobs=self.jobs,
            idempotency=self.idempotency,
            budget=self.budget,
            store=store,
            release_conditions_fn=lambda tx, episode_row, package: [],
            approval_hooks=[],
        )
        self._owner_id: uuid.UUID | None = None

    def owner_id(self) -> uuid.UUID:
        if self._owner_id is None:
            with self.db.transaction() as tx:
                self._owner_id = seed_owner(tx)
        return self._owner_id

    def human(self) -> Principal:
        owner = self.owner_id()
        with self.db.transaction() as tx:
            session = seed_human_session(tx, owner)
        return Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )

    def submit_intake(self, *, episode_count: int = EPISODES, key: str = "wizard-key-1"):
        from microdrama.review.intake import IntakeAnswers

        return self.intake.submit(
            self.human(),
            answers=IntakeAnswers(
                story_idea=IDEA,
                genre_tags=("family-drama",),
                tone=TONE,
                episode_count=episode_count,
            ),
            key=key,
        )

    def drain_intake_jobs(self) -> int:
        """Claim, run and finish every queued intake job like a worker deployment."""

        ran = 0
        while True:
            job = self.jobs.claim("production", worker_id="t044b2-worker", lease_ms=60_000)
            if job is None:
                break
            assert job.job_type == INTAKE_JOB_TYPE
            context = self.jobs.context(job, "t044b2-worker")
            outcome = self.intake.handle_research_job(context)
            assert outcome is not None
            self.jobs.finish(job.id, worker_id="t044b2-worker", outcome=outcome)
            ran += 1
        return ran

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def committed_research(self, season_id: uuid.UUID) -> int:
        row = self.row(
            "SELECT reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd "
            "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
            (season_id,),
        )
        assert row is not None
        return (
            row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"]
        )

    def current_candidate_docs(self, intake_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.row_all(
            "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = 'ConceptCandidate' AND current "
            "AND payload->>'intake_id' = %s ORDER BY payload->>'title_en'",
            (str(intake_id),),
        )

    def row_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)


def test_owner_intake_to_gate1_with_selection_rebinding(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _candidate_payload("a", "b"))

    # --- the owner submits only the three answers; one durable job is dispatched ---------
    ack = world.submit_intake()
    assert ack.status_code == 202 and ack.body["status"] == "QUEUED"
    season_id = uuid.UUID(ack.body["season_id"])
    intake_id = uuid.UUID(ack.body["intake_id"])
    assert intake_id == intake_record_id(season_id)
    assert world.count("SELECT COUNT(*) FROM jobs WHERE job_type = %s", (INTAKE_JOB_TYPE,)) == 1
    assert world.committed_research(season_id) == 0, "dispatch alone spends nothing"

    # --- the bounded candidate+research job reaches a current Gate 1 proposal ------------
    assert world.drain_intake_jobs() == 1
    view = world.intake.status(world.human(), season_id)
    assert view.phase == "CANDIDATES_READY"
    assert len(view.candidates) == 2
    assert all(card.rights_status == "PENDING" for card in view.candidates)
    assert all(card.originality_status == "CLEAR" for card in view.candidates)
    assert view.proposal_id is not None and view.proposal_status == "PROPOSED"
    research_chosen = next(card for card in view.candidates if card.is_current_proposal)
    other = next(card for card in view.candidates if not card.is_current_proposal)
    spend_after_first = world.committed_research(season_id)
    assert spend_after_first > 0
    proposal = world.row(
        "SELECT scope_hash, scope_version, status FROM season_proposals WHERE id = %s",
        (view.proposal_id,),
    )
    assert proposal["scope_hash"] == research_chosen.scope_sha256
    assert (
        world.count(
            "SELECT COUNT(*) FROM reservations WHERE season_id = %s AND state = 'ACTIVE'",
            (season_id,),
        )
        == 0
    ), "the bounded run leaves nothing held"

    # --- the owner selects the OTHER candidate: the proposal rebinds to that exact hash ---
    selection = world.intake.select(
        world.human(), season_id, other.record_id, intake_sha256=view.intake_sha256
    )
    assert selection.status_code == 202 and selection.body["status"] == "QUEUED"
    assert world.drain_intake_jobs() == 1
    view2 = world.intake.status(world.human(), season_id)
    assert view2.proposal_id is not None and view2.proposal_id != view.proposal_id
    proposal2 = world.row(
        "SELECT scope, scope_hash, scope_version, status FROM season_proposals WHERE id = %s",
        (view2.proposal_id,),
    )
    assert proposal2["scope_version"] == proposal["scope_version"] + 1
    # The persisted proposal IS the selected candidate's concept, and the
    # candidate document is rebound to the exact persisted scope hash.
    assert proposal2["scope"]["title_th"] == other.title_th
    assert proposal2["scope"]["title_en"] == other.title_en
    assert proposal2["scope"]["expected_episode_count"] == other.episode_count
    selected_card = next(card for card in view2.candidates if card.record_id == other.record_id)
    assert selected_card.scope_sha256 == proposal2["scope_hash"]
    assert selected_card.is_current_proposal
    other_doc = next(
        doc
        for doc in world.current_candidate_docs(intake_id)
        if doc["record_id"] == other.record_id
    )
    assert other_doc["payload"]["scope_sha256"] == proposal2["scope_hash"]
    assert other_doc["version"] >= 2, "the selected candidate is rebound to the proposal hash"

    # --- retry/restart before the gate: replays change nothing ----------------------------
    spend_before_replay = world.committed_research(season_id)
    candidate_rows_before = world.count(
        "SELECT COUNT(*) FROM v2_contract_documents WHERE contract_type = 'ConceptCandidate'"
    )
    replay = world.submit_intake()
    assert replay.replayed and replay.body["season_id"] == str(season_id)
    assert world.count("SELECT COUNT(*) FROM seasons") == 1
    # A worker crash-and-retry of the intake job AFTER the selection already ran
    # is the stale-replay shape: generation and the intake research run replay,
    # nothing is re-spent, and the live proposal binding is never un-bound.
    from microdrama.contracts.jobs import SeasonStepInput

    intake_job = world.jobs.get(uuid.UUID(ack.body["job_id"]))
    replay_job = world.intake.handle_research_job(
        JobContext(
            intake_job,
            "t044b2-worker",
            SeasonStepInput.model_validate(intake_job.input),
        )
    )
    assert isinstance(replay_job, Succeeded)
    assert replay_job.result["proposal_id"] == str(view.proposal_id), "the intake run replays"
    assert world.committed_research(season_id) == spend_before_replay, "replays add no spend"
    assert (
        world.count("SELECT COUNT(*) FROM research_runs WHERE season_id = %s", (season_id,)) == 2
    ), "the intake run and the selection run, nothing more"
    assert (
        world.count("SELECT COUNT(*) FROM season_proposals WHERE season_id = %s", (season_id,)) == 2
    ), "no duplicate proposal rows from replays"
    assert (
        world.count(
            "SELECT COUNT(*) FROM v2_contract_documents WHERE contract_type = 'ConceptCandidate'"
        )
        == candidate_rows_before
    ), "a stale replay appends no candidate versions"
    still_bound = next(
        doc
        for doc in world.current_candidate_docs(intake_id)
        if doc["record_id"] == other.record_id
    )
    assert still_bound["payload"]["scope_sha256"] == proposal2["scope_hash"]
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (season_id,)) == 0
    ), "silence still approves nothing"

    # --- Gate 1: the existing human gate binds the chosen candidate hash ------------------
    revision = world.row("SELECT revision FROM seasons WHERE id = %s", (season_id,))["revision"]
    decision = world.review.decide_season(
        world.human(),
        season_id,
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=revision,
            package_hash=proposal2["scope_hash"],
            idempotency_key="gate1-t044b2-1",
        ),
    )
    assert decision.status_code == 202
    assert world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == (
        "SEASON_APPROVED"
    )
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (season_id,)) == 1
    ), "the wizard adds no second human decision"
    # Post-Gate-1 the season compiles through the existing T039 path, and no
    # further intake work can be dispatched for a decided season.
    compiled = build_story_service(
        db,
        world.clock,
        world.ids,
        offline_settings,
        budget=world.budget,
        llm=world.llm,
    ).compile_season(season_id)
    assert compiled.bible.approved_scope_hash == proposal2["scope_hash"]
    decided_replay = world.intake.handle_research_job(
        JobContext(
            intake_job,
            "t044b2-worker",
            SeasonStepInput.model_validate(intake_job.input),
        )
    )
    from microdrama.core.jobs import Failed as JobFailed

    assert isinstance(decided_replay, JobFailed)
    assert decided_replay.error_code == "INTAKE_SEASON_NOT_PROPOSED"


def test_reselecting_the_proposed_candidate_is_a_replay_not_new_spend(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _candidate_payload("a", "b"))
    ack = world.submit_intake(key="wizard-key-2")
    season_id = uuid.UUID(ack.body["season_id"])
    world.drain_intake_jobs()
    view = world.intake.status(world.human(), season_id)
    current = next(card for card in view.candidates if card.is_current_proposal)
    spend = world.committed_research(season_id)

    again = world.intake.select(
        world.human(), season_id, current.record_id, intake_sha256=view.intake_sha256
    )
    assert again.status_code == 200 and again.body["status"] == "REPLAYED"
    assert again.body["job_id"] is None
    assert world.count("SELECT COUNT(*) FROM jobs") == 1, "no new job for the same selection"
    assert world.committed_research(season_id) == spend
    # A stale intake hash is refused typed.
    from microdrama.contracts.errors import StaleRevision

    with pytest.raises(StaleRevision):
        world.intake.select(
            world.human(),
            season_id,
            current.record_id,
            intake_sha256="0" * 64,
        )


def test_selection_after_gate1_is_refused(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    from microdrama.contracts.errors import InvalidTransition
    from microdrama.contracts.season import ApprovalCommand

    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _candidate_payload("a", "b"))
    ack = world.submit_intake(key="wizard-key-3")
    season_id = uuid.UUID(ack.body["season_id"])
    world.drain_intake_jobs()
    view = world.intake.status(world.human(), season_id)
    current = next(card for card in view.candidates if card.is_current_proposal)
    revision = world.row("SELECT revision FROM seasons WHERE id = %s", (season_id,))["revision"]
    world.review.decide_season(
        world.human(),
        season_id,
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=revision,
            package_hash=view.proposal_scope_hash,
            idempotency_key="gate1-t044b2-3",
        ),
    )
    with pytest.raises(InvalidTransition):
        world.intake.select(
            world.human(),
            season_id,
            current.record_id,
            intake_sha256=view.intake_sha256,
        )
    assert world.count("SELECT COUNT(*) FROM jobs WHERE job_type = %s", (INTAKE_JOB_TYPE,)) == 1, (
        "no post-gate selection dispatch"
    )


def test_scope_template_policy_is_preserved_not_browser_chosen(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    """The generated scopes carry the configured default policy byte for byte."""
    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _candidate_payload("a", "b"))
    ack = world.submit_intake(key="wizard-key-4")
    season_id = uuid.UUID(ack.body["season_id"])
    world.drain_intake_jobs()
    view = world.intake.status(world.human(), season_id)
    proposal = world.row("SELECT scope FROM season_proposals WHERE id = %s", (view.proposal_id,))
    template = season_scope()
    scope = proposal["scope"]
    assert scope["creative_constraints"]["original_fiction_only"] is True
    assert scope["creative_constraints"]["retain_thai_performances"] is True
    assert scope["cost_policy"] == template.cost_policy.model_dump(mode="json")
    assert scope["destinations"] == [d.model_dump(mode="json") for d in template.destinations]
    assert scope["management_policy"] == template.management_policy.model_dump(mode="json")
    assert 180_000 <= scope["episode_min_duration_ms"]
    assert scope["episode_max_duration_ms"] <= 300_000
    assert scope["expected_episode_count"] == EPISODES
    assert f"Tone: {TONE}" in scope["creative_constraints"]["style_rules"]


def test_reselecting_after_another_selection_reruns_the_candidate(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    """F1 (review fix): selecting B, then A, then B again must RE-RUN B.

    The old behavior replayed B's first completed job (semantic key and research
    trigger key named only the candidate), so the current Gate 1 proposal stayed
    on A and the owner's latest choice silently lost. Every selection intent now
    carries a durable revision in both keys; a double-click while the run is
    still queued dedupes to that same job. The third selection REPEATS an
    earlier selection target (B again after A), which is the shape the
    candidate-only key could not survive (DB-1).
    """
    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, _candidate_payload("a", "b"))
    ack = world.submit_intake(key="wizard-key-bab")
    season_id = uuid.UUID(ack.body["season_id"])
    world.drain_intake_jobs()
    view = world.intake.status(world.human(), season_id)
    first = next(card for card in view.candidates if card.is_current_proposal)
    second = next(card for card in view.candidates if not card.is_current_proposal)
    first_title = first.title_en

    # Select the candidate the current proposal does NOT bind, and let it run.
    switched_ack = world.intake.select(
        world.human(), season_id, second.record_id, intake_sha256=view.intake_sha256
    )
    assert switched_ack.status_code == 202
    world.drain_intake_jobs()
    switched = world.intake.status(world.human(), season_id)
    rebound_second = next(
        card for card in switched.candidates if card.record_id == second.record_id
    )
    assert switched.proposal_scope_hash == rebound_second.scope_sha256
    switched_proposal = world.row(
        "SELECT scope FROM season_proposals WHERE id = %s", (switched.proposal_id,)
    )
    assert switched_proposal["scope"]["title_en"] == second.title_en

    # Switch BACK to the first candidate: this must be a NEW bounded run, never
    # a replay of that candidate's old completed job.
    back = world.intake.select(
        world.human(), season_id, first.record_id, intake_sha256=switched.intake_sha256
    )
    assert back.status_code == 202 and back.body["status"] == "QUEUED"
    # A double-click while the switched-back run is still queued dedupes to it.
    double = world.intake.select(
        world.human(), season_id, first.record_id, intake_sha256=switched.intake_sha256
    )
    assert double.status_code == 200 and double.replayed
    assert double.body["job_id"] == back.body["job_id"]
    assert world.count("SELECT COUNT(*) FROM jobs") == 3, "intake + two selection intents only"

    assert world.drain_intake_jobs() == 1
    final = world.intake.status(world.human(), season_id)
    final_proposal = world.row(
        "SELECT scope, scope_hash FROM season_proposals WHERE id = %s", (final.proposal_id,)
    )
    assert final_proposal["scope"]["title_en"] == first_title, "the latest selection wins"
    rebound = next(card for card in final.candidates if card.record_id == first.record_id)
    assert rebound.is_current_proposal
    assert final.proposal_scope_hash == rebound.scope_sha256

    # Select B A SECOND TIME: this third selection repeats an earlier selection
    # target, so a candidate-only key would replay B's first COMPLETED job
    # instead of running a new bounded intent (the DB-1 shape). It must be a
    # brand-new job with a new revision in both keys.
    after_a = world.intake.status(world.human(), season_id)
    again = world.intake.select(
        world.human(), season_id, second.record_id, intake_sha256=after_a.intake_sha256
    )
    assert again.status_code == 202 and again.body["status"] == "QUEUED"
    assert again.body["job_id"] != switched_ack.body["job_id"], (
        "re-selecting B is a NEW job, never a replay of B's first completed job"
    )
    assert world.count("SELECT COUNT(*) FROM jobs") == 4, "intake + three selection intents"
    assert world.drain_intake_jobs() == 1
    end = world.intake.status(world.human(), season_id)
    end_proposal = world.row(
        "SELECT scope, scope_hash FROM season_proposals WHERE id = %s", (end.proposal_id,)
    )
    assert end_proposal["scope"]["title_en"] == second.title_en, "the latest selection (B) wins"
    end_card = next(card for card in end.candidates if card.record_id == second.record_id)
    assert end_card.is_current_proposal
    assert end.proposal_scope_hash == end_card.scope_sha256
    assert (
        world.count("SELECT COUNT(*) FROM research_runs WHERE season_id = %s", (season_id,)) == 4
    ), "the intake run plus one bounded run per distinct selection intent"

    # Every selection intent is a distinct revision in BOTH keys: the job
    # semantic keys and the research run trigger keys never collide pairwise.
    job_keys = [
        str(row["semantic_key"])
        for row in world.row_all(
            "SELECT semantic_key FROM jobs WHERE season_id = %s AND job_type = %s"
            " AND starts_with(input->>'trigger', 'owner_selection.')",
            (season_id, INTAKE_JOB_TYPE),
        )
    ]
    assert len(job_keys) == 3 and len(set(job_keys)) == 3, (
        f"selection job semantic keys must all differ: {sorted(job_keys)}"
    )
    run_keys = [
        str(row["semantic_key"])
        for row in world.row_all(
            "SELECT semantic_key FROM research_runs WHERE season_id = %s", (season_id,)
        )
    ]
    assert len(run_keys) == 4 and len(set(run_keys)) == 4, (
        f"research trigger keys must all differ: {sorted(run_keys)}"
    )


def test_stale_selection_job_is_superseded_by_a_newer_intent(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    """DB-9: a stale selection job completing after a newer selection changes nothing.

    The owner selects X, then selects Y before any run starts (three candidates:
    the initially-bound one can never be re-selected while its proposal stands,
    so a real stale/newer pair needs two unbound candidates). A worker runs
    Y's job (the newest intent) and only then picks up X's older queued job —
    e.g. after a restart or a lease handoff. X's job must recognize it was
    superseded (a higher-revision selection job exists for the season), return
    a typed superseded outcome, spend nothing on research, and leave the
    current Gate 1 proposal on Y.
    """
    payload = _candidate_payload("x", "y")
    payload["candidates"].append(
        {
            **payload["candidates"][1],
            "title_th": "บันทึกฉบับที่สาม",
            "title_en": "The Third Draft",
            "logline": "An original season about the third draft told in Thai.",
        }
    )
    world = OwnerPath(db, offline_settings, object_store)
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, payload)
    ack = world.submit_intake(key="wizard-key-superseded")
    season_id = uuid.UUID(ack.body["season_id"])
    assert world.drain_intake_jobs() == 1
    view = world.intake.status(world.human(), season_id)
    bound = next(card for card in view.candidates if card.is_current_proposal)
    unbound = [card for card in view.candidates if not card.is_current_proposal]
    assert len(unbound) == 2
    stale_card, newest_card = unbound[0], unbound[1]

    # Select X (revision 1), then Y (revision 2) — two real selection jobs, neither run.
    select_x = world.intake.select(
        world.human(), season_id, stale_card.record_id, intake_sha256=view.intake_sha256
    )
    assert select_x.status_code == 202
    select_y = world.intake.select(
        world.human(), season_id, newest_card.record_id, intake_sha256=view.intake_sha256
    )
    assert select_y.status_code == 202

    # Claim in FIFO order (X's job first); run Y's job, then X's stale job.
    claimed_x = world.jobs.claim("production", worker_id="t044b2-worker", lease_ms=60_000)
    claimed_y = world.jobs.claim("production", worker_id="t044b2-worker", lease_ms=60_000)
    assert claimed_x is not None and claimed_y is not None
    assert str(claimed_x.input["trigger"]).endswith(str(stale_card.record_id))
    assert str(claimed_y.input["trigger"]).endswith(str(newest_card.record_id))

    def _run(job) -> object:
        context = world.jobs.context(job, "t044b2-worker")
        outcome = world.intake.handle_research_job(context)
        assert outcome is not None
        world.jobs.finish(job.id, worker_id="t044b2-worker", outcome=outcome)
        return outcome

    _run(claimed_y)  # the newest intent runs first: the proposal moves to Y
    on_y = world.intake.status(world.human(), season_id)
    assert on_y.proposal_id is not None
    y_proposal = world.row("SELECT scope FROM season_proposals WHERE id = %s", (on_y.proposal_id,))
    assert y_proposal["scope"]["title_en"] == newest_card.title_en

    stale_outcome = _run(claimed_x)  # X's job completes AFTER the newer selection
    assert isinstance(stale_outcome, Succeeded), "the stale job is a typed superseded result"
    assert stale_outcome.result["status"] == "SUPERSEDED"
    assert int(stale_outcome.result["superseded_by_revision"]) == 2
    assert stale_outcome.result.get("research_run_id") is None, "a superseded job spends nothing"

    final = world.intake.status(world.human(), season_id)
    final_proposal = world.row(
        "SELECT scope FROM season_proposals WHERE id = %s", (final.proposal_id,)
    )
    assert final_proposal["scope"]["title_en"] == newest_card.title_en, "the proposal stays on Y"
    y_card = next(card for card in final.candidates if card.record_id == newest_card.record_id)
    assert y_card.is_current_proposal
    stale_card_after = next(
        card for card in final.candidates if card.record_id == stale_card.record_id
    )
    assert not stale_card_after.is_current_proposal
    assert bound is not None  # the initially-bound candidate stays a plain card
    assert (
        world.count("SELECT COUNT(*) FROM research_runs WHERE season_id = %s", (season_id,)) == 2
    ), "only the intake run and Y's bounded run ever reach research"

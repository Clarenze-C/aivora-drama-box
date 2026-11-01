"""T039 composed acceptance: short owner idea -> Gate 1 -> rich bible -> episode packs.

The whole Script Maker chain offline over real PostgreSQL with the T007 fakes: the owner
never writes a ``SeasonScope``, candidate generation and the bounded research run share
one season research envelope, the chosen candidate binds to the exact persisted
provenance-stamped proposal scope hash, Gate 1 stays the single human decision before
production, the post-gate rich bible and the first-three/later packs honour reveal
timing, Thai form and the 180-300 s band, and replays of a finished generation cost
nothing extra.
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
from microdrama.contracts.errors import InvalidTransition
from microdrama.contracts.examples import season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.principals import Principal
from microdrama.contracts.season import ApprovalCommand
from microdrama.contracts.v2 import ConceptIntake, PendingRightsAssessment
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence import Database
from microdrama.research import (
    ComparatorCorpus,
    ConceptDraft,
    ResearchRequest,
    ResearchService,
    ResearchTrigger,
    build_research_service,
    build_script_maker_service,
)
from microdrama.review.service import ReviewService
from microdrama.story import (
    StoryService,
    build_script_maker_story_service,
    build_story_service,
)
from microdrama.story.script_maker import CandidateScopeBinding, first_three_and_later_map
from microdrama.testing.fakes import (
    FakeClock,
    FakeLLMProvider,
    FakeSourceProvider,
    SequentialIds,
)
from microdrama.testing.seed import (
    seed_episode,
    seed_human_session,
    seed_owner,
    seed_season,
)

pytestmark = [pytest.mark.db]

T0 = datetime(2026, 10, 30, tzinfo=UTC)
EPISODES = 5
ENVELOPE = 2_000_000
COMPARATOR_SCENE = (
    "A retired detective hunts a kidnapping syndicate through the flooded alleys of old "
    "Bangkok while his former partner covers for him."
)
SECRET_LETTER_FACT = "จดหมายที่แม่ซ่อนไว้เผยว่าลุงเล็กเป็นคนค้ำประกันเงินกู้ทั้งก้อน"
SECRET_ORDERS_FACT = "คำสั่งเรียกหนี้ทั้งหมดมาจากบริษัทแม่ของนก ไม่ใช่เจ้าหนี้ภายนอก"


def _candidate(title_th: str, title_en: str) -> dict[str, Any]:
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
            {
                "character_id": "nok",
                "name_th": "นก",
                "name_en": "Nok",
                "role": "collector",
                "description": "A polite, relentless collector.",
                "voice_direction": "Even, formal.",
                "featured": False,
            },
        ],
    }


def _bible_output(cast: list[Any]) -> dict[str, Any]:
    ids = [character.character_id for character in cast]
    knowledge = {
        "fon": {"2": ["mother-letter"]},
        "lek": {"2": ["mother-letter"]},
        "nok": {"5": ["collector-orders"]},
    }
    return {
        "characters": [
            {
                "character_id": character_id,
                "observable_goal": "Keep the stall open.",
                "strategy": "Find the truth before the deadline.",
                "flaw": "Hides worry from family.",
                "secret_id": {
                    "fon": "mother-letter",
                    "lek": "mother-letter",
                    "nok": ("collector-orders"),
                }[character_id],
                "relationship_pressures": ["A family promise is at risk."],
                "knowledge_by_episode": knowledge[character_id],
            }
            for character_id in ids
        ],
        "secrets": [
            {
                "secret_id": "mother-letter",
                "held_by_character_id": "lek",
                "fact": SECRET_LETTER_FACT,
                "planned_reveal_episode": 2,
                "known_by_character_ids": ["fon", "lek"],
            },
            {
                "secret_id": "collector-orders",
                "held_by_character_id": "nok",
                "fact": SECRET_ORDERS_FACT,
                "planned_reveal_episode": 5,
                "known_by_character_ids": ["nok"],
            },
        ],
        "promise": "ครอบครัวหนึ่งปกป้องร้านของแม่จากหนี้ที่ซ่อนอยู่",
        "payoff_debts": [
            {
                "debt_id": "stall-debt",
                "description": "ปิดจบหนี้ของร้านและความลับทั้งหมด",
                "due_episode": EPISODES,
                "status": "OPEN",
            }
        ],
        "escalations": [
            {"episode_number": episode, "description": f"บททดสอบของตอนที่ {episode}"}
            for episode in range(1, EPISODES + 1)
        ],
    }


def _pack_output(episode_number: int, asset_id: uuid.UUID) -> dict[str, Any]:
    return {
        "episode_number": episode_number,
        "duration_target_ms": 240_000,
        "promise": "ครอบครัวอาจรอดจากหนี้ครั้งนี้",
        "payoff_debt": ["ใครเป็นเจ้าของหนี้จริง"],
        "escalation": "เวลาของครอบครัวเดินแรงขึ้น",
        "scenes": [
            {
                "scene_id": f"scene-{episode_number}",
                "scene_number": 1,
                "story_time": {
                    "story_day": episode_number,
                    "local_time": "10:00",
                    "setting": "stall",
                    "timezone": "Asia/Bangkok",
                },
                "location_id": "stall",
                "visible_character_ids": ["fon", "lek", "nok"],
                "prop_ids": ["letter"],
                "dependency_scene_ids": [],
                "wardrobe_assignment_ids": [],
                "state_in": [],
                "state_out": [],
                "beats": [
                    {
                        "beat_id": f"beat-{episode_number}",
                        "function": "escalation",
                        "visible_action": "ฝนเก็บจดหมายที่ยังไม่เปิดไว้ใต้เครื่องนับเงิน",
                        "proof_object_ids": ["letter"],
                        "dependency_beat_ids": [],
                        "state_in": [],
                        "state_out": [],
                        "required_asset_ids": [str(asset_id)],
                        "reveal_ids": [],
                    }
                ],
            }
        ],
    }


class Compose:
    """Every T039 service wired to one database, budget, clock and fake providers."""

    def __init__(self, db: Database, settings: Settings, store: ObjectStore) -> None:
        self.db = db
        self.settings = settings
        self._owner_id: uuid.UUID | None = None
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("t039")
        self.budget = BudgetService(db, self.clock, SequentialIds("t039-budget"), settings)
        self.sources = FakeSourceProvider(clock=self.clock, ids=SequentialIds("t039-sources"))
        self.llm = FakeLLMProvider(clock=self.clock, ids=SequentialIds("t039-llm"))
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
        self.story: StoryService = build_story_service(
            db, self.clock, self.ids, settings, budget=self.budget, llm=self.llm
        )
        self.story_maker = build_script_maker_story_service(
            db, self.clock, settings, budget=self.budget, llm=self.llm
        )
        self.review = ReviewService(
            db,
            self.clock,
            self.ids,
            jobs=JobService(db, self.clock, self.ids),
            idempotency=IdempotencyService(db),
            budget=self.budget,
            store=store,
            release_conditions_fn=lambda tx, episode_row, package: [],
            approval_hooks=[],
        )

    # --- seeds -----------------------------------------------------------------------

    def owner_id(self) -> uuid.UUID:
        """The canonical owner the compose path acts as (created lazily)."""
        if self._owner_id is None:
            with self.db.transaction() as tx:
                self._owner_id = seed_owner(tx)
        return self._owner_id

    def proposed_season(self) -> uuid.UUID:
        with self.db.transaction() as tx:
            season_id = seed_season(tx, state="PROPOSED", owner_id=self.owner_id())
            self.budget.open_research_account(tx, season_id=season_id, envelope_micro_usd=ENVELOPE)
        return season_id

    def intake(self) -> ConceptIntake:
        return ConceptIntake.seal(
            record_id=uuid.uuid4(),
            version=1,
            created_at=T0,
            updated_at=T0,
            valid_from=T0,
            story_idea="ครอบครัวพยายามรักษาร้านอาหารเล็ก ๆ ของแม่จากหนี้ที่ไม่มีใครเคยพูดถึง",
            genre_tags=["family-drama"],
            tone="อบอุ่นแต่มีความลุ้น",
            requested_episode_count=EPISODES,
        )

    def human(self) -> Principal:
        owner = self.owner_id()
        with self.db.transaction() as tx:
            session = seed_human_session(tx, owner)
        return Principal(
            principal_id=f"owner:{owner}",
            kind=PrincipalKind.HUMAN_OWNER,
            session_id=session,
        )

    def episodes(self, season_id: uuid.UUID, scope: Any) -> list[uuid.UUID]:
        """Seed the season's episodes and open each one's budget account."""
        ids: list[uuid.UUID] = []
        scope_hash = canonical_hash(scope)
        with self.db.transaction() as tx:
            for number in range(1, EPISODES + 1):
                episode_id = seed_episode(tx, season_id, number=number, state="PLANNED")
                tx.execute(
                    "UPDATE episodes SET approved_scope_hash = %s WHERE id = %s",
                    (scope_hash, episode_id),
                )
                self.budget.open_episode_account(
                    tx,
                    season_id=season_id,
                    episode_id=episode_id,
                    policy=scope.cost_policy,
                )
                ids.append(episode_id)
        return ids

    # --- reads -----------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def committed(
        self, *, season_id: uuid.UUID | None = None, episode_id: uuid.UUID | None = None
    ) -> int:
        if season_id is not None:
            row = self.row(
                "SELECT reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd "
                "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
                (season_id,),
            )
        else:
            row = self.row(
                "SELECT reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd "
                "FROM budget_accounts WHERE scope_kind = 'EPISODE' AND episode_id = %s",
                (episode_id,),
            )
        assert row is not None
        return (
            row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"]
        )


def test_short_idea_reaches_gate1_and_builds_packs_without_a_handwritten_scope(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    world = Compose(db, offline_settings, object_store)
    season_id = world.proposed_season()
    owner_intake = world.intake()

    # --- the owner submits only an idea, genre/tone and an episode count ----------------
    world.llm.script_role(
        RuntimeRole.STORY_ARCHITECT,
        {
            "candidates": [
                _candidate("ตลาดสุดท้าย", "The Last Market"),
                _candidate("ร้านของลุงเล็ก", "Uncle Lek's Shop"),
            ]
        },
    )
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": EPISODES}
    )
    generated = world.script_maker.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-submit-1"
    )
    assert generated.status == "COMPLETED"
    assert len(generated.candidates) == len(generated.scopes) == 2
    assert all(isinstance(c.rights, PendingRightsAssessment) for c in generated.candidates)
    assert all(len(scope.arc) == EPISODES for scope in generated.scopes)
    assert all(
        180_000 <= scope.episode_min_duration_ms and scope.episode_max_duration_ms <= 300_000
        for scope in generated.scopes
    ), "candidate scopes keep the approved 180-300 s duration band"
    envelope_committed = world.committed(season_id=season_id)
    assert envelope_committed == generated.settled_micro_usd > 0
    assert (
        world.count(
            "SELECT COUNT(*) FROM reservations WHERE season_id = %s AND state = 'ACTIVE'",
            (season_id,),
        )
        == 0
    ), "candidate generation leaves nothing held on the research envelope"
    # Rights and evidence are never invented at candidate stage (SPEC §7: unknowns stay
    # unknown): pending rights only, no rights route, no source evidence, Thai retained.
    assert all(
        not scope.rights_route_id and not scope.research_evidence_refs for scope in generated.scopes
    )
    assert all(scope.creative_constraints.retain_thai_performances for scope in generated.scopes)
    assert all(
        f"Tone: {owner_intake.tone}" in scope.creative_constraints.style_rules
        for scope in generated.scopes
    )
    assert all(
        beat.summary.startswith("จุดเปลี่ยน") for scope in generated.scopes for beat in scope.arc
    ), "arc beats stay in the owner's Thai language"

    # --- bounded research picks one candidate and persists the proposal scope ------------
    template = ResearchRequest(
        trigger=ResearchTrigger.MANUAL,
        trigger_key="script-maker.selected:v1",
        allowed_source_ids=["src-thai-drama-1", "src-thai-drama-2"],
        query_texts=[owner_intake.story_idea],
        comparator_corpus=ComparatorCorpus(scenes=[COMPARATOR_SCENE]),
        candidate_concepts=[ConceptDraft(concept_id="placeholder", scope=generated.scopes[0])],
    )
    research_result = world.research.run_research(season_id, generated.research_request(template))
    assert research_result.state == "COMPLETED"
    assert research_result.proposal_id is not None
    assert research_result.outcome is not None
    assert research_result.outcome.chosen_concept_id is not None

    bound = generated.bind_gate1_proposal(research_result, world.research)
    persisted_scope = world.research.proposal_scope(research_result.proposal_id)
    chosen_index = next(
        i
        for i, candidate in enumerate(bound.candidates)
        if str(candidate.record_id) == research_result.outcome.chosen_concept_id
    )
    chosen = bound.candidates[chosen_index]
    proposal_row = world.row(
        "SELECT scope_hash, status FROM season_proposals WHERE id = %s",
        (research_result.proposal_id,),
    )
    assert proposal_row is not None and proposal_row["status"] == "PROPOSED"
    # The candidate is bound to the exact persisted, provenance-stamped scope hash.
    assert chosen.scope_sha256 == canonical_hash(persisted_scope) == proposal_row["scope_hash"]
    binding = CandidateScopeBinding.from_candidate(owner_intake, chosen, persisted_scope)

    # --- Gate 1: the existing human gate, and the only one before production -------------
    with pytest.raises(InvalidTransition, match="PROPOSED"):
        world.story.compile_season(season_id)
    revision = world.row("SELECT revision FROM seasons WHERE id = %s", (season_id,))["revision"]
    decision = world.review.decide_season(
        world.human(),
        season_id,
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=revision,
            package_hash=canonical_hash(persisted_scope),
            idempotency_key="gate1-approve-t039-1",
        ),
    )
    assert decision.status_code == 202
    assert (
        world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"]
        == "SEASON_APPROVED"
    )
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (season_id,)) == 1
    ), "Script Maker adds no third human gate"

    # --- post-gate: compiled bible, rich character/secret ledger, packs ------------------
    compiled = world.story.compile_season(season_id)
    bible = compiled.bible
    assert bible.approved_scope_hash == canonical_hash(persisted_scope) == binding.scope_hash

    episode_ids = world.episodes(season_id, persisted_scope)
    world.llm.script_token(
        f"script-maker:{episode_ids[0]}:rich-bible:{season_id}:v1:t1",
        _bible_output(persisted_scope.characters),
    )
    rich = world.story_maker.generate_rich_bible(
        episode_ids[0], bible=bible, episode_count=EPISODES
    )
    assert rich.status == "COMPLETED" and rich.rich_bible is not None
    ledger = rich.rich_bible.season_story_ledger
    assert ledger.approved_scope_hash == bible.approved_scope_hash
    assert ledger.season_id == bible.season_id

    asset_id = uuid.uuid4()
    packs = []
    for number, episode_id in enumerate(episode_ids, start=1):
        world.llm.script_token(
            f"script-maker:{episode_id}:episode-pack:{number}:v1:t1",
            _pack_output(number, asset_id),
        )
        outcome = world.story_maker.generate_episode_pack(
            episode_id,
            candidate_binding=binding,
            episode_number=number,
            season_scope=persisted_scope,
            bible=bible,
            rich_bible=rich.rich_bible,
            available_asset_ids={asset_id},
            available_prop_ids={"letter"},
            available_location_ids={"stall"},
            available_wardrobe_assignment_ids=set(),
        )
        assert outcome.status == "COMPLETED" and outcome.episode_pack is not None
        packs.append(outcome.episode_pack)

    detailed, later = first_three_and_later_map(packs)
    assert [p.episode_number for p in detailed] == [1, 2, 3]
    assert [p.episode_number for p in later] == [4, 5]
    assert all(not p.scoped_map_only for p in detailed)
    assert all(p.scoped_map_only for p in later)
    assert all(180_000 <= p.duration_target_ms <= 300_000 for p in packs)

    # --- reveal timing: no future secret reaches an early pack --------------------------
    pack_json = packs[0].model_dump_json()
    assert "mother-letter" not in pack_json and "collector-orders" not in pack_json
    assert SECRET_LETTER_FACT not in pack_json and SECRET_ORDERS_FACT not in pack_json
    assert all(logic.secret_id is None for logic in packs[0].character_logic)
    # From its reveal episode on, the letter secret is visible knowledge again.
    pack2_knowledge = {
        logic.character_id: ids
        for logic in packs[1].character_logic
        for ids in logic.knowledge_by_episode.values()
    }
    assert "mother-letter" in pack2_knowledge["fon"]
    assert "mother-letter" in pack2_knowledge["lek"]
    assert all("collector-orders" not in ids for ids in pack2_knowledge.values())
    pack5_knowledge = {
        logic.character_id: ids
        for logic in packs[4].character_logic
        for ids in logic.knowledge_by_episode.values()
    }
    assert "collector-orders" in pack5_knowledge["nok"]

    # --- replay: the finished generation costs nothing extra ----------------------------
    envelope_after = world.committed(season_id=season_id)
    replayed = world.script_maker.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-submit-1"
    )
    assert replayed.status == "COMPLETED"
    assert replayed.settled_micro_usd == 0, "a replayed generation adds no spend"
    assert replayed.candidates == generated.candidates
    assert world.committed(season_id=season_id) == envelope_after

    rich_replay = world.story_maker.generate_rich_bible(
        episode_ids[0], bible=bible, episode_count=EPISODES
    )
    assert rich_replay.status == "REPLAYED"
    assert rich_replay.settled_micro_usd == 0
    assert rich_replay.rich_bible == rich.rich_bible
    assert world.committed(episode_id=episode_ids[0]) > 0

    # --- budget truth: every account settled inside its cap, nothing left held -----------
    for episode_id in episode_ids:
        account = world.row(
            "SELECT cap_micro_usd, settled_micro_usd, reserved_outstanding_micro_usd "
            "FROM budget_accounts WHERE scope_kind = 'EPISODE' AND episode_id = %s",
            (episode_id,),
        )
        assert account is not None
        assert account["settled_micro_usd"] > 0
        assert account["settled_micro_usd"] <= account["cap_micro_usd"]
        assert account["reserved_outstanding_micro_usd"] == 0
    research_account = world.row(
        "SELECT cap_micro_usd, settled_micro_usd, reserved_outstanding_micro_usd "
        "FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
        (season_id,),
    )
    assert research_account is not None
    assert research_account["settled_micro_usd"] <= research_account["cap_micro_usd"]
    assert research_account["reserved_outstanding_micro_usd"] == 0


def test_pack_writer_refuses_anything_but_the_persisted_gate1_scope(
    db: Database, offline_settings: Settings, object_store: ObjectStore
) -> None:
    """Post-gate sequencing: packs bind the exact approved scope or refuse with zero spend."""
    world = Compose(db, offline_settings, object_store)
    season_id = world.proposed_season()
    owner_intake = world.intake()

    world.llm.script_role(
        RuntimeRole.STORY_ARCHITECT,
        {
            "candidates": [
                _candidate("ตลาดสุดท้าย", "The Last Market"),
                _candidate("ร้านของลุงเล็ก", "Uncle Lek's Shop"),
            ]
        },
    )
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": EPISODES}
    )
    generated = world.script_maker.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-submit-2"
    )
    assert generated.status == "COMPLETED"

    template = ResearchRequest(
        trigger=ResearchTrigger.MANUAL,
        trigger_key="script-maker.selected:v2",
        allowed_source_ids=["src-thai-drama-1"],
        query_texts=[owner_intake.story_idea],
        comparator_corpus=ComparatorCorpus(scenes=[COMPARATOR_SCENE]),
        candidate_concepts=[ConceptDraft(concept_id="placeholder", scope=generated.scopes[0])],
    )
    research_result = world.research.run_research(season_id, generated.research_request(template))
    assert research_result.state == "COMPLETED"
    assert research_result.outcome is not None
    assert research_result.outcome.chosen_concept_id is not None
    bound = generated.bind_gate1_proposal(research_result, world.research)
    persisted_scope = world.research.proposal_scope(research_result.proposal_id)
    chosen = next(
        candidate
        for candidate in bound.candidates
        if str(candidate.record_id) == research_result.outcome.chosen_concept_id
    )
    binding = CandidateScopeBinding.from_candidate(owner_intake, chosen, persisted_scope)

    revision = world.row("SELECT revision FROM seasons WHERE id = %s", (season_id,))["revision"]
    world.review.decide_season(
        world.human(),
        season_id,
        ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=revision,
            package_hash=canonical_hash(persisted_scope),
            idempotency_key="gate1-approve-t039-2",
        ),
    )
    bible = world.story.compile_season(season_id).bible
    episode_ids = world.episodes(season_id, persisted_scope)
    world.llm.script_token(
        f"script-maker:{episode_ids[0]}:rich-bible:{season_id}:v1:t1",
        _bible_output(persisted_scope.characters),
    )
    rich = world.story_maker.generate_rich_bible(
        episode_ids[0], bible=bible, episode_count=EPISODES
    )
    assert rich.status == "COMPLETED" and rich.rich_bible is not None

    # A scope that differs from the persisted Gate-1 scope by one field is refused
    # before any paid dispatch, whichever side the drift is on.
    drifted = persisted_scope.model_copy(update={"title_en": "A Drifted Title"})
    with pytest.raises(ValueError, match="does not match"):
        binding.verify_gate1_scope(drifted)
    draft_binding = CandidateScopeBinding.bind(owner_intake, chosen.record_id, drifted)
    with pytest.raises(ValueError, match="exact Gate-1-approved scope"):
        world.story_maker.generate_episode_pack(
            episode_ids[0],
            candidate_binding=draft_binding,
            episode_number=1,
            season_scope=drifted,
            bible=bible,
            rich_bible=rich.rich_bible,
            available_asset_ids={uuid.uuid4()},
            available_prop_ids={"letter"},
            available_location_ids={"stall"},
            available_wardrobe_assignment_ids=set(),
        )
    # Nothing was dispatched for the refused pack.
    account = world.row(
        "SELECT settled_micro_usd FROM budget_accounts WHERE scope_kind = 'EPISODE' "
        "AND episode_id = %s",
        (episode_ids[0],),
    )
    assert account is not None
    assert account["settled_micro_usd"] > 0, "the rich bible itself did dispatch and settle"
    pack_calls = [
        call for call in world.llm.calls if call.method == "generate" and "episode-pack" in call.key
    ]
    assert pack_calls == [], "no pack writer dispatch happened for the drifted scope"

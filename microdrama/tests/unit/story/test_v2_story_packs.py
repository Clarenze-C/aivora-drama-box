from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from story_support import T0, World

from microdrama.contracts.enums import RightsSubjectKind
from microdrama.contracts.examples import season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import (
    ConceptIntake,
    OutfitDefinition,
    PackBeat,
    PendingRightsAssessment,
    RightsGrant,
    RightsStatus,
    SceneWardrobeAssignment,
    StateEvent,
    StateValue,
    StoryTime,
    WardrobeBible,
)
from microdrama.story import build_script_maker_story_service
from microdrama.story.directing import BeatIntent, compile_episode_pack, invalidated_shot_ids
from microdrama.story.models import BibleFact, FactKind, SeasonBible
from microdrama.story.script_maker import (
    CandidateScopeBinding,
    EpisodePackDraft,
    _episode_character_logic_id,
    build_candidate,
    build_episode_pack,
    build_rich_bible,
)
from microdrama.testing.fakes import FakeLLMProvider, SequentialIds

_NOW = datetime(2026, 10, 30, tzinfo=UTC)
_LEAKED_FACT = "แผนที่ซ่อนอยู่ในจดหมายเผยว่าลุงเล็กค้ำประกันหนี้ทั้งก้อนไว้กับบริษัทของนก"


def intake(episode_count: int = 10) -> ConceptIntake:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    return ConceptIntake.seal(
        record_id=uuid4(),
        version=1,
        created_at=now,
        updated_at=now,
        valid_from=now,
        story_idea="A family tries to save its small market stall.",
        genre_tags=["family-drama"],
        tone="warm, suspenseful",
        requested_episode_count=episode_count,
    )


class PackWorld:
    """An approved scope, candidate, bible and rich bible for one pack build."""

    def __init__(self, episode_count: int = 10) -> None:
        self.intake = intake(episode_count)
        self.scope = season_scope().model_copy(update={"expected_episode_count": episode_count})
        self.candidate = build_candidate(self.intake, self.scope, record_id=uuid4(), now=_NOW)
        self.binding = CandidateScopeBinding.from_candidate(self.intake, self.candidate, self.scope)
        self.bible = SeasonBible(
            bible_id=uuid4(),
            season_id=self.scope.season_id,
            scope_version=self.scope.scope_version,
            approved_scope_hash=canonical_hash(self.scope),
            canon_version=1,
            title_th=self.scope.title_th,
            title_en=self.scope.title_en,
            logline=self.scope.logline,
            premise=self.scope.premise,
            characters=self.scope.characters,
            arc=self.scope.arc,
            facts=[
                BibleFact(
                    fact_key="premise",
                    kind=FactKind.PREMISE,
                    statement=self.scope.premise,
                    source_field="premise",
                )
            ],
            playbook_version="test",
            compiled_at=_NOW,
        )
        self.rich = build_rich_bible(
            {
                "characters": [
                    {
                        "character_id": char.character_id,
                        "observable_goal": "Keep the stall open.",
                        "strategy": "Find another source of income.",
                        "flaw": "Hides worry.",
                        "secret_id": "mother-letter" if i == 0 else None,
                        "relationship_pressures": ["A family promise is at risk."],
                        "knowledge_by_episode": {"1": [], "2": ["mother-letter"]}
                        if i == 0
                        else {"1": [], "2": []},
                    }
                    for i, char in enumerate(self.scope.characters)
                ],
                "secrets": [
                    {
                        "secret_id": "mother-letter",
                        "held_by_character_id": self.scope.characters[0].character_id,
                        "fact": "A planned future secret.",
                        "planned_reveal_episode": 2,
                        "known_by_character_ids": [self.scope.characters[0].character_id],
                    }
                ],
                "promise": "A family protects the stall through a hidden debt.",
                "payoff_debts": [
                    {
                        "debt_id": "stall-debt",
                        "description": "Resolve the stall debt.",
                        "due_episode": episode_count,
                        "status": "OPEN",
                    }
                ],
                "escalations": [
                    {"episode_number": 1, "description": "The first deadline appears."},
                    {"episode_number": 2, "description": "The hidden letter arrives."},
                ],
            },
            bible=self.bible,
            episode_count=episode_count,
            now=_NOW,
        )

    def draft(
        self,
        *,
        episode_number: int = 1,
        duration_target_ms: int = 240_000,
        visible_action: str = "Fon counts the day's earnings.",
        scene_extra: dict | None = None,
        beat_extra: dict | None = None,
    ) -> EpisodePackDraft:
        beat: dict = {
            "beat_id": "find-letter",
            "function": "revelation",
            "visible_action": visible_action,
            "proof_object_ids": ["letter"],
            "dependency_beat_ids": [],
            "state_in": [],
            "state_out": [],
            "required_asset_ids": [],
            "reveal_ids": [],
        }
        beat.update(beat_extra or {})
        scene: dict = {
            "scene_id": "market",
            "scene_number": 1,
            "location_id": "stall",
            "visible_character_ids": [c.character_id for c in self.scope.characters],
            "prop_ids": ["letter"],
            "beats": [beat],
        }
        scene.update(scene_extra or {})
        return EpisodePackDraft(
            episode_id=uuid4(),
            episode_number=episode_number,
            duration_target_ms=duration_target_ms,
            promise="The family may save the stall.",
            payoff_debt=["Who threatened the lease?"],
            escalation="A deadline gets closer.",
            scenes=[scene],
            story_time_by_scene={
                "market": {"story_day": 1, "local_time": "10:00", "setting": "stall"}
            },
            character_logic=list(self.rich.character_logic),
        )

    def pack(
        self, *, episode_number: int = 1, visible_action: str = "Fon counts the day's earnings."
    ):
        return build_episode_pack(
            self.draft(episode_number=episode_number, visible_action=visible_action),
            bible=self.bible,
            secret_ledger=self.rich.secret_ledger,
            candidate_binding=self.binding,
            record_id=UUID("00000000-0000-4000-8000-000000000041"),
            now=_NOW,
        )

    def stateful_pack(self):
        draft = self.draft()
        first = dict(draft.scenes[0]["beats"][0])
        first["beat_id"] = "take-letter"
        first["state_out"] = [{"entity_id": "letter", "field": "holder", "value": "fon"}]
        second = {
            "beat_id": "hand-letter",
            "function": "handoff",
            "visible_action": "Fon passes the letter to Lek.",
            "proof_object_ids": ["letter"],
            "dependency_beat_ids": ["take-letter"],
            "state_in": [{"entity_id": "letter", "field": "holder", "value": "fon"}],
            "state_out": [{"entity_id": "letter", "field": "holder", "value": "lek"}],
            "required_asset_ids": [],
            "reveal_ids": [],
        }
        draft.scenes[0]["beats"] = [first, second]
        return build_episode_pack(
            draft,
            bible=self.bible,
            secret_ledger=self.rich.secret_ledger,
            candidate_binding=self.binding,
            record_id=UUID("00000000-0000-4000-8000-000000000042"),
            now=_NOW,
        )


def _wardrobe_fixture(pack, *, day_offset: int = 0, setting_override: str | None = None):
    bibles = []
    assignments = []
    updated_scenes = []
    for scene in pack.scenes:
        scene_assignment_ids = []
        for character_id in scene.visible_character_ids:
            asset_id = uuid4()
            outfit_id = f"outfit-{character_id}"
            assignment_id = uuid4()
            setting = setting_override or scene.story_time.setting
            rights = RightsGrant(
                rights_route_id="test-rights",
                subject_kind=RightsSubjectKind.MODEL_OUTPUT,
                subject_ref=outfit_id,
                rights_version=1,
                status=RightsStatus.ELIGIBLE,
                territories=["TH"],
                commercial_use=True,
                output_release_allowed=True,
                evidence_sha256=["a" * 64],
            )
            outfit = OutfitDefinition(
                outfit_id=outfit_id,
                version=1,
                asset_id=asset_id,
                asset_version=1,
                asset_sha256="b" * 64,
                story_day_from=1,
                story_day_until=10,
                setting_tags=sorted({scene.story_time.setting, setting}),
                rights=rights,
            )
            bible = WardrobeBible.seal(
                record_id=uuid4(),
                version=1,
                created_at=_NOW,
                updated_at=_NOW,
                valid_from=_NOW,
                season_id=pack.season_id,
                character_id=character_id,
                outfits=[outfit],
            )
            assignment = SceneWardrobeAssignment.seal(
                record_id=assignment_id,
                version=1,
                created_at=_NOW,
                updated_at=_NOW,
                valid_from=_NOW,
                episode_id=pack.episode_id,
                scene_id=scene.scene_id,
                character_id=character_id,
                story_day=scene.story_time.story_day + day_offset,
                setting=setting,
                wardrobe_bible_id=bible.record_id,
                wardrobe_bible_version=bible.version,
                outfit_id=outfit.outfit_id,
                outfit_version=outfit.version,
                asset_id=outfit.asset_id,
                asset_version=outfit.asset_version,
                asset_sha256=outfit.asset_sha256,
                rights=rights,
            )
            bibles.append(bible)
            assignments.append(assignment)
            scene_assignment_ids.append(assignment.record_id)
        updated_scenes.append(
            scene.model_copy(update={"wardrobe_assignment_ids": scene_assignment_ids})
        )
    bound_pack = type(pack).seal(
        **pack.model_copy(update={"scenes": updated_scenes}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    return bound_pack, bibles, assignments


def _two_scene_handoff_pack(world: PackWorld):
    base = world.stateful_pack()
    first_scene = base.scenes[0]
    first_beat, second_beat = first_scene.beats
    holder_fon = StateValue(entity_id="letter", field="holder", value="fon")
    holder_lek = StateValue(entity_id="letter", field="holder", value="lek")
    first_scene = first_scene.model_copy(
        update={
            "beats": [first_beat],
            "state_in": [holder_fon],
            "state_out": [holder_fon],
        }
    )
    home_time = StoryTime.seal(
        record_id=uuid4(),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        story_day=2,
        local_time="09:00",
        setting="home",
    )
    second_scene = first_scene.model_copy(
        update={
            "scene_id": "home",
            "scene_number": 2,
            "story_time": home_time,
            "location_id": "home",
            "dependency_scene_ids": ["market"],
            "beats": [second_beat],
            "state_in": [holder_fon],
            "state_out": [holder_lek],
        }
    )
    pack = type(base).seal(
        **base.model_copy(update={"scenes": [first_scene, second_scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    event = StateEvent.seal(
        record_id=uuid4(),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        episode_id=pack.episode_id,
        sequence=1,
        entity_id="letter",
        field="holder",
        before="fon",
        after="lek",
        scene_id="home",
        effective_from_ms=135_000,
        effective_until_ms=150_000,
        evidence_sha256="c" * 64,
    )
    return pack, event


def test_candidate_binding_is_stable_and_rejects_changed_gate1_scope() -> None:
    owner_intake = intake()
    scope = season_scope().model_copy(update={"expected_episode_count": 10})
    binding = CandidateScopeBinding.bind(owner_intake, uuid4(), scope)

    binding.verify_gate1_scope(scope)
    changed_scope = scope.model_copy(update={"title_en": "A different story"})
    with pytest.raises(ValueError, match="does not match"):
        binding.verify_gate1_scope(changed_scope)


def test_candidate_binding_requires_intake_episode_count() -> None:
    owner_intake = intake(episode_count=8)
    scope = season_scope().model_copy(update={"expected_episode_count": 10})
    with pytest.raises(ValueError, match="episode count"):
        CandidateScopeBinding.bind(owner_intake, uuid4(), scope)


def test_candidate_keeps_rights_pending_and_binds_scope_hash() -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    owner_intake = intake()
    scope = season_scope().model_copy(update={"expected_episode_count": 10})
    candidate = build_candidate(owner_intake, scope, record_id=uuid4(), now=now)

    assert isinstance(candidate.rights, PendingRightsAssessment)
    binding = CandidateScopeBinding.from_candidate(owner_intake, candidate, scope)
    binding.verify_gate1_scope(scope)


def test_pack_filters_future_secret_and_validates_proof_object_mapping() -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    owner_intake = intake()
    scope = season_scope().model_copy(update={"expected_episode_count": 10})
    candidate = build_candidate(owner_intake, scope, record_id=uuid4(), now=now)
    binding = CandidateScopeBinding.from_candidate(owner_intake, candidate, scope)
    bible = SeasonBible(
        bible_id=uuid4(),
        season_id=scope.season_id,
        scope_version=scope.scope_version,
        approved_scope_hash=canonical_hash(scope),
        canon_version=1,
        title_th=scope.title_th,
        title_en=scope.title_en,
        logline=scope.logline,
        premise=scope.premise,
        characters=scope.characters,
        arc=scope.arc,
        facts=[
            BibleFact(
                fact_key="premise",
                kind=FactKind.PREMISE,
                statement=scope.premise,
                source_field="premise",
            )
        ],
        playbook_version="test",
        compiled_at=now,
    )
    rich = build_rich_bible(
        {
            "characters": [
                {
                    "character_id": char.character_id,
                    "observable_goal": "Keep the stall open.",
                    "strategy": "Find another source of income.",
                    "flaw": "Hides worry.",
                    "secret_id": "mother-letter" if i == 0 else None,
                    "relationship_pressures": ["A family promise is at risk."],
                    "knowledge_by_episode": {"1": [], "2": ["mother-letter"]}
                    if i == 0
                    else {"1": [], "2": []},
                }
                for i, char in enumerate(scope.characters)
            ],
            "secrets": [
                {
                    "secret_id": "mother-letter",
                    "held_by_character_id": scope.characters[0].character_id,
                    "fact": "A planned future secret.",
                    "planned_reveal_episode": 2,
                    "known_by_character_ids": [scope.characters[0].character_id],
                }
            ],
            "promise": "A family protects the stall through a hidden debt.",
            "payoff_debts": [
                {
                    "debt_id": "stall-debt",
                    "description": "Resolve the stall debt.",
                    "due_episode": 10,
                    "status": "OPEN",
                }
            ],
            "escalations": [
                {"episode_number": 1, "description": "The first deadline appears."},
                {"episode_number": 2, "description": "The hidden letter arrives."},
            ],
        },
        bible=bible,
        episode_count=10,
        now=now,
    )
    secret_ledger = rich.secret_ledger
    logic = list(rich.character_logic)
    assert rich.season_story_ledger.approved_scope_hash == canonical_hash(scope)
    asset_id = uuid4()
    draft = EpisodePackDraft(
        episode_id=uuid4(),
        episode_number=1,
        duration_target_ms=240_000,
        promise="The family may save the stall.",
        payoff_debt=["Who threatened the lease?"],
        escalation="A deadline gets closer.",
        scenes=[
            {
                "scene_id": "market",
                "scene_number": 1,
                "location_id": "stall",
                "visible_character_ids": [c.character_id for c in scope.characters],
                "prop_ids": ["letter"],
                "beats": [
                    PackBeat(
                        beat_id="find-letter",
                        function="revelation",
                        visible_action="Fon finds the sealed letter.",
                        proof_object_ids=["letter"],
                        required_asset_ids=[asset_id],
                    )
                ],
            }
        ],
        story_time_by_scene={"market": {"story_day": 1, "local_time": "10:00", "setting": "stall"}},
        character_logic=logic,
    )

    pack = build_episode_pack(
        draft,
        bible=bible,
        secret_ledger=secret_ledger,
        candidate_binding=binding,
        record_id=uuid4(),
        now=now,
    )

    assert all(character.secret_id is None for character in pack.character_logic)
    assert all(
        "mother-letter" not in ids
        for character in pack.character_logic
        for ids in character.knowledge_by_episode.values()
    )
    assert pack.scenes[0].beats[0].proof_object_ids == ["letter"]
    with pytest.raises(ValueError, match="proof_object_ids"):
        build_episode_pack(
            replace(draft, scenes=[{**draft.scenes[0], "prop_ids": []}]),
            bible=bible,
            secret_ledger=secret_ledger,
            candidate_binding=binding,
            record_id=uuid4(),
            now=now,
        )


def test_pack_rejects_duration_outside_the_approved_band() -> None:
    world = PackWorld()
    for bad_ms in (150_000, 301_000):
        with pytest.raises(ValueError, match="duration is outside"):
            build_episode_pack(
                world.draft(duration_target_ms=bad_ms),
                bible=world.bible,
                secret_ledger=world.rich.secret_ledger,
                candidate_binding=world.binding,
                record_id=uuid4(),
                now=_NOW,
            )


def test_pack_dependencies_must_resolve_and_stay_acyclic() -> None:
    world = PackWorld()
    with pytest.raises(ValueError, match="resolve inside this pack"):
        build_episode_pack(
            world.draft(scene_extra={"dependency_scene_ids": ["nowhere"]}),
            bible=world.bible,
            secret_ledger=world.rich.secret_ledger,
            candidate_binding=world.binding,
            record_id=uuid4(),
            now=_NOW,
        )
    cyclic = world.draft(beat_extra={"proof_object_ids": [], "dependency_beat_ids": ["beat-two"]})
    cyclic.scenes[0]["beats"].append(
        {
            "beat_id": "beat-two",
            "function": "reaction",
            "visible_action": "Lek reacts.",
            "proof_object_ids": [],
            "dependency_beat_ids": ["find-letter"],
            "state_in": [],
            "state_out": [],
            "required_asset_ids": [],
            "reveal_ids": [],
        }
    )
    with pytest.raises(ValueError, match="cyclic beat dependencies"):
        build_episode_pack(
            cyclic,
            bible=world.bible,
            secret_ledger=world.rich.secret_ledger,
            candidate_binding=world.binding,
            record_id=uuid4(),
            now=_NOW,
        )


def test_pack_required_assets_accept_uuid_strings_but_refuse_unknown_ids() -> None:
    world = PackWorld()
    asset_id = uuid4()

    def build(beat_extra: dict) -> None:
        build_episode_pack(
            world.draft(beat_extra=beat_extra),
            bible=world.bible,
            secret_ledger=world.rich.secret_ledger,
            candidate_binding=world.binding,
            record_id=uuid4(),
            now=_NOW,
            available_asset_ids={asset_id},
        )

    # Writer output carries asset ids as strings; the availability set is UUIDs.
    pack = build_episode_pack(
        world.draft(beat_extra={"required_asset_ids": [str(asset_id)]}),
        bible=world.bible,
        secret_ledger=world.rich.secret_ledger,
        candidate_binding=world.binding,
        record_id=uuid4(),
        now=_NOW,
        available_asset_ids={asset_id},
    )
    assert pack.scenes[0].beats[0].required_asset_ids == [asset_id]
    assert isinstance(pack.scenes[0].beats[0].required_asset_ids[0], UUID)
    with pytest.raises(ValueError, match="missing required asset id"):
        build({"required_asset_ids": [str(uuid4())]})
    with pytest.raises(ValueError, match="missing required asset id"):
        build({"required_asset_ids": ["not-a-uuid"]})


def test_pack_refuses_an_unrevealed_secret_fact_in_its_text() -> None:
    world = PackWorld()
    # The letter secret is planned for episode 2; episode 1 must not carry its fact.
    leaked_rich = build_rich_bible(
        {
            "characters": [
                {
                    "character_id": logic.character_id,
                    "observable_goal": logic.observable_goal,
                    "strategy": logic.strategy,
                    "flaw": logic.flaw,
                    "secret_id": logic.secret_id,
                    "relationship_pressures": list(logic.relationship_pressures),
                    "knowledge_by_episode": dict(logic.knowledge_by_episode),
                }
                for logic in world.rich.character_logic
            ],
            "secrets": [
                {
                    "secret_id": "mother-letter",
                    "held_by_character_id": world.scope.characters[0].character_id,
                    "fact": _LEAKED_FACT,
                    "planned_reveal_episode": 2,
                    "known_by_character_ids": [world.scope.characters[0].character_id],
                }
            ],
            "promise": "A family protects the stall through a hidden debt.",
            "payoff_debts": [
                {
                    "debt_id": "stall-debt",
                    "description": "Resolve the stall debt.",
                    "due_episode": 10,
                    "status": "OPEN",
                }
            ],
            "escalations": [
                {"episode_number": 1, "description": "The first deadline appears."},
                {"episode_number": 2, "description": "The hidden letter arrives."},
            ],
        },
        bible=world.bible,
        episode_count=10,
        now=_NOW,
    )
    with pytest.raises(ValueError, match="unrevealed secret fact"):
        build_episode_pack(
            world.draft(episode_number=1, visible_action=f"ฝนเปิดอ่าน: {_LEAKED_FACT}"),
            bible=world.bible,
            secret_ledger=leaked_rich.secret_ledger,
            candidate_binding=world.binding,
            record_id=uuid4(),
            now=_NOW,
        )


def test_pack_refuses_a_bible_bound_to_a_different_approved_scope() -> None:
    world = PackWorld()
    drifted = world.scope.model_copy(update={"title_en": "A Drifted Title"})
    drifted_binding = CandidateScopeBinding.bind(world.intake, world.candidate.record_id, drifted)
    with pytest.raises(ValueError, match="not bound to the selected candidate scope"):
        build_episode_pack(
            world.draft(),
            bible=world.bible,
            secret_ledger=world.rich.secret_ledger,
            candidate_binding=drifted_binding,
            record_id=uuid4(),
            now=_NOW,
        )


def test_rich_bible_is_bound_to_the_exact_approved_scope_hash() -> None:
    world = PackWorld()
    ledger = world.rich.season_story_ledger
    assert ledger.approved_scope_hash == canonical_hash(world.scope)
    from microdrama.contracts.v2 import validate_season_story_ledger

    validate_season_story_ledger(
        ledger,
        list(world.rich.character_logic),
        world.rich.secret_ledger,
        approved_scope_hash=canonical_hash(world.scope),
        episode_count=10,
    )
    with pytest.raises(ValueError, match="different approved scope"):
        validate_season_story_ledger(
            ledger,
            list(world.rich.character_logic),
            world.rich.secret_ledger,
            approved_scope_hash="f" * 64,
            episode_count=10,
        )


def test_v2_story_artifacts_replay_from_durable_store_after_service_rebuild(world: World) -> None:
    season_id, approved_scope = world.season()
    bible = world.service.compile_season(season_id).bible
    episode_id = world.episode(season_id, approved_scope)
    with world.db.transaction() as tx:
        world.budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=approved_scope.cost_policy
        )

    owner_intake = intake(approved_scope.expected_episode_count)
    candidate = build_candidate(owner_intake, approved_scope, record_id=uuid4(), now=T0)
    binding = CandidateScopeBinding.from_candidate(owner_intake, candidate, approved_scope)
    first_character = approved_scope.characters[0].character_id
    rich_output = {
        "characters": [
            {
                "character_id": character.character_id,
                "observable_goal": "Keep the family stall open.",
                "strategy": "Find another source of income.",
                "flaw": "Hides worry from the family.",
                "secret_id": "mother-letter" if index == 0 else None,
                "relationship_pressures": ["A family promise is at risk."],
                "knowledge_by_episode": {"1": [], "2": ["mother-letter"]}
                if index == 0
                else {"1": [], "2": []},
            }
            for index, character in enumerate(approved_scope.characters)
        ],
        "secrets": [
            {
                "secret_id": "mother-letter",
                "held_by_character_id": first_character,
                "fact": "The old lease contains a concealed payment agreement.",
                "planned_reveal_episode": 2,
                "known_by_character_ids": [first_character],
            }
        ],
        "promise": "A family protects its stall while old promises come due.",
        "payoff_debts": [
            {
                "debt_id": "lease-debt",
                "description": "Resolve the threatened lease.",
                "due_episode": approved_scope.expected_episode_count,
                "status": "OPEN",
            }
        ],
        "escalations": [
            {"episode_number": 1, "description": "A closing deadline appears."},
            {"episode_number": 2, "description": "An old letter surfaces."},
        ],
    }
    pack_output = {
        "episode_number": 1,
        "duration_target_ms": 240_000,
        "promise": "The family may keep the stall.",
        "payoff_debt": ["Who set the deadline?"],
        "escalation": "A landlord gives the family one day.",
        "scenes": [
            {
                "scene_id": "stall-opening",
                "scene_number": 1,
                "story_time": {
                    "story_day": 1,
                    "local_time": "09:00",
                    "setting": "market stall",
                    "timezone": "Asia/Bangkok",
                },
                "location_id": "stall",
                "visible_character_ids": [c.character_id for c in approved_scope.characters],
                "prop_ids": ["lease-letter"],
                "dependency_scene_ids": [],
                "wardrobe_assignment_ids": [],
                "state_in": [],
                "state_out": [],
                "beats": [
                    {
                        "beat_id": "deadline",
                        "function": "inciting_pressure",
                        "visible_action": "The landlord posts a deadline beside the stall.",
                        "proof_object_ids": ["lease-letter"],
                        "dependency_beat_ids": [],
                        "state_in": [],
                        "state_out": [],
                        "required_asset_ids": [],
                        "reveal_ids": [],
                    }
                ],
            }
        ],
    }
    provider = FakeLLMProvider(clock=world.clock, ids=SequentialIds("v2-writer-first"))
    provider.script_token(f"script-maker:{episode_id}:rich-bible:{season_id}:v1:t1", rich_output)
    provider.script_token(f"script-maker:{episode_id}:rich-bible:{season_id}:v2:t1", rich_output)
    provider.script_token(f"script-maker:{episode_id}:episode-pack:1:v1:t1", pack_output)
    service = build_script_maker_story_service(
        world.db, world.clock, world.settings, budget=world.budget, llm=provider
    )

    rich_result = service.generate_rich_bible(
        episode_id, bible=bible, episode_count=approved_scope.expected_episode_count
    )
    assert rich_result.status == "COMPLETED"
    assert rich_result.rich_bible is not None
    durable_types = {
        row["contract_type"]
        for row in world.rows(
            "SELECT DISTINCT contract_type FROM v2_contract_documents "
            "WHERE payload->>'season_id' = %s",
            (str(season_id),),
        )
    }
    assert {"CharacterLogic", "SecretLedger", "SeasonStoryLedger"} <= durable_types

    restarted_provider = FakeLLMProvider(
        clock=world.clock, ids=SequentialIds("v2-writer-restarted")
    )
    restarted = build_script_maker_story_service(
        world.db,
        world.clock,
        world.settings,
        budget=world.budget,
        llm=restarted_provider,
    )
    replayed_rich = restarted.generate_rich_bible(
        episode_id, bible=bible, episode_count=approved_scope.expected_episode_count
    )
    assert replayed_rich.status == "REPLAYED"
    assert replayed_rich.rich_bible == rich_result.rich_bible
    assert restarted_provider.calls == []

    with pytest.raises(ValueError, match="different approved scope"):
        restarted.generate_rich_bible(
            episode_id,
            bible=bible.model_copy(update={"approved_scope_hash": "f" * 64}),
            episode_count=approved_scope.expected_episode_count,
        )
    assert restarted_provider.calls == []

    revised_rich = service.generate_rich_bible(
        episode_id,
        bible=bible,
        episode_count=approved_scope.expected_episode_count,
        version=2,
    )
    assert revised_rich.status == "COMPLETED"
    assert revised_rich.rich_bible is not None
    assert [r.record_id for r in revised_rich.rich_bible.character_logic] == [
        r.record_id for r in rich_result.rich_bible.character_logic
    ]
    assert {r.version for r in revised_rich.rich_bible.character_logic} == {2}
    replayed_revision = restarted.generate_rich_bible(
        episode_id,
        bible=bible,
        episode_count=approved_scope.expected_episode_count,
        version=2,
    )
    assert replayed_revision.status == "REPLAYED"
    assert replayed_revision.rich_bible == revised_rich.rich_bible
    assert restarted_provider.calls == []

    pack_result = service.generate_episode_pack(
        episode_id,
        candidate_binding=binding,
        episode_number=1,
        season_scope=approved_scope,
        bible=bible,
        rich_bible=revised_rich.rich_bible,
        available_asset_ids=set(),
        available_prop_ids={"lease-letter"},
        available_location_ids={"stall"},
        available_wardrobe_assignment_ids=set(),
    )
    assert pack_result.status == "COMPLETED"
    assert pack_result.episode_pack is not None
    assert pack_result.episode_pack.approved_scope_hash == canonical_hash(approved_scope)
    source_by_character = {
        logic.character_id: logic for logic in revised_rich.rich_bible.character_logic
    }
    for snapshot in pack_result.episode_pack.character_logic:
        source = source_by_character[snapshot.character_id]
        assert snapshot.record_id == _episode_character_logic_id(episode_id, source.record_id)
        assert snapshot.record_id != source.record_id
    assert {logic.record_id for logic in pack_result.episode_pack.character_logic}.isdisjoint(
        {logic.record_id for logic in revised_rich.rich_bible.character_logic}
    )

    replayed_pack = restarted.generate_episode_pack(
        episode_id,
        candidate_binding=binding,
        episode_number=1,
        season_scope=approved_scope,
        bible=bible,
        rich_bible=replayed_revision.rich_bible,
        available_asset_ids=set(),
        available_prop_ids={"lease-letter"},
        available_location_ids={"stall"},
        available_wardrobe_assignment_ids=set(),
    )
    assert replayed_pack.status == "REPLAYED"
    assert replayed_pack.episode_pack == pack_result.episode_pack
    assert restarted_provider.calls == []
    changed_scope = approved_scope.model_copy(update={"title_en": "A changed approved title"})
    with pytest.raises(ValueError, match="exact Gate-1-approved scope"):
        restarted.generate_episode_pack(
            episode_id,
            candidate_binding=CandidateScopeBinding.bind(
                owner_intake, candidate.record_id, changed_scope
            ),
            episode_number=1,
            season_scope=changed_scope,
            bible=bible,
            rich_bible=replayed_rich.rich_bible,
            available_asset_ids=set(),
            available_prop_ids={"lease-letter"},
            available_location_ids={"stall"},
            available_wardrobe_assignment_ids=set(),
        )
    assert restarted_provider.calls == []


def test_directing_compile_is_stable_short_and_targeted() -> None:
    world = PackWorld()
    pack = world.pack()
    intent = BeatIntent(
        screen_axis="stall-counter-axis",
        screen_direction="LEFT_TO_RIGHT",
        eyeline="Fon keeps her gaze on the letter, then turns toward Lek.",
        action_handoff="Her right hand leaves the letter on the counter for the next shot.",
        sound_intent="Keep market room tone under a soft paper rustle.",
        edit_intent="Cut on the hand release and preserve screen direction.",
        framing="medium-two-shot",
    )
    first = compile_episode_pack(
        pack,
        approved_scope_hash=pack.approved_scope_hash,
        intents={"find-letter": intent},
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    second = compile_episode_pack(
        pack,
        approved_scope_hash=pack.approved_scope_hash,
        intents={"find-letter": intent},
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    assert first == second
    assert all(0 < shot.duration_ms <= 15_000 for shot in first.shots)
    assert sum(shot.duration_ms for shot in first.shots) == pack.duration_target_ms
    assert sum(len(section.shot_ids) for section in first.sections) == len(first.shots)
    changed_hash = first.shots[0].source_hashes[0]
    assert invalidated_shot_ids(first, {changed_hash}) == [
        shot.shot_id for shot in first.shots if changed_hash in shot.source_hashes
    ]
    with pytest.raises(ValueError, match="required outside draft mode"):
        compile_episode_pack(
            pack,
            approved_scope_hash=pack.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
        )
    with pytest.raises(ValueError, match="missing explicit directing intent"):
        compile_episode_pack(
            pack,
            approved_scope_hash=pack.approved_scope_hash,
            intents={},
            secret_ledger=world.rich.secret_ledger,
            draft_mode=True,
        )


def test_directing_rejects_unknown_state_and_future_reveal() -> None:
    world = PackWorld()
    pack = world.pack()
    beat = (
        pack.scenes[0]
        .beats[0]
        .model_copy(
            update={"state_out": [StateValue(entity_id="ghost", field="holder", value="Fon")]}
        )
    )
    scene = pack.scenes[0].model_copy(update={"beats": [beat]})
    pack = type(pack).seal(
        **pack.model_copy(update={"scenes": [scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    intent = BeatIntent(
        screen_axis="counter",
        screen_direction="STATIC",
        eyeline="Toward the letter.",
        action_handoff="Place the letter down.",
        sound_intent="Room tone.",
        edit_intent="Cut on the hand release.",
        framing="close-up",
    )
    with pytest.raises(ValueError, match="unknown beat output state entities"):
        compile_episode_pack(
            pack,
            approved_scope_hash=pack.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
            draft_mode=True,
        )

    future_pack = world.pack()
    beat = future_pack.scenes[0].beats[0].model_copy(update={"reveal_ids": ["mother-letter"]})
    scene = future_pack.scenes[0].model_copy(update={"beats": [beat]})
    future_pack = type(future_pack).seal(
        **future_pack.model_copy(update={"scenes": [scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    with pytest.raises(ValueError, match="before its planned episode"):
        compile_episode_pack(
            future_pack,
            approved_scope_hash=future_pack.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
            draft_mode=True,
        )


def test_directing_tracks_prop_handoff_state_event() -> None:
    world = PackWorld()
    pack = world.stateful_pack()
    event = StateEvent.seal(
        record_id=uuid4(),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        episode_id=pack.episode_id,
        sequence=1,
        entity_id="letter",
        field="holder",
        before="fon",
        after="lek",
        scene_id="market",
        effective_from_ms=135_000,
        effective_until_ms=150_000,
        evidence_sha256="a" * 64,
    )
    intents = {
        beat_id: BeatIntent(
            screen_axis="stall-counter",
            screen_direction="LEFT_TO_RIGHT",
            eyeline="Follow the letter from Fon to Lek.",
            action_handoff="Transfer the letter into Lek's left hand.",
            sound_intent="Paper movement under market room tone.",
            edit_intent="Match the hand position across the cut.",
            framing="insert-hands",
        )
        for beat_id in ("take-letter", "hand-letter")
    }
    manifest = compile_episode_pack(
        pack,
        approved_scope_hash=pack.approved_scope_hash,
        intents=intents,
        state_events=[event],
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    handoff_shots = [shot for shot in manifest.shots if shot.beat_id == "hand-letter"]
    assert any(event in shot.events for shot in handoff_shots)
    assert handoff_shots[-1].state_out[-1].value == "lek"


def test_directing_seeds_and_reconciles_scene_state_across_scenes() -> None:
    world = PackWorld()
    pack, event = _two_scene_handoff_pack(world)
    intents = {
        beat_id: BeatIntent(
            screen_axis="market-to-home",
            screen_direction="LEFT_TO_RIGHT",
            eyeline="Track the letter between the characters.",
            action_handoff="Continue holding the letter in the declared hand.",
            sound_intent="Carry room tone through the handoff.",
            edit_intent="Match the prop state across scenes.",
            framing="insert-hands",
        )
        for beat_id in ("take-letter", "hand-letter")
    }
    manifest = compile_episode_pack(
        pack,
        approved_scope_hash=pack.approved_scope_hash,
        intents=intents,
        state_events=[event],
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    first = [shot for shot in manifest.shots if shot.scene_id == "market"]
    second = [shot for shot in manifest.shots if shot.scene_id == "home"]
    assert first[0].state_in[0].value == "fon"
    assert first[-1].state_out[0].value == "fon"
    assert second[0].state_in[0].value == "fon"
    assert second[-1].state_out[0].value == "lek"

    bad_scene = pack.scenes[1].model_copy(
        update={"state_in": [StateValue(entity_id="letter", field="holder", value="lek")]}
    )
    contradictory_pack = type(pack).seal(
        **pack.model_copy(update={"scenes": [pack.scenes[0], bad_scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    with pytest.raises(ValueError, match="contradictory scene state-in"):
        compile_episode_pack(
            contradictory_pack,
            approved_scope_hash=contradictory_pack.approved_scope_hash,
            intents=intents,
            state_events=[event],
            secret_ledger=world.rich.secret_ledger,
            draft_mode=True,
        )

    bad_event = StateEvent.seal(
        record_id=uuid4(),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        episode_id=pack.episode_id,
        sequence=1,
        entity_id="letter",
        field="holder",
        before="lek",
        after="fon",
        scene_id="home",
        effective_from_ms=135_000,
        effective_until_ms=150_000,
        evidence_sha256="d" * 64,
    )
    with pytest.raises(ValueError, match="state event before-value contradicts current state"):
        compile_episode_pack(
            pack,
            approved_scope_hash=pack.approved_scope_hash,
            intents=intents,
            state_events=[bad_event],
            secret_ledger=world.rich.secret_ledger,
            draft_mode=True,
        )


def test_directing_invalidation_stays_with_changed_beat() -> None:
    world = PackWorld()
    pack = world.stateful_pack()
    event = StateEvent.seal(
        record_id=UUID("00000000-0000-4000-8000-000000000099"),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        episode_id=pack.episode_id,
        sequence=1,
        entity_id="letter",
        field="holder",
        before="fon",
        after="lek",
        scene_id="market",
        effective_from_ms=135_000,
        effective_until_ms=150_000,
        evidence_sha256="b" * 64,
    )
    intents = {
        beat_id: BeatIntent(
            screen_axis="stall-counter",
            screen_direction="LEFT_TO_RIGHT",
            eyeline="Follow the letter.",
            action_handoff="Keep the prop in the same hand.",
            sound_intent="Market room tone.",
            edit_intent="Match on action.",
            framing="insert-hands",
        )
        for beat_id in ("take-letter", "hand-letter")
    }
    original = compile_episode_pack(
        pack,
        approved_scope_hash=pack.approved_scope_hash,
        intents=intents,
        state_events=[event],
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    scene = pack.scenes[0]
    changed_beat = scene.beats[1].model_copy(
        update={"visible_action": "Fon passes the letter slowly to Lek."}
    )
    changed_scene = scene.model_copy(update={"beats": [scene.beats[0], changed_beat]})
    changed_pack = type(pack).seal(
        **pack.model_copy(update={"scenes": [changed_scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    changed = compile_episode_pack(
        changed_pack,
        approved_scope_hash=changed_pack.approved_scope_hash,
        intents=intents,
        state_events=[event],
        secret_ledger=world.rich.secret_ledger,
        draft_mode=True,
    )
    assert changed.pack_hash != original.pack_hash
    changed_hashes = {canonical_hash(scene.beats[1]), canonical_hash(changed_beat)}
    affected = set(invalidated_shot_ids(original, changed_hashes))
    assert affected
    assert {shot.beat_id for shot in original.shots if shot.shot_id in affected} == {"hand-letter"}


def test_directing_wardrobe_binding_matches_scene_day_setting_and_ids() -> None:
    world = PackWorld()
    pack = world.pack()
    intent = BeatIntent(
        screen_axis="stall-counter",
        screen_direction="STATIC",
        eyeline="Toward Fon.",
        action_handoff="Keep the action on the counter.",
        sound_intent="Market room tone.",
        edit_intent="Hold through the beat.",
        framing="medium-two-shot",
    )
    bound_pack, bibles, assignments = _wardrobe_fixture(pack)
    compiled = compile_episode_pack(
        bound_pack,
        approved_scope_hash=bound_pack.approved_scope_hash,
        intents={"find-letter": intent},
        secret_ledger=world.rich.secret_ledger,
        wardrobe_bibles=bibles,
        wardrobe_assignments=assignments,
    )
    assert compiled.shots

    next_day, bibles, assignments = _wardrobe_fixture(pack, day_offset=1)
    with pytest.raises(ValueError, match="story day or setting"):
        compile_episode_pack(
            next_day,
            approved_scope_hash=next_day.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
            wardrobe_bibles=bibles,
            wardrobe_assignments=assignments,
        )

    wrong_setting, bibles, assignments = _wardrobe_fixture(pack, setting_override="home")
    with pytest.raises(ValueError, match="story day or setting"):
        compile_episode_pack(
            wrong_setting,
            approved_scope_hash=wrong_setting.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
            wardrobe_bibles=bibles,
            wardrobe_assignments=assignments,
        )

    wrong_ids, bibles, assignments = _wardrobe_fixture(pack)
    scene = wrong_ids.scenes[0].model_copy(update={"wardrobe_assignment_ids": [uuid4()]})
    wrong_ids = type(wrong_ids).seal(
        **wrong_ids.model_copy(update={"scenes": [scene]}).model_dump(
            mode="python", exclude={"content_sha256"}
        )
    )
    with pytest.raises(ValueError, match="not declared by its scene"):
        compile_episode_pack(
            wrong_ids,
            approved_scope_hash=wrong_ids.approved_scope_hash,
            intents={"find-letter": intent},
            secret_ledger=world.rich.secret_ledger,
            wardrobe_bibles=bibles,
            wardrobe_assignments=assignments,
        )

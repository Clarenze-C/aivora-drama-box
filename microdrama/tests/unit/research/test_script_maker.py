from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import PriceSource, PriceUnit, RuntimeRole
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.examples import season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import ConceptIntake, PendingRightsAssessment
from microdrama.research import (
    ComparatorCorpus,
    ConceptDraft,
    ResearchConfig,
    ResearchRequest,
    ResearchTrigger,
    ScriptMakerService,
)
from microdrama.story import CandidateScopeBinding
from microdrama.testing.fakes import (
    FakeClock,
    FakeLLMProvider,
    LLMScenario,
    SequentialIds,
    fake_price_quote,
)

_NOW = datetime(2026, 10, 30, tzinfo=UTC)


def intake(episode_count: int = 2) -> ConceptIntake:
    return ConceptIntake.seal(
        record_id=uuid4(),
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        story_idea="ครอบครัวพยายามรักษาร้านอาหารเล็ก ๆ ของแม่",
        genre_tags=["family-drama"],
        tone="อบอุ่นแต่มีความลุ้น",
        requested_episode_count=episode_count,
    )


def candidate(title_th: str) -> dict:
    return {
        "title_th": title_th,
        "title_en": "The Last Market",
        "logline": "A family uncovers why their market stall is in danger.",
        "premise": "ครอบครัวหนึ่งพยายามช่วยร้านตลาดของแม่",
        "genre_tags": ["family-drama"],
        "originality_statement": "An original fictional story.",
        "arc": [
            {
                "episode_number": episode,
                "summary": f"จุดเปลี่ยนของเรื่องตอนที่ {episode}",
                "planned_reveals": ["ความลับที่วางแผนไว้"] if episode == 2 else [],
                "cliffhanger": "ใครบางคนมาถึง" if episode == 2 else None,
            }
            for episode in (1, 2)
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
            }
        ],
    }


def test_short_idea_generates_bounded_gate1_scopes_and_pending_rights() -> None:
    owner_intake = intake()
    season_id = uuid4()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    llm = FakeLLMProvider(clock=FakeClock(_NOW), ids=SequentialIds("script-maker-llm"))
    llm.script_role(
        RuntimeRole.STORY_ARCHITECT, {"candidates": [candidate("ตลาดสุดท้าย"), candidate("ร้านที่สอง")]}
    )
    budget = Mock()
    budget.reserve.side_effect = lambda req: SimpleNamespace(id=uuid4())
    prices = {
        "llm_input_price": PriceQuote(
            currency="USD",
            unit=PriceUnit.INPUT_TOKEN_1K,
            unit_price_micro_usd=2,
            source=PriceSource.FAKE_SYNTHETIC,
            price_table_version="test",
            as_of=_NOW,
        ),
        "llm_output_price": PriceQuote(
            currency="USD",
            unit=PriceUnit.OUTPUT_TOKEN_1K,
            unit_price_micro_usd=4,
            source=PriceSource.FAKE_SYNTHETIC,
            price_table_version="test",
            as_of=_NOW,
        ),
    }
    service = ScriptMakerService(
        FakeClock(_NOW),
        Settings(),
        budget=budget,
        llm=llm,
        config=ResearchConfig(llm_max_attempts=1, **prices),
    )

    result = service.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-submit-1"
    )

    assert result.status == "COMPLETED"
    assert len(result.candidates) == len(result.scopes) == 2
    assert result.research_drafts()[0].scope == result.scopes[0]
    assert all(scope.expected_episode_count == 2 for scope in result.scopes)
    assert all(scope.episode_min_duration_ms >= 180_000 for scope in result.scopes)
    assert all(isinstance(c.rights, PendingRightsAssessment) for c in result.candidates)
    assert budget.reserve.call_count == 2
    assert budget.record_usage.call_count == 2
    assert budget.release.call_count == 0

    template = ResearchRequest(
        trigger=ResearchTrigger.MANUAL,
        trigger_key="selected-candidate-run",
        allowed_source_ids=["public-example"],
        query_texts=[owner_intake.story_idea],
        comparator_corpus=ComparatorCorpus(scenes=["unrelated sample"]),
        candidate_concepts=[ConceptDraft(concept_id="placeholder", scope=result.scopes[0])],
    )
    selection = result.research_request(template, candidate_ids={result.candidates[1].record_id})
    assert len(selection.candidate_concepts) == 1
    assert selection.candidate_concepts[0].concept_id == str(result.candidates[1].record_id)

    proposal_id = uuid4()
    proposed_scope = result.scopes[1].model_copy(
        update={
            "scope_version": 2,
            "source_proposal_id": proposal_id,
            "research_evidence_refs": ["source:approved-public"],
            "uncertainty_notes": ["One source date is unknown."],
        }
    )
    research = Mock()
    research.proposal_scope.return_value = proposed_scope
    research_result = SimpleNamespace(
        proposal_id=proposal_id,
        outcome=SimpleNamespace(chosen_concept_id=str(result.candidates[1].record_id)),
    )
    bound = result.bind_gate1_proposal(research_result, research)
    chosen = bound.candidates[1]
    assert chosen.scope_sha256 == canonical_hash(proposed_scope)
    assert CandidateScopeBinding.from_candidate(
        owner_intake, chosen, proposed_scope
    ).scope_hash == canonical_hash(proposed_scope)


def test_missing_price_does_not_dispatch_or_reserve() -> None:
    owner_intake = intake()
    season_id = uuid4()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    llm = Mock()
    budget = Mock()
    service = ScriptMakerService(
        FakeClock(_NOW),
        Settings(),
        budget=budget,
        llm=llm,
        config=ResearchConfig(),
    )

    result = service.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-submit-2"
    )

    assert result.status == "NOT_DISPATCHED"
    llm.generate.assert_not_called()
    budget.reserve.assert_not_called()


def _priced_config(**overrides) -> ResearchConfig:
    defaults = {
        "llm_input_price": fake_price_quote(PriceUnit.INPUT_TOKEN_1K),
        "llm_output_price": fake_price_quote(PriceUnit.OUTPUT_TOKEN_1K),
    }
    defaults.update(overrides)
    return ResearchConfig(**defaults)


def _script_candidates(llm: FakeLLMProvider) -> None:
    llm.script_role(
        RuntimeRole.STORY_ARCHITECT,
        {"candidates": [candidate("ตลาดสุดท้าย"), candidate("ร้านที่สอง")]},
    )


def test_blank_idea_or_tone_is_refused_before_any_dispatch() -> None:
    season_id = uuid4()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    llm = Mock()
    budget = Mock()
    service = ScriptMakerService(
        FakeClock(_NOW), Settings(), budget=budget, llm=llm, config=_priced_config()
    )
    for field, payload in (
        ("story_idea", "   "),
        ("tone", "\t\n"),
    ):
        owner_intake = intake().model_copy(update={field: payload})
        with pytest.raises(SchemaInvalid, match=field.split("_")[0]):
            service.generate_candidates(
                season_id,
                owner_intake,
                scope_defaults=defaults,
                idempotency_key=f"blank-{field}",
            )
    llm.generate.assert_not_called()
    budget.reserve.assert_not_called()


def test_transient_provider_failure_fails_unbilled_and_holds_nothing(world) -> None:
    season_id = world.season()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    world.llm.queue_scenarios(*([LLMScenario.TRANSIENT_TIMEOUT] * 4))
    service = ScriptMakerService(
        world.clock,
        world.settings,
        budget=world.budget,
        llm=world.llm,
        config=_priced_config(llm_max_attempts=2, transport_attempts=2),
    )

    result = service.generate_candidates(
        season_id, intake(), scope_defaults=defaults, idempotency_key="intake-blank-fail"
    )

    assert result.status == "FAILED"
    assert result.settled_micro_usd == 0, "an unbilled failure must not claim spend"
    assert result.candidates == ()
    assert world.committed(season_id) == 0, "nothing stays held on the envelope"
    assert (
        world.count(
            "SELECT COUNT(*) FROM reservations WHERE season_id = %s AND state = 'ACTIVE'",
            (season_id,),
        )
        == 0
    )


def test_invalid_billed_output_keeps_its_charge_and_the_next_attempt_succeeds(world) -> None:
    season_id = world.season()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    _script_candidates(world.llm)
    world.llm.queue_scenarios(LLMScenario.MALFORMED_OUTPUT)
    service = ScriptMakerService(
        world.clock,
        world.settings,
        budget=world.budget,
        llm=world.llm,
        config=_priced_config(llm_max_attempts=2),
    )

    result = service.generate_candidates(
        season_id, intake(), scope_defaults=defaults, idempotency_key="intake-retry-1"
    )

    assert result.status == "COMPLETED"
    assert result.settled_micro_usd > 0
    # The invalid first attempt was billed and its charge is retained (MD-008).
    assert (
        world.count(
            "SELECT COUNT(*) FROM reservations WHERE season_id = %s AND state = 'SETTLED'",
            (season_id,),
        )
        == 4
    ), "both attempts' input and output holds settled"
    assert world.committed(season_id) == result.settled_micro_usd


def test_replayed_generation_adds_no_spend_or_reservations(world) -> None:
    season_id = world.season()
    defaults = season_scope().model_copy(
        update={"season_id": season_id, "expected_episode_count": 2}
    )
    _script_candidates(world.llm)
    service = ScriptMakerService(
        world.clock,
        world.settings,
        budget=world.budget,
        llm=world.llm,
        config=_priced_config(llm_max_attempts=2),
    )
    owner_intake = intake()

    first = service.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-replay-1"
    )
    assert first.status == "COMPLETED"
    committed = world.committed(season_id)
    reservations = world.count(
        "SELECT COUNT(*) FROM reservations WHERE season_id = %s", (season_id,)
    )

    second = service.generate_candidates(
        season_id, owner_intake, scope_defaults=defaults, idempotency_key="intake-replay-1"
    )

    assert second.status == "COMPLETED"
    assert second.settled_micro_usd == 0, "a replayed generation adds no spend"
    assert second.candidates == first.candidates
    assert world.committed(season_id) == committed
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE season_id = %s", (season_id,))
        == reservations
    )

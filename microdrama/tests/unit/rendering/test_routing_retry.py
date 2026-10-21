"""Ordinary retry accounting and failure-driven tier promotion (AT-07 acceptance)."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_routing_support import (
    REFERENCE_CONTROLS,
    RoutingWorld,
    measurements,
    preset_record,
    shot,
    standard_catalog_presets,
)

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind, RenderTier, ShotPattern
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.primitives import DEFAULT_LIMITS
from microdrama.persistence import Database
from microdrama.rendering.presets import PresetTierClass
from microdrama.rendering.routing import (
    AttemptCapReached,
    NoCompatiblePreset,
    attempt_semantic_key,
    route_id_for,
)

pytestmark = [pytest.mark.db]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> RoutingWorld:
    return RoutingWorld(db, tmp_path / "store")


def _failed_fast_insert_shot():
    return shot(
        pattern=ShotPattern.COMIC_REACTION,
        controls=(ControlKind.TEXT_PROMPT,),
        shot_id="sh7",
    )


def test_the_policy_cap_is_the_existing_contract_cap(world: RoutingWorld) -> None:
    """No second cap source: routing uses ProductionLimits, the same 3 the frozen
    RenderRequest enforces (and the RenderRequest itself still refuses attempt 4)."""
    assert world.router.policy.max_attempts_per_shot == DEFAULT_LIMITS.max_attempts_per_shot == 3
    request = dict(
        render_id=world.ids.new_id(),
        semantic_key="render.shot:ep1:sh9:attempt4",
        episode_id=world.ids.new_id(),
        episode_number=1,
        shot_id="sh9",
        manifest_version=1,
        attempt_number=4,
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        required_controls=[ControlKind.TEXT_PROMPT],
        workflow_sha256="0" * 64,
        seed=1,
        width=720,
        height=1280,
        fps=24,
        duration_ms=4_000,
        reservation_id=world.ids.new_id(),
        prompt_text="probe",
    )
    with pytest.raises(ValueError, match="maximum three paid generation attempts"):
        RenderRequest(**request)


def test_a_promotion_consumes_the_next_ordinary_attempt(world: RoutingWorld) -> None:
    """Acceptance: failure-driven tier promotion uses the EXISTING attempt cap."""
    world.seed_presets()
    episode = world.episode()
    failed = _failed_fast_insert_shot()
    promotion = world.router.plan_promotion(
        failed,
        episode_id=episode.episode_id,
        manifest_version=1,
        failed_attempt_number=1,
        failed_tier_class=PresetTierClass.FAST,
    )
    assert promotion.attempt_number == 2  # the ordinary next attempt
    assert promotion.promotion_from is PresetTierClass.FAST
    assert promotion.chosen is not None
    assert promotion.chosen.tier_class is PresetTierClass.QUALITY
    assert promotion.chosen.preset_id == "fake-quality-8step"
    # the semantic key is the ordinary attempt-2 key (house pattern)
    assert (
        attempt_semantic_key(1, failed.shot_id, 2) == f"render.shot:ep1:{failed.shot_id}:attempt2"
    )


def test_promotions_never_invent_attempts_past_the_cap(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    failed = _failed_fast_insert_shot()
    # attempts 1 (fast) and 2 (quality) are spent; promoting again would be attempt 4
    with pytest.raises(AttemptCapReached) as excinfo:
        world.router.plan_promotion(
            failed,
            episode_id=episode.episode_id,
            manifest_version=1,
            failed_attempt_number=3,
            failed_tier_class=PresetTierClass.QUALITY,
        )
    assert excinfo.value.details["cap"] == 3
    assert excinfo.value.details["attempt_number"] == 4
    # nothing was reserved or dispatched for the refused attempt
    assert world.operation_rows() == []


def test_a_promotion_from_the_terminal_class_is_refused(world: RoutingWorld) -> None:
    """CONTROL is terminal: the fallback edit path, not another paid attempt, follows."""
    world.seed_presets()
    episode = world.episode()
    failed = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
        shot_id="sh8",
    )
    with pytest.raises(NoCompatiblePreset, match="terminal"):
        world.router.plan_promotion(
            failed,
            episode_id=episode.episode_id,
            manifest_version=1,
            failed_attempt_number=3,
            failed_tier_class=PresetTierClass.CONTROL,
        )


def test_a_promotion_below_attempt_two_is_a_caller_bug(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    failed = _failed_fast_insert_shot()
    with pytest.raises(SchemaInvalid, match="next ordinary attempt"):
        world.router.route_shot(
            failed,
            episode_id=episode.episode_id,
            manifest_version=1,
            attempt_number=1,
            promotion_from=PresetTierClass.FAST,
        )


def test_attempt_numbers_outside_the_cap_are_refused_before_any_dispatch(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    with pytest.raises(AttemptCapReached):
        world.router.route_shot(
            reference_shot, episode_id=episode.episode_id, manifest_version=1, attempt_number=4
        )
    with pytest.raises(AttemptCapReached):
        world.router.route_shot(
            reference_shot, episode_id=episode.episode_id, manifest_version=1, attempt_number=0
        )
    assert world.operation_rows() == []


def test_the_promotion_decision_is_durable_with_its_accounting(world: RoutingWorld) -> None:
    world.seed_presets()
    episode = world.episode()
    failed = _failed_fast_insert_shot()
    world.router.route_shot(
        failed, episode_id=episode.episode_id, manifest_version=1, attempt_number=1
    )
    promotion = world.router.plan_promotion(
        failed,
        episode_id=episode.episode_id,
        manifest_version=1,
        failed_attempt_number=1,
        failed_tier_class=PresetTierClass.FAST,
    )
    events = world.routing_events(route_id_for(episode.episode_id, failed.shot_id, 1))
    assert len(events) == 2  # attempt 1, then the promoted attempt 2, same aggregate
    first_payload, promotion_payload = (e["payload"] for e in events)
    assert first_payload["attempt_number"] == 1
    assert "promotion_from" not in first_payload
    assert promotion_payload["attempt_number"] == 2
    assert promotion_payload["promotion_from"] == "fast"
    assert promotion_payload["max_attempts_per_shot"] == 3
    assert promotion.chosen is not None
    assert promotion_payload["chosen"]["preset_id"] == promotion.chosen.preset_id


def test_a_promotion_with_no_compatible_stronger_preset_is_refused_typed(
    world: RoutingWorld,
) -> None:
    """FAST failed and the only stronger mapped preset fails the gate: typed refusal.

    A CONTROL-class preset exists in the registry but has no PRESET_TEMPLATES mapping
    (T013-owned), so it cannot dispatch; the promotion is refused typed rather than
    falling back to a weaker or unmapped preset. Adding the mapping is a handoff
    proposal (see evidence/T014.md).
    """
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-fast-4step",
                tier=RenderTier.FAST_FOUR_STEP,
                controls=(ControlKind.TEXT_PROMPT, ControlKind.SEED),
                measured=measurements(cost_per_accepted_shot=200_000),
            ),
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(critical_quality_bp=1_000),  # fails the gate
            ),
        ]
    )
    episode = world.episode()
    failed = shot(
        pattern=ShotPattern.QUIET_CONFESSION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
        shot_id="sh10",
    )
    with pytest.raises(NoCompatiblePreset):
        world.router.plan_promotion(
            failed,
            episode_id=episode.episode_id,
            manifest_version=1,
            failed_attempt_number=1,
            failed_tier_class=PresetTierClass.FAST,
        )


def test_standard_catalog_is_rankable_for_every_pattern(world: RoutingWorld) -> None:
    """Smoke: each of the six pattern classes routes (or refuses typed) offline."""
    world.seed_presets(standard_catalog_presets())
    episode = world.episode()
    for pattern in ShotPattern:
        reference_shot = shot(
            pattern=pattern,
            controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
            shot_id=f"smoke-{pattern.value}",
        )
        decision = world.router.route_shot(
            reference_shot, episode_id=episode.episode_id, manifest_version=1
        )
        assert decision.chosen is not None
        assert decision.chosen.preset_id == "fake-quality-8step"

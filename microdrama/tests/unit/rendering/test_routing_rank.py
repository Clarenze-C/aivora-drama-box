"""Ranking by total accepted cost (never advertised speed) and the quality gates."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_routing_support import (
    REFERENCE_CONTROLS,
    TEXT_ONLY_CONTROLS,
    RoutingWorld,
    measurements,
    preset_record,
    shot,
)

from microdrama.contracts.enums import ControlKind, RenderTier, ShotPattern
from microdrama.persistence import Database
from microdrama.rendering.presets import EligibilityReason
from microdrama.rendering.routing import (
    ROUTE_DECISION_EVENT,
    NoCompatiblePreset,
    route_id_for,
)

pytestmark = [pytest.mark.db]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> RoutingWorld:
    return RoutingWorld(db, tmp_path / "store")


def test_ranking_uses_total_accepted_cost_not_advertised_speed(world: RoutingWorld) -> None:
    """Acceptance: ranks total accepted cost rather than advertised speed.

    ``fake-fast-4step`` advertises a 20s warm full job but costs 200k+0 per accepted
    shot; ``fake-quality-8step`` is slower (95s) yet cheaper per accepted shot
    (120k+10k). For a shot where both tier classes are allowed, the cheaper accepted
    cost must win — speed is a receipt fact, not a ranking input.
    """
    world.seed_presets()
    episode = world.episode()
    insert = shot(pattern=ShotPattern.PRACTICAL_PROP_ACTION, controls=(ControlKind.TEXT_PROMPT,))
    decision = world.router.route_shot(insert, episode_id=episode.episode_id, manifest_version=1)
    assert decision.chosen is not None
    assert decision.chosen.preset_id == "fake-quality-8step"
    assert decision.chosen.total_accepted_cost_micro_usd == 130_000
    fast = next(c for c in decision.ranked if c.preset_id == "fake-fast-4step")
    assert fast.warm_full_job_ms < decision.chosen.warm_full_job_ms  # it IS faster...
    assert fast.total_accepted_cost_micro_usd > decision.chosen.total_accepted_cost_micro_usd


def test_ranking_counts_downstream_repair_cost_in_the_total(world: RoutingWorld) -> None:
    """Same per-accepted-shot cost: the cheaper downstream repair tail ranks first."""
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(cost_per_accepted_shot=100_000, downstream_repair=50_000),
            ),
            preset_record(
                preset_id="fake-fast-4step",
                tier=RenderTier.FAST_FOUR_STEP,
                controls=TEXT_ONLY_CONTROLS,
                measured=measurements(cost_per_accepted_shot=100_000, downstream_repair=0),
            ),
        ]
    )
    episode = world.episode()
    text_insert = shot(controls=(ControlKind.TEXT_PROMPT,))
    decision = world.router.route_shot(
        text_insert, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
    assert decision.chosen.preset_id == "fake-fast-4step"
    assert [c.preset_id for c in decision.ranked] == ["fake-fast-4step", "fake-quality-8step"]
    assert decision.ranked[0].total_accepted_cost_micro_usd == 100_000
    assert decision.ranked[1].total_accepted_cost_micro_usd == 150_000


def test_ranking_breaks_cost_ties_deterministically_by_preset_id(world: RoutingWorld) -> None:
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(cost_per_accepted_shot=100_000, downstream_repair=10_000),
            ),
            preset_record(
                preset_id="fake-fast-4step",
                tier=RenderTier.FAST_FOUR_STEP,
                controls=TEXT_ONLY_CONTROLS,
                measured=measurements(cost_per_accepted_shot=110_000, downstream_repair=0),
            ),
        ]
    )
    episode = world.episode()
    text_insert = shot(controls=(ControlKind.TEXT_PROMPT,))
    decision = world.router.route_shot(
        text_insert, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
    # both total 110_000: the preset id decides, deterministically, in every process
    assert decision.chosen.preset_id == "fake-fast-4step"


def test_a_critical_shot_applies_the_quality_gate(world: RoutingWorld) -> None:
    """Emotional/dialogue shots need critical quality above the policy floor."""
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(critical_quality_bp=4_000),  # below 5_000 floor
            ),
        ]
    )
    episode = world.episode()
    confession = shot(
        pattern=ShotPattern.QUIET_CONFESSION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    with pytest.raises(NoCompatiblePreset) as excinfo:
        world.router.route_shot(confession, episode_id=episode.episode_id, manifest_version=1)
    reasons = {r["reason"] for r in excinfo.value.details["rejections"]}
    assert reasons == {"QUALITY_GATE"}


def test_a_dialogue_shot_is_critical_even_for_a_non_emotional_pattern(
    world: RoutingWorld,
) -> None:
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(critical_quality_bp=4_000),
            ),
        ]
    )
    episode = world.episode()
    talking_insert = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
        speakers=1,
    )
    with pytest.raises(NoCompatiblePreset):
        world.router.route_shot(talking_insert, episode_id=episode.episode_id, manifest_version=1)


def test_unmeasured_shot_class_acceptance_is_a_typed_unknown(world: RoutingWorld) -> None:
    """Acceptance for the shot's class missing/zero ⇒ CLASS_UNMEASURED, never eligible."""
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                # measured only for insert classes, not for the shot's class
                measured=measurements(shot_classes=("practical_prop_action_v1",)),
            ),
        ]
    )
    episode = world.episode()
    confession = shot(
        pattern=ShotPattern.QUIET_CONFESSION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    with pytest.raises(NoCompatiblePreset) as excinfo:
        world.router.route_shot(confession, episode_id=episode.episode_id, manifest_version=1)
    (rejection,) = excinfo.value.details["rejections"]
    assert rejection["reason"] == "CLASS_UNMEASURED"


def test_low_class_acceptance_fails_the_quality_gate(world: RoutingWorld) -> None:
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(acceptance_bp=500),  # below the 1_000 floor
            ),
        ]
    )
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    from microdrama.rendering.routing import NoCompatiblePreset

    with pytest.raises(NoCompatiblePreset) as excinfo:
        world.router.route_shot(reference_shot, episode_id=episode.episode_id, manifest_version=1)
    (rejection,) = excinfo.value.details["rejections"]
    assert rejection["reason"] == "QUALITY_GATE"
    assert "acceptance" in rejection["detail"]


def test_the_decision_receipt_carries_latency_and_cost_per_class(world: RoutingWorld) -> None:
    """Per-class latency/rejection receipts: cold/warm latencies live in the event."""
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    world.router.route_shot(reference_shot, episode_id=episode.episode_id, manifest_version=1)
    events = world.routing_events(route_id_for(episode.episode_id, reference_shot.shot_id, 1))
    assert [e["event_type"] for e in events] == [ROUTE_DECISION_EVENT]
    payload = events[0]["payload"]
    assert payload["shot_class"] == "practical_prop_action_v1"
    assert payload["critical"] is False
    chosen = payload["chosen"]
    assert chosen["cold_start_ms"] == 180_000
    assert chosen["warm_full_job_ms"] == 95_000
    assert chosen["total_accepted_cost_micro_usd"] == 130_000
    assert payload["ranked"] and payload["rejections"]
    assert payload["policy"] == {"critical_min_quality_bp": 5_000, "min_class_acceptance_bp": 1_000}


def test_rejections_and_rank_together_name_every_catalog_candidate(world: RoutingWorld) -> None:
    """Every current record appears exactly once across the rank table + rejections."""
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
    seen = [c.preset_id for c in decision.ranked] + [r.preset_id for r in decision.rejections]
    current = [record.preset_id for record in world.catalog.current_records()]
    assert sorted(seen) == sorted(current)
    # the unmapped control preset is rejected, the two mapped ones ranked/rejected
    assert set(seen) == {"fake-fast-4step", "fake-quality-8step", "fake-control-baseline"}
    assert decision.rejections[0].reason in {
        EligibilityReason.HARD_CONTROL,
        EligibilityReason.NO_TEMPLATE,
        EligibilityReason.TIER_POLICY,
    }

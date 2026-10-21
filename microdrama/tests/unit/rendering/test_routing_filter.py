"""The hard-control filter and typed rejections (T014 acceptance bullet 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_routing_support import (
    REFERENCE_CONTROLS,
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


def test_a_fast_text_only_route_is_rejected_when_references_are_required(
    world: RoutingWorld,
) -> None:
    """Acceptance: rejects a fast text-only route when references are required."""
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(
        pattern=ShotPattern.PRACTICAL_PROP_ACTION,
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE),
    )
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    fast_rejection = next(r for r in decision.rejections if r.preset_id == "fake-fast-4step")
    assert fast_rejection.reason is EligibilityReason.HARD_CONTROL
    assert "CHARACTER_REFERENCE" in fast_rejection.detail
    # the text-only fast preset is never chosen for a reference shot
    assert decision.chosen is not None
    assert decision.chosen.preset_id != "fake-fast-4step"
    # and the rejection is durable, not a log line
    events = world.routing_events(route_id_for(episode.episode_id, reference_shot.shot_id, 1))
    assert [e["event_type"] for e in events] == [ROUTE_DECISION_EVENT]
    payload = events[0]["payload"]
    assert any(
        r["reason"] == "HARD_CONTROL" and r["preset_id"] == "fake-fast-4step"
        for r in payload["rejections"]
    )


def test_the_same_fast_preset_is_eligible_for_a_text_only_insert(world: RoutingWorld) -> None:
    """The filter is per-shot: the fast preset routes fine when nothing requires refs."""
    world.seed_presets()
    episode = world.episode()
    text_only_shot = shot(
        pattern=ShotPattern.COMIC_REACTION,
        controls=(ControlKind.TEXT_PROMPT,),
    )
    decision = world.router.route_shot(
        text_only_shot, episode_id=episode.episode_id, manifest_version=1
    )
    assert decision.chosen is not None
    # the fast preset is eligible (ranked, not rejected) for a shot that needs no refs
    ranked_ids = [choice.preset_id for choice in decision.ranked]
    assert "fake-fast-4step" in ranked_ids
    assert not [r for r in decision.rejections if r.preset_id == "fake-fast-4step"]
    # the standard catalog's quality preset is still cheaper per accepted shot
    # (130k vs 210k), so accepted cost — not the fast preset's 20s advertised
    # warm job — decides the winner here too
    assert decision.chosen.preset_id == "fake-quality-8step"


def test_an_emotional_shot_never_takes_a_fast_tier_preset(world: RoutingWorld) -> None:
    """Tier policy fires even when the fast preset could carry the controls: this
    shot requires only TEXT_PROMPT, so the rejection is purely TIER_POLICY."""
    world.seed_presets()
    episode = world.episode()
    confession = shot(
        pattern=ShotPattern.QUIET_CONFESSION,
        controls=(ControlKind.TEXT_PROMPT,),
    )
    decision = world.router.route_shot(
        confession, episode_id=episode.episode_id, manifest_version=1
    )
    fast_rejection = next(r for r in decision.rejections if r.preset_id == "fake-fast-4step")
    assert fast_rejection.reason is EligibilityReason.TIER_POLICY
    assert decision.chosen is not None
    assert decision.chosen.preset_id == "fake-quality-8step"


def test_an_unmeasured_preset_is_never_eligible(world: RoutingWorld) -> None:
    """V-7 typed-unknown: unknown quality/cost can never route, even recorded+enabled-ish."""
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=None,
                enabled=False,  # the contract forbids enabled without measurements
            )
        ]
    )
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    with pytest.raises(NoCompatiblePreset) as excinfo:
        world.router.route_shot(reference_shot, episode_id=episode.episode_id, manifest_version=1)
    reasons = {r["reason"] for r in excinfo.value.details["rejections"]}
    assert "UNMEASURED" in reasons


def test_a_disabled_measured_preset_is_rejected_disabled(world: RoutingWorld) -> None:
    world.seed_presets(
        [
            preset_record(
                preset_id="fake-quality-8step",
                tier=RenderTier.QUALITY_EIGHT_STEP,
                controls=REFERENCE_CONTROLS,
                measured=measurements(),
                enabled=False,
            )
        ]
    )
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    with pytest.raises(NoCompatiblePreset):
        world.router.route_shot(reference_shot, episode_id=episode.episode_id, manifest_version=1)
    events = world.routing_events(route_id_for(episode.episode_id, reference_shot.shot_id, 1))
    rejections = events[0]["payload"]["rejections"]
    assert any(r["reason"] == "DISABLED" for r in rejections)
    assert events[0]["payload"]["chosen"] is None


def test_an_unmapped_preset_is_a_typed_no_template_rejection(world: RoutingWorld) -> None:
    """Preset→template mapping is T013-owned: unmapped ids are reported, not added."""
    world.seed_presets()
    episode = world.episode()
    reference_shot = shot(controls=(ControlKind.TEXT_PROMPT, ControlKind.CHARACTER_REFERENCE))
    decision = world.router.route_shot(
        reference_shot, episode_id=episode.episode_id, manifest_version=1
    )
    control_rejection = next(
        r for r in decision.rejections if r.preset_id == "fake-control-baseline"
    )
    assert control_rejection.reason is EligibilityReason.NO_TEMPLATE
    assert "handoff proposal" in control_rejection.detail


def test_no_compatible_preset_still_persists_the_rejection_receipt(
    world: RoutingWorld,
) -> None:
    world.seed_presets()
    episode = world.episode()
    # a control the no offline preset supports: camera motion
    impossible = shot(
        controls=(ControlKind.TEXT_PROMPT, ControlKind.CAMERA_MOTION),
    )
    with pytest.raises(NoCompatiblePreset):
        world.router.route_shot(impossible, episode_id=episode.episode_id, manifest_version=1)
    events = world.routing_events(route_id_for(episode.episode_id, impossible.shot_id, 1))
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["chosen"] is None
    assert json.dumps(payload["rejections"])  # every candidate has a typed reason
    assert {r["reason"] for r in payload["rejections"]} >= {
        "HARD_CONTROL",
        "NO_TEMPLATE",
    }

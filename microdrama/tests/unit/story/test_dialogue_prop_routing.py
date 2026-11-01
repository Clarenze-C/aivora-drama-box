"""V1 staging props compile into prop fields, never into wardrobe assignments."""

from __future__ import annotations

import copy

from story_support import World, canonical_writer_output

from microdrama.contracts.enums import RuntimeRole
from microdrama.story import WriteStatus


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    return world.episode(season_id, scope)


def test_scene_and_dialogue_props_reach_manifest_and_replay_is_free(world: World) -> None:
    episode_id = _ready(world)
    draft = copy.deepcopy(canonical_writer_output())
    draft["scenes"][0]["staging"]["prop_ids"] = ["prop-ledger"]
    draft["scenes"][0]["lines"][0]["staging"] = {"prop_ids": ["prop-letter"]}
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, draft)

    first = world.service.write_episode(episode_id)
    assert first.status is WriteStatus.CURRENT
    manifest = world.service.manifest(episode_id)

    establishing = next(
        shot for shot in manifest.shots if shot.scene_id == "sc1" and not shot.line_ids
    )
    dialogue = next(shot for shot in manifest.shots if "sc1-l1" in shot.line_ids)
    assert establishing.prop_ids == ["prop-ledger"]
    assert establishing.outfit_ids == []
    assert dialogue.prop_ids == ["prop-letter"]
    assert dialogue.outfit_ids == []

    # Normal story-write idempotency/budget path: replay must not call paid writer work.
    calls_after_first = world.generate_calls()
    second = world.service.write_episode(episode_id)
    assert second.status is WriteStatus.REPLAYED
    assert second.script_id == first.script_id
    assert second.settled_micro_usd == 0
    assert world.generate_calls() == calls_after_first
    assert world.service.manifest(episode_id).model_dump() == manifest.model_dump()


def test_absent_staging_prop_means_empty_prop_and_outfit_lists(world: World) -> None:
    episode_id = _ready(world)
    result = world.service.write_episode(episode_id)
    assert result.status is WriteStatus.CURRENT
    dialogue = next(
        shot for shot in world.service.manifest(episode_id).shots if "sc1-l1" in shot.line_ids
    )
    assert dialogue.prop_ids == []
    assert dialogue.outfit_ids == []


def test_malformed_prop_id_is_dropped_not_reinterpreted_as_outfit(world: World) -> None:
    episode_id = _ready(world)
    draft = copy.deepcopy(canonical_writer_output())
    draft["scenes"][0]["lines"][0]["staging"] = {"prop_ids": ["bad id", None]}
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, draft)

    result = world.service.write_episode(episode_id)
    assert result.status is WriteStatus.CURRENT
    dialogue = next(
        shot for shot in world.service.manifest(episode_id).shots if "sc1-l1" in shot.line_ids
    )
    assert dialogue.prop_ids == []
    assert dialogue.outfit_ids == []

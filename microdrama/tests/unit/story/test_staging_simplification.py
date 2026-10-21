"""Automatic staging simplification: unsupported staging simplified, change preserved."""

from __future__ import annotations

from story_support import World

from microdrama.contracts.enums import ControlKind, FallbackEdit, ShotPattern
from microdrama.story import WriteStatus


def _ready(world: World):
    season_id, scope = world.season()
    world.service.compile_season(season_id)
    episode_id = world.episode(season_id, scope)
    return episode_id


def test_unsupported_control_is_simplified_without_losing_the_dramatic_change(world: World) -> None:
    """The money line requests CAMERA_MOTION (unsupported) plus SEED (supported)."""
    episode_id = _ready(world)
    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT

    # The canonical draft's line sc1-l11 (the fifty-thousand-baht line) requests
    # CAMERA_MOTION + SEED; the compiled shot for it must keep SEED, drop CAMERA_MOTION.
    manifest = world.service.manifest(episode_id)
    shot = next(s for s in manifest.shots if "sc1-l11" in s.line_ids)
    controls = set(shot.required_identity_controls)
    assert ControlKind.CAMERA_MOTION not in controls, "unsupported control silently kept"
    assert ControlKind.SEED in controls, "supported control was lost"
    assert ControlKind.TEXT_PROMPT in controls
    assert shot.shot_pattern_id is ShotPattern.PRACTICAL_PROP_ACTION
    assert shot.fallback_edit is FallbackEdit.INSERT_STILL_WITH_AUDIO

    # The simplification is recorded and the dramatic change is preserved verbatim.
    assert len(outcome.simplifications) == 1
    recorded = outcome.simplifications[0]
    assert recorded.shot_id == shot.shot_id
    assert recorded.removed_controls == ["CAMERA_MOTION"]
    assert recorded.fallback_applied is FallbackEdit.INSERT_STILL_WITH_AUDIO
    assert "A visible result affects the decision" in recorded.preserved_change
    assert recorded.preserved_change in shot.purpose
    # Dialogue binding and importance survive the simplification.
    assert shot.line_ids == ["sc1-l11"]
    assert shot.dramatic_importance.value == "HIGH"
    event = world.events(episode_id, "story.script_written")[0]
    assert event["simplifications"][0]["shot_id"] == shot.shot_id


def test_supported_staging_is_kept_without_simplification(world: World) -> None:
    """Scene-level STYLE_REFERENCE is supported: the establishing shot keeps it."""
    episode_id = _ready(world)
    outcome = world.service.write_episode(episode_id)
    manifest = world.service.manifest(episode_id)

    establishing = manifest.shots[0]
    assert establishing.line_ids == []
    assert ControlKind.STYLE_REFERENCE in set(establishing.required_identity_controls)
    # Only the camera-motion line was simplified; nothing else.
    assert [s.shot_id for s in outcome.simplifications] == [
        s.shot_id for s in manifest.shots if "sc1-l11" in s.line_ids
    ]


def test_simplification_never_leaves_a_shot_without_controls(world: World) -> None:
    """A shot requesting an unsupported control alongside its base set still carries
    TEXT_PROMPT plus the supported identity controls (the contract minimum of one)."""
    episode_id = _ready(world)
    import copy

    from story_support import canonical_writer_output

    from microdrama.contracts.enums import RuntimeRole

    output = copy.deepcopy(canonical_writer_output())
    output["scenes"][0]["lines"][0]["controls"] = ["CAMERA_MOTION", "LAST_FRAME"]
    world.llm.script_role(RuntimeRole.STORY_ARCHITECT, output)

    outcome = world.service.write_episode(episode_id)
    assert outcome.status is WriteStatus.CURRENT
    manifest = world.service.manifest(episode_id)
    shot = next(s for s in manifest.shots if "sc1-l1" in s.line_ids)
    controls = set(shot.required_identity_controls)
    assert ControlKind.TEXT_PROMPT in controls
    assert ControlKind.LAST_FRAME in controls, "supported extra kept"
    assert ControlKind.CAMERA_MOTION not in controls
    # Camera motion is the only unsupported request here.
    assert [s.removed_controls for s in outcome.simplifications if s.shot_id == shot.shot_id] == [
        ["CAMERA_MOTION"]
    ]

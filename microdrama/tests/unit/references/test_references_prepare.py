"""T011 prepare: anchors, filled script/manifest, actual durations, replay, typed refusals."""

from __future__ import annotations

import uuid

import pytest
from references_support import SCENE_1_LINES, SCENE_2_LINES

from microdrama.contracts.enums import AssetKind, EpisodeState
from microdrama.contracts.errors import (
    Conflict,
    IdentityLockRequired,
    InvalidTransition,
    NotFound,
)
from microdrama.contracts.season import Script, ShotManifest
from microdrama.references import PrepareStatus, RefKind
from microdrama.testing.fakes.generation import voice_duration_ms


def test_prepare_creates_anchors_lines_and_fills_script_and_manifest(world):
    season_id, _scope, episode_id, outcome = world.prepared_episode()
    assert outcome.status is PrepareStatus.CURRENT
    assert outcome.script_version == 2 and outcome.manifest_version == 2
    # Anchors: style + 3 faces + 3 wardrobes + 3 voices + 2 locations = 12
    kinds = {a.ref_kind for a in outcome.anchors}
    assert kinds == {RefKind.STYLE, RefKind.FACE, RefKind.WARDROBE, RefKind.VOICE, RefKind.LOCATION}
    assert len(outcome.anchors) == 12
    assert len(outcome.lines) == len(SCENE_1_LINES) + len(SCENE_2_LINES)
    # Every line carries a voice id and a measured (actual) duration.
    for audio in outcome.lines:
        assert audio.voice_id.startswith("voice-")
        assert audio.actual_duration_ms == voice_duration_ms(
            next(t for lid, _s, t in [*SCENE_1_LINES, *SCENE_2_LINES] if lid == audio.line_id)
        )
    script = Script.model_validate(
        world.row(
            "SELECT body FROM scripts WHERE episode_id = %s AND status = 'CURRENT'", (episode_id,)
        )["body"]
    )
    assert all(
        line.voice_id and line.actual_duration_ms for scene in script.scenes for line in scene.lines
    )
    manifest = ShotManifest.model_validate(
        world.row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )["body"]
    )
    assert all(shot.voice_ids for shot in manifest.shots if shot.speaker_ids)
    assert all(shot.required_reference_asset_ids for shot in manifest.shots)
    assert all(shot.reference_lock_version is None for shot in manifest.shots)


def test_prepare_moves_the_episode_forward_and_emits_events(world):
    season_id, _scope, episode_id, _outcome = world.prepared_episode()
    assert world.episode_state(episode_id) == EpisodeState.RENDERING.value
    events = world.events(episode_id, "references.prepared")
    assert events and events[0]["anchors"] == 12
    claim = world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))
    assert claim["correlation_id"] is None


def test_prepare_registers_assets_and_reference_versions(world):
    season_id, _scope, episode_id, outcome = world.prepared_episode()
    for anchor in outcome.anchors:
        row = world.row("SELECT * FROM assets WHERE id = %s", (anchor.asset_id,))
        assert row is not None and row["state"] == "PROVISIONAL"
        version = world.row(
            "SELECT * FROM reference_versions WHERE asset_id = %s", (anchor.asset_id,)
        )
        assert version is not None
        assert version["state"] == "PROVISIONAL"
        assert version["reviewed_in_package_id"] is None
        kind = AssetKind.AUDIO if anchor.ref_kind is RefKind.VOICE else AssetKind.IMAGE
        assert row["asset_kind"] == kind.value
    voices = world.rows("SELECT * FROM voices WHERE season_id = %s", (season_id,))
    assert {v["voice_key"] for v in voices} == {"voice.fon", "voice.lek", "voice.nok"}
    assert all(v["state"] == "PROVISIONAL" for v in voices)


def test_prepare_is_idempotent_and_replays_without_paid_calls(world):
    season_id, _scope, episode_id, first = world.prepared_episode()
    image_calls = len(world.image.calls)
    voice_calls = len(world.voice.calls)
    second = world.service.prepare_episode(episode_id)
    assert second.status is PrepareStatus.REPLAYED
    assert second.script_version == first.script_version
    assert len(world.image.calls) == image_calls
    assert len(world.voice.calls) == voice_calls
    assert world.count("SELECT COUNT(*) FROM scripts WHERE episode_id = %s", (episode_id,)) == 2


def test_prepare_replays_line_audio_after_a_crash_between_generation_and_persist(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    world.service.prepare_episode(episode_id)
    # A re-write (new script version with open fields) replays the same line assets:
    # they are content-keyed, so no second paid synthesis of the same text happens.
    voice_calls = len(world.voice.calls)
    replayed = world.service.prepare_episode(episode_id)
    assert replayed.status is PrepareStatus.REPLAYED  # already filled: full replay
    assert len(world.voice.calls) == voice_calls


def test_prepare_refuses_episodes_without_a_script(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    with pytest.raises(NotFound):
        world.service.prepare_episode(episode_id)
    assert world.episode_state(episode_id) == EpisodeState.SCRIPTING.value


def test_prepare_refuses_wrong_states(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope, state="PLANNED")
    with pytest.raises(InvalidTransition):
        world.service.prepare_episode(episode_id)


def test_later_episode_without_the_lock_is_refused_before_any_dispatch(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope, number=2, state="SCRIPTING")
    with pytest.raises(IdentityLockRequired):
        world.service.prepare_episode(episode_id)
    # Nothing was paid, nothing claimed, no budget account opened.
    assert (
        world.count("SELECT COUNT(*) FROM reservations WHERE episode_id = %s", (episode_id,)) == 0
    )
    assert (
        world.count("SELECT COUNT(*) FROM budget_accounts WHERE episode_id = %s", (episode_id,))
        == 0
    )
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )


def test_render_bindings_refused_before_the_lock(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope, number=2, state="RENDERING")
    with pytest.raises(IdentityLockRequired):
        world.service.render_request_bindings(episode_id)


def test_prepare_refuses_a_live_claim_by_another_step(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    token = uuid.uuid4()
    with world.db.transaction() as tx:
        tx.execute("UPDATE episodes SET correlation_id = %s WHERE id = %s", (token, episode_id))
    with pytest.raises(Conflict):
        world.service.prepare_episode(episode_id)
    with world.db.transaction() as tx:
        tx.execute("UPDATE episodes SET correlation_id = NULL WHERE id = %s", (episode_id,))


def test_failed_prepare_releases_the_claim_and_persists_a_typed_event(world):
    season_id, scope = world.season()
    episode_id = world.episode(season_id, scope)
    world.seed_script_and_manifest(episode_id=episode_id, scope=scope)
    # Every anchor submit is refused on rights grounds by the provider.
    from microdrama.testing.fakes.generation import GenerationScenario

    world.image.queue_scenarios(*[GenerationScenario.DENIED_RIGHTS] * 20)
    from microdrama.contracts.errors import RightsUncleared

    with pytest.raises(RightsUncleared):
        world.service.prepare_episode(episode_id)
    assert world.episode_state(episode_id) == EpisodeState.REFERENCES.value
    assert (
        world.row("SELECT correlation_id FROM episodes WHERE id = %s", (episode_id,))[
            "correlation_id"
        ]
        is None
    )
    events = world.events(episode_id, "references.prepare_failed")
    assert events and events[0]["error_code"] == "RIGHTS_UNCLEARED"

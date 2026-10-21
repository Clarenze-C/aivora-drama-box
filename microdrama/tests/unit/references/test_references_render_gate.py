"""T011 render gate: pre-lock denial, bindings, and the RenderRequest contract edge."""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind, RenderTier
from microdrama.contracts.errors import Conflict, IdentityLockRequired, NotFound
from microdrama.contracts.hashing import sha256_hex


def test_episode_one_renders_without_a_lock_via_bindings(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    bindings = world.service.render_request_bindings(ep1)
    assert bindings.lock_id is None and bindings.lock_version is None
    assert bindings.reference_asset_ids  # style/faces/wardrobes/locations bound
    assert bindings.provisional_ref_keys == [] and bindings.locked_ref_keys == []


def test_later_episode_render_denied_before_the_lock(world):
    season_id, scope = world.season()
    ep2 = world.episode(season_id, scope, number=2, state="RENDERING")
    with pytest.raises(IdentityLockRequired) as refused:
        world.service.render_request_bindings(ep2)
    assert "episode one has not been approved" in refused.value.details["hint"]


def test_render_request_contract_itself_refuses_later_episodes_without_a_lock(world):
    season_id, scope = world.season()
    ep2 = world.episode(season_id, scope, number=2, state="RENDERING")
    with pytest.raises(Exception, match="IMP-01"):
        RenderRequest(
            render_id=uuid.uuid4(),
            semantic_key="render.shot:ep2:sh1:attempt1",
            episode_id=ep2,
            episode_number=2,
            shot_id="sh1",
            manifest_version=1,
            attempt_number=1,
            preset_id="preset-x",
            tier=RenderTier.QUALITY_EIGHT_STEP,
            required_controls=[ControlKind.TEXT_PROMPT],
            reference_asset_ids=[],
            audio_asset_id=None,
            identity_lock_id=None,  # IMP-01: refused by the frozen contract itself
            workflow_sha256=sha256_hex(b"workflow"),
            seed=1,
            width=720,
            height=1280,
            fps=24,
            duration_ms=6_000,
            reservation_id=uuid.uuid4(),
            prompt_text="fon at the stall",
        )


def test_bindings_refuse_unprepared_references(world):
    season_id, scope = world.season()
    ep1 = world.episode(season_id, scope, state="RENDERING")
    world.seed_script_and_manifest(episode_id=ep1, scope=scope)
    with pytest.raises(Conflict):
        world.service.render_request_bindings(ep1)


def test_bindings_list_locked_and_provisional_keys_for_later_episodes(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    world.to_awaiting_review(ep1)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=ep1)
    world.service.mark_reviewed_in_package(ep1)
    world.approve_episode(ep1, package)
    lock = world.service.current_lock(season_id)

    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    world.service.prepare_episode(ep2)
    bindings = world.service.render_request_bindings(ep2)
    assert bindings.lock_id == lock.lock_id
    assert bindings.lock_version == 1
    assert bindings.locked_ref_keys  # the whole reviewed cast is locked
    assert bindings.provisional_ref_keys == []  # nothing new was introduced
    # Every bound asset exists and verifies in the private store.
    for asset_id in bindings.reference_asset_ids:
        row = world.row("SELECT object_key, sha256 FROM assets WHERE id = %s", (asset_id,))
        assert row is not None
        assert world.store.verify(row["object_key"], row["sha256"])


def test_bindings_refuse_unknown_episodes(world):
    with pytest.raises(NotFound):
        world.service.render_request_bindings(uuid.uuid4())


def test_manifest_of_later_episode_carries_the_lock_version(world):
    from microdrama.contracts.season import ShotManifest

    season_id, scope, ep1, _outcome = world.prepared_episode()
    world.to_awaiting_review(ep1)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=ep1)
    world.service.mark_reviewed_in_package(ep1)
    world.approve_episode(ep1, package)
    lock = world.service.current_lock(season_id)
    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    world.service.prepare_episode(ep2)
    manifest = ShotManifest.model_validate(
        world.row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (ep2,),
        )["body"]
    )
    assert manifest.identity_lock_id == lock.lock_id
    assert all(shot.reference_lock_version == 1 for shot in manifest.shots)

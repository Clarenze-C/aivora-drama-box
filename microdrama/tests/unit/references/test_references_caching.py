"""T011 full-key caching: identical inputs are generated and paid once per season."""

from __future__ import annotations

from microdrama.contracts.enums import Provenance
from microdrama.references import RefKind
from microdrama.references import anchors as A
from microdrama.references.models import AnchorSpec


def _approve_episode_one(world, season_id, scope, episode_id):
    revision = world.to_awaiting_review(episode_id)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=episode_id)
    world.service.mark_reviewed_in_package(episode_id)
    world.approve_episode(episode_id, package, revision)
    return world.service.current_lock(season_id)


def _submits(provider) -> int:
    return sum(1 for call in provider.calls if call.method == "submit")


def test_second_episode_reuses_season_anchors_without_paid_calls(world):
    season_id, scope, ep1, _first = world.prepared_episode(number=1)
    ep1_image_submits = _submits(world.image)
    ep1_voice_submits = _submits(world.voice)
    lock = _approve_episode_one(world, season_id, scope, ep1)
    assert lock is not None

    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    second = world.service.prepare_episode(ep2)
    assert second.status is not None
    # Same season, same prompts: every image anchor is a cache hit (zero new image
    # submits) and the three voice anchors replay; only the six new dialogue lines of
    # episode two are new paid syntheses.
    assert _submits(world.image) == ep1_image_submits
    assert _submits(world.voice) == ep1_voice_submits + 6
    # The reference rows are shared, not duplicated.
    assert (
        world.count("SELECT COUNT(*) FROM reference_versions WHERE season_id = %s", (season_id,))
        == 12
    )
    assert second.settled_micro_usd > 0  # the six line syntheses settled


def test_locked_keys_resolve_to_the_locked_versions(world):
    season_id, scope, ep1, _first = world.prepared_episode(number=1)
    lock = _approve_episode_one(world, season_id, scope, ep1)

    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    outcome = world.service.prepare_episode(ep2)
    fon_locked = next(
        m for m in lock.members if m.ref_kind is RefKind.FACE and m.character_key == "fon"
    )
    fon_used = next(
        a for a in outcome.anchors if a.ref_kind is RefKind.FACE and a.ref_key == "face.fon"
    )
    assert fon_used.asset_id == fon_locked.asset_id
    assert fon_used.state == "LOCKED"
    assert outcome.reference_lock_version == lock.version
    bindings = world.service.render_request_bindings(ep2)
    assert bindings.lock_version == lock.version
    assert "FACE:face.fon" in bindings.locked_ref_keys


def test_cache_key_covers_every_input_that_changes_the_bytes(world):
    season_id, scope = world.season()
    base = dict(
        ref_kind=RefKind.STYLE,
        ref_key="style.season",
        prompt="style anchor",
        width=64,
        height=64,
        seed=7,
        lineage_asset_ids=[],
    )
    ref = world.service.config.image_model_config_ref
    route = world.service.config.image_rights_route_id
    key = A.anchor_cache_key(AnchorSpec(**base), model_config_ref=ref, rights_route_id=route)
    # Not deduped by text alone: model, rights route, size, seed and lineage all count.
    for changed in (
        {"prompt": "style anchor v2"},
        {"width": 32},
        {"height": 32},
        {"seed": 8},
        {"lineage_asset_ids": [A.ref_id_for("x", "y")]},
    ):
        other = A.anchor_cache_key(
            AnchorSpec(**{**base, **changed}), model_config_ref=ref, rights_route_id=route
        )
        assert other != key
    other_model = A.anchor_cache_key(
        AnchorSpec(**base), model_config_ref="ref-anchor-image-v2", rights_route_id=route
    )
    other_route = A.anchor_cache_key(
        AnchorSpec(**base), model_config_ref=ref, rights_route_id="route-ref-image-alt"
    )
    assert other_model != key and other_route != key


def test_one_version_per_cache_key_per_season(world):
    season_id, _scope, episode_id, _outcome = world.prepared_episode()
    # The UNIQUE (season, cache_key) held through a full preparation.
    rows = world.rows(
        "SELECT cache_key, COUNT(*) AS n FROM reference_versions WHERE season_id = %s "
        "GROUP BY cache_key HAVING COUNT(*) > 1",
        (season_id,),
    )
    assert rows == []


def test_changed_prompt_misses_the_cache_and_versions_the_reference(world):
    season_id, scope, ep1, _first = world.prepared_episode()
    image_submits = _submits(world.image)
    changed = world.service.explicit_change(
        ep1,
        RefKind.LOCATION,
        "location.stall",
        new_prompt="set anchor for location stall: night version, moody practical lights",
        reason="operator wants the stall at night",
    )
    assert changed.superseded_version == 1
    assert changed.new_version == 2
    assert changed.new_asset_id is not None
    assert _submits(world.image) == image_submits + 1
    old = world.row(
        "SELECT state FROM reference_versions WHERE season_id = %s "
        "AND ref_key = 'location.stall' AND version = 1",
        (season_id,),
    )
    assert old["state"] == "SUPERSEDED"
    new = world.row(
        "SELECT state FROM reference_versions WHERE season_id = %s "
        "AND ref_key = 'location.stall' AND version = 2",
        (season_id,),
    )
    assert new["state"] == "PROVISIONAL"


def test_cached_anchor_bytes_are_persisted_and_verifiable(world):
    season_id, _scope, episode_id, outcome = world.prepared_episode()
    for anchor in outcome.anchors:
        row = world.row("SELECT object_key FROM assets WHERE id = %s", (anchor.asset_id,))
        data = world.store.get_bytes(row["object_key"])
        assert data  # real bytes in the private store, never a URL
    descriptors = world.rows(
        "SELECT provenance FROM assets WHERE id = ANY(%s)",
        ([a.asset_id for a in outcome.anchors],),
    )
    assert all(d["provenance"] == Provenance.FAKE_SYNTHETIC.value for d in descriptors)

"""T011 explicit changes: versioning, dependent invalidation, never-lockable invalidated."""

from __future__ import annotations

import pytest

from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.references import RefKind


def _approve_full(world, season_id, scope, episode_id):
    world.to_awaiting_review(episode_id)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=episode_id)
    world.service.mark_reviewed_in_package(episode_id)
    world.approve_episode(episode_id, package)
    return package


def test_explicit_change_supersedes_the_version_and_invalidates_dependents(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    changed = world.service.explicit_change(
        episode_id,
        RefKind.STYLE,
        "style.season",
        new_prompt="style anchor: Mother's Chicken Rice Stall — warmer palette, soft noon light",
        reason="operator wants a warmer look",
    )
    assert changed.superseded_version == 1
    assert changed.new_version == 2
    # The style change invalidates every version derived from the style asset
    # (faces/wardrobes/locations carry it in their lineage).
    invalidated = set(changed.invalidated_ref_keys)
    assert "FACE:face.fon" in invalidated
    assert "WARDROBE:wardrobe.lek.1" in invalidated
    assert "LOCATION:location.stall" in invalidated
    assert len(invalidated) == 8  # 3 faces + 3 wardrobes + 2 locations (voices derive
    # from text, not the style image: they are not dependents)
    superseded = world.rows(
        "SELECT ref_key FROM reference_versions WHERE season_id = %s AND state = 'SUPERSEDED'",
        (season_id,),
    )
    assert len(superseded) == 9  # the style itself + its 8 image dependents
    assert (
        world.count(
            "SELECT COUNT(*) FROM reference_versions WHERE season_id = %s AND state = 'PROVISIONAL'",
            (season_id,),
        )
        == 4
    )  # the new style v2 + the three voice anchors (not style dependents)


def test_an_invalidated_version_can_never_be_locked(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    # Supersede fon's face BEFORE the gate: it can no longer be reviewed/locked.
    world.service.explicit_change(
        episode_id,
        RefKind.FACE,
        "face.fon",
        new_prompt="face anchor: Fon (ฝน), lead. Softer jaw, tired eyes, late twenties",
        reason="operator recast note",
    )
    live_fon = world.row(
        "SELECT asset_id FROM reference_versions WHERE season_id = %s "
        "AND ref_key = 'face.fon' AND state = 'PROVISIONAL'",
        (season_id,),
    )
    world.to_awaiting_review(episode_id)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=episode_id)
    world.service.mark_reviewed_in_package(episode_id)
    # The superseded v1 is marked SUPERSEDED — mark_reviewed skips it (PROVISIONAL
    # only), so the lock excludes it even though its asset is in the cast.
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE reference_versions SET state = 'ACCEPTED', reviewed_in_package_id = %s "
            "WHERE season_id = %s AND ref_key = 'face.fon' AND version = 1",
            (
                world.row(
                    "SELECT id FROM release_packages WHERE episode_id = %s "
                    "ORDER BY version DESC LIMIT 1",
                    (episode_id,),
                )["id"],
                season_id,
            ),
        )
    world.approve_episode(episode_id, package)
    lock = world.service.current_lock(season_id)
    fon_members = [m for m in lock.members if m.ref_key == "face.fon"]
    assert [m.version for m in fon_members] == [2]  # only the live v2 locked
    assert live_fon is not None


def test_pre_approval_change_rides_the_ordinary_final_gate(world):
    from microdrama.review.service import is_material_change

    season_id, scope, episode_id, _outcome = world.prepared_episode()
    world.to_awaiting_review(episode_id)
    package_v1 = world.store_review_package(
        season_id=season_id, scope=scope, episode_id=episode_id, version=1
    )
    world.service.explicit_change(
        episode_id,
        RefKind.LOCATION,
        "location.stall",
        new_prompt="set anchor for location stall: night version, moody practical lights",
        reason="operator wants the stall at night",
    )
    package_v2 = world.store_review_package(
        season_id=season_id, scope=scope, episode_id=episode_id, version=2
    )
    # Cast assets are material to the release package: the changed episode needs its
    # ordinary Gate 2 decision — no new approval type exists or is needed.
    assert is_material_change(package_v1, package_v2)
    assert set(package_v1.cast_package_asset_ids) != set(package_v2.cast_package_asset_ids)


def test_change_after_lock_breaks_the_lock_for_later_renders(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    _approve_full(world, season_id, scope, ep1)
    lock = world.service.current_lock(season_id)
    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    world.service.prepare_episode(ep2)
    assert world.service.render_request_bindings(ep2).lock_version == 1
    # An explicit change to a LOCKED version is allowed (the operator asked for it)
    # — carried by a pre-approval episode — but it breaks the lock: later-episode
    # renders refuse until a new Gate 2 approval mints a new lock version.
    world.service.explicit_change(
        ep2,
        RefKind.FACE,
        "face.fon",
        new_prompt="face anchor: Fon (ฝน), lead. Rain-soaked look for the finale arc",
        reason="finale arc refresh",
    )
    with pytest.raises(Conflict):
        world.service.render_request_bindings(ep2)
    fresh_lock = world.service.current_lock(season_id)
    member = next(m for m in fresh_lock.members if m.ref_key == "face.fon")
    assert member.state == "SUPERSEDED"


def test_change_requires_a_reason_and_real_content(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    with pytest.raises(SchemaInvalid):
        world.service.explicit_change(
            episode_id, RefKind.STYLE, "style.season", new_prompt="x", reason="   "
        )
    with pytest.raises(NotFound):
        world.service.explicit_change(
            episode_id,
            RefKind.LOCATION,
            "location.never-planned",
            new_prompt="anything",
            reason="unknown key",
        )


def test_invalidated_voice_anchor_versions_are_tracked_not_deleted(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    world.service.explicit_change(
        episode_id,
        RefKind.VOICE,
        "voice.fon",
        new_prompt="เสียงฝนเวอร์ชันใหม่ นิ่งและอบอุ่นกว่าเดิม",
        reason="voice direction update",
    )
    # Both versions remain auditable; the table is append-only by design.
    versions = world.rows(
        "SELECT version, state FROM reference_versions WHERE season_id = %s "
        "AND ref_key = 'voice.fon' ORDER BY version",
        (season_id,),
    )
    assert [v["state"] for v in versions] == ["SUPERSEDED", "PROVISIONAL"]
    events = world.events(season_id, "references.explicit_change")
    assert events and events[0]["ref_kind"] == "VOICE"

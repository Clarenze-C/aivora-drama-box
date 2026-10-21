"""T011 identity lock: the real Gate 2 hook, reviewed-only locking, non-inheritance."""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.enums import ApprovalAction, GateType
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.season import ApprovalCommand, IdentityLock
from microdrama.core.hooks import ApprovalHook


def _approve_episode_one(world, season_id, scope, episode_id, *, cast=None):
    world.to_awaiting_review(episode_id)
    package = world.store_review_package(
        season_id=season_id, scope=scope, episode_id=episode_id, cast=cast
    )
    marked = world.service.mark_reviewed_in_package(episode_id)
    result = world.approve_episode(episode_id, package)
    return package, marked, result


def test_gate2_approval_locks_included_reviewed_versions_atomically(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    ep_existing = world.episode(season_id, scope, number=2, state="PLANNED")
    package, marked, _result = _approve_episode_one(world, season_id, scope, episode_id)
    assert marked == 12
    lock = world.service.current_lock(season_id)
    assert lock is not None and lock.version == 1
    assert lock.source_episode_id == episode_id
    assert lock.release_package_hash == package.package_hash
    assert len(lock.members) == 12
    assert all(m.state == "LOCKED" for m in lock.members)
    # The locked assets are exactly the reviewed cast assets of the approved package.
    assert {m.asset_id for m in lock.members} == set(package.cast_package_asset_ids)
    # Reference versions, voices and characters moved to LOCKED.
    assert (
        world.count(
            "SELECT COUNT(*) FROM reference_versions WHERE season_id = %s AND state = 'LOCKED'",
            (season_id,),
        )
        == 12
    )
    assert (
        world.count(
            "SELECT COUNT(*) FROM voices WHERE season_id = %s AND state = 'LOCKED'", (season_id,)
        )
        == 3
    )
    assert (
        world.count(
            "SELECT COUNT(*) FROM characters WHERE season_id = %s AND state = 'LOCKED'",
            (season_id,),
        )
        == 3
    )
    body = world.row("SELECT body FROM identity_locks WHERE id = %s", (lock.lock_id,))["body"]
    validated = IdentityLock.model_validate(body)
    assert len(validated.locked_assets) == 12
    # Episodes that existed at approval time are stamped with the lock; ones created
    # later adopt it explicitly (attach_identity_lock).
    assert (
        world.row("SELECT identity_lock_id FROM episodes WHERE id = %s", (ep_existing,))[
            "identity_lock_id"
        ]
        == lock.lock_id
    )
    ep_created_after = world.episode(season_id, scope, number=3, state="PLANNED")
    assert world.service.attach_identity_lock(ep_created_after) == lock.lock_id


def test_unreviewed_cast_never_inherits_the_lock(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    # Review and include only fon's face: everything else stays PROVISIONAL and out.
    fon_face = world.row(
        "SELECT asset_id FROM reference_versions WHERE season_id = %s "
        "AND ref_kind = 'FACE' AND ref_key = 'face.fon'",
        (season_id,),
    )["asset_id"]
    package, marked, _result = _approve_episode_one(
        world, season_id, scope, episode_id, cast=[fon_face]
    )
    assert marked == 1
    lock = world.service.current_lock(season_id)
    assert lock is not None
    assert [m.ref_key for m in lock.members] == ["face.fon"]
    # The unreviewed eleven stay PROVISIONAL (they never inherit LOCKED).
    assert (
        world.count(
            "SELECT COUNT(*) FROM reference_versions WHERE season_id = %s "
            "AND state = 'PROVISIONAL'",
            (season_id,),
        )
        == 11
    )
    assert (
        world.count(
            "SELECT COUNT(*) FROM characters WHERE season_id = %s AND state = 'LOCKED'",
            (season_id,),
        )
        == 1
    )  # fon only: lek/nok have no locked identity member


def test_new_unseen_cast_in_episode_two_stays_provisional_outside_the_lock(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    fon_face = world.row(
        "SELECT asset_id FROM reference_versions WHERE season_id = %s "
        "AND ref_kind = 'FACE' AND ref_key = 'face.fon'",
        (season_id,),
    )["asset_id"]
    _approve_episode_one(world, season_id, scope, ep1, cast=[fon_face])
    lock = world.service.current_lock(season_id)

    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    outcome = world.service.prepare_episode(ep2)
    # fon's face resolves to the LOCKED version; lek and nok were never reviewed in
    # the approved package, so their anchors stay provisional and outside the lock.
    bindings = world.service.render_request_bindings(ep2)
    assert bindings.locked_ref_keys == ["FACE:face.fon"]
    assert "FACE:face.lek" in bindings.provisional_ref_keys
    assert all(m.state == "LOCKED" for m in lock.members)
    lek = next(a for a in outcome.anchors if a.ref_key == "face.lek")
    nok = next(a for a in outcome.anchors if a.ref_key == "face.nok")
    assert lek.state == "PROVISIONAL" and nok.state == "PROVISIONAL"
    assert nok.asset_id not in {m.asset_id for m in lock.members}


def test_hook_refusal_rolls_back_the_whole_approval(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    world.to_awaiting_review(episode_id)
    package = world.store_review_package(season_id=season_id, scope=scope, episode_id=episode_id)
    # No mark_reviewed call: the package's cast assets are all unreviewed, so the
    # hook refuses and the approval transaction rolls back whole.
    with pytest.raises(Conflict):
        world.approve_episode(episode_id, package)
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (episode_id,)) == 0
    )
    assert (
        world.count("SELECT COUNT(*) FROM identity_locks WHERE season_id = %s", (season_id,)) == 0
    )
    assert world.episode_state(episode_id) == "AWAITING_FINAL_REVIEW"
    status = world.row(
        "SELECT status FROM release_packages WHERE episode_id = %s ORDER BY version DESC",
        (episode_id,),
    )
    assert status["status"] == "READY"  # the APPROVED write rolled back too


def test_replayed_approval_never_locks_twice(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    package, _marked, result = _approve_episode_one(world, season_id, scope, episode_id)
    assert result.status_code == 202
    # A second, differently-keyed APPROVE of the now-RELEASE_APPROVED episode is a
    # typed conflict on the frozen state machine — the hook never runs twice.
    with pytest.raises(Conflict):
        world.approve_episode(episode_id, package)
    assert (
        world.count("SELECT COUNT(*) FROM identity_locks WHERE season_id = %s", (season_id,)) == 1
    )


def test_the_hook_satisfies_the_frozen_approval_hook_protocol(world):
    hook = world.service.identity_lock_hook()
    assert isinstance(hook, ApprovalHook)


def test_hook_refuses_non_approval_commands(world):
    season_id, scope, episode_id, _outcome = world.prepared_episode()
    hook = world.service.identity_lock_hook()
    revise = ApprovalCommand(
        gate=GateType.EPISODE_FINAL,
        action=ApprovalAction.REVISE,
        entity_id=episode_id,
        expected_revision=1,
        package_hash="0" * 64,
        idempotency_key="hook-refuses-revise",
        feedback=[
            {
                "category": "identity_voice",
                "start_ms": 0,
                "end_ms": 1000,
                "comment": "fon sounds too young",
            }
        ],
    )
    with pytest.raises(SchemaInvalid):
        with world.db.transaction() as tx:
            hook.on_recorded(
                tx,
                approval_event_id=uuid.uuid4(),
                command=revise,
                principal=world.human(),
            )


def test_attach_identity_lock_adopts_the_season_lock_for_new_episodes(world):
    season_id, scope, ep1, _outcome = world.prepared_episode()
    _approve_episode_one(world, season_id, scope, ep1, cast=None)
    lock = world.service.current_lock(season_id)
    # An episode created AFTER the lock has no stamp yet.
    ep3 = world.episode(season_id, scope, number=3, state="PLANNED")
    assert (
        world.row("SELECT identity_lock_id FROM episodes WHERE id = %s", (ep3,))["identity_lock_id"]
        is None
    )
    adopted = world.service.attach_identity_lock(ep3)
    assert adopted == lock.lock_id


def test_attach_identity_lock_without_a_season_lock_is_typed(world):
    from microdrama.contracts.errors import IdentityLockRequired

    season_id, scope = world.season()
    ep2 = world.episode(season_id, scope, number=2, state="PLANNED")
    with pytest.raises(IdentityLockRequired):
        world.service.attach_identity_lock(ep2)


def test_locked_anchor_used_by_a_broken_lock_state_is_refused(world):
    """A lock member that left LOCKED state breaks the lock for later episodes."""
    season_id, scope, ep1, _outcome = world.prepared_episode()
    _approve_episode_one(world, season_id, scope, ep1)
    lock = world.service.current_lock(season_id)
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE reference_versions SET state = 'SUPERSEDED' WHERE season_id = %s "
            "AND ref_key = 'face.fon'",
            (season_id,),
        )
    ep2 = world.episode(
        season_id, scope, number=2, state="SCRIPTING", identity_lock_id=lock.lock_id
    )
    world.seed_script_and_manifest(
        episode_id=ep2, scope=scope, number=2, identity_lock_id=lock.lock_id
    )
    with pytest.raises(Conflict):
        world.service.prepare_episode(ep2)  # refuses to silently change fon's identity
    with pytest.raises(Conflict):
        world.service.render_request_bindings(ep2)

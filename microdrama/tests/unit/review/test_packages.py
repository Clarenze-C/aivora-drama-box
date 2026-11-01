"""Release package storage: one current version per episode, immutable content, status rules."""

import pytest
from review_support import World

from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.examples import v2_owner_approved_release_approval_manifest
from microdrama.contracts.season import ApprovalCommand
from microdrama.contracts.v2 import ApprovedSlotMetadata, ReleaseApprovalManifest
from microdrama.review.packages import (
    PackageStatus,
    current_package,
    current_release_approval_manifest,
    store_approved_slot_metadata,
    store_release_approval_manifest,
    store_release_package,
)

pytestmark = pytest.mark.db


def test_stored_ready_package_is_the_current_one_with_its_hashes(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)

    with world.db.transaction(readonly=True) as tx:
        stored = current_package(tx, episode_id)
    assert stored is not None
    assert stored.status is PackageStatus.READY
    assert stored.version == 1
    assert stored.package_hash == package.package_hash
    assert stored.media_hashes == package.media_hashes
    assert stored.release_scope_hash == package.release_scope_hash
    assert stored.management_policy_hash == package.management_policy_hash


def test_a_newer_version_supersedes_open_versions_and_the_old_hash_stops_being_current(
    world: World,
) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    first = world.package(season_id=season_id, episode_id=episode_id, master=master, version=1)
    world.store_package(first, status="READY")
    recut = world.asset(season_id=season_id, episode_id=episode_id, data=b"recut-bytes")
    second = world.package(season_id=season_id, episode_id=episode_id, master=recut, version=2)
    world.store_package(second, status="READY")

    statuses = {
        row["version"]: row["status"]
        for row in world.row_all(
            "SELECT version, status FROM release_packages WHERE episode_id = %s", (episode_id,)
        )
    }
    assert statuses == {1: "SUPERSEDED", 2: "READY"}
    with world.db.transaction(readonly=True) as tx:
        assert current_package(tx, episode_id).package_hash == second.package_hash
    assert first.package_hash != second.package_hash


def test_package_version_must_increase(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    newer = world.package(season_id=season_id, episode_id=episode_id, master=master, version=2)
    world.store_package(newer)
    older = world.package(season_id=season_id, episode_id=episode_id, master=master, version=1)
    with pytest.raises(Conflict, match="must increase"):
        world.store_package(older)


def test_ready_and_blocked_status_must_match_the_gate_blockers(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    clean = world.package(season_id=season_id, episode_id=episode_id, master=master)
    with pytest.raises(SchemaInvalid, match="READY package carries no gate blockers"):
        world.store_package(
            world.package(
                season_id=season_id,
                episode_id=episode_id,
                master=master,
                gate_blockers=["open finding"],
            ),
            status="READY",
        )
    with pytest.raises(SchemaInvalid, match="BLOCKED package must name"):
        world.store_package(clean, status="BLOCKED")
    with pytest.raises(SchemaInvalid, match="start as DRAFT, READY or BLOCKED"):
        world.store_package(clean, status="APPROVED")


def test_stored_content_is_immutable_in_the_database(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    with pytest.raises(Conflict, match="immutable"), world.db.transaction() as tx:
        tx.execute(
            "UPDATE release_packages SET media_hashes = '[]'::jsonb WHERE episode_id = %s",
            (episode_id,),
        )


def test_package_must_match_the_episode_it_is_stored_for(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, number=2)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    wrong_number = world.package(
        season_id=season_id, episode_id=episode_id, number=1, master=master
    )
    with pytest.raises(Conflict, match="does not match the episode"):
        world.store_package(wrong_number)


def test_no_new_package_once_the_episode_has_an_outcome(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    world.row_exec(
        "UPDATE episodes SET outcome = 'CANCELLED', outcome_detail = 'test' WHERE id = %s",
        (episode_id,),
    )
    master = world.asset(season_id=season_id, episode_id=episode_id)
    with pytest.raises(Conflict, match="no new release package"):
        world.store_package(
            world.package(season_id=season_id, episode_id=episode_id, master=master)
        )


def test_storing_a_package_bumps_the_episode_revision_and_points_to_it(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    before = world.episode_revision(episode_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    after = world.row(
        "SELECT revision, current_package_id FROM episodes WHERE id = %s", (episode_id,)
    )
    assert after["revision"] == before + 1
    stored = world.row("SELECT id FROM release_packages WHERE episode_id = %s", (episode_id,))
    assert after["current_package_id"] == stored["id"]


def test_approved_episode_refuses_a_new_version_until_it_is_reviewed_again(world: World) -> None:
    """A material change after approval has no state path back to Gate 2 (frozen state table)."""
    season_id, episode_id, package = world.ready_episode()
    world.service.decide_episode(
        world.human(), episode_id, world.gate2_command(episode_id, package)
    )
    newer = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=world.asset(season_id=season_id, episode_id=episode_id, data=b"recut"),
        version=2,
    )
    with pytest.raises(Conflict):
        world.store_package(newer)


def test_store_helper_is_used_inside_a_caller_transaction(world: World) -> None:
    """The helper only works inside the caller's transaction and returns the new row id."""
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    with world.db.transaction() as tx:
        row_id = store_release_package(tx, package, status=PackageStatus.READY)
    assert row_id == package.package_id


def _bound_v2_manifest(package):
    source = v2_owner_approved_release_approval_manifest()
    slot_fields = source.slots[0].model_dump(mode="python")
    slot_fields.update(
        release_package_id=package.package_id,
        release_package_hash=package.package_hash,
        slot_id=f"slot-{package.release_scope[0].slot.dedupe_key}",
    )
    slot = ApprovedSlotMetadata.seal(**slot_fields)
    manifest_fields = source.model_dump(mode="python")
    manifest_fields.update(
        release_package_id=package.package_id,
        release_package_hash=package.package_hash,
        slots=[slot],
    )
    return slot, ReleaseApprovalManifest.seal(**manifest_fields)


def test_gate2_manifest_is_current_only_while_it_covers_exact_slot_metadata(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    slot, manifest = _bound_v2_manifest(package)
    with world.db.transaction() as tx:
        store_approved_slot_metadata(tx, slot)
        store_release_approval_manifest(tx, manifest)
    with world.db.transaction(readonly=True) as tx:
        assert (
            current_release_approval_manifest(
                tx, package_id=package.package_id, package_hash=package.package_hash
            )
            == manifest
        )

    changed = ApprovedSlotMetadata.seal(
        **{
            **slot.model_dump(mode="python"),
            "version": 2,
            "metadata_version": 2,
            "caption": "A substantively changed caption",
        }
    )
    with world.db.transaction() as tx:
        store_approved_slot_metadata(tx, changed)
    with world.db.transaction(readonly=True) as tx:
        assert (
            current_release_approval_manifest(
                tx, package_id=package.package_id, package_hash=package.package_hash
            )
            is None
        )


def test_owner_can_prepare_a_displayable_manifest_for_the_current_gate2_package(
    world: World,
) -> None:
    _season_id, episode_id, package = world.ready_episode()
    slot, draft_manifest = _bound_v2_manifest(package)
    manifest = world.service.prepare_release_approval_manifest(
        world.human(),
        episode_id,
        metadata_policy=draft_manifest.metadata_policy,
        slots=[slot],
    )
    assert manifest.release_package_id == package.package_id
    assert manifest.slots == [slot]
    assert manifest.approval_manifest_sha256
    view = world.service.episode_review(world.human(), episode_id)
    assert view.release_approval_manifest == manifest
    assert view.gate_enabled


def test_gate2_event_atomically_binds_v1_package_and_v2_manifest_hash(world: World) -> None:
    _season_id, episode_id, package = world.ready_episode()
    slot, draft_manifest = _bound_v2_manifest(package)
    manifest = world.service.prepare_release_approval_manifest(
        world.human(),
        episode_id,
        metadata_policy=draft_manifest.metadata_policy,
        slots=[slot],
    )
    command_fields = world.gate2_command(episode_id, package).model_dump(mode="python")
    command_fields["release_manifest_hash"] = manifest.approval_manifest_sha256
    command = ApprovalCommand.model_validate(command_fields)
    result = world.service.decide_episode(world.human(), episode_id, command)
    event = world.row(
        "SELECT package_hash, release_manifest_hash FROM approval_events WHERE id = %s",
        (result.body["event_id"],),
    )
    assert event == {
        "package_hash": package.package_hash,
        "release_manifest_hash": manifest.approval_manifest_sha256,
    }
    with pytest.raises(Conflict), world.db.transaction() as tx:
        tx.execute(
            "UPDATE approval_events SET release_manifest_hash = NULL WHERE id = %s",
            (result.body["event_id"],),
        )

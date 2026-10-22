"""T020 metadata policy: versioned, immutable rows, one current version per post."""

from __future__ import annotations

import uuid

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.errors import Conflict
from microdrama.publishing import metadata as meta


def _submitted(world: PublishingWorld):
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.row("SELECT id FROM platform_posts WHERE episode_id = %s", (episode_id,))["id"]
    return package, post_id, command


def test_first_submit_creates_the_deterministic_metadata_version(
    world: PublishingWorld,
) -> None:
    package, post_id, command = _submitted(world)
    row = world.row("SELECT * FROM metadata_versions WHERE platform_post_id = %s", (post_id,))
    assert row["id"] == command.metadata_version_id
    assert row["version"] == 1
    assert row["applied_at"] is not None
    assert row["substantive"] is True
    post = world.post_row(post_id)
    assert post["current_metadata_version_id"] == row["id"]


def test_first_submit_naming_a_foreign_version_is_refused(world: PublishingWorld) -> None:
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    command = command.model_copy(update={"metadata_version_id": uuid.uuid4()})
    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=world.submit_job(command))


def test_later_command_must_name_the_current_version(world: PublishingWorld) -> None:
    package, post_id, command = _submitted(world)
    # a stale rebuild (naming v1 while v2 is current) is refused
    with world.db.transaction() as tx:
        meta.create_version(
            tx,
            post_id=post_id,
            version_id=uuid.uuid4(),
            metadata=world.metadata(title="ชื่อใหม่"),
            policy_hash=world.policy_hash(),
            now=world.clock.now(),
        )
    # the slot is SUBMITTED now, so submitting the old command is refused by state;
    # exercise the metadata rule directly:
    with pytest.raises(Conflict):
        with world.db.transaction() as tx:
            meta.require_current(tx, post_id, command.metadata_version_id)


def test_substantive_and_cosmetic_changes_are_distinguished(world: PublishingWorld) -> None:
    _pkg, post_id, _cmd = _submitted(world)
    cosmetic = world.metadata().model_copy(update={"catalog_version": 2})
    substantive = world.metadata().model_copy(update={"title": "ชื่อที่เปลี่ยนไป", "catalog_version": 3})
    with world.db.transaction() as tx:
        version = meta.create_version(
            tx,
            post_id=post_id,
            version_id=uuid.uuid4(),
            metadata=cosmetic,
            policy_hash=world.policy_hash(),
            now=world.clock.now(),
        )
        assert version == 2
        version = meta.create_version(
            tx,
            post_id=post_id,
            version_id=uuid.uuid4(),
            metadata=substantive,
            policy_hash=world.policy_hash(),
            now=world.clock.now(),
        )
        assert version == 3
    cosmetic_row = world.row(
        "SELECT substantive FROM metadata_versions WHERE platform_post_id = %s AND version = 2",
        (post_id,),
    )
    substantive_row = world.row(
        "SELECT substantive FROM metadata_versions WHERE platform_post_id = %s AND version = 3",
        (post_id,),
    )
    assert cosmetic_row["substantive"] is False
    assert substantive_row["substantive"] is True


def test_rollback_records_its_target_and_moves_current(world: PublishingWorld) -> None:
    _pkg, post_id, command = _submitted(world)
    v2 = uuid.uuid4()
    with world.db.transaction() as tx:
        meta.create_version(
            tx,
            post_id=post_id,
            version_id=v2,
            metadata=world.metadata(title="v2"),
            policy_hash=world.policy_hash(),
            now=world.clock.now(),
        )
    v3 = uuid.uuid4()
    with world.db.transaction() as tx:
        meta.create_version(
            tx,
            post_id=post_id,
            version_id=v3,
            metadata=world.metadata(title="back to v1"),
            policy_hash=world.policy_hash(),
            now=world.clock.now(),
            rollback_of=v2,
        )
    row = world.row("SELECT * FROM metadata_versions WHERE id = %s", (v3,))
    assert row["rollback_of"] == v2
    assert world.post_row(post_id)["current_metadata_version_id"] == v3


def test_rollback_target_must_belong_to_the_same_post(world: PublishingWorld) -> None:
    _pkg, post_id, _cmd = _submitted(world)
    with pytest.raises(Exception):  # noqa: B017 - NotFound: foreign rollback target
        with world.db.transaction() as tx:
            meta.create_version(
                tx,
                post_id=post_id,
                version_id=uuid.uuid4(),
                metadata=world.metadata(),
                policy_hash=world.policy_hash(),
                now=world.clock.now(),
                rollback_of=uuid.uuid4(),
            )


def test_metadata_rows_are_immutable(world: PublishingWorld) -> None:
    _pkg, post_id, _cmd = _submitted(world)
    with pytest.raises(Exception):  # noqa: B017 - trigger: md_immutable_columns
        with world.db.transaction() as tx:
            tx.execute(
                "UPDATE metadata_versions SET metadata = '{}'::jsonb WHERE platform_post_id = %s",
                (post_id,),
            )
    with pytest.raises(Exception):  # noqa: B017 - trigger: no delete
        with world.db.transaction() as tx:
            tx.execute("DELETE FROM metadata_versions WHERE platform_post_id = %s", (post_id,))

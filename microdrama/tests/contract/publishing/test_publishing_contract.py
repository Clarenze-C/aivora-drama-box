"""Contract pins for the release core (T020).

Freeze the interfaces the platform adapters (T021–T024) build against: the PublisherAdapter
protocol conformance of the fake, the unmetered operation kinds of contract 1.6.0, the
job specs the frozen contracts declare for publishing, and the end-to-end scenario matrix
(accepted / denied / 429 / timeout-ambiguous / replayed) through the service surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.cost import UNMETERED_OPERATION_KINDS
from microdrama.contracts.enums import Platform
from microdrama.contracts.jobs import JOB_SPECS
from microdrama.contracts.providers import PublisherAdapter
from microdrama.contracts.release import PublicationCommand
from microdrama.testing.fakes.publishing import PublishScenario, fake_post_id

PUBLISH_JOB_TYPES = {
    "publish.schedule_release",
    "publish.submit_slot",
    "publish.poll_status",
    "publish.reconcile_slot",
}


@pytest.fixture
def world(db, tmp_path, offline_settings):
    return PublishingWorld(db, tmp_path, offline_settings)


def test_publish_job_specs_match_the_frozen_contracts() -> None:
    specs = {spec.job_type: spec for spec in JOB_SPECS}
    for job_type in PUBLISH_JOB_TYPES:
        assert specs[job_type].owner_module == "publishing", job_type
    assert specs["publish.submit_slot"].input_model is PublicationCommand


def test_unmetered_kinds_are_exactly_the_publish_operations() -> None:
    assert UNMETERED_OPERATION_KINDS == frozenset(
        {
            "publish.submit_slot",
            "publish.poll_status",
            "publish.reconcile_slot",
            "publish.update_metadata",
        }
    )


def test_fake_publisher_satisfies_the_adapter_protocol(
    world: PublishingWorld,
) -> None:
    for adapter in world.adapters.values():
        assert isinstance(adapter, PublisherAdapter)


@pytest.mark.parametrize(
    ("scenario", "expected_state"),
    [
        (PublishScenario.ACCEPTED, "SUBMITTED"),
        (PublishScenario.DENIED_PERMISSION, "FAILED"),
        (PublishScenario.TOKEN_EXPIRED, "FAILED"),
        (PublishScenario.RATE_LIMITED, "RETRY_WAIT"),
        (PublishScenario.TIMEOUT_CREATED, "NEEDS_RECONCILIATION"),
        (PublishScenario.TIMEOUT_NOT_CREATED, "NEEDS_RECONCILIATION"),
    ],
)
def test_provider_response_matrix_maps_to_slot_states(
    world: PublishingWorld, scenario: PublishScenario, expected_state: str
) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.adapters[Platform.YOUTUBE].queue_scenarios(scenario)
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == expected_state
    # every path leaves exactly one durable provider operation, job-linked and unmetered
    ops = world.rows("SELECT * FROM provider_operations")
    assert len(ops) == 1
    assert ops[0]["operation_kind"] == "publish.submit_slot"
    assert ops[0]["job_id"] is not None
    assert ops[0]["reservation_id"] is None


def test_replayed_submit_is_deduplicated_by_client_token(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    first = world.service.submit_slot(command, job_id=job_id)
    second = world.service.submit_slot(command, job_id=job_id)  # the job ran twice

    assert second["external_id"] == first["external_id"]
    assert (
        world.row(
            "SELECT count(*) AS n FROM provider_operations WHERE client_token = %s",
            (command.client_token,),
        )["n"]
        == 1
    )
    # the fake answered the replay from its dedupe cache, creating no second post
    posts = world.rows("SELECT * FROM platform_posts WHERE external_id IS NOT NULL")
    assert len(posts) == 1


def test_full_offline_release_flow_schedule_to_verified(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    post_ids = world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["external_id"] == fake_post_id(Platform.YOUTUBE, command.client_token)

    processing = world.service.poll_status(post_ids[0])
    assert processing["state"] == "PROCESSING"
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    from urllib.parse import urlparse

    assert urlparse(verified["url"]).hostname.endswith(".invalid")  # fake host only

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_publication_command_round_trips_through_the_durable_row(
    world: PublishingWorld,
) -> None:
    """A poll/reconcile rebuilds the command from the slot row: hashes must match."""
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.post_by_slot("full", episode_id)["id"]
    rebuilt = world.rebuilt_command(post_id)
    from microdrama.contracts.hashing import canonical_hash

    assert canonical_hash(rebuilt) == canonical_hash(command)


def test_media_is_resolved_from_the_store_not_caller_bytes(
    world: PublishingWorld, tmp_path: Path
) -> None:
    """The submitter cannot swap media: the store object must hash to the pinned value."""
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    # corrupt the stored object on disk (the store itself refuses overwrites): the
    # service must verify the hash and refuse before any adapter call
    plan = package.release_scope[0]
    row = world.row("SELECT object_key FROM assets WHERE id = %s", (plan.asset_id,))
    world.store.local_path(row["object_key"]).write_bytes(b"tampered bytes")
    with pytest.raises(Exception):  # noqa: B017 - Conflict: hash mismatch
        world.service.submit_slot(command, job_id=world.submit_job(command))

"""T020 submit gates: approval binding, media immutability, capability, dependencies."""

from __future__ import annotations

import uuid

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    Platform,
    SlotKind,
)
from microdrama.contracts.errors import Conflict, PolicyDenied
from microdrama.publishing.service import MAX_SUBMIT_ATTEMPTS


def _scheduled_single(world: PublishingWorld):
    season_id, episode_id, package, approval = world.approved_episode()
    post_ids = world.schedule(episode_id)
    return season_id, episode_id, package, approval, post_ids[0]


def test_accepted_submit_reaches_submitted_with_external_id(
    world: PublishingWorld,
) -> None:
    _s, episode_id, package, approval, post_id = _scheduled_single(world)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    updated = world.service.submit_slot(command, job_id=job_id)

    assert updated["state"] == "SUBMITTED"
    assert updated["external_id"] is not None
    assert updated["attempt"] == 1
    assert updated["submitted_at"] is not None
    assert world.episode_state(episode_id) == "PUBLISHING"
    op = world.row(
        "SELECT * FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "SUBMITTED"
    assert op["operation_kind"] == "publish.submit_slot"
    assert op["reservation_id"] is None  # unmetered kind (contract 1.6.0)


def test_command_naming_a_different_package_is_refused(world: PublishingWorld) -> None:
    _s, _e, package, approval, _post = _scheduled_single(world)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    command = command.model_copy(update={"release_package_hash": "0" * 64})
    job_id = world.submit_job(command)
    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=job_id)


def test_command_with_a_foreign_approval_event_is_refused(world: PublishingWorld) -> None:
    _s, _e, package, _approval, _post = _scheduled_single(world)
    command = world.command(
        package.release_scope[0], package=package, approval_event_id=uuid.uuid4()
    )
    job_id = world.submit_job(command)
    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=job_id)


def test_command_media_hash_mismatch_is_refused(world: PublishingWorld) -> None:
    _s, _e, package, approval, _post = _scheduled_single(world)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    command = command.model_copy(update={"asset_sha256": "f" * 64})
    job_id = world.submit_job(command)
    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=job_id)


def test_disabled_capability_holds_the_slot_not_the_episode(
    world: PublishingWorld,
) -> None:
    world.adapters[Platform.YOUTUBE]._enabled = False
    _s, episode_id, package, approval, _post = _scheduled_single(world)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    updated = world.service.submit_slot(command, job_id=job_id)

    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    assert world.episode_state(episode_id) == "SCHEDULED"  # not a failure of the episode
    # no provider operation was begun and nothing reached the adapter
    assert (
        world.row(
            "SELECT count(*) AS n FROM provider_operations WHERE operation_kind = "
            "'publish.submit_slot'"
        )["n"]
        == 0
    )

    # the hold clears when the destination is re-enabled
    world.adapters[Platform.YOUTUBE]._enabled = True
    world.service.retry_held_slot(updated["id"])
    retried = world.service.submit_slot(command, job_id=job_id)
    assert retried["state"] == "SUBMITTED"


def test_unsupported_disclosure_holds_the_slot(world: PublishingWorld) -> None:
    adapter = world.adapters[Platform.YOUTUBE]
    adapter._operations = dict(adapter._operations)
    adapter._operations[CapabilityOperation.AI_DISCLOSURE] = CapabilitySupport.UNSUPPORTED
    _s, _e, package, approval, _post = _scheduled_single(world)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"


def test_stale_capability_record_holds_the_slot(world: PublishingWorld) -> None:
    _s, _e, package, approval, _post = _scheduled_single(world)
    adapter = world.adapters[Platform.YOUTUBE]
    adapter._version = 2  # scheduling pinned version 1
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_STALE"


def test_dependency_waits_for_the_actual_verified_target(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        full = world.slot_plan(
            season_id=season_id, episode_id=episode_id, asset=master, slot="full"
        )
        promo = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="promo",
            slot_kind=SlotKind.PROMO_CUT,
            required=False,
            platform=Platform.TIKTOK,
            account_ref="acct:tiktok-main",
            depends_on=[full.slot.dedupe_key],
        )
        return [full, promo]

    _s, episode_id, package, approval = world.approved_episode(scope_builder=scope)
    world.schedule(episode_id)
    full_plan, promo_plan = package.release_scope

    promo_command = world.command(promo_plan, package=package, approval_event_id=approval)
    job_id = world.submit_job(promo_command)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(promo_command, job_id=job_id)

    # the target publishing does not yet verify it: still waiting
    full_command = world.command(full_plan, package=package, approval_event_id=approval)
    full_job = world.submit_job(full_command)
    world.service.submit_slot(full_command, job_id=full_job)
    full_post = world.post_by_slot("full", episode_id)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(promo_command, job_id=job_id)

    # once the target is PUBLISHED_VERIFIED with a live external id, the promo may go
    world.service.poll_status(full_post["id"])  # SUBMITTED -> PROCESSING
    world.service.poll_status(full_post["id"])  # PROCESSING -> verified
    updated = world.service.submit_slot(promo_command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"


def test_future_window_without_schedule_support_is_refused(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        return [
            world.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                schedule=world.future_schedule(),
            )
        ]

    _s, _e, package, approval = world.approved_episode(scope_builder=scope)
    world.schedule(_e := package.episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    adapter = world.adapters[Platform.YOUTUBE]
    adapter._operations = dict(adapter._operations)
    adapter._operations[CapabilityOperation.SCHEDULE] = CapabilitySupport.UNSUPPORTED
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(command, job_id=job_id)

    # with schedule support the provider takes the future window now
    adapter._operations[CapabilityOperation.SCHEDULE] = CapabilitySupport.SUPPORTED_DOCUMENTED
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"


def test_submit_attempt_cap_is_enforced(world: PublishingWorld) -> None:
    _s, _e, package, approval, post_id = _scheduled_single(world)
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE platform_posts SET attempt = %s WHERE id = %s",
            (MAX_SUBMIT_ATTEMPTS, post_id),
        )
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(command, job_id=job_id)


def test_no_adapter_registered_refuses_before_any_write(world: PublishingWorld) -> None:
    _s, _e, package, approval, _post = _scheduled_single(world)
    world.service._adapters.pop(Platform.YOUTUBE)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(command, job_id=job_id)

"""Service-level Instagram outcomes (T023): the declaration-truth e2e path.

Through PublishingService, an Instagram slot can never reach the adapter: MD-015
requires every release slot to declare AI_GENERATED_CONTENT, the platform honestly
supports no API disclosure surface, so ``_check_capability`` HELDs every Instagram
slot with UNSUPPORTED_DISCLOSURE before any provider operation begins. These tests
pin that documented outcome end-to-end (plus the CAPABILITY_STALE and
CAPABILITY_UNAVAILABLE holds), proving the destination is never called.
"""

from __future__ import annotations

import pytest
from instagram_lane_support import DEFAULT_ACCOUNT_REF, PERSONAL_ACCOUNT_REF, InstagramWorld

from microdrama.contracts.errors import Conflict
from microdrama.publishing.service import HeldSlot


def _held_submit(world: InstagramWorld, *, account_ref: str = DEFAULT_ACCOUNT_REF):
    _season, episode_id, package, approval = world.approved_instagram_episode(
        account_ref=account_ref
    )
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    return updated, command, episode_id


def test_submit_holds_with_unsupported_disclosure(world: InstagramWorld) -> None:
    """The documented e2e outcome: no API disclosure surface, slot HELDs."""
    updated, _command, episode_id = _held_submit(world)

    assert updated["state"] == "HELD"
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"
    assert world.episode_state(episode_id) == "SCHEDULED"  # not a failure of the episode
    # nothing began; the destination was only asked for capability account facts
    assert world.rows("SELECT * FROM provider_operations") == []
    assert {call.method for call in world.transport.calls} == {"account"}
    assert world.transport.create_container_calls == 0


def test_held_slot_blocks_full_release_qualification(world: InstagramWorld) -> None:
    updated, _command, episode_id = _held_submit(world)
    assert updated["required"] is True

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"] == [
        {
            "slot": updated["release_slot"],
            "state": "HELD",
            "blocker": "UNSUPPORTED_DISCLOSURE",
        }
    ]


def test_replayed_held_submit_conflicts_without_touching_the_destination(
    world: InstagramWorld,
) -> None:
    updated, command, _episode = _held_submit(world)
    job_id = world.submit_job(command)

    # the job ran twice: the slot is HELD and cannot be submitted again
    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=job_id)
    assert world.rows("SELECT * FROM provider_operations") == []
    assert {call.method for call in world.transport.calls} == {"account"}


def test_retry_held_slot_still_blocked_by_the_disclosure_truth(
    world: InstagramWorld,
) -> None:
    updated, _command, _episode = _held_submit(world)
    with pytest.raises(HeldSlot):
        world.service.retry_held_slot(updated["id"])  # the destination check re-runs
    assert world.post_row(updated["id"])["state"] == "HELD"


def test_stale_capability_record_holds(world: InstagramWorld) -> None:
    _season, episode_id, package, approval = world.approved_instagram_episode()
    world.schedule(episode_id)
    world.bump_instagram_version()  # scheduling pinned version 1

    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_STALE"


def test_personal_account_route_is_unavailable(world: InstagramWorld) -> None:
    """Professional-account requirement: a personal route cannot publish at all."""
    updated, _command, _episode = _held_submit(world, account_ref=PERSONAL_ACCOUNT_REF)

    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    # the only destination touch was the capability account query
    assert {call.method for call in world.transport.calls} == {"account"}
    assert world.transport.create_container_calls == 0


def test_disclosure_hold_precedes_the_schedule_window_refusal(
    world: InstagramWorld,
) -> None:
    """SCHEDULE is UNSUPPORTED on this platform, but the disclosure check runs
    first: even a future window lands HELD, never a schedule PolicyDenied."""
    _season, episode_id, package, approval = world.approved_instagram_episode(
        schedule=world.future_schedule()
    )
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"

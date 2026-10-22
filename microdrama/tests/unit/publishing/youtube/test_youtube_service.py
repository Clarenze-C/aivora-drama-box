"""Service-level flows (T021): the adapter driven through PublishingService.

The frozen scenario matrix mapped to slot states, the replay dedupe, crash-safe
reconciliation (adopt found / re-arm proven-absent), the HeldSlot destination
blockers (stale capability, disabled, unsupported disclosure), schedule-ahead
through the documented private+publishAt model, and the full verify flow with
release qualification.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

import pytest
from youtube_support import YouTubeWorld

from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport, SlotKind
from microdrama.contracts.errors import PolicyDenied
from microdrama.publishing.service import PUBLISH_DEADLINE_MS
from microdrama.publishing.youtube import YouTubeScenario
from microdrama.publishing.youtube.transport import youtube_external_id


def _scheduled(world: YouTubeWorld, **plan_kwargs) -> tuple:
    """Approved episode + scheduled slots; returns (episode_id, package, approval, post_ids)."""
    if plan_kwargs:

        def scope_builder(season_id, episode_id, master):
            return [
                world.slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, **plan_kwargs
                )
            ]

        _s, episode_id, package, approval = world.approved_episode(scope_builder=scope_builder)
    else:
        _s, episode_id, package, approval = world.approved_episode()
    return episode_id, package, approval, world.schedule(episode_id)


def _submit(world: YouTubeWorld, package, approval):
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    return command, world.service.submit_slot(command, job_id=world.submit_job(command))


@pytest.mark.parametrize(
    ("scenario", "expected_state"),
    [
        (YouTubeScenario.ACCEPTED, "SUBMITTED"),
        (YouTubeScenario.DENIED_PERMISSION, "FAILED"),
        (YouTubeScenario.TOKEN_EXPIRED, "FAILED"),
        (YouTubeScenario.RATE_LIMITED, "RETRY_WAIT"),
        (YouTubeScenario.TIMEOUT_CREATED, "NEEDS_RECONCILIATION"),
        (YouTubeScenario.TIMEOUT_NOT_CREATED, "NEEDS_RECONCILIATION"),
    ],
)
def test_provider_response_matrix_maps_to_slot_states(
    world: YouTubeWorld, scenario: YouTubeScenario, expected_state: str
) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
    world.youtube.queue_scenarios(scenario)
    command, updated = _submit(world, package, approval)

    assert updated["state"] == expected_state
    if scenario is YouTubeScenario.ACCEPTED:
        assert updated["external_id"] == youtube_external_id(command.client_token)
    if scenario in (YouTubeScenario.DENIED_PERMISSION, YouTubeScenario.TOKEN_EXPIRED):
        assert (
            updated["last_error_code"]
            == {
                YouTubeScenario.DENIED_PERMISSION: "PERMISSION_DENIED",
                YouTubeScenario.TOKEN_EXPIRED: "TOKEN_EXPIRED",
            }[scenario]
        )
    # every path leaves exactly one durable provider operation, job-linked and unmetered
    ops = world.rows("SELECT * FROM provider_operations")
    assert len(ops) == 1
    assert ops[0]["operation_kind"] == "publish.submit_slot"
    assert ops[0]["job_id"] is not None
    assert ops[0]["reservation_id"] is None


def test_replayed_job_run_deduplicates_by_client_token(world: YouTubeWorld) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
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
    posts = world.rows("SELECT * FROM platform_posts WHERE external_id IS NOT NULL")
    assert len(posts) == 1
    assert world.youtube.transport.video_count() == 1


def test_full_verify_flow_qualifies_the_release(world: YouTubeWorld) -> None:
    episode_id, package, approval, post_ids = _scheduled(world)
    command, updated = _submit(world, package, approval)
    assert updated["external_id"] == youtube_external_id(command.client_token)

    processing = world.service.poll_status(post_ids[0])
    assert processing["state"] == "PROCESSING"
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert urlparse(verified["url"]).hostname == "youtube.fake.invalid"  # fake host only

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"
    op = world.row(
        "SELECT state FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "SUCCEEDED"


def test_timeout_created_is_adopted_by_reconciliation(world: YouTubeWorld) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
    world.youtube.queue_scenarios(YouTubeScenario.TIMEOUT_CREATED)
    command, ambiguous = _submit(world, package, approval)
    assert ambiguous["state"] == "NEEDS_RECONCILIATION"
    assert ambiguous["external_id"] is None

    post_id = world.post_by_slot("full", episode_id)["id"]
    adopted = world.service.reconcile_slot(post_id)
    assert adopted["state"] == "SUBMITTED"
    assert adopted["external_id"] == youtube_external_id(command.client_token)

    world.service.poll_status(post_id)
    verified = world.service.poll_status(post_id)
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_timeout_not_created_rearms_the_same_token_for_one_more_attempt(
    world: YouTubeWorld,
) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
    world.youtube.queue_scenarios(YouTubeScenario.TIMEOUT_NOT_CREATED, YouTubeScenario.ACCEPTED)
    command, ambiguous = _submit(world, package, approval)
    assert ambiguous["state"] == "NEEDS_RECONCILIATION"

    post_id = world.post_by_slot("full", episode_id)["id"]
    world.clock.advance(ms=PUBLISH_DEADLINE_MS)  # operation deadline passes
    rearmed = world.service.reconcile_slot(post_id)
    assert rearmed["state"] == "SUBMITTED"
    assert rearmed["attempt"] == 2

    resubmitted = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["external_id"] == youtube_external_id(command.client_token)
    assert world.youtube.transport.video_count() == 1  # exactly one upload ever happened


def test_stale_capability_version_holds_then_clears(world: YouTubeWorld) -> None:
    episode_id, package, approval, _posts = _scheduled(world)  # pins version 1
    world.youtube._version = 2  # the record moved after scheduling
    _command, held = _submit(world, package, approval)

    assert held["state"] == "HELD"
    assert held["blocker"] == "CAPABILITY_STALE"
    assert world.episode_state(episode_id) == "SCHEDULED"  # the episode is not failed
    assert world.rows("SELECT * FROM provider_operations") == []

    world.youtube._version = 1
    post_id = world.post_by_slot("full", episode_id)["id"]
    world.service.retry_held_slot(post_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    retried = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert retried["state"] == "SUBMITTED"


def test_disabled_capability_holds_and_re_enables(world: YouTubeWorld) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
    world.youtube._enabled = False
    _command, held = _submit(world, package, approval)
    assert held["state"] == "HELD"
    assert held["blocker"] == "CAPABILITY_UNAVAILABLE"

    world.youtube._enabled = True
    post_id = world.post_by_slot("full", episode_id)["id"]
    world.service.retry_held_slot(post_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    assert world.service.submit_slot(command, job_id=world.submit_job(command))["state"] == (
        "SUBMITTED"
    )


def test_unsupported_disclosure_holds_the_slot(world: YouTubeWorld) -> None:
    episode_id, package, approval, _posts = _scheduled(world)
    world.youtube._operations[CapabilityOperation.AI_DISCLOSURE] = CapabilitySupport.UNSUPPORTED
    _command, held = _submit(world, package, approval)
    assert held["state"] == "HELD"
    assert held["blocker"] == "UNSUPPORTED_DISCLOSURE"
    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"][0]["blocker"] == "UNSUPPORTED_DISCLOSURE"


def test_schedule_ahead_flows_private_then_public(world: YouTubeWorld) -> None:
    episode_id, package, approval, post_ids = _scheduled(
        world, schedule=world.future_schedule(), slot="night-full"
    )
    command, submitted = _submit(world, package, approval)
    assert submitted["state"] == "SUBMITTED"
    assert submitted["external_id"] == youtube_external_id(command.client_token)

    assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
    still_private = world.service.poll_status(post_ids[0])
    assert still_private["state"] == "PROCESSING"  # processed, waiting for the window

    world.clock.set(command.schedule.utc_instant + timedelta(minutes=1))
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_schedule_ahead_without_schedule_support_is_denied(world: YouTubeWorld) -> None:
    world.youtube._operations[CapabilityOperation.SCHEDULE] = CapabilitySupport.UNSUPPORTED
    _episode_id, package, approval, _posts = _scheduled(
        world, schedule=world.future_schedule(), slot="night-full"
    )
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(command, job_id=world.submit_job(command))


def test_shorts_slot_publishes_through_the_service(world: YouTubeWorld) -> None:
    """A HOOK slot (Shorts route) rides the same lifecycle end to end."""
    episode_id, package, approval, _posts = _scheduled(world, slot="hook", slot_kind=SlotKind.HOOK)
    _command, submitted = _submit(world, package, approval)
    assert submitted["state"] == "SUBMITTED"

    post_id = world.post_by_slot("hook", episode_id)["id"]
    world.service.poll_status(post_id)
    verified = world.service.poll_status(post_id)
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert world.youtube.transport.route_of(verified["external_id"]) == "shorts"

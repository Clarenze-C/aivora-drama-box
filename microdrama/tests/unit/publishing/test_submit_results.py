"""T020 submit outcomes: the fake publisher's scenario matrix on the service."""

from __future__ import annotations

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform
from microdrama.testing.fakes.publishing import PublishScenario, fake_post_id


def _ready(world: PublishingWorld, scenario: PublishScenario | None = None):
    if scenario is not None:
        world.adapters[Platform.YOUTUBE].queue_scenarios(scenario)
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    return episode_id, command, job_id


def test_accepted(world: PublishingWorld) -> None:
    episode_id, command, job_id = _ready(world)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"
    assert updated["external_id"] == fake_post_id(Platform.YOUTUBE, command.client_token)
    assert world.episode_state(episode_id) == "PUBLISHING"


def test_rate_limited_lands_in_retry_wait_then_retries(world: PublishingWorld) -> None:
    _episode, command, job_id = _ready(world)
    adapter = world.adapters[Platform.YOUTUBE]
    adapter.queue_scenarios(PublishScenario.RATE_LIMITED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "RETRY_WAIT"
    assert updated["last_error_code"] == "RATE_LIMITED"
    op = world.row(
        "SELECT * FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "FAILED"
    assert op["last_result"]["transient"] is True

    # a retry after the wait submits normally (next scenario: default ACCEPTED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"
    assert updated["attempt"] == 2


def test_permission_denied_fails_the_slot(world: PublishingWorld) -> None:
    _e, command, job_id = _ready(world, PublishScenario.DENIED_PERMISSION)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "FAILED"
    assert updated["last_error_code"] == "PERMISSION_DENIED"


def test_expired_token_fails_the_slot(world: PublishingWorld) -> None:
    _e, command, job_id = _ready(world, PublishScenario.TOKEN_EXPIRED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "FAILED"
    assert updated["last_error_code"] == "TOKEN_EXPIRED"


def test_ambiguous_created_needs_reconciliation_and_never_blindly_repeats(
    world: PublishingWorld,
) -> None:
    _e, command, job_id = _ready(world, PublishScenario.TIMEOUT_CREATED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "NEEDS_RECONCILIATION"
    assert updated["external_id"] is None  # unknown: nothing may be assumed

    # a blind resubmit is refused while the outcome is ambiguous
    with pytest.raises(Exception):  # noqa: B017 - Conflict: slot cannot be submitted
        world.service.submit_slot(command, job_id=job_id)


def test_ambiguous_not_created_needs_reconciliation(world: PublishingWorld) -> None:
    _e, command, job_id = _ready(world, PublishScenario.TIMEOUT_NOT_CREATED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "NEEDS_RECONCILIATION"


def test_crash_between_begin_and_send_leaves_recoverable_state(
    world: PublishingWorld,
) -> None:
    """Durable intent is committed before the adapter call (AT-04 shape for publishing)."""
    episode_id, command, job_id = _ready(world)

    class Boom(RuntimeError):
        pass

    adapter = world.adapters[Platform.YOUTUBE]
    original = adapter.submit

    def crashing(cmd, media_path):
        raise Boom("process died mid-upload")

    adapter.submit = crashing  # type: ignore[method-assign]
    with pytest.raises(Boom):
        world.service.submit_slot(command, job_id=job_id)
    adapter.submit = original  # type: ignore[method-assign]

    # the intent row survived the crash and blocks nothing; the slot never moved
    op = world.row(
        "SELECT * FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "PENDING_SUBMIT"
    post = world.row(
        "SELECT * FROM platform_posts WHERE client_token = %s", (command.client_token,)
    )
    assert post["state"] == "SCHEDULED"

    # the retry with the SAME client token creates exactly one post (token dedupe)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"
    posts = world.rows("SELECT * FROM platform_posts WHERE external_id IS NOT NULL")
    assert len(posts) == 1

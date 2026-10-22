"""T020 reconciliation: adopt the found, re-arm only the proven absent (AT-09)."""

from __future__ import annotations

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform
from microdrama.publishing.service import MAX_SUBMIT_ATTEMPTS, PUBLISH_DEADLINE_MS
from microdrama.testing.fakes.publishing import PublishScenario, fake_post_id


def _ambiguous(world: PublishingWorld, scenario: PublishScenario):
    season_id, episode_id, package, approval = world.approved_episode()
    world.adapters[Platform.YOUTUBE].queue_scenarios(scenario)
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "NEEDS_RECONCILIATION"
    post = world.row("SELECT * FROM platform_posts WHERE episode_id = %s", (episode_id,))
    return episode_id, command, job_id, post["id"]


def test_reconcile_before_the_deadline_is_refused(world: PublishingWorld) -> None:
    # An UNKNOWN outcome (ambiguous submit) may reconcile immediately — that is the
    # point of UNKNOWN. The deadline guard protects SUBMITTED operations whose polls
    # stopped: those are only reconcilable once past their deadline.
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.row("SELECT id FROM platform_posts WHERE episode_id = %s", (episode_id,))["id"]
    with pytest.raises(Exception):  # noqa: B017 - Conflict: SUBMITTED, not due yet
        world.service.reconcile_slot(post_id)
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    updated = world.service.reconcile_slot(post_id)
    assert updated["state"] in ("SUBMITTED", "PROCESSING", "PUBLISHED_VERIFIED")


def test_timeout_created_is_adopted_by_external_id(world: PublishingWorld) -> None:
    episode_id, command, _job, post_id = _ambiguous(world, PublishScenario.TIMEOUT_CREATED)
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    updated = world.service.reconcile_slot(post_id)

    # the post existed: adopted with its external id, no second submission
    assert updated["state"] == "SUBMITTED"
    assert updated["external_id"] == fake_post_id(Platform.YOUTUBE, command.client_token)
    op = world.row(
        "SELECT * FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "SUBMITTED"
    assert op["external_id"] == updated["external_id"]

    # and the normal poll path takes it from there
    world.service.poll_status(post_id)
    updated = world.service.poll_status(post_id)
    assert updated["state"] == "PUBLISHED_VERIFIED"
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_timeout_not_created_re_arms_the_same_token(world: PublishingWorld) -> None:
    _e, command, _job, post_id = _ambiguous(world, PublishScenario.TIMEOUT_NOT_CREATED)
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    updated = world.service.reconcile_slot(post_id)

    assert updated["state"] == "SUBMITTED"  # armed again, same client token
    assert updated["attempt"] == 2
    op = world.row(
        "SELECT * FROM provider_operations WHERE client_token = %s", (command.client_token,)
    )
    assert op["state"] == "PENDING_SUBMIT"  # re-armed by resubmit_allowed

    # the resubmit uses the SAME token and creates exactly one post
    submitted = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert submitted["state"] == "SUBMITTED"
    assert submitted["external_id"] == fake_post_id(Platform.YOUTUBE, command.client_token)
    assert (
        world.row(
            "SELECT count(*) AS n FROM provider_operations WHERE client_token = %s",
            (command.client_token,),
        )["n"]
        == 1
    )


def test_repeated_absence_hits_the_attempt_cap(world: PublishingWorld) -> None:
    _e, command, job_id, post_id = _ambiguous(world, PublishScenario.TIMEOUT_NOT_CREATED)
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    # reconcile -> absent -> re-arm -> submit (ambiguous again) -> ... until the cap
    while True:
        updated = world.service.reconcile_slot(post_id)
        if updated["state"] == "FAILED":
            assert updated["last_error_code"] == "ATTEMPT_CAP_REACHED"
            break
        world.adapters[Platform.YOUTUBE].queue_scenarios(PublishScenario.TIMEOUT_NOT_CREATED)
        updated = world.service.submit_slot(command, job_id=job_id)
        assert updated["state"] == "NEEDS_RECONCILIATION"
        world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    assert updated["attempt"] >= MAX_SUBMIT_ATTEMPTS


def test_reconcile_on_a_clean_slot_is_refused(world: PublishingWorld) -> None:
    season_id, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    post_id = world.row("SELECT id FROM platform_posts WHERE episode_id = %s", (episode_id,))["id"]
    with pytest.raises(Exception):  # noqa: B017 - Conflict: SCHEDULED, nothing to reconcile
        world.service.reconcile_slot(post_id)

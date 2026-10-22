"""T020 release qualification view and rollback (cancel) state."""

from __future__ import annotations

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import Platform
from microdrama.contracts.errors import Conflict, PolicyDenied


def _world_with_held_required(world: PublishingWorld):
    world.adapters[Platform.YOUTUBE]._enabled = False
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    return episode_id, package, approval


def test_held_required_slot_blocks_full_release_qualification(
    world: PublishingWorld,
) -> None:
    episode_id, _pkg, _ap = _world_with_held_required(world)
    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"] == [
        {"slot": "full", "state": "HELD", "blocker": "CAPABILITY_UNAVAILABLE"}
    ]
    assert view["episode_state"] == "SCHEDULED"  # HELD is not an episode failure


def test_held_optional_slot_does_not_block(world: PublishingWorld) -> None:
    def scope(season_id, episode_id, master):
        full = world.slot_plan(
            season_id=season_id, episode_id=episode_id, asset=master, slot="full"
        )
        promo = world.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=master,
            slot="promo",
            slot_kind="PROMO_CUT",
            required=False,
            platform=Platform.TIKTOK,
            account_ref="acct:tiktok-main",
        )
        return [full, promo]

    tiktok = world.adapters[Platform.TIKTOK]
    tiktok._enabled = False
    _s, episode_id, package, approval = world.approved_episode(scope_builder=scope)
    world.schedule(episode_id)

    full_command = world.command(
        package.release_scope[0], package=package, approval_event_id=approval
    )
    world.service.submit_slot(full_command, job_id=world.submit_job(full_command))
    full_post = world.post_by_slot("full", episode_id)
    world.service.poll_status(full_post["id"])
    world.service.poll_status(full_post["id"])

    promo_command = world.command(
        package.release_scope[1], package=package, approval_event_id=approval
    )
    world.service.submit_slot(promo_command, job_id=world.submit_job(promo_command))

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert view["blockers"] == []
    held = [slot for slot in view["slots"] if slot["state"] == "HELD"]
    assert len(held) == 1 and held[0]["required"] is False
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_all_required_verified_reports_ready(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.post_by_slot("full", episode_id)["id"]
    world.service.poll_status(post_id)
    world.service.poll_status(post_id)

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert view["blockers"] == []
    assert view["episode_state"] == "PUBLISHED_VERIFIED"


def test_cancel_stops_a_slot_before_it_reaches_the_provider(world: PublishingWorld) -> None:
    _s, episode_id, _pkg, _ap = world.approved_episode()
    post_ids = world.schedule(episode_id)
    updated = world.service.cancel_slot(post_ids[0], reason="operator stopped the route")
    assert updated["state"] == "CANCELLED"
    assert updated["blocker"] == "operator stopped the route"

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False  # the required destination is gone
    assert view["blockers"][0]["state"] == "CANCELLED"


def test_cancel_refuses_a_live_post(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.post_by_slot("full", episode_id)["id"]
    with pytest.raises(PolicyDenied):
        world.service.cancel_slot(post_id, reason="too late")


def test_cancel_refuses_terminal_slots(world: PublishingWorld) -> None:
    # A FAILED slot with nothing at the provider is terminal: cancel is refused even
    # though no live post exists. (A verified slot hits the live-post refusal first.)
    from microdrama.testing.fakes.publishing import PublishScenario

    world.adapters[Platform.YOUTUBE].queue_scenarios(PublishScenario.TOKEN_EXPIRED)
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))
    post_id = world.post_by_slot("full", episode_id)["id"]
    assert world.post_row(post_id)["state"] == "FAILED"
    with pytest.raises(Conflict):
        world.service.cancel_slot(post_id, reason="already terminal")


def test_failed_required_slot_is_a_blocker_not_an_episode_failure(
    world: PublishingWorld,
) -> None:
    from microdrama.testing.fakes.publishing import PublishScenario

    world.adapters[Platform.YOUTUBE].queue_scenarios(PublishScenario.TOKEN_EXPIRED)
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    world.service.submit_slot(command, job_id=world.submit_job(command))

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"][0]["blocker"] == "TOKEN_EXPIRED"
    assert view["episode_outcome"] is None  # no episode-level outcome was forced

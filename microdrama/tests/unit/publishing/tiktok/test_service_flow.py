"""T022 service-level flows: the TikTok adapter under the REAL PublishingService.

Covers the full offline release (schedule → submit → poll → verified → release view),
the HeldSlot destination blockers (stale / disabled / unsupported disclosure), the
no-schedule-ahead rule, the rate-limit and ambiguous-submit paths, and replay dedupe.
"""

from __future__ import annotations

import pytest
from tiktok_support import TikTokWorld

from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport, Platform, SlotKind
from microdrama.contracts.errors import PolicyDenied
from microdrama.publishing.service import PUBLISH_DEADLINE_MS
from microdrama.publishing.tiktok.transport import (
    TikTokScenario,
    fixture_publish_id,
)


def _slot_row(world: TikTokWorld, episode_id):
    return world.row(
        "SELECT * FROM platform_posts WHERE episode_id = %s AND platform = 'TIKTOK'",
        (episode_id,),
    )


def test_full_offline_release_flow_schedule_to_verified(world: TikTokWorld) -> None:
    episode_id, command, job_id = world.submit_ready()
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "SUBMITTED"
    assert updated["external_id"] == fixture_publish_id(command.client_token)

    post_id = _slot_row(world, episode_id)["id"]
    processing = world.service.poll_status(post_id)
    assert processing["state"] == "PROCESSING"
    verified = world.service.poll_status(post_id)
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert verified["url"].split("//", 1)[1].split("/", 1)[0].endswith(".invalid")

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert view["blockers"] == []
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_stale_capability_record_holds_the_slot(world: TikTokWorld) -> None:
    episode_id, command, job_id = world.submit_ready()
    world.tiktok.bump_version()  # the record moved after scheduling
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_STALE"
    assert world.tiktok_transport.publish_ids == ()


def test_disabled_capability_holds_the_slot(tiktok_world) -> None:
    world = tiktok_world(enabled=False)
    _e, command, job_id = world.submit_ready()
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    assert world.tiktok_transport.publish_ids == ()


def test_unsupported_disclosure_holds_the_slot(tiktok_world) -> None:
    world = tiktok_world(
        operations_override={CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNSUPPORTED}
    )
    _e, command, job_id = world.submit_ready()
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"
    assert world.tiktok_transport.publish_ids == ()


def test_future_window_cannot_schedule_ahead(world: TikTokWorld) -> None:
    """TikTok direct post documents no schedule field: the slot waits for its window."""
    season_id = world.season()
    episode_id = world.episode(season_id)
    master = world.asset(season_id, episode_id)
    scope = world.tiktok_scope(
        season_id, episode_id, master, schedule=TikTokWorld.future_schedule()
    )
    package = world.package(season_id=season_id, episode_id=episode_id, scope=scope, master=master)
    approval = world.approve(season_id=season_id, episode_id=episode_id, package=package)
    world.schedule(episode_id)
    plan = next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)
    command = world.command(plan, package=package, approval_event_id=approval)
    with pytest.raises(PolicyDenied):
        world.service.submit_slot(command, job_id=world.submit_job(command))
    assert world.tiktok_transport.publish_ids == ()


def test_rate_limited_lands_in_retry_wait_then_retries(world: TikTokWorld) -> None:
    _e, command, job_id = world.submit_ready(scenario=TikTokScenario.RATE_LIMITED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "RETRY_WAIT"
    assert updated["last_error_code"] == "RATE_LIMITED"

    retry = world.service.submit_slot(command, job_id=job_id)
    assert retry["state"] == "SUBMITTED"
    assert retry["attempt"] == 2


def test_timeout_created_is_reconciled_adopted_and_verified(world: TikTokWorld) -> None:
    episode_id, command, job_id = world.submit_ready(scenario=TikTokScenario.TIMEOUT_CREATED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "NEEDS_RECONCILIATION"
    assert updated["external_id"] is None

    post_id = _slot_row(world, episode_id)["id"]
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    adopted = world.service.reconcile_slot(post_id)
    assert adopted["state"] == "PROCESSING"
    assert adopted["external_id"] == fixture_publish_id(command.client_token)

    verified = world.service.poll_status(post_id)
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_timeout_not_created_re_arms_the_same_token(world: TikTokWorld) -> None:
    episode_id, command, job_id = world.submit_ready(scenario=TikTokScenario.TIMEOUT_NOT_CREATED)
    updated = world.service.submit_slot(command, job_id=job_id)
    assert updated["state"] == "NEEDS_RECONCILIATION"

    post_id = _slot_row(world, episode_id)["id"]
    world.clock.advance(ms=PUBLISH_DEADLINE_MS + 1_000)
    rearmed = world.service.reconcile_slot(post_id)
    assert rearmed["state"] == "SUBMITTED"
    assert rearmed["attempt"] == 2

    submitted = world.service.submit_slot(command, job_id=job_id)
    assert submitted["state"] == "SUBMITTED"
    assert submitted["external_id"] == fixture_publish_id(command.client_token)


def test_replayed_submit_through_the_service_creates_one_post(world: TikTokWorld) -> None:
    _e, command, job_id = world.submit_ready()
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
    assert world.tiktok_transport.publish_ids == (first["external_id"],)


def test_optional_promo_cut_publishes_through_the_short_upload_op(world: TikTokWorld) -> None:
    """PROMO_CUT maps to UPLOAD_SHORT: same route, still inside the documented window."""
    season_id = world.season()
    episode_id = world.episode(season_id)
    master = world.asset(season_id, episode_id)
    scope = world.tiktok_scope(season_id, episode_id, master)
    scope += world.tiktok_scope(
        season_id,
        episode_id,
        master,
        slot="tt-promo",
        slot_kind=SlotKind.PROMO_CUT,
        required=False,
    )
    package = world.package(season_id=season_id, episode_id=episode_id, scope=scope, master=master)
    approval = world.approve(season_id=season_id, episode_id=episode_id, package=package)
    world.schedule(episode_id)

    full = next(p for p in package.release_scope if p.slot_kind is SlotKind.FULL_EPISODE)
    promo = next(p for p in package.release_scope if p.slot_kind is SlotKind.PROMO_CUT)
    full_command = world.command(full, package=package, approval_event_id=approval)
    world.service.submit_slot(full_command, job_id=world.submit_job(full_command))
    full_post = world.row("SELECT id FROM platform_posts WHERE release_slot = 'tt-full'", ())["id"]
    world.service.poll_status(full_post)
    world.service.poll_status(full_post)
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"

    promo_command = world.command(promo, package=package, approval_event_id=approval)
    promo_updated = world.service.submit_slot(promo_command, job_id=world.submit_job(promo_command))
    assert promo_updated["state"] == "SUBMITTED"
    assert promo_updated["external_id"] == fixture_publish_id(promo_command.client_token)
    # an optional slot never gates the full release
    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True

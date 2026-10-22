"""The Facebook adapter through the REAL PublishingService (T024).

Three layers of truth, all through ``PublishingService``:

1. The shipped snapshot: every MD-015 slot (AI_GENERATED_CONTENT is mandatory) HELDs
   with ``UNSUPPORTED_DISCLOSURE`` — the documented outcome while no Facebook Page
   API field can set and read back an AI label. Held paths for stale/disabled/
   unknown-upload records pin alongside.
2. The ``TEST_AI_CAPABLE_OPS`` test-only variant opens the pipeline so the full
   verify flow (schedule -> submit -> poll -> readback-gated PUBLISHED_VERIFIED ->
   release_view) and both explicit routes run end to end offline.
3. Crash-safety outcomes (TIMEOUT_* through the service) reconcile by client token:
   found posts are adopted, proven-absent ones re-arm the SAME token, capped.
"""

from __future__ import annotations

import uuid

import pytest
from facebook_support import (
    FUTURE_SCHEDULE,
    NO_FULL_VIDEO_OPS,
    TEST_AI_CAPABLE_OPS,
)

from microdrama.contracts.enums import Platform, SlotKind
from microdrama.contracts.errors import Conflict
from microdrama.publishing.facebook.transport import FacebookScenario
from microdrama.publishing.service import HeldSlot


def fb_episode(world, *, scope=None):
    """Season + approved episode whose release scope is Facebook-only."""
    if scope is None:

        def scope(season_id, episode_id, master):
            return [
                world.fb_slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, slot="full"
                )
            ]

    return world.approved_episode(scope_builder=scope)


class TestHeldPathsTheShippedSnapshotGuarantees:
    def test_ai_disclosed_slot_holds_unsupported_disclosure(self, fb_world) -> None:
        """Declaration truth through the service: the documented outcome for every
        Facebook slot while AI_DISCLOSURE is UNKNOWN."""
        world = fb_world()
        _s, episode_id, package, approval = fb_episode(world)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))

        assert updated["state"] == "HELD"
        assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"
        view = world.service.release_view(episode_id)
        assert view["full_release_ready"] is False
        assert view["blockers"][0]["blocker"] == "UNSUPPORTED_DISCLOSURE"
        # HELD is a destination blocker, not an episode failure
        assert world.episode_state(episode_id) == "SCHEDULED"

    def test_held_slot_stays_held_until_the_destination_changes(self, fb_world) -> None:
        world = fb_world()
        _s, episode_id, package, approval = fb_episode(world)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        world.service.submit_slot(command, job_id=world.submit_job(command))
        post_id = world.post_by_slot("full", episode_id)["id"]
        with pytest.raises(HeldSlot) as blocked:
            world.service.retry_held_slot(post_id)  # the destination check still fails
        assert blocked.value.blocker == "UNSUPPORTED_DISCLOSURE"

    def test_disabled_capability_holds(self, fb_world) -> None:
        world = fb_world(enabled=False)
        _s, episode_id, package, approval = fb_episode(world)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] == "HELD"
        assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"

    def test_stale_capability_holds(self, fb_world) -> None:
        world = fb_world()
        season_id = world.season()
        episode_id = world.episode(season_id)
        master = world.asset(season_id, episode_id)
        plan = world.fb_slot_plan(season_id=season_id, episode_id=episode_id, asset=master)
        stale = plan.model_copy(update={"capability_version": plan.capability_version + 1})
        package = world.package(
            season_id=season_id, episode_id=episode_id, scope=[stale], master=master
        )
        approval = world.approve(season_id=season_id, episode_id=episode_id, package=package)
        world.schedule(episode_id)
        command = world.command(stale, package=package, approval_event_id=approval)
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] == "HELD"
        assert updated["blocker"] == "CAPABILITY_STALE"

    def test_unknown_full_video_holds_full_episode_slots(self, fb_world) -> None:
        """No speculative capability: a record without UPLOAD_FULL_VIDEO HELDs
        FULL_EPISODE (CAPABILITY_UNAVAILABLE) even when the disclosure is supported."""
        world = fb_world(operations=NO_FULL_VIDEO_OPS)
        _s, episode_id, package, approval = fb_episode(world)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] == "HELD"
        assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"


class TestFullVerifyFlowWhereTheEncodingAllows:
    def test_schedule_to_verified_full_release(self, fb_world) -> None:
        world = fb_world(operations=TEST_AI_CAPABLE_OPS)
        _s, episode_id, package, approval = fb_episode(world)
        post_ids = world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] == "SUBMITTED"
        assert updated["external_id"].startswith("fb-full-")

        assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
        verified = world.service.poll_status(post_ids[0])
        assert verified["state"] == "PUBLISHED_VERIFIED"
        assert verified["url"].startswith("https://facebook.invalid/")
        assert verified["verified_fields"] == ["visibility", "disclosures"]

        view = world.service.release_view(episode_id)
        assert view["full_release_ready"] is True
        assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"

    def test_optional_hook_runs_the_reel_route_alongside_the_full_episode(self, fb_world):
        world = fb_world(operations=TEST_AI_CAPABLE_OPS)

        def scope(season_id, episode_id, master):
            return [
                world.fb_slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, slot="full",
                    slot_kind=SlotKind.FULL_EPISODE, required=True,
                ),
                world.fb_slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, slot="promo",
                    slot_kind=SlotKind.PROMO_CUT, required=False,
                ),
            ]  # fmt: skip

        _s, episode_id, package, approval = fb_episode(world, scope=scope)
        post_ids = world.schedule(episode_id)
        assert len(post_ids) == 2

        full_plan = next(p for p in package.release_scope if p.slot.release_slot == "full")
        promo_plan = next(p for p in package.release_scope if p.slot.release_slot == "promo")
        full_cmd = world.command(full_plan, package=package, approval_event_id=approval)
        promo_cmd = world.command(promo_plan, package=package, approval_event_id=approval)

        full = world.service.submit_slot(full_cmd, job_id=world.submit_job(full_cmd))
        assert full["external_id"].startswith("fb-full-")
        promo = world.service.submit_slot(promo_cmd, job_id=world.submit_job(promo_cmd))
        assert promo["external_id"].startswith("fb-reel-")

        reel_methods = [c.method for c in world.facebook.transport.calls]
        assert "start_reel_container" in reel_methods
        assert "start_page_video_upload" in reel_methods  # both routes ran

        promo_id = world.post_by_slot("promo", episode_id)["id"]
        assert world.service.poll_status(promo_id)["state"] == "PROCESSING"
        assert world.service.poll_status(promo_id)["state"] == "PUBLISHED_VERIFIED"

    def test_scheduled_full_video_publishes_only_at_its_window(self, fb_world) -> None:
        world = fb_world(operations=TEST_AI_CAPABLE_OPS)

        def scope(season_id, episode_id, master):
            return [
                world.fb_slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, slot="full",
                    schedule=FUTURE_SCHEDULE,
                )
            ]  # fmt: skip

        _s, episode_id, package, approval = fb_episode(world, scope=scope)
        post_ids = world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] in ("SUBMITTED", "PROCESSING")  # scheduled at the platform
        assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"

        world.clock.advance(seconds=4 * 3600)  # the 22:30 Bangkok window opens
        verified = world.service.poll_status(post_ids[0])
        assert verified["state"] == "PUBLISHED_VERIFIED"

    def test_future_window_short_slot_fails_schedule_unsupported_on_reels(self, fb_world):
        world = fb_world(operations=TEST_AI_CAPABLE_OPS)

        def scope(season_id, episode_id, master):
            return [
                world.fb_slot_plan(
                    season_id=season_id, episode_id=episode_id, asset=master, slot="promo",
                    slot_kind=SlotKind.PROMO_CUT, schedule=FUTURE_SCHEDULE,
                )
            ]  # fmt: skip

        _s, episode_id, package, approval = fb_episode(world, scope=scope)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        updated = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert updated["state"] == "FAILED"
        assert updated["last_error_code"] == "SCHEDULE_UNSUPPORTED_ON_REELS"
        view = world.service.release_view(episode_id)
        assert view["blockers"][0]["blocker"] == "SCHEDULE_UNSUPPORTED_ON_REELS"


class TestCrashSafetyThroughTheService:
    def test_rate_limited_lands_in_retry_wait_then_succeeds(self, fb_world) -> None:
        world = fb_world(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.RATE_LIMITED,))
        _s, episode_id, package, approval = fb_episode(world)
        post_ids = world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        limited = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert limited["state"] == "RETRY_WAIT"
        assert limited["attempt"] == 1
        assert limited["last_error_code"] == "RATE_LIMITED"

        retried = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert retried["state"] == "SUBMITTED"  # same client token, one more attempt
        assert retried["attempt"] == 2
        assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
        assert world.service.poll_status(post_ids[0])["state"] == "PUBLISHED_VERIFIED"

    def test_timeout_created_needs_reconciliation_then_adopts(self, fb_world) -> None:
        world = fb_world(
            operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.TIMEOUT_CREATED,)
        )
        _s, episode_id, package, approval = fb_episode(world)
        post_ids = world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        ambiguous = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert ambiguous["state"] == "NEEDS_RECONCILIATION"
        with pytest.raises(Conflict):  # a blind resubmit is refused while ambiguous
            world.service.submit_slot(command, job_id=world.submit_job(command))

        adopted = world.service.reconcile_slot(post_ids[0])
        assert adopted["state"] == "SUBMITTED"
        assert adopted["external_id"].startswith("fb-full-")
        assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
        assert world.service.poll_status(post_ids[0])["state"] == "PUBLISHED_VERIFIED"
        assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"

    def test_timeout_not_created_rearms_and_resubmits(self, fb_world) -> None:
        world = fb_world(
            operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.TIMEOUT_NOT_CREATED,)
        )
        _s, episode_id, package, approval = fb_episode(world)
        post_ids = world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        ambiguous = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert ambiguous["state"] == "NEEDS_RECONCILIATION"

        rearmed = world.service.reconcile_slot(post_ids[0])  # proven absent: same token re-armed
        assert rearmed["state"] == "SUBMITTED"
        assert rearmed["attempt"] == 2
        fresh = world.service.submit_slot(command, job_id=world.submit_job(command))
        assert fresh["state"] == "SUBMITTED"
        assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
        assert world.service.poll_status(post_ids[0])["state"] == "PUBLISHED_VERIFIED"

    def test_one_unmetered_job_linked_provider_operation_per_path(self, fb_world) -> None:
        world = fb_world(operations=TEST_AI_CAPABLE_OPS, scenarios=(FacebookScenario.RATE_LIMITED,))
        _s, episode_id, package, approval = fb_episode(world)
        world.schedule(episode_id)
        command = world.command(package.release_scope[0], package=package, approval_event_id=approval)  # fmt: skip
        world.service.submit_slot(command, job_id=world.submit_job(command))
        world.service.submit_slot(command, job_id=world.submit_job(command))

        ops = world.rows("SELECT * FROM provider_operations")
        assert len(ops) == 1  # the replay reused the token's operation
        assert ops[0]["operation_kind"] == "publish.submit_slot"
        assert ops[0]["job_id"] is not None
        assert ops[0]["reservation_id"] is None  # unmetered (contract 1.6.0)


class TestPlatformRegistration:
    def test_the_adapter_registers_under_facebook(self, fb_world) -> None:
        world = fb_world()
        from microdrama.contracts.providers import PublisherAdapter

        assert world.adapters[Platform.FACEBOOK] is world.facebook
        assert isinstance(world.facebook, PublisherAdapter)
        assert world.facebook.platform is Platform.FACEBOOK
        assert world.facebook.provider_route == "facebook-page"
        assert isinstance(uuid.uuid4(), uuid.UUID)  # sanity: world helpers intact

"""Contract pins for the Facebook adapter lane (T024).

Freezes the T024 surface the rest of the system builds against: PublisherAdapter
protocol conformance, the frozen capability snapshot (documentation-only claims,
empty supported disclosures — declaration truth), the explicit full/short route
selection, the scenario matrix (accepted / denied / 429 / timeout-ambiguous /
replayed) through the REAL service, and the documented outcome that every
AI-disclosed Facebook slot HELDs with UNSUPPORTED_DISCLOSURE until Meta documents a
settable-and-readable label field (T032 may revisit).

The service wiring mirrors ``test_publishing_contract.py``: a PublishingWorld
subclass swaps ``Platform.FACEBOOK`` for the T024 adapter and rebuilds the service.
The disclosure-capable operations map is a TEST-ONLY variant (never a shipped
capability) that opens the pipeline so the matrix can run through the service.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from publishing_support import PublishingWorld

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EvidenceSource,
    ExecutionMode,
    Platform,
    SlotKind,
)
from microdrama.contracts.providers import PublisherAdapter
from microdrama.persistence import Database
from microdrama.publishing.facebook import facebook_page_adapter
from microdrama.publishing.facebook.adapter import FacebookPageAdapter
from microdrama.publishing.facebook.capabilities import (
    FB_PAGE_ACCOUNT,
    FB_PAGE_OPERATIONS,
    FB_REEL_LIMITS,
    facebook_page_capability_record,
)
from microdrama.publishing.facebook.transport import (
    FacebookScenario,
    FixtureFacebookTransport,
)
from microdrama.publishing.service import PublishingService
from microdrama.testing.fakes.common import FakeClock, SequentialIds

#: TEST-ONLY capability variant (a Page surface that can set and read back the AI
#: label) so the scenario matrix can pass the service's disclosure gate. The SHIPPED
#: snapshot keeps AI_DISCLOSURE UNKNOWN and HELDs every MD-015 slot — see the
#: declaration-truth test below.
TEST_AI_CAPABLE_OPS: dict[CapabilityOperation, CapabilitySupport] = {
    **FB_PAGE_OPERATIONS,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
}

FUTURE_SCHEDULE = PublishingWorld.future_schedule()


class FacebookContractWorld(PublishingWorld):
    """PublishingWorld with the T024 adapter under Platform.FACEBOOK."""

    def __init__(
        self,
        db: Database,
        tmp: Path,
        settings: Settings,
        *,
        operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
        scenarios: tuple[FacebookScenario, ...] = (),
    ) -> None:
        super().__init__(db, tmp, settings)
        self.facebook = FacebookPageAdapter(
            clock=self.clock,
            transport=FixtureFacebookTransport(clock=self.clock, ids=self.ids, scenarios=scenarios),
            operations=operations,
            fixture=True,
        )
        self.adapters[Platform.FACEBOOK] = self.facebook
        self.service = PublishingService(self.db, self.clock, self.ids, self.adapters, self.store)

    def fb_episode(self, *, slot_kind: SlotKind = SlotKind.FULL_EPISODE, schedule=None):
        def scope(season_id, episode_id, master):
            return [
                self.slot_plan(
                    season_id=season_id,
                    episode_id=episode_id,
                    asset=master,
                    slot="full" if slot_kind is SlotKind.FULL_EPISODE else "promo",
                    platform=Platform.FACEBOOK,
                    account_ref=FB_PAGE_ACCOUNT,
                    slot_kind=slot_kind,
                    schedule=schedule,
                )
            ]

        return self.approved_episode(scope_builder=scope)


@pytest.fixture
def world(db, tmp_path, offline_settings) -> FacebookContractWorld:
    return FacebookContractWorld(db, tmp_path, offline_settings)


@pytest.fixture
def capable_world(db, tmp_path, offline_settings) -> FacebookContractWorld:
    return FacebookContractWorld(db, tmp_path, offline_settings, operations=TEST_AI_CAPABLE_OPS)


def test_facebook_adapters_satisfy_the_publisher_adapter_protocol() -> None:
    clock = FakeClock(PublishingWorld.past_schedule().utc_instant)
    ids = SequentialIds("fb-contract")
    fixture = facebook_page_adapter(clock=clock, ids=ids, settings=Settings())
    refusing = facebook_page_adapter(
        clock=clock, ids=ids, settings=Settings(execution_mode=ExecutionMode.PRODUCTION)
    )
    assert isinstance(fixture, PublisherAdapter)
    assert isinstance(refusing, PublisherAdapter)
    assert fixture.provider_route == "facebook-page"


def test_capability_snapshot_is_frozen() -> None:
    """Drift guard: the shipped claims are documentation-only and disclosure-empty."""
    assert dict(FB_PAGE_OPERATIONS) == {
        CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.METADATA_UPDATE: CapabilitySupport.SUPPORTED_DOCUMENTED,
        CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNKNOWN,
        CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
    }
    assert CapabilitySupport.SUPPORTED_TESTED not in set(FB_PAGE_OPERATIONS.values())
    assert FB_REEL_LIMITS.max_duration_ms == 90_000
    assert FB_REEL_LIMITS.aspect_ratios == ["9:16"]
    record = facebook_page_capability_record(FB_PAGE_ACCOUNT)
    assert record.supported_disclosures == []  # declaration truth
    assert record.enabled is False  # live publishing disabled until T032
    assert all(ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION for ref in record.evidence)
    assert all(
        "developers.facebook.com" in ref.ref and "2026-10" in ref.ref for ref in record.evidence
    )


@pytest.mark.parametrize(
    ("scenario", "expected_state"),
    [
        (FacebookScenario.ACCEPTED, "SUBMITTED"),
        (FacebookScenario.DENIED_PERMISSION, "FAILED"),
        (FacebookScenario.TOKEN_EXPIRED, "FAILED"),
        (FacebookScenario.RATE_LIMITED, "RETRY_WAIT"),
        (FacebookScenario.TIMEOUT_CREATED, "NEEDS_RECONCILIATION"),
        (FacebookScenario.TIMEOUT_NOT_CREATED, "NEEDS_RECONCILIATION"),
    ],
)
def test_provider_response_matrix_maps_to_slot_states(
    db, tmp_path, offline_settings, scenario: FacebookScenario, expected_state: str
) -> None:
    world = FacebookContractWorld(
        db, tmp_path, offline_settings, operations=TEST_AI_CAPABLE_OPS, scenarios=(scenario,)
    )
    _s, episode_id, package, approval = world.fb_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == expected_state
    # every path leaves exactly one durable provider operation, job-linked and unmetered
    ops = world.rows("SELECT * FROM provider_operations")
    assert len(ops) == 1
    assert ops[0]["operation_kind"] == "publish.submit_slot"
    assert ops[0]["provider"] == "facebook-page"
    assert ops[0]["job_id"] is not None
    assert ops[0]["reservation_id"] is None


def test_declaration_truth_holds_every_ai_disclosed_slot(world) -> None:
    """The documented outcome on the SHIPPED snapshot: MD-015 makes every slot
    declare AI_GENERATED_CONTENT, and the Facebook surface cannot support it —
    the slot HELDs with UNSUPPORTED_DISCLOSURE, an honest blocker, not a failure."""
    _s, episode_id, package, approval = world.fb_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"
    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is False
    assert view["blockers"][0]["blocker"] == "UNSUPPORTED_DISCLOSURE"


def test_explicit_route_selection_full_and_short(capable_world) -> None:
    """FULL_EPISODE -> videos edge (fb-full-), PROMO_CUT -> Reels edge (fb-reel-);
    the routes never call each other's endpoints."""
    world = capable_world
    _s, episode_id, package, approval = world.fb_episode()
    world.schedule(episode_id)
    full_cmd = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    full = world.service.submit_slot(full_cmd, job_id=world.submit_job(full_cmd))
    assert full["external_id"].startswith("fb-full-")

    _s2, episode2, package2, approval2 = world.fb_episode(slot_kind=SlotKind.PROMO_CUT)
    world.schedule(episode2)
    promo_cmd = world.command(
        package2.release_scope[0], package=package2, approval_event_id=approval2
    )
    promo = world.service.submit_slot(promo_cmd, job_id=world.submit_job(promo_cmd))
    assert promo["external_id"].startswith("fb-reel-")

    methods = [call.method for call in world.facebook.transport.calls]
    assert "start_page_video_upload" in methods
    assert "finish_page_video_upload" in methods
    assert "start_reel_container" in methods
    assert "publish_reel" in methods


def test_replayed_submit_is_deduplicated_by_client_token(capable_world) -> None:
    _s, episode_id, package, approval = capable_world.fb_episode()
    capable_world.schedule(episode_id)
    command = capable_world.command(
        package.release_scope[0], package=package, approval_event_id=approval
    )
    job_id = capable_world.submit_job(command)
    first = capable_world.service.submit_slot(command, job_id=job_id)
    second = capable_world.service.submit_slot(command, job_id=job_id)  # the job ran twice

    assert second["external_id"] == first["external_id"]
    assert (
        capable_world.row(
            "SELECT count(*) AS n FROM provider_operations WHERE client_token = %s",
            (command.client_token,),
        )["n"]
        == 1
    )
    assert len(capable_world.facebook.transport.videos) == 1  # one post at the platform


def test_scheduled_full_video_verifies_only_after_its_window(db, tmp_path, offline_settings):
    world = FacebookContractWorld(db, tmp_path, offline_settings, operations=TEST_AI_CAPABLE_OPS)
    _s, episode_id, package, approval = world.fb_episode(schedule=FUTURE_SCHEDULE)
    post_ids = world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["external_id"].startswith("fb-full-")
    assert world.service.poll_status(post_ids[0])["state"] == "PROCESSING"

    world.clock.advance(seconds=4 * 3600)  # the documented window opens
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert urlparse(verified["url"]).hostname.endswith(".invalid")
    assert world.service.release_view(episode_id)["full_release_ready"] is True


def test_full_offline_release_flow_schedule_to_verified(capable_world) -> None:
    """Where the encoding allows it (test variant): the whole release pipeline runs
    offline through the Facebook adapter, readback-gated exactly like the fakes."""
    _s, episode_id, package, approval = capable_world.fb_episode()
    post_ids = capable_world.schedule(episode_id)
    command = capable_world.command(
        package.release_scope[0], package=package, approval_event_id=approval
    )
    updated = capable_world.service.submit_slot(command, job_id=capable_world.submit_job(command))
    assert updated["external_id"].startswith("fb-full-")

    assert capable_world.service.poll_status(post_ids[0])["state"] == "PROCESSING"
    verified = capable_world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert urlparse(verified["url"]).hostname.endswith(".invalid")  # fake host only

    view = capable_world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert capable_world.episode_state(episode_id) == "PUBLISHED_VERIFIED"

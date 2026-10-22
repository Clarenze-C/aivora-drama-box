"""Contract pins for the TikTok adapter (T022).

Freeze the lane's contract surface: the ``PublisherAdapter`` protocol conformance of
the TikTok adapter, the frozen scenario matrix (accepted / denied / 429 / timeout
ambiguous x2 / replayed) through the REAL publishing service on the TIKTOK platform,
the readback-gated full offline release, and the inbox-route rule that can never be
mislabeled unattended. Capability claims stay documentation-only: nothing here may
ever pin ``SUPPORTED_TESTED`` (that evidence belongs to T032).
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from publishing_support import PublishingWorld

from microdrama.contracts.enums import CapabilitySupport, EvidenceSource, Platform
from microdrama.contracts.providers import PublisherAdapter
from microdrama.publishing.tiktok.capabilities import AS_OF
from microdrama.publishing.tiktok.transport import TikTokScenario, fixture_publish_id

_UNIT_TIKTOK = Path(__file__).resolve().parents[2] / "unit" / "publishing" / "tiktok"
if str(_UNIT_TIKTOK) not in sys.path:
    sys.path.insert(0, str(_UNIT_TIKTOK))


@pytest.fixture
def world(db, tmp_path: Path, offline_settings) -> PublishingWorld:
    from tiktok_support import TikTokWorld

    return TikTokWorld(db, tmp_path, offline_settings)


@pytest.fixture
def inbox_world(db, tmp_path: Path, offline_settings) -> PublishingWorld:
    from tiktok_support import TikTokWorld

    from microdrama.publishing.tiktok.capabilities import TikTokRoute

    return TikTokWorld(db, tmp_path, offline_settings, route=TikTokRoute.INBOX_UPLOAD)


def _tiktok_plan(package):
    return next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)


def test_tiktok_adapter_satisfies_the_publisher_protocol(world: PublishingWorld) -> None:
    assert isinstance(world.adapters[Platform.TIKTOK], PublisherAdapter)


def test_capability_claims_are_documentation_only(world: PublishingWorld) -> None:
    record = world.adapters[Platform.TIKTOK].capability("acct:tiktok-main")
    assert CapabilitySupport.SUPPORTED_TESTED not in set(record.operations.values())
    assert record.enabled is True  # the OFFLINE_MOCK fixture variant
    assert any(ref.source is EvidenceSource.FAKE_FIXTURE for ref in record.evidence)
    documented = [
        ref for ref in record.evidence if ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION
    ]
    assert documented and all(AS_OF in ref.ref for ref in documented)


@pytest.mark.parametrize(
    ("scenario", "expected_state"),
    [
        (TikTokScenario.ACCEPTED, "SUBMITTED"),
        (TikTokScenario.DENIED_PERMISSION, "FAILED"),
        (TikTokScenario.TOKEN_EXPIRED, "FAILED"),
        (TikTokScenario.RATE_LIMITED, "RETRY_WAIT"),
        (TikTokScenario.TIMEOUT_CREATED, "NEEDS_RECONCILIATION"),
        (TikTokScenario.TIMEOUT_NOT_CREATED, "NEEDS_RECONCILIATION"),
    ],
)
def test_provider_response_matrix_maps_to_slot_states(
    world: PublishingWorld, scenario: TikTokScenario, expected_state: str
) -> None:
    world.tiktok_transport.queue_scenarios(scenario)
    _s, episode_id, package, approval = world.approved_tiktok_episode()
    world.schedule(episode_id)
    plan = _tiktok_plan(package)
    command = world.command(plan, package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["state"] == expected_state
    # every path leaves exactly one durable provider operation, job-linked and unmetered
    ops = world.rows("SELECT * FROM provider_operations")
    assert len(ops) == 1
    assert ops[0]["operation_kind"] == "publish.submit_slot"
    assert ops[0]["provider"] == "tiktok-direct-post"
    assert ops[0]["job_id"] is not None
    assert ops[0]["reservation_id"] is None


def test_replayed_submit_is_deduplicated_by_client_token(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_tiktok_episode()
    world.schedule(episode_id)
    command = world.command(_tiktok_plan(package), package=package, approval_event_id=approval)
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
    # the adapter answered the replay from its token map, creating no second post
    assert world.tiktok_transport.publish_ids == (first["external_id"],)


def test_full_offline_release_flow_schedule_to_verified(world: PublishingWorld) -> None:
    _s, episode_id, package, approval = world.approved_tiktok_episode()
    post_ids = world.schedule(episode_id)
    command = world.command(_tiktok_plan(package), package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["external_id"] == fixture_publish_id(command.client_token)

    processing = world.service.poll_status(post_ids[0])
    assert processing["state"] == "PROCESSING"
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert urlparse(verified["url"]).hostname.endswith(".invalid")  # fake host only

    view = world.service.release_view(episode_id)
    assert view["full_release_ready"] is True
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


def test_inbox_route_slot_is_held_never_published_unattended(
    inbox_world: PublishingWorld,
) -> None:
    """The core mislabel freeze: INBOX uploads need a human, so the slot HELDs."""
    _s, episode_id, package, approval = inbox_world.approved_tiktok_episode()
    inbox_world.schedule(episode_id)
    command = inbox_world.command(
        _tiktok_plan(package), package=package, approval_event_id=approval
    )
    updated = inbox_world.service.submit_slot(command, job_id=inbox_world.submit_job(command))
    assert updated["state"] == "HELD"
    assert updated["blocker"] == "CAPABILITY_UNAVAILABLE"
    assert updated["external_id"] is None
    assert inbox_world.tiktok_transport.publish_ids == ()
    assert inbox_world.episode_state(episode_id) == "SCHEDULED"

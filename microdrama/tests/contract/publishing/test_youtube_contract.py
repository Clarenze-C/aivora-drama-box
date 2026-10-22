"""Contract pins for the YouTube adapter (T021).

Freeze the pieces the platform lanes and the integrator build against: the
adapter's conformance to the frozen ``PublisherAdapter`` protocol, the scenario
matrix (accepted / denied / 429 / timeout-ambiguous ×2 / replayed) through the
service surface, the offline-only factory guard, the named live-transport
refusal, and the honesty of the capability snapshot (documentation-only claims,
no SUPPORTED_TESTED anywhere, live route disabled until T032).
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import CapabilitySupport, ExecutionMode
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.contracts.providers import PublisherAdapter
from microdrama.contracts.release import PublicationCommand
from microdrama.publishing.youtube import (
    LiveYouTubeTransport,
    YouTubeScenario,
    build_youtube_adapter,
)
from microdrama.publishing.youtube.capabilities import research_capability_record
from microdrama.publishing.youtube.transport import youtube_external_id
from microdrama.testing.fakes.common import FakeClock, SequentialIds

_UNIT_YOUTUBE = Path(__file__).resolve().parents[2] / "unit" / "publishing" / "youtube"
if str(_UNIT_YOUTUBE) not in sys.path:
    sys.path.insert(0, str(_UNIT_YOUTUBE))

from publishing_support import T0  # noqa: E402
from youtube_support import YouTubeWorld  # noqa: E402


@pytest.fixture
def world(db, tmp_path, offline_settings) -> YouTubeWorld:
    return YouTubeWorld(db, tmp_path, offline_settings)


def test_youtube_adapter_satisfies_the_frozen_publisher_protocol(world: YouTubeWorld) -> None:
    assert isinstance(world.youtube, PublisherAdapter)
    # the service drives exactly these; they must exist on the frozen interface
    for method in ("capability", "submit", "status", "reconcile", "update_metadata", "readback"):
        assert callable(getattr(world.youtube, method))


def test_publication_command_input_model_is_unchanged(world: YouTubeWorld) -> None:
    """The adapter consumes the frozen command model; nothing platform-specific leaks in."""
    from microdrama.contracts.jobs import JOB_SPECS

    spec = next(s for s in JOB_SPECS if s.job_type == "publish.submit_slot")
    assert spec.input_model is PublicationCommand


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
def test_scenario_matrix_through_the_service(
    world: YouTubeWorld, scenario: YouTubeScenario, expected_state: str
) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    world.youtube.queue_scenarios(scenario)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))

    assert updated["state"] == expected_state
    ops = world.rows("SELECT * FROM provider_operations")
    assert len(ops) == 1
    assert ops[0]["operation_kind"] == "publish.submit_slot"
    assert ops[0]["reservation_id"] is None  # unmetered publish kind (contract 1.6.0)


def test_replayed_submit_is_deduplicated_by_client_token(world: YouTubeWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    first = world.service.submit_slot(command, job_id=job_id)
    second = world.service.submit_slot(command, job_id=job_id)  # the job ran twice

    assert (
        second["external_id"] == first["external_id"] == youtube_external_id(command.client_token)
    )
    assert (
        world.row(
            "SELECT count(*) AS n FROM provider_operations WHERE client_token = %s",
            (command.client_token,),
        )["n"]
        == 1
    )
    assert world.youtube.transport.video_count() == 1


def test_full_offline_release_flow_schedule_to_verified(world: YouTubeWorld) -> None:
    _s, episode_id, package, approval = world.approved_episode()
    post_ids = world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    updated = world.service.submit_slot(command, job_id=world.submit_job(command))
    assert updated["external_id"] == youtube_external_id(command.client_token)

    world.service.poll_status(post_ids[0])
    verified = world.service.poll_status(post_ids[0])
    assert verified["state"] == "PUBLISHED_VERIFIED"
    assert urlparse(verified["url"]).hostname.endswith(".invalid")  # fake host only

    assert world.service.release_view(episode_id)["full_release_ready"] is True
    assert world.episode_state(episode_id) == "PUBLISHED_VERIFIED"


@pytest.mark.parametrize(
    "mode",
    [ExecutionMode.PAID_BENCHMARK, ExecutionMode.CONTROLLED_ACCOUNT_TEST, ExecutionMode.PRODUCTION],
)
def test_offline_factory_refuses_every_non_mock_mode(
    offline_settings: Settings, mode: ExecutionMode
) -> None:
    settings = offline_settings.model_copy(update={"execution_mode": mode})
    with pytest.raises(EffectDenied):
        build_youtube_adapter(settings, clock=FakeClock(T0), ids=SequentialIds("refused"))


def test_live_transport_construction_is_a_named_refusal() -> None:
    with pytest.raises(PolicyDenied) as err:
        LiveYouTubeTransport()
    assert "T032" in str(err.value)
    assert err.value.details.get("blocked_until") == "T032"


def test_capability_claims_stay_documentation_only(world: YouTubeWorld) -> None:
    fixture_record = world.youtube.capability("acct:youtube-main")
    assert CapabilitySupport.SUPPORTED_TESTED not in fixture_record.operations.values()
    assert fixture_record.evidence_is_fake_only is True  # offline fixture, honest labels

    research = research_capability_record("acct:youtube-main")
    assert research.enabled is False  # the live route ships disabled
    assert CapabilitySupport.SUPPORTED_TESTED not in research.operations.values()
    assert research.evidence  # documentation-only sources, dated in each ref

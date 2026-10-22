"""Contract pins for the Instagram adapter lane (T023).

Freezes what T021-T024 sibling lanes and the integrator build against:

- the adapter satisfies the shared ``PublisherAdapter`` protocol;
- the frozen provider response matrix maps to slot states — BUT through the
  service every Instagram row lands HELD/UNSUPPORTED_DISCLOSURE with zero provider
  operations and no destination call, because MD-015 requires an AI disclosure on
  every slot and this platform honestly has no documented API surface to set or
  read one back (the declaration truth; pinned here as the documented outcome);
- the scenario mechanics themselves are contract-pinned at the adapter boundary,
  where they are reachable;
- the factory returns the fixture variant only in OFFLINE_MOCK and a refusing
  adapter in every other mode (live publishing disabled until T032).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, ReleaseState
from microdrama.contracts.errors import NeedsReconciliation, RateLimited
from microdrama.contracts.providers import PublisherAdapter
from microdrama.publishing.instagram import DEFAULT_ACCOUNT_REF, build_instagram_adapter
from microdrama.publishing.instagram.transport import (
    FixtureInstagramTransport,
    InstagramScenario,
    instagram_media_id,
)

_IG_UNIT = Path(__file__).resolve().parents[2] / "unit" / "publishing" / "instagram"
if str(_IG_UNIT) not in sys.path:
    sys.path.insert(0, str(_IG_UNIT))

# Load the lane's support module under the lane-unique name (the same name the
# unit conftest registers), so parallel adapter lanes' support modules can never
# collide inside one pytest process and this file never re-executes it.
if "instagram_lane_support" in sys.modules:
    _SUPPORT = sys.modules["instagram_lane_support"]
else:
    _SPEC = importlib.util.spec_from_file_location(
        "instagram_lane_support", _IG_UNIT / "support.py"
    )
    _SUPPORT = importlib.util.module_from_spec(_SPEC)
    sys.modules["instagram_lane_support"] = _SUPPORT
    assert _SPEC.loader is not None
    _SPEC.loader.exec_module(_SUPPORT)
InstagramWorld = _SUPPORT.InstagramWorld
ig_command = _SUPPORT.ig_command
write_media = _SUPPORT.write_media

SCENARIO_ROWS = (
    (InstagramScenario.ACCEPTED, "HELD"),
    (InstagramScenario.DENIED_PERMISSION, "HELD"),
    (InstagramScenario.TOKEN_EXPIRED, "HELD"),
    (InstagramScenario.RATE_LIMITED, "HELD"),
    (InstagramScenario.TIMEOUT_CREATED, "HELD"),
    (InstagramScenario.TIMEOUT_NOT_CREATED, "HELD"),
)


@pytest.fixture
def world(db, tmp_path, offline_settings) -> InstagramWorld:
    return InstagramWorld(db, tmp_path, offline_settings)


def test_instagram_adapter_satisfies_the_publisher_protocol(
    world: InstagramWorld, offline_settings: Settings
) -> None:
    assert isinstance(world.adapter, PublisherAdapter)
    assert isinstance(build_instagram_adapter(offline_settings), PublisherAdapter)


@pytest.mark.parametrize(("scenario", "expected_state"), SCENARIO_ROWS)
def test_scenario_matrix_through_the_service_lands_held(
    world: InstagramWorld, scenario: InstagramScenario, expected_state: str
) -> None:
    """The documented outcome for EVERY provider row: the destination cannot
    support the mandatory AI disclosure, so the slot HELDs before the provider
    operation begins — the scripted platform response is never even consumed."""
    _season, episode_id, package, approval = world.approved_instagram_episode()
    world.transport.queue_scenarios(scenario)
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)

    updated = world.service.submit_slot(command, job_id=world.submit_job(command))

    assert updated["state"] == expected_state
    assert updated["blocker"] == "UNSUPPORTED_DISCLOSURE"
    assert world.rows("SELECT * FROM provider_operations") == []
    # the scripted platform response was never consumed: the hold precedes the wire
    consumed = [call for call in world.transport.calls if call.method == "create_container"]
    assert consumed == []
    assert world.transport.create_container_calls == 0


def test_replayed_held_submit_conflicts_with_zero_operations(world: InstagramWorld) -> None:
    """The client-token dedupe path through the service: the first run holds the
    slot; a rerun of the same job conflicts (HELD is not submittable) and still
    nothing reached the provider."""
    from microdrama.contracts.errors import Conflict

    _season, episode_id, package, approval = world.approved_instagram_episode()
    world.schedule(episode_id)
    command = world.command(package.release_scope[0], package=package, approval_event_id=approval)
    job_id = world.submit_job(command)
    first = world.service.submit_slot(command, job_id=job_id)
    assert first["state"] == "HELD"

    with pytest.raises(Conflict):
        world.service.submit_slot(command, job_id=job_id)
    assert world.rows("SELECT * FROM provider_operations") == []
    assert (
        world.row("SELECT count(*) AS n FROM platform_posts WHERE external_id IS NOT NULL")["n"]
        == 0
    )


def test_declaration_truth_is_pinned_on_the_capability_record(
    world: InstagramWorld,
) -> None:
    """MD-015 requires AI_GENERATED_CONTENT on every slot; the Instagram record
    honestly carries no supported disclosure, so the held outcome above is the
    ONLY outcome possible on this platform until a verified mechanism exists."""
    from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport
    from microdrama.publishing.instagram import capabilities as caps

    record = world.adapter.capability(DEFAULT_ACCOUNT_REF)
    assert record.supported_disclosures == []
    assert record.support(CapabilityOperation.AI_DISCLOSURE) is CapabilitySupport.UNSUPPORTED
    documented = caps.documented_capability_record(
        account_ref=DEFAULT_ACCOUNT_REF, account_type="BUSINESS"
    )
    assert documented.enabled is False  # live disabled until T032
    assert documented.supported_disclosures == []


@pytest.mark.parametrize(
    ("scenario", "kind"),
    [
        (InstagramScenario.ACCEPTED, "submitted"),
        (InstagramScenario.DENIED_PERMISSION, "failed"),
        (InstagramScenario.TOKEN_EXPIRED, "failed"),
        (InstagramScenario.RATE_LIMITED, "rate_limited"),
        (InstagramScenario.TIMEOUT_CREATED, "reconcile_found"),
        (InstagramScenario.TIMEOUT_NOT_CREATED, "reconcile_absent"),
    ],
)
def test_adapter_scenario_matrix_maps_provider_responses(
    offline_settings: Settings, tmp_path: Path, scenario: InstagramScenario, kind: str
) -> None:
    """The frozen platform response mapping, pinned at the adapter boundary
    (the only boundary where the disclosure hold does not preempt it)."""
    adapter = build_instagram_adapter(offline_settings, scenarios=(scenario,))
    media = write_media(tmp_path)
    command = ig_command(media)

    if kind == "submitted":
        result = adapter.submit(command, media[0])
        assert result.state is ReleaseState.SUBMITTED
        assert result.external_id is not None
    elif kind == "failed":
        result = adapter.submit(command, media[0])
        assert result.state is ReleaseState.FAILED
        assert result.transient is False
    elif kind == "rate_limited":
        with pytest.raises(RateLimited) as limited:
            adapter.submit(command, media[0])
        assert limited.value.details["retry_after_ms"] == 60_000
    else:
        with pytest.raises(NeedsReconciliation):
            adapter.submit(command, media[0])
        outcome = adapter.reconcile(command)
        assert outcome.found is (kind == "reconcile_found")
        assert (outcome.result is not None) is (kind == "reconcile_found")


def test_full_offline_adapter_flow_publishes_but_disclosure_stays_unverified(
    offline_settings: Settings, tmp_path: Path
) -> None:
    """The documented container flow end to end: submit -> container, poll ->
    processing, poll -> published media id + permalink, readback visible but
    disclosure-blind (an AI disclosure can never VERIFY on this API)."""
    adapter = build_instagram_adapter(offline_settings)
    media = write_media(tmp_path)
    command = ig_command(media)

    submitted = adapter.submit(command, media[0])
    assert submitted.state is ReleaseState.SUBMITTED
    processing = adapter.status(command, submitted.external_id)
    assert processing.state is ReleaseState.PROCESSING
    verified = adapter.status(command, submitted.external_id)
    assert verified.state is ReleaseState.PUBLISHED_VERIFIED
    assert verified.external_id == instagram_media_id(command.client_token)

    from urllib.parse import urlparse

    assert urlparse(verified.url).hostname.endswith(".invalid")  # fake host only

    readback = adapter.readback(command.slot.account_ref, verified.external_id)
    assert readback.visible is True
    assert readback.disclosures_visible == []
    assert "disclosures" in readback.unverified_fields


def test_factory_offline_is_fixture_and_non_mock_refuses(
    offline_settings: Settings, tmp_path: Path
) -> None:
    offline = build_instagram_adapter(offline_settings)
    assert isinstance(offline._transport, FixtureInstagramTransport)
    assert offline.capability(DEFAULT_ACCOUNT_REF).enabled is True

    live = build_instagram_adapter(Settings(execution_mode=ExecutionMode.PRODUCTION))
    with pytest.raises(Exception, match="T032"):
        live.capability(DEFAULT_ACCOUNT_REF)
    media = write_media(tmp_path)
    with pytest.raises(Exception, match="T032"):
        live.submit(ig_command(media), media[0])

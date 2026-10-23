"""AT-13 reproduced independently: blockers stay blockers, secrets stay secret,
and the offline wall holds.

A green QA score cannot bypass a disabled account capability (the frozen T006
evaluator, driven through its public API with a behaviorally-recorded disabled
version); the composed world cannot be constructed outside OFFLINE_MOCK (no
fake provider silently falls through to production); every verified pilot post
URL is a fake.invalid fixture; and session credentials never appear in the
durable payloads the flows produce.
"""

from __future__ import annotations

import uuid

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    DisclosureKind,
    ExecutionMode,
    Platform,
)
from microdrama.contracts.errors import EffectDenied
from microdrama.core.registry.capabilities import CapabilityRegistry
from microdrama.core.registry.release_conditions import (
    DestinationRequirement,
    evaluate_release_conditions,
)
from microdrama.core.registry.rights import RightsRegistry
from microdrama.pipeline.conditions import MOCK_OUTPUT_ROUTE
from microdrama.pipeline.world import build_pipeline_world

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _destination(platform: Platform = Platform.YOUTUBE) -> DestinationRequirement:
    return DestinationRequirement(
        platform=platform,
        account_ref="acct:fake-main",
        required_ops=frozenset(
            {
                CapabilityOperation.UPLOAD_FULL_VIDEO,
                CapabilityOperation.STATUS,
                CapabilityOperation.READBACK,
            }
        ),
        disclosures=frozenset({DisclosureKind.AI_GENERATED_CONTENT}),
        required=True,
        provider_route=None,
    )


def test_disabled_capability_blocks_release_despite_green_qa(validation_world) -> None:
    """The same destination clears with the seeded enabled capability and blocks
    after a behaviorally-recorded disabled version — with ``qa_all_green=True``
    throughout. QA green never waives an account blocker."""
    world = validation_world
    capabilities = CapabilityRegistry(world.db, world.fakes.clock, world.settings)
    rights = RightsRegistry(world.db, world.fakes.clock, world.settings)
    subjects = [("MODEL_OUTPUT", MOCK_OUTPUT_ROUTE)]

    clear = evaluate_release_conditions(
        rights=rights,
        capabilities=capabilities,
        rights_route_id=MOCK_OUTPUT_ROUTE,
        rights_subjects=subjects,
        territories=("TH",),
        destinations=[_destination()],
        at=world.fakes.clock.now(),
        qa_all_green=True,
    )
    destination_blockers = [b for b in clear if "destination" in b.lower() or "capab" in b.lower()]
    assert destination_blockers == [], clear

    # Record a disabled next version through the registry's own API (behavior,
    # not a hand-edited row), then the identical evaluation must block.
    current = capabilities.current(Platform.YOUTUBE, "acct:fake-main")
    assert current is not None and current.enabled
    disabled = current.model_copy(update={"enabled": False, "version": current.version + 1})
    from microdrama.contracts.enums import Provenance

    capabilities.record(disabled, source_provenance=Provenance.FAKE_SYNTHETIC)

    blocked = evaluate_release_conditions(
        rights=rights,
        capabilities=capabilities,
        rights_route_id=MOCK_OUTPUT_ROUTE,
        rights_subjects=subjects,
        territories=("TH",),
        destinations=[_destination()],
        at=world.fakes.clock.now(),
        qa_all_green=True,
    )
    assert blocked != [], "a disabled capability must block despite green QA"
    assert any("capab" in b.lower() or "destination" in b.lower() for b in blocked), blocked


def test_the_composed_world_refuses_to_exist_outside_offline_mock(tmp_path) -> None:
    """No fake provider falls through to production: constructing the composition
    with PAID_BENCHMARK or PRODUCTION settings raises EffectDenied at the first
    external boundary — before any service exists (the DB is never touched)."""
    for mode in (ExecutionMode.PAID_BENCHMARK, ExecutionMode.PRODUCTION):
        settings = Settings(execution_mode=mode, object_store_root=tmp_path / "objects")
        with pytest.raises(EffectDenied):
            build_pipeline_world(settings, None)  # type: ignore[arg-type]


def test_every_verified_pilot_post_lives_on_a_fake_domain(pilot) -> None:
    world, report = pilot
    with world.db.transaction(readonly=True) as tx:
        urls = tx.fetchall(
            "SELECT url FROM platform_posts WHERE episode_id = %s "
            "AND state = 'PUBLISHED_VERIFIED' AND url IS NOT NULL",
            (report.episode_id,),
        )
    assert urls, "the pilot verified posts"
    for row in urls:
        assert row["url"].endswith(".fake.invalid") or ".fake.invalid/" in row["url"], row["url"]


def test_session_credentials_never_reach_durable_payloads(validation_world) -> None:
    """Run real flows (owner session, jobs, a webhook), then scan every durable
    payload the flows produced for the live session token and password."""
    import json

    world = validation_world
    world.auth.create_owner("t030-secret-owner", "t030-real-password-xyz")
    tokens = world.auth.login("t030-secret-owner", "t030-real-password-xyz")
    from microdrama.contracts.jobs import EpisodeStepInput

    with world.db.transaction() as tx:
        world.jobs.enqueue(
            tx,
            job_type="qa.technical",
            semantic_key=f"t030.secret:{uuid.uuid4().hex[:8]}",
            payload=EpisodeStepInput(episode_id=uuid.uuid4()),
        )
    event = {"id": "evt-t030-secret", "type": "members:pledge:create", "member_ref": "member:t030"}
    from microdrama.testing.fakes.membership import SIGNATURE_HEADER, fake_signature

    body = json.dumps(event).encode()
    world.memberships.entitlements.process_webhook({SIGNATURE_HEADER: fake_signature(body)}, body)

    secrets = (tokens.session_token, "t030-real-password-xyz")
    with world.db.transaction(readonly=True) as tx:
        payloads = tx.fetchall(
            "SELECT payload::text AS t FROM webhook_events UNION ALL SELECT input::text FROM jobs"
        )
    for row in payloads:
        for secret in secrets:
            assert secret not in row["t"], "a session credential leaked into a durable payload"
    # Member refs are hashed in stored webhook payloads (AT-13 privacy).
    with world.db.transaction(readonly=True) as tx:
        stored = tx.fetchall(
            "SELECT payload::text AS t FROM webhook_events WHERE event_id = %s",
            ("evt-t030-secret",),
        )
    assert stored and all("member:t030" not in row["t"] for row in stored)

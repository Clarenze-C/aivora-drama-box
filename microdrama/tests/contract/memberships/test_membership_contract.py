"""Contract guarantees for the membership lane (T026), pinned end-to-end.

The frozen contracts this lane consumes — ``MembershipProvider``,
``MembershipCatalogEntry`` truthfulness validators, ``WebhookVerification``,
``ManagementAction`` metering invariants — are exercised here THROUGH the lane's
services and adapter, not by re-testing the contracts in isolation (that is the
guardian's ``tests/contract/contracts`` suite).
"""

from __future__ import annotations

import uuid

import pytest
from membership_support import PRICE, MembershipWorld, bangkok_instant

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode, Provenance
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.contracts.providers import MembershipProvider
from microdrama.memberships.patreon import (
    BMC_ALTERNATE_NOTE,
    LIVE_DISABLED_MESSAGE,
    LivePatreonTransport,
    build_patreon_adapter,
)


@pytest.fixture
def episode(world: MembershipWorld):
    season = world.season()
    episode_id = world.episode(season, number=2)
    return season, episode_id


class TestProtocolConformance:
    def test_adapter_satisfies_the_frozen_membership_provider_protocol(self, world):
        assert isinstance(world.services.adapter, MembershipProvider)

    def test_offline_factory_refuses_every_non_mock_mode(self, offline_settings, db, tmp_path):
        from microdrama.testing.fakes.common import FakeClock, SequentialIds

        for mode in (
            ExecutionMode.CONTROLLED_ACCOUNT_TEST,
            ExecutionMode.PRODUCTION,
        ):
            settings = Settings(execution_mode=mode)
            with pytest.raises(EffectDenied):
                build_patreon_adapter(
                    settings,
                    clock=FakeClock(bangkok_instant(27).utc_instant),
                    ids=SequentialIds("contract"),
                )

    def test_live_transport_construction_is_a_named_refusal(self):
        with pytest.raises(PolicyDenied, match=LIVE_DISABLED_MESSAGE):
            LivePatreonTransport()

    def test_bmc_stays_a_documented_alternate_never_a_half_built_route(self):
        from microdrama.memberships.patreon.capabilities import RESEARCH_OPERATIONS

        # The snapshot speaks only for the Patreon route; BMC appears only as the
        # documented note, and no BMC adapter/builder exists to construct.
        assert "Buy Me a Coffee" in BMC_ALTERNATE_NOTE
        assert not any("bmc" in op for op in RESEARCH_OPERATIONS)

    def test_research_snapshot_ships_disabled_and_documented_only(self):
        from microdrama.memberships.patreon.capabilities import (
            RESEARCH_OPERATIONS,
            research_snapshot,
        )

        snapshot = research_snapshot()
        assert snapshot.enabled is False
        assert not any(
            support.value == "SUPPORTED_TESTED" for support in snapshot.operations.values()
        )
        assert RESEARCH_OPERATIONS["membership.early_access_publish"].value == "UNKNOWN"


class TestCatalogContractTruth:
    def test_contract_validator_blocks_early_access_without_approval_through_the_service(
        self, world, episode
    ):
        """The contract's own truthfulness rule, driven through the service."""
        season, episode_id = episode
        with pytest.raises(PolicyDenied):
            world.catalog.publish_early_access(
                season_id=season,
                episode_id=episode_id,
                episode_number=2,
                provider=world.services.adapter,
                media_path=world.tmp / "m.mp4",
                approval_event_id=uuid.uuid4(),
                price=PRICE,
                free_release=bangkok_instant(31),
            )

    def test_contract_validator_blocks_secret_tokens_in_catalog_urls(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        world.clock.advance(seconds=4 * 24 * 3600)
        with pytest.raises(PolicyDenied, match="PUBLISHED_VERIFIED"):
            world.catalog.mark_public_free(
                episode_id=episode_id,
                public_url="https://watch.fake.invalid/e?token=leak",
            )

    def test_every_persisted_entry_body_round_trips_the_contract(self, world, episode):
        from microdrama.contracts.catalog import MembershipCatalogEntry

        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        rows = world.rows(
            "SELECT body FROM membership_catalog WHERE episode_id = %s", (episode_id,)
        )
        assert rows
        for row in rows:
            entry = MembershipCatalogEntry.model_validate(row["body"])
            assert entry.provenance is Provenance.FAKE_SYNTHETIC

    def test_all_offline_results_are_fake_provenance(self, world, episode):
        season, episode_id = episode
        entry = world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        assert entry.provenance is Provenance.FAKE_SYNTHETIC
        assert ".invalid" in entry.member_url
        decision = world.entitlements.check(member_ref="m-1", episode_id=episode_id)
        assert decision.entitled is True  # default scenario ACTIVE


class TestWebhookContract:
    def test_valid_webhook_verification_always_carries_an_event_id(self, world, episode):
        import json

        from microdrama.testing.fakes.membership import SIGNATURE_HEADER, fake_signature

        _, episode_id = episode
        body = json.dumps(
            {
                "id": "evt-c1",
                "type": "members:pledge:create",
                "member_ref": "m-1",
                "episode_id": str(episode_id),
            }
        ).encode()
        verification = world.services.adapter.verify_webhook(
            {SIGNATURE_HEADER: fake_signature(body)}, body
        )
        assert verification.valid and verification.event_id == "evt-c1"

    def test_invalid_webhook_verification_never_carries_its_payload(self, world):
        from microdrama.testing.fakes.membership import SIGNATURE_HEADER, fake_signature

        body = b'{"id": "evt-c2", "spoiler": "untrusted"}'
        verification = world.services.adapter.verify_webhook(
            {SIGNATURE_HEADER: fake_signature(body + b"x")},
            body,  # wrong signature
        )
        assert verification.valid is False
        assert verification.payload == {}

    def test_invalid_webhooks_are_rejected_end_to_end_by_the_service(self, world, episode):
        import json

        from microdrama.testing.fakes.membership import SIGNATURE_HEADER

        _, episode_id = episode
        body = json.dumps(
            {
                "id": "evt-c3",
                "type": "members:pledge:create",
                "member_ref": "m-1",
                "episode_id": str(episode_id),
            }
        ).encode()
        outcome = world.entitlements.process_webhook({SIGNATURE_HEADER: "deadbeef"}, body)
        assert outcome.valid is False
        assert world.rows("SELECT * FROM webhook_events") == []
        assert world.rows("SELECT * FROM entitlement_links") == []


class TestManagementActionContract:
    def test_executed_metered_dm_carries_its_reservation(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        outcome = world.dm.handle_inbound(
            world.dm_event("contract-dm-1", "ตอนต่อไปคะ"), episode_id=episode_id
        )
        assert outcome.sent
        row = world.row("SELECT * FROM management_actions")
        assert row["reservation_id"] is not None  # metered before execution
        assert row["policy_hash"] == world.dm._policy_hash
        assert row["decision"] == "EXECUTED"

    def test_suppressed_actions_record_their_reason(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        outcome = world.dm.handle_inbound(
            world.dm_event("contract-dm-2", "no keyword here"), episode_id=episode_id
        )
        assert outcome.status.name == "IGNORED"
        assert (
            world.row(
                "SELECT status FROM community_events WHERE provider_event_id = 'contract-dm-2'"
            )["status"]
            == "IGNORED"
        )

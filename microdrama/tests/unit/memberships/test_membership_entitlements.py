"""Provider entitlement checks and webhook verification (T026).

Pinned rules: access flows only from ``active=True`` provider checks tied to the
current entry; revoked/unverifiable never yields access and no fallback link
exists; raw member identifiers never persist; checks are metered through the real
BudgetService; AT-11 insufficient-budget behavior stays truthful.
"""

from __future__ import annotations

import json

import pytest
from membership_support import MembershipWorld, bangkok_instant

from microdrama.contracts.errors import PolicyDenied, SchemaInvalid
from microdrama.memberships.catalog import member_ref_hash
from microdrama.testing.fakes.membership import (
    FAKE_WEBHOOK_SECRET,
    SIGNATURE_HEADER,
    EntitlementScenario,
    fake_signature,
)

MEMBER = "member-117"


@pytest.fixture
def gated(world: MembershipWorld):
    """An episode with open member early access."""
    season = world.season()
    episode_id = world.episode(season, number=2)
    world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
    return season, episode_id


def signed_body(event: dict) -> tuple[dict, bytes]:
    body = json.dumps(event).encode()
    return {SIGNATURE_HEADER: fake_signature(body)}, body


class TestEntitlementChecks:
    def test_active_member_is_entitled_against_the_current_entry(self, world, gated):
        _, episode_id = gated
        decision = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert decision.entitled is True
        assert decision.active is True
        assert decision.tier == "fake-supporter"
        row = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert row is not None and row["active"] is True
        assert row["verification_method"] == "provider_api"

    def test_revoked_member_is_not_entitled_and_gets_no_fallback(self, world, gated):
        _, episode_id = gated
        world.provider.queue_scenarios(EntitlementScenario.REVOKED)
        decision = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert decision.entitled is False
        assert decision.active is False
        # No fallback link materializes for the revoked member: the only recorded
        # link row says active=false.
        row = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert row["active"] is False

    def test_stale_active_row_never_survives_a_fresh_revoked_check(self, world, gated):
        """An unlisted link is not entitlement enforcement (hard rule 4)."""
        _, episode_id = gated
        first = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert first.entitled is True
        world.provider.queue_scenarios(EntitlementScenario.REVOKED)
        second = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert second.entitled is False  # the fresh check overrides the stale row
        row = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert row["active"] is False and row["revision"] >= 1

    def test_unverifiable_active_none_is_never_entitled(self, world, gated):
        _, episode_id = gated
        world.provider.queue_scenarios(EntitlementScenario.UNVERIFIABLE)
        decision = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert decision.active is None
        assert decision.entitled is False
        assert "never treated as entitled" in decision.reason
        row = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert row["active"] is None  # NULL = could not verify

    def test_raw_member_identifiers_never_persist(self, world, gated):
        _, episode_id = gated
        world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        headers, body = signed_body(
            {
                "id": "evt-priv",
                "type": "members:pledge:create",
                "member_ref": MEMBER,
                "episode_id": str(episode_id),
            }
        )
        world.entitlements.process_webhook(headers, body)
        hashed = member_ref_hash(MEMBER)
        assert hashed != MEMBER and len(hashed) == 64
        rows = world.rows("SELECT member_ref_hash FROM entitlement_links")
        assert rows and all(r["member_ref_hash"] == hashed for r in rows)
        # Raw identifiers are hashed even in the stored webhook payloads.
        stored_payloads = world.rows("SELECT payload::text AS t FROM webhook_events")
        assert all(MEMBER not in r["t"] for r in stored_payloads)

    def test_ungated_episode_has_nothing_to_check_or_grant(self, world, gated):
        season = world.season()
        episode_id = world.episode(season, number=3)
        decision = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert decision.entitled is False
        assert decision.active is None
        assert "no member-gated" in decision.reason
        # No provider call was made (nothing to verify against).
        assert all(c.method != "check_entitlement" for c in world.provider.calls)

    def test_blank_member_ref_is_rejected(self, world, gated):
        _, episode_id = gated
        with pytest.raises(SchemaInvalid):
            world.entitlements.check(member_ref="  ", episode_id=episode_id)


class TestMeteredChecks:
    def test_each_check_reserves_and_settles_one_metered_request(self, world, gated):
        _, episode_id = gated
        world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        state = world.metered_state(episode_id)
        assert state["settled_micro_usd"] == 1_000
        assert state["cat_committed"] == 1_000
        assert state["reserved_micro_usd"] == 0  # settled, not left held

    def test_insufficient_metered_budget_suppresses_truthfully(
        self, world, gated, db, tmp_path, offline_settings
    ):
        """AT-11: no metered room -> could-not-verify, never entitled, never faked."""
        from membership_support import MembershipWorld as W

        # A dedicated world whose metered allocation fits exactly ONE request.
        tight = W(
            db,
            tmp_path,
            offline_settings,
            metered_micro_usd=1_000,
            ids_namespace="memberships-tight",
        )
        season = tight.season()
        episode_id = tight.episode(season, number=5)
        tight.open_early_access(season, episode_id, number=5, free_release=bangkok_instant(31))
        first = tight.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert first.entitled is True  # the single request fits
        second = tight.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert second.metered_suppressed is True
        assert second.entitled is False
        assert second.active is None
        assert "metered-management budget exhausted" in second.reason
        # The refusal is real budgeting, not a stub: allocation fully committed.
        state = tight.metered_state(episode_id)
        assert state["cat_committed"] == state["allocated_micro_usd"]

    def test_metered_check_never_touches_protected_categories(self, world, gated):
        _, episode_id = gated
        world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        gpu = world.row(
            "SELECT a.reserved_outstanding_micro_usd, a.accrued_micro_usd, a.settled_micro_usd "
            "FROM budget_category_allocations a "
            "JOIN budget_accounts b ON b.id = a.account_id WHERE b.episode_id = %s "
            "AND a.category = 'GPU_GENERATION'",
            (episode_id,),
        )
        assert gpu["reserved_outstanding_micro_usd"] == 0
        assert gpu["accrued_micro_usd"] == 0
        assert gpu["settled_micro_usd"] == 0


class TestWebhooks:
    def pledge_event(self, world, episode_id, event_id="evt-1", active=True):
        event_type = "members:pledge:create" if active else "members:pledge:delete"
        return signed_body(
            {
                "id": event_id,
                "type": event_type,
                "member_ref": MEMBER,
                "episode_id": str(episode_id),
            }
        )

    def test_valid_signed_webhook_records_and_updates_the_link(self, world, gated):
        _, episode_id = gated
        headers, body = self.pledge_event(world, episode_id)
        outcome = world.entitlements.process_webhook(headers, body)
        assert outcome.valid and outcome.applied and outcome.active is True
        assert outcome.duplicate is False
        row = world.row("SELECT * FROM webhook_events WHERE event_id = 'evt-1'")
        assert row["signature_valid"] is True
        assert row["processed_at"] is not None
        link = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert link["active"] is True
        assert link["verification_method"] == "webhook_signature"
        assert link["last_webhook_event"] == row["id"]

    def test_missing_signature_is_rejected_before_any_record(self, world, gated):
        _, episode_id = gated
        _, body = self.pledge_event(world, episode_id)
        outcome = world.entitlements.process_webhook({}, body)
        assert outcome.valid is False
        assert outcome.failure_reason == "MISSING_SIGNATURE"
        assert world.rows("SELECT * FROM webhook_events") == []
        assert world.rows("SELECT * FROM entitlement_links") == []

    def test_bad_signature_is_rejected_and_passes_no_payload_on(self, world, gated):
        _, episode_id = gated
        _, body = self.pledge_event(world, episode_id)
        forged = {SIGNATURE_HEADER: "0" * 64}
        outcome = world.entitlements.process_webhook(forged, body)
        assert outcome.valid is False
        assert outcome.failure_reason == "SIGNATURE_MISMATCH"
        # No link row: a forged webhook can never create entitlement.
        assert world.rows("SELECT * FROM entitlement_links") == []
        # And the service never surfaced the untrusted payload.
        assert not hasattr(outcome, "payload")

    def test_malformed_body_is_rejected(self, world, gated):
        _, episode_id = gated
        body = b"not-json"
        headers = {SIGNATURE_HEADER: fake_signature(body)}
        outcome = world.entitlements.process_webhook(headers, body)
        assert outcome.valid is False
        assert outcome.failure_reason == "MALFORMED_BODY"

    def test_duplicate_webhook_delivery_never_repeats_its_effect(self, world, gated):
        _, episode_id = gated
        headers, body = self.pledge_event(world, episode_id)
        first = world.entitlements.process_webhook(headers, body)
        second = world.entitlements.process_webhook(headers, body)
        assert first.applied and second.duplicate and not second.applied
        assert len(world.rows("SELECT * FROM webhook_events")) == 1
        link = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert link["revision"] == 0  # the duplicate did not re-apply

    def test_pledge_delete_marks_the_link_inactive(self, world, gated):
        _, episode_id = gated
        headers, body = self.pledge_event(world, episode_id, event_id="evt-2", active=False)
        outcome = world.entitlements.process_webhook(headers, body)
        assert outcome.applied and outcome.active is False
        link = world.entitlements.link_row(
            member_ref=MEMBER,
            entry_id=world.catalog.current_entry(episode_id).entry_id,
        )
        assert link["active"] is False

    def test_unknown_event_type_is_recorded_without_effect(self, world, gated):
        _, episode_id = gated
        headers, body = signed_body(
            {
                "id": "evt-3",
                "type": "members:unknown:thing",
                "member_ref": MEMBER,
                "episode_id": str(episode_id),
            }
        )
        outcome = world.entitlements.process_webhook(headers, body)
        assert outcome.valid and not outcome.applied
        assert "unknown webhook event type" in (outcome.reason or "")
        assert world.rows("SELECT * FROM entitlement_links") == []

    def test_webhook_alone_grants_no_access_without_a_provider_check(self, world, gated):
        """Rule 4 end-to-end: the link row is bookkeeping; access needs a check."""
        _, episode_id = gated
        headers, body = self.pledge_event(world, episode_id)
        world.entitlements.process_webhook(headers, body)
        # The webhook said active, but a fresh provider check that says REVOKED wins.
        world.provider.queue_scenarios(EntitlementScenario.REVOKED)
        decision = world.entitlements.check(member_ref=MEMBER, episode_id=episode_id)
        assert decision.entitled is False

    def test_webhook_secret_is_not_a_playback_token_in_any_url(self, world, gated):
        _, episode_id = gated
        entry = world.catalog.current_entry(episode_id)
        assert FAKE_WEBHOOK_SECRET.decode() not in (entry.member_url or "")
        assert FAKE_WEBHOOK_SECRET.decode() not in (entry.public_url or "")


class TestProviderRouteRules:
    def test_adapter_refuses_entries_of_another_provider_kind(self, world, gated):
        from microdrama.contracts.enums import MembershipProviderKind

        _, episode_id = gated
        entry = world.catalog.current_entry(episode_id)
        bmc_entry = entry.model_copy(
            update={"member_provider": MembershipProviderKind.BUY_ME_A_COFFEE}
        )
        with pytest.raises(PolicyDenied, match="another membership provider"):
            world.services.adapter.publish_early_access(bmc_entry, world.tmp / "media.mp4")

    def test_adapter_refuses_non_early_access_entries(self, world, gated):
        from microdrama.contracts.enums import CatalogPublicState

        _, episode_id = gated
        entry = world.catalog.current_entry(episode_id)
        public = entry.model_copy(update={"public_state": CatalogPublicState.PUBLIC_FREE})
        with pytest.raises(PolicyDenied, match="EARLY_ACCESS_MEMBERS"):
            world.services.adapter.publish_early_access(public, world.tmp / "media.mp4")

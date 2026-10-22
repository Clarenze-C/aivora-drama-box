"""Permitted keyword/inbound DM delivery (T026 acceptance: windows, recipient
restrictions, caps, duplicate suppression, MD-016 content truth, real metering)."""

from __future__ import annotations

import pytest
from membership_support import KEYWORDS, MembershipWorld, bangkok_instant

from microdrama.community.dm.service import DmReason, DmStatus
from microdrama.contracts.enums import CommunityEventKind
from microdrama.testing.fakes.community import INJECTION_COMMENT, CommunityScenario

MEMBER = "member-117"


@pytest.fixture
def gated(world: MembershipWorld):
    season = world.season()
    episode_id = world.episode(season, number=2)
    world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
    return season, episode_id


class TestHappyPath:
    def test_keyword_dm_with_open_window_sends_a_member_unlock(self, world, gated):
        _, episode_id = gated
        event = world.dm_event("dm-1", "ตอนต่อไป ตอนที่ 2 ค่ะ")
        outcome = world.dm.handle_inbound(event, episode_id=episode_id)
        assert outcome.sent
        assert outcome.message_kind == "member_unlock"
        entry = world.catalog.current_entry(episode_id)
        assert entry.member_url in outcome.message_content
        assert outcome.action.decision.value == "EXECUTED"
        # One durable action row, event ACTIONED.
        assert (
            world.row("SELECT status FROM community_events WHERE provider_event_id = 'dm-1'")[
                "status"
            ]
            == "ACTIONED"
        )

    def test_comment_with_keyword_and_open_window_unlocks_once(self, world, gated):
        _, episode_id = gated
        event = world.dm_event("c-1", "Next please", kind=CommunityEventKind.COMMENT)
        outcome = world.dm.handle_inbound(event, episode_id=episode_id)
        assert outcome.sent

    def test_the_send_is_metered_with_reserve_and_settle(self, world, gated):
        _, episode_id = gated
        before = world.metered_state(episode_id)
        world.dm.handle_inbound(world.dm_event("dm-2", "ตอนต่อไป"), episode_id=episode_id)
        after = world.metered_state(episode_id)
        # The entitlement check AND the DM send each settle one metered request.
        assert after["settled_micro_usd"] - before["settled_micro_usd"] == 2_000
        assert after["reserved_micro_usd"] == 0


class TestDuplicateSuppression:
    def test_exact_duplicate_delivery_never_repeats_the_message(self, world, gated):
        _, episode_id = gated
        event = world.dm_event("dm-3", "ตอนต่อไปคะ")
        first = world.dm.handle_inbound(event, episode_id=episode_id)
        second = world.dm.handle_inbound(event, episode_id=episode_id)
        assert first.sent
        assert second.status is DmStatus.DUPLICATE_DELIVERY
        assert len(world.rows("SELECT * FROM community_events")) == 1
        assert len(world.rows("SELECT * FROM management_actions")) == 1
        assert len(world.community.ledger) == 1  # the provider saw exactly one send

    def test_a_new_comment_from_the_same_author_never_repeats_the_unlock(self, world, gated):
        """Duplicate comments (different event ids) still do not re-send."""
        _, episode_id = gated
        first = world.dm.handle_inbound(world.dm_event("c-10", "ตอนต่อไปคะ"), episode_id=episode_id)
        second = world.dm.handle_inbound(
            world.dm_event("c-11", "ตอนต่อไปอีกครั้งคะ"), episode_id=episode_id
        )
        assert first.sent
        assert second.status is DmStatus.SUPPRESSED
        assert second.reason is DmReason.UNLOCK_ALREADY_SENT
        assert len(world.community.ledger) == 1

    def test_a_different_episode_from_the_same_author_can_unlock(self, world, gated):
        season, episode_id = gated
        other = world.episode(season, number=3)
        world.open_early_access(season, other, number=3, free_release=bangkok_instant(31))
        assert world.dm.handle_inbound(
            world.dm_event("c-20", "ตอนต่อไป"), episode_id=episode_id
        ).sent
        assert world.dm.handle_inbound(world.dm_event("c-21", "ตอนต่อไป"), episode_id=other).sent


class TestEligibility:
    def test_no_keyword_is_ignored_including_injection_attempts(self, world, gated):
        _, episode_id = gated
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-9", "random chatter, no keyword"), episode_id=episode_id
        )
        assert outcome.status is DmStatus.IGNORED
        assert outcome.reason is DmReason.NO_KEYWORD
        injection = world.dm_event("dm-10", INJECTION_COMMENT)
        outcome = world.dm.handle_inbound(injection, episode_id=episode_id)
        assert outcome.status is DmStatus.IGNORED  # untrusted text is data, never executed

    def test_unhandled_event_kinds_are_ignored(self, world, gated):
        _, episode_id = gated
        outcome = world.dm.handle_inbound(
            world.dm_event("m-1", "ตอนต่อไป", kind=CommunityEventKind.MENTION),
            episode_id=episode_id,
        )
        assert outcome.status is DmStatus.IGNORED
        assert outcome.reason is DmReason.NOT_A_PERMITTED_EVENT

    def test_missing_window_defers_the_dm(self, world, gated):
        _, episode_id = gated
        event = world.dm_event(
            "c-30", "ตอนต่อไป", window_hours=None, kind=CommunityEventKind.COMMENT
        )
        outcome = world.dm.handle_inbound(event, episode_id=episode_id)
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.NO_MESSAGING_WINDOW
        assert world.community.ledger == []

    def test_expired_window_suppresses_the_dm(self, world, gated):
        _, episode_id = gated
        event = world.dm_event("dm-31", "ตอนต่อไป", window_hours=-1)
        outcome = world.dm.handle_inbound(event, episode_id=episode_id)
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.WINDOW_EXPIRED

    def test_blocked_recipient_is_never_messaged(
        self, world, gated, db, tmp_path, offline_settings
    ):
        from microdrama.community.dm import build_dm_delivery_service

        _, episode_id = gated
        blocked = build_dm_delivery_service(
            db=db,
            clock=world.clock,
            ids=world.ids,
            community=world.community,
            catalog=world.catalog,
            entitlements=world.entitlements,
            budget=world.budget,
            policy=world.policy,
            blocked_recipient_refs=frozenset({MEMBER}),
        )
        outcome = blocked.handle_inbound(
            world.dm_event("dm-32", "ตอนต่อไป", author=MEMBER), episode_id=episode_id
        )
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.BLOCKED_RECIPIENT

    def test_the_account_never_dms_itself(self, world, gated):
        _, episode_id = gated
        event = world.dm_event("dm-33", "ตอนต่อไป", author="acct:ig-members")
        outcome = world.dm.handle_inbound(event, episode_id=episode_id)
        assert outcome.reason is DmReason.BLOCKED_RECIPIENT

    def test_conversation_cap_bounds_total_dms(self, world, gated):
        season, episode_id = gated
        other = world.episode(season, number=3)
        world.open_early_access(season, other, number=3, free_release=bangkok_instant(31))
        third = world.episode(season, number=4)
        world.open_early_access(season, third, number=4, free_release=bangkok_instant(31))
        fourth = world.episode(season, number=5)
        world.open_early_access(season, fourth, number=5, free_release=bangkok_instant(31))
        results = [
            world.dm.handle_inbound(
                world.dm_event(f"c-4{i}", "ตอนต่อไป", author="chatty-1"),
                episode_id=target,
            )
            for i, target in enumerate((episode_id, other, third, fourth), start=1)
        ]
        assert [r.sent for r in results[:3]] == [True, True, True]  # max_dms_per_conversation=3
        assert results[3].status is DmStatus.SUPPRESSED
        assert results[3].reason is DmReason.CONVERSATION_CAP

    def test_policy_without_dm_send_silences_the_lane(self, world, gated):
        from microdrama.contracts.season import ManagementPolicy

        _, episode_id = gated
        world.dm._policy = ManagementPolicy(
            allowed_actions=frozenset({"PUBLIC_REPLY"}), dm_keywords=list(KEYWORDS)
        )
        outcome = world.dm.handle_inbound(world.dm_event("dm-34", "ตอนต่อไป"), episode_id=episode_id)
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.DM_SEND_NOT_ALLOWED


class TestTransientRetry:
    def test_deferred_send_keeps_its_reservation_and_retries_cleanly(self, world, gated):
        _, episode_id = gated
        world.community.queue_scenarios(CommunityScenario.RATE_LIMITED)
        first = world.dm.handle_inbound(world.dm_event("dm-40", "ตอนต่อไป"), episode_id=episode_id)
        assert first.status is DmStatus.DEFERRED
        assert first.provider_error == "RATE_LIMITED"
        # The reservation stays held for the retry (not settled, not released).
        state = world.metered_state(episode_id)
        assert state["reserved_micro_usd"] >= 1_000
        # A later inbound event retries the SAME unlock: sent exactly once.
        world.community.queue_scenarios(CommunityScenario.HAPPY)
        retry = world.dm.handle_inbound(
            world.dm_event("dm-41", "ตอนต่อไป ค่ะ"), episode_id=episode_id
        )
        assert retry.sent
        assert retry.message_content == first.message_content
        assert len([c for c in world.community.ledger]) == 1
        after = world.metered_state(episode_id)
        assert after["reserved_micro_usd"] == 0  # settled by the retry


class TestContentTruth:
    def test_public_free_unlock_carries_the_public_url_and_never_the_paywall(self, world):
        season = world.season()
        episode_id = world.episode(season, number=7)
        world.open_early_access(season, episode_id, number=7, free_release=bangkok_instant(28))
        world.clock.advance(seconds=4 * 24 * 3600)
        url = world.published_post_url(episode_id)
        world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-50", "ตอนต่อไปคะ", author="freebie-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "free_unlock"
        assert url in outcome.message_content
        member_url = world.catalog.current_entry(episode_id).member_url
        assert member_url not in outcome.message_content

    def test_not_entitled_member_gets_price_plus_free_date_before_checkout(self, world, gated):
        from microdrama.testing.fakes.membership import EntitlementScenario

        _, episode_id = gated
        world.provider.queue_scenarios(EntitlementScenario.REVOKED)
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-51", "ตอนต่อไปคะ", author="stranger-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "early_access_offer"
        assert "$3.00/month" in outcome.message_content  # labelled price (MD-016)
        assert world.catalog.current_entry(episode_id).member_url in outcome.message_content
        assert "2026-10-31T19:30" in outcome.message_content  # the free alternative

    def test_unverifiable_entitlement_sends_no_member_link(self, world, gated):
        from microdrama.testing.fakes.membership import EntitlementScenario

        _, episode_id = gated
        world.provider.queue_scenarios(EntitlementScenario.UNVERIFIABLE)
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-52", "ตอนต่อไปคะ", author="ghost-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "verification_unavailable"
        member_url = world.catalog.current_entry(episode_id).member_url
        assert member_url not in outcome.message_content

    def test_unreleased_episode_is_offered_nothing(self, world):
        season = world.season()
        episode_id = world.episode(season, number=2)
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-53", "ตอนต่อไปคะ"), episode_id=episode_id
        )
        assert outcome.sent and outcome.message_kind == "not_available"
        assert "http" not in outcome.message_content

    def test_withdrawn_episode_is_no_longer_sold(self, world, gated):
        _, episode_id = gated
        world.catalog.withdraw(episode_id=episode_id, reason="quality repair")
        outcome = world.dm.handle_inbound(
            world.dm_event("dm-54", "ตอนต่อไปคะ", author="late-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "withdrawn"
        member_url = world.catalog.current_entry(episode_id).member_url
        assert member_url not in outcome.message_content


class TestBudgetTruth:
    def test_insufficient_metered_budget_suppresses_the_send_without_lying(
        self, world, gated, db, tmp_path, offline_settings
    ):
        from membership_support import MembershipWorld as W

        tight = W(
            db,
            tmp_path,
            offline_settings,
            metered_micro_usd=1_000,
            ids_namespace="memberships-tight-dm",
        )
        season = tight.season()
        episode_id = tight.episode(season, number=6)
        tight.open_early_access(season, episode_id, number=6, free_release=bangkok_instant(31))
        # The single metered request is consumed by the entitlement check, so the
        # DM send itself can no longer reserve: suppressed, nothing delivered.
        outcome = tight.dm.handle_inbound(
            tight.dm_event("dm-60", "ตอนต่อไปคะ"), episode_id=episode_id
        )
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.METERED_BUDGET_EXHAUSTED
        assert tight.community.ledger == []  # the provider was never called
        assert outcome.message_content is None  # nothing was claimed delivered
        row = tight.row("SELECT status FROM community_events WHERE provider_event_id = 'dm-60'")
        assert row["status"] == "SUPPRESSED"


class TestNoColdOutreach:
    def test_the_only_send_path_is_an_inbound_event(self, world, gated):
        """MD-018: every executed send follows an inbound event (no initiate API)."""
        _, episode_id = gated
        send_methods = [
            name for name in dir(world.dm) if not name.startswith("_") and "send" in name.lower()
        ]
        assert send_methods == []  # no public send/initiate surface exists
        before = len(world.community.calls)
        world.dm.handle_inbound(world.dm_event("dm-61", "ตอนต่อไปคะ"), episode_id=episode_id)
        executes = [c for c in world.community.calls[before:] if c.method == "execute"]
        assert len(executes) == 1  # the send exists only because the event did

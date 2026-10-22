"""AT-11 end-to-end sweep: free/paid catalog and DM messages stay truthful through
delayed release, cancellation, public transition and insufficient metered-management
budget. One narrative per scenario, through the REAL services and fakes.
"""

from __future__ import annotations

import pytest
from membership_support import MembershipWorld, bangkok_instant

from microdrama.community.dm.service import DmReason, DmStatus
from microdrama.contracts.enums import CatalogPublicState
from microdrama.memberships.catalog import FreeDateOwnerDecision


@pytest.fixture
def episode(world: MembershipWorld):
    season = world.season()
    episode_id = world.episode(season, number=2)
    return season, episode_id


class TestDelayedRelease:
    def test_catalog_and_messages_stay_truthful_when_the_free_date_passes(self, world, episode):
        """Delayed release: no free claim, original date quoted as the original promise."""
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        world.clock.advance(seconds=3 * 24 * 3600)  # the announced date has passed

        facts = world.catalog.facts(episode_id)
        assert facts.state is CatalogPublicState.EARLY_ACCESS_MEMBERS  # not free yet
        assert facts.free_release_passed is True

        # A non-member asking now still gets a TRUTHFUL offer: the original promise
        # quoted as the original promise, never re-promised as upcoming.
        from microdrama.testing.fakes.membership import EntitlementScenario

        world.provider.queue_scenarios(EntitlementScenario.REVOKED)
        outcome = world.dm.handle_inbound(
            world.dm_event("at11-delay-1", "ตอนต่อไปคะ", author="waiter-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "early_access_offer"
        assert "ตามกำหนดเดิม" in outcome.message_content  # "per the original schedule"
        assert "2026-10-28T19:30" in outcome.message_content

        # And the free CTA still does not exist: no public URL was invented.
        assert world.catalog.current_entry(episode_id).public_url is None

    def test_the_public_transition_later_restores_the_free_promise(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        world.clock.advance(seconds=3 * 24 * 3600)
        url = world.published_post_url(episode_id)
        entry = world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        assert entry.public_state is CatalogPublicState.PUBLIC_FREE
        assert entry.free_release == bangkok_instant(28)  # original instant preserved
        outcome = world.dm.handle_inbound(
            world.dm_event("at11-delay-2", "ตอนต่อไปคะ", author="waiter-2"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "free_unlock"
        assert url in outcome.message_content


class TestCancellation:
    def test_withdrawal_stops_every_offer_and_no_link_survives(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        world.catalog.withdraw(episode_id=episode_id, reason="creator pulled the cut")

        # A member with a VERIFIED active entitlement still gets nothing: the
        # catalog state gates the message before the entitlement does.
        outcome = world.dm.handle_inbound(
            world.dm_event("at11-cancel-1", "ตอนต่อไปคะ", author="paid-1"),
            episode_id=episode_id,
        )
        assert outcome.sent and outcome.message_kind == "withdrawn"
        entry = world.catalog.current_entry(episode_id)
        assert entry.member_url not in outcome.message_content

        # Selling again is refused while the media is withdrawn... a re-open is a
        # new owner-visible version, and the announced date still cannot move.
        with pytest.raises(Exception, match="cannot silently move"):
            world.open_early_access(season, episode_id, free_release=bangkok_instant(30))


class TestPublicTransition:
    def test_member_to_public_flow_never_leaves_a_paywall_cta(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(29))
        member_ask = world.dm.handle_inbound(
            world.dm_event("at11-pub-1", "ตอนต่อไปคะ", author="buyer-1"),
            episode_id=episode_id,
        )
        assert member_ask.sent and member_ask.message_kind == "member_unlock"

        world.clock.advance(seconds=4 * 24 * 3600)
        url = world.published_post_url(episode_id)
        world.catalog.mark_public_free(episode_id=episode_id, public_url=url)

        # After the transition, the same question yields the FREE link only.
        free_ask = world.dm.handle_inbound(
            world.dm_event("at11-pub-2", "ตอนต่อไปคะ", author="buyer-2"),
            episode_id=episode_id,
        )
        assert free_ask.sent and free_ask.message_kind == "free_unlock"
        assert url in free_ask.message_content
        assert world.catalog.current_entry(episode_id).member_url not in (free_ask.message_content)
        # And the catalog can never go back to selling it.
        with pytest.raises(Exception, match="not truthful"):
            world.open_early_access(season, episode_id)


class TestInsufficientMeteredBudget:
    def test_budget_starvation_never_lies_in_catalog_or_message(
        self, world, episode, db, tmp_path, offline_settings
    ):
        from membership_support import MembershipWorld as W

        tight = W(
            db,
            tmp_path,
            offline_settings,
            metered_micro_usd=1_000,
            ids_namespace="memberships-at11",
        )
        season = tight.season()
        episode_id = tight.episode(season, number=8)
        tight.open_early_access(season, episode_id, number=8, free_release=bangkok_instant(31))

        # The one metered request funds the entitlement check; the send cannot
        # reserve and is suppressed with a recorded reason. Nothing is delivered
        # and nothing claims otherwise.
        outcome = tight.dm.handle_inbound(
            tight.dm_event("at11-budget-1", "ตอนต่อไปคะ", author="hungry-1"),
            episode_id=episode_id,
        )
        assert outcome.status is DmStatus.SUPPRESSED
        assert outcome.reason is DmReason.METERED_BUDGET_EXHAUSTED
        assert tight.community.ledger == []
        assert outcome.message_content is None

        # The catalog itself is untouched and still truthful: early access with
        # the original price and the original free date.
        entry = tight.catalog.current_entry(episode_id)
        assert entry.public_state is CatalogPublicState.EARLY_ACCESS_MEMBERS
        assert entry.free_release == bangkok_instant(31)
        assert entry.member_price.amount_micro_usd == 3_000_000

        # Metered starvation never leaks into protected funds.
        gpu = tight.row(
            "SELECT a.reserved_outstanding_micro_usd, a.accrued_micro_usd, "
            "a.settled_micro_usd FROM budget_category_allocations a "
            "JOIN budget_accounts b ON b.id = a.account_id WHERE b.episode_id = %s "
            "AND a.category = 'GPU_GENERATION'",
            (episode_id,),
        )
        assert (
            gpu["reserved_outstanding_micro_usd"],
            gpu["accrued_micro_usd"],
            gpu["settled_micro_usd"],
        ) == (0, 0, 0)


class TestSweepHonesty:
    def test_every_sent_message_names_its_catalog_version(self, world, episode):
        """Every delivered DM is auditable against the exact catalog version used."""
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        outcome = world.dm.handle_inbound(
            world.dm_event("at11-audit-1", "ตอนต่อไปคะ"), episode_id=episode_id
        )
        assert outcome.catalog_version == 1
        body = world.row("SELECT body, catalog_version FROM management_actions")
        assert body["catalog_version"] == 1
        assert body["body"]["content"] == outcome.message_content

    def test_owner_free_date_change_is_always_a_visible_event(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        world.open_early_access(
            season,
            episode_id,
            free_release=bangkok_instant(30, hour=20),
            owner_decision=FreeDateOwnerDecision(reason="at11 sweep decision"),
        )
        events = world.rows(
            "SELECT * FROM domain_events WHERE event_type = 'membership.free_date_changed'"
        )
        assert len(events) == 1
        assert events[0]["payload"]["decided_by"] == "owner"

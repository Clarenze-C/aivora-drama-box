"""Truthful catalog transitions (T026 acceptance: unfinished/unapproved cannot be
sold; free-date immutability; PUBLIC_FREE needs a verified URL; version chain)."""

from __future__ import annotations

import uuid

import pytest
from membership_support import PRICE, MembershipWorld, bangkok_instant

from microdrama.contracts.enums import CatalogPublicState
from microdrama.contracts.errors import Conflict, PolicyDenied
from microdrama.memberships.catalog import FreeDateOwnerDecision


@pytest.fixture
def episode(world: MembershipWorld):
    season = world.season()
    episode_id = world.episode(season, number=2)
    return season, episode_id


class TestNotReleased:
    def test_initial_version_is_not_released_and_cannot_be_reset(self, world, episode):
        season, episode_id = episode
        entry = world.catalog.record_not_released(
            season_id=season, episode_id=episode_id, episode_number=2
        )
        assert entry.public_state is CatalogPublicState.NOT_RELEASED
        assert entry.catalog_version == 1
        with pytest.raises(Conflict):
            world.catalog.record_not_released(
                season_id=season, episode_id=episode_id, episode_number=2
            )


class TestEarlyAccessTruthfulness:
    def test_early_access_needs_a_real_gate2_approval_for_the_episode(self, world, episode):
        season, episode_id = episode
        # No approval event at all -> refused (unfinished/unapproved cannot be sold).
        with pytest.raises(PolicyDenied, match="not finished-and-approved|approval event"):
            world.catalog.publish_early_access(
                season_id=season,
                episode_id=episode_id,
                episode_number=2,
                provider=world.services.adapter,
                media_path=world.tmp / "media.mp4",
                approval_event_id=uuid.uuid4(),
                price=PRICE,
                free_release=bangkok_instant(31),
            )
        # A Gate 1 (season) approval is NOT a Gate 2 approval for this episode.
        gate1 = world.row(
            "SELECT id FROM approval_events WHERE gate_type = 'SEASON_CONCEPT' LIMIT 1"
        )
        with pytest.raises(PolicyDenied):
            world.open_early_access(season, episode_id, approval_event_id=gate1["id"])
        assert world.catalog.current_entry(episode_id) is None

    def test_early_access_records_provider_post_price_and_free_date(self, world, episode):
        season, episode_id = episode
        entry = world.open_early_access(season, episode_id)
        assert entry.public_state is CatalogPublicState.EARLY_ACCESS_MEMBERS
        assert entry.media_finished_and_approved is True
        assert entry.member_price == PRICE
        assert entry.free_release == bangkok_instant(31)
        assert entry.member_post_id and ".invalid" in entry.member_url
        row = world.row(
            "SELECT * FROM membership_catalog WHERE episode_id = %s AND current",
            (episode_id,),
        )
        assert row["catalog_version"] == 1
        assert row["member_price_micro_usd"] == PRICE.amount_micro_usd
        assert row["free_release_utc"] == entry.free_release.utc_instant

    def test_zero_price_is_not_a_truthful_recurring_price(self, world, episode):
        season, episode_id = episode
        with pytest.raises(PolicyDenied, match="truthful recurring price"):
            world.open_early_access(
                season, episode_id, price=PRICE.model_copy(update={"amount_micro_usd": 0})
            )

    def test_identical_reopen_is_an_idempotent_replay(self, world, episode):
        season, episode_id = episode
        approval = world.gate2_approval(episode_id)
        first = world.open_early_access(season, episode_id, approval_event_id=approval)
        again = world.open_early_access(season, episode_id, approval_event_id=approval)
        assert again.entry_id == first.entry_id
        assert (
            len(world.rows("SELECT * FROM membership_catalog WHERE episode_id = %s", (episode_id,)))
            == 1
        )

    def test_cannot_return_to_not_released_after_early_access(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id)
        with pytest.raises(Conflict):
            world.catalog.record_not_released(
                season_id=season, episode_id=episode_id, episode_number=2
            )


class TestFreeDateImmutability:
    def test_announced_free_date_cannot_silently_move(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        with pytest.raises(PolicyDenied, match="cannot silently move"):
            world.open_early_access(season, episode_id, free_release=bangkok_instant(30))
        # The current row is untouched: the original promise still stands.
        current = world.catalog.current_entry(episode_id)
        assert current.free_release == bangkok_instant(31)
        assert current.catalog_version == 1

    def test_owner_acknowledged_move_is_recorded_as_a_visible_event(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        entry = world.open_early_access(
            season,
            episode_id,
            free_release=bangkok_instant(30, hour=20),
            owner_decision=FreeDateOwnerDecision(reason="operator moved the premiere"),
        )
        assert entry.free_release == bangkok_instant(30, hour=20)
        events = world.rows(
            "SELECT * FROM domain_events WHERE aggregate_id = %s "
            "AND event_type = 'membership.free_date_changed'",
            (episode_id,),
        )
        assert len(events) == 1
        assert "operator moved the premiere" in events[0]["payload"]["reason"]

    def test_the_announced_date_survives_dst_and_expired_windows(self, world, episode):
        season, episode_id = episode
        approval = world.gate2_approval(episode_id)
        # Announce in Bangkok (UTC+7, no DST) and then move the clock far past it.
        world.open_early_access(
            season, episode_id, free_release=bangkok_instant(31), approval_event_id=approval
        )
        world.clock.advance(seconds=45 * 24 * 3600)
        # A re-open attempt with the SAME frozen instant is not a move: the expired
        # window cannot alter the announced date.
        entry = world.open_early_access(
            season, episode_id, free_release=bangkok_instant(31), approval_event_id=approval
        )
        assert entry.free_release == bangkok_instant(31)


class TestPublicFree:
    def test_public_free_requires_a_published_verified_post_url(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id)
        with pytest.raises(PolicyDenied, match="PUBLISHED_VERIFIED"):
            world.catalog.mark_public_free(
                episode_id=episode_id, public_url="https://watch.fake.invalid/not-verified"
            )
        # An unlisted/unverified link never becomes the free CTA.
        assert world.catalog.current_entry(episode_id).public_state is (
            CatalogPublicState.EARLY_ACCESS_MEMBERS
        )

    def test_public_free_preserves_the_announced_date(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(29))
        world.clock.advance(seconds=4 * 24 * 3600)  # at/after the announced date
        url = world.published_post_url(episode_id)
        entry = world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        assert entry.public_state is CatalogPublicState.PUBLIC_FREE
        assert entry.public_url == url
        assert entry.free_release == bangkok_instant(29)  # the ORIGINAL instant

    def test_going_free_before_the_announced_date_needs_the_owner(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(31))
        url = world.published_post_url(episode_id)
        with pytest.raises(PolicyDenied, match="cannot silently move"):
            world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        entry = world.catalog.mark_public_free(
            episode_id=episode_id,
            public_url=url,
            owner_decision=FreeDateOwnerDecision(reason="operator released early"),
        )
        assert entry.free_release.utc_instant <= world.clock.now()

    def test_free_content_cannot_return_to_paid_early_access(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        world.clock.advance(seconds=4 * 24 * 3600)
        url = world.published_post_url(episode_id)
        world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        with pytest.raises(PolicyDenied, match="not truthful|already"):
            world.open_early_access(season, episode_id)

    def test_marking_public_free_is_idempotent_for_the_same_url(self, world, episode):
        season, episode_id = episode
        world.catalog.record_not_released(season_id=season, episode_id=episode_id, episode_number=2)
        url = world.published_post_url(episode_id)
        first = world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        again = world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        assert again.entry_id == first.entry_id


class TestWithdrawal:
    def test_withdrawal_records_reason_and_stops_the_offer(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id)
        entry = world.catalog.withdraw(episode_id=episode_id, reason="quality repair")
        assert entry.public_state is CatalogPublicState.WITHDRAWN
        events = world.rows(
            "SELECT * FROM domain_events WHERE aggregate_id = %s "
            "AND event_type = 'membership.withdrawn'",
            (episode_id,),
        )
        assert events and events[0]["payload"]["reason"] == "quality repair"
        assert world.catalog.withdraw(episode_id=episode_id, reason="again").entry_id == (
            entry.entry_id
        )

    def test_withdrawn_episode_cannot_be_marked_public_without_a_verified_url(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id)
        world.catalog.withdraw(episode_id=episode_id, reason="repair")
        with pytest.raises(PolicyDenied):
            world.catalog.mark_public_free(
                episode_id=episode_id, public_url="https://watch.fake.invalid/none"
            )


class TestVersionChain:
    def test_transitions_create_new_versions_with_one_current(self, world, episode):
        season, episode_id = episode
        world.catalog.record_not_released(season_id=season, episode_id=episode_id, episode_number=2)
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        world.clock.advance(seconds=4 * 24 * 3600)
        url = world.published_post_url(episode_id)
        entry = world.catalog.mark_public_free(episode_id=episode_id, public_url=url)
        rows = world.rows(
            "SELECT catalog_version, public_state, current FROM membership_catalog "
            "WHERE episode_id = %s ORDER BY catalog_version",
            (episode_id,),
        )
        assert [r["catalog_version"] for r in rows] == [1, 2, 3]
        assert [r["current"] for r in rows] == [False, False, True]
        assert entry.catalog_version == 3

    def test_facts_on_a_missing_entry_stay_not_released(self, world, episode):
        _, episode_id = episode
        facts = world.catalog.facts(episode_id)
        assert facts.state is CatalogPublicState.NOT_RELEASED
        assert facts.public_url is None and facts.member_url is None

    def test_facts_flag_a_passed_free_date_for_delayed_release(self, world, episode):
        season, episode_id = episode
        world.open_early_access(season, episode_id, free_release=bangkok_instant(28))
        assert world.catalog.facts(episode_id).free_release_passed is False
        world.clock.advance(seconds=3 * 24 * 3600)
        assert world.catalog.facts(episode_id).free_release_passed is True

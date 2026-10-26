"""Effective cost: failures retained, committed counted, minutes from reality (T027)."""

from __future__ import annotations

from microdrama.analytics import effective_cost
from microdrama.contracts.enums import BudgetCategory


class TestSeasonCost:
    def test_variable_spend_counts_every_episode_including_failures(self, world):
        season = world.season()
        ok, _post = world.published_episode(season, number=2)
        world.charge(ok, 400_000)
        failed = world.failed_episode(
            season, number=3, outcome="FAILED_QA", spend_micro_usd=250_000
        )
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 650_000  # the failed 250k is retained
        by_episode = {spend.episode_number: spend for spend in cost.per_episode}
        assert by_episode[2].spend_micro_usd == 400_000
        assert by_episode[3].spend_micro_usd == 250_000
        assert failed  # readability: the failed episode exists in the season

    def test_research_account_is_fixed_and_reported_separately(self, world):
        season = world.season()
        with world.db.transaction() as tx:
            world.budget.open_research_account(tx, season_id=season, envelope_micro_usd=1_000_000)
        ok, _post = world.published_episode(season, number=2)
        world.charge(ok, 100_000)
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 100_000
        assert cost.fixed_costs_reported_separately is True
        # research spend rides along for the report but never enters variable cost
        assert cost.fixed_research_micro_usd == 0  # nothing spent from it yet

    def test_service_recorded_overrun_is_a_subset_of_spend_never_added(self, world):
        season = world.season()
        ok, _post = world.published_episode(season, number=2)
        # A REAL overrun through the budget service: an unreserved settlement above
        # the $10 cap settles in full and records the above-cap portion (10.5M
        # settled, 500k overrun). The overrun is already inside the committed
        # counters — adding it again would report $11 for $10.50 of spend.
        result = world.charge_result(ok, 10_500_000)
        assert result.overrun_recorded_micro_usd == 500_000
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 10_500_000
        assert cost.overrun_micro_usd == 500_000
        by_episode = {spend.episode_number: spend for spend in cost.per_episode}
        assert by_episode[2].spend_micro_usd == 10_500_000
        assert by_episode[2].overrun_micro_usd == 500_000
        assert by_episode[2].overrun is True


class TestEffectiveCost:
    def test_no_successes_is_undividable_not_zero(self, world):
        per_episode, per_minute = effective_cost(
            total_variable_micro_usd=500_000, successful_episodes=0, published_minutes_ms=0
        )
        assert per_episode is None
        assert per_minute is None

    def test_division_is_total_over_successes_and_minutes(self, world):
        per_episode, per_minute = effective_cost(
            total_variable_micro_usd=1_000_000,
            successful_episodes=4,
            published_minutes_ms=10 * 60_000,
        )
        assert per_episode == 250_000
        assert per_minute == 100_000

    def test_partial_published_minutes_are_not_truncated(self, world):
        # 3.5 published minutes is 210_000 ms: the exact ratio is ~285_714.28
        # micro-USD/min and floor is the single final rounding rule — the old
        # whole-minute truncation reported 333_333 from the same spend.
        _per_episode, per_minute = effective_cost(
            total_variable_micro_usd=1_000_000,
            successful_episodes=1,
            published_minutes_ms=210_000,
        )
        assert per_minute == 285_714


class TestPublishedMinutes:
    def test_minutes_read_from_the_published_master(self, world):
        season = world.season()
        episode, post = world.published_episode(season, number=2, duration_ms=600_000)
        from microdrama.analytics import published_minutes_ms

        with world.db.transaction(readonly=True) as tx:
            total, unmeasured = published_minutes_ms(tx, (episode,))
        assert total == 600_000
        assert unmeasured == ()
        assert post["slot_kind"] == "FULL_EPISODE"

    def test_episode_without_published_post_is_unmeasured(self, world):
        season = world.season()
        episode = world.episode_with_account(season, number=2)
        from microdrama.analytics import published_minutes_ms

        with world.db.transaction(readonly=True) as tx:
            total, unmeasured = published_minutes_ms(tx, (episode,))
        assert total == 0
        assert episode in unmeasured  # reported, never assumed


class TestSpendCategories:
    def test_metered_management_spend_is_counted_where_it_happened(self, world):
        season = world.season()
        ok, _post = world.published_episode(season, number=2)
        world.charge(ok, 30_000, category=BudgetCategory.METERED_MANAGEMENT)
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 30_000


class TestResearchAttribution:
    """F06: allocated research rides inside variable cost; the residue stays fixed."""

    def test_two_episode_accounts_reconcile_exactly_to_provider_spend(self, world):
        season = world.season()
        with world.db.transaction() as tx:
            world.budget.open_research_account(tx, season_id=season, envelope_micro_usd=1_000_000)
        world.research_charge(season, 300_000, suffix="accepted")
        ok1, _post1 = world.published_episode(season, number=2)
        ok2, _post2 = world.published_episode(season, number=3)
        # The story lane's claim-time attribution (same call, same basis rule).
        from microdrama.story.service import StoryService

        with world.db.transaction() as tx:
            allocations = world.budget.allocate_research_cost(
                tx=tx,
                season_id=season,
                episode_ids=[ok1, ok2],
                basis=StoryService.RESEARCH_ALLOCATION_BASIS,
            )
        assert sum(a.amount_micro_usd for a in allocations) == 300_000
        cost = world.analytics.season_cost(season)
        assert cost.attributed_research_micro_usd == 300_000
        assert cost.variable_micro_usd == 300_000  # both shares live in episodes
        assert cost.fixed_research_micro_usd == 0  # nothing left unattributed
        # A rejected proposal's cost (no episode ever claims it) and a late bill
        # that arrives after allocation stay project-level fixed residue.
        world.research_charge(season, 50_000, suffix="rejected")
        cost = world.analytics.season_cost(season)
        assert cost.attributed_research_micro_usd == 300_000
        assert cost.fixed_research_micro_usd == 50_000
        assert cost.variable_micro_usd + cost.fixed_research_micro_usd == 350_000

    def test_rejected_research_without_episodes_stays_fixed(self, world):
        season = world.season()
        with world.db.transaction() as tx:
            world.budget.open_research_account(tx, season_id=season, envelope_micro_usd=1_000_000)
        world.research_charge(season, 75_000, suffix="rejected-proposal")
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 0
        assert cost.attributed_research_micro_usd == 0
        assert cost.fixed_research_micro_usd == 75_000

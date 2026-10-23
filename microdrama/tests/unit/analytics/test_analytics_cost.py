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

    def test_recorded_overrun_is_spend_not_hidden(self, world):
        season = world.season()
        ok, _post = world.published_episode(season, number=2)
        world.charge(ok, 100_000)
        # An overrun is recorded by the budget service on real overspend (and blocks
        # paid dispatch); prove the read path counts it by writing the same pair of
        # columns the service would write.
        with world.db.transaction() as tx:
            tx.execute(
                "UPDATE budget_accounts SET overrun_micro_usd = 50_000, paid_dispatch_blocked = true "
                "WHERE episode_id = %s",
                (ok,),
            )
        cost = world.analytics.season_cost(season)
        assert cost.variable_micro_usd == 150_000
        assert cost.overrun_micro_usd == 50_000


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

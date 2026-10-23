"""Rolling ten-episode qualification: streaks, resets, 7-day windows (AT-12)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from analytics_support import AnalyticsWorld

from microdrama.analytics import MANAGEMENT_WINDOW_DAYS, REQUIRED_CONSECUTIVE
from microdrama.contracts.enums import QualificationStatus
from microdrama.contracts.errors import Conflict

# Evaluations happen well after every window so management is decidable unless a
# test deliberately probes inside the window.
LATE = timedelta(days=30)


def _clean_published(world: AnalyticsWorld, season, number: int, *, spend: int = 100_000):
    episode, _post = world.published_episode(season, number=number)
    if spend:
        world.charge(episode, spend)
    return episode


class TestTenRequired:
    def test_nine_clean_episodes_are_not_qualified(self, world):
        season = world.season()
        for number in range(2, 11):  # nine episodes, all clean
            _clean_published(world, season, number)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 9
        # Clean so far but fewer than ten: still pending, never qualified. The
        # management track rolls over the last TEN windows too: nine clean
        # closed windows are not yet a management qualification.
        assert result.production_status is QualificationStatus.PENDING
        assert result.management_status is QualificationStatus.PENDING
        assert result.required_consecutive == REQUIRED_CONSECUTIVE == 10

    def test_ten_clean_episodes_qualify(self, world):
        season = world.season()
        for number in range(2, 12):  # ten episodes
            _clean_published(world, season, number)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 10
        assert result.production_status is QualificationStatus.QUALIFIED
        assert result.management_status is QualificationStatus.QUALIFIED

    def test_one_success_is_never_enough(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 1
        assert result.production_status is not QualificationStatus.QUALIFIED


class TestStreakResets:
    def test_failed_episode_resets_the_streak(self, world):
        season = world.season()
        for number in (2, 3, 4):
            _clean_published(world, season, number)
        world.failed_episode(season, number=5, outcome="REJECTED", spend_micro_usd=50_000)
        for number in (6, 7):
            _clean_published(world, season, number)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 2  # only 6 and 7 after the reset
        assert result.production_status is QualificationStatus.NOT_QUALIFIED
        assert any("outcome=REJECTED" in reason for reason in result.streak_resets)

    def test_manual_fixed_published_episode_resets_the_streak(self, world):
        season = world.season()
        for number in (2, 3):
            _clean_published(world, season, number)
        fixed = _clean_published(world, season, 4)
        world.intervention(fixed, season, days_after_publication=1.0)  # human rescued it
        _clean_published(world, season, 5)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 1  # only episode 5
        episode_4 = next(e for e in result.episodes if e.episode_number == 4)
        assert episode_4.production_qualifies is False
        assert episode_4.manual_interventions == 1
        assert any("manual_interventions=1" in r for r in result.streak_resets)

    def test_pending_episode_stops_the_trailing_streak_without_resetting(self, world):
        season = world.season()
        for number in (2, 3):
            _clean_published(world, season, number)
        world.episode_with_account(season, number=4)  # in flight, not published, no outcome
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.consecutive_qualifying_production == 0  # trailing run stops at pending
        episode_4 = next(e for e in result.episodes if e.episode_number == 4)
        assert episode_4.production_qualifies is None
        assert result.streak_resets == []  # pending is an open end, not a reset
        assert result.production_status is QualificationStatus.PENDING


class TestManagementWindows:
    def test_window_pending_before_day_seven(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        now = world.clock.now() + timedelta(days=3)
        result = world.analytics.evaluate_qualification(season, now=now)
        episode = result.episodes[0]
        assert episode.management_window_status is QualificationStatus.PENDING
        assert episode.management_window_ends_at is not None
        verified = world.row(
            "SELECT min(verified_at) AS v FROM platform_posts WHERE episode_id = %s",
            (episode.episode_id,),
        )["v"]
        assert episode.management_window_ends_at == verified + timedelta(
            days=MANAGEMENT_WINDOW_DAYS
        )
        assert result.management_status is QualificationStatus.PENDING

    def test_window_clean_after_seven_days(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        now = world.clock.now() + timedelta(days=MANAGEMENT_WINDOW_DAYS, hours=1)
        result = world.analytics.evaluate_qualification(season, now=now)
        assert result.episodes[0].management_window_status is QualificationStatus.QUALIFIED

    def test_intervention_inside_window_fails_management(self, world):
        season = world.season()
        episode = _clean_published(world, season, 2)
        world.intervention(episode, season, days_after_publication=2.0)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.episodes[0].management_window_status is QualificationStatus.NOT_QUALIFIED
        assert result.management_status is QualificationStatus.NOT_QUALIFIED

    def test_intervention_after_window_close_does_not_fail_management(self, world):
        season = world.season()
        episode = _clean_published(world, season, 2)
        # but note: any intervention still breaks production qualification; this
        # test pins the MANAGEMENT window decision independently by dating the
        # intervention outside the window while checking window status only.
        world.intervention(episode, season, days_after_publication=9.0)
        result = world.analytics.evaluate_qualification(
            season, now=world.clock.now() + timedelta(days=10)
        )
        assert result.episodes[0].management_window_status is QualificationStatus.QUALIFIED

    def test_failed_before_publication_never_opens_a_window(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        world.failed_episode(season, number=3, outcome="FAILED_INFRA", spend_micro_usd=10_000)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        episode_3 = next(e for e in result.episodes if e.episode_number == 3)
        assert episode_3.management_window_status is QualificationStatus.NOT_QUALIFIED
        assert episode_3.management_window_ends_at is None


class TestCostInVerdicts:
    def test_failed_spend_is_retained_and_attributed(self, world):
        season = world.season()
        _clean_published(world, season, 2, spend=400_000)
        world.failed_episode(season, number=3, outcome="FAILED_QA", spend_micro_usd=250_000)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.total_variable_spend_micro_usd == 650_000
        assert result.successful_episodes == 1
        episode_2, episode_3 = result.episodes
        assert episode_2.failed_attempt_cost_micro_usd == 0
        assert episode_3.failed_attempt_cost_micro_usd == 250_000
        assert result.effective_cost_per_successful_episode_micro_usd == 650_000

    def test_per_minute_cost_uses_published_duration(self, world):
        season = world.season()
        _clean_published(world, season, 2, spend=600_000)
        # master duration 600_000 ms = 10 minutes (published_episode default)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.episodes[0].published_minutes_ms == 600_000
        assert result.effective_cost_per_published_minute_micro_usd == 60_000

    def test_human_review_minutes_stay_null_when_unmeasured(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert result.episodes[0].human_review_minutes is None


class TestRunPersistence:
    def test_run_row_is_persisted_append_only(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        first = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        row = world.row("SELECT * FROM qualification_runs WHERE id = %s", (first.run_id,))
        assert row["production_status"] == first.production_status.value
        assert row["consecutive"] == first.consecutive_qualifying_production
        with pytest.raises(Conflict):  # the append-only trigger forbids mutation
            with world.db.transaction() as tx:
                tx.execute(
                    "UPDATE qualification_runs SET consecutive = 99 WHERE id = %s",
                    (first.run_id,),
                )

    def test_second_evaluation_is_a_new_run(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        first = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        second = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        assert first.run_id != second.run_id
        assert world.row("SELECT count(*) AS n FROM qualification_runs")["n"] == 2

    def test_database_refuses_qualified_below_ten(self, world):
        season = world.season()
        _clean_published(world, season, 2)
        result = world.analytics.evaluate_qualification(season, now=world.clock.now() + LATE)
        # The service never claims QUALIFIED below ten; the DB CHECK is the backstop.
        assert not (
            result.production_status is QualificationStatus.QUALIFIED
            and result.consecutive_qualifying_production < 10
        )
        with pytest.raises(Conflict):  # CHECK (QUALIFIED requires ten consecutive)
            with world.db.transaction() as tx:
                tx.execute(
                    "INSERT INTO qualification_runs (id, season_id, evaluated_at, "
                    "production_status, management_status, consecutive, body) VALUES "
                    "(%s, %s, %s, 'QUALIFIED', 'PENDING', 3, '{}'::jsonb)",
                    (__import__("uuid").uuid4(), season, world.clock.now()),
                )

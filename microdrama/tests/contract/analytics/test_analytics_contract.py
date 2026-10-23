"""Contract tests for the analytics lane (T027): the frozen surfaces it consumes.

Pins, against the frozen 1.6.0 contracts and the real migrated database:
- ``MetricSnapshot``/``MetricValue`` validation (missing value is None, never
  coerced; strict integers; windows are exactly H24/H72/D7);
- ``QualificationResult``/``EpisodeQualification`` validation (ten is the only
  required_consecutive, trailing-streak definition, episode order, run-level
  cost fields and the always-separate fixed costs);
- the ``performance_snapshots`` table contract (one row per post+window,
  append-only, window/traffic CHECKs) and the ``qualification_runs`` contract
  (QUALIFIED requires ten consecutive, append-only);
- the frozen job-spec routing: both analytics job types live on the community
  queue, unpaid, with their pinned input models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from microdrama.contracts.catalog import EpisodeQualification, MetricSnapshot, QualificationResult
from microdrama.contracts.enums import (
    Platform,
    Provenance,
    QualificationStatus,
    QueueName,
    SnapshotWindow,
    TrafficKind,
)
from microdrama.contracts.errors import Conflict, DuplicateSemanticKey
from microdrama.contracts.jobs import JOB_SPECS_BY_TYPE, MetricWindowInput
from microdrama.persistence.db import insert_row, jsonb

FAKE = Provenance.FAKE_SYNTHETIC
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def snapshot(**updates: object) -> MetricSnapshot:
    fields: dict[str, object] = {
        "snapshot_id": uuid.uuid4(),
        "platform": Platform.YOUTUBE,
        "account_ref": "acct:youtube-main",
        "platform_post_id": uuid.uuid4(),
        "external_post_id": "yt-1",
        "episode_id": uuid.uuid4(),
        "window": SnapshotWindow.H24,
        "observed_at": T0 + timedelta(hours=25),
        "definitions_version": "metrics-v1",
        "metrics": {},
        "provenance": FAKE,
    }
    fields.update(updates)
    return MetricSnapshot(**fields)  # type: ignore[arg-type]


def episode_qualification(number: int, *, qualifies: bool | None = True, **updates: object):
    fields: dict[str, object] = {
        "episode_id": uuid.uuid4(),
        "episode_number": number,
        "production_qualifies": qualifies,
        "management_window_status": QualificationStatus.QUALIFIED,
        "variable_cost_micro_usd": 100_000,
    }
    fields.update(updates)
    return EpisodeQualification(**fields)  # type: ignore[arg-type]


def result(**updates: object) -> QualificationResult:
    fields: dict[str, object] = {
        "run_id": uuid.uuid4(),
        "season_id": uuid.uuid4(),
        "evaluated_at": T0,
        "consecutive_qualifying_production": 1,
        "production_status": QualificationStatus.PENDING,
        "management_status": QualificationStatus.PENDING,
        "episodes": [episode_qualification(1)],
        "total_variable_spend_micro_usd": 100_000,
        "successful_episodes": 1,
        "provenance": Provenance.DERIVED_LOCAL,
    }
    fields.update(updates)
    return QualificationResult(**fields)  # type: ignore[arg-type]


# --- MetricSnapshot ------------------------------------------------------------------------


def test_missing_metric_value_is_none_never_coerced() -> None:
    snap = snapshot(metrics={"watch_time": {"value": None, "definition": "wt-def"}})
    assert snap.metrics["watch_time"].value is None
    with pytest.raises(ValidationError):
        snapshot(metrics={"watch_time": {"value": "500", "definition": "wt-def"}})  # strict int


def test_metric_denominator_travels_with_the_value() -> None:
    snap = snapshot(
        metrics={"views": {"value": 500, "definition": "views-def", "denominator": 1_000}}
    )
    assert snap.metrics["views"].denominator == 1_000


def test_windows_are_exactly_the_three_frozen_schedules() -> None:
    assert {w.value for w in SnapshotWindow} == {"H24", "H72", "D7"}
    assert {t.value for t in TrafficKind} == {"ORGANIC", "PAID", "UNKNOWN"}


# --- QualificationResult -------------------------------------------------------------------


def test_ten_is_the_only_required_consecutive() -> None:
    with pytest.raises(ValidationError):
        result(required_consecutive=9)
    with pytest.raises(ValidationError):
        result(required_consecutive=11)
    assert result(required_consecutive=10).required_consecutive == 10


def test_consecutive_must_equal_the_trailing_streak() -> None:
    episodes = [
        episode_qualification(1),
        episode_qualification(2, qualifies=False),
        episode_qualification(3),
    ]
    # trailing streak is 1 (only episode 3); claiming 2 is a contract violation
    with pytest.raises(ValidationError):
        result(episodes=episodes, consecutive_qualifying_production=2)
    built = result(episodes=episodes, consecutive_qualifying_production=1)
    assert built.consecutive_qualifying_production == 1


def test_manual_intervention_breaks_the_trailing_streak_even_when_published() -> None:
    episodes = [
        episode_qualification(1),
        episode_qualification(2, manual_interventions=2),
    ]
    with pytest.raises(ValidationError):
        result(episodes=episodes, consecutive_qualifying_production=2)


def test_episodes_listed_once_each_in_order() -> None:
    with pytest.raises(ValidationError):
        result(
            episodes=[episode_qualification(2), episode_qualification(1)],
            consecutive_qualifying_production=0,
        )


def test_fixed_costs_are_always_reported_separately() -> None:
    assert result().fixed_costs_reported_separately is True


def test_human_review_minutes_may_stay_unknown() -> None:
    assert episode_qualification(1).human_review_minutes is None


# --- table contracts ------------------------------------------------------------------------


def test_performance_snapshots_one_row_per_post_window_and_append_only(
    db, tmp_path, offline_settings
) -> None:
    from analytics_support import AnalyticsWorld

    world = AnalyticsWorld(db, tmp_path, offline_settings)
    season = world.season()
    _episode, post = world.published_episode(season, number=2)
    base = {
        "platform": post["platform"],
        "account_ref": post["account_ref"],
        "external_post_id": post["external_id"],
        "episode_id": post["episode_id"],
        "snapshot_window": "H24",
        "observed_at": post["verified_at"],
        "definitions_version": "metrics-v1",
        "metrics": jsonb({"views": {"value": 5, "definition": "views-def"}}),
        "traffic": "ORGANIC",
        "provenance": "FAKE_SYNTHETIC",
        "body": jsonb({"snapshot_id": str(uuid.uuid4())}),
    }
    with db.transaction() as tx:
        insert_row(
            tx,
            "performance_snapshots",
            {"id": uuid.uuid4(), "platform_post_id": post["id"], **base},
        )
    with pytest.raises(DuplicateSemanticKey):  # UNIQUE (platform_post_id, snapshot_window)
        with db.transaction() as tx:
            insert_row(
                tx,
                "performance_snapshots",
                {"id": uuid.uuid4(), "platform_post_id": post["id"], **base},
            )
    with pytest.raises(Conflict):  # append-only trigger (check_violation)
        with db.transaction() as tx:
            tx.execute(
                "UPDATE performance_snapshots SET traffic = 'PAID' WHERE platform_post_id = %s",
                (post["id"],),
            )
    with pytest.raises(Conflict):  # window CHECK
        with db.transaction() as tx:
            insert_row(
                tx,
                "performance_snapshots",
                {
                    "id": uuid.uuid4(),
                    "platform_post_id": post["id"],
                    **{**base, "snapshot_window": "H48"},
                },
            )


def test_qualification_runs_qualified_requires_ten_and_append_only(db) -> None:
    with db.transaction() as tx:
        from microdrama.testing.seed import seed_season

        season_id = seed_season(tx, state="SEASON_APPROVED")
        insert_row(
            tx,
            "qualification_runs",
            {
                "id": uuid.uuid4(),
                "season_id": season_id,
                "evaluated_at": T0,
                "production_status": "NOT_QUALIFIED",
                "management_status": "PENDING",
                "consecutive": 3,
                "body": jsonb({"run": "contract"}),
            },
        )
    with pytest.raises(Conflict):  # CHECK (QUALIFIED requires ten consecutive)
        with db.transaction() as tx:
            insert_row(
                tx,
                "qualification_runs",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "evaluated_at": T0,
                    "production_status": "QUALIFIED",
                    "management_status": "QUALIFIED",
                    "consecutive": 9,
                    "body": jsonb({"run": "contract"}),
                },
            )
    with pytest.raises(Conflict):  # append-only trigger (check_violation)
        with db.transaction() as tx:
            tx.execute(
                "UPDATE qualification_runs SET consecutive = 10 WHERE season_id = %s",
                (season_id,),
            )


# --- frozen job-spec routing ------------------------------------------------------------------


def test_analytics_job_specs_are_frozen_on_the_community_queue() -> None:
    snap = JOB_SPECS_BY_TYPE["analytics.snapshot"]
    assert snap.queue is QueueName.COMMUNITY
    assert snap.input_model is MetricWindowInput
    assert snap.paid is False
    assert snap.owner_module == "analytics"

    qual = JOB_SPECS_BY_TYPE["analytics.qualification"]
    assert qual.queue is QueueName.COMMUNITY
    assert qual.paid is False
    assert qual.owner_module == "analytics"

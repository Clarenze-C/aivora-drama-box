"""Backpressure tests (real DB): rate limits defer with a retry window.

The fake community provider's RATE_LIMITED scenario returns a DEFERRED,
transient ActionResult with ``retry_after_ms``. The service must record the
deferral with the window, free the unused reservation, refuse early retries and
succeed after the window — with the SAME durable action row throughout.
"""

from __future__ import annotations

import pytest
from community_support import CommunityWorld

from microdrama.contracts.errors import Conflict
from microdrama.testing.fakes.community import RETRY_AFTER_MS, CommunityScenario


def _deferred_row(world: CommunityWorld) -> dict:
    row = world.row(
        "SELECT * FROM management_actions WHERE decision = 'DEFERRED' ORDER BY dedupe_key"
    )
    assert row is not None
    return row


def test_rate_limited_reply_defers_with_retry_after_and_frees_the_reservation(
    rate_limited_world: CommunityWorld,
) -> None:
    world = rate_limited_world
    post = world.published_post()
    report = world.process(post["season_id"], post["episode_id"])

    assert report.executed == 0
    assert report.deferred == 2  # the seeded question and praise replies both deferred
    row = _deferred_row(world)
    assert row["error_code"] == "RATE_LIMITED"
    assert f"retry_after_ms={RETRY_AFTER_MS}" in row["reason"]
    assert row["external_id"] is None
    # The unused reservations were released: nothing is held against the allowance.
    assert world.rows("SELECT * FROM reservations WHERE state = 'ACTIVE'") == []
    allocation, committed, _settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert committed == 0 and allocation == 1_000_000
    assert world.event_row("fake-comment-0001")["status"] == "DEFERRED"


def test_retry_before_the_window_is_refused(rate_limited_world: CommunityWorld) -> None:
    world = rate_limited_world
    post = world.published_post()
    world.process(post["season_id"], post["episode_id"])
    row = _deferred_row(world)

    with pytest.raises(Conflict) as exc:
        world.community.retry_deferred(
            row["dedupe_key"], season_id=post["season_id"], episode_id=post["episode_id"]
        )
    assert "retry window" in exc.value.message


def test_retry_after_the_window_executes_and_settles(rate_limited_world: CommunityWorld) -> None:
    world = rate_limited_world
    post = world.published_post()
    world.process(post["season_id"], post["episode_id"])
    row = _deferred_row(world)
    total = world.row("SELECT count(*) AS c FROM management_actions")["c"]
    world.clock.advance(seconds=RETRY_AFTER_MS // 1000 + 1)
    # The provider recovers: the retry's execute step is scripted HAPPY.
    world.community_provider.queue_scenarios(CommunityScenario.HAPPY)

    retried = world.community.retry_deferred(
        row["dedupe_key"], season_id=post["season_id"], episode_id=post["episode_id"]
    )
    assert retried["decision"] == "EXECUTED"
    assert retried["id"] == row["id"]  # same durable row, updated — not a second action
    assert world.row("SELECT count(*) AS c FROM management_actions")["c"] == total
    # The retry's fresh reservation settled exactly once.
    _allocation, committed, settled = world.metered_counters(post["episode_id"])[
        "METERED_MANAGEMENT"
    ]
    assert committed == settled == 1_000
    # The deferred event completed its ladder: DEFERRED -> ACTIONED.
    assert world.event_row("fake-comment-0001")["status"] == "ACTIONED"


def test_retry_of_an_executed_action_is_refused(rate_limited_world: CommunityWorld) -> None:
    world = rate_limited_world
    post = world.published_post()
    world.process(post["season_id"], post["episode_id"])
    row = _deferred_row(world)
    world.clock.advance(seconds=RETRY_AFTER_MS // 1000 + 1)
    world.community_provider.queue_scenarios(CommunityScenario.HAPPY)
    first = world.community.retry_deferred(
        row["dedupe_key"], season_id=post["season_id"], episode_id=post["episode_id"]
    )
    assert first["decision"] == "EXECUTED"
    with pytest.raises(Conflict):
        world.community.retry_deferred(
            row["dedupe_key"], season_id=post["season_id"], episode_id=post["episode_id"]
        )

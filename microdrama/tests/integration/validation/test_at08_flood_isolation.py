"""AT-08 reproduced independently through the composed worker runtime.

A 250-comment flood cannot starve a due release, cannot reserve protected
production funds, and cannot lose events — every flood job eventually completes
through its own reserved concurrency. Drives the composed world's real
JobService + SharedRateLimiter + WorkerRuntime (T028 semantics), not a re-built
harness.
"""

from __future__ import annotations

import uuid

import pytest

from microdrama.contracts.enums import QueueName
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.jobs import CommunityEventRef, PlatformPostRef
from microdrama.workers import counting_handler

pytestmark = [pytest.mark.db, pytest.mark.slow]

FLOOD = 250


def _enqueue(world, job_type: str, payload, *, counter: list) -> uuid.UUID:
    counter[0] += 1
    with world.db.transaction() as tx:
        result = world.jobs.enqueue(
            tx,
            job_type=job_type,
            semantic_key=f"{job_type}:t030:{counter[0]}:{uuid.uuid4().hex[:8]}",
            payload=payload,
        )
    return result.job_id


def test_flood_cannot_starve_a_due_publication(validation_world) -> None:
    world = validation_world
    counter = [0]
    for _ in range(FLOOD):
        _enqueue(
            world,
            "community.ingest_event",
            CommunityEventRef(community_event_id=uuid.uuid4()),
            counter=counter,
        )
    release_job = _enqueue(
        world,
        "publish.poll_status",
        PlatformPostRef(platform_post_id=uuid.uuid4()),
        counter=counter,
    )

    runtime = world.runtime(
        {
            "community.ingest_event": counting_handler({}, "ingest"),
            "publish.poll_status": counting_handler({}, "poll"),
        }
    )
    first_cycle = runtime.run_cycle()
    actions = {r.job_id: r.action for r in first_cycle.reports}
    assert actions.get(release_job) == "EXECUTED", (
        "the due release must be served in the SAME cycle"
    )
    community_served = sum(1 for r in first_cycle.reports if r.queue is QueueName.COMMUNITY)
    assert community_served <= 2, "the flood queues behind its own reserved slots"

    with world.db.transaction(readonly=True) as tx:
        state = tx.fetchone("SELECT status FROM jobs WHERE id = %s", (release_job,))
    assert state["status"] == "SUCCEEDED"


def test_flood_events_are_never_lost(validation_world) -> None:
    """Under flood, every event job reaches a terminal state within a bounded
    number of cycles (reserved concurrency + limiter defer, never a drop)."""
    world = validation_world
    counter = [0]
    job_ids = [
        _enqueue(
            world,
            "community.ingest_event",
            CommunityEventRef(community_event_id=uuid.uuid4()),
            counter=counter,
        )
        for _ in range(FLOOD)
    ]
    runtime = world.runtime({"community.ingest_event": counting_handler({}, "ingest")})
    for _ in range(500):
        cycle = runtime.run_cycle()
        if len(cycle.idle_queues) == 3:  # all three queues idle: drained
            break
        world.fakes.clock.advance(ms=2_000)
    else:
        pytest.fail("flood jobs did not drain within 500 cycles")
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT status, count(*) AS c FROM jobs GROUP BY status")
    by_status = {row["status"]: row["c"] for row in rows}
    assert by_status.get("SUCCEEDED", 0) >= FLOOD, by_status
    assert len(job_ids) == FLOOD


def test_community_context_cannot_reserve_protected_gpu_funds(validation_world) -> None:
    """From behavior: a COMMUNITY-queue reservation of GPU production money is
    refused before anything is held — the budget service's own ownership rule."""
    from datetime import timedelta

    from microdrama.contracts.cost import (
        BudgetReservationRequest,
        ExposureCeilings,
    )
    from microdrama.contracts.enums import (
        BudgetCategory,
        BudgetScopeKind,
        PriceUnit,
    )
    from microdrama.contracts.season import CostPolicy
    from microdrama.testing.fakes.common import fake_price_quote
    from microdrama.testing.seed import seed_episode, seed_season

    world = validation_world
    with world.db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        account_id = world.budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    request = BudgetReservationRequest(
        request_id=uuid.uuid5(uuid.NAMESPACE_URL, "t030:community-gpu"),
        semantic_key="t030.community-gpu",
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.COMMUNITY,  # the community lane asking for render money
        job_id=None,
        provider="fake-runpod",
        operation_kind="gpu.render_shot",
        price=fake_price_quote(PriceUnit.GPU_SECOND),
        ceilings=ExposureCeilings(timeout_ms=1_000, max_units=1),
        worst_case_micro_usd=700_000,
        is_shutdown_or_cleanup=False,
        expires_at=world.fakes.clock.now() + timedelta(hours=1),
    )
    with pytest.raises(PolicyDenied):
        world.budget.reserve(request)
    with world.db.transaction(readonly=True) as tx:
        held = tx.fetchval(
            "SELECT reserved_outstanding_micro_usd FROM budget_accounts WHERE id = %s",
            (account_id,),
        )
    assert held == 0, "a refused community reservation must hold nothing"

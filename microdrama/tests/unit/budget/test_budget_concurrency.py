"""AT-01 under genuine concurrency: many threads race the same account on a real PostgreSQL.

Each race starts all threads behind a barrier so the calls overlap in the database. The account
row lock is what serializes them; these tests prove the result is exactly the sequential one.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

import pytest
from budget_support import (
    CPU,
    GPU,
    METERED,
    QA,
    REFERENCES,
    RESEARCH,
    T0,
    World,
    fake_receipt,
    request_for,
)

from microdrama.contracts.enums import QueueName, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted, Conflict
from microdrama.persistence import Database

pytestmark = [pytest.mark.db, pytest.mark.slow]

THREADS = 16


def race(calls: list[Callable[[], Any]]) -> list[tuple[str, Any]]:
    """Run every call in its own thread, all released together. Returns ("ok"|"err", value)."""
    barrier = threading.Barrier(len(calls))
    outcomes: list[tuple[str, Any]] = [("missing", None)] * len(calls)

    def run(index: int, call: Callable[[], Any]) -> None:
        barrier.wait(timeout=60)
        try:
            outcomes[index] = ("ok", call())
        except BaseException as exc:  # recorded and asserted by the caller
            outcomes[index] = ("err", exc)

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads), "a racing call hung"
    return outcomes


def test_at01_sixteen_racing_gpu_reservations_fit_exactly_the_allowance(
    world: World, check_consistent, db: Database
) -> None:
    """AT-01: 16 x 700,000 against 2,500,000 GPU allocation plus 2,250,000 spill from recovery.

    Only floor(4,750,000 / 700,000) = 6 can fit. Repeated over three fresh episodes so that more
    interleavings are exercised in one run.
    """
    fits = (2_500_000 + (2_500_000 - 250_000)) // 700_000
    assert fits == 6
    for round_no in range(3):
        ep = world.episode()
        requests = [
            request_for(key=f"race.gpu.{round_no}.{i}", episode_id=ep.episode_id, worst=700_000)
            for i in range(THREADS)
        ]
        outcomes = race([partial(world.service.reserve, r) for r in requests])
        successes = [value for kind, value in outcomes if kind == "ok"]
        failures = [value for kind, value in outcomes if kind == "err"]
        assert len(successes) == fits, f"round {round_no}: {len(successes)} succeeded"
        assert len(failures) == THREADS - fits
        assert all(isinstance(exc, BudgetExhausted) for exc in failures), failures
        assert sum(r.reserved_micro_usd for r in successes) == fits * 700_000

        counters = world.counters(ep.account_id)
        assert counters["reserved"] == fits * 700_000 == counters["committed"]
        assert counters["committed"] + counters["shutdown"] <= counters["cap"]
        assert (
            world.count(
                "SELECT count(*) FROM reservations WHERE account_id = %s AND state = 'ACTIVE'",
                (ep.account_id,),
            )
            == fits
        )
        check_consistent(ep.account_id)

        # The boundary is exact: the policy oracle says 550,000 still fits and 550,001 does not.
        assert world.production_gpu_headroom(ep.account_id) == 550_000
        with pytest.raises(BudgetExhausted):
            world.service.reserve(
                request_for(
                    key=f"race.gpu.{round_no}.over", episode_id=ep.episode_id, worst=550_001
                )
            )
        world.service.reserve(
            request_for(key=f"race.gpu.{round_no}.fits", episode_id=ep.episode_id, worst=550_000)
        )
        assert world.production_gpu_headroom(ep.account_id) == 0
        check_consistent(ep.account_id)


def test_identical_semantic_key_from_many_threads_yields_one_reservation(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    request = request_for(key="race.duplicate", episode_id=ep.episode_id, worst=700_000)
    outcomes = race([partial(world.service.reserve, request) for _ in range(THREADS)])
    assert all(kind == "ok" for kind, _ in outcomes), outcomes
    reservations = [value for _, value in outcomes]
    assert len({r.id for r in reservations}) == 1
    assert sum(1 for r in reservations if not r.replayed) == 1
    assert sum(1 for r in reservations if r.replayed) == THREADS - 1
    assert world.counters(ep.account_id)["committed"] == 700_000
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 1
    )
    check_consistent(ep.account_id)


def test_mixed_category_storm_near_the_cap_never_overspends(world: World, check_consistent) -> None:
    ep = world.episode()
    spec = (
        [(f"mix.gpu.{i}", GPU, QueueName.PRODUCTION, 600_000) for i in range(8)]
        + [(f"mix.ref.{i}", REFERENCES, QueueName.PRODUCTION, 400_000) for i in range(4)]
        + [(f"mix.qa.{i}", QA, QueueName.PRODUCTION, 300_000) for i in range(4)]
        + [(f"mix.res.{i}", RESEARCH, QueueName.PRODUCTION, 250_000) for i in range(4)]
        + [(f"mix.cpu.{i}", CPU, QueueName.PUBLICATION, 200_000) for i in range(3)]
        + [(f"mix.met.{i}", METERED, QueueName.COMMUNITY, 500_000) for i in range(3)]
    )
    requests = [
        request_for(key=key, episode_id=ep.episode_id, worst=worst, category=category, queue=queue)
        for key, category, queue, worst in spec
    ]
    outcomes = race([partial(world.service.reserve, r) for r in requests])
    failed = [(r, v) for r, (kind, v) in zip(requests, outcomes, strict=True) if kind == "err"]
    succeeded = [v for kind, v in outcomes if kind == "ok"]
    assert all(isinstance(exc, BudgetExhausted) for _, exc in failed), [e for _, e in failed]
    assert succeeded and failed, "the storm must both fit and refuse to be meaningful"

    counters = world.counters(ep.account_id)
    assert counters["committed"] + counters["shutdown"] <= counters["cap"]
    assert counters["committed"] == sum(r.reserved_micro_usd for r in succeeded)
    check_consistent(ep.account_id)
    # Nothing is ever released in this storm, so every refused request must still be refused.
    for request, _ in failed:
        with pytest.raises(BudgetExhausted):
            world.service.reserve(request)
    check_consistent(ep.account_id)


def test_settlements_racing_new_reservations_keep_every_total_exact(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    episode = ep.episode_id
    gpu_pending = [
        svc.reserve(request_for(key=f"settle.gpu.{i}", episode_id=episode, worst=500_000))
        for i in range(4)
    ]
    for i in range(4):
        svc.reserve(
            request_for(key=f"settle.res.{i}", episode_id=episode, worst=250_000, category=RESEARCH)
        )

    calls: list[Callable[[], Any]] = []
    for i, reservation in enumerate(gpu_pending):
        receipt = fake_receipt(
            provider_receipt_id=f"settle.gpu.{i}.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=400_000,
            reservation=reservation,
            episode_id=episode,
            observed_at=T0,
        )
        calls.append(partial(svc.record_usage, receipt))
    for i in range(4):
        calls.append(
            partial(
                svc.reserve,
                request_for(key=f"settle.new.gpu.{i}", episode_id=episode, worst=600_000),
            )
        )
    for i in range(4):
        calls.append(
            partial(
                svc.reserve,
                request_for(
                    key=f"settle.new.qa.{i}", episode_id=episode, worst=250_000, category=QA
                ),
            )
        )
    outcomes = race(calls)

    settlements = outcomes[:4]
    assert all(kind == "ok" for kind, _ in settlements), settlements
    new_reservations = outcomes[4:]
    assert all(kind == "ok" or isinstance(v, BudgetExhausted) for kind, v in new_reservations)

    counters = world.counters(ep.account_id)
    # Settlements are final: exactly 4 x 400,000 is settled, and nothing was double counted.
    assert counters["settled"] == 1_600_000
    # Four research reservations (1,000,000) stay open; the new GPU/QA reservations add to them.
    open_new = sum(v.reserved_micro_usd for k, v in new_reservations if k == "ok")
    assert counters["reserved"] == 1_000_000 + open_new
    assert counters["committed"] + counters["shutdown"] <= counters["cap"]
    check_consistent(ep.account_id)
    # The GPU room left after the race is exactly what the policy oracle reports.
    headroom = world.production_gpu_headroom(ep.account_id)
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="settle.edge.over", episode_id=episode, worst=headroom + 1))
    if headroom:
        svc.reserve(request_for(key="settle.edge.fits", episode_id=episode, worst=headroom))
    check_consistent(ep.account_id)


def test_warm_pod_interval_racing_across_episodes_is_counted_once(
    world: World, check_consistent, db: Database
) -> None:
    """Two episodes (two account locks) report the same paid interval of one pod at once."""
    first = world.episode()
    second = world.episode()
    res_a = world.service.reserve(
        request_for(key="pod.a.res", episode_id=first.episode_id, worst=100_000)
    )
    res_b = world.service.reserve(
        request_for(key="pod.b.res", episode_id=second.episode_id, worst=100_000)
    )
    lease_a = world.lease(
        episode=first, reservation=res_a, pod_id="pod-shared", lease_state="RELEASED"
    )
    lease_b = world.lease(episode=second, reservation=res_b, pod_id="pod-shared")
    start, end = T0, T0 + timedelta(minutes=10)
    receipt_a = fake_receipt(
        provider_receipt_id="pod.interval.a",
        kind=ReceiptKind.ACCRUAL,
        amount=40_000,
        reservation=res_a,
        interval=(start, end),
        episode_id=first.episode_id,
    )
    receipt_b = fake_receipt(
        provider_receipt_id="pod.interval.b",
        kind=ReceiptKind.ACCRUAL,
        amount=40_000,
        reservation=res_b,
        interval=(start, end),
        episode_id=second.episode_id,
    )

    def report(lease, account, receipt):
        return world.service.record_gpu_interval(
            lease_id=lease,
            provider="fake-runpod",
            pod_id="pod-shared",
            account_id=account,
            interval_start=start,
            interval_end=end,
            basis="RUNNING",
            receipt=receipt,
        )

    outcomes = race(
        [
            partial(report, lease_a, first.account_id, receipt_a),
            partial(report, lease_b, second.account_id, receipt_b),
        ]
    )
    winners = [v for kind, v in outcomes if kind == "ok"]
    losers = [v for kind, v in outcomes if kind == "err"]
    assert len(winners) == 1 and len(losers) == 1, outcomes
    assert isinstance(losers[0], Conflict)
    assert "already attributed" in losers[0].message
    assert world.count("SELECT count(*) FROM pod_usage_intervals WHERE pod_id = 'pod-shared'") == 1
    total_accrued = (
        world.counters(first.account_id)["accrued"] + world.counters(second.account_id)["accrued"]
    )
    assert total_accrued == 40_000  # the interval's 40,000 was counted once across both episodes
    check_consistent(first.account_id)
    check_consistent(second.account_id)


def test_concurrent_opening_of_one_episode_budget_yields_one_account(
    world: World, check_consistent, db: Database
) -> None:
    from microdrama.contracts.season import CostPolicy
    from microdrama.testing.seed import seed_episode, seed_season

    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)

    def open_in_own_transaction() -> object:
        with db.transaction() as tx:
            return world.service.open_episode_account(
                tx, season_id=season, episode_id=episode, policy=CostPolicy()
            )

    outcomes = race([open_in_own_transaction for _ in range(THREADS)])
    assert all(kind == "ok" for kind, _ in outcomes), outcomes
    ids = {value for _, value in outcomes}
    assert len(ids) == 1
    assert (
        world.count("SELECT count(*) FROM budget_accounts WHERE episode_id = %s", (episode,)) == 1
    )
    assert (
        world.count(
            "SELECT count(*) FROM budget_category_allocations WHERE account_id = %s", (ids.pop(),)
        )
        == 7
    )

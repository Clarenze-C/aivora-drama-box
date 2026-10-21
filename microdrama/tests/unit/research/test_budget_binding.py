"""Budget binding: envelope, idempotent allowance, rejection retention, concurrency (T009)."""

from __future__ import annotations

import threading

import pytest
from research_support import ENVELOPE, World, request

from microdrama.contracts.errors import BudgetExhausted
from microdrama.testing.seed import seed_episode


def test_spend_is_settled_on_the_research_account_through_real_reservations(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.outcome is not None
    acct = world.account(season)
    assert acct["settled_micro_usd"] == result.outcome.settled_micro_usd
    assert acct["accrued_micro_usd"] == 0
    assert acct["reserved_outstanding_micro_usd"] == 0  # every hold was reconciled
    assert acct["cap_micro_usd"] == ENVELOPE  # the envelope itself never moved
    assert world.committed(season) == acct["settled_micro_usd"]

    reservations = world.reservations(season)
    assert {row["category"] for row in reservations} == {"RESEARCH_SCRIPT_PROMPTS_METADATA"}
    assert {row["queue"] for row in reservations} == {"production"}
    assert all(row["state"] == "SETTLED" for row in reservations)
    # Every settled charge is linked to its reservation (no unreserved spend).
    charges = world.rows("SELECT * FROM charges WHERE season_id = %s", (season,))
    assert {row["reservation_id"] for row in charges} == {row["id"] for row in reservations}


def test_new_trigger_keys_consume_the_envelope_and_exhaustion_is_typed(world: World) -> None:
    season = world.season()
    world.service.run_research(season, request(key="research.daily:v1"))
    settled_one = world.account(season)["settled_micro_usd"]

    world.service.run_research(season, request(key="research.daily:v2"))
    assert world.account(season)["settled_micro_usd"] == settled_one * 2

    # Shrink reality to the boundary: an envelope that cannot fit another planned run.
    small = world.season(envelope=8_000)  # exactly one planned worst case
    world.service.run_research(small, request(key="research.daily:v1"))
    with pytest.raises(BudgetExhausted):
        world.service.run_research(small, request(key="research.daily:v2"))
    # The first trigger still replays: repeated triggers never reset the allowance.
    replay = world.service.run_research(small, request(key="research.daily:v1"))
    assert replay.replayed is True
    assert world.account(small)["settled_micro_usd"] > 0


def test_gate1_rejection_retains_research_spend(world: World) -> None:
    season = world.season()
    result = world.service.run_research(season, request())
    assert result.outcome is not None
    settled = world.account(season)["settled_micro_usd"]
    assert settled == result.outcome.settled_micro_usd > 0

    # Gate 1 rejection (as review records it: season REJECTED, proposal REJECTED).
    with world.db.transaction() as tx:
        tx.execute("UPDATE seasons SET state = 'REJECTED' WHERE id = %s", (season,))
        tx.execute(
            "UPDATE season_proposals SET status = 'REJECTED' WHERE season_id = %s", (season,)
        )

    acct = world.account(season)
    assert acct["settled_micro_usd"] == settled  # the charge survived the rejection
    assert acct["credits_micro_usd"] == 0  # no refund was invented
    assert (
        world.count("SELECT count(*) FROM cost_overruns WHERE account_id = %s", (acct["id"],)) == 0
    )

    # Attribution still sees the full rejected spend (MD-008).
    from microdrama.contracts.season import CostPolicy

    with world.db.transaction() as tx:
        episodes = [seed_episode(tx, season, number=n) for n in (1, 2)]
        for episode_id in episodes:
            world.budget.open_episode_account(
                tx, season_id=season, episode_id=episode_id, policy=CostPolicy()
            )
    allocations = world.budget.allocate_research_cost(
        season_id=season, episode_ids=episodes, basis="pre-gate-1 research"
    )
    assert sum(a.amount_micro_usd for a in allocations) == settled
    assert world.account(season)["settled_micro_usd"] == settled


def test_concurrent_runs_cannot_overspend_the_envelope(world: World) -> None:
    """Two racing runs on an envelope that fits one planned worst case: per-call
    reservations serialize the money; at most one run completes."""
    season = world.season(envelope=8_000)
    barrier = threading.Barrier(4, timeout=30)
    results: dict[str, object] = {}
    errors: dict[str, object] = {}

    def run(name: str, key: str) -> None:
        barrier.wait()
        try:
            results[name] = world.service.run_research(season, request(key=key))
        except Exception as exc:  # noqa: BLE001 - the assertion inspects the typed errors
            errors[name] = exc

    threads = [
        threading.Thread(target=run, args=(f"a{i}", f"research.race:{i}")) for i in range(2)
    ] + [threading.Thread(target=run, args=(f"b{i}", f"research.race:{i + 2}")) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)

    completed = [r for r in results.values() if getattr(r, "state", None) == "COMPLETED"]
    assert len(completed) == 1, f"expected exactly one completed run, got {len(completed)}"
    for exc in errors.values():
        assert isinstance(exc, BudgetExhausted), f"unexpected error {exc!r}"

    acct = world.account(season)
    committed = (
        acct["reserved_outstanding_micro_usd"]
        + acct["accrued_micro_usd"]
        + acct["settled_micro_usd"]
    )
    assert committed <= acct["cap_micro_usd"]
    assert acct["overrun_micro_usd"] == 0  # the cap was never breached
    runs = world.rows(
        "SELECT state, failure_code FROM research_runs WHERE season_id = %s", (season,)
    )
    assert [row["state"] for row in runs].count("COMPLETED") == 1
    assert {row["state"] for row in runs} <= {"COMPLETED", "FAILED"}
    assert all(
        row["failure_code"] == "BUDGET_EXHAUSTED" for row in runs if row["state"] == "FAILED"
    )

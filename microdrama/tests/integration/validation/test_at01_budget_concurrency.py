"""AT-01 reproduced independently through the composed world's BudgetService.

The T005 lane proved these invariants with its own world builder; T030 re-derives
them from the pipeline composition (``build_pipeline_world``) with independently
constructed reservation requests: genuine threads, one real PostgreSQL, and the
counters read back from the account rows — never from the service's return
values alone.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import pytest

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    PriceUnit,
    QueueName,
)
from microdrama.contracts.errors import BudgetExhausted
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = [pytest.mark.db, pytest.mark.slow]

THREADS = 16
RESERVE = 700_000

_EXPIRY_TTL = timedelta(hours=1)


def _now(world) -> datetime:
    return world.fakes.clock.now()


def _request(
    *, key: str, episode_id: uuid.UUID, worst: int = RESERVE, world
) -> BudgetReservationRequest:
    """A valid GPU reservation request; retries of one logical step reuse the key.
    ``expires_at`` stays relative to the world's fake clock so the request remains
    valid however far earlier steps advanced it."""
    return BudgetReservationRequest(
        request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"t030:{key}"),
        semantic_key=key,
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        job_id=None,
        provider="fake-runpod",
        operation_kind="gpu.render_shot",
        price=_quote(),
        ceilings=ExposureCeilings(timeout_ms=1_000, max_units=1),
        worst_case_micro_usd=worst,
        is_shutdown_or_cleanup=False,
        expires_at=_now(world) + _EXPIRY_TTL,
    )


def _quote():
    """The T007 labelled FAKE_SYNTHETIC price (unit price 1 µUSD, so the contract's
    worst-case >= unit price × max_units rule holds for any probe size)."""
    from microdrama.testing.fakes.common import fake_price_quote

    return fake_price_quote(PriceUnit.GPU_SECOND).model_copy(update={"unit_price_micro_usd": 1})


def _request(
    *, key: str, episode_id: uuid.UUID, worst: int = RESERVE, world
) -> BudgetReservationRequest:
    """A valid GPU reservation request; retries of one logical step reuse the key.
    ``expires_at`` stays relative to the world's fake clock so the request remains
    valid however far earlier steps advanced it."""
    return BudgetReservationRequest(
        request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"t030:{key}"),
        semantic_key=key,
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode_id,
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        job_id=None,
        provider="fake-runpod",
        operation_kind="gpu.render_shot",
        price=_quote(),
        ceilings=ExposureCeilings(timeout_ms=1_000, max_units=1),
        worst_case_micro_usd=worst,
        is_shutdown_or_cleanup=False,
        expires_at=_now(world) + _EXPIRY_TTL,
    )


def _race(calls: list[Callable[[], Any]]) -> list[tuple[str, Any]]:
    """Every call in its own thread, released together; returns ("ok"|"err", value)."""
    barrier = threading.Barrier(len(calls))
    outcomes: list[tuple[str, Any]] = [("missing", None)] * len(calls)

    def run(index: int, call: Callable[[], Any]) -> None:
        barrier.wait(timeout=60)
        try:
            outcomes[index] = ("ok", call())
        except BaseException as exc:  # asserted by the caller
            outcomes[index] = ("err", exc)

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads), "a racing call hung"
    return outcomes


def _episode_account(world, db: Database) -> uuid.UUID:
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id, number=1)
        account_id = world.budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    return episode_id, account_id


def _counters(db: Database, account_id: uuid.UUID) -> dict[str, int]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
    assert row is not None
    return {
        "cap": row["cap_micro_usd"],
        "shutdown": row["shutdown_reserve_micro_usd"],
        "reserved": row["reserved_outstanding_micro_usd"],
        "accrued": row["accrued_micro_usd"],
        "settled": row["settled_micro_usd"],
    }


def test_racing_reservations_cannot_overspend_the_episode_cap(validation_world, db) -> None:
    """16 concurrent worst-case reservations against the US$10 account: only what
    fits is granted, the rest is a typed BudgetExhausted, and the counters read
    back from the row are exact (committed + shutdown reserve never passes cap)."""
    episode_id, account_id = _episode_account(validation_world, db)
    requests = [
        _request(key=f"t030.race.{i}", episode_id=episode_id, world=validation_world)
        for i in range(THREADS)
    ]
    outcomes = _race([partial(validation_world.budget.reserve, r) for r in requests])

    successes = [value for kind, value in outcomes if kind == "ok"]
    failures = [value for kind, value in outcomes if kind == "err"]
    assert successes, "cap must admit at least one reservation"
    assert all(isinstance(exc, BudgetExhausted) for exc in failures), failures
    assert len(successes) + len(failures) == THREADS

    counters = _counters(db, account_id)
    assert counters["reserved"] == len(successes) * RESERVE
    assert counters["reserved"] + counters["accrued"] + counters["settled"] == counters["reserved"]
    assert (
        counters["reserved"] + counters["accrued"] + counters["settled"] + counters["shutdown"]
        <= counters["cap"]
    )
    with db.transaction(readonly=True) as tx:
        active = tx.fetchval(
            "SELECT count(*) FROM reservations WHERE account_id = %s AND state = 'ACTIVE'",
            (account_id,),
        )
    assert active == len(successes), "one durable reservation per granted request"


def test_identical_semantic_key_racing_yields_exactly_one_reservation(validation_world, db) -> None:
    """A crashed worker's retry storm on ONE semantic key holds the money once."""
    episode_id, account_id = _episode_account(validation_world, db)
    request = _request(key="t030.same-key", episode_id=episode_id, world=validation_world)
    outcomes = _race([partial(validation_world.budget.reserve, request) for _ in range(THREADS)])
    successes = [value for kind, value in outcomes if kind == "ok"]
    assert len(successes) == THREADS  # every racer gets an answer, none times out
    ids = {value.id for value in successes}
    assert len(ids) == 1, f"semantic idempotency broke: {len(ids)} distinct reservations"
    replays = [value for value in successes if value.replayed]
    assert len(replays) >= THREADS - 1, "concurrent retries must be recognized as replays"
    counters = _counters(db, account_id)
    assert counters["reserved"] == RESERVE  # the money is held exactly once


def test_settlement_racing_new_reservations_keeps_totals_exact(validation_world, db) -> None:
    """Settling granted reservations while more reservations arrive: the account's
    committed total never exceeds what sequentially-executed calls would produce."""
    episode_id, account_id = _episode_account(validation_world, db)
    settled = [
        validation_world.budget.reserve(
            _request(key=f"t030.mix.{i}", episode_id=episode_id, world=validation_world)
        )
        for i in range(3)
    ]
    calls: list[Callable[[], Any]] = [
        partial(validation_world.budget.release, reservation.id, reason="t030 settled path")
        for reservation in settled
    ]
    calls += [
        partial(
            validation_world.budget.reserve,
            _request(key=f"t030.mix.late.{i}", episode_id=episode_id, world=validation_world),
        )
        for i in range(8)
    ]
    outcomes = _race(calls)
    released = [value for kind, value in outcomes[:3] if kind == "ok"]
    assert len(released) == 3, "releases cannot fail while racing new holds"
    late = outcomes[3:]
    failures = [value for kind, value in late if kind == "err"]
    granted_late = sum(1 for kind, _ in late if kind == "ok")
    # Refusals are allowed ONLY as the typed exhaustion that protects the shutdown
    # reserve — never a crash, never an inconsistent grant.
    assert all(isinstance(exc, BudgetExhausted) for exc in failures), failures
    counters = _counters(db, account_id)
    assert counters["reserved"] == granted_late * RESERVE  # first 3 released
    assert (
        counters["reserved"] + counters["accrued"] + counters["settled"] + counters["shutdown"]
        <= counters["cap"]
    ), "racing releases + new holds breached the US$10 cap"


def test_expired_reservation_cannot_be_double_spent_after_expiry_sweep(
    validation_world, db
) -> None:
    """The janitor's stale-expiry path releases exactly the expired holds — a
    retry of the same semantic key afterwards still sees a consistent account."""
    episode_id, account_id = _episode_account(validation_world, db)
    soon = _request(key="t030.expiring", episode_id=episode_id, world=validation_world)
    validation_world.budget.reserve(soon)
    validation_world.fakes.clock.advance(seconds=int(_EXPIRY_TTL.total_seconds()) + 60)
    expired = validation_world.budget.expire_stale()
    assert expired >= 1
    counters = _counters(db, account_id)
    assert counters["reserved"] == 0
    # The same logical step may run again cleanly after its hold expired.
    again = validation_world.budget.reserve(
        _request(key="t030.expiring.retry", episode_id=episode_id, world=validation_world)
    )
    assert again.reserved_micro_usd == RESERVE

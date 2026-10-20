"""Reservations: exact holds, the cap with its shutdown reserve, category spill, queue rules,
unknown-price blocking, idempotent retries and the no-reset rule (AT-01 building blocks)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from budget_support import (
    CAP,
    CPU,
    GPU,
    METERED,
    QA,
    RECOVERY,
    REFERENCES,
    RESEARCH,
    SHUTDOWN,
    T0,
    World,
    fake_receipt,
    request_for,
)

from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import (
    PriceSource,
    PriceUnit,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    IdempotencyConflict,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
    UnknownPrice,
)
from microdrama.contracts.primitives import DEFAULT_BUDGET_ALLOCATION_MICRO_USD
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.testing.fakes import fake_price_quote


def _settle(world: World, reservation, amount: int, key: str, category=GPU) -> None:
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id=key,
            kind=ReceiptKind.SETTLEMENT,
            amount=amount,
            category=category,
            reservation=reservation,
            episode_id=reservation_episode(world, reservation),
            observed_at=T0,
        )
    )


def reservation_episode(world: World, reservation) -> uuid.UUID:
    with world.db.transaction() as tx:
        return tx.fetchval("SELECT episode_id FROM reservations WHERE id = %s", (reservation.id,))


def test_open_episode_account_is_idempotent_and_opens_the_policy_allocation(
    world: World, check_consistent, db: Database
) -> None:
    ep = world.episode()
    with db.transaction() as tx:
        again = world.service.open_episode_account(
            tx, season_id=ep.season_id, episode_id=ep.episode_id, policy=CostPolicy()
        )
        protected = {
            row["category"]: row["protected"]
            for row in tx.fetchall(
                "SELECT category, protected FROM budget_category_allocations WHERE account_id = %s",
                (ep.account_id,),
            )
        }
    assert again == ep.account_id
    counters = world.counters(ep.account_id)
    assert counters["cap"] == CAP and counters["shutdown"] == SHUTDOWN
    assert counters["committed"] == 0
    for category, amount in DEFAULT_BUDGET_ALLOCATION_MICRO_USD.items():
        assert world.category(ep.account_id, category)["allocated"] == amount
    # Protected = production and recovery funds; only metered management is community-owned.
    assert protected == {c.value: c is not METERED for c in DEFAULT_BUDGET_ALLOCATION_MICRO_USD}
    check_consistent(ep.account_id)


def test_reopening_an_episode_with_a_different_policy_is_refused(world: World) -> None:
    ep = world.episode()
    shrunk = dict(DEFAULT_BUDGET_ALLOCATION_MICRO_USD)
    shrunk[RECOVERY] -= 1_000_000
    smaller = CostPolicy(episode_cap_micro_usd=9_000_000, allocation_micro_usd=shrunk)
    with pytest.raises(Conflict), world.db.transaction() as tx:
        world.service.open_episode_account(
            tx, season_id=ep.season_id, episode_id=ep.episode_id, policy=smaller
        )


def test_research_envelope_is_idempotent_and_cannot_be_resized(world: World) -> None:
    ep = world.episode()
    research = world.research(ep.season_id, envelope=2_000_000)
    with world.db.transaction() as tx:
        again = world.service.open_research_account(
            tx, season_id=ep.season_id, envelope_micro_usd=2_000_000
        )
    assert again == research
    assert world.category(research, RESEARCH)["allocated"] == 2_000_000
    assert world.category(research, GPU)["allocated"] == 0
    assert world.counters(research)["shutdown"] == 0
    with pytest.raises(Conflict), world.db.transaction() as tx:
        world.service.open_research_account(
            tx, season_id=ep.season_id, envelope_micro_usd=3_000_000
        )


def test_budgets_are_never_auto_created(world: World) -> None:
    ghost_episode = uuid.uuid4()
    with pytest.raises(NotFound):
        world.service.reserve(request_for(key="ghost.reserve", episode_id=ghost_episode))
    with pytest.raises(NotFound):
        world.service.reserve(request_for(key="ghost.research", season_id=uuid.uuid4()))
    with pytest.raises(NotFound):
        world.service.summary(ghost_episode)


def test_reservation_holds_exact_worst_case_in_account_and_category(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    reserved = world.service.reserve(
        request_for(key="gpu.hold", worst=700_000, episode_id=ep.episode_id)
    )
    assert reserved.replayed is False
    assert reserved.reserved_micro_usd == 700_000
    counters = world.counters(ep.account_id)
    assert counters["reserved"] == 700_000 and counters["committed"] == 700_000
    assert world.category(ep.account_id, GPU)["reserved"] == 700_000
    assert world.reservation_state(reserved.id)["state"] == "ACTIVE"
    assert world.service.summary(ep.episode_id).remaining_micro_usd == CAP - 700_000
    check_consistent(ep.account_id)


def test_allowance_boundary_includes_the_shutdown_reserve_until_cleanup(
    world: World, check_consistent
) -> None:
    """Fill to the cap minus the shutdown reserve, then prove the last quarter-dollar is cleanup-only."""
    ep = world.episode()
    svc = world.service
    episode = ep.episode_id
    svc.reserve(request_for(key="fill.gpu", episode_id=episode, worst=2_500_000))
    svc.reserve(
        request_for(key="fill.ref", episode_id=episode, worst=1_500_000, category=REFERENCES)
    )
    svc.reserve(request_for(key="fill.qa", episode_id=episode, worst=1_000_000, category=QA))
    svc.reserve(
        request_for(key="fill.research", episode_id=episode, worst=1_000_000, category=RESEARCH)
    )
    svc.reserve(request_for(key="fill.cpu", episode_id=episode, worst=500_000, category=CPU))
    svc.reserve(
        request_for(
            key="fill.metered",
            episode_id=episode,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
        )
    )
    # Production GPU borrows 2.25M of recovery headroom, leaving exactly the shutdown reserve.
    svc.reserve(request_for(key="fill.gpu2", episode_id=episode, worst=2_250_000))
    assert world.counters(ep.account_id)["committed"] == CAP - SHUTDOWN
    assert world.category(ep.account_id, RECOVERY)["allocated"] == SHUTDOWN

    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="over.one", episode_id=episode, worst=1))
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(
                key="over.metered",
                episode_id=episode,
                worst=1,
                category=METERED,
                queue=QueueName.COMMUNITY,
            )
        )

    cleanup = svc.reserve(
        request_for(
            key="cleanup.shutdown",
            episode_id=episode,
            worst=SHUTDOWN,
            category=RECOVERY,
            cleanup=True,
        )
    )
    assert cleanup.reserved_micro_usd == SHUTDOWN
    assert world.counters(ep.account_id)["committed"] == CAP
    check_consistent(ep.account_id)


def test_production_spill_keeps_the_shutdown_reserve_but_cleanup_may_use_it(
    world: World, check_consistent, db: Database
) -> None:
    ep = world.episode()
    svc = world.service
    before = world.counters(ep.account_id)
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="spill.too.far", episode_id=ep.episode_id, worst=4_900_000))
    assert world.counters(ep.account_id) == before
    assert world.category(ep.account_id, RECOVERY)["allocated"] == 2_500_000

    cleanup = svc.reserve(
        request_for(key="spill.cleanup", episode_id=ep.episode_id, worst=4_900_000, cleanup=True)
    )
    assert cleanup.reserved_micro_usd == 4_900_000
    assert world.category(ep.account_id, GPU)["allocated"] == 4_900_000
    assert world.category(ep.account_id, RECOVERY)["allocated"] == 100_000
    with db.transaction() as tx:
        transfers = tx.fetchall(
            "SELECT from_category, to_category, amount_micro_usd, reason FROM budget_transfers "
            "WHERE account_id = %s",
            (ep.account_id,),
        )
    assert [
        (t["from_category"], t["to_category"], t["amount_micro_usd"], t["reason"])
        for t in transfers
    ] == [("RECOVERY_HEADROOM", "GPU_GENERATION", 2_400_000, "auto-spill:spill.cleanup")]
    check_consistent(ep.account_id)


def test_community_and_publication_never_spill_but_production_does(world: World) -> None:
    ep = world.episode()
    svc = world.service
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(
                key="meter.spill",
                episode_id=ep.episode_id,
                worst=1_000_001,
                category=METERED,
                queue=QueueName.COMMUNITY,
            )
        )
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(
                key="cpu.spill",
                episode_id=ep.episode_id,
                worst=500_001,
                category=CPU,
                queue=QueueName.PUBLICATION,
            )
        )
    assert world.counters(ep.account_id)["committed"] == 0
    # Positive control: the same overflow from production borrows recovery headroom.
    svc.reserve(request_for(key="qa.spill", episode_id=ep.episode_id, worst=1_000_001, category=QA))
    assert world.category(ep.account_id, RECOVERY)["allocated"] == 2_500_000 - 1


def test_metered_management_cannot_reach_render_or_shutdown_funds(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    svc.reserve(
        request_for(
            key="meter.full",
            episode_id=ep.episode_id,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
        )
    )
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(
                key="meter.more",
                episode_id=ep.episode_id,
                worst=1,
                category=METERED,
                queue=QueueName.COMMUNITY,
            )
        )
    with pytest.raises(PolicyDenied):
        svc.reserve(
            request_for(
                key="meter.gpu",
                episode_id=ep.episode_id,
                worst=1,
                category=GPU,
                queue=QueueName.COMMUNITY,
            )
        )
    with pytest.raises(PolicyDenied):
        svc.reserve(
            request_for(
                key="prod.metered",
                episode_id=ep.episode_id,
                worst=1,
                category=METERED,
                queue=QueueName.PRODUCTION,
            )
        )
    assert world.category(ep.account_id, GPU)["reserved"] == 0
    assert world.category(ep.account_id, RECOVERY)["allocated"] == 2_500_000
    assert world.counters(ep.account_id)["committed"] == 1_000_000
    check_consistent(ep.account_id)


def test_unknown_price_blocks_paid_dispatch_and_records_nothing(db: Database) -> None:
    world = World(db)
    ep = world.episode()
    eur = PriceQuote(
        currency="EUR",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=250,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version="quote-v1",
        as_of=fake_price_quote(PriceUnit.GPU_SECOND).as_of,
    )
    for key, price in [("price.none", None), ("price.eur", eur)]:
        with pytest.raises(UnknownPrice):
            world.service.reserve(request_for(key=key, episode_id=ep.episode_id, price=price))
    # A synthetic price is not admissible once the process is not in OFFLINE_MOCK.
    paid = World(db, settings=_paid_settings())
    with pytest.raises(UnknownPrice):
        paid.service.reserve(request_for(key="price.fake.paid", episode_id=ep.episode_id))
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 0
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 0
    )


def _paid_settings():
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode

    return Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)


def test_retry_with_the_same_key_returns_the_same_reservation(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    request = request_for(key="gpu.retry", episode_id=ep.episode_id, worst=700_000)
    first = world.service.reserve(request)
    second = world.service.reserve(request)
    assert second.replayed is True
    assert second.id == first.id
    assert world.counters(ep.account_id)["committed"] == 700_000
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 1
    )
    check_consistent(ep.account_id)


def test_same_key_or_request_id_with_different_content_is_refused(world: World) -> None:
    ep = world.episode()
    original = request_for(key="gpu.stable", episode_id=ep.episode_id, worst=700_000)
    world.service.reserve(original)
    with pytest.raises(IdempotencyConflict):
        world.service.reserve(
            request_for(key="gpu.stable", episode_id=ep.episode_id, worst=800_000)
        )
    reused_id = request_for(key="gpu.other", episode_id=ep.episode_id, worst=700_000).model_copy(
        update={"request_id": original.request_id}
    )
    with pytest.raises(IdempotencyConflict):
        world.service.reserve(reused_id)
    assert world.counters(ep.account_id)["committed"] == 700_000


def test_expired_request_is_not_admitted_as_new_exposure(world: World) -> None:
    ep = world.episode()
    with pytest.raises(SchemaInvalid):
        world.service.reserve(
            request_for(
                key="gpu.stale", episode_id=ep.episode_id, expires_at=T0 - timedelta(seconds=1)
            )
        )
    assert world.counters(ep.account_id)["committed"] == 0


def test_failed_job_spend_is_kept_and_new_attempts_consume_the_allowance(
    world: World, check_consistent
) -> None:
    """No reset: a failed job keeps its spend; a new attempt, a renamed job or a retry of the old
    request cannot restore allowance."""
    ep = world.episode()
    svc = world.service
    job = world.job("render.job.ep1")
    first = svc.reserve(
        request_for(key="render.a1", episode_id=ep.episode_id, worst=1_200_000, job_id=job)
    )
    _settle(world, first, 1_000_000, key="fail.a1")
    assert world.counters(ep.account_id)["committed"] == 1_000_000

    svc.reserve(request_for(key="render.a2", episode_id=ep.episode_id, worst=1_200_000, job_id=job))
    svc.reserve(
        request_for(key="render.renamed.a3", episode_id=ep.episode_id, worst=1_200_000, job_id=job)
    )
    assert world.counters(ep.account_id)["committed"] == 3_400_000

    replay = svc.reserve(
        request_for(key="render.a1", episode_id=ep.episode_id, worst=1_200_000, job_id=job)
    )
    assert replay.replayed is True and replay.state.value == "SETTLED"
    assert world.counters(ep.account_id)["committed"] == 3_400_000

    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="render.a4", episode_id=ep.episode_id, worst=7_000_000))
    check_consistent(ep.account_id)


def test_unknown_queue_category_pairs_are_policy_denied_before_any_lock(world: World) -> None:
    ep = world.episode()
    with pytest.raises(PolicyDenied):
        world.service.reserve(
            request_for(
                key="cpu.from.community",
                episode_id=ep.episode_id,
                category=CPU,
                queue=QueueName.COMMUNITY,
            )
        )
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 0
    )


def test_research_reservation_needs_its_envelope_and_never_spills(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    envelope = world.research(ep.season_id, envelope=1_000_000)
    svc = world.service
    svc.reserve(
        request_for(key="research.ok", season_id=ep.season_id, worst=1_000_000, category=RESEARCH)
    )
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(key="research.more", season_id=ep.season_id, worst=1, category=RESEARCH)
        )
    assert world.counters(envelope)["committed"] == 1_000_000
    check_consistent(envelope)

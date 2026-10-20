"""Expired-reservation usage (no double counting) and the closed-reason audit trail (migration 0012).

Usage on an expired, unsettled reservation counts max(reserved, actual usage). Only the increase is
moved into accrued. Every closed reservation records why it closed, and a released reservation is
terminal (its state and reason never change again).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from budget_support import (
    CPU,
    METERED,
    QA,
    REFERENCES,
    RESEARCH,
    T0,
    World,
    fake_receipt,
    request_for,
)

from microdrama.budget.ledger import (
    EXPIRED_REASON,
    SETTLED_AFTER_EXPIRY_REASON,
    SETTLED_REASON,
)
from microdrama.contracts.enums import QueueName, ReceiptKind
from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.persistence import Database

pytestmark = pytest.mark.db


def _expired_gpu(world: World, *, worst: int = 700_000, accrued: int = 200_000):
    """A GPU reservation with ``accrued`` usage that has expired and is unsettled."""
    ep = world.episode()
    svc = world.service
    res = svc.reserve(
        request_for(
            key="exp.audit",
            episode_id=ep.episode_id,
            worst=worst,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    if accrued:
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="exp.audit.a0",
                kind=ReceiptKind.ACCRUAL,
                amount=accrued,
                reservation=res,
                episode_id=ep.episode_id,
                observed_at=T0,
            )
        )
    world.clock.advance(seconds=7200)
    assert svc.expire_stale() == 1
    return ep, res


def _late(world: World, ep, res, *, key: str, amount: int, kind: ReceiptKind = ReceiptKind.ACCRUAL):
    return world.service.record_usage(
        fake_receipt(
            provider_receipt_id=key,
            kind=kind,
            amount=amount,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )


# --- F-1: expired reservations count max(reserved, usage) -------------------------------


def test_late_accrual_within_the_expired_worst_case_adds_nothing(
    world: World, check_consistent
) -> None:
    ep, res = _expired_gpu(world)
    counters = world.counters(ep.account_id)
    assert counters["accrued"] == 700_000 and counters["committed"] == 700_000

    result = _late(
        world, ep, res, key="exp.audit.late", amount=300_000
    )  # real usage 500,000 <= 700,000
    assert result.overrun_recorded_micro_usd == 0
    counters = world.counters(ep.account_id)
    assert counters["accrued"] == 700_000  # not 1,000,000: the worst case already covers it
    assert (
        counters["committed"] == 700_000
        and counters["overrun"] == 0
        and counters["blocked"] is False
    )
    assert world.reservation_state(res.id)["accrued"] == 700_000
    check_consistent(ep.account_id)


def test_late_accrual_above_the_worst_case_adds_exactly_the_excess(
    world: World, check_consistent
) -> None:
    ep, res = _expired_gpu(world)
    _late(world, ep, res, key="exp.audit.big", amount=900_000)  # real usage 1,100,000
    assert world.counters(ep.account_id)["accrued"] == 1_100_000
    assert world.reservation_state(res.id)["accrued"] == 1_100_000
    _late(world, ep, res, key="exp.audit.more", amount=100_000)  # real usage 1,200,000
    assert world.counters(ep.account_id)["accrued"] == 1_200_000  # exactly the new 100,000 excess
    check_consistent(ep.account_id)


def test_late_adjustment_on_an_expired_reservation_follows_the_same_rule(
    world: World, check_consistent
) -> None:
    ep, res = _expired_gpu(world)
    _late(
        world, ep, res, key="exp.audit.adj1", amount=400_000, kind=ReceiptKind.ADJUSTMENT
    )  # 600,000 used
    assert world.counters(ep.account_id)["accrued"] == 700_000
    _late(
        world, ep, res, key="exp.audit.adj2", amount=300_000, kind=ReceiptKind.ADJUSTMENT
    )  # 900,000 used
    assert world.counters(ep.account_id)["accrued"] == 900_000
    check_consistent(ep.account_id)


def test_expired_accrual_near_the_cap_records_no_overrun_within_the_worst_case(
    world: World, check_consistent
) -> None:
    """Committed spend sits at cap minus shutdown reserve. Expired GPU usage is then fed in: no
    overrun while real usage stays within the 4,750,000 worst case, and exactly the excess above it."""
    ep = world.episode()
    svc = world.service
    episode = ep.episode_id
    gpu = svc.reserve(
        request_for(
            key="nc.gpu", episode_id=episode, worst=4_750_000, expires_at=T0 + timedelta(hours=1)
        )
    )
    later = T0 + timedelta(hours=10)
    svc.reserve(
        request_for(
            key="nc.ref", episode_id=episode, worst=1_500_000, category=REFERENCES, expires_at=later
        )
    )
    svc.reserve(
        request_for(key="nc.qa", episode_id=episode, worst=1_000_000, category=QA, expires_at=later)
    )
    svc.reserve(
        request_for(
            key="nc.res", episode_id=episode, worst=1_000_000, category=RESEARCH, expires_at=later
        )
    )
    svc.reserve(
        request_for(key="nc.cpu", episode_id=episode, worst=500_000, category=CPU, expires_at=later)
    )
    svc.reserve(
        request_for(
            key="nc.met",
            episode_id=episode,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
            expires_at=later,
        )
    )
    assert world.counters(ep.account_id)["committed"] == 9_750_000

    world.clock.advance(seconds=7200)
    assert svc.expire_stale() == 1  # only the GPU hold has expired
    assert world.counters(ep.account_id)["committed"] == 9_750_000

    def accrue(key: str, amount: int):
        return svc.record_usage(
            fake_receipt(
                provider_receipt_id=key,
                kind=ReceiptKind.ACCRUAL,
                amount=amount,
                reservation=gpu,
                episode_id=episode,
                observed_at=world.clock.now(),
            )
        )

    assert accrue("nc.use.4m", 4_000_000).overrun_recorded_micro_usd == 0  # within the worst case
    assert accrue("nc.use.4_75m", 750_000).overrun_recorded_micro_usd == 0  # exactly the worst case
    assert world.counters(ep.account_id)["committed"] == 9_750_000
    assert (
        accrue("nc.use.over", 250_000).overrun_recorded_micro_usd == 0
    )  # 5.0M used, exactly at cap
    assert world.counters(ep.account_id)["committed"] == 10_000_000
    assert world.counters(ep.account_id)["overrun"] == 0

    result = accrue("nc.use.excess", 500_000)  # 5.5M used: 500,000 above the worst case
    assert result.overrun_recorded_micro_usd == 500_000
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 10_500_000 and counters["overrun"] == 500_000
    assert counters["blocked"] is True
    check_consistent(ep.account_id)


def test_invariant_checker_rejects_a_double_counted_expired_accrual(
    world: World, check_consistent, db: Database
) -> None:
    """Reproduces the reported defect in SQL: the stored expired accrual is 1,000,000 while real usage
    is 500,000 under a 700,000 worst case. The checker must refuse it."""
    ep, res = _expired_gpu(world)
    check_consistent(ep.account_id)  # the honest state passes first
    with db.transaction() as tx:
        tx.execute("UPDATE reservations SET accrued_micro_usd = 1000000 WHERE id = %s", (res.id,))
    with pytest.raises(AssertionError, match="expired reservation"):
        check_consistent(ep.account_id)


# --- F-2: closed reasons ----------------------------------------------------------------


def test_active_reservations_carry_no_closed_reason(world: World) -> None:
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="reason.active", episode_id=ep.episode_id, worst=100_000)
    )
    assert res.closed_reason is None
    assert world.reservation_state(res.id)["closed_reason"] is None
    replay = world.service.reserve(
        request_for(key="reason.active", episode_id=ep.episode_id, worst=100_000)
    )
    assert replay.replayed is True and replay.closed_reason is None


def test_release_persists_the_validated_reason(world: World, check_consistent) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="reason.release", episode_id=ep.episode_id, worst=700_000))
    released = svc.release(res.id, reason="  idea rejected at review  ")
    assert released.state.value == "RELEASED"
    assert released.closed_reason == "idea rejected at review"  # stripped, then persisted
    stored = world.reservation_state(res.id)
    assert stored["state"] == "RELEASED" and stored["closed_reason"] == "idea rejected at review"
    check_consistent(ep.account_id)


@pytest.mark.parametrize("reason", ["", "   ", "two lines\nhere", "carriage\rreturn", "x" * 501])
def test_release_refuses_reasons_the_schema_would_reject(world: World, reason: str) -> None:
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="reason.bad", episode_id=ep.episode_id, worst=100_000)
    )
    with pytest.raises(SchemaInvalid):
        world.service.release(res.id, reason=reason)
    stored = world.reservation_state(res.id)
    assert stored["state"] == "ACTIVE" and stored["closed_reason"] is None


def test_release_accepts_a_reason_of_exactly_500_characters(world: World) -> None:
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="reason.long", episode_id=ep.episode_id, worst=100_000)
    )
    released = world.service.release(res.id, reason="r" * 500)
    assert released.closed_reason == "r" * 500


def test_released_reservation_is_terminal_except_late_settled_amount(
    world: World, db: Database
) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="reason.terminal", episode_id=ep.episode_id, worst=700_000))
    svc.release(res.id, reason="withdrawn")
    late = svc.record_usage(
        fake_receipt(
            provider_receipt_id="reason.terminal.late",
            kind=ReceiptKind.ADJUSTMENT,  # late billing after a release is an ADJUSTMENT (V-5)
            amount=100_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    assert late.replayed is False
    stored = world.reservation_state(res.id)
    assert stored["state"] == "RELEASED" and stored["closed_reason"] == "withdrawn"
    assert stored["settled"] == 100_000
    with pytest.raises(Conflict):  # the database refuses any change of a released reason or state
        with db.transaction() as tx:
            tx.execute(
                "UPDATE reservations SET closed_reason = 'rewritten' WHERE id = %s", (res.id,)
            )
    with pytest.raises(Conflict):
        with db.transaction() as tx:
            tx.execute(
                "UPDATE reservations SET state = 'ACTIVE', closed_at = NULL WHERE id = %s",
                (res.id,),
            )


def test_expiry_writes_the_fixed_expiry_reason(world: World) -> None:
    ep, res = _expired_gpu(world, accrued=0)
    stored = world.reservation_state(res.id)
    assert stored["state"] == "EXPIRED" and stored["closed_reason"] == EXPIRED_REASON


def test_settlement_writes_settled_or_settled_after_expiry(world: World) -> None:
    ep = world.episode()
    svc = world.service
    open_res = svc.reserve(
        request_for(key="reason.open.settle", episode_id=ep.episode_id, worst=300_000)
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="reason.open.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=200_000,
            reservation=open_res,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    assert world.reservation_state(open_res.id)["closed_reason"] == SETTLED_REASON

    expired_ep, expired = _expired_gpu(world, accrued=0)
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="reason.expired.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=250_000,
            reservation=expired,
            episode_id=expired_ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    stored = world.reservation_state(expired.id)
    assert stored["state"] == "SETTLED" and stored["closed_reason"] == SETTLED_AFTER_EXPIRY_REASON


def test_every_closed_state_must_carry_a_reason(world: World, db: Database) -> None:
    """The migration's CHECK: a reservation can leave ACTIVE only together with its reason."""
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="reason.check", episode_id=ep.episode_id, worst=100_000)
    )
    with pytest.raises(Conflict):
        with db.transaction() as tx:
            tx.execute(
                "UPDATE reservations SET state = 'SETTLED', closed_at = now() WHERE id = %s",
                (res.id,),
            )

"""V-17: expiry follows the injected clock only. V-13: the invariant checker derives every
reservation's settled amount from its own charges and compares it with the stored value."""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest
from budget_support import T0, World, fake_receipt, request_for

from microdrama.budget import BudgetService
from microdrama.contracts.enums import ReceiptKind

pytestmark = pytest.mark.db


def test_expiry_follows_only_the_injected_clock(world: World, check_consistent) -> None:
    ep = world.episode()
    svc = world.service
    svc.reserve(
        request_for(
            key="v17.hold",
            episode_id=ep.episode_id,
            worst=700_000,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    world.clock.advance(seconds=3000)  # 50 minutes
    assert svc.expire_stale() == 0
    world.clock.advance(seconds=600)  # 60 minutes after expiry comes into effect
    assert svc.expire_stale() == 1
    assert (
        world.count(
            "SELECT count(*) FROM reservations WHERE account_id = %s AND state = 'EXPIRED'",
            (ep.account_id,),
        )
        == 1
    )
    check_consistent(ep.account_id)


def test_expire_stale_takes_no_caller_instant(world: World) -> None:
    assert list(inspect.signature(BudgetService.expire_stale).parameters) == ["self"]
    with pytest.raises(TypeError):
        world.service.expire_stale(now=T0 + timedelta(days=30))  # a caller cannot move the clock


def test_checker_derives_settled_from_charges_including_late_adjustments(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    res = world.service.reserve(request_for(key="v13.ok", episode_id=ep.episode_id, worst=500_000))
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v13.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v13.late",
            kind=ReceiptKind.ADJUSTMENT,
            amount=100_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    assert world.reservation_state(res.id)["settled"] == 400_000
    check_consistent(ep.account_id)


def test_checker_rejects_a_settled_amount_that_disagrees_with_its_charges(
    world: World, check_consistent, db
) -> None:
    ep = world.episode()
    res = world.service.reserve(request_for(key="v13.bad", episode_id=ep.episode_id, worst=500_000))
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v13.bad.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    check_consistent(ep.account_id)
    with db.transaction() as tx:  # a double-counted settled amount, written past the service
        tx.execute("UPDATE reservations SET settled_micro_usd = 600000 WHERE id = %s", (res.id,))
    with pytest.raises(AssertionError, match="derived from charges"):
        check_consistent(ep.account_id)


def test_settlement_clears_the_accrued_usage_on_the_row(world: World, check_consistent) -> None:
    """V-27: a SETTLED row no longer carries the usage it had accrued (the account counters were right)."""
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="v27.settle", episode_id=ep.episode_id, worst=700_000)
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v27.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=200_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v27.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=250_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    state = world.reservation_state(res.id)
    assert state["state"] == "SETTLED" and state["accrued"] == 0 and state["settled"] == 250_000
    assert world.counters(ep.account_id)["committed"] == 250_000
    check_consistent(ep.account_id)


def test_expiry_then_settlement_clears_the_accrued_usage_on_the_row(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    res = world.service.reserve(
        request_for(
            key="v27.expired",
            episode_id=ep.episode_id,
            worst=700_000,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v27.exp.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=200_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    world.clock.advance(seconds=7200)
    assert world.service.expire_stale() == 1
    assert world.reservation_state(res.id)["accrued"] == 700_000  # expired rows keep the worst case
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v27.exp.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=250_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    assert world.reservation_state(res.id)["accrued"] == 0
    assert world.counters(ep.account_id)["committed"] == 250_000
    check_consistent(ep.account_id)


def test_checker_rejects_a_settled_row_that_keeps_accrued_usage(
    world: World, check_consistent, db
) -> None:
    ep = world.episode()
    res = world.service.reserve(request_for(key="v27.bad", episode_id=ep.episode_id, worst=500_000))
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v27.bad.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    check_consistent(ep.account_id)
    with db.transaction() as tx:  # a stale accrued value left on a closed row
        tx.execute("UPDATE reservations SET accrued_micro_usd = 200000 WHERE id = %s", (res.id,))
    with pytest.raises(AssertionError, match="keeps accrued"):
        check_consistent(ep.account_id)

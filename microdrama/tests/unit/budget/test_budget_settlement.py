"""Usage and settlement: accrual, reconciliation, observed overruns, replays, credits, expiry,
late reconciliation and release. Every scenario ends with the invariant checker."""

from __future__ import annotations

import uuid
from datetime import timedelta

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
    measured_receipt,
    request_for,
)

from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import ExecutionMode, PriceSource, PriceUnit, QueueName, ReceiptKind
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    IdempotencyConflict,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
    UnknownPrice,
)
from microdrama.persistence import Database


def _receipt_kwargs(world: World, reservation, episode_id: uuid.UUID):
    return {"reservation": reservation, "episode_id": episode_id, "observed_at": world.clock.now()}


def test_settlement_below_reservation_frees_the_difference_exactly(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="s.small", episode_id=ep.episode_id, worst=700_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="s.small.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=200_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    counters = world.counters(ep.account_id)
    assert (counters["reserved"], counters["accrued"], counters["committed"]) == (
        500_000,
        200_000,
        700_000,
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="s.small.settle",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    counters = world.counters(ep.account_id)
    assert (counters["reserved"], counters["accrued"], counters["settled"]) == (0, 0, 300_000)
    assert counters["committed"] == 300_000  # 400,000 freed exactly
    state = world.reservation_state(res.id)
    assert state["state"] == "SETTLED" and state["settled"] == 300_000 and state["closed"]
    check_consistent(ep.account_id)


def test_accrual_beyond_reservation_is_counted_and_only_a_cap_breach_blocks(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="s.excess", episode_id=ep.episode_id, worst=700_000))
    result = svc.record_usage(
        fake_receipt(
            provider_receipt_id="s.excess.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=800_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    assert result.overrun_recorded_micro_usd == 0
    counters = world.counters(ep.account_id)
    assert (counters["reserved"], counters["accrued"], counters["blocked"]) == (0, 800_000, False)
    assert world.reservation_state(res.id)["accrued"] == 800_000
    check_consistent(ep.account_id)


def test_settlement_above_reservation_is_recorded_as_overrun_and_blocks_paid_work(
    world: World, check_consistent, db: Database
) -> None:
    ep = world.episode()
    svc = world.service
    episode = ep.episode_id
    svc.reserve(request_for(key="c.gpu1", episode_id=episode, worst=2_500_000))
    svc.reserve(request_for(key="c.ref", episode_id=episode, worst=1_500_000, category=REFERENCES))
    svc.reserve(request_for(key="c.qa", episode_id=episode, worst=1_000_000, category=QA))
    svc.reserve(request_for(key="c.res", episode_id=episode, worst=1_000_000, category=RESEARCH))
    svc.reserve(request_for(key="c.cpu", episode_id=episode, worst=500_000, category=CPU))
    metered = svc.reserve(
        request_for(
            key="c.met",
            episode_id=episode,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
        )
    )
    gpu2 = svc.reserve(request_for(key="c.gpu2", episode_id=episode, worst=2_250_000))
    assert world.counters(ep.account_id)["committed"] == 9_750_000

    result = svc.record_usage(
        fake_receipt(
            provider_receipt_id="c.gpu2.settle",
            kind=ReceiptKind.SETTLEMENT,
            amount=3_250_000,
            **_receipt_kwargs(world, gpu2, episode),
        )
    )
    assert result.overrun_recorded_micro_usd == 750_000
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 10_750_000 and counters["overrun"] == 750_000
    assert counters["blocked"] is True

    with db.transaction() as tx:
        overrun = tx.fetchone("SELECT * FROM cost_overruns WHERE account_id = %s", (ep.account_id,))
        kept = tx.fetchval(
            "SELECT count(*) FROM charges WHERE receipt_id = %s",
            (
                fake_receipt(
                    provider_receipt_id="c.gpu2.settle", kind=ReceiptKind.SETTLEMENT, amount=1
                ).receipt_id,
            ),
        )
    assert overrun["amount_micro_usd"] == 750_000
    assert overrun["quarantined_profile"] == "fake-runpod:gpu.render_shot"
    assert overrun["charge_id"] == result.charge_id
    assert kept == 1  # the receipt is kept, never erased or relabelled

    # Paid dispatch is stopped: new work, replays, and cleanup all refuse at the cap.
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="c.after", episode_id=episode, worst=1))
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="c.gpu1", episode_id=episode, worst=2_500_000))
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(key="c.cleanup", episode_id=episode, worst=1, cleanup=True, category=GPU)
        )

    # Releasing other exposure frees room, but the recorded overrun and the block stay.
    svc.release(metered.id, reason="community plan withdrawn")
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 9_750_000
    assert counters["overrun"] == 750_000 and counters["blocked"] is True
    check_consistent(ep.account_id)


def test_replayed_receipt_is_not_double_counted_and_key_reuse_is_refused(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="replay.res", episode_id=ep.episode_id, worst=700_000))
    settlement = fake_receipt(
        provider_receipt_id="replay.settle",
        kind=ReceiptKind.SETTLEMENT,
        amount=500_000,
        **_receipt_kwargs(world, res, ep.episode_id),
    )
    first = svc.record_usage(settlement)
    second = svc.record_usage(settlement)
    assert second.replayed is True and second.charge_id == first.charge_id
    counters = world.counters(ep.account_id)
    assert counters["settled"] == 500_000 and counters["committed"] == 500_000
    assert world.count("SELECT count(*) FROM charges WHERE account_id = %s", (ep.account_id,)) == 1

    different = fake_receipt(
        provider_receipt_id="replay.settle",
        kind=ReceiptKind.SETTLEMENT,
        amount=600_000,
        **_receipt_kwargs(world, res, ep.episode_id),
    )
    with pytest.raises(IdempotencyConflict):
        svc.record_usage(different)
    assert world.counters(ep.account_id)["settled"] == 500_000
    check_consistent(ep.account_id)


def test_credit_is_recorded_but_never_restores_allowance(world: World, check_consistent) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="credit.res", episode_id=ep.episode_id, worst=2_500_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="credit.settle",
            kind=ReceiptKind.SETTLEMENT,
            amount=2_500_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="credit.refund",
            kind=ReceiptKind.CREDIT,
            amount=1_000_000,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["credits"] == 1_000_000
    assert counters["committed"] == 2_500_000  # spent money is not reduced by a credit

    with pytest.raises(BudgetExhausted) as refused:
        svc.reserve(request_for(key="credit.big", episode_id=ep.episode_id, worst=7_300_000))
    assert "cap_micro_usd" in refused.value.details  # refused by the cap, not a category
    check_consistent(ep.account_id)


def test_unreserved_usage_is_spend_and_late_billing_after_settlement_is_counted(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="unres.1",
            kind=ReceiptKind.ACCRUAL,
            amount=500_000,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["settled"] == 500_000
    assert world.category(ep.account_id, GPU)["settled"] == 500_000

    res = svc.reserve(request_for(key="late.res", episode_id=ep.episode_id, worst=300_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="late.settle",
            kind=ReceiptKind.SETTLEMENT,
            amount=300_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="late.adjust",
            kind=ReceiptKind.ADJUSTMENT,
            amount=100_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="late.second.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=50_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["settled"] == 500_000 + 300_000 + 100_000 + 50_000
    assert world.reservation_state(res.id)["settled"] == 450_000
    check_consistent(ep.account_id)


def test_expired_reservation_keeps_exposure_until_a_late_settlement_reconciles(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(
        request_for(
            key="exp.res",
            episode_id=ep.episode_id,
            worst=700_000,
            expires_at=T0 + timedelta(hours=1),
        )
    )
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="exp.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=200_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    world.clock.advance(seconds=7200)
    assert svc.expire_stale() == 1
    state = world.reservation_state(res.id)
    assert state["state"] == "EXPIRED" and state["accrued"] == 700_000
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 700_000 and counters["reserved"] == 0
    with pytest.raises(BudgetExhausted):
        svc.reserve(
            request_for(
                key="exp.more",
                episode_id=ep.episode_id,
                worst=9_000_000,
                expires_at=world.clock.now() + timedelta(hours=1),
            )
        )
    assert len(svc.cost_view(ep.episode_id).unknowns) == 1  # never hidden

    svc.record_usage(
        fake_receipt(
            provider_receipt_id="exp.settle",
            kind=ReceiptKind.SETTLEMENT,
            amount=250_000,
            **_receipt_kwargs(world, res, ep.episode_id),
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["committed"] == 250_000 and counters["accrued"] == 0
    assert world.reservation_state(res.id)["state"] == "SETTLED"
    assert svc.expire_stale() == 0
    assert svc.cost_view(ep.episode_id).unknowns == []
    check_consistent(ep.account_id)


def test_active_reservation_past_expiry_is_still_counted_until_swept(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    svc = world.service
    svc.reserve(
        request_for(
            key="sweep.res",
            episode_id=ep.episode_id,
            worst=700_000,
            expires_at=T0 + timedelta(minutes=5),
        )
    )
    world.clock.advance(seconds=600)
    assert world.counters(ep.account_id)["reserved"] == 700_000
    assert len(svc.cost_view(ep.episode_id).unknowns) == 1
    assert svc.expire_stale() == 1
    check_consistent(ep.account_id)


def test_release_is_only_for_reservations_without_usage(world: World, check_consistent) -> None:
    ep = world.episode()
    svc = world.service
    used = svc.reserve(request_for(key="rel.used", episode_id=ep.episode_id, worst=700_000))
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="rel.used.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=1,
            **_receipt_kwargs(world, used, ep.episode_id),
        )
    )
    with pytest.raises(Conflict):
        svc.release(used.id, reason="cancelled")
    idle = svc.reserve(request_for(key="rel.idle", episode_id=ep.episode_id, worst=700_000))
    released = svc.release(idle.id, reason="idea rejected at review")
    assert released.state.value == "RELEASED"
    assert world.counters(ep.account_id)["committed"] == 700_000  # only the used one remains
    with pytest.raises(Conflict):
        svc.release(idle.id, reason="again")
    with pytest.raises(NotFound):
        svc.release(uuid.uuid4(), reason="unknown")
    with pytest.raises(SchemaInvalid):
        svc.release(used.id, reason="  ")
    check_consistent(ep.account_id)


def test_receipts_must_match_their_reservation_and_name_a_scope(world: World) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="scope.res", episode_id=ep.episode_id, worst=700_000))
    with pytest.raises(Conflict):
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="scope.cat",
                kind=ReceiptKind.SETTLEMENT,
                amount=1,
                category=REFERENCES,
                **_receipt_kwargs(world, res, ep.episode_id),
            )
        )
    with pytest.raises(Conflict):
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="scope.other.ep",
                kind=ReceiptKind.SETTLEMENT,
                amount=1,
                reservation=res,
                episode_id=uuid.uuid4(),
                observed_at=world.clock.now(),
            )
        )
    with pytest.raises(SchemaInvalid):
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="scope.none",
                kind=ReceiptKind.ACCRUAL,
                amount=1,
                observed_at=world.clock.now(),
            )
        )
    with pytest.raises(NotFound):
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="scope.ghost",
                kind=ReceiptKind.SETTLEMENT,
                amount=1,
                reservation_id=uuid.uuid4(),
                observed_at=world.clock.now(),
            )
        )
    with pytest.raises(NotFound):
        svc.record_usage(
            fake_receipt(
                provider_receipt_id="scope.ghost.ep",
                kind=ReceiptKind.ACCRUAL,
                amount=1,
                episode_id=uuid.uuid4(),
                observed_at=world.clock.now(),
            )
        )
    assert world.counters(ep.account_id)["committed"] == 700_000


def test_measured_money_is_recorded_only_outside_mock_and_fakes_never_leave_mock(
    db: Database,
) -> None:
    mock = World(db)
    ep = mock.episode()
    paid_settings = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    paid = World(db, settings=paid_settings)
    quote = PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=1,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version="quote-v1",
        as_of=T0,
    )
    res = paid.service.reserve(
        request_for(
            key="billed.res",
            episode_id=ep.episode_id,
            worst=700_000,
            provider="live-provider",
            price=quote,
        )
    )
    receipt = measured_receipt(
        provider_receipt_id="billed.1",
        kind=ReceiptKind.SETTLEMENT,
        amount=300_000,
        reservation=res,
        episode_id=ep.episode_id,
    )
    with pytest.raises(PolicyDenied):
        mock.service.record_usage(receipt)  # real money is refused in OFFLINE_MOCK
    paid.service.record_usage(receipt)
    assert mock.counters(ep.account_id)["settled"] == 300_000
    assert (
        mock.count(
            "SELECT count(*) FROM charges WHERE account_id = %s AND cost_basis = 'BILLED'",
            (ep.account_id,),
        )
        == 1
    )
    fake = fake_receipt(
        provider_receipt_id="fake.in.paid",
        kind=ReceiptKind.ACCRUAL,
        amount=1,
        episode_id=ep.episode_id,
        observed_at=T0,
    )
    with pytest.raises(PolicyDenied):
        paid.service.record_usage(fake)


def test_non_usd_receipt_is_refused_so_it_cannot_be_hidden_as_spend(world: World) -> None:
    ep = world.episode()
    eur = fake_receipt(
        provider_receipt_id="eur.1",
        kind=ReceiptKind.ACCRUAL,
        amount=1,
        episode_id=ep.episode_id,
        observed_at=T0,
    ).model_copy(update={"currency": "EUR"})
    with pytest.raises(UnknownPrice):
        world.service.record_usage(eur)
    assert world.counters(ep.account_id)["committed"] == 0


def test_settled_reservation_refuses_a_replay_with_changed_fields(world: World) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="changed.res", episode_id=ep.episode_id, worst=700_000))
    base = fake_receipt(
        provider_receipt_id="changed.1",
        kind=ReceiptKind.SETTLEMENT,
        amount=10,
        **_receipt_kwargs(world, res, ep.episode_id),
    )
    svc.record_usage(base)
    with pytest.raises(IdempotencyConflict):
        svc.record_usage(base.model_copy(update={"units": 2}))
    assert world.counters(ep.account_id)["settled"] == 10


def test_settlement_budget_checks_are_not_bypassed_by_unreserved_usage(
    world: World, check_consistent
) -> None:
    """Unreserved usage above the cap is still spend: it is recorded and blocks paid dispatch."""
    ep = world.episode()
    svc = world.service
    result = svc.record_usage(
        fake_receipt(
            provider_receipt_id="unres.big",
            kind=ReceiptKind.ACCRUAL,
            amount=10_500_000,
            episode_id=ep.episode_id,
            observed_at=world.clock.now(),
        )
    )
    assert result.overrun_recorded_micro_usd == 500_000
    assert world.counters(ep.account_id)["blocked"] is True
    with pytest.raises(BudgetExhausted):
        svc.reserve(request_for(key="unres.after", episode_id=ep.episode_id, worst=1))
    check_consistent(ep.account_id)

"""V-5: after a reservation closes, only ADJUSTMENT receipts are accepted (late billing, added to
settled). A SETTLEMENT or ACCRUAL is a second final amount or new usage on a closed hold: refused with
Conflict, and nothing is written. The T007 LATE_BILLING fake (ACCRUAL then ADJUSTMENT on an open
reservation) still records correctly."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from budget_support import GPU, T0, World, fake_receipt, request_for

from microdrama.contracts.cost import ProviderOperation
from microdrama.contracts.enums import PriceUnit, ProviderOperationState, ReceiptKind
from microdrama.contracts.errors import Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.providers import ImageRequest
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, FakeGenerationProvider, SequentialIds
from microdrama.testing.fakes.common import fake_price_quote
from microdrama.testing.fakes.generation import GenerationScenario

pytestmark = pytest.mark.db


def _settled(world: World, *, amount: int = 1_000_000):
    ep = world.episode()
    res = world.service.reserve(
        request_for(key="v5.settled", episode_id=ep.episode_id, worst=1_500_000)
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v5.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=amount,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    return ep, res


def test_second_settlement_on_a_settled_reservation_is_refused_and_writes_nothing(
    world: World, check_consistent
) -> None:
    """Sequence from the validator: SETTLEMENT 1,000,000, then SETTLEMENT 600,000."""
    ep, res = _settled(world)
    before = world.counters(ep.account_id)
    with pytest.raises(Conflict, match="ADJUSTMENT"):
        world.service.record_usage(
            fake_receipt(
                provider_receipt_id="v5.restated",
                kind=ReceiptKind.SETTLEMENT,
                amount=600_000,
                reservation=res,
                episode_id=ep.episode_id,
                observed_at=T0,
            )
        )
    assert world.counters(ep.account_id) == before
    assert world.counters(ep.account_id)["settled"] == 1_000_000
    assert world.count("SELECT count(*) FROM charges WHERE account_id = %s", (ep.account_id,)) == 1
    check_consistent(ep.account_id)


def test_interim_accrual_on_a_settled_reservation_is_refused_and_writes_nothing(
    world: World, check_consistent
) -> None:
    """Sequence from the validator: SETTLEMENT 1,000,000, then an interim ACCRUAL 600,000."""
    ep, res = _settled(world)
    before = world.counters(ep.account_id)
    with pytest.raises(Conflict, match="ADJUSTMENT"):
        world.service.record_usage(
            fake_receipt(
                provider_receipt_id="v5.interim",
                kind=ReceiptKind.ACCRUAL,
                amount=600_000,
                reservation=res,
                episode_id=ep.episode_id,
                observed_at=T0,
            )
        )
    assert world.counters(ep.account_id) == before
    assert world.counters(ep.account_id)["committed"] == 1_000_000
    check_consistent(ep.account_id)


def test_adjustment_is_the_late_billing_path_and_is_added(world: World, check_consistent) -> None:
    ep, res = _settled(world)
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v5.late",
            kind=ReceiptKind.ADJUSTMENT,
            amount=600_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    counters = world.counters(ep.account_id)
    assert counters["settled"] == 1_600_000
    assert world.reservation_state(res.id)["settled"] == 1_600_000
    assert world.reservation_state(res.id)["state"] == "SETTLED"
    check_consistent(ep.account_id)


def test_released_reservation_accepts_only_adjustments(world: World, check_consistent) -> None:
    ep = world.episode()
    svc = world.service
    res = svc.reserve(request_for(key="v5.released", episode_id=ep.episode_id, worst=500_000))
    svc.release(res.id, reason="withdrawn")
    for kind in (ReceiptKind.SETTLEMENT, ReceiptKind.ACCRUAL):
        with pytest.raises(Conflict):
            svc.record_usage(
                fake_receipt(
                    provider_receipt_id=f"v5.released.{kind.value}",
                    kind=kind,
                    amount=100_000,
                    reservation=res,
                    episode_id=ep.episode_id,
                    observed_at=T0,
                )
            )
    assert world.counters(ep.account_id)["settled"] == 0
    svc.record_usage(
        fake_receipt(
            provider_receipt_id="v5.released.adjust",
            kind=ReceiptKind.ADJUSTMENT,
            amount=100_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    assert world.counters(ep.account_id)["settled"] == 100_000
    assert world.reservation_state(res.id)["state"] == "RELEASED"
    check_consistent(ep.account_id)


def test_open_reservation_still_accepts_accrual_then_settlement(
    world: World, check_consistent
) -> None:
    """Refusals only apply after a close: an open hold takes ordinary accrual and its final amount."""
    ep = world.episode()
    res = world.service.reserve(request_for(key="v5.open", episode_id=ep.episode_id, worst=500_000))
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v5.open.accrue",
            kind=ReceiptKind.ACCRUAL,
            amount=200_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    world.service.record_usage(
        fake_receipt(
            provider_receipt_id="v5.open.final",
            kind=ReceiptKind.SETTLEMENT,
            amount=250_000,
            reservation=res,
            episode_id=ep.episode_id,
            observed_at=T0,
        )
    )
    assert world.counters(ep.account_id)["settled"] == 250_000
    check_consistent(ep.account_id)


def test_t007_late_billing_fake_records_accrual_then_adjustment(
    world: World, check_consistent, db: Database
) -> None:
    """The fake's LATE_BILLING scenario: the base usage is an ACCRUAL, and the next status adds an
    ADJUSTMENT. Both land on the open reservation, and neither is refused."""
    ep = world.episode()
    price = fake_price_quote(PriceUnit.IMAGE)
    reservation = world.service.reserve(
        request_for(
            key="v5.fake.late",
            episode_id=ep.episode_id,
            worst=100_000,
            category=GPU,
            provider="fake-generation",
            operation_kind="generation.submit",
            price=price,
        )
    )
    fake = FakeGenerationProvider(
        clock=FakeClock(T0),
        ids=SequentialIds("v5-fake"),
        scenarios=(GenerationScenario.LATE_BILLING,),
    )
    request = ImageRequest(
        request_id=uuid.uuid4(),
        model_config_ref="fake-image-profile",
        rights_route_id="rights-fixture-route",
        prompt_text="Medium close-up of a fixture character at dusk.",
        width=720,
        height=1280,
        seed=1234,
        client_token="v5-late-billing-1",
        reservation_id=reservation.id,
    )
    op = ProviderOperation(
        operation_id=uuid.uuid4(),
        provider="fake-generation",
        operation_kind="generation.submit",
        client_token=request.client_token,
        request_sha256=canonical_hash(request),
        state=ProviderOperationState.PENDING_SUBMIT,
        deadline_at=T0 + timedelta(hours=1),
    )
    fake.submit(op, request)
    fake.status(op)
    accrual = fake.status(op)
    adjustment = fake.status(op)
    assert [r.kind for r in accrual.usage] == [ReceiptKind.ACCRUAL]
    assert [r.kind for r in adjustment.usage] == [ReceiptKind.ADJUSTMENT]
    for receipt in accrual.usage + adjustment.usage:
        world.service.record_usage(receipt)

    base = accrual.usage[0].amount_micro_usd
    late = adjustment.usage[0].amount_micro_usd
    assert base == 20_000 and late == 10_000  # IMAGE price table: base, then half as late billing
    counters = world.counters(ep.account_id)
    assert counters["accrued"] == base + late and counters["settled"] == 0
    state = world.reservation_state(reservation.id)
    assert state["state"] == "ACTIVE" and state["accrued"] == base + late
    check_consistent(ep.account_id)

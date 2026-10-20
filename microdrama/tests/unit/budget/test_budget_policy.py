"""Pure budget rules (no database): queue ownership, price/receipt admission, integer splits."""

from __future__ import annotations

import pytest
from budget_support import (
    CPU,
    GPU,
    METERED,
    QA,
    RECOVERY,
    RESEARCH,
    fake_receipt,
    measured_receipt,
    request_for,
)

from microdrama.budget import policy
from microdrama.budget.service import split_first_takes_remainder
from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    ExecutionMode,
    PriceSource,
    PriceUnit,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import PolicyDenied, UnknownPrice
from microdrama.testing.fakes import fake_price_quote

MOCK = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
PAID = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)


@pytest.mark.parametrize(
    ("queue", "category", "allowed"),
    [
        (QueueName.PRODUCTION, GPU, True),
        (QueueName.PRODUCTION, RECOVERY, True),
        (QueueName.PRODUCTION, RESEARCH, True),
        (QueueName.PRODUCTION, METERED, False),
        (QueueName.PUBLICATION, CPU, True),
        (QueueName.PUBLICATION, QA, False),
        (QueueName.PUBLICATION, GPU, False),
        (QueueName.COMMUNITY, METERED, True),
        (QueueName.COMMUNITY, GPU, False),
        (QueueName.COMMUNITY, RECOVERY, False),
    ],
)
def test_queue_ownership_matrix(queue: QueueName, category: BudgetCategory, allowed: bool) -> None:
    if allowed:
        policy.check_queue_may_reserve(queue, category)
    else:
        with pytest.raises(PolicyDenied):
            policy.check_queue_may_reserve(queue, category)


def test_only_production_spills_and_never_into_recovery() -> None:
    assert policy.spill_allowed(QueueName.PRODUCTION, GPU)
    assert not policy.spill_allowed(QueueName.PRODUCTION, RECOVERY)
    assert not policy.spill_allowed(QueueName.PUBLICATION, CPU)
    assert not policy.spill_allowed(QueueName.COMMUNITY, METERED)


def test_fake_price_is_admitted_in_offline_mock_only() -> None:
    request = request_for(key="price.ok")
    policy.check_price_admissible(request, MOCK)  # positive control: a valid mock price passes
    with pytest.raises(UnknownPrice):
        policy.check_price_admissible(request, PAID)


@pytest.mark.parametrize(
    "mutation",
    ["no_price", "eur", "zero_exposure"],
)
def test_unknown_price_or_exposure_blocks_dispatch(mutation: str) -> None:
    if mutation == "no_price":
        request = request_for(key="price.none", price=None)
    elif mutation == "eur":
        eur = PriceQuote(
            currency="EUR",
            unit=PriceUnit.GPU_SECOND,
            unit_price_micro_usd=250,
            source=PriceSource.PROVIDER_QUOTE,
            price_table_version="quote-v1",
            as_of=fake_price_quote(PriceUnit.GPU_SECOND).as_of,
        )
        request = request_for(key="price.eur", price=eur)
    else:
        # The contract refuses a bounded worst case below unit price x units, so build a request
        # with a valid price and then force a zero exposure to exercise the service-level guard.
        request = request_for(key="price.zero").model_copy(update={"worst_case_micro_usd": 0})
    with pytest.raises(UnknownPrice):
        policy.check_price_admissible(request, MOCK)


def test_price_source_provider_quote_is_admitted_outside_mock() -> None:
    quote = PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=250,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version="quote-v1",
        as_of=fake_price_quote(PriceUnit.GPU_SECOND).as_of,
    )
    policy.check_price_admissible(request_for(key="price.quote", price=quote), PAID)


def test_receipts_are_admitted_by_execution_mode() -> None:
    fake = fake_receipt(provider_receipt_id="r-fake", kind=ReceiptKind.ACCRUAL, amount=10)
    billed = measured_receipt(
        provider_receipt_id="r-billed", kind=ReceiptKind.SETTLEMENT, amount=10
    )
    policy.check_receipt_admissible(fake, MOCK)
    policy.check_receipt_admissible(billed, PAID)
    with pytest.raises(PolicyDenied):
        policy.check_receipt_admissible(billed, MOCK)  # measured money is refused in mock
    with pytest.raises(PolicyDenied):
        policy.check_receipt_admissible(fake, PAID)  # synthetic receipts never leave mock


def test_non_usd_receipt_cannot_be_priced() -> None:
    eur = fake_receipt(provider_receipt_id="r-eur", kind=ReceiptKind.SETTLEMENT, amount=10)
    eur = eur.model_copy(update={"currency": "EUR"})
    with pytest.raises(UnknownPrice):
        policy.check_receipt_admissible(eur, MOCK)


def test_fake_receipts_are_labelled_synthetic() -> None:
    fake = fake_receipt(provider_receipt_id="r-label", kind=ReceiptKind.ACCRUAL, amount=1)
    assert fake.cost_basis is CostBasis.SYNTHETIC_FAKE
    assert not fake.measured


@pytest.mark.parametrize(("amount", "parts"), [(0, 3), (1, 3), (1_000_001, 3), (10, 1), (999, 7)])
def test_integer_split_is_exact_and_remainder_goes_first(amount: int, parts: int) -> None:
    shares = split_first_takes_remainder(amount, parts)
    assert sum(shares) == amount
    assert len(shares) == parts
    assert all(share >= 0 for share in shares)
    assert max(shares[1:], default=0) - min(shares[1:], default=0) <= 0
    assert shares[0] - (shares[1] if parts > 1 else shares[0]) == amount % parts


def test_split_matches_the_documented_example() -> None:
    assert split_first_takes_remainder(1_000_001, 3) == [333_335, 333_333, 333_333]


@pytest.mark.parametrize(
    ("queue", "category"),
    [
        (QueueName.PRODUCTION, GPU),
        (QueueName.PRODUCTION, RECOVERY),
        (QueueName.PRODUCTION, CPU),
    ],
)
def test_shutdown_grant_is_given_to_production_cleanup_only(
    queue: QueueName, category: BudgetCategory
) -> None:
    assert policy.shutdown_grant(queue, category, requested=True) is True
    assert policy.shutdown_grant(queue, category, requested=False) is False


@pytest.mark.parametrize(
    ("queue", "category"),
    [
        (QueueName.PRODUCTION, QA),
        (QueueName.PRODUCTION, METERED),
        (QueueName.PUBLICATION, CPU),
        (QueueName.COMMUNITY, METERED),
    ],
)
def test_shutdown_grant_refuses_every_other_queue_and_category(
    queue: QueueName, category: BudgetCategory
) -> None:
    assert policy.shutdown_grant(queue, category, requested=False) is False
    with pytest.raises(PolicyDenied):
        policy.shutdown_grant(queue, category, requested=True)

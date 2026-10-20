"""Price admission (V-20, V-21). A zero unit price is not a known price, however large the ceilings.
GPU generation is priced per GPU second, so a GPU job declared under another unit cannot hold budget
against a timeout it does not bound. Requests built past the contract (model_construct) must be refused
by the service with UnknownPrice, and the refused request never reaches the ledger."""

from __future__ import annotations

import pytest
from budget_support import GPU, T0, World, request_for
from pydantic import ValidationError

from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings, PriceQuote
from microdrama.contracts.enums import BudgetCategory, PriceSource, PriceUnit
from microdrama.contracts.errors import UnknownPrice

pytestmark = pytest.mark.db

TEN_HOURS_MS = 10 * 60 * 60 * 1000


def _quote(unit: PriceUnit, unit_price: int) -> PriceQuote:
    return PriceQuote(
        currency="USD",
        unit=unit,
        unit_price_micro_usd=unit_price,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version="quote-v1",
        as_of=T0,
    )


def _unvalidated(valid: BudgetReservationRequest, **fields) -> BudgetReservationRequest:
    """The same request, built without validation (what a buggy caller could hand the service)."""
    return BudgetReservationRequest.model_construct(**{**dict(valid), **fields})


def test_zero_priced_request_with_large_ceilings_never_reaches_the_ledger(
    world: World, check_consistent
) -> None:
    ep = world.episode()
    ceilings = ExposureCeilings(timeout_ms=TEN_HOURS_MS, max_units=1)
    valid = request_for(
        key="v20.zero.control",
        episode_id=ep.episode_id,
        worst=1_000_000,
        price=_quote(PriceUnit.GPU_SECOND, 1),
        cleanup=False,
    )
    zero = _unvalidated(
        valid,
        price=_quote(PriceUnit.GPU_SECOND, 0),
        ceilings=ceilings,
        semantic_key="v20.zero",
        worst_case_micro_usd=1_000_000,
    )
    with pytest.raises(ValidationError):  # the contract refuses the zero price at construction
        BudgetReservationRequest(
            **{
                **dict(valid),
                "price": _quote(PriceUnit.GPU_SECOND, 0),
                "ceilings": ceilings,
                "semantic_key": "v20.zero.typed",
            }
        )
    with pytest.raises(UnknownPrice) as refused:
        world.service.reserve(zero)
    assert refused.value.code == "UNKNOWN_PRICE"
    assert world.counters(ep.account_id)["committed"] == 0
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 0
    )
    check_consistent(ep.account_id)

    # Positive control: the same request at a real unit price holds its worst case.
    held = world.service.reserve(
        _unvalidated(
            valid, ceilings=ceilings, semantic_key="v20.priced", worst_case_micro_usd=1_000_000
        )
    )
    assert held.reserved_micro_usd == 1_000_000


def test_gpu_job_declared_under_request_with_a_ten_hour_timeout_is_refused(
    world: World, check_consistent
) -> None:
    """Probe from the validator: a GPU job priced per REQUEST with a 10 h timeout held 1 USD."""
    ep = world.episode()
    ceilings = ExposureCeilings(timeout_ms=TEN_HOURS_MS, max_units=1)
    request_quote = _quote(PriceUnit.REQUEST, 1_000_000)  # 1 USD per request, one request allowed
    with pytest.raises(ValidationError):
        BudgetReservationRequest(
            **{
                **dict(
                    request_for(
                        key="v21.typed",
                        episode_id=ep.episode_id,
                        worst=1_000_000,
                        price=_quote(PriceUnit.GPU_SECOND, 1),
                    )
                ),
                "price": request_quote,
                "ceilings": ceilings,
                "semantic_key": "v21.typed.2",
            }
        )
    probe = _unvalidated(
        request_for(
            key="v21.probe",
            episode_id=ep.episode_id,
            worst=1_000_000,
            price=_quote(PriceUnit.GPU_SECOND, 1),
        ),
        price=request_quote,
        ceilings=ceilings,
        worst_case_micro_usd=1_000_000,
        semantic_key="v21.probe.gpu",
    )
    with pytest.raises(UnknownPrice):
        world.service.reserve(probe)
    assert world.counters(ep.account_id)["committed"] == 0
    check_consistent(ep.account_id)


def test_the_same_ten_hour_job_is_admitted_when_priced_per_gpu_second(world: World) -> None:
    """Positive control: GPU generation priced per GPU second is bounded by its ten-hour timeout.
    At 1 micro-USD per second the ceiling allows 36,000 units, so the worst case is 36,000."""
    ep = world.episode()
    held = world.service.reserve(
        request_for(
            key="v21.gpu.second",
            episode_id=ep.episode_id,
            worst=36_000,
            price=_quote(PriceUnit.GPU_SECOND, 1),
            ceilings=ExposureCeilings(timeout_ms=TEN_HOURS_MS, max_units=1),
        )
    )
    assert held.reserved_micro_usd == 36_000 and held.category is GPU


def test_request_pricing_is_admitted_outside_gpu_generation(world: World) -> None:
    """Positive control: a REQUEST price is fine for a non-GPU category (e.g. QA review)."""
    ep = world.episode()
    held = world.service.reserve(
        request_for(
            key="v21.qa.request",
            episode_id=ep.episode_id,
            worst=1_000_000,
            category=BudgetCategory.QA_CAPTIONS,
            price=_quote(PriceUnit.REQUEST, 1_000_000),
            operation_kind="generation.call",
            ceilings=ExposureCeilings(timeout_ms=TEN_HOURS_MS, max_units=1),
        )
    )
    assert held.reserved_micro_usd == 1_000_000

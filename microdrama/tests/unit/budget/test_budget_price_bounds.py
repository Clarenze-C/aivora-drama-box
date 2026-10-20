"""V-3: every price unit has a bounded worst case. An under-bounded request is refused by the contract
(typed ValidationError at construction) and, if it is built past the contract (model_construct /
model_copy), refused by the service with a typed UnknownPrice before anything is written.

Each unit is reserved under a category that fits it (GPU generation is priced per GPU second only,
so the one GPU_GENERATION case uses GPU_SECOND)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from budget_support import World
from pydantic import ValidationError

from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    PriceQuote,
    exposure_units,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    PriceSource,
    PriceUnit,
    QueueName,
)
from microdrama.contracts.errors import MicrodramaError, UnknownPrice

pytestmark = pytest.mark.db

T0 = datetime(2026, 10, 20, tzinfo=UTC)
UNIT_PRICE = 1_000

# A category that fits each unit. GPU_GENERATION only ever carries GPU_SECOND (contract, 1.4.0).
_CATEGORY_FOR_UNIT = {
    PriceUnit.REQUEST: BudgetCategory.QA_CAPTIONS,
    PriceUnit.INPUT_TOKEN_1K: BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
    PriceUnit.OUTPUT_TOKEN_1K: BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA,
    PriceUnit.AUDIO_SECOND: BudgetCategory.REFERENCES_DIALOGUE,
    PriceUnit.VIDEO_SECOND: BudgetCategory.QA_CAPTIONS,
    PriceUnit.GPU_SECOND: BudgetCategory.GPU_GENERATION,
    PriceUnit.IMAGE: BudgetCategory.REFERENCES_DIALOGUE,
    PriceUnit.CHARACTER_1K: BudgetCategory.REFERENCES_DIALOGUE,
    PriceUnit.GIGABYTE: BudgetCategory.CPU_STORAGE_TRANSFER,
}
assert set(_CATEGORY_FOR_UNIT) == set(PriceUnit)


def _ceilings(unit: PriceUnit) -> ExposureCeilings:
    if unit is PriceUnit.INPUT_TOKEN_1K:
        return ExposureCeilings(timeout_ms=5_000, max_units=1, max_input_tokens=2_000)
    if unit is PriceUnit.OUTPUT_TOKEN_1K:
        return ExposureCeilings(timeout_ms=5_000, max_units=1, max_output_tokens=3_000)
    if unit in (PriceUnit.AUDIO_SECOND, PriceUnit.VIDEO_SECOND):
        return ExposureCeilings(timeout_ms=5_000, max_units=1, max_duration_ms=10_000)
    return ExposureCeilings(timeout_ms=5_000, max_units=1)


def _bound(unit: PriceUnit, ceilings: ExposureCeilings) -> int:
    return UNIT_PRICE * exposure_units(unit, ceilings)


def _request(
    unit: PriceUnit, *, worst: int, ceilings: ExposureCeilings, episode_id
) -> BudgetReservationRequest:
    quote = PriceQuote(
        currency="USD",
        unit=unit,
        unit_price_micro_usd=UNIT_PRICE,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version="quote-v1",
        as_of=T0,
    )
    return BudgetReservationRequest(
        request_id=uuid.uuid4(),
        semantic_key=f"v3.{unit.value.lower()}.{worst}",
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode_id,
        category=_CATEGORY_FOR_UNIT[unit],
        queue=QueueName.PRODUCTION,
        provider="live-provider",
        operation_kind="generation.call",
        price=quote,
        ceilings=ceilings,
        worst_case_micro_usd=worst,
        expires_at=T0 + timedelta(hours=1),
    )


@pytest.mark.parametrize("unit", list(PriceUnit), ids=lambda u: u.value)
def test_contract_refuses_an_under_bounded_request_with_a_typed_validation_error(
    unit: PriceUnit,
) -> None:
    ceilings = _ceilings(unit)
    bound = _bound(unit, ceilings)
    episode = uuid.uuid4()
    _request(unit, worst=bound, ceilings=ceilings, episode_id=episode)  # exactly the bound is valid
    with pytest.raises(ValidationError):
        _request(unit, worst=bound - 1, ceilings=ceilings, episode_id=episode)


@pytest.mark.parametrize("unit", list(PriceUnit), ids=lambda u: u.value)
def test_service_refuses_an_under_bounded_request_with_unknown_price(
    world: World, unit: PriceUnit, check_consistent
) -> None:
    ep = world.episode()
    ceilings = _ceilings(unit)
    bound = _bound(unit, ceilings)
    valid = _request(unit, worst=bound, ceilings=ceilings, episode_id=ep.episode_id)
    under = valid.model_copy(
        update={"worst_case_micro_usd": bound - 1}
    )  # past the contract on purpose
    with pytest.raises(UnknownPrice) as refused:
        world.service.reserve(under)
    assert refused.value.code == "UNKNOWN_PRICE"
    assert isinstance(refused.value, MicrodramaError)
    assert world.counters(ep.account_id)["committed"] == 0
    assert (
        world.count("SELECT count(*) FROM reservations WHERE account_id = %s", (ep.account_id,))
        == 0
    )
    check_consistent(ep.account_id)


@pytest.mark.parametrize(
    "unit",
    [
        PriceUnit.INPUT_TOKEN_1K,
        PriceUnit.OUTPUT_TOKEN_1K,
        PriceUnit.AUDIO_SECOND,
        PriceUnit.VIDEO_SECOND,
    ],
    ids=lambda u: u.value,
)
def test_missing_token_or_duration_ceiling_is_uncertain_exposure(
    world: World, unit: PriceUnit
) -> None:
    ep = world.episode()
    complete = _ceilings(unit)
    bare = ExposureCeilings(timeout_ms=5_000, max_units=1)  # the matching ceiling is absent
    valid = _request(
        unit, worst=_bound(unit, complete), ceilings=complete, episode_id=ep.episode_id
    )
    with pytest.raises(ValidationError):
        _request(unit, worst=_bound(unit, complete), ceilings=bare, episode_id=ep.episode_id)
    with pytest.raises(UnknownPrice):
        world.service.reserve(valid.model_copy(update={"ceilings": bare}))


@pytest.mark.parametrize("unit", list(PriceUnit), ids=lambda u: u.value)
def test_exact_bound_is_admitted(world: World, unit: PriceUnit) -> None:
    """Positive control: a request at exactly unit price x exposure units reserves normally."""
    ep = world.episode()
    ceilings = _ceilings(unit)
    reserved = world.service.reserve(
        _request(unit, worst=_bound(unit, ceilings), ceilings=ceilings, episode_id=ep.episode_id)
    )
    assert reserved.reserved_micro_usd == _bound(unit, ceilings)
    assert reserved.category is _CATEGORY_FOR_UNIT[unit]

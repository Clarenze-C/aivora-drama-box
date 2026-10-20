"""Shared fake machinery: clock, ids, synthetic pricing, scenario queue, and the offline gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    ExecutionMode,
    PriceUnit,
    Provenance,
    ReceiptKind,
)
from microdrama.contracts.errors import EffectDenied
from microdrama.testing.fakes import (
    FAKE_PRICE_TABLE,
    FAKE_PRICE_TABLE_VERSION,
    FakeClock,
    PublishScenario,
    SequentialIds,
    build_fake_providers,
    ensure_mock_mode,
    fake_https,
    fake_price_quote,
    synthetic_receipt,
)
from microdrama.testing.fakes.common import ScenarioQueue, priced

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def test_clock_is_deterministic_and_rejects_naive_or_backwards_time() -> None:
    clock = FakeClock(T0)
    assert clock.now() == T0
    clock.advance(ms=1500)
    assert clock.now() == T0 + timedelta(milliseconds=1500)
    clock.set(T0)
    assert clock.now() == T0
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 10, 20))
    with pytest.raises(ValueError):
        clock.advance(ms=-1)


def test_sequential_ids_repeat_across_instances_and_differ_within_one() -> None:
    first = SequentialIds("same")
    second = SequentialIds("same")
    run_one = [first.new_id() for _ in range(3)]
    run_two = [second.new_id() for _ in range(3)]
    assert run_one == run_two
    assert len(set(run_one)) == 3
    assert SequentialIds("other").new_id() != run_one[0]


def test_price_table_is_integer_micro_usd_and_labelled_synthetic() -> None:
    assert all(isinstance(v, int) and v > 0 for v in FAKE_PRICE_TABLE.values())
    quote = fake_price_quote(PriceUnit.GPU_SECOND)
    assert quote.unit_price_micro_usd == 250
    assert quote.source.value == "FAKE_SYNTHETIC"
    assert quote.price_table_version == FAKE_PRICE_TABLE_VERSION == "fake-prices-v1"
    assert priced(PriceUnit.GPU_SECOND, 4) == 1_000


def test_synthetic_receipt_carries_fake_provenance_and_basis() -> None:
    receipt = synthetic_receipt(
        provider="fake-x",
        provider_receipt_id="rx-1",
        kind=ReceiptKind.SETTLEMENT,
        category=BudgetCategory.QA_CAPTIONS,
        unit=PriceUnit.REQUEST,
        units=1,
        amount_micro_usd=1_000,
        observed_at=T0,
    )
    assert receipt.provenance is Provenance.FAKE_SYNTHETIC
    assert receipt.cost_basis is CostBasis.SYNTHETIC_FAKE
    assert not receipt.measured
    twin = synthetic_receipt(
        provider="fake-x",
        provider_receipt_id="rx-1",
        kind=ReceiptKind.SETTLEMENT,
        category=BudgetCategory.QA_CAPTIONS,
        unit=PriceUnit.REQUEST,
        units=1,
        amount_micro_usd=1_000,
        observed_at=T0,
    )
    assert receipt.receipt_id == twin.receipt_id  # ids depend only on the dedupe key


def test_fake_urls_only_use_the_invalid_tld() -> None:
    assert fake_https("sources.fake", "a/1") == "https://sources.fake.invalid/a/1"
    assert fake_https("members.fake.invalid").endswith(".invalid/")


def test_scenario_queue_consumes_in_order_then_falls_back_to_default() -> None:
    queue = ScenarioQueue(PublishScenario.ACCEPTED, [PublishScenario.TOKEN_EXPIRED])
    queue.push(PublishScenario.RATE_LIMITED)
    assert queue.next() is PublishScenario.TOKEN_EXPIRED
    assert queue.next() is PublishScenario.RATE_LIMITED
    assert queue.next() is PublishScenario.ACCEPTED


@pytest.mark.parametrize(
    "mode",
    [ExecutionMode.PAID_BENCHMARK, ExecutionMode.CONTROLLED_ACCOUNT_TEST, ExecutionMode.PRODUCTION],
)
def test_fakes_refuse_to_build_outside_offline_mock(mode: ExecutionMode) -> None:
    settings = Settings(execution_mode=mode)
    with pytest.raises(EffectDenied):
        ensure_mock_mode(settings)
    with pytest.raises(EffectDenied):
        build_fake_providers(settings, FakeClock(T0), SequentialIds("gate"))


def test_offline_mock_builds_one_fake_per_boundary(offline_settings: Settings) -> None:
    providers = build_fake_providers(offline_settings, FakeClock(T0), SequentialIds("gate"))
    assert set(providers.publishers) == set(providers.community)
    assert len(providers.publishers) == 4
    assert len(providers.memberships) == 2
    assert providers.comfy_state.prompts == {}
    assert providers.truth.get("0" * 64) is None


def test_default_offline_settings_are_offline_mock() -> None:
    assert Settings().execution_mode is ExecutionMode.OFFLINE_MOCK

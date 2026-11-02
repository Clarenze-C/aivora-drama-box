from decimal import Decimal

import pytest

from microdrama.budget.billing import (
    amount_to_micro_usd,
    largest_remainder,
    parse_provider_bucket,
)


def test_provider_decimal_conversion_is_exact_to_micro_usd() -> None:
    assert amount_to_micro_usd("0.000001") == 1
    assert amount_to_micro_usd(Decimal("1.2345675")) == 1_234_568


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity", 0.1])
def test_rejects_negative_nonfinite_and_float_money(value: object) -> None:
    with pytest.raises(ValueError):
        amount_to_micro_usd(value)  # type: ignore[arg-type]


def test_provider_components_must_sum_and_are_usd() -> None:
    assert parse_provider_bucket(
        {
            "totalAmount": Decimal("1.00"),
            "gpuAmount": Decimal("0.70"),
            "cpuAmount": Decimal("0.10"),
            "diskAmount": Decimal("0.20"),
            "currency": "USD",
        }
    ) == {"total": 1_000_000, "gpu": 700_000, "cpu": 100_000, "disk": 200_000}
    with pytest.raises(ValueError, match="does not equal"):
        parse_provider_bucket(
            {
                "totalAmount": Decimal("1.00"),
                "gpuAmount": Decimal("0.70"),
                "cpuAmount": Decimal("0.10"),
                "diskAmount": Decimal("0.10"),
                "currency": "USD",
            }
        )


def test_largest_remainder_conserves_positive_and_negative_deltas() -> None:
    weights = [("lease-a", 1), ("lease-b", 1), ("recovery", 1)]
    assert largest_remainder(5, weights) == {"lease-a": 2, "lease-b": 2, "recovery": 1}
    assert largest_remainder(-5, weights) == {"lease-a": -2, "lease-b": -2, "recovery": -1}
    assert sum(largest_remainder(5, weights).values()) == 5

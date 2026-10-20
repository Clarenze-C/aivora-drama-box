"""Money/time/unknown-value conventions every lane relies on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from microdrama.contracts.catalog import MetricValue
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    CoverageStatus,
    Provenance,
    QAOutcome,
)
from microdrama.contracts.examples import (
    capability_record,
    qa_finding,
    release_package,
    usage_receipt,
)
from microdrama.contracts.primitives import (
    DEFAULT_BUDGET_ALLOCATION_MICRO_USD,
    EPISODE_CAP_MICRO_USD,
    IanaZone,
    MicroUSD,
    ObjectKey,
    ScheduleInstant,
    UtcDateTime,
)
from microdrama.contracts.release import PublishResult

money = TypeAdapter(MicroUSD)


def test_cap_and_allocation() -> None:
    assert EPISODE_CAP_MICRO_USD == 10_000_000
    assert sum(DEFAULT_BUDGET_ALLOCATION_MICRO_USD.values()) == EPISODE_CAP_MICRO_USD


@pytest.mark.parametrize("bad", [1.0, 0.5, True, "100", -1, None])
def test_micro_usd_rejects_non_integers_and_negatives(bad: object) -> None:
    with pytest.raises(ValidationError):
        money.validate_python(bad)


def test_micro_usd_from_json_rejects_float_literal() -> None:
    with pytest.raises(ValidationError):
        money.validate_json("10.0")
    assert money.validate_json("10") == 10


def test_utc_datetime_requires_awareness_and_normalizes() -> None:
    adapter = TypeAdapter(UtcDateTime)
    with pytest.raises(ValidationError):
        adapter.validate_python(datetime(2026, 1, 1))
    value = adapter.validate_python(datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7))))
    assert value.tzinfo is UTC and value.hour == 0


def test_iana_zone_validation() -> None:
    adapter = TypeAdapter(IanaZone)
    assert adapter.validate_python("Asia/Bangkok") == "Asia/Bangkok"
    for bad in ("Mars/Olympus", "+07:00", "../etc/passwd"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_schedule_dst_gap_and_overlap_are_explicit() -> None:
    with pytest.raises(ValueError):
        ScheduleInstant.from_local("America/New_York", datetime(2026, 3, 8, 2, 30))  # gap
    with pytest.raises(ValueError):
        ScheduleInstant.from_local(
            "America/New_York", datetime(2026, 11, 1, 1, 30)
        )  # overlap, no fold
    first = ScheduleInstant.from_local("America/New_York", datetime(2026, 11, 1, 1, 30), fold=0)
    second = ScheduleInstant.from_local("America/New_York", datetime(2026, 11, 1, 1, 30), fold=1)
    assert second.utc_instant - first.utc_instant == timedelta(hours=1)
    bkk = ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 19, 30))
    assert bkk.utc_instant == datetime(2026, 10, 27, 12, 30, tzinfo=UTC)


def test_object_keys_are_private_relative_paths() -> None:
    adapter = TypeAdapter(ObjectKey)
    assert adapter.validate_python("episodes/ep1/master.mp4")
    for bad in ("/abs/path", "a/../b", "a//b", "./a", "a b"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_unknown_stays_representable() -> None:
    finding = qa_finding().model_copy(
        update={"coverage": CoverageStatus.UNAVAILABLE, "outcome": QAOutcome.UNKNOWN}
    )
    assert finding.outcome is QAOutcome.UNKNOWN
    assert finding.blocks_release  # critical and not PASS
    assert MetricValue(definition="x").value is None
    assert capability_record().support(CapabilityOperation.INSIGHTS) is CapabilitySupport.UNKNOWN


def test_fake_results_never_carry_real_urls() -> None:
    with pytest.raises(ValidationError):
        PublishResult(
            state="SUBMITTED",
            url="https://www.youtube.com/watch?v=x",
            provenance=Provenance.FAKE_SYNTHETIC,
        )
    ok = PublishResult(
        state="SUBMITTED", url="https://video.fake.invalid/x", provenance=Provenance.FAKE_SYNTHETIC
    )
    assert ok.url.endswith("/x")
    with pytest.raises(ValidationError):
        PublishResult(
            state="SUBMITTED",
            url="https://video.fake.invalid/x",
            provenance=Provenance.LIVE_PROVIDER,
        )


def test_fake_usage_is_synthetic_not_measured() -> None:
    receipt = usage_receipt()
    assert receipt.provenance is Provenance.FAKE_SYNTHETIC
    assert not receipt.measured


def test_gate_readiness_reflects_blockers() -> None:
    pkg = release_package()
    assert pkg.gate_ready
    blocked = pkg.model_copy(update={"gate_blockers": ["critical finding unresolved"]})
    assert not blocked.gate_ready

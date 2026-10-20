"""Money/time/unknown-value conventions every lane relies on."""

from __future__ import annotations

import uuid
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
from microdrama.contracts.release import PublishResult, ReleasePackage

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


def test_blocking_findings_cannot_hide_from_the_gate() -> None:
    """A package that lists a blocking finding must also list a gate blocker (validated)."""
    pkg = release_package()
    qa = pkg.qa.model_copy(update={"blocking_finding_ids": [uuid.uuid4()]})
    # Reseal the hash for the changed QA summary so only the blocker rule is exercised.
    resealed = ReleasePackage.model_construct(**{**pkg.__dict__, "qa": qa}).compute_hash()
    data = pkg.model_dump(mode="json")
    data["qa"] = qa.model_dump(mode="json")
    data["package_hash"] = resealed
    data["gate_blockers"] = []
    with pytest.raises(ValidationError, match="blocking findings must appear as gate blockers"):
        ReleasePackage.model_validate(data)
    data["gate_blockers"] = ["critical finding unresolved"]
    blocked = ReleasePackage.model_validate(data)
    assert not blocked.gate_ready


def test_qa_summary_change_changes_the_package_hash() -> None:
    """Approval binds the hash; a different QA outcome is a different package."""
    pkg = release_package()
    changed = ReleasePackage.model_construct(
        **{
            **pkg.__dict__,
            "qa": pkg.qa.model_copy(update={"finding_count": pkg.qa.finding_count + 1}),
        }
    )
    assert changed.compute_hash() != pkg.package_hash


def test_publish_verification_and_readback_links_follow_url_rules() -> None:
    from microdrama.contracts.providers import PostReadback

    with pytest.raises(ValidationError):
        PostReadback(
            external_id="x",
            links=["https://www.tiktok.com/@a/video/1"],
            provenance=Provenance.FAKE_SYNTHETIC,
        )
    with pytest.raises(ValidationError):
        PublishResult(
            state="PUBLISHED_VERIFIED", external_id="x", provenance=Provenance.FAKE_SYNTHETIC
        )
    ok = PublishResult(
        state="PUBLISHED_VERIFIED",
        external_id="x",
        verified_fields=["exists"],
        provenance=Provenance.FAKE_SYNTHETIC,
    )
    assert ok.verified_fields == ["exists"]

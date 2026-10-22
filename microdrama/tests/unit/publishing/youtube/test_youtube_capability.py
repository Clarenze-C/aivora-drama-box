"""Capability snapshot pins (T021): documentation-only support, disabled research record.

The snapshot must be honest research: OFFICIAL_DOCUMENTATION sources with the
as-of date inside every ref, SUPPORTED_DOCUMENTED at most (a fixture run is not a
controlled account test), unknown surfaces left UNKNOWN, and the research record
shipped disabled until T032 produces live evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EvidenceSource,
    Platform,
)
from microdrama.publishing.youtube.capabilities import (
    PROVIDER_ROUTE,
    RESEARCH_EVIDENCE,
    RESEARCH_LIMITS,
    RESEARCH_OPERATIONS,
    capability_id_for,
    fixture_capability_record,
    research_capability_record,
)

SNAPSHOT_ACCOUNT = "acct:youtube-main"


def test_research_record_is_disabled_and_documentation_sourced() -> None:
    record = research_capability_record(SNAPSHOT_ACCOUNT)
    assert record.enabled is False  # live publishing off until T032 evidence exists
    assert record.platform is Platform.YOUTUBE
    assert record.provider_route == PROVIDER_ROUTE
    assert record.verified_at is not None
    assert record.evidence, "a documentation snapshot names its sources"
    for ref in record.evidence:
        assert ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION
        assert "2026-10" in ref.ref, "every doc claim carries its as-of date"
        assert ref.note, "every doc claim states what was actually documented"


def test_no_operation_is_ever_claimed_tested() -> None:
    for operations in (
        RESEARCH_OPERATIONS,
        research_capability_record(SNAPSHOT_ACCOUNT).operations,
    ):
        assert CapabilitySupport.SUPPORTED_TESTED not in operations.values()
    fixture = fixture_capability_record(
        SNAPSHOT_ACCOUNT, verified_at=datetime(2026, 10, 22, tzinfo=UTC)
    )
    assert CapabilitySupport.SUPPORTED_TESTED not in fixture.operations.values()


def test_documented_operations_are_supported_and_rest_stay_unknown() -> None:
    record = research_capability_record(SNAPSHOT_ACCOUNT)
    documented = {
        CapabilityOperation.UPLOAD_FULL_VIDEO,
        CapabilityOperation.UPLOAD_SHORT,
        CapabilityOperation.SCHEDULE,
        CapabilityOperation.STATUS,
        CapabilityOperation.READBACK,
        CapabilityOperation.AI_DISCLOSURE,
        CapabilityOperation.CAPTIONS_UPLOAD,
        CapabilityOperation.LOCALIZED_METADATA,
        CapabilityOperation.METADATA_UPDATE,
        CapabilityOperation.COVER_UPDATE,
    }
    for op in documented:
        assert record.support(op) is CapabilitySupport.SUPPORTED_DOCUMENTED
    # surfaces this snapshot did not research stay UNKNOWN, never guessed
    for op in (
        CapabilityOperation.INSIGHTS,
        CapabilityOperation.COMMENT_READ,
        CapabilityOperation.COMMENT_REPLY,
        CapabilityOperation.WEBHOOKS,
        CapabilityOperation.SPONSOR_DISCLOSURE,
    ):
        assert record.support(op) is CapabilitySupport.UNKNOWN
    # and the platform genuinely has no DM surface
    assert record.support(CapabilityOperation.DM_SEND) is CapabilitySupport.UNSUPPORTED


def test_documented_limits_carry_their_derivation_in_the_evidence() -> None:
    limits = research_capability_record(SNAPSHOT_ACCOUNT).limits
    assert limits.max_duration_ms == 900_000  # documented default cap (unverified channels)
    assert limits.max_file_bytes == RESEARCH_LIMITS.max_file_bytes
    # 10,000 documented quota units/day at 1,600 units per videos.insert call
    assert limits.daily_post_quota == 6
    quota_note = next(e for e in RESEARCH_EVIDENCE if "10,000 units/day" in e.note)
    assert "1600" in quota_note.note


def test_disclosure_surface_is_one_documented_field() -> None:
    record = research_capability_record(SNAPSHOT_ACCOUNT)
    assert set(record.supported_disclosures) == {
        kind
        for kind in record.supported_disclosures
        if kind.value in ("AI_GENERATED_CONTENT", "SYNTHETIC_VOICE")
    }


def test_fixture_variant_is_enabled_with_fake_evidence_only() -> None:
    verified = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
    record = fixture_capability_record(SNAPSHOT_ACCOUNT, verified_at=verified)
    assert record.enabled is True
    assert record.verified_at == verified
    assert record.evidence_is_fake_only is True  # fixture data carries no real evidence (D3)
    kinds = {kind.value for kind in record.supported_disclosures}
    assert kinds == {"AI_GENERATED_CONTENT", "SYNTHETIC_VOICE"}


def test_fixture_variant_capability_id_is_stable_across_accounts_and_versions() -> None:
    verified = datetime(2026, 10, 22, tzinfo=UTC)
    v1 = fixture_capability_record(SNAPSHOT_ACCOUNT, verified_at=verified, version=1)
    v2 = fixture_capability_record(SNAPSHOT_ACCOUNT, verified_at=verified, version=2)
    assert v1.capability_id == v2.capability_id == capability_id_for(SNAPSHOT_ACCOUNT)
    assert v1.version != v2.version  # staleness is version-only, by design


def test_fixture_disclosures_follow_disclosure_support() -> None:
    operations = dict(RESEARCH_OPERATIONS)
    operations[CapabilityOperation.AI_DISCLOSURE] = CapabilitySupport.UNSUPPORTED
    record = fixture_capability_record(
        SNAPSHOT_ACCOUNT, verified_at=datetime(2026, 10, 22, tzinfo=UTC), operations=operations
    )
    assert record.supported_disclosures == []

"""The frozen Facebook capability snapshot (T024): declaration truth, page scope.

Pins what the shipped record may claim: OFFICIAL_DOCUMENTATION evidence only, at most
SUPPORTED_DOCUMENTED (SUPPORTED_TESTED belongs to T032), an empty
``supported_disclosures`` while no documented API field can set and read back an AI
label, and Page-scope-only accounts (personal profiles have no publishing API).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from facebook_support import FB_ACCOUNT, T0, fixture_adapter

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EvidenceSource,
    ExecutionMode,
)
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.providers import PublisherAdapter
from microdrama.contracts.release import CapabilityRecord
from microdrama.publishing.facebook import facebook_page_adapter
from microdrama.publishing.facebook.capabilities import (
    FB_PAGE_ACCOUNT,
    FB_PAGE_OPERATIONS,
    SNAPSHOT_AS_OF,
    facebook_page_capability_record,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds

EXPECTED_OPERATIONS = {
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.METADATA_UPDATE: CapabilitySupport.SUPPORTED_DOCUMENTED,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNKNOWN,
    CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
}


def clock() -> FakeClock:
    return FakeClock(T0)


def ids() -> SequentialIds:
    return SequentialIds("fb-tests")


def test_snapshot_operations_are_frozen() -> None:
    assert FB_PAGE_OPERATIONS == EXPECTED_OPERATIONS


def test_operations_outside_the_snapshot_read_as_unknown() -> None:
    record = facebook_page_capability_record(FB_PAGE_ACCOUNT)
    for op in (CapabilityOperation.INSIGHTS, CapabilityOperation.CAPTIONS_UPLOAD):
        assert record.support(op) is CapabilitySupport.UNKNOWN


def test_no_operation_ever_claims_supported_tested() -> None:
    record = facebook_page_capability_record(FB_PAGE_ACCOUNT)
    assert CapabilitySupport.SUPPORTED_TESTED not in set(record.operations.values())
    with pytest.raises(ValueError, match="SUPPORTED_TESTED is reserved for T032"):
        facebook_page_capability_record(
            FB_PAGE_ACCOUNT,
            operations={
                **FB_PAGE_OPERATIONS,
                CapabilityOperation.UPLOAD_SHORT: CapabilitySupport.SUPPORTED_TESTED,
            },
        )


def test_default_record_is_disabled_with_documentation_evidence_only() -> None:
    record = facebook_page_capability_record(FB_PAGE_ACCOUNT)
    assert isinstance(record, CapabilityRecord)
    assert record.enabled is False  # live publishing stays off until T032
    assert record.account_type == "page"
    assert record.provider_route == "facebook-page"
    assert record.verified_at == SNAPSHOT_AS_OF
    assert record.evidence, "even a disabled record carries its research evidence"
    for ref in record.evidence:
        assert ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION
        assert "developers.facebook.com" in ref.ref
        assert "2026-10" in ref.ref  # the as-of date is part of the claim


def test_declaration_truth_no_supported_disclosures() -> None:
    """No documented AI-label field -> no supported disclosures -> MD-015 slots HELD.

    This is the documented outcome for BOTH the default and the fixture record: the
    evidence label differs between them, the platform truth does not.
    """
    default = facebook_page_capability_record(FB_PAGE_ACCOUNT)
    fixture = facebook_page_capability_record(
        FB_PAGE_ACCOUNT,
        fixture=True,
        verified_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    )
    assert default.supported_disclosures == []
    assert fixture.supported_disclosures == []
    assert default.limits.min_duration_ms == 500
    assert default.limits.max_duration_ms == 90_000
    assert default.limits.aspect_ratios == ["9:16"]


def test_fixture_record_is_enabled_with_fake_evidence_only() -> None:
    fixture = facebook_page_capability_record(
        FB_PAGE_ACCOUNT, fixture=True, verified_at=datetime(2026, 10, 27, tzinfo=UTC)
    )
    assert fixture.enabled is True
    assert fixture.evidence_is_fake_only is True


def test_capability_id_is_deterministic_per_account() -> None:
    adapter = fixture_adapter(
        clock(),
        ids(),
        page_accounts={FB_PAGE_ACCOUNT: "main", "acct:facebook-second-page": "second"},
    )
    first = adapter.capability(FB_PAGE_ACCOUNT)
    second = adapter.capability(FB_PAGE_ACCOUNT)
    other = adapter.capability("acct:facebook-second-page")
    assert (first.capability_id, first.version) == (second.capability_id, second.version)
    assert first.capability_id != other.capability_id


def test_capability_refuses_user_timeline_accounts() -> None:
    """Personal profiles have no publishing API; only Page accounts get a record."""
    adapter = fixture_adapter(clock(), ids())
    with pytest.raises(PolicyDenied, match="personal profiles have no publishing API"):
        adapter.capability("acct:facebook-personal-profile")
    record = adapter.capability(FB_PAGE_ACCOUNT)
    assert record.account_type == "page"
    assert record.account_ref == FB_PAGE_ACCOUNT
    assert FB_ACCOUNT == FB_PAGE_ACCOUNT


def test_adapters_satisfy_the_publisher_adapter_protocol() -> None:
    fixture = facebook_page_adapter(clock=clock(), ids=ids(), settings=Settings())
    refusing = facebook_page_adapter(
        clock=clock(), ids=ids(), settings=Settings(execution_mode=ExecutionMode.PRODUCTION)
    )
    assert isinstance(fixture, PublisherAdapter)
    assert isinstance(refusing, PublisherAdapter)


def test_factory_returns_fixture_only_in_offline_mock() -> None:
    fixture = facebook_page_adapter(clock=clock(), ids=ids(), settings=Settings())
    assert fixture.capability(FB_PAGE_ACCOUNT).enabled is True
    from microdrama.publishing.facebook.transport import (
        FixtureFacebookTransport,
        RefusingFacebookTransport,
    )

    assert isinstance(fixture.transport, FixtureFacebookTransport)

    live = facebook_page_adapter(
        clock=clock(), ids=ids(), settings=Settings(execution_mode=ExecutionMode.PRODUCTION)
    )
    assert isinstance(live.transport, RefusingFacebookTransport)
    record = live.capability(FB_PAGE_ACCOUNT)
    assert record.enabled is False  # the documentation snapshot, disabled until T032


def test_live_transport_refuses_every_call_until_t032() -> None:
    live = facebook_page_adapter(
        clock=clock(), ids=ids(), settings=Settings(execution_mode=ExecutionMode.PRODUCTION)
    )
    with pytest.raises(PolicyDenied, match="live publishing disabled until T032"):
        live.transport.video_status(external_id="fb-full-0000000000000000")
    with pytest.raises(PolicyDenied, match="T032"):
        live.transport.get_video(external_id="fb-full-0000000000000000")
    with pytest.raises(PolicyDenied, match="scenario scripting"):
        live.queue_scenarios()

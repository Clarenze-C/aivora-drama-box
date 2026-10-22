"""Capability truth pins (T023): the frozen 2026-10 documentation snapshot.

The declaration-truth decision is pinned here as data: AI_DISCLOSURE is UNSUPPORTED
(no documented API field sets or reads back a synthetic-media label),
``supported_disclosures`` is empty, no operation is SUPPORTED_TESTED (that is T032),
and the live/default record is disabled.
"""

from __future__ import annotations

import pytest
from instagram_lane_support import PERSONAL_ACCOUNT_REF, default_accounts
from publishing_support import T0

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EvidenceSource,
    ExecutionMode,
    Platform,
)
from microdrama.contracts.providers import PublisherAdapter
from microdrama.publishing.instagram import RESEARCH_AS_OF, build_instagram_adapter
from microdrama.publishing.instagram import capabilities as caps
from microdrama.publishing.instagram.adapter import InstagramAdapter
from microdrama.publishing.instagram.transport import (
    DEFAULT_ACCOUNT_REF,
    FixtureInstagramTransport,
    InstagramAccount,
    InstagramAccountType,
    InstagramTransport,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds

DOCUMENTED_UNSUPPORTED = (
    CapabilityOperation.AI_DISCLOSURE,
    CapabilityOperation.SCHEDULE,
    CapabilityOperation.CAPTIONS_UPLOAD,
    CapabilityOperation.LOCALIZED_METADATA,
    CapabilityOperation.METADATA_UPDATE,
    CapabilityOperation.COVER_UPDATE,
)
DOCUMENTED_SUPPORTED = (
    CapabilityOperation.UPLOAD_FULL_VIDEO,
    CapabilityOperation.UPLOAD_SHORT,
    CapabilityOperation.STATUS,
    CapabilityOperation.READBACK,
    CapabilityOperation.INSIGHTS,
)

CREATOR_ACCOUNT_REF = "acct:instagram-creator"


def _adapter(accounts: dict | None = None) -> InstagramAdapter:
    return InstagramAdapter(
        FixtureInstagramTransport(
            clock=FakeClock(T0),
            ids=SequentialIds("caps"),
            accounts=default_accounts() if accounts is None else accounts,
        )
    )


def test_adapter_and_transport_satisfy_their_protocols() -> None:
    adapter = _adapter()
    assert isinstance(adapter, PublisherAdapter)
    assert adapter.platform is Platform.INSTAGRAM
    assert isinstance(adapter._transport, InstagramTransport)


def test_fixture_record_is_enabled_with_fixture_evidence() -> None:
    record = _adapter().capability(DEFAULT_ACCOUNT_REF)
    assert record.enabled is True
    assert record.account_type == "BUSINESS"
    assert record.provider_route == caps.PROVIDER_ROUTE
    assert record.verified_at is not None
    assert record.platform is Platform.INSTAGRAM
    sources = {evidence.source for evidence in record.evidence}
    assert EvidenceSource.FAKE_FIXTURE in sources
    assert EvidenceSource.OFFICIAL_DOCUMENTATION in sources
    # every documentation ref is dated (frozen snapshot)
    for ref in record.evidence:
        if ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION:
            assert RESEARCH_AS_OF in ref.ref


def test_capability_id_is_deterministic_per_account() -> None:
    adapter = _adapter()
    first = adapter.capability(DEFAULT_ACCOUNT_REF)
    second = adapter.capability(DEFAULT_ACCOUNT_REF)
    assert first.capability_id == second.capability_id
    assert first.capability_id == caps.capability_id_for(DEFAULT_ACCOUNT_REF)


def test_declaration_truth_no_disclosure_surface_on_this_platform() -> None:
    """THE core honesty pin: no documented API disclosure surface."""
    record = _adapter().capability(DEFAULT_ACCOUNT_REF)
    assert record.support(CapabilityOperation.AI_DISCLOSURE) is CapabilitySupport.UNSUPPORTED
    assert record.supported_disclosures == []


def test_no_operation_claims_supported_tested() -> None:
    record = _adapter().capability(DEFAULT_ACCOUNT_REF)
    tested = [
        op
        for op, support in record.operations.items()
        if support is CapabilitySupport.SUPPORTED_TESTED
    ]
    assert tested == []


def test_documented_operations_snapshot() -> None:
    record = _adapter().capability(DEFAULT_ACCOUNT_REF)
    for op in DOCUMENTED_SUPPORTED:
        assert record.support(op) is CapabilitySupport.SUPPORTED_DOCUMENTED, op
    for op in DOCUMENTED_UNSUPPORTED:
        assert record.support(op) is CapabilitySupport.UNSUPPORTED, op
    assert record.support(CapabilityOperation.SPONSOR_DISCLOSURE) is CapabilitySupport.UNKNOWN


def test_documented_limits_carry_the_route_ceilings() -> None:
    limits = _adapter().capability(DEFAULT_ACCOUNT_REF).limits
    assert limits.max_duration_ms == caps.FEED_VIDEO_MAX_DURATION_MS == 3_600_000
    assert limits.min_duration_ms == caps.FEED_VIDEO_MIN_DURATION_MS == 3_000
    assert limits.daily_post_quota == caps.MAX_DAILY_POSTS == 50
    # the reels ceiling is enforced by the routing rules, asserted there
    assert caps.REELS_MAX_DURATION_MS == 900_000


def test_personal_account_record_is_disabled() -> None:
    record = _adapter().capability(PERSONAL_ACCOUNT_REF)
    assert record.account_type == "PERSONAL"
    assert record.enabled is False  # a personal route cannot publish at all


def test_creator_account_is_professional() -> None:
    accounts = {
        **default_accounts(),
        CREATOR_ACCOUNT_REF: InstagramAccount(
            account_ref=CREATOR_ACCOUNT_REF,
            account_type=InstagramAccountType.MEDIA_CREATOR,
            username="microdrama.creator",
        ),
    }
    record = _adapter(accounts).capability(CREATOR_ACCOUNT_REF)
    assert record.account_type == "MEDIA_CREATOR"
    assert record.enabled is True


def test_unknown_account_defaults_to_the_professional_mock() -> None:
    record = _adapter().capability("acct:instagram-unregistered")
    assert record.account_type == "BUSINESS"
    assert record.enabled is True


def test_documented_default_record_is_disabled_until_t032() -> None:
    record = caps.documented_capability_record(
        account_ref=DEFAULT_ACCOUNT_REF, account_type="BUSINESS"
    )
    assert record.enabled is False
    assert record.verified_at is None
    assert record.evidence  # documentation refs still present
    assert all(
        evidence.source is EvidenceSource.OFFICIAL_DOCUMENTATION for evidence in record.evidence
    )


def test_factory_offline_returns_the_fixture_variant() -> None:
    adapter = build_instagram_adapter(Settings())
    assert isinstance(adapter._transport, FixtureInstagramTransport)
    record = adapter.capability(DEFAULT_ACCOUNT_REF)
    assert record.enabled is True


def test_factory_non_mock_returns_the_live_refusing_adapter() -> None:
    adapter = build_instagram_adapter(Settings(execution_mode=ExecutionMode.PRODUCTION))
    with pytest.raises(Exception, match="T032"):
        adapter.capability(DEFAULT_ACCOUNT_REF)  # capability needs a live account query


def test_factory_non_mock_refuses_custom_transports() -> None:
    transport = FixtureInstagramTransport(clock=FakeClock(T0), ids=SequentialIds("caps-x"))
    with pytest.raises(Exception, match="T032"):
        build_instagram_adapter(
            Settings(execution_mode=ExecutionMode.CONTROLLED_ACCOUNT_TEST),
            transport=transport,
        )

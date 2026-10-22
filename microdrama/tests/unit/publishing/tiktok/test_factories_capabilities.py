"""T022 capability snapshot and factories: documentation-only truth, mock-guarded fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tiktok_support import TikTokWorld

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    EvidenceSource,
    ExecutionMode,
)
from microdrama.publishing.tiktok import (
    DIRECT_POST_DOCUMENTED_OPERATIONS,
    INBOX_DOCUMENTED_OPERATIONS,
    build_tiktok_adapter,
    documented_tiktok_adapter,
    fixture_tiktok_adapter,
)
from microdrama.publishing.tiktok.capabilities import AS_OF, capability_id_for
from microdrama.testing.fakes.common import FakeClock, SequentialIds

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_no_operation_is_ever_claimed_tested() -> None:
    """Documentation alone can never label an operation SUPPORTED_TESTED (that is T032)."""
    for table in (DIRECT_POST_DOCUMENTED_OPERATIONS, INBOX_DOCUMENTED_OPERATIONS):
        for support in table.values():
            assert support is not CapabilitySupport.SUPPORTED_TESTED


def test_direct_post_documented_support_and_absences() -> None:
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.UPLOAD_FULL_VIDEO]
        is CapabilitySupport.SUPPORTED_DOCUMENTED
    )
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.UPLOAD_SHORT]
        is CapabilitySupport.SUPPORTED_DOCUMENTED
    )
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.STATUS]
        is CapabilitySupport.SUPPORTED_DOCUMENTED
    )
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.AI_DISCLOSURE]
        is CapabilitySupport.SUPPORTED_DOCUMENTED
    )
    # no documented schedule field; no documented metadata update endpoint;
    # readback (disclosure visibility through the API) is honestly UNKNOWN
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.SCHEDULE]
        is CapabilitySupport.UNSUPPORTED
    )
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.METADATA_UPDATE]
        is CapabilitySupport.UNSUPPORTED
    )
    assert (
        DIRECT_POST_DOCUMENTED_OPERATIONS[CapabilityOperation.READBACK] is CapabilitySupport.UNKNOWN
    )


def test_inbox_documented_uploads_stay_unsupported() -> None:
    assert (
        INBOX_DOCUMENTED_OPERATIONS[CapabilityOperation.UPLOAD_FULL_VIDEO]
        is CapabilitySupport.UNSUPPORTED
    )
    assert (
        INBOX_DOCUMENTED_OPERATIONS[CapabilityOperation.UPLOAD_SHORT]
        is CapabilitySupport.UNSUPPORTED
    )


def test_documented_adapter_is_disabled_with_documentation_evidence_only() -> None:
    adapter = documented_tiktok_adapter()
    record = adapter.capability("acct:tiktok-main")
    assert record.enabled is False
    assert record.verified_at is None
    assert record.evidence
    assert all(ref.source is EvidenceSource.OFFICIAL_DOCUMENTATION for ref in record.evidence)
    assert all(AS_OF in ref.ref for ref in record.evidence)
    assert record.evidence_is_fake_only is False


def test_documented_adapter_transport_refuses_until_t032() -> None:
    from types import SimpleNamespace

    adapter = documented_tiktok_adapter()
    duck_command = SimpleNamespace(
        client_token="tok", slot=SimpleNamespace(account_ref="acct:tiktok-main")
    )
    with pytest.raises(Exception) as refused:  # noqa: B017 - PolicyDenied until T032
        adapter.submit(duck_command, None)
    assert "T032" in str(refused.value)


def test_capability_ids_are_stable_per_account_and_route() -> None:
    direct = capability_id_for("acct:tiktok-main", "tiktok-direct-post")
    inbox = capability_id_for("acct:tiktok-main", "tiktok-inbox-upload")
    assert direct == capability_id_for("acct:tiktok-main", "tiktok-direct-post")
    assert direct != inbox


def test_fixture_factory_builds_an_enabled_mock_record() -> None:
    settings = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
    adapter = fixture_tiktok_adapter(settings, clock=FakeClock(T0), ids=SequentialIds("tiktok"))
    record = adapter.capability("acct:tiktok-main")
    assert record.enabled is True
    assert record.verified_at is not None
    assert any(ref.source is EvidenceSource.FAKE_FIXTURE for ref in record.evidence)
    assert record.evidence_is_fake_only is False  # documentation refs stand next to it


def test_fixture_factory_refuses_to_build_outside_offline_mock() -> None:
    production = Settings(execution_mode=ExecutionMode.PRODUCTION)
    with pytest.raises(Exception) as denied:  # noqa: B017 - EffectDenied guard
        fixture_tiktok_adapter(production, clock=FakeClock(T0), ids=SequentialIds("tiktok"))
    assert "OFFLINE_MOCK" in str(denied.value)


def test_build_dispatches_on_execution_mode() -> None:
    offline = Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
    adapter = build_tiktok_adapter(offline, clock=FakeClock(T0), ids=SequentialIds("tiktok"))
    assert adapter.capability("acct:tiktok-main").enabled is True

    live = build_tiktok_adapter(Settings(execution_mode=ExecutionMode.PRODUCTION))
    assert live.capability("acct:tiktok-main").enabled is False
    from types import SimpleNamespace

    duck_command = SimpleNamespace(
        client_token="tok", slot=SimpleNamespace(account_ref="acct:tiktok-main")
    )
    with pytest.raises(Exception) as refused:  # noqa: B017 - refusing live stub
        live.submit(duck_command, None)
    assert "T032" in str(refused.value)


def test_world_adapter_is_the_fixture_variant_in_mock_mode(world: TikTokWorld) -> None:
    from microdrama.contracts.enums import Platform

    record = world.tiktok.capability("acct:tiktok-main")
    assert record.enabled is True
    assert any(ref.source is EvidenceSource.FAKE_FIXTURE for ref in record.evidence)
    # the service drives the TIKTOK platform only through this lane's adapter
    assert world.adapters[Platform.TIKTOK] is world.tiktok

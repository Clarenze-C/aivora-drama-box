"""T045 R10 (G11): quote attestation fields and the both-ways evidence cross-check.

Red-first: ``RunpodQuoteAttestation`` had no quote id, currency, persistent-volume size,
maximum storage exposure or provider account label, so no cross-check against
``RunpodQuoteEvidence`` was possible and a lease claim could not record the account a
Pod's buckets must be attributed to.

Every mismatch must deny before any transport call: the fixture transport records each
call and the tests assert it stayed empty.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rendering_support import RenderWorld

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.providers import PodCreateRequest
from microdrama.persistence import Database
from microdrama.pipeline.live_world import RunpodQuoteEvidence
from microdrama.rendering.leases import PodLeaseConfig
from microdrama.rendering.runpod_transport import (
    RunpodQuoteAttestation,
    RunpodRestProvider,
)

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
IMAGE = "registry.example/comfy@sha256:" + "a" * 64
ACCOUNT = "acct:runpod-t031"


class _RecordingTransport:
    """Fails the test if the live provider ever reaches HTTP."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, *, headers: Any, body: bytes | None = None) -> Any:
        self.calls.append((method, url))
        raise AssertionError(f"transport must not be called during R10 denials: {method} {url}")


def _attestation(**overrides: Any) -> RunpodQuoteAttestation:
    values: dict[str, Any] = dict(
        namespace="a1b2c3d4",
        quote_id="quote-t031-current",
        currency="USD",
        provider_account_ref=ACCOUNT,
        quote_micro_usd_per_hour=900_000,
        quote_as_of=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        container_disk_gb=1,
        container_storage_micro_usd_per_gb_month=100_000,
        persistent_volume_gb=5,
        persistent_storage_micro_usd_per_gb_month=200_000,
        max_storage_exposure_micro_usd=1_200_000,
        pinned_image=IMAGE,
        allowed_gpu_types=frozenset({"NVIDIA A40"}),
        host_ram_gb_by_gpu={"NVIDIA A40": 64},
        rights_evidence_id="rights-evidence-t031",
        preset_evidence_id="preset-evidence-t031",
        activation_enabled=True,
    )
    values.update(overrides)
    return RunpodQuoteAttestation(**values)


def _evidence(attestation: RunpodQuoteAttestation, **overrides: Any) -> RunpodQuoteEvidence:
    values: dict[str, Any] = dict(
        quote_id=attestation.quote_id,
        currency=attestation.currency,
        captured_at=attestation.quote_as_of,
        expires_at=attestation.expires_at,
        compute_micro_usd_per_hour=attestation.quote_micro_usd_per_hour,
        container_disk_gb=attestation.container_disk_gb,
        container_storage_micro_usd_per_gb_month=attestation.container_storage_micro_usd_per_gb_month,
        persistent_volume_gb=attestation.persistent_volume_gb,
        persistent_storage_micro_usd_per_gb_month=attestation.persistent_storage_micro_usd_per_gb_month,
        max_storage_exposure_micro_usd=attestation.max_storage_exposure_micro_usd,
        allowed_gpu_types=attestation.allowed_gpu_types,
        host_ram_gb_by_gpu=dict(attestation.host_ram_gb_by_gpu),
        maximum_runtime_ms=60_000,
        maximum_exposure_micro_usd=2_000_000,
    )
    values.update(overrides)
    return RunpodQuoteEvidence(**values)


def _provider(transport: _RecordingTransport) -> RunpodRestProvider:
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    return RunpodRestProvider(
        settings,
        credential_ref="credref:runpod-test",
        credential_resolver=lambda _ref: "fixture-secret",
        attestation=_attestation(),
        now=lambda: NOW,
        reservation_guard=lambda _request, _attestation: None,
        cleanup_guard=lambda _operation, _pod_id: None,
        transport=transport,
    )


def _create_request(*, volume_gb: int = 5) -> PodCreateRequest:
    return PodCreateRequest(
        client_token="token-r10",
        name="md-a1b2c3d4-" + "0" * 32,
        owned_tag="microdrama-owned:a1b2c3d4",
        gpu_type_allowlist=("NVIDIA A40",),
        max_hourly_price_micro_usd=900_000,
        min_host_ram_gb=32,
        container_image=IMAGE,
        volume_gb=volume_gb,
    )


# --- attestation-level refusals (no evidence, no transport) --------------------------


def test_attestation_refuses_a_non_usd_quote_currency() -> None:
    with pytest.raises(ValueError, match="USD"):
        _attestation(currency="EUR")


def test_attestation_refuses_a_malformed_provider_account_label() -> None:
    with pytest.raises(ValueError, match="account"):
        _attestation(provider_account_ref="not-an-account-ref")


def test_attestation_refuses_a_missing_quote_id_and_non_positive_exposure() -> None:
    with pytest.raises(ValueError, match="quote id"):
        _attestation(quote_id="")
    with pytest.raises(ValueError, match="storage exposure"):
        _attestation(max_storage_exposure_micro_usd=0)


# --- both-ways cross-checks against the operator evidence ---------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quote_id", "quote-someone-else"),
        ("currency", "EUR"),
        ("persistent_volume_gb", 50),
        ("max_storage_exposure_micro_usd", 999_999),
    ],
)
def test_every_quote_field_mismatch_denies_both_ways(field: str, value: Any) -> None:
    attestation = _attestation()
    mismatched = _evidence(attestation, **{field: value})
    with pytest.raises(PolicyDenied, match="quote evidence"):
        mismatched.check(now=NOW, attestation=attestation)


def test_non_usd_evidence_currency_is_denied_on_its_own() -> None:
    attestation = _attestation()  # attestation is USD-only by construction
    with pytest.raises(PolicyDenied, match="USD"):
        _evidence(attestation, currency="THB").check(now=NOW, attestation=attestation)


def test_storage_exposure_ceiling_must_cover_the_quoted_storage() -> None:
    attestation = _attestation(max_storage_exposure_micro_usd=1)
    evidence = _evidence(attestation, max_storage_exposure_micro_usd=1)
    with pytest.raises(PolicyDenied, match="storage exposure"):
        evidence.check(now=NOW, attestation=attestation)


def test_a_matching_quote_pair_passes_the_cross_check() -> None:
    attestation = _attestation()
    _evidence(attestation).check(now=NOW, attestation=attestation)


# --- provider-side use of the attested fields ----------------------------------------


def test_create_refuses_a_volume_above_the_attested_persistent_volume() -> None:
    transport = _RecordingTransport()
    provider = _provider(transport)
    with pytest.raises(PolicyDenied, match="persistent volume"):
        provider.create_pod(_create_request(volume_gb=6))
    assert transport.calls == []


# --- the claim writes the provider account label (R10) -------------------------------


def test_claim_records_the_provider_account_ref_on_the_lease(db: Database) -> None:
    from dataclasses import replace

    config = PodLeaseConfig.for_mock()
    assert config.provider_account_ref is None
    world = RenderWorld(db, config=replace(config, provider_account_ref="acct:runpod-r10"))
    episode = world.episode()
    handle = world.claim(episode, "t045-r10-account-ref")
    row = world.lease_row(handle.lease.lease_id)
    assert row["provider_account_ref"] == "acct:runpod-r10"


def test_mock_claims_leave_the_provider_account_ref_null(db: Database) -> None:
    world = RenderWorld(db)
    episode = world.episode()
    handle = world.claim(episode, "t045-r10-no-account")
    assert world.lease_row(handle.lease.lease_id)["provider_account_ref"] is None

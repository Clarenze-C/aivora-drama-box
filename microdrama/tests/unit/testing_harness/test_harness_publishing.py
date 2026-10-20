"""Publisher fake: dedupe, scripted failures, reconciliation, capability rules, readback limits."""

from __future__ import annotations

import pytest

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
    Provenance,
    ReleaseState,
)
from microdrama.contracts.errors import NeedsReconciliation, RateLimited
from microdrama.contracts.examples import publication_command
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.providers import PublisherAdapter
from microdrama.contracts.release import PostMetadata, PublicationCommand
from microdrama.testing.fakes import FakeClock, FakePublisherAdapter, PublishScenario, SequentialIds
from microdrama.testing.media import make_clip


@pytest.fixture
def media(tmp_path) -> tuple[object, str]:
    path = make_clip(tmp_path / "master.mp4", duration_ms=1_000, with_audio=True)
    return path, file_sha256(str(path))


def _command(sha: str, token: str = "pub-token-1") -> PublicationCommand:
    base = publication_command().model_dump(mode="python")
    base.update(asset_sha256=sha, client_token=token)
    return PublicationCommand(**base)


def _adapter(
    clock: FakeClock, ids: SequentialIds, *steps: PublishScenario, **kwargs
) -> FakePublisherAdapter:
    return FakePublisherAdapter(Platform.YOUTUBE, clock=clock, ids=ids, scenarios=steps, **kwargs)


def test_fake_satisfies_publisher_protocol(clock, ids) -> None:
    assert isinstance(_adapter(clock, ids), PublisherAdapter)


def test_accepted_flow_moves_to_verified_with_an_invalid_tld_url(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids)
    command = _command(sha)
    submitted = adapter.submit(command, path)
    assert submitted.state is ReleaseState.SUBMITTED
    processing = adapter.status(command, submitted.external_id)  # type: ignore[arg-type]
    assert processing.state is ReleaseState.PROCESSING
    verified = adapter.status(command, submitted.external_id)  # type: ignore[arg-type]
    assert verified.state is ReleaseState.PUBLISHED_VERIFIED
    assert verified.url is not None and verified.url.startswith("https://youtube.fake.invalid/")
    assert verified.provenance is Provenance.FAKE_SYNTHETIC


def test_repeated_client_token_returns_the_same_post(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids)
    command = _command(sha)
    first = adapter.submit(command, path)
    second = adapter.submit(command, path)
    assert first == second
    assert len(adapter.calls) == 2 and adapter.calls[1].scenario == "REPLAYED"


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        (PublishScenario.DENIED_PERMISSION, "PERMISSION_DENIED"),
        (PublishScenario.TOKEN_EXPIRED, "TOKEN_EXPIRED"),
    ],
)
def test_scripted_failures_are_non_transient_failed_results(
    clock, ids, media, scenario, code
) -> None:
    path, sha = media
    adapter = _adapter(clock, ids, scenario)
    result = adapter.submit(_command(sha), path)
    assert result.state is ReleaseState.FAILED
    assert result.error_code == code
    assert result.transient is False
    assert adapter.reconcile(_command(sha)).found is False


def test_rate_limit_raises_with_retry_and_creates_nothing(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids, PublishScenario.RATE_LIMITED)
    with pytest.raises(RateLimited) as info:
        adapter.submit(_command(sha), path)
    assert info.value.transient is True
    assert info.value.details["retry_after_ms"] == 60_000
    assert adapter.reconcile(_command(sha)).found is False


def test_timeout_after_creation_is_found_by_reconcile(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids, PublishScenario.TIMEOUT_CREATED)
    command = _command(sha)
    with pytest.raises(NeedsReconciliation):
        adapter.submit(command, path)
    reconciled = adapter.reconcile(command)
    assert reconciled.found is True
    assert reconciled.result is not None and reconciled.result.external_id


def test_timeout_without_creation_reconciles_to_not_found(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids, PublishScenario.TIMEOUT_NOT_CREATED)
    command = _command(sha)
    with pytest.raises(NeedsReconciliation):
        adapter.submit(command, path)
    assert adapter.reconcile(command).found is False


def test_unsupported_ai_disclosure_fails_before_anything_is_created(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(
        clock, ids, operations={CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNSUPPORTED}
    )
    command = _command(sha)
    result = adapter.submit(command, path)
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "UNSUPPORTED_DISCLOSURE"
    assert adapter.reconcile(command).found is False


def test_wrong_asset_hash_fails_without_creating_a_post(clock, ids, media) -> None:
    path, _ = media
    adapter = _adapter(clock, ids)
    command = _command("a" * 64)
    result = adapter.submit(command, path)
    assert result.error_code == "ASSET_HASH_MISMATCH"
    assert adapter.reconcile(command).found is False


def test_capability_is_fixture_evidence_and_reports_disclosures(clock, ids) -> None:
    adapter = _adapter(clock, ids)
    record = adapter.capability("acct:fake-main")
    assert record.evidence_is_fake_only is True
    assert all(e.source is EvidenceSource.FAKE_FIXTURE for e in record.evidence)
    assert record.enabled is True
    assert DisclosureKind.AI_GENERATED_CONTENT in record.supported_disclosures
    unknown = _adapter(clock, ids, operations={}).capability("acct:fake-main")
    assert DisclosureKind.AI_GENERATED_CONTENT not in unknown.supported_disclosures


def test_readback_leaves_unverified_fields_visible(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids)
    command = _command(sha)
    external = adapter.submit(command, path).external_id
    adapter.status(command, external)  # type: ignore[arg-type]
    adapter.status(command, external)  # type: ignore[arg-type]
    readback = adapter.readback("acct:fake-main", external)  # type: ignore[arg-type]
    assert readback.visible is True
    assert "privacy" in readback.unverified_fields
    assert readback.provenance is Provenance.FAKE_SYNTHETIC


def test_metadata_updates_are_versioned_and_not_yet_verified(clock, ids, media) -> None:
    path, sha = media
    adapter = _adapter(clock, ids)
    command = _command(sha)
    external = adapter.submit(command, path).external_id
    metadata = PostMetadata(locale="th-TH", title="ปรับชื่อใหม่", disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
                            catalog_version=2)  # fmt: skip
    result = adapter.update_metadata("acct:fake-main", external, metadata)  # type: ignore[arg-type]
    assert result.unverified_fields == ["title"]
    assert len(adapter.metadata_versions[external]) == 1  # type: ignore[index]


def test_platform_label_is_used_in_every_fake_url(clock, ids) -> None:
    adapter = FakePublisherAdapter(Platform.TIKTOK, clock=clock, ids=ids)
    assert adapter.provider_route == "fake-tiktok-adapter"
    assert adapter.capability("acct:fake-tt").provider_route == "fake-tiktok-adapter"

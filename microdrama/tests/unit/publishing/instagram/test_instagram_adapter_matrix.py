"""Adapter-level scenario matrix (T023): the frozen T020 provider response set.

Every platform outcome the service freezes is exercised directly against the
adapter: ACCEPTED, DENIED_PERMISSION, TOKEN_EXPIRED, RATE_LIMITED (with
retry_after_ms), TIMEOUT_CREATED / TIMEOUT_NOT_CREATED (ambiguous submits,
resolved by reconcile), plus the replayed-submit dedupe by client_token and the
professional-account refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from instagram_lane_support import PERSONAL_ACCOUNT_REF, ig_command

from microdrama.contracts.errors import NeedsReconciliation, NotFound, RateLimited
from microdrama.contracts.release import PublicationCommand
from microdrama.publishing.instagram import InstagramAdapter
from microdrama.publishing.instagram.transport import (
    FixtureInstagramTransport,
    InstagramScenario,
    instagram_container_id,
)


def _submit(adapter: InstagramAdapter, command: PublicationCommand, media: tuple[Path, str]):
    return adapter.submit(command, media[0])


def test_accepted_creates_a_reels_container_for_a_promo_cut(
    adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    command = ig_command(media)
    result = _submit(adapter, command, media)
    assert result.state.value == "SUBMITTED"
    assert result.external_id == instagram_container_id(command.client_token)
    fixture = adapter._transport.containers[result.external_id]
    assert fixture.request.media_type.value == "REELS"
    assert fixture.request.caption == f"{command.metadata.caption} #thaidrama #shortseries"


def test_denied_permission_fails_non_transient(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    transport.queue_scenarios(InstagramScenario.DENIED_PERMISSION)
    result = _submit(adapter, ig_command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "PERMISSION_DENIED"
    assert result.transient is False
    # the wire was hit (a scenario step was consumed) but nothing was created
    assert [call.method for call in transport.calls] == ["account", "create_container"]
    assert transport.create_container_calls == 0


def test_token_expired_fails_non_transient(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    transport.queue_scenarios(InstagramScenario.TOKEN_EXPIRED)
    result = _submit(adapter, ig_command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "TOKEN_EXPIRED"


def test_rate_limited_raises_with_retry_after_ms(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    transport.queue_scenarios(InstagramScenario.RATE_LIMITED)
    with pytest.raises(RateLimited) as limited:
        _submit(adapter, ig_command(media), media)
    assert limited.value.details["retry_after_ms"] == 60_000
    assert transport.create_container_calls == 0  # refused before anything was created
    assert [call.method for call in transport.calls] == ["account", "create_container"]


def test_timeout_created_is_ambiguous_then_reconciled_found(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    command = ig_command(media)
    transport.queue_scenarios(InstagramScenario.TIMEOUT_CREATED)
    with pytest.raises(NeedsReconciliation):
        _submit(adapter, command, media)
    assert transport.create_container_calls == 1  # the container exists

    outcome = adapter.reconcile(command)
    assert outcome.found is True
    assert outcome.result is not None
    assert outcome.result.state.value == "SUBMITTED"
    assert outcome.result.external_id == instagram_container_id(command.client_token)


def test_timeout_not_created_is_ambiguous_then_reconciled_absent(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    command = ig_command(media)
    transport.queue_scenarios(InstagramScenario.TIMEOUT_NOT_CREATED)
    with pytest.raises(NeedsReconciliation):
        _submit(adapter, command, media)
    assert transport.create_container_calls == 0  # nothing was created

    outcome = adapter.reconcile(command)
    assert outcome.found is False
    assert outcome.result is None


def test_replayed_submit_is_deduplicated_by_client_token(
    adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    command = ig_command(media)
    first = _submit(adapter, command, media)
    second = _submit(adapter, command, media)  # the job ran twice
    assert second.external_id == first.external_id
    assert second.state == first.state
    assert adapter._transport.create_container_calls == 1  # exactly one container


def test_non_professional_account_is_refused(
    adapter: InstagramAdapter, media: tuple[Path, str]
) -> None:
    """Documented platform rule: personal accounts cannot use the publishing API."""
    command = ig_command(media, account_ref=PERSONAL_ACCOUNT_REF)
    result = _submit(adapter, command, media)
    assert result.state.value == "FAILED"
    assert result.error_code == "NOT_PROFESSIONAL_ACCOUNT"
    assert adapter._transport.create_container_calls == 0  # never reached the wire


def test_missing_media_file_is_not_found(adapter: InstagramAdapter, tmp_path: Path) -> None:
    from instagram_lane_support import write_media

    media = write_media(tmp_path)
    command = ig_command(media)
    media[0].unlink()
    with pytest.raises(NotFound):
        adapter.submit(command, media[0])


def test_media_hash_mismatch_fails(adapter: InstagramAdapter, media: tuple[Path, str]) -> None:
    command = ig_command(media)
    tampered = command.model_copy(update={"asset_sha256": "f" * 64})
    result = adapter.submit(tampered, media[0])
    assert result.state.value == "FAILED"
    assert result.error_code == "ASSET_HASH_MISMATCH"
    assert adapter._transport.create_container_calls == 0

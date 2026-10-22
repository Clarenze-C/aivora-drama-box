"""T022 adapter-level scenario matrix: the frozen provider-response shapes on TikTok."""

from __future__ import annotations

import pytest
from tiktok_support import AdapterBench

from microdrama.contracts.errors import NeedsReconciliation, RateLimited
from microdrama.contracts.providers import PublisherAdapter
from microdrama.publishing.tiktok.transport import (
    TikTokScenario,
    fixture_publish_id,
)


def test_adapter_satisfies_the_publisher_protocol(bench: AdapterBench) -> None:
    assert isinstance(bench.adapter, PublisherAdapter)
    assert bench.adapter.platform.value == "TIKTOK"
    assert bench.adapter.provider_route == "tiktok-direct-post"


def test_accepted_creates_a_deterministic_post(bench: AdapterBench) -> None:
    media = bench.media()
    command = bench.command(media)
    result = bench.adapter.submit(command, media)
    assert result.state.value == "SUBMITTED"
    assert result.external_id == fixture_publish_id(command.client_token)
    assert result.url is None
    assert result.provenance.value == "FAKE_SYNTHETIC"


def test_denied_permission_fails_typed(bench: AdapterBench) -> None:
    media = bench.media()
    bench.transport.queue_scenarios(TikTokScenario.DENIED_PERMISSION)
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "PERMISSION_DENIED"
    assert result.transient is False
    assert bench.transport.publish_ids == ()


def test_token_expired_fails_typed(bench: AdapterBench) -> None:
    media = bench.media()
    bench.transport.queue_scenarios(TikTokScenario.TOKEN_EXPIRED)
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "TOKEN_EXPIRED"
    assert bench.transport.publish_ids == ()


def test_rate_limited_raises_with_retry_after_ms(bench: AdapterBench) -> None:
    media = bench.media()
    bench.transport.queue_scenarios(TikTokScenario.RATE_LIMITED)
    with pytest.raises(RateLimited) as limited:
        bench.adapter.submit(bench.command(media), media)
    assert limited.value.details["retry_after_ms"] == 60_000
    assert bench.transport.publish_ids == ()


def test_timeout_created_is_ambiguous_then_found_by_token(bench: AdapterBench) -> None:
    media = bench.media()
    bench.transport.queue_scenarios(TikTokScenario.TIMEOUT_CREATED)
    command = bench.command(media)
    with pytest.raises(NeedsReconciliation):
        bench.adapter.submit(command, media)
    outcome = bench.adapter.reconcile(command)
    assert outcome.found is True
    assert outcome.result is not None
    assert outcome.result.external_id == fixture_publish_id(command.client_token)


def test_timeout_not_created_is_ambiguous_then_proven_absent(bench: AdapterBench) -> None:
    media = bench.media()
    bench.transport.queue_scenarios(TikTokScenario.TIMEOUT_NOT_CREATED)
    command = bench.command(media)
    with pytest.raises(NeedsReconciliation):
        bench.adapter.submit(command, media)
    assert bench.adapter.reconcile(command).found is False


def test_replayed_submit_is_deduplicated_by_client_token(bench: AdapterBench) -> None:
    media = bench.media()
    command = bench.command(media)
    first = bench.adapter.submit(command, media)
    second = bench.adapter.submit(command, media)

    assert second.external_id == first.external_id
    inits = [call for call in bench.transport.calls if call.method == "direct_post_init"]
    assert len(inits) == 1  # the replay consumed no scenario step, created nothing
    assert bench.transport.publish_ids == (first.external_id,)


def test_media_hash_mismatch_is_a_typed_refusal(bench: AdapterBench) -> None:
    media = bench.media()
    command = bench.command(media)
    tampered = bench.media(b"tampered bytes entirely")
    result = bench.adapter.submit(command, tampered)
    assert result.state.value == "FAILED"
    assert result.error_code == "ASSET_HASH_MISMATCH"
    assert bench.transport.publish_ids == ()

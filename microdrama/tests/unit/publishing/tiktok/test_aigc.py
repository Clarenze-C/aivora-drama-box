"""T022 AIGC declaration: AI_GENERATED_CONTENT maps to the documented AIGC field."""

from __future__ import annotations

from microdrama.contracts.enums import CapabilityOperation, CapabilitySupport, DisclosureKind


def test_declared_aigc_reaches_the_init_payload(bench) -> None:
    media = bench.media()
    command = bench.command(media)  # declares AI_GENERATED_CONTENT by default
    assert DisclosureKind.AI_GENERATED_CONTENT in command.metadata.disclosures
    bench.adapter.submit(command, media)

    request = bench.transport.init_requests[-1]
    assert request.aigc_label is True
    assert request.client_token == command.client_token


def test_supported_disclosures_follow_the_capability(bench) -> None:
    record = bench.adapter.capability("acct:tiktok-main")
    assert record.support(CapabilityOperation.AI_DISCLOSURE).value == "SUPPORTED_DOCUMENTED"
    assert record.supported_disclosures == [DisclosureKind.AI_GENERATED_CONTENT]


def test_unsupported_aigc_is_a_typed_refusal(tmp_path) -> None:
    from tiktok_support import AdapterBench

    bench = AdapterBench(
        tmp_path,
        operations_override={CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNSUPPORTED},
    )
    media = bench.media()
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "UNSUPPORTED_DISCLOSURE"
    assert bench.transport.publish_ids == ()
    assert bench.adapter.capability("acct:tiktok-main").supported_disclosures == []


def test_unknown_aigc_support_is_a_typed_refusal(tmp_path) -> None:
    from tiktok_support import AdapterBench

    bench = AdapterBench(
        tmp_path,
        operations_override={CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.UNKNOWN},
    )
    media = bench.media()
    result = bench.adapter.submit(bench.command(media), media)
    assert result.state.value == "FAILED"
    assert result.error_code == "DISCLOSURE_UNVERIFIED"
    assert bench.transport.publish_ids == ()


def test_readback_proves_the_declared_aigc_label(bench) -> None:
    media = bench.media()
    command = bench.command(media)
    submitted = bench.adapter.submit(command, media)
    bench.adapter.status(command, submitted.external_id)  # PROCESSING
    bench.adapter.status(command, submitted.external_id)  # PUBLISH_COMPLETE
    readback = bench.adapter.readback(command.slot.account_ref, submitted.external_id)
    assert readback.visible is True
    assert DisclosureKind.AI_GENERATED_CONTENT in readback.disclosures_visible
    from urllib.parse import urlparse

    assert readback.links
    assert urlparse(readback.links[0]).hostname.endswith(".invalid")  # fake host only
    assert not ({"visibility", "disclosures"} & set(readback.unverified_fields))

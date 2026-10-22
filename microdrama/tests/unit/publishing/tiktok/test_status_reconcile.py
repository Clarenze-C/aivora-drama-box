"""T022 status/reconcile/readback progression and typed publish failures."""

from __future__ import annotations

import pytest
from tiktok_support import AdapterBench

from microdrama.contracts.errors import NotFound


def _submitted(bench: AdapterBench):
    media = bench.media()
    command = bench.command(media)
    result = bench.adapter.submit(command, media)
    assert result.state.value == "SUBMITTED"
    return command, result.external_id


def test_status_progresses_processing_then_verified(bench: AdapterBench) -> None:
    command, publish_id = _submitted(bench)
    first = bench.adapter.status(command, publish_id)
    assert first.state.value == "PROCESSING"
    second = bench.adapter.status(command, publish_id)
    assert second.state.value == "PUBLISHED_VERIFIED"
    assert second.url is not None
    assert second.url.startswith("https://")
    assert second.url.split("//", 1)[1].split("/", 1)[0].endswith(".invalid")
    assert second.verified_fields  # a verified result names what it verified
    # completion is sticky: further fetches keep reporting it
    third = bench.adapter.status(command, publish_id)
    assert third.state.value == "PUBLISHED_VERIFIED"


def test_status_failure_keeps_a_typed_fail_code(bench: AdapterBench) -> None:
    command, publish_id = _submitted(bench)
    bench.transport.fail_next_status("VIDEO_REFUSED")
    failed = bench.adapter.status(command, publish_id)
    assert failed.state.value == "FAILED"
    assert failed.error_code == "VIDEO_REFUSED"
    assert failed.transient is False
    # the failure is sticky, never silently recovered
    again = bench.adapter.status(command, publish_id)
    assert again.state.value == "FAILED"


def test_undocumented_fail_code_collapses_to_the_typed_generic(bench: AdapterBench) -> None:
    command, publish_id = _submitted(bench)
    bench.transport.fail_next_status("SOME_UNDOCUMENTED_CODE")
    failed = bench.adapter.status(command, publish_id)
    assert failed.state.value == "FAILED"
    assert failed.error_code == "PUBLISH_FAILED"


def test_status_for_an_unknown_publish_id_is_not_found(bench: AdapterBench) -> None:
    command, _publish_id = _submitted(bench)
    with pytest.raises(NotFound):
        bench.adapter.status(command, "tiktok-doesnotexist")


def test_readback_before_completion_reports_a_gap_not_a_verification(bench: AdapterBench) -> None:
    command, publish_id = _submitted(bench)
    readback = bench.adapter.readback(command.slot.account_ref, publish_id)
    assert readback.visible is None
    assert readback.disclosures_visible == []
    assert {"visibility", "disclosures"} <= set(readback.unverified_fields)


def test_reconcile_reports_a_completed_post_with_proof(bench: AdapterBench) -> None:
    command, publish_id = _submitted(bench)
    bench.adapter.status(command, publish_id)  # PROCESSING
    bench.adapter.status(command, publish_id)  # PUBLISH_COMPLETE
    outcome = bench.adapter.reconcile(command)
    assert outcome.found is True
    assert outcome.result is not None
    assert outcome.result.state.value == "PUBLISHED_VERIFIED"
    assert outcome.result.external_id == publish_id
    assert outcome.result.verified_fields


def test_update_metadata_is_a_typed_refusal(bench: AdapterBench) -> None:
    """The documented surface has no metadata-update endpoint for this route."""
    command, publish_id = _submitted(bench)
    result = bench.adapter.update_metadata(command.slot.account_ref, publish_id, command.metadata)
    assert result.state.value == "FAILED"
    assert result.error_code == "METADATA_UPDATE_UNSUPPORTED"

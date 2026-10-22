"""Container / process / publish flow (T023): the documented state machine.

submit creates the container (SUBMITTED, container id); status observes
in_progress (PROCESSING) then finished (publish + PUBLISHED_VERIFIED with the
media id and a permalink); container error/expired fail the slot. The readback
truth is pinned: the media node is visible but disclosure-blind —
``disclosures_visible`` is empty and "disclosures" stays unverified, so an AI
disclosure can never be verified through this API.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from instagram_lane_support import ig_command

from microdrama.contracts.enums import ReleaseState
from microdrama.contracts.errors import NotFound
from microdrama.contracts.release import PublicationCommand
from microdrama.publishing.instagram.adapter import InstagramAdapter
from microdrama.publishing.instagram.transport import (
    FixtureInstagramTransport,
    InstagramScenario,
    instagram_media_id,
)


def _publish(adapter: InstagramAdapter, command: PublicationCommand, media: tuple) -> str:
    submitted = adapter.submit(command, media[0])
    assert submitted.state is ReleaseState.SUBMITTED
    processing = adapter.status(command, submitted.external_id)
    assert processing.state is ReleaseState.PROCESSING
    verified = adapter.status(command, submitted.external_id)
    assert verified.state is ReleaseState.PUBLISHED_VERIFIED
    return verified.external_id


def test_container_progression_submitted_processing_published(
    adapter: InstagramAdapter, media: tuple
) -> None:
    command = ig_command(media)
    submitted = adapter.submit(command, media[0])
    assert submitted.state is ReleaseState.SUBMITTED
    assert submitted.external_id.startswith("igc-")

    processing = adapter.status(command, submitted.external_id)
    assert processing.state is ReleaseState.PROCESSING
    assert processing.external_id == submitted.external_id
    assert adapter._transport.publish_calls == 0  # publish waits for finished

    verified = adapter.status(command, submitted.external_id)
    assert verified.state is ReleaseState.PUBLISHED_VERIFIED
    # the external id becomes the PUBLISHED media id, not the container id
    assert verified.external_id == instagram_media_id(command.client_token)
    assert urlparse(verified.url).hostname.endswith(".invalid")  # fake host only
    assert adapter._transport.publish_calls == 1


def test_repoll_is_idempotent_by_either_id(adapter: InstagramAdapter, media: tuple) -> None:
    command = ig_command(media)
    media_id = _publish(adapter, command, media)
    container_id = adapter._container_by_token[command.client_token]

    by_media = adapter.status(command, media_id)  # service stores the media id
    by_container = adapter.status(command, container_id)  # pre-verification re-poll
    assert by_media.state is ReleaseState.PUBLISHED_VERIFIED
    assert by_container.state is ReleaseState.PUBLISHED_VERIFIED
    assert adapter._transport.publish_calls == 1  # no second media_publish


def test_readback_is_visible_but_disclosure_blind(adapter: InstagramAdapter, media: tuple) -> None:
    """Declaration truth: the readback can never verify an AI disclosure."""
    command = ig_command(media)
    media_id = _publish(adapter, command, media)

    readback = adapter.readback(command.slot.account_ref, media_id)
    assert readback.visible is True
    assert readback.disclosures_visible == []  # no documented disclosure field
    assert "disclosures" in readback.unverified_fields
    assert readback.links == [f"https://instagram.invalid/p/{media_id}"]


def test_readback_of_an_unknown_media_is_not_found(adapter: InstagramAdapter, media: tuple) -> None:
    with pytest.raises(NotFound):
        adapter.readback("acct:instagram-main", "igm-doesnotexist")


def test_container_error_fails_the_slot(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple
) -> None:
    transport.queue_scenarios(InstagramScenario.ACCEPTED, InstagramScenario.CONTAINER_ERROR)
    command = ig_command(media)
    submitted = adapter.submit(command, media[0])
    failed = adapter.status(command, submitted.external_id)
    assert failed.state is ReleaseState.FAILED
    assert failed.error_code == "CONTAINER_ERROR"
    assert failed.transient is False
    assert transport.publish_calls == 0


def test_container_expired_fails_the_slot(
    transport: FixtureInstagramTransport, adapter: InstagramAdapter, media: tuple
) -> None:
    transport.queue_scenarios(InstagramScenario.ACCEPTED, InstagramScenario.CONTAINER_EXPIRED)
    command = ig_command(media)
    submitted = adapter.submit(command, media[0])
    failed = adapter.status(command, submitted.external_id)
    assert failed.state is ReleaseState.FAILED
    assert failed.error_code == "CONTAINER_EXPIRED"


def test_update_metadata_refuses_video_caption_edits(
    adapter: InstagramAdapter, media: tuple
) -> None:
    """Documented constraint: caption update via POST /{ig-media-id} is image-only."""
    command = ig_command(media)
    media_id = _publish(adapter, command, media)
    result = adapter.update_metadata(command.slot.account_ref, media_id, command.metadata)
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "METADATA_UPDATE_IMAGE_ONLY"


def test_update_metadata_of_an_unpublished_container_is_not_found(
    adapter: InstagramAdapter, media: tuple
) -> None:
    command = ig_command(media)
    submitted = adapter.submit(command, media[0])
    with pytest.raises(NotFound):
        adapter.update_metadata(command.slot.account_ref, submitted.external_id, command.metadata)


def test_insights_documented_edge_after_publish(adapter: InstagramAdapter, media: tuple) -> None:
    command = ig_command(media)
    media_id = _publish(adapter, command, media)

    metrics = adapter.insights(command.slot.account_ref, media_id)
    assert "impressions" in metrics
    assert "reach" in metrics

    submitted_container = ig_command(media, token="ig-token-insights-container")
    container_id = adapter.submit(submitted_container, media[0]).external_id
    with pytest.raises(NotFound):  # insights is a media edge, not a container edge
        adapter.insights(command.slot.account_ref, container_id)

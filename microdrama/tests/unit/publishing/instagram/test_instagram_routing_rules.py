"""Routing and documented platform rules (T023): REELS vs feed VIDEO, ceilings.

PROMO_CUT/HOOK route to REELS containers; FULL_EPISODE/PART route to feed VIDEO
containers. The documented duration ceilings are enforced per route (Reels 3s-15
minutes, feed video 3s-60 minutes) against the media duration the caller can
supply; with no duration knowledge the adapter proceeds and the platform's
container processing stays the documented backstop. The caption is one string with
the hashtags appended and must fit the documented 2,200-character limit.
"""

from __future__ import annotations

import uuid

import pytest
from instagram_lane_support import ig_command, write_media

from microdrama.contracts.enums import DisclosureKind, ReleaseState, SlotKind
from microdrama.contracts.release import PostMetadata
from microdrama.publishing.instagram.adapter import (
    CONTAINER_KIND_BY_SLOT,
    InstagramAdapter,
    caption_text,
)
from microdrama.publishing.instagram.capabilities import (
    CAPTION_MAX_CHARS,
    FEED_VIDEO_MAX_DURATION_MS,
    REELS_MAX_DURATION_MS,
)
from microdrama.publishing.instagram.transport import ContainerKind


@pytest.mark.parametrize(
    ("slot_kind", "expected_kind"),
    [
        (SlotKind.PROMO_CUT, ContainerKind.REELS),
        (SlotKind.HOOK, ContainerKind.REELS),
        (SlotKind.FULL_EPISODE, ContainerKind.VIDEO),
        (SlotKind.PART, ContainerKind.VIDEO),
    ],
)
def test_slot_kind_routes_to_the_documented_container(
    adapter: InstagramAdapter, media: tuple, slot_kind: SlotKind, expected_kind: ContainerKind
) -> None:
    command = ig_command(media, slot_kind=slot_kind)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.SUBMITTED
    fixture = adapter._transport.containers[result.external_id]
    assert fixture.request.media_type is expected_kind
    assert CONTAINER_KIND_BY_SLOT[slot_kind] is expected_kind


def _duration_adapter(transport, asset_id: uuid.UUID, duration_ms: int) -> InstagramAdapter:
    return InstagramAdapter(
        transport, duration_lookup=lambda lookup_id: duration_ms if lookup_id == asset_id else None
    )


def test_reels_over_the_documented_ceiling_is_refused(transport, media: tuple) -> None:
    command = ig_command(media, slot_kind=SlotKind.PROMO_CUT, asset_id=uuid.uuid4())
    adapter = _duration_adapter(transport, command.asset_id, REELS_MAX_DURATION_MS + 1)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "DURATION_EXCEEDS_ROUTE_LIMIT"
    assert transport.create_container_calls == 0


def test_reels_exactly_at_the_ceiling_is_accepted(transport, media: tuple) -> None:
    command = ig_command(media, slot_kind=SlotKind.PROMO_CUT)
    adapter = _duration_adapter(transport, command.asset_id, REELS_MAX_DURATION_MS)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.SUBMITTED


def test_feed_video_over_the_documented_ceiling_is_refused(transport, media: tuple) -> None:
    command = ig_command(media, slot_kind=SlotKind.FULL_EPISODE)
    adapter = _duration_adapter(transport, command.asset_id, FEED_VIDEO_MAX_DURATION_MS + 1)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "DURATION_EXCEEDS_ROUTE_LIMIT"


def test_media_below_the_three_second_minimum_is_refused(transport, media: tuple) -> None:
    command = ig_command(media, slot_kind=SlotKind.FULL_EPISODE)
    adapter = _duration_adapter(transport, command.asset_id, 2_999)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "DURATION_BELOW_MINIMUM"


def test_unknown_duration_proceeds_with_container_processing_as_backstop(
    adapter: InstagramAdapter, media: tuple
) -> None:
    command = ig_command(media, slot_kind=SlotKind.FULL_EPISODE)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.SUBMITTED  # the platform validates server-side


def test_caption_with_hashtags_over_the_documented_limit_is_refused(
    adapter: InstagramAdapter, media: tuple
) -> None:
    caption = "ก" * (CAPTION_MAX_CHARS - 20)
    command = ig_command(media, caption=caption, hashtags=("#thaidrama", "#shortseries"))
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.FAILED
    assert result.error_code == "CAPTION_TOO_LONG"
    assert adapter._transport.create_container_calls == 0


def test_caption_exactly_at_the_limit_is_accepted(adapter: InstagramAdapter, media: tuple) -> None:
    hashtags = ("#thaidrama", "#shortseries")
    caption = "a" * (CAPTION_MAX_CHARS - len(" #thaidrama #shortseries"))
    command = ig_command(media, caption=caption, hashtags=hashtags)
    result = adapter.submit(command, media[0])
    assert result.state is ReleaseState.SUBMITTED
    fixture = adapter._transport.containers[result.external_id]
    assert len(fixture.request.caption) == CAPTION_MAX_CHARS


def test_caption_text_appends_hashtags() -> None:
    metadata = PostMetadata(
        locale="th-TH",
        title="t",
        caption="แคปชัน",
        hashtags=["#หนึ่ง", "#สอง"],
        disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
        catalog_version=1,
    )
    assert caption_text(metadata) == "แคปชัน #หนึ่ง #สอง"
    assert caption_text(metadata.model_copy(update={"caption": "", "hashtags": []})) == ""


def test_two_commands_share_no_dedupe_collision(
    adapter: InstagramAdapter, media: tuple, tmp_path
) -> None:
    """Different client tokens produce different containers (fixture determinism)."""
    media2 = write_media(tmp_path, data=b"\x00\x00\x00\x18ftypmp42" + b"second-media-" * 64)
    first = adapter.submit(ig_command(media, token="tok-a"), media[0])
    second = adapter.submit(ig_command(media2, token="tok-b"), media2[0])
    assert first.external_id != second.external_id

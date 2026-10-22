"""Explicit full/short route selection and platform rules (T024).

The core truth of this packet: FULL_EPISODE/PART go to the Page videos edge
(resumable upload, title/description, scheduled_publish_time) and PROMO_CUT/HOOK go
to the Reels container flow (description only, no schedule parameter) — chosen
strictly from slot_kind, never inferred across surfaces. Readback declaration truth
and metadata edits are pinned here too.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from facebook_support import (
    FUTURE_SCHEDULE,
    NO_FULL_VIDEO_OPS,
    T0,
    TEST_AI_CAPABLE_OPS,
    fb_command,
    fb_metadata,
    fixture_adapter,
    media_file,
)

from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.errors import NotFound, PolicyDenied
from microdrama.publishing.facebook.adapter import FacebookPageAdapter
from microdrama.publishing.facebook.capabilities import FB_PAGE_ACCOUNT, FB_PAGE_OPERATIONS
from microdrama.testing.fakes.common import FakeClock, SequentialIds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def media(tmp_path: Path):
    return media_file(tmp_path)


def adapter(clock: FakeClock, operations=None) -> FacebookPageAdapter:
    return fixture_adapter(clock, SequentialIds("fb-routes"), operations=operations)


def methods_of(fb: FacebookPageAdapter) -> list[str]:
    return [call.method for call in fb.transport.calls]


class TestExplicitRouteSelection:
    def test_full_episode_and_part_use_the_videos_edge(self, clock, media) -> None:
        for kind in (SlotKind.FULL_EPISODE, SlotKind.PART):
            fb = adapter(clock, TEST_AI_CAPABLE_OPS)
            result = fb.submit(fb_command(slot_kind=kind, token=f"tok-{kind.value}", asset=media), media[0])  # fmt: skip
            assert result.external_id.startswith("fb-full-"), kind
            assert "start_page_video_upload" in methods_of(fb)
            assert "finish_page_video_upload" in methods_of(fb)
            assert "start_reel_container" not in methods_of(fb)  # no inference
            assert "publish_reel" not in methods_of(fb)

    def test_promo_cut_and_hook_use_the_reels_edge(self, clock, media) -> None:
        for kind in (SlotKind.PROMO_CUT, SlotKind.HOOK):
            fb = adapter(clock, TEST_AI_CAPABLE_OPS)
            result = fb.submit(fb_command(slot_kind=kind, token=f"tok-{kind.value}", asset=media), media[0])  # fmt: skip
            assert result.external_id.startswith("fb-reel-"), kind
            assert "start_reel_container" in methods_of(fb)
            assert "publish_reel" in methods_of(fb)
            assert "start_page_video_upload" not in methods_of(fb)  # no inference
            assert "finish_page_video_upload" not in methods_of(fb)

    def test_resumable_upload_transfers_contiguous_chunks_then_finishes(self, clock, media) -> None:
        """The documented upload_phase protocol: every chunk transferred before finish."""
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        result = fb.submit(fb_command(token="tok-chunks", asset=media), media[0])
        transfers = [c for c in fb.transport.calls if c.method == "transfer_chunk"]
        assert len(transfers) >= 2  # the fixture chunks at 64 bytes in tests
        offsets = [int(c.key.split(":")[1]) for c in transfers]
        assert offsets == sorted(offsets)
        assert offsets[0] == 0
        assert methods_of(fb)[-1] == "finish_page_video_upload"
        assert result.state is ReleaseState.SUBMITTED

    def test_full_video_carries_title_and_description(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        result = fb.submit(fb_command(token="tok-title", asset=media), media[0])
        fields = fb.transport.get_video(external_id=result.external_id)
        assert fields.title == "ตอนที่ ๒"
        assert fields.description == "Fon negotiates for time."

    def test_reel_carries_description_only(self, clock, media) -> None:
        """The documented Reels surface has a description parameter; there is no title."""
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        result = fb.submit(
            fb_command(slot_kind=SlotKind.PROMO_CUT, token="tok-reel-desc", asset=media),
            media[0],
        )
        fields = fb.transport.get_video(external_id=result.external_id)
        assert fields.title is None
        assert fields.description == "Fon negotiates for time."

    def test_upload_operation_not_supported_is_a_policy_refusal(self, clock, media) -> None:
        """No speculative capability: an unsupported upload op refuses before transport."""
        fb = adapter(clock, NO_FULL_VIDEO_OPS)
        with pytest.raises(PolicyDenied, match="UPLOAD_FULL_VIDEO is UNKNOWN"):
            fb.submit(fb_command(token="tok-nofull", asset=media), media[0])
        # nothing but the dedupe lookup ever reached the platform surface
        assert all(call.method == "find_post_by_token" for call in fb.transport.calls)


class TestScheduleTruth:
    def test_future_window_short_slot_is_refused(self, clock, media) -> None:
        """The Reels surface documents no scheduled-publish parameter: refused, not
        silently published now."""
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        command = fb_command(
            slot_kind=SlotKind.PROMO_CUT, token="tok-future-reel", asset=media,
            schedule=FUTURE_SCHEDULE,
        )  # fmt: skip
        result = fb.submit(command, media[0])
        assert result.state is ReleaseState.FAILED
        assert result.error_code == "SCHEDULE_UNSUPPORTED_ON_REELS"
        assert fb.reconcile(command).found is False  # nothing was created

    def test_future_window_full_video_uses_the_documented_schedule(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        command = fb_command(token="tok-sched", asset=media, schedule=FUTURE_SCHEDULE)
        result = fb.submit(command, media[0])
        assert result.state is ReleaseState.PROCESSING  # scheduled at the platform
        status = fb.status(command, result.external_id)
        assert status.state is ReleaseState.PROCESSING  # window has not opened yet
        assert fb.transport.video_status(external_id=result.external_id).scheduled_publish_at \
            == FUTURE_SCHEDULE.utc_instant  # fmt: skip

        clock.advance(seconds=4 * 3600)  # past 22:30 Bangkok
        published = fb.status(command, result.external_id)
        assert published.state is ReleaseState.PUBLISHED_VERIFIED
        assert urlparse(published.url).hostname.endswith(".invalid")

    def test_schedule_withdrawn_refuses_future_full_video(self, clock, media) -> None:
        no_schedule_with_disclosure = {
            **TEST_AI_CAPABLE_OPS,
            CapabilityOperation.SCHEDULE: CapabilitySupport.UNKNOWN,
        }
        fb = adapter(clock, no_schedule_with_disclosure)
        command = fb_command(token="tok-nosched", asset=media, schedule=FUTURE_SCHEDULE)
        result = fb.submit(command, media[0])
        assert result.state is ReleaseState.FAILED
        assert result.error_code == "SCHEDULE_UNSUPPORTED"

    def test_past_window_publishes_immediately(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        result = fb.submit(fb_command(token="tok-past", asset=media), media[0])
        assert fb.transport.video_status(external_id=result.external_id).scheduled_publish_at \
            is None  # fmt: skip


class TestMediaIntegrity:
    def test_missing_media_file_raises_not_found(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        with pytest.raises(NotFound, match="media file"):
            fb.submit(fb_command(token="tok-missing", asset=media), Path("/nonexistent/m.mp4"))

    def test_media_hash_mismatch_fails_without_reaching_the_platform(
        self, clock, media, tmp_path: Path
    ) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        other = media_file(tmp_path, data=b"different bytes entirely")
        command = fb_command(token="tok-mismatch", asset=media)
        result = fb.submit(command, other[0])
        assert result.state is ReleaseState.FAILED
        assert result.error_code == "ASSET_HASH_MISMATCH"
        assert fb.reconcile(command).found is False


class TestReadbackDeclarationTruth:
    def test_published_video_cannot_prove_the_ai_label(self, clock, media) -> None:
        """Two adapters, one platform: the capable variant publishes; the SHIPPED
        snapshot's readback still reports no visible disclosure — the surface cannot
        read back a label it can never set. This is the documented outcome."""
        capable = adapter(clock, TEST_AI_CAPABLE_OPS)
        result = capable.submit(fb_command(token="tok-truth-rb", asset=media), media[0])
        external_id = result.external_id
        capable.status(fb_command(token="tok-truth-rb", asset=media), external_id)
        capable.status(fb_command(token="tok-truth-rb", asset=media), external_id)

        shipped = FacebookPageAdapter(
            clock=clock,
            transport=capable.transport,
            operations=FB_PAGE_OPERATIONS,
            fixture=True,
        )
        readback = shipped.readback(FB_PAGE_ACCOUNT, external_id)
        assert readback.visible is True
        assert readback.disclosures_visible == []
        assert "disclosures" in readback.unverified_fields
        assert readback.provenance.value == "FAKE_SYNTHETIC"

    def test_capable_variant_readback_verifies_the_disclosure(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        command = fb_command(token="tok-rb-ok", asset=media)
        result = fb.submit(command, media[0])
        fb.status(command, result.external_id)
        fb.status(command, result.external_id)
        readback = fb.readback(FB_PAGE_ACCOUNT, result.external_id)
        assert readback.visible is True
        assert [kind.value for kind in readback.disclosures_visible] == ["AI_GENERATED_CONTENT"]
        assert "disclosures" not in readback.unverified_fields
        assert all(urlparse(link).hostname.endswith(".invalid") for link in readback.links)

    def test_unpublished_video_reports_unknown_visibility(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        command = fb_command(token="tok-rb-unpub", asset=media)
        result = fb.submit(command, media[0])
        readback = fb.readback(FB_PAGE_ACCOUNT, result.external_id)
        assert readback.visible is None
        assert readback.disclosures_visible == []
        assert readback.links == []


class TestMetadataEdits:
    def test_update_metadata_edits_title_and_description(self, clock, media) -> None:
        fb = adapter(clock, TEST_AI_CAPABLE_OPS)
        command = fb_command(token="tok-meta", asset=media)
        result = fb.submit(command, media[0])
        updated = fb.update_metadata(
            FB_PAGE_ACCOUNT,
            result.external_id,
            fb_metadata(title="ตอนที่ ๒ (แก้ไข)"),
        )
        assert updated.external_id == result.external_id
        fields = fb.transport.get_video(external_id=result.external_id)
        assert fields.title == "ตอนที่ ๒ (แก้ไข)"
        assert fb.metadata_versions[result.external_id]

    def test_update_metadata_refused_when_not_supported(self, clock, media) -> None:
        no_metadata_ops = {
            **TEST_AI_CAPABLE_OPS,
            CapabilityOperation.METADATA_UPDATE: CapabilitySupport.UNKNOWN,
        }
        fb = adapter(clock, no_metadata_ops)
        command = fb_command(token="tok-meta-no", asset=media)
        result = fb.submit(command, media[0])
        with pytest.raises(PolicyDenied, match="METADATA_UPDATE"):
            fb.update_metadata(FB_PAGE_ACCOUNT, result.external_id, fb_metadata())

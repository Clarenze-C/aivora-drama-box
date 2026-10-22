"""Shared builders for the Facebook adapter tests (T024).

``FacebookWorld`` subclasses the lane's ``PublishingWorld`` (never edited): the
Facebook adapter replaces ``world.adapters[Platform.FACEBOOK]`` and the service is
rebuilt over the new adapter map, so submit/poll/reconcile/release_view run through
the REAL ``PublishingService`` exactly like production lanes.

Variant operations maps here are TEST-ONLY overrides of the frozen snapshot. They
exist to exercise transport mechanics the honest default cannot reach (see
``TEST_AI_CAPABLE_OPS``); they are never a shipped capability and never leave tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from publishing_support import PublishingWorld

from microdrama.config import Settings
from microdrama.contracts.enums import (
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    Platform,
    SlotKind,
)
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.release import PostMetadata, PublicationCommand, ReleaseSlotKey
from microdrama.persistence import Database
from microdrama.publishing.facebook.adapter import FacebookPageAdapter
from microdrama.publishing.facebook.capabilities import (
    FB_PAGE_ACCOUNT,
    FB_PAGE_OPERATIONS,
)
from microdrama.publishing.facebook.transport import (
    FacebookScenario,
    FixtureFacebookTransport,
)
from microdrama.publishing.service import PublishingService
from microdrama.testing.fakes.common import FakeClock, SequentialIds

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

#: TEST-ONLY variant: models a Page surface that CAN set and read back the AI label,
#: so the upload/processing/publish/verify mechanics are reachable end to end. The
#: shipped snapshot keeps AI_DISCLOSURE UNKNOWN (no documented field, 2026-10) and
#: every AI-disclosed slot HELDs with UNSUPPORTED_DISCLOSURE.
TEST_AI_CAPABLE_OPS: dict[CapabilityOperation, CapabilitySupport] = {
    **FB_PAGE_OPERATIONS,
    CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_DOCUMENTED,
}

#: TEST-ONLY variant proving the no-speculative-capability gate: a record that does
#: not grant UPLOAD_FULL_VIDEO must HELD FULL_EPISODE slots (CAPABILITY_UNAVAILABLE).
NO_FULL_VIDEO_OPS: dict[CapabilityOperation, CapabilitySupport] = {
    **FB_PAGE_OPERATIONS,
    CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.UNKNOWN,
}

#: TEST-ONLY variant with the documented schedule parameter withdrawn.
NO_SCHEDULE_OPS: dict[CapabilityOperation, CapabilitySupport] = {
    **FB_PAGE_OPERATIONS,
    CapabilityOperation.SCHEDULE: CapabilitySupport.UNKNOWN,
}

PAST_SCHEDULE = ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 18, 0))
FUTURE_SCHEDULE = ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 22, 30))

MEDIA_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"facebook-t024-media-" * 16


def media_file(tmp: Path, data: bytes = MEDIA_BYTES) -> tuple[Path, str]:
    path = tmp / f"media-{uuid.uuid4().hex}.mp4"
    path.write_bytes(data)
    return path, file_sha256(str(path))


def fixture_adapter(
    clock: FakeClock,
    ids: SequentialIds,
    *,
    operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
    scenarios: tuple[FacebookScenario, ...] = (),
    enabled: bool | None = None,
    page_accounts: dict[str, str] | None = None,
    chunk_size: int = 64,
) -> FacebookPageAdapter:
    """A Facebook adapter over the fixture transport (offline; small chunks in tests)."""
    return FacebookPageAdapter(
        clock=clock,
        transport=FixtureFacebookTransport(
            clock=clock, ids=ids, scenarios=scenarios, chunk_size=chunk_size
        ),
        operations=operations,
        page_accounts=page_accounts,
        fixture=True,
        enabled=enabled,
    )


def fb_metadata(
    *, disclosures: list[DisclosureKind] | None = None, title: str = "ตอนที่ ๒"
) -> PostMetadata:
    return PostMetadata(
        locale="th-TH",
        title=title,
        caption="ร้านข้าวมันไก่ของแม่",
        description="Fon negotiates for time.",
        hashtags=["#thaidrama"],
        disclosures=disclosures or [DisclosureKind.AI_GENERATED_CONTENT],
        catalog_version=1,
    )


def fb_command(
    *,
    slot_kind: SlotKind = SlotKind.FULL_EPISODE,
    token: str,
    asset: tuple[Path, str],
    schedule: ScheduleInstant | None = None,
    disclosures: list[DisclosureKind] | None = None,
    account_ref: str = FB_PAGE_ACCOUNT,
) -> PublicationCommand:
    """A standalone PublicationCommand for adapter-level (serviceless) tests."""
    key = ReleaseSlotKey(
        series_id=uuid.uuid4(),
        episode_id=uuid.uuid4(),
        part=0 if slot_kind in (SlotKind.FULL_EPISODE,) else 1,
        locale="th-TH",
        platform=Platform.FACEBOOK,
        account_ref=account_ref,
        release_slot="full" if slot_kind is SlotKind.FULL_EPISODE else "promo",
    )
    return PublicationCommand(
        command_id=uuid.uuid4(),
        release_package_id=uuid.uuid4(),
        release_package_hash="0" * 64,
        approval_event_id=uuid.uuid4(),
        slot=key,
        slot_kind=slot_kind,
        asset_id=uuid.uuid4(),
        asset_sha256=asset[1],
        metadata=fb_metadata(disclosures=disclosures),
        metadata_version_id=uuid.uuid4(),
        schedule=schedule or PAST_SCHEDULE,
        capability_id=uuid.uuid4(),
        capability_version=1,
        client_token=token,
    )


class FacebookWorld(PublishingWorld):
    """``PublishingWorld`` with the T024 adapter registered for Platform.FACEBOOK."""

    def __init__(
        self,
        db: Database,
        tmp: Path,
        settings: Settings,
        *,
        operations: dict[CapabilityOperation, CapabilitySupport] | None = None,
        scenarios: tuple[FacebookScenario, ...] = (),
        enabled: bool | None = None,
    ) -> None:
        super().__init__(db, tmp, settings)
        self.facebook = fixture_adapter(
            self.clock, self.ids, operations=operations, scenarios=scenarios, enabled=enabled
        )
        self.adapters[Platform.FACEBOOK] = self.facebook
        self.service = PublishingService(self.db, self.clock, self.ids, self.adapters, self.store)

    def fb_slot_plan(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        asset: tuple[uuid.UUID, str],
        slot: str = "full",
        slot_kind: SlotKind = SlotKind.FULL_EPISODE,
        required: bool = True,
        schedule: ScheduleInstant | None = None,
    ) -> Any:
        return self.slot_plan(
            season_id=season_id,
            episode_id=episode_id,
            asset=asset,
            slot=slot,
            platform=Platform.FACEBOOK,
            account_ref=FB_PAGE_ACCOUNT,
            slot_kind=slot_kind,
            required=required,
            schedule=schedule,
        )


#: The mock Page account the fixture adapter publishes as.
FB_ACCOUNT = FB_PAGE_ACCOUNT

__all__ = [
    "FB_ACCOUNT",
    "FUTURE_SCHEDULE",
    "MEDIA_BYTES",
    "NO_FULL_VIDEO_OPS",
    "NO_SCHEDULE_OPS",
    "PAST_SCHEDULE",
    "TEST_AI_CAPABLE_OPS",
    "T0",
    "FacebookWorld",
    "fb_command",
    "fb_metadata",
    "fixture_adapter",
    "media_file",
]

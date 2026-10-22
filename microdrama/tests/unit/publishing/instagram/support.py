"""Builders for the Instagram (T023) tests: a PublishingWorld subclass + commands.

``InstagramWorld`` subclasses the T020 ``PublishingWorld`` (never edits it): the
INSTAGRAM adapter registration is replaced with this lane's adapter and the service
is rebuilt, so capability pinning through ``slot_plan`` matches by construction.
Adapter-level tests use ``ig_command`` + ``write_media`` with no database at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from publishing_support import PublishingWorld

from microdrama.contracts.enums import DisclosureKind, Platform, SlotKind
from microdrama.contracts.hashing import file_sha256
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.publishing.instagram import InstagramAdapter
from microdrama.publishing.instagram.transport import (
    DEFAULT_ACCOUNT_REF,
    DEFAULT_FIXTURE_ACCOUNTS,
    PERSONAL_ACCOUNT_REF,
    PERSONAL_FIXTURE_ACCOUNT,
    FixtureInstagramTransport,
)
from microdrama.publishing.service import PublishingService

MASTER_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"instagram-lane-media-" * 64


def default_accounts() -> dict[str, Any]:
    """The default professional mock plus the personal-account refusal case."""
    return {
        **DEFAULT_FIXTURE_ACCOUNTS,
        PERSONAL_ACCOUNT_REF: PERSONAL_FIXTURE_ACCOUNT,
    }


def write_media(tmp_path: Path, data: bytes = MASTER_BYTES) -> tuple[Path, str]:
    """A media file on disk plus its pinned sha (adapter submits verify the hash)."""
    path = tmp_path / f"media-{uuid.uuid4().hex}.mp4"
    path.write_bytes(data)
    return path, file_sha256(str(path))


def ig_command(
    media: tuple[Path, str],
    *,
    token: str = "ig-token-1",
    slot_kind: SlotKind = SlotKind.PROMO_CUT,
    account_ref: str = DEFAULT_ACCOUNT_REF,
    caption: str = "ร้านข้าวมันไก่ของแม่ — ตอนต่อไป",
    hashtags: tuple[str, ...] = ("#thaidrama", "#shortseries"),
    asset_id: uuid.UUID | None = None,
) -> PublicationCommand:
    """An adapter-level PublicationCommand for Instagram (no database involved)."""
    _path, sha = media
    return PublicationCommand(
        command_id=uuid.uuid4(),
        release_package_id=uuid.uuid4(),
        release_package_hash="a" * 64,
        approval_event_id=uuid.uuid4(),
        slot=ReleaseSlotKey(
            series_id=uuid.uuid4(),
            episode_id=uuid.uuid4(),
            part=0 if slot_kind is SlotKind.FULL_EPISODE else 1,
            locale="th-TH",
            platform=Platform.INSTAGRAM,
            account_ref=account_ref,
            release_slot="promo",
        ),
        slot_kind=slot_kind,
        asset_id=asset_id or uuid.uuid4(),
        asset_sha256=sha,
        metadata=PostMetadata(
            locale="th-TH",
            title="ตอนที่ ๒ – หนี้ที่แม่ซ่อนไว้",
            caption=caption,
            description="Fon negotiates for time.",
            hashtags=list(hashtags),
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            catalog_version=1,
        ),
        metadata_version_id=uuid.uuid4(),
        schedule=ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 18, 0)),
        capability_id=uuid.uuid4(),
        capability_version=1,
        client_token=token,
    )


class InstagramWorld(PublishingWorld):
    """The T020 world with the INSTAGRAM adapter replaced by this lane's adapter."""

    def __init__(self, db, tmp: Path, settings, *, accounts: dict[str, Any] | None = None):
        super().__init__(db, tmp, settings)
        self.transport = FixtureInstagramTransport(
            clock=self.clock,
            ids=self.ids,
            accounts=accounts if accounts is not None else default_accounts(),
        )
        self.adapter = InstagramAdapter(self.transport)
        self._install(self.adapter)

    def _install(self, adapter: InstagramAdapter) -> None:
        self.adapters[Platform.INSTAGRAM] = adapter
        self.service = PublishingService(self.db, self.clock, self.ids, self.adapters, self.store)

    def bump_instagram_version(self) -> None:
        """Scheduling pinned version N; a bumped record makes it stale."""
        self._install(self.adapter.with_version(self.adapter.version + 1))

    def instagram_scope(
        self,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        master: tuple[uuid.UUID, str],
        *,
        account_ref: str = DEFAULT_ACCOUNT_REF,
        slot_kind: SlotKind = SlotKind.FULL_EPISODE,
        slot: str = "full",
        schedule: ScheduleInstant | None = None,
    ) -> list[ReleaseSlotPlan]:
        """A one-slot Instagram release scope built from this lane's capability."""
        return [
            self.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot=slot,
                platform=Platform.INSTAGRAM,
                account_ref=account_ref,
                slot_kind=slot_kind,
                schedule=schedule,
            )
        ]

    def approved_instagram_episode(
        self, *, account_ref: str = DEFAULT_ACCOUNT_REF, schedule: ScheduleInstant | None = None
    ) -> tuple[uuid.UUID, uuid.UUID, Any, uuid.UUID]:
        """Season + episode + an Instagram-only scope through the REAL Gate 2."""
        return self.approved_episode(
            scope_builder=lambda season_id, episode_id, master: self.instagram_scope(
                season_id,
                episode_id,
                master,
                account_ref=account_ref,
                schedule=schedule,
            )
        )


__all__ = [
    "DEFAULT_ACCOUNT_REF",
    "InstagramWorld",
    "MASTER_BYTES",
    "PERSONAL_ACCOUNT_REF",
    "ig_command",
    "write_media",
]

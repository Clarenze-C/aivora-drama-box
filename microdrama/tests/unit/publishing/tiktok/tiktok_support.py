"""Shared builders for the TikTok adapter tests (T022).

``AdapterBench`` drives the adapter alone (no database): a fixture transport, a
duration probe, deterministic commands and media files. ``TikTokWorld`` subclasses the
T020 ``PublishingWorld`` WITHOUT editing it: the TikTok platform slot is re-pointed at
this lane's adapter and the publishing service is rebuilt over the new adapter map, so
slot plans pin capability records from the TikTok adapter by construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from publishing_support import MASTER_BYTES, T0, PublishingWorld

from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    Platform,
    Provenance,
    SlotKind,
)
from microdrama.contracts.examples import ACCOUNT_TT
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.persistence import register_asset
from microdrama.publishing.service import PublishingService
from microdrama.publishing.tiktok.adapter import (
    FixtureDurationProbe,
    TikTokPublisherAdapter,
)
from microdrama.publishing.tiktok.capabilities import TikTokRoute
from microdrama.publishing.tiktok.transport import (
    DEFAULT_ACCOUNT_SETTINGS,
    FixtureTikTokTransport,
    TikTokAccountSettings,
)
from microdrama.testing.fakes.common import FakeClock, SequentialIds, ensure_mock_mode

FAKE = Provenance.FAKE_SYNTHETIC


def private_account_settings(*, max_video_duration_sec: int = 600) -> TikTokAccountSettings:
    """An account whose settings do not permit direct post (account truth)."""
    return TikTokAccountSettings(
        privacy_level_options=("SELF_ONLY",),
        comment_options=("CLOSE_TO_COMMENT",),
        direct_post_permitted=False,
        max_video_duration_sec=max_video_duration_sec,
    )


def short_account_settings(*, max_video_duration_sec: int = 120) -> TikTokAccountSettings:
    """An eligible account whose real max duration is tighter than the docs' ceiling."""
    return TikTokAccountSettings(
        privacy_level_options=DEFAULT_ACCOUNT_SETTINGS.privacy_level_options,
        comment_options=DEFAULT_ACCOUNT_SETTINGS.comment_options,
        direct_post_permitted=True,
        max_video_duration_sec=max_video_duration_sec,
    )


class AdapterBench:
    """Adapter-level harness: transport + probe + deterministic commands, no database."""

    def __init__(
        self,
        tmp: Path,
        *,
        route: TikTokRoute = TikTokRoute.DIRECT_POST,
        account_settings: dict[str, TikTokAccountSettings] | None = None,
        operations_override: dict[CapabilityOperation, CapabilitySupport] | None = None,
    ) -> None:
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("tiktok-bench")
        self.transport = FixtureTikTokTransport(
            clock=self.clock, ids=self.ids, account_settings=account_settings
        )
        self.probe = FixtureDurationProbe()
        self.adapter = TikTokPublisherAdapter(
            transport=self.transport,
            route=route,
            duration_probe=self.probe,
            operations_override=operations_override,
            clock=self.clock,
        )
        self._tmp = tmp
        self._counter = 0

    def media(self, data: bytes = MASTER_BYTES, *, duration_ms: int | None = None) -> Path:
        self._counter += 1
        path = self._tmp / f"bench-media-{self._counter}.mp4"
        path.write_bytes(data)
        if duration_ms is not None:
            self.probe.by_sha[sha256_hex(data)] = duration_ms
        return path

    def command(
        self,
        media: Path,
        *,
        client_token: str = "tt-bench-token-1",
        disclosures: tuple[DisclosureKind, ...] = (DisclosureKind.AI_GENERATED_CONTENT,),
        slot_kind: SlotKind = SlotKind.FULL_EPISODE,
        account_ref: str = ACCOUNT_TT,
        schedule: ScheduleInstant | None = None,
    ) -> PublicationCommand:
        def uid(name: str) -> UUID:
            return uuid5(NAMESPACE_URL, f"https://microdrama.invalid/tiktok-bench/{name}")

        part = 0 if slot_kind is SlotKind.FULL_EPISODE else 1
        slot = ReleaseSlotKey(
            series_id=uid("series"),
            episode_id=uid("episode"),
            part=part,
            locale="th-TH",
            platform=Platform.TIKTOK,
            account_ref=account_ref,
            release_slot="full" if part == 0 else "cut",
        )
        return PublicationCommand(
            command_id=uid(f"command:{client_token}"),
            release_package_id=uid("package"),
            release_package_hash=sha256_hex(b"bench-package"),
            approval_event_id=uid("approval"),
            slot=slot,
            slot_kind=slot_kind,
            asset_id=uid("asset"),
            asset_sha256=sha256_hex(media.read_bytes()),
            metadata=PostMetadata(
                locale="th-TH",
                title="ตอนที่ ๒ – หนี้ที่แม่ซ่อนไว้",
                caption="ร้านข้าวมันไก่ของแม่",
                description="Fon negotiates for time.",
                hashtags=["#thaidrama"],
                disclosures=list(disclosures),
                catalog_version=1,
            ),
            metadata_version_id=uid(f"metadata-version:{client_token}"),
            schedule=schedule or PublishingWorld.past_schedule(),
            capability_id=uid("capability"),
            capability_version=1,
            client_token=client_token,
        )


class TikTokWorld(PublishingWorld):
    """The T020 publishing world with the TikTok slot driven by the T022 adapter."""

    def __init__(
        self,
        db: Any,
        tmp: Path,
        settings: Any,
        *,
        route: TikTokRoute = TikTokRoute.DIRECT_POST,
        account_settings: dict[str, TikTokAccountSettings] | None = None,
        operations_override: dict[CapabilityOperation, CapabilitySupport] | None = None,
        enabled: bool = True,
        version: int = 1,
    ) -> None:
        ensure_mock_mode(settings)  # fixture variants exist only in OFFLINE_MOCK
        super().__init__(db, tmp, settings)
        self.tiktok_transport = FixtureTikTokTransport(
            clock=self.clock, ids=self.ids, account_settings=account_settings
        )
        self.duration_probe = FixtureDurationProbe()
        self.tiktok = TikTokPublisherAdapter(
            transport=self.tiktok_transport,
            route=route,
            duration_probe=self.duration_probe,
            operations_override=operations_override,
            clock=self.clock,
            enabled=enabled,
            version=version,
        )
        self.adapters[Platform.TIKTOK] = self.tiktok
        self.service = PublishingService(self.db, self.clock, self.ids, self.adapters, self.store)

    # --- tiktok-specific builders ---------------------------------------------------------

    def tiktok_scope(
        self,
        season_id: UUID,
        episode_id: UUID,
        master: tuple[UUID, str],
        *,
        slot: str = "tt-full",
        slot_kind: SlotKind = SlotKind.FULL_EPISODE,
        required: bool = True,
        schedule: ScheduleInstant | None = None,
        disclosures: list[DisclosureKind] | None = None,
        account_ref: str = ACCOUNT_TT,
    ) -> list[ReleaseSlotPlan]:
        return [
            self.slot_plan(
                season_id=season_id,
                episode_id=episode_id,
                asset=master,
                slot=slot,
                platform=Platform.TIKTOK,
                account_ref=account_ref,
                slot_kind=slot_kind,
                required=required,
                schedule=schedule,
                disclosures=disclosures,
            )
        ]

    def asset_with_duration(
        self, season_id: UUID, episode_id: UUID, *, duration_ms: int, data: bytes = MASTER_BYTES
    ) -> tuple[UUID, str]:
        """Register an asset whose measured duration the adapter's probe will report."""
        asset_id = uuid5(NAMESPACE_URL, f"asset:{episode_id}:{duration_ms}")
        key = f"tiktok-tests/{asset_id.hex}.mp4"
        stored = self.store.put_bytes(key, data, media_type="video/mp4")
        with self.db.transaction() as tx:
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.VIDEO,
                    object_key=key,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type="video/mp4",
                    media=MediaInfo(duration_ms=duration_ms, has_video=True, has_audio=True),
                    state=AssetState.ACCEPTED,
                    provenance=FAKE,
                    episode_id=episode_id,
                    season_id=season_id,
                    created_at=self.clock.now(),
                ),
            )
        self.duration_probe.by_sha[stored.sha256] = duration_ms
        return asset_id, stored.sha256

    def approved_tiktok_episode(self, *, scope_builder=None) -> tuple[UUID, UUID, Any, UUID]:
        """approved_episode with a TikTok direct-post slot scope by default."""

        def default_scope(season_id: UUID, episode_id: UUID, master: tuple[UUID, str]):
            return self.tiktok_scope(season_id, episode_id, master)

        return self.approved_episode(scope_builder=scope_builder or default_scope)

    def submit_ready(self, *, scenario: Any = None):
        """Approve + schedule + build the command and job for the first TikTok slot."""
        if scenario is not None:
            self.tiktok_transport.queue_scenarios(scenario)
        _s, episode_id, package, approval = self.approved_tiktok_episode()
        self.schedule(episode_id)
        plan = next(p for p in package.release_scope if p.slot.platform is Platform.TIKTOK)
        command = self.command(plan, package=package, approval_event_id=approval)
        return episode_id, command, self.submit_job(command)


__all__ = [
    "ACCOUNT_TT",
    "AdapterBench",
    "TikTokWorld",
    "private_account_settings",
    "short_account_settings",
]

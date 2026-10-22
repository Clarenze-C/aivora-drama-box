"""T026 test support: the offline membership/DM world.

Everything is driven through the REAL services (catalog, entitlements, budget,
DM delivery) over the T007 fakes and the frozen tables — no stubbed budget, no
fabricated catalog state. Seeded rows are built with the real contracts
(``ReleasePackage.seal``, ``AssetDescriptor``, ``ManagementPolicy``) exactly the
way accepted lanes seed their fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.community.dm import build_dm_delivery_service
from microdrama.config import Settings
from microdrama.contracts.catalog import MemberPrice, MembershipCatalogEntry
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CommunityEventKind,
    DisclosureKind,
    Platform,
    Provenance,
    SlotKind,
)
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.providers import CommunityEventIn
from microdrama.contracts.release import (
    CostSummary,
    MediaRef,
    QASummary,
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import CostPolicy, ManagementPolicy
from microdrama.memberships import build_membership_services, member_media_file
from microdrama.memberships.catalog import FreeDateOwnerDecision
from microdrama.persistence import Database, register_asset
from microdrama.persistence.db import insert_row
from microdrama.testing.fakes.common import FakeClock, SequentialIds
from microdrama.testing.fakes.community import FakeCommunityProvider
from microdrama.testing.fakes.membership import EntitlementScenario
from microdrama.testing.seed import seed_episode, seed_human_session, seed_owner, seed_season

FAKE = Provenance.FAKE_SYNTHETIC
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
ACCOUNT_IG = "acct:ig-members"

KEYWORDS = ("ตอนต่อไป", "next")
PRICE = MemberPrice(amount_micro_usd=3_000_000)  # $3.00/month, integer micro-USD


def bangkok_instant(day: int, hour: int = 19, minute: int = 30) -> ScheduleInstant:
    """A frozen Asia/Bangkok wall-clock instant (the announced-free-date shape)."""
    return ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, day, hour, minute))


class MembershipWorld:
    """One offline membership/DM stack per test."""

    def __init__(
        self,
        db: Database,
        tmp: Path,
        settings: Settings,
        *,
        entitlement_scenarios: tuple[EntitlementScenario, ...] = (),
        metered_micro_usd: int = 1_000_000,
        dm_keywords: tuple[str, ...] = KEYWORDS,
        ids_namespace: str = "memberships",
    ) -> None:
        self.db = db
        self.tmp = tmp
        self.settings = settings
        self.clock = FakeClock(T0)
        self.ids = SequentialIds(ids_namespace)
        self.budget = BudgetService(db, self.clock, self.ids, settings)
        self.services = build_membership_services(
            settings,
            db=db,
            clock=self.clock,
            ids=self.ids,
            budget=self.budget,
            scenarios=entitlement_scenarios,
        )
        self.catalog = self.services.catalog
        self.entitlements = self.services.entitlements
        self.provider = self.services.fake_provider
        self.community = FakeCommunityProvider(
            Platform.INSTAGRAM,
            clock=self.clock,
            ids=self.ids,
            account_ref=ACCOUNT_IG,
            seed_events=False,
        )
        self.policy = ManagementPolicy(
            allowed_actions=frozenset({"PUBLIC_REPLY", "DM_SEND"}),
            dm_keywords=list(dm_keywords),
        )
        self.dm = build_dm_delivery_service(
            db=db,
            clock=self.clock,
            ids=self.ids,
            community=self.community,
            catalog=self.catalog,
            entitlements=self.entitlements,
            budget=self.budget,
            policy=self.policy,
        )
        self._metered_micro_usd = metered_micro_usd

    # --- season / episode / gates -------------------------------------------------------

    def season(self) -> UUID:
        with self.db.transaction() as tx:
            return seed_season(tx, state="SEASON_APPROVED")

    def episode(self, season_id: UUID, *, number: int = 2) -> UUID:
        allocation = dict(CostPolicy().allocation_micro_usd)
        allocation["METERED_MANAGEMENT"] = self._metered_micro_usd
        allocation["RECOVERY_HEADROOM"] += 1_000_000 - self._metered_micro_usd
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, number=number, state="AWAITING_FINAL_REVIEW")
            self.budget.open_episode_account(
                tx,
                season_id=season_id,
                episode_id=episode_id,
                policy=CostPolicy(allocation_micro_usd=allocation),
            )
        return episode_id

    def gate2_approval(self, episode_id: UUID) -> UUID:
        """A real-shaped Gate 2 APPROVE for the episode (idempotent: one per episode)."""
        package = self.release_package(episode_id)
        existing = self._gate2_of(package)
        if existing is not None:
            return existing
        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            approval_id = uuid.uuid4()
            payload = {"episode_id": str(episode_id), "package": str(package.package_id)}
            insert_row(
                tx,
                "approval_events",
                {
                    "id": approval_id,
                    "gate_type": "EPISODE_FINAL",
                    "action": "APPROVE",
                    "entity_type": "episode",
                    "entity_id": episode_id,
                    "expected_revision": 0,
                    "package_hash": package.package_hash,
                    "media_hashes": package.media_hashes,
                    "management_policy_hash": canonical_hash(self.policy),
                    "release_scope_hash": package.release_scope_hash,
                    "actor_owner_id": owner,
                    "actor_session_id": session,
                    "idempotency_key": f"seed-gate2-{approval_id.hex}",
                    "command_hash": canonical_hash(payload),
                },
                returning="id",
            )
        return approval_id

    def release_package(self, episode_id: UUID) -> ReleasePackage:
        """A real-shaped READY release package (idempotent per episode).

        READY with no blockers and caption tracks that are CURRENT + actually
        aligned — exactly what the Gate 2 trigger demands before an APPROVE row
        may exist (migration 0008/0009 hardening).
        """
        existing = self.row(
            "SELECT body FROM release_packages WHERE episode_id = %s AND version = 1",
            (episode_id,),
        )
        if existing is not None:
            return ReleasePackage.model_validate(existing["body"])
        season_row = self._one(
            "SELECT season_id, episode_number FROM episodes WHERE id = %s", (episode_id,)
        )
        asset = self._asset(season_row["season_id"], episode_id)
        caption_id = self._caption_track(episode_id)
        key = ReleaseSlotKey(
            series_id=season_row["season_id"],
            episode_id=episode_id,
            part=0,
            locale="th-TH",
            platform=Platform.YOUTUBE,
            account_ref="acct:youtube-main",
            release_slot="full",
        )
        plan = ReleaseSlotPlan(
            slot=key,
            slot_kind=SlotKind.FULL_EPISODE,
            required=True,
            asset_id=asset.asset_id,
            asset_sha256=asset.sha256,
            schedule=bangkok_instant(28),
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            capability_id=uuid.uuid4(),
            capability_version=1,
        )
        package = ReleasePackage.seal(
            package_id=uuid.uuid4(),
            episode_id=episode_id,
            season_id=season_row["season_id"],
            episode_number=season_row["episode_number"],
            version=1,
            media=[MediaRef(asset_id=asset.asset_id, sha256=asset.sha256, role="master")],
            caption_track_ids=[caption_id],
            release_scope=[plan],
            management_policy_hash=canonical_hash(self.policy),
            qa=QASummary(provenance=FAKE),
            cost=CostSummary(
                episode_cap_micro_usd=10_000_000,
                settled_micro_usd=0,
                accrued_micro_usd=0,
                reserved_outstanding_micro_usd=0,
                remaining_micro_usd=10_000_000,
            ),
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "release_packages",
                {
                    "id": package.package_id,
                    "episode_id": episode_id,
                    "version": 1,
                    "package_hash": package.package_hash,
                    "body": package,
                    "media_hashes": package.media_hashes,
                    "management_policy_hash": canonical_hash(self.policy),
                    "release_scope_hash": package.release_scope_hash,
                    "status": "READY",
                },
            )
        return package

    def _caption_track(self, episode_id: UUID) -> UUID:
        from microdrama.contracts.enums import CaptionTimingSource
        from microdrama.contracts.media import CaptionCue, CaptionTrack

        track_id = uuid.uuid4()
        track = CaptionTrack(
            track_id=track_id,
            episode_id=episode_id,
            version=1,
            locale="th-TH",
            timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
            derived_from_audio_sha256=[sha256_hex(f"audio:{episode_id}".encode())],
            cues=[CaptionCue(cue_id="c1", start_ms=0, end_ms=1_000, text="ทดสอบคำบรรยาย")],
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "caption_tracks",
                {
                    "id": track_id,
                    "episode_id": episode_id,
                    "version": 1,
                    "locale": "th-TH",
                    "timing_source": CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT.value,
                    "body": track,
                    "body_hash": canonical_hash(track),
                    "state": "CURRENT",
                },
            )
        return track_id

    def published_post_url(self, episode_id: UUID, *, url: str | None = None) -> str:
        """A PUBLISHED_VERIFIED platform post URL for the episode (idempotent)."""
        existing = self.row(
            "SELECT url FROM platform_posts WHERE episode_id = %s "
            "AND state = 'PUBLISHED_VERIFIED' ORDER BY created_at LIMIT 1",
            (episode_id,),
        )
        if existing is not None and url is None:
            return existing["url"]
        package = self.release_package(episode_id)
        season_row = self._one("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        asset = self._asset(season_row["season_id"], episode_id)
        approval_id = self._gate2_of(package) or self.gate2_approval(episode_id)
        external_id = f"yt-{sha256_hex(str(episode_id).encode())[:12]}"
        url = url or f"https://watch.fake.invalid/{external_id}"
        slot_key = ReleaseSlotKey(
            series_id=season_row["season_id"],
            episode_id=episode_id,
            part=0,
            locale="th-TH",
            platform=Platform.YOUTUBE,
            account_ref="acct:youtube-main",
            release_slot="full",
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "platform_posts",
                {
                    "id": uuid.uuid4(),
                    "series_id": season_row["season_id"],
                    "episode_id": episode_id,
                    "part": 0,
                    "locale": "th-TH",
                    "platform": Platform.YOUTUBE.value,
                    "account_ref": "acct:youtube-main",
                    "release_slot": "full",
                    "dedupe_key": slot_key.dedupe_key,
                    "slot_kind": SlotKind.FULL_EPISODE.value,
                    "required": True,
                    "release_package_id": package.package_id,
                    "approval_event_id": approval_id,
                    "asset_id": asset.asset_id,
                    "asset_sha256": asset.sha256,
                    "state": "PUBLISHED_VERIFIED",
                    "iana_zone": "Asia/Bangkok",
                    "local_time": "2026-10-28T19:30",
                    "scheduled_utc": bangkok_instant(28).utc_instant,
                    "client_token": f"client-{sha256_hex(str(episode_id).encode())[:16]}",
                    "external_id": external_id,
                    "url": url,
                    "verified_at": self.clock.now(),
                },
            )
        return url

    def _gate2_of(self, package: ReleasePackage) -> UUID | None:
        with self.db.transaction(readonly=True) as tx:
            found = tx.fetchone(
                "SELECT id FROM approval_events WHERE package_hash = %s AND "
                "gate_type = 'EPISODE_FINAL' AND action = 'APPROVE' AND entity_id = %s",
                (package.package_hash, package.episode_id),
            )
        return found["id"] if found else None

    def _asset(self, season_id: UUID, episode_id: UUID) -> AssetDescriptor:
        asset_id = uuid.uuid5(uuid.NAMESPACE_URL, f"asset:{episode_id}")
        existing = self.row("SELECT descriptor FROM assets WHERE id = %s", (asset_id,))
        if existing is not None:
            return AssetDescriptor.model_validate(existing["descriptor"])
        data = b"\x00\x00\x00\x18ftypmp42" + f"membership-{episode_id}".encode() * 32
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=AssetKind.VIDEO,
            object_key=f"membership-tests/{episode_id}.mp4",
            sha256=sha256_hex(data),
            size_bytes=len(data),
            media_type="video/mp4",
            media=MediaInfo(duration_ms=30_000, has_video=True, has_audio=True),
            state=AssetState.ACCEPTED,
            provenance=FAKE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=T0,
        )
        with self.db.transaction() as tx:
            register_asset(tx, descriptor)
        return descriptor

    def _one(self, sql: str, params):
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    # --- membership flows ------------------------------------------------------------------

    def open_early_access(
        self,
        season_id: UUID,
        episode_id: UUID,
        *,
        number: int = 2,
        free_release: ScheduleInstant | None = None,
        price: MemberPrice = PRICE,
        approval_event_id: UUID | None = None,
        owner_decision: FreeDateOwnerDecision | None = None,
    ) -> MembershipCatalogEntry:
        return self.catalog.publish_early_access(
            season_id=season_id,
            episode_id=episode_id,
            episode_number=number,
            provider=self.services.adapter,
            media_path=member_media_file(self.tmp, number),
            approval_event_id=approval_event_id or self.gate2_approval(episode_id),
            price=price,
            free_release=free_release or bangkok_instant(31),
            owner_decision=owner_decision,
        )

    # --- inbound DM events -------------------------------------------------------------------

    def dm_event(
        self,
        event_id: str,
        text: str,
        *,
        author: str = "member-117",
        kind: CommunityEventKind = CommunityEventKind.DIRECT_MESSAGE,
        window_hours: float | None = 24.0,
    ) -> CommunityEventIn:
        return CommunityEventIn(
            provider_event_id=event_id,
            kind=kind,
            platform=Platform.INSTAGRAM,
            account_ref=ACCOUNT_IG,
            external_post_id="ig-post-0001",
            author_ref=author,
            text=text,
            received_at=self.clock.now(),
            dm_window_expires_at=(
                self.clock.now() + timedelta(hours=window_hours)
                if window_hours is not None
                else None
            ),
            provenance=FAKE,
        )

    def row(self, sql: str, params=()):
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params=()):
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def metered_state(self, episode_id: UUID) -> dict:
        row = self.row(
            "SELECT c.allocated_micro_usd, c.reserved_outstanding_micro_usd, "
            "c.accrued_micro_usd, c.settled_micro_usd FROM budget_category_allocations c "
            "JOIN budget_accounts a ON a.id = c.account_id "
            "WHERE a.episode_id = %s AND c.category = 'METERED_MANAGEMENT'",
            (episode_id,),
        )
        if row is None:
            return {}
        state = dict(row)
        state["cat_committed"] = (
            state["reserved_outstanding_micro_usd"]
            + state["accrued_micro_usd"]
            + state["settled_micro_usd"]
        )
        state["reserved_micro_usd"] = state["reserved_outstanding_micro_usd"]
        return state


__all__ = [
    "ACCOUNT_IG",
    "KEYWORDS",
    "PRICE",
    "T0",
    "MembershipWorld",
    "bangkok_instant",
]

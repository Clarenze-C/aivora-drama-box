"""Shared builders for the publishing (T020) tests. Plain helpers; fixtures in conftest.

The world drives the REAL Gate 2 (review service) to produce an APPROVED package and a
RELEASE_APPROVED episode — the only state ``schedule_release`` accepts — then runs the
publishing service over fake adapters. Slot plans are built from the fake adapters' own
capability records so the capability pinning checks match by construction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from microdrama.budget import BudgetService
from microdrama.contracts.enums import (
    ApprovalAction,
    AssetKind,
    AssetState,
    DisclosureKind,
    GateType,
    Platform,
    PrincipalKind,
    Provenance,
    SlotKind,
)
from microdrama.contracts.examples import ACCOUNT_YT, season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.principals import Principal
from microdrama.contracts.release import (
    CostSummary,
    MediaRef,
    PostMetadata,
    PublicationCommand,
    QASummary,
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import ApprovalCommand, CostPolicy
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence import Database, FilesystemObjectStore, register_asset
from microdrama.publishing import metadata as meta
from microdrama.publishing import schedule_release as schedule_slots
from microdrama.publishing.service import PublishingService, command_id_for
from microdrama.publishing.slots import publish_client_token
from microdrama.review.packages import store_release_package
from microdrama.review.service import ReviewService
from microdrama.testing.fakes.common import FakeClock, SequentialIds
from microdrama.testing.fakes.publishing import FakePublisherAdapter
from microdrama.testing.seed import (
    seed_episode,
    seed_gate1_approval,
    seed_human_session,
    seed_owner,
)

FAKE = Provenance.FAKE_SYNTHETIC
MASTER_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-publish-master-" * 64
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)  # 19:00 Bangkok: past the 19:30 window? no —
# 12:00 UTC = 19:00 ICT, so the 19:30 ICT example schedule is still 30 min ahead; the
# world builds its own past-schedule slots by default (see slot_plan below).


def new_key(prefix: str = "key") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class PublishingWorld:
    def __init__(self, db: Database, tmp: Path, settings) -> None:
        self.db = db
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("publishing")
        self.store = FilesystemObjectStore(tmp / "objects")
        self.jobs = JobService(self.db, self.clock, self.ids)
        self.idempotency = IdempotencyService(self.db)
        self.budget = BudgetService(self.db, self.clock, self.ids, settings)
        self.adapters: dict[Platform, FakePublisherAdapter] = {
            platform: FakePublisherAdapter(platform, clock=self.clock, ids=self.ids)
            for platform in (
                Platform.YOUTUBE,
                Platform.TIKTOK,
                Platform.INSTAGRAM,
                Platform.FACEBOOK,
            )
        }
        self.service = PublishingService(
            self.db,
            self.clock,
            self.ids,
            self.adapters,
            self.store,
        )

    # --- principals ------------------------------------------------------------------

    def human(self) -> Principal:
        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
        return Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )

    # --- season / episode / media ------------------------------------------------------

    def season(self) -> uuid.UUID:
        """An approved season with its full scope proposal (the Gate 2 policy source)."""
        from microdrama.persistence.db import insert_row

        season_id = uuid.uuid4()
        scope = season_scope().model_copy(update={"season_id": season_id, "scope_version": 1})
        scope_hash = canonical_hash(scope)
        with self.db.transaction() as tx:
            approval_id = seed_gate1_approval(tx, season_id, scope_hash)
            tx.execute(
                "INSERT INTO seasons (id, state, title_th, title_en, approved_scope_version, "
                "approved_scope_hash, approval_event_id, approved_at) VALUES (%s, "
                "'SEASON_APPROVED', %s, 'Test season', 1, %s, %s, %s)",
                (season_id, scope.title_th, scope_hash, approval_id, self.clock.now()),
            )
            insert_row(
                tx,
                "season_proposals",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "scope_version": 1,
                    "scope": scope,
                    "scope_hash": scope_hash,
                    "status": "APPROVED",
                },
            )
        return season_id

    def episode(self, season_id: uuid.UUID, *, number: int = 2) -> uuid.UUID:
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, number=number, state="AWAITING_FINAL_REVIEW")
            self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
            )
        return episode_id

    def asset(
        self, season_id: uuid.UUID, episode_id: uuid.UUID, *, data: bytes = MASTER_BYTES
    ) -> tuple[uuid.UUID, str]:
        asset_id = uuid.uuid4()
        key = f"publishing-tests/{asset_id.hex}.mp4"
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
                    media=MediaInfo(duration_ms=30_000, has_video=True, has_audio=True),
                    state=AssetState.ACCEPTED,
                    provenance=FAKE,
                    episode_id=episode_id,
                    season_id=season_id,
                    created_at=self.clock.now(),
                ),
            )
        return asset_id, stored.sha256

    def caption(self, episode_id: uuid.UUID) -> uuid.UUID:
        from microdrama.contracts.enums import CaptionTimingSource
        from microdrama.contracts.media import CaptionCue, CaptionTrack

        track_id = uuid.uuid4()
        track = CaptionTrack(
            track_id=track_id,
            episode_id=episode_id,
            version=1,
            locale="th-TH",
            timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
            derived_from_audio_sha256=[canonical_hash({"audio": str(track_id)})],
            cues=[CaptionCue(cue_id="c1", start_ms=0, end_ms=1_000, text="ทดสอบคำบรรยาย")],
        )
        from microdrama.persistence.db import insert_row

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

    # --- slot plans and packages ---------------------------------------------------------

    def slot_plan(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        asset: tuple[uuid.UUID, str],
        slot: str = "full",
        platform: Platform = Platform.YOUTUBE,
        account_ref: str = ACCOUNT_YT,
        slot_kind: SlotKind = SlotKind.FULL_EPISODE,
        required: bool = True,
        depends_on: list[str] | None = None,
        schedule: ScheduleInstant | None = None,
        disclosures: list[DisclosureKind] | None = None,
    ) -> ReleaseSlotPlan:
        adapter = self.adapters[platform]
        capability = adapter.capability(account_ref)
        key = ReleaseSlotKey(
            series_id=season_id,
            episode_id=episode_id,
            part=0 if slot_kind is SlotKind.FULL_EPISODE else 1,
            locale="th-TH",
            platform=platform,
            account_ref=account_ref,
            release_slot=slot,
        )
        plan = ReleaseSlotPlan(
            slot=key,
            slot_kind=slot_kind,
            required=required,
            asset_id=asset[0],
            asset_sha256=asset[1],
            schedule=schedule or self.past_schedule(),
            depends_on=list(depends_on or []),
            disclosures=disclosures or [DisclosureKind.AI_GENERATED_CONTENT],
            capability_id=capability.capability_id,
            capability_version=capability.version,
        )
        return plan

    @staticmethod
    def policy_hash() -> str:
        return canonical_hash(season_scope().management_policy)

    @staticmethod
    def past_schedule() -> ScheduleInstant:
        """A window that has already opened (late-window submit is allowed)."""
        return ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 18, 0))

    @staticmethod
    def future_schedule() -> ScheduleInstant:
        """A window well past the test clock (needs the SCHEDULE capability to submit)."""
        return ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 22, 30))

    def package(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        scope: list[ReleaseSlotPlan],
        master: tuple[uuid.UUID, str],
        number: int = 2,
    ) -> ReleasePackage:
        return ReleasePackage.seal(
            package_id=uuid.uuid4(),
            episode_id=episode_id,
            season_id=season_id,
            episode_number=number,
            version=1,
            media=[MediaRef(asset_id=master[0], sha256=master[1], role="master")],
            caption_track_ids=[self.caption(episode_id)],
            hook_experiment_id=None,
            cast_package_asset_ids=[],
            release_scope=scope,
            management_policy_hash=self.policy_hash(),
            qa=QASummary(
                blocking_finding_ids=[],
                unknown_coverage_check_ids=[],
                finding_count=0,
                provenance=FAKE,
            ),  # fmt: skip
            cost=CostSummary(
                episode_cap_micro_usd=10_000_000,
                settled_micro_usd=0,
                accrued_micro_usd=0,
                reserved_outstanding_micro_usd=0,
                remaining_micro_usd=10_000_000,
                synthetic_fake_micro_usd=0,
            ),
            gate_blockers=[],
        )

    # --- Gate 2 (the real one) ------------------------------------------------------------

    def approve(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        package: ReleasePackage,
    ) -> uuid.UUID:
        """Drive the REAL Gate 2 APPROVE; returns the approval event id."""
        with self.db.transaction() as tx:
            store_release_package(tx, package, status="READY", now=self.clock.now())
        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            revision = tx.fetchone("SELECT revision FROM episodes WHERE id = %s", (episode_id,))[
                "revision"
            ]
        principal = Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )
        review = ReviewService(
            self.db,
            self.clock,
            self.ids,
            jobs=self.jobs,
            idempotency=self.idempotency,
            budget=self.budget,
            store=self.store,
            release_conditions_fn=lambda tx, episode_row, pkg: [],
            approval_hooks=[],
        )
        command = ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_id=episode_id,
            expected_revision=int(revision),
            package_hash=package.package_hash,
            media_hashes=package.media_hashes,
            management_policy_hash=package.management_policy_hash,
            release_scope_hash=package.release_scope_hash,
            idempotency_key=new_key("gate2"),
        )
        review.decide_episode(principal, episode_id, command)
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT approval_event_id FROM release_packages WHERE package_hash = %s",
                (package.package_hash,),
            )
        return row["approval_event_id"]

    def approved_episode(
        self, *, scope_builder=None
    ) -> tuple[uuid.UUID, uuid.UUID, ReleasePackage, uuid.UUID]:
        """Season + episode 2 + master + scope + READY package + REAL Gate 2 approval.

        Returns (season_id, episode_id, package, approval_event_id); the episode ends at
        RELEASE_APPROVED with the ``publish.schedule_release`` job enqueued by the review
        service itself.
        """
        season_id = self.season()
        episode_id = self.episode(season_id)
        master = self.asset(season_id, episode_id)
        scope = (
            scope_builder(season_id, episode_id, master)
            if scope_builder
            else [self.slot_plan(season_id=season_id, episode_id=episode_id, asset=master)]
        )
        package = self.package(
            season_id=season_id, episode_id=episode_id, scope=scope, master=master
        )
        approval_id = self.approve(season_id=season_id, episode_id=episode_id, package=package)
        return season_id, episode_id, package, approval_id

    # --- scheduling and commands ----------------------------------------------------------

    def schedule(self, episode_id: uuid.UUID) -> list[uuid.UUID]:
        with self.db.transaction() as tx:
            return schedule_slots(
                tx,
                episode_id=episode_id,
                actor=self.service._principal,
                now=self.clock.now(),
                correlation_id=uuid.uuid4(),
            )

    def submit_job(self, command: PublicationCommand) -> uuid.UUID:
        with self.db.transaction() as tx:
            result = self.jobs.enqueue(
                tx,
                job_type="publish.submit_slot",
                semantic_key=f"publish.submit_slot:{command.slot.dedupe_key}",
                payload=command,
                episode_id=command.slot.episode_id,
            )
        return result.job_id

    def command(
        self,
        plan: ReleaseSlotPlan,
        *,
        package: ReleasePackage,
        approval_event_id: uuid.UUID,
        metadata: PostMetadata | None = None,
    ) -> PublicationCommand:
        return PublicationCommand(
            command_id=command_id_for(plan.slot.dedupe_key),
            release_package_id=self.package_row_id(package),
            release_package_hash=package.package_hash,
            approval_event_id=approval_event_id,
            slot=plan.slot,
            slot_kind=plan.slot_kind,
            asset_id=plan.asset_id,
            asset_sha256=plan.asset_sha256,
            metadata=metadata or self.metadata(),
            metadata_version_id=meta.initial_metadata_version_id(plan.slot.dedupe_key),
            schedule=plan.schedule,
            capability_id=plan.capability_id,
            capability_version=plan.capability_version,
            client_token=publish_client_token(plan.slot.dedupe_key, package.package_hash),
        )

    @staticmethod
    def metadata(*, title: str = "ตอนที่ ๒ – หนี้ที่แม่ซ่อนไว้", catalog_version: int = 1) -> PostMetadata:
        return PostMetadata(
            locale="th-TH",
            title=title,
            caption="ร้านข้าวมันไก่ของแม่ ตอนที่ 2",
            description="Fon negotiates for time.",
            hashtags=["#thaidrama", "#shortseries"],
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            catalog_version=catalog_version,
        )

    # --- row access -------------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def post_row(self, post_id: uuid.UUID) -> dict[str, Any]:
        row = self.row("SELECT * FROM platform_posts WHERE id = %s", (post_id,))
        assert row is not None
        return row

    def post_by_slot(self, release_slot: str, episode_id: uuid.UUID) -> dict[str, Any]:
        row = self.row(
            "SELECT * FROM platform_posts WHERE release_slot = %s AND episode_id = %s",
            (release_slot, episode_id),
        )
        assert row is not None
        return row

    def episode_state(self, episode_id: uuid.UUID) -> str:
        return self.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"]

    def rebuilt_command(self, post_id: uuid.UUID) -> PublicationCommand:
        """The command the service reconstructs for poll/reconcile (hash-identical)."""
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM platform_posts WHERE id = %s", (post_id,))
            assert row is not None
            return self.service._command_for_post(tx, row)

    def package_row_id(self, package: ReleasePackage) -> uuid.UUID:
        row = self.row(
            "SELECT id FROM release_packages WHERE package_hash = %s", (package.package_hash,)
        )
        assert row is not None
        return row["id"]


__all__ = ["PublishingWorld", "T0", "new_key"]

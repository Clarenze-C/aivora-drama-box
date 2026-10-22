"""T025 test support: the frozen T020 publishing world plus the community service.

``CommunityWorld`` subclasses the T020 ``PublishingWorld`` (never edited) and
registers a ``FakeCommunityProvider`` (T007) for YouTube plus the T025
``CommunityService`` over the real budget service. ``managed_episode`` drives a
real Gate 2 approval and a real submit/poll path so community work runs against
a genuinely PUBLISHED_VERIFIED post with a real metadata version — no fabricated
platform_post rows.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from microdrama.community import CommunityService
from microdrama.config import Settings
from microdrama.contracts.enums import BudgetCategory, Platform, Provenance, SlotKind
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.primitives import DEFAULT_BUDGET_ALLOCATION_MICRO_USD
from microdrama.contracts.release import (
    CostSummary,
    MediaRef,
    QASummary,
    ReleasePackage,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.testing.fakes.common import SequentialIds, ensure_mock_mode
from microdrama.testing.fakes.community import CommunityScenario, FakeCommunityProvider

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1] / "publishing"
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))

from publishing_support import ACCOUNT_YT, PublishingWorld  # noqa: E402

FAKE = Provenance.FAKE_SYNTHETIC


def small_metered_policy(metered_micro_usd: int) -> CostPolicy:
    """The default allocation with METERED_MANAGEMENT resized (recovery absorbs it)."""
    allocation = dict(DEFAULT_BUDGET_ALLOCATION_MICRO_USD)
    delta = metered_micro_usd - allocation[BudgetCategory.METERED_MANAGEMENT]
    allocation[BudgetCategory.METERED_MANAGEMENT] = metered_micro_usd
    allocation[BudgetCategory.RECOVERY_HEADROOM] -= delta
    return CostPolicy(allocation_micro_usd=allocation)


class CommunityWorld(PublishingWorld):
    """One registered community provider (YouTube) + the community service."""

    def __init__(
        self,
        db: Database,
        tmp: Path,
        settings: Settings,
        *,
        scenarios: tuple[CommunityScenario, ...] = (),
        account_ref: str = ACCOUNT_YT,
        max_actions_per_run: int | None = None,
    ) -> None:
        super().__init__(db, tmp, settings)
        ensure_mock_mode(settings)  # fake providers exist only in OFFLINE_MOCK
        self.community_account = account_ref
        self.community_provider = FakeCommunityProvider(
            Platform.YOUTUBE,
            clock=self.clock,
            ids=SequentialIds("community"),
            account_ref=account_ref,
            scenarios=scenarios,
        )
        self.community = CommunityService(
            self.db,
            self.clock,
            self.ids,
            {Platform.YOUTUBE: self.community_provider},
            self.budget,
            **({} if max_actions_per_run is None else {"max_actions_per_run": max_actions_per_run}),
        )

    # --- episode / post plumbing -----------------------------------------------------

    def episode_with_policy(
        self, season_id: uuid.UUID, *, policy: CostPolicy | None = None
    ) -> uuid.UUID:
        with self.db.transaction() as tx:
            from microdrama.testing.seed import seed_episode

            episode_id = seed_episode(tx, season_id, number=2, state="AWAITING_FINAL_REVIEW")
            self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=policy or CostPolicy()
            )
        return episode_id

    def published_post(
        self,
        *,
        policy: CostPolicy | None = None,
        promo: bool = False,
        cover: bool = False,
    ) -> dict[str, Any]:
        """A genuinely published post (real Gate 2 + submit + poll + readback).

        ``cover`` ships an extra cover-role image asset in the package so the
        metadata worker's cover-selection policy has a real approved set.
        """
        season_id = self.season()
        episode_id = self.episode_with_policy(season_id, policy=policy)
        master = self.asset(season_id, episode_id)
        self.cover_asset = self.image_asset(season_id, episode_id)
        plans: list[ReleaseSlotPlan] = [
            self.slot_plan(season_id=season_id, episode_id=episode_id, asset=master)
        ]
        if promo:
            plans.append(
                self.slot_plan(
                    season_id=season_id,
                    episode_id=episode_id,
                    asset=master,
                    slot="promo",
                    slot_kind=SlotKind.PROMO_CUT,
                    required=False,
                    schedule=self.future_schedule(),
                )
            )
        package = self.package(
            season_id=season_id,
            episode_id=episode_id,
            scope=plans,
            master=master,
            cover=cover,
        )
        approval = self.approve(season_id=season_id, episode_id=episode_id, package=package)
        self.schedule(episode_id)
        command = self.command(plans[0], package=package, approval_event_id=approval)
        self.service.submit_slot(command, job_id=self.submit_job(command))
        post = self.post_by_slot("full", episode_id)
        self.service.poll_status(post["id"])  # PROCESSING
        updated = self.service.poll_status(post["id"])  # PUBLISHED_VERIFIED + readback
        assert updated["state"] == "PUBLISHED_VERIFIED"
        return {**dict(self.post_row(post["id"])), "season_id": season_id}

    def package(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        scope: list[ReleaseSlotPlan],
        master: tuple[uuid.UUID, str],
        number: int = 2,
        cover: bool = False,
    ) -> ReleasePackage:
        """The T020 package builder, optionally with an approved cover asset."""
        media = [MediaRef(asset_id=master[0], sha256=master[1], role="master")]
        if cover:
            media.append(
                MediaRef(asset_id=self.cover_asset[0], sha256=self.cover_asset[1], role="cover")
            )
        return ReleasePackage.seal(
            package_id=uuid.uuid4(),
            episode_id=episode_id,
            season_id=season_id,
            episode_number=number,
            version=1,
            media=media,
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
            ),
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

    # --- community plumbing -----------------------------------------------------------

    def image_asset(self, season_id: uuid.UUID, episode_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """A small fake cover image asset (accepted, synthetic)."""
        from microdrama.contracts.enums import AssetKind, AssetState
        from microdrama.contracts.media import MediaInfo
        from microdrama.persistence import register_asset

        asset_id = uuid.uuid4()
        key = f"community-tests/{asset_id.hex}.png"
        stored = self.store.put_bytes(
            key, b"\x89PNG-fake-cover-" + asset_id.hex.encode(), media_type="image/png"
        )
        with self.db.transaction() as tx:
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.IMAGE,
                    object_key=key,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type="image/png",
                    media=MediaInfo(duration_ms=0, has_video=False, has_audio=False),
                    state=AssetState.ACCEPTED,
                    provenance=FAKE,
                    episode_id=episode_id,
                    season_id=season_id,
                    created_at=self.clock.now(),
                ),
            )
        return asset_id, stored.sha256

    def script_comment(
        self,
        provider_event_id: str,
        text: str,
        *,
        external_post_id: str | None = None,
    ) -> None:
        """Append one scripted comment (untrusted data) to the provider feed."""
        from datetime import timedelta

        from microdrama.contracts.enums import CommunityEventKind, Provenance
        from microdrama.contracts.providers import CommunityEventIn

        self.community_provider.script_events(
            [
                CommunityEventIn(
                    provider_event_id=provider_event_id,
                    kind=CommunityEventKind.COMMENT,
                    platform=Platform.YOUTUBE,
                    account_ref=self.community_account,
                    external_post_id=external_post_id or "fake-post-0001",
                    author_ref=f"author-{provider_event_id}",
                    text=text,
                    received_at=self.clock.now() + timedelta(seconds=1),
                    provenance=Provenance.FAKE_SYNTHETIC,
                )
            ]
        )

    def process(self, season_id: uuid.UUID, episode_id: uuid.UUID):
        return self.community.process(
            Platform.YOUTUBE,
            self.community_account,
            season_id=season_id,
            episode_id=episode_id,
        )

    def event_row(self, provider_event_id: str) -> dict[str, Any]:
        row = self.row(
            "SELECT * FROM community_events WHERE provider_event_id = %s",
            (provider_event_id,),
        )
        assert row is not None, f"event {provider_event_id} was not ingested"
        return row

    def action_rows(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            return self.rows("SELECT * FROM management_actions ORDER BY created_at, id")
        return self.rows(
            "SELECT * FROM management_actions WHERE kind = %s ORDER BY created_at, id", (kind,)
        )

    def metered_counters(self, episode_id: uuid.UUID) -> dict[str, int]:
        """Committed/settled counters per category for the episode's budget account."""
        rows = self.rows(
            "SELECT c.category, c.allocated_micro_usd, c.reserved_outstanding_micro_usd, "
            "c.settled_micro_usd FROM budget_category_allocations c "
            "JOIN budget_accounts a ON a.id = c.account_id WHERE a.episode_id = %s "
            "ORDER BY c.category",
            (episode_id,),
        )
        return {
            row["category"]: (
                row["allocated_micro_usd"],
                row["reserved_outstanding_micro_usd"] + row["settled_micro_usd"],
                row["settled_micro_usd"],
            )
            for row in rows
        }

    def current_metadata(self, post_id: uuid.UUID):
        from microdrama.publishing import metadata as meta

        with self.db.transaction(readonly=True) as tx:
            return meta.current_metadata(tx, post_id)


__all__ = ["CommunityWorld", "small_metered_policy"]

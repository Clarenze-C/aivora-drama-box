"""T027 test support: the frozen T020 publishing world plus the analytics service.

``AnalyticsWorld`` subclasses the T020 ``PublishingWorld`` (never edited) and
adds the T027 ``AnalyticsService`` over the real budget service. Episodes are
driven through real Gate 2 approvals and real submit/poll paths, so
qualification and cost run against genuinely published posts — no fabricated
``platform_posts`` rows. Failures are produced by real budget usage plus a
seeded terminal outcome (the outcome columns exist for exactly that record).
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from microdrama.analytics import AnalyticsService
from microdrama.config import Settings
from microdrama.contracts.catalog import MetricSnapshot, MetricValue
from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    Platform,
    Provenance,
    ReceiptKind,
    SnapshotWindow,
)
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
from microdrama.persistence.db import insert_row
from microdrama.testing.fakes.common import ensure_mock_mode

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1] / "publishing"
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))

from publishing_support import PublishingWorld  # noqa: E402

FAKE = Provenance.FAKE_SYNTHETIC


def default_policy() -> CostPolicy:
    return CostPolicy(allocation_micro_usd=dict(DEFAULT_BUDGET_ALLOCATION_MICRO_USD))


class AnalyticsWorld(PublishingWorld):
    """The publishing world + analytics service + season/episode builders."""

    def __init__(self, db: Database, tmp: Path, settings: Settings) -> None:
        super().__init__(db, tmp, settings)
        ensure_mock_mode(settings)
        self.analytics = AnalyticsService(self.db, self.clock, self.ids)
        self._receipt_counter = 0

    # --- episode plumbing ---------------------------------------------------------------

    def asset_with_duration(
        self, season_id: UUID, episode_id: UUID, *, duration_ms: int
    ) -> tuple[UUID, str]:
        """The T020 asset builder with a configurable master duration."""
        from microdrama.contracts.enums import AssetKind, AssetState
        from microdrama.contracts.media import MediaInfo
        from microdrama.persistence import register_asset

        asset_id = uuid.uuid4()
        key = f"analytics-tests/{asset_id.hex}.mp4"
        stored = self.store.put_bytes(
            key, b"analytics-fake-master-" + asset_id.hex.encode(), media_type="video/mp4"
        )
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
        return asset_id, stored.sha256

    def episode_with_account(
        self, season_id: UUID, *, number: int, policy: CostPolicy | None = None
    ) -> UUID:
        with self.db.transaction() as tx:
            from microdrama.testing.seed import seed_episode

            episode_id = seed_episode(tx, season_id, number=number, state="AWAITING_FINAL_REVIEW")
            self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=policy or default_policy()
            )
        return episode_id

    def published_episode(
        self,
        season_id: UUID,
        *,
        number: int,
        duration_ms: int = 600_000,
        policy: CostPolicy | None = None,
    ) -> tuple[UUID, dict[str, Any]]:
        """A genuinely published full-episode post (real Gate 2 + submit + poll)."""
        episode_id = self.episode_with_account(season_id, number=number, policy=policy)
        master = self.asset_with_duration(season_id, episode_id, duration_ms=duration_ms)
        plan = self.slot_plan(season_id=season_id, episode_id=episode_id, asset=master)
        package = self.package(
            season_id=season_id, episode_id=episode_id, scope=[plan], master=master, number=number
        )
        approval = self.approve(season_id=season_id, episode_id=episode_id, package=package)
        self.schedule(episode_id)
        command = self.command(plan, package=package, approval_event_id=approval)
        self.service.submit_slot(command, job_id=self.submit_job(command))
        post = self.post_by_slot("full", episode_id)
        self.service.poll_status(post["id"])  # PROCESSING
        updated = self.service.poll_status(post["id"])  # PUBLISHED_VERIFIED + readback
        assert updated["state"] == "PUBLISHED_VERIFIED"
        return episode_id, dict(self.post_row(post["id"]))

    def failed_episode(
        self, season_id: UUID, *, number: int, outcome: str, spend_micro_usd: int = 250_000
    ) -> UUID:
        """An episode that spent real money and then failed terminally."""
        episode_id = self.episode_with_account(season_id, number=number)
        if spend_micro_usd:
            self.charge(episode_id, spend_micro_usd)
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE episodes SET state = 'AWAITING_FINAL_REVIEW', outcome = %s WHERE id = %s",
                (outcome, episode_id),
            )
        return episode_id

    def charge(
        self,
        episode_id: UUID,
        amount_micro_usd: int,
        *,
        category: BudgetCategory = BudgetCategory.GPU_GENERATION,
    ) -> None:
        """Real usage through the REAL BudgetService (synthetic receipt)."""
        self._receipt_counter += 1
        self.budget.record_usage(
            UsageReceipt(
                receipt_id=uuid.uuid4(),
                provider="runpod",
                provider_receipt_id=f"analytics-{episode_id.hex[:8]}-{self._receipt_counter}",
                kind=ReceiptKind.SETTLEMENT,
                cost_basis=CostBasis.SYNTHETIC_FAKE,
                episode_id=episode_id,
                category=category,
                amount_micro_usd=amount_micro_usd,
                units=1,
                unit="GPU_SECOND",
                observed_at=self.clock.now(),
                provenance=FAKE,
            )
        )

    def intervention(
        self,
        episode_id: UUID,
        season_id: UUID,
        *,
        days_after_publication: float = 0.0,
        kind: str = "MANUAL_UPLOAD",
    ) -> None:
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "manual_interventions",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "kind": kind,
                    "description": "test intervention",
                    "actor": "owner",
                    "occurred_at": self.clock.now() + timedelta(days=days_after_publication),
                },
            )

    # --- snapshot plumbing ----------------------------------------------------------------

    def snapshot(
        self,
        post: dict[str, Any],
        *,
        window: SnapshotWindow,
        observed_at_hours: float,
        metrics: dict[str, MetricValue | None],
        definitions_version: str = "fake-metrics-v1",
        traffic: str = "UNKNOWN",
    ) -> MetricSnapshot:
        """A MetricSnapshot for ``post`` observed N hours after verification."""
        verified_at = post["verified_at"]
        return MetricSnapshot(
            snapshot_id=uuid.uuid4(),
            platform=Platform(post["platform"]),
            account_ref=post["account_ref"],
            platform_post_id=post["id"],
            external_post_id=post["external_id"],
            episode_id=post["episode_id"],
            window=window,
            observed_at=verified_at + timedelta(hours=observed_at_hours),
            definitions_version=definitions_version,
            metrics={
                name: (
                    value
                    if value is not None
                    else MetricValue(value=None, definition=f"{name}-def", denominator=None)
                )
                for name, value in metrics.items()
            },
            traffic=traffic,
            provenance=FAKE,
        )

    def metric(
        self, value: int | None, *, definition: str = "views-def", denominator: int | None = 1_000
    ) -> MetricValue:
        return MetricValue(value=value, definition=definition, denominator=denominator)

    # --- package builder with episode number ----------------------------------------------

    def package(
        self,
        *,
        season_id: UUID,
        episode_id: UUID,
        scope: list[ReleaseSlotPlan],
        master: tuple[UUID, str],
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


__all__ = ["AnalyticsWorld", "default_policy"]

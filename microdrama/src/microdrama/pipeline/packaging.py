"""Gate 2 package assembly from durable state (T029).

The integrator-owned packaging step behind the ``review.prepare_package`` job:
collects what the accepted lanes persisted (final-review media from T016, the
caption tracks from T015, the episode-one cast package from T011, the current
capability pins, the latest QA cycle, the live cost view) and seals one
immutable ``ReleasePackage``. Nothing is fabricated here: every id and hash is
read back from the database, and the release conditions are re-verified at
decision time by ``review.gate_conditions`` — never trusted from this package.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from microdrama.contracts.enums import (
    DisclosureKind,
    Provenance,
    SlotKind,
)
from microdrama.contracts.release import (
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.persistence.db import Tx
from microdrama.review.packages import store_release_package

from .registry_seed import mock_account

#: A release window that has already opened at the mock T0 (18:00 Bangkok = 11:00 UTC,
#: one hour before the 12:00 UTC world clock).
DEMO_SCHEDULE_LOCAL = (2026, 10, 27, 18, 0)

MOCK_DISCLOSURES = [DisclosureKind.AI_GENERATED_CONTENT, DisclosureKind.SYNTHETIC_VOICE]


def _qa_summary(tx: Tx, episode_id: UUID):
    from microdrama.contracts.release import QASummary
    from microdrama.review.gate_conditions import finding_blocks

    findings = tx.fetchall(
        "SELECT id, severity, outcome, resolution FROM qa_findings WHERE episode_id = %s "
        "ORDER BY qa_cycle DESC, created_at DESC LIMIT 200",
        (episode_id,),
    )
    blocking = [
        row["id"]
        for row in findings
        if finding_blocks(row["severity"], row["outcome"], row["resolution"] or "OPEN")
    ]
    return QASummary(
        blocking_finding_ids=sorted(set(blocking), key=str),
        unknown_coverage_check_ids=[],
        finding_count=len(findings),
        provenance=Provenance.FAKE_SYNTHETIC,
    )


def _slot_plan(
    tx: Tx,
    *,
    season_id: UUID,
    episode_id: UUID,
    platform,
    asset: tuple[UUID, str],
    slot_kind: SlotKind,
    release_slot: str,
    required: bool,
    schedule,
    account: str | None = None,
) -> ReleaseSlotPlan:
    capability = tx.fetchone(
        "SELECT capability_id, version FROM capability_registry "
        "WHERE platform = %s AND account_ref = %s AND current",
        (platform.value, account or mock_account(platform)),
    )
    if capability is None:
        raise LookupError(f"no current capability record for {platform.value}/{account}")
    key = ReleaseSlotKey(
        series_id=season_id,
        episode_id=episode_id,
        part=0 if slot_kind is SlotKind.FULL_EPISODE else 1,
        locale="th-TH",
        platform=platform,
        account_ref=account or mock_account(platform),
        release_slot=release_slot,
    )
    return ReleaseSlotPlan(
        slot=key,
        slot_kind=slot_kind,
        required=required,
        asset_id=asset[0],
        asset_sha256=asset[1],
        schedule=schedule,
        depends_on=[],
        disclosures=list(MOCK_DISCLOSURES),
        capability_id=capability["capability_id"],
        capability_version=capability["version"],
    )


def _asset_sha(tx: Tx, asset_id: UUID) -> tuple[UUID, str] | None:
    row = tx.fetchone("SELECT sha256 FROM assets WHERE id = %s", (asset_id,))
    return None if row is None else (asset_id, row["sha256"])


def build_release_package(
    tx: Tx,
    *,
    world,
    season_id: UUID,
    episode_id: UUID,
    episode_number: int,
    package_id: UUID,
    version: int,
) -> ReleasePackage:
    """Assemble + seal the package from durable state (called inside a transaction)."""
    from microdrama.contracts.primitives import ScheduleInstant
    from microdrama.contracts.release import CostSummary

    review_media = world.variants.final_review_media(episode_id)
    if not review_media.media:
        raise LookupError("no assembled media for this episode")

    cast_asset_ids: list[UUID] = []
    if episode_number == 1:
        cast_asset_ids = list(world.references.cast_package_assets(episode_id))

    schedule = ScheduleInstant.from_local("Asia/Bangkok", datetime(*DEMO_SCHEDULE_LOCAL))
    master = (review_media.media[0].asset_id, review_media.media[0].sha256)
    plans: list[ReleaseSlotPlan] = []
    variant_by_prefix = {
        ref.role: ref for ref in review_media.media if ref.role in ("variant", "hook")
    }
    from microdrama.contracts.enums import Platform

    full_platforms = (Platform.YOUTUBE, Platform.FACEBOOK)
    short_platforms = (Platform.TIKTOK, Platform.INSTAGRAM)
    for platform in full_platforms:
        plans.append(
            _slot_plan(
                tx,
                season_id=season_id,
                episode_id=episode_id,
                platform=platform,
                asset=master,
                slot_kind=SlotKind.FULL_EPISODE,
                release_slot="full",
                required=platform is Platform.YOUTUBE,
                schedule=schedule,
            )
        )
    for platform in short_platforms:
        variant = variant_by_prefix.get("variant")
        asset = (variant.asset_id, variant.sha256) if variant is not None else master
        plans.append(
            _slot_plan(
                tx,
                season_id=season_id,
                episode_id=episode_id,
                platform=platform,
                asset=asset,
                slot_kind=SlotKind.PROMO_CUT,
                release_slot="short",
                required=False,
                schedule=schedule,
            )
        )

    policy_hash = tx.fetchone(
        "SELECT approved_scope_hash FROM seasons WHERE id = %s", (season_id,)
    )["approved_scope_hash"]
    scope = tx.fetchone(
        "SELECT scope FROM season_proposals WHERE season_id = %s AND scope_hash = %s "
        "ORDER BY scope_version DESC LIMIT 1",
        (season_id, policy_hash),
    )
    from microdrama.contracts.hashing import canonical_hash

    management_policy_hash = canonical_hash(scope["scope"]["management_policy"])

    cost_summary: CostSummary = world.budget.cost_view(episode_id).summary
    package = ReleasePackage.seal(
        package_id=package_id,
        episode_id=episode_id,
        season_id=season_id,
        episode_number=episode_number,
        version=version,
        media=list(review_media.media),
        caption_track_ids=list(review_media.caption_track_ids),
        hook_experiment_id=review_media.hook_experiment_id,
        cast_package_asset_ids=cast_asset_ids,
        release_scope=plans,
        management_policy_hash=management_policy_hash,
        qa=_qa_summary(tx, episode_id),
        cost=cost_summary,
        gate_blockers=[],
    )
    return package


def prepare_and_store_package(
    world,
    *,
    season_id: UUID,
    episode_id: UUID,
    episode_number: int,
) -> ReleasePackage:
    """The ``review.prepare_package`` step: seal the package and store it READY."""
    from microdrama.contracts.enums import EpisodeState, PrincipalKind
    from microdrama.contracts.principals import Principal
    from microdrama.core.state_machine import transition_episode

    with world.db.transaction() as tx:
        version_row = tx.fetchone(
            "SELECT max(version) AS v FROM release_packages WHERE episode_id = %s",
            (episode_id,),
        )
        version = 1 if version_row is None or version_row["v"] is None else version_row["v"] + 1
        package = build_release_package(
            tx,
            world=world,
            season_id=season_id,
            episode_id=episode_id,
            episode_number=episode_number,
            package_id=world.fakes.ids.new_id(),
            version=version,
        )
        store_release_package(tx, package, status="READY", now=world.fakes.clock.now())
    world.references.mark_reviewed_in_package(episode_id)
    # With a READY package and green QA the episode waits at the human gate: the
    # same no-approval transition the repair lane uses to reopen Gate 2.
    with world.db.transaction() as tx:
        episode = tx.fetchone("SELECT state, revision FROM episodes WHERE id = %s", (episode_id,))
        if episode["state"] == EpisodeState.AI_REVIEW.value:
            transition_episode(
                tx,
                episode_id=episode_id,
                to=EpisodeState.AWAITING_FINAL_REVIEW,
                expected_revision=episode["revision"],
                actor=Principal(principal_id="svc:pipeline-packager", kind=PrincipalKind.SCHEDULER),
                now=world.fakes.clock.now(),
                correlation_id=package.package_id,
                reason="release package READY; entering human final review",
            )
    return package


__all__ = [
    "MOCK_DISCLOSURES",
    "build_release_package",
    "prepare_and_store_package",
]

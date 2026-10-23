"""The complete job handler registry for the composed pipeline (T029).

One handler per ``JOB_SPECS`` job type, binding the claimed job to its owning
module service. Handlers are thin: they translate the frozen job input into the
service call and the service result into a typed ``JobOutcome``. Every gate,
budget hold, idempotency rule and capability check lives in the services — a
handler never re-implements one.

The registry is exhaustive by contract: a test pins that every JOB_SPECS type
has exactly one handler, so a new job type cannot silently run NO_HANDLER.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from microdrama.analytics import analytics_handlers
from microdrama.contracts.enums import AssetState, ProviderOperationState
from microdrama.contracts.errors import NotFound
from microdrama.contracts.jobs import (
    CommunityEventRef,
    EpisodeStepInput,
    PlatformPostRef,
    PublicationCommand,
    SeasonStepInput,
)
from microdrama.contracts.release import ManagementAction, PostMetadata
from microdrama.core.jobs import (
    Failed,
    JobContext,
    JobOutcome,
    RetryLater,
    Succeeded,
    WaitExternal,
)
from microdrama.persistence.assets import asset_revision, set_asset_state

from .mocks import mock_research_request
from .packaging import prepare_and_store_package
from .registry_seed import MOCK_ACCOUNT


def _episode(db, episode_id: UUID) -> dict[str, Any]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT id, season_id, episode_number, state FROM episodes WHERE id = %s",
            (episode_id,),
        )
    if row is None:
        raise NotFound("episode not found", episode_id=str(episode_id))
    return row


def _operation_for_job(db, job_id: UUID) -> UUID | None:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT id FROM provider_operations WHERE job_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (job_id,),
        )
    return None if row is None else row["id"]


def _shot_assets(db, episode_id: UUID) -> dict[str, UUID]:
    """shot_id -> latest registered render asset for the episode (object-key order)."""
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id, object_key FROM assets WHERE episode_id = %s "
            "AND object_key LIKE 'renders/%%' ORDER BY object_key",
            (episode_id,),
        )
    assets: dict[str, UUID] = {}
    for row in rows:
        # renders/{episode}/{shot}/a{attempt}/{node}.ext — last write per shot wins.
        parts = row["object_key"].split("/")
        if len(parts) >= 4:
            assets[parts[2]] = row["id"]
    return assets


def _accept_asset(db, asset_id: UUID) -> None:
    with db.transaction() as tx:
        revision = asset_revision(tx, asset_id)
        set_asset_state(tx, asset_id, AssetState.ACCEPTED, expected_revision=revision)


def _master_asset(db, episode_id: UUID) -> UUID:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
    if row is None:
        raise NotFound("no assembled master for episode", episode_id=str(episode_id))
    return row["output_asset_id"]


def build_handlers(world) -> dict[str, Any]:
    """The exhaustive handler registry for every JOB_SPECS job type."""
    db = world.db
    handlers: dict[str, Any] = {}

    # --- production lane ----------------------------------------------------------------

    def research_collect_and_propose(ctx: JobContext) -> JobOutcome:
        payload: SeasonStepInput = ctx.payload  # type: ignore[assignment]
        result = world.research.run_research(
            payload.season_id, mock_research_request(payload.season_id, trigger=payload.trigger)
        )
        return Succeeded(
            {
                "run_id": str(result.run_id),
                "proposal_id": str(result.proposal_id) if result.proposal_id else None,
                "mock": True,
            }
        )

    handlers["research.collect_and_propose"] = research_collect_and_propose

    def story_compile_season(ctx: JobContext) -> JobOutcome:
        payload: SeasonStepInput = ctx.payload  # type: ignore[assignment]
        result = world.story.compile_season(payload.season_id, scope_version=payload.scope_version)
        return Succeeded(
            {
                "canon_version": str(result.canon_version),
                "scope_version": result.scope_version,
                "replayed": result.replayed,
                "mock": True,
            }
        )

    handlers["story.compile_season"] = story_compile_season

    def story_write_episode(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        outcome = world.story.write_episode(payload.episode_id, trigger=payload.trigger)
        if outcome.status in ("CURRENT", "REPLAYED"):
            return Succeeded(
                {
                    "script_id": str(outcome.script_id),
                    "manifest_id": str(outcome.manifest_id),
                    "settled_micro_usd": outcome.settled_micro_usd,
                    "rounds_used": outcome.rounds_used,
                    "mock": True,
                }
            )
        return Failed(f"story_{outcome.status.lower()}", detail=str(outcome.findings or ""))

    handlers["story.write_episode"] = story_write_episode

    def references_prepare_episode(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        outcome = world.references.prepare_episode(payload.episode_id, trigger=payload.trigger)
        if outcome.status in ("CURRENT", "REPLAYED"):
            return Succeeded(
                {
                    "anchors": len(outcome.anchors),
                    "lines": len(outcome.lines),
                    "settled_micro_usd": outcome.settled_micro_usd,
                    "identity_lock_id": (
                        str(outcome.identity_lock_id) if outcome.identity_lock_id else None
                    ),
                    "mock": True,
                }
            )
        return Failed(f"references_{outcome.status.lower()}")

    handlers["references.prepare_episode"] = references_prepare_episode

    def render_shot(ctx: JobContext) -> JobOutcome:
        operation_id = _operation_for_job(db, ctx.job.id)
        if operation_id is None:
            return RetryLater("no_operation_yet", retry_after_ms=1_000)
        status = world.comfy.poll(operation_id)
        if status.state is ProviderOperationState.SUCCEEDED:
            for asset in status.assets:
                _accept_asset(db, asset.asset_id)
            return Succeeded(
                {
                    "operation_id": str(operation_id),
                    "assets": [str(a.asset_id) for a in status.assets],
                    "settled_micro_usd": status.settled_micro_usd,
                    "mock": True,
                }
            )
        if status.state is ProviderOperationState.FAILED:
            return Failed(status.error_code or "render_failed")
        return WaitExternal(external_id=str(operation_id), poll_after_ms=1_000)

    handlers["render.shot"] = render_shot

    def edit_assemble_episode(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        shot_assets = _shot_assets(db, payload.episode_id)
        outcome = world.editing.assemble_episode(payload.episode_id, shot_assets=shot_assets)
        return Succeeded(
            {
                "edl_id": str(outcome.edl_id),
                "duration_ms": outcome.duration_ms,
                "clean_asset_id": str(outcome.clean_asset_id),
                "burned_asset_id": (
                    str(outcome.burned_asset_id) if outcome.burned_asset_id else None
                ),
                "caption_track_ids": [str(t) for t in outcome.caption_track_ids],
                "settled_micro_usd": outcome.settled_micro_usd,
                "mock": True,
            }
        )

    handlers["edit.assemble_episode"] = edit_assemble_episode

    def edit_variants_and_hooks(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        from microdrama.contracts.enums import Platform
        from microdrama.editing.variants_service import VariantTarget

        targets = [
            VariantTarget(platform=platform, account_ref=MOCK_ACCOUNT)
            for platform in (Platform.TIKTOK, Platform.INSTAGRAM)
        ]
        variants = world.variants.build_variants(payload.episode_id, targets=targets)
        covers = world.variants.derive_covers(payload.episode_id, targets=targets)
        hooks = world.variants.generate_hook_candidates(payload.episode_id)
        return Succeeded(
            {
                "variants": [r.variant_key for r in variants.results],
                "blockers": [b.reason for b in variants.blockers],
                "covers": len(covers.covers),
                "hook_candidates": len(hooks.candidates),
                "hook_experiment_id": str(hooks.experiment_id),
                "mock": True,
            }
        )

    handlers["edit.variants_and_hooks"] = edit_variants_and_hooks

    def qa_technical(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        run = world.qa_technical.run_episode_qa(
            payload.episode_id, asset_id=_master_asset(db, payload.episode_id)
        )
        if run.all_checks_green:
            return Succeeded(
                {
                    "qa_cycle": run.qa_cycle,
                    "blocking_check_ids": list(run.blocking_check_ids),
                    "unknown_check_ids": list(run.unknown_check_ids),
                    "mock": True,
                }
            )
        return Failed(
            "qa_blocking_checks",
            detail=f"blocking: {sorted(run.blocking_check_ids)}",
        )

    handlers["qa.technical"] = qa_technical

    def qa_observe(ctx: JobContext) -> JobOutcome:
        from microdrama.contracts.qa import ObservationRequest

        payload: ObservationRequest = ctx.payload  # type: ignore[assignment]
        frozen = world.qa_observation.observe_media(
            payload.episode_id,
            asset_id=payload.media[0].asset_id,
            questions=payload.questions,
        )
        return Succeeded(
            {
                "report_id": str(frozen.report.report_id),
                "settled_micro_usd": frozen.settled_micro_usd,
                "mock": True,
            }
        )

    handlers["qa.observe"] = qa_observe

    def qa_compare(ctx: JobContext) -> JobOutcome:
        from microdrama.contracts.qa import ComparisonRequest

        payload: ComparisonRequest = ctx.payload  # type: ignore[assignment]
        run = world.qa_comparison.compare(
            payload.episode_id,
            observation_report_id=payload.observation_report_id,
            identity_lock_id=payload.identity_lock_id,
        )
        if run.all_checks_green:
            return Succeeded({"qa_cycle": run.qa_cycle, "mock": True})
        return Failed(
            "comparison_blocking_checks", detail=f"blocking: {sorted(run.blocking_check_ids)}"
        )

    handlers["qa.compare"] = qa_compare

    def qa_plan_repairs(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        plan = world.qa_repairs.plan_from_findings(payload.episode_id)
        if plan.plan_id is None:
            return Succeeded({"plan_id": None, "reason": "nothing repairable", "mock": True})
        execution = world.qa_repairs.execute_plan(plan.plan_id)
        return Succeeded(
            {
                "plan_id": str(plan.plan_id),
                "executed_steps": len(execution.steps),
                "returns_to_gate2": execution.returns_to_gate2,
                "mock": True,
            }
        )

    handlers["qa.plan_repairs"] = qa_plan_repairs

    def review_prepare_package(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        episode = _episode(db, payload.episode_id)
        # SPEC §5 rule 8 / T012: the GPU must be off before the human wait.
        world.leases.stop_for_human_wait(payload.episode_id)
        package = prepare_and_store_package(
            world,
            season_id=episode["season_id"],
            episode_id=payload.episode_id,
            episode_number=episode["episode_number"],
        )
        return Succeeded(
            {
                "package_hash": package.package_hash,
                "media": len(package.media),
                "slots": len(package.release_scope),
                "cast_assets": len(package.cast_package_asset_ids),
                "mock": True,
            }
        )

    handlers["review.prepare_package"] = review_prepare_package

    # --- publication lane -----------------------------------------------------------------

    def publish_schedule_release(ctx: JobContext) -> JobOutcome:
        from microdrama.publishing.slots import schedule_release

        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        with db.transaction() as tx:
            post_ids = schedule_release(
                tx,
                episode_id=payload.episode_id,
                actor=world.publishing._principal,
                now=world.fakes.clock.now(),
                correlation_id=ctx.job.id,
            )
        return Succeeded({"platform_post_ids": [str(p) for p in post_ids], "mock": True})

    handlers["publish.schedule_release"] = publish_schedule_release

    def publish_submit_slot(ctx: JobContext) -> JobOutcome:
        payload: PublicationCommand = ctx.payload  # type: ignore[assignment]
        result = world.publishing.submit_slot(payload, job_id=ctx.job.id)
        state = result.get("state")
        if state == "HELD":
            # A held slot is the designed outcome of an unqualified capability:
            # auditable, retryable via retry_held_slot — not a job failure.
            return Succeeded(
                {
                    "platform_post_id": str(result.get("platform_post_id")),
                    "state": "HELD",
                    "blocker": str(result.get("blocker")),
                    "mock": True,
                }
            )
        if state == "RETRY_WAIT":
            return RetryLater(
                "provider_rate_limited", retry_after_ms=result.get("retry_after_ms", 60_000)
            )
        if state == "NEEDS_RECONCILIATION":
            from microdrama.core.jobs import NeedsReconciliation

            return NeedsReconciliation(
                "submit outcome ambiguous; reconcile before resubmission",
                external_id=str(result.get("external_id") or "") or None,
            )
        return Succeeded(
            {
                "platform_post_id": str(result.get("platform_post_id")),
                "external_id": result.get("external_id"),
                "url": result.get("url"),
                "mock": True,
            }
        )

    handlers["publish.submit_slot"] = publish_submit_slot

    def publish_poll_status(ctx: JobContext) -> JobOutcome:
        payload: PlatformPostRef = ctx.payload  # type: ignore[assignment]
        result = world.publishing.poll_status(payload.platform_post_id)
        state = result.get("state")
        if state in ("PUBLISHED_VERIFIED", "COMPLETED"):
            return Succeeded(
                {
                    "platform_post_id": str(payload.platform_post_id),
                    "state": state,
                    "url": result.get("url"),
                    "mock": True,
                }
            )
        return WaitExternal(external_id=str(payload.platform_post_id), poll_after_ms=5_000)

    handlers["publish.poll_status"] = publish_poll_status

    def publish_reconcile_slot(ctx: JobContext) -> JobOutcome:
        payload: PlatformPostRef = ctx.payload  # type: ignore[assignment]
        result = world.publishing.reconcile_slot(payload.platform_post_id)
        return Succeeded(
            {
                "platform_post_id": str(payload.platform_post_id),
                "state": result.get("state"),
                "mock": True,
            }
        )

    handlers["publish.reconcile_slot"] = publish_reconcile_slot

    # --- community lane --------------------------------------------------------------------

    def community_ingest_event(ctx: JobContext) -> JobOutcome:
        payload: CommunityEventRef = ctx.payload  # type: ignore[assignment]
        with db.transaction(readonly=True) as tx:
            event = tx.fetchone(
                "SELECT platform, account_ref FROM community_events WHERE id = %s",
                (payload.community_event_id,),
            )
            job = tx.fetchone("SELECT season_id, episode_id FROM jobs WHERE id = %s", (ctx.job.id,))
        if event is None or job is None or job["episode_id"] is None:
            return Failed("event_not_found")
        report = world.community.process(
            event["platform"],
            event["account_ref"],
            season_id=job["season_id"],
            episode_id=job["episode_id"],
        )
        return Succeeded(
            {
                "ingested_new": report.ingested_new,
                "executed": report.executed,
                "suppressed": report.suppressed,
                "deferred": report.deferred,
                "mock": True,
            }
        )

    handlers["community.ingest_event"] = community_ingest_event

    def community_respond(ctx: JobContext) -> JobOutcome:
        payload: ManagementAction = ctx.payload  # type: ignore[assignment]
        with db.transaction(readonly=True) as tx:
            job = tx.fetchone("SELECT season_id, episode_id FROM jobs WHERE id = %s", (ctx.job.id,))
        result = world.community.execute_action(
            payload, season_id=job["season_id"], episode_id=job["episode_id"]
        )
        return Succeeded({"status": result.get("status"), "mock": True})

    handlers["community.respond"] = community_respond

    def community_optimize_metadata(ctx: JobContext) -> JobOutcome:
        from microdrama.community.grounding import load_facts
        from microdrama.community.metadata_worker import propose_hashtag_optimization

        payload: PlatformPostRef = ctx.payload  # type: ignore[assignment]
        with db.transaction(readonly=True) as tx:
            post = tx.fetchone(
                "SELECT series_id, current_metadata_version_id FROM platform_posts WHERE id = %s",
                (payload.platform_post_id,),
            )
            current = None
            if post is not None and post["current_metadata_version_id"] is not None:
                row = tx.fetchone(
                    "SELECT metadata FROM metadata_versions WHERE id = %s",
                    (post["current_metadata_version_id"],),
                )
                if row is not None:
                    current = PostMetadata.model_validate(row["metadata"])
                    facts = load_facts(tx, post["series_id"], now=world.fakes.clock.now())
        if current is None:
            return Failed("no_current_metadata")
        proposed = propose_hashtag_optimization(current, facts)
        result = world.community.apply_metadata_edit(payload.platform_post_id, proposed)
        return Succeeded({"decision": result.get("decision"), "mock": True})

    handlers["community.optimize_metadata"] = community_optimize_metadata

    def community_deliver_dm(ctx: JobContext) -> JobOutcome:
        payload: ManagementAction = ctx.payload  # type: ignore[assignment]
        with db.transaction(readonly=True) as tx:
            job = tx.fetchone("SELECT season_id, episode_id FROM jobs WHERE id = %s", (ctx.job.id,))
        result = world.community.execute_action(
            payload, season_id=job["season_id"], episode_id=job["episode_id"]
        )
        return Succeeded({"status": result.get("status"), "mock": True})

    handlers["community.deliver_dm"] = community_deliver_dm

    def membership_sync_catalog(ctx: JobContext) -> JobOutcome:
        payload: EpisodeStepInput = ctx.payload  # type: ignore[assignment]
        entry = world.memberships.catalog.current_entry(payload.episode_id)
        return Succeeded(
            {
                "episode_id": str(payload.episode_id),
                "catalog_state": entry.state.value if hasattr(entry, "state") else str(entry),
                "mock": True,
            }
        )

    handlers["membership.sync_catalog"] = membership_sync_catalog

    # --- analytics lane (T027's ready-made handlers) ---------------------------------------

    handlers.update(analytics_handlers(world.analytics))

    return handlers


__all__ = ["build_handlers"]

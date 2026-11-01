"""The durable progress projection (T044a): counts, stages, revisions, waits.

Every projection is computed from current rows: a refresh and a fresh database
connection reproduce it exactly. Failed attempts never count as accepted; a new
required shot or outfit changes the denominator with a visible plan revision;
production and release stay separate; a missing plan is indeterminate, never a
fabricated number; and a provider's internal percentage never surfaces.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from review_support import World

from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    JobStatus,
    Provenance,
    ReleaseState,
)
from microdrama.contracts.examples import V2_T0, v2_directing_manifest, v2_wardrobe_assignment
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.v2 import (
    DirectingManifest,
    DirectingSection,
    SceneWardrobeAssignment,
)
from microdrama.core.events import append_event
from microdrama.persistence import Database, register_asset
from microdrama.review.progress import ProgressProjection
from microdrama.story.v2_store import StoryV2Store

pytestmark = pytest.mark.db
FAKE = Provenance.FAKE_SYNTHETIC


# --- builders --------------------------------------------------------------------------------


def _manifest_for(
    episode_id: UUID, record_id: UUID, version: int, shot_ids: list[str]
) -> DirectingManifest:
    """A valid directing manifest for this episode with exactly ``shot_ids``."""
    proto = v2_directing_manifest()
    proto_shot = proto.shots[0]
    shots = []
    sections = []
    for index, shot_id in enumerate(shot_ids, start=1):
        section_id = f"sec-probe-{index}"
        shots.append(
            proto_shot.model_copy(
                update={
                    "shot_id": shot_id,
                    "sequence": index,
                    "section_id": section_id,
                    # The example shot's state events/values are bound to the
                    # example's episode; this probe shot carries none.
                    "events": [],
                    "state_in": [],
                    "state_out": [],
                }
            )
        )
        sections.append(
            DirectingSection(
                section_id=section_id,
                sequence=index,
                shot_ids=[shot_id],
                duration_ms=proto_shot.duration_ms,
            )
        )
    return DirectingManifest.seal(
        record_id=record_id,
        version=version,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        episode_id=episode_id,
        pack_id=proto.pack_id,
        pack_version=proto.pack_version,
        pack_hash=proto.pack_hash,
        approved_scope_hash=proto.approved_scope_hash,
        shots=shots,
        sections=sections,
        source_hashes=proto.source_hashes,
    )


def _assignment_for(
    episode_id: UUID,
    record_id: UUID,
    asset_id: UUID,
    *,
    outfit_id: str | None = None,
    version: int = 1,
) -> SceneWardrobeAssignment:
    proto = v2_wardrobe_assignment()
    return SceneWardrobeAssignment.seal(
        record_id=record_id,
        version=version,
        created_at=V2_T0,
        updated_at=V2_T0,
        valid_from=V2_T0,
        episode_id=episode_id,
        scene_id=proto.scene_id,
        character_id=proto.character_id,
        story_day=proto.story_day,
        setting=proto.setting,
        wardrobe_bible_id=proto.wardrobe_bible_id,
        wardrobe_bible_version=proto.wardrobe_bible_version,
        outfit_id=outfit_id or proto.outfit_id,
        outfit_version=proto.outfit_version,
        asset_id=asset_id,
        asset_version=1,
        asset_sha256=proto.asset_sha256,
        rights=proto.rights,
    )


def _store_asset(
    world: World,
    *,
    season_id: UUID,
    episode_id: UUID,
    object_key: str,
    state: AssetState = AssetState.ACCEPTED,
) -> UUID:
    asset_id = uuid.uuid4()
    stored = world.store.put_bytes(object_key, object_key.encode(), media_type="image/png")
    descriptor = AssetDescriptor(
        asset_id=asset_id,
        asset_kind=AssetKind.IMAGE,
        object_key=object_key,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        media_type="image/png",
        state=state,
        provenance=FAKE,
        episode_id=episode_id,
        season_id=season_id,
        created_at=world.clock.now(),
    )
    with world.db.transaction() as tx:
        register_asset(tx, descriptor)
    return asset_id


def _shot_asset(
    world: World,
    *,
    season_id: UUID,
    episode_id: UUID,
    shot_id: str,
    attempt: int,
    state: AssetState = AssetState.ACCEPTED,
) -> UUID:
    return _store_asset(
        world,
        season_id=season_id,
        episode_id=episode_id,
        object_key=f"renders/{episode_id}/{shot_id}/a{attempt}/frame.png",
        state=state,
    )


def _job(
    world: World,
    episode_id: UUID,
    *,
    status: str,
    attempt: int = 1,
    outcome: dict[str, Any] | None = None,
    job_type: str = "render.shot",
) -> UUID:
    job_id = uuid.uuid4()
    payload = {"episode_id": str(episode_id)}
    with world.db.transaction() as tx:
        tx.execute(
            "INSERT INTO jobs (id, job_type, queue, semantic_key, input_hash, input, status, "
            "attempt, outcome, episode_id) VALUES (%s, %s, 'production', %s, %s, %s, %s, %s, "
            "%s, %s)",
            (
                job_id,
                job_type,
                f"{job_type}:{job_id.hex}",
                canonical_hash(payload),
                psycopg.types.json.Jsonb(payload),
                status,
                attempt,
                psycopg.types.json.Jsonb(outcome) if outcome else None,
                episode_id,
            ),
        )
    return job_id


def _event(world: World, episode_id: UUID) -> UUID:
    with world.db.transaction() as tx:
        event = append_event(
            tx,
            aggregate_type="episode",
            aggregate_id=episode_id,
            event_type="probe.progress_changed",
            payload={"probe": True},
            correlation_id=uuid.uuid4(),
            occurred_at=world.clock.now(),
        )
    return event.event_id


def _bump_revision(world: World, episode_id: UUID) -> None:
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE episodes SET revision = revision + 1, updated_at = %s WHERE id = %s",
            (datetime.now(UTC), episode_id),
        )


@pytest.fixture
def planned(world: World):
    """An approved season + episode with a 3-shot plan and one required outfit."""
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, state="RENDERING")
    outfit_asset = _store_asset(
        world,
        season_id=season_id,
        episode_id=episode_id,
        object_key=f"outfits/{episode_id}/apron.png",
    )
    StoryV2Store(world.db).save_bundle(
        [
            _manifest_for(episode_id, uuid.uuid4(), 1, ["probe-1", "probe-2", "probe-3"]),
            _assignment_for(episode_id, uuid.uuid4(), outfit_asset),
        ]
    )
    return world, season_id, episode_id, outfit_asset


# --- the projection -------------------------------------------------------------------------


def test_no_current_plan_is_indeterminate(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode(season_id, state="SCRIPTING")
    view = world.service.episode_progress(world.human(), episode_id)

    assert view.production.required == 0
    assert view.production.accepted == 0
    assert view.production.progress_bp is None
    assert view.plan is None
    assert any("no current DirectingManifest" in item for item in view.indeterminate)
    # Nothing is fabricated: no canonical record without provenance.
    assert view.snapshot is None


def test_counts_come_from_current_rows_and_failed_attempts_never_count(planned) -> None:
    world, season_id, episode_id, outfit_asset = planned
    # probe-1 accepted on its only attempt; probe-2 accepted at a1 but FAILED at a2
    # (the latest attempt governs); probe-3 has no render yet.
    _shot_asset(world, season_id=season_id, episode_id=episode_id, shot_id="probe-1", attempt=1)
    _shot_asset(world, season_id=season_id, episode_id=episode_id, shot_id="probe-2", attempt=1)
    _shot_asset(
        world,
        season_id=season_id,
        episode_id=episode_id,
        shot_id="probe-2",
        attempt=2,
        state=AssetState.FAILED,
    )

    view = world.service.episode_progress(world.human(), episode_id)
    work = view.production
    assert work.required == 4  # 3 shots + 1 outfit
    assert work.accepted == 2  # probe-1 + the accepted outfit
    assert work.progress_bp == 2 * 10_000 // 4
    assert view.plan is not None and view.plan.version == 1
    assert view.plan.denominator_changed is False  # first revision: nothing to compare

    # The outfit asset going FAILED drops accepted work by one, percent included.
    with world.db.transaction() as tx:
        tx.execute("UPDATE assets SET state = 'FAILED' WHERE id = %s", (outfit_asset,))
    again = world.service.episode_progress(world.human(), episode_id)
    assert again.production.accepted == 1
    assert again.production.progress_bp == 10_000 // 4


def test_a_new_required_shot_changes_the_denominator_and_shows_the_revision(planned) -> None:
    world, season_id, episode_id, _outfit = planned
    # All three current shots accepted.
    for shot in ("probe-1", "probe-2", "probe-3"):
        _shot_asset(world, season_id=season_id, episode_id=episode_id, shot_id=shot, attempt=1)
    before = world.service.episode_progress(world.human(), episode_id)
    assert before.production.accepted == 4
    assert before.production.progress_bp == 10_000

    # Plan v2 requires a fourth shot: denominator 4 -> 5, percent drops truthfully.
    StoryV2Store(world.db).save_bundle(
        [
            _manifest_for(
                episode_id,
                before.plan.record_id,
                2,
                ["probe-1", "probe-2", "probe-3", "probe-4"],
            )
        ]
    )
    after = world.service.episode_progress(world.human(), episode_id)
    assert after.production.required == 5
    assert after.production.accepted == 4
    assert after.production.progress_bp == 8_000  # the percent went DOWN with a stated reason
    assert after.plan.version == 2
    assert after.plan.previous_version == 1
    assert after.plan.denominator_changed is True
    assert "probe-4" in (after.plan.change_reason or "")
    # The outfit record has no comparable history, so only shots are claimed changed.
    assert "required shots 3 -> 4" in (after.plan.change_reason or "")
    assert "outfits" not in (after.plan.change_reason or "")
    # The set-level binding moved with the requirement set, not just the manifest.
    assert after.plan.plan_fingerprint != before.plan.plan_fingerprint
    assert after.plan.plan_revision > before.plan.plan_revision
    assert "assignment history is not persisted" in after.plan.denominator_basis


def test_an_added_outfit_without_a_manifest_change_is_a_visible_plan_change(
    planned, db_dsn
) -> None:
    """Review finding 2: a new current assignment while the manifest stays at v1.

    The denominator and the set-level fingerprint/revision move, the percent
    drops, and the projection explains the current requirement honestly (no
    comparable history is persisted, so no prior count is invented). A fresh
    database connection reproduces the same projection.
    """
    world, season_id, episode_id, _outfit = planned
    for shot in ("probe-1", "probe-2", "probe-3"):
        _shot_asset(world, season_id=season_id, episode_id=episode_id, shot_id=shot, attempt=1)
    before = world.service.episode_progress(world.human(), episode_id)
    assert before.production.required == 4  # 3 shots + 1 outfit
    assert before.production.accepted == 4
    assert before.production.progress_bp == 10_000

    # A SECOND required outfit appears (its asset still PROVISIONAL — not
    # accepted work yet); the manifest record itself is untouched.
    scarf_asset = _store_asset(
        world,
        season_id=season_id,
        episode_id=episode_id,
        object_key=f"outfits/{episode_id}/scarf.png",
        state=AssetState.PROVISIONAL,
    )
    StoryV2Store(world.db).save_bundle(
        [_assignment_for(episode_id, uuid.uuid4(), scarf_asset, outfit_id="fon-scarf")]
    )

    after = world.service.episode_progress(world.human(), episode_id)
    assert after.production.required == 5  # the denominator grew with the outfit
    assert after.production.accepted == 4  # the new outfit is not accepted work yet
    assert after.production.progress_bp == 4 * 10_000 // 5  # the percent dropped
    assert after.plan.version == 1  # the manifest record itself did not move
    assert after.plan.record_id == before.plan.record_id
    assert after.plan.plan_fingerprint != before.plan.plan_fingerprint  # the set moved
    assert after.plan.plan_revision != before.plan.plan_revision

    # No comparable assignment history is persisted: explain instead of inventing.
    assert after.plan.denominator_changed is False
    assert after.plan.change_reason is None
    assert "3 required shot(s) + 2 required outfit(s) = 5 work units" in (
        after.plan.denominator_basis
    )
    assert "no comparable historical requirement set" in after.plan.denominator_basis

    # The workbench page renders the honest explanation.
    from microdrama.review.render import render

    page = render("progress.html", progress=world.service.season_progress(world.human(), season_id))
    assert "3 required shot(s) + 2 required outfit(s) = 5 work units" in page
    assert "no comparable historical requirement set" in page

    # A fresh connection (a restarted process) reproduces the same projection.
    with Database(db_dsn, min_size=1, max_size=2).open() as fresh_db:
        from microdrama.core.idempotency import IdempotencyService
        from microdrama.core.jobs import JobService
        from microdrama.review.service import ReviewService

        restarted = ReviewService(
            fresh_db,
            world.clock,
            world.ids,
            jobs=JobService(fresh_db, world.clock, world.ids),
            idempotency=IdempotencyService(fresh_db),
            budget=world.budget,
            store=world.store,
            release_conditions_fn=world.release_conditions,
            approval_hooks=[],
            identity_lock_hook=world.identity_lock_hook,
        )
        third = restarted.episode_progress(world.human(), episode_id)
    assert third == after


def test_an_outfit_change_with_comparable_history_shows_the_exact_diff(planned) -> None:
    """When assignment history IS persisted, the exact outfit change is claimed."""
    world, season_id, episode_id, outfit_asset = planned
    record_id = world.row(
        "SELECT record_id FROM v2_contract_documents "
        "WHERE contract_type = 'SceneWardrobeAssignment' AND current "
        "AND payload->>'episode_id' = %s",
        (str(episode_id),),
    )["record_id"]

    # The assignment record moves to v2 with a DIFFERENT outfit: its superseded
    # v1 row is comparable history, so the exact removal/addition is provable.
    StoryV2Store(world.db).save_bundle(
        [_assignment_for(episode_id, record_id, outfit_asset, outfit_id="fon-scarf", version=2)]
    )
    after = world.service.episode_progress(world.human(), episode_id)
    assert after.plan.denominator_changed is True
    assert "outfits removed: fon/fon-apron" in (after.plan.change_reason or "")
    assert "outfits added: fon/fon-scarf" in (after.plan.change_reason or "")
    assert "required outfits 1 -> 1" in (after.plan.change_reason or "")
    # Shots have no comparable history here, so no shot claim is invented.
    assert "shots" not in (after.plan.change_reason or "")
    assert "assignment history is not persisted" not in after.plan.denominator_basis


def test_refresh_and_a_fresh_connection_reproduce_the_same_progress(planned, db_dsn) -> None:
    world, season_id, episode_id, _outfit = planned
    _shot_asset(world, season_id=season_id, episode_id=episode_id, shot_id="probe-1", attempt=1)
    _bump_revision(world, episode_id)
    _event(world, episode_id)
    _job(
        world,
        episode_id,
        status=JobStatus.WAITING_EXTERNAL.value,
        outcome={"internal_percent": 77},
    )

    first = world.service.episode_progress(world.human(), episode_id)
    second = world.service.episode_progress(world.human(), episode_id)
    assert first == second  # a refresh of unchanged rows is identical

    # A fresh process: a new connection and a new service instance.
    with Database(db_dsn, min_size=1, max_size=2).open() as fresh_db:
        from microdrama.core.idempotency import IdempotencyService
        from microdrama.core.jobs import JobService
        from microdrama.review.service import ReviewService

        restarted = ReviewService(
            fresh_db,
            world.clock,
            world.ids,
            jobs=JobService(fresh_db, world.clock, world.ids),
            idempotency=IdempotencyService(fresh_db),
            budget=world.budget,
            store=world.store,
            release_conditions_fn=world.release_conditions,
            approval_hooks=[],
            identity_lock_hook=world.identity_lock_hook,
        )
        third = restarted.episode_progress(world.human(), episode_id)
    assert third == first


def test_canonical_snapshot_only_with_full_provenance(planned) -> None:
    world, _season, episode_id, _outfit = planned
    human = world.human()

    # No events and revision 0: local view only, no fabricated ids.
    bare = world.service.episode_progress(human, episode_id)
    assert bare.snapshot is None

    _event(world, episode_id)
    _bump_revision(world, episode_id)
    sealed = world.service.episode_progress(human, episode_id)
    assert sealed.snapshot is not None
    assert sealed.snapshot.aggregate_id == episode_id
    assert sealed.snapshot.projection_revision == 1
    assert sealed.snapshot.source_event_ids  # real ids, at least one
    assert sealed.snapshot.accepted_work == sealed.production.accepted
    assert sealed.snapshot.required_work == sealed.production.required
    assert sealed.snapshot.production_stage == sealed.production_stage
    assert sealed.snapshot.release_stage == sealed.release_stage


def test_provider_internals_never_surface_as_progress(planned) -> None:
    world, _season, episode_id, _outfit = planned
    _job(
        world,
        episode_id,
        status=JobStatus.WAITING_EXTERNAL.value,
        attempt=3,
        outcome={"internal_percent": 77, "provider_says": "almost done"},
    )
    view = world.service.episode_progress(world.human(), episode_id)
    assert view.jobs.by_status[JobStatus.WAITING_EXTERNAL.value] == 1
    assert view.jobs.retried_jobs == 1
    payload = view.model_dump(mode="json")
    # Only durable job states appear; the provider's own numbers and narrative never do.
    assert "provider_says" not in str(payload)
    assert "internal_percent" not in str(payload)


def test_retry_failure_and_human_wait_are_distinct_states(world: World) -> None:
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, state="RENDERING")
    human = world.human()

    # A job in retry backoff: WAITING, with the retry visible.
    _job(world, episode_id, status=JobStatus.RETRY_WAIT.value, attempt=2)
    waiting = world.service.episode_progress(human, episode_id)
    assert waiting.production_stage.value == "WAITING"
    assert waiting.jobs.retried_jobs == 1
    assert "retry" in (waiting.next_action or "")

    # A failed job: BLOCKED with the failure counted.
    world.row_exec("UPDATE jobs SET status = 'FAILED' WHERE episode_id = %s", (episode_id,))
    blocked = world.service.episode_progress(human, episode_id)
    assert blocked.production_stage.value == "BLOCKED"
    assert blocked.jobs.failed_jobs == 1
    assert any("FAILED" in blocker for blocker in blocked.blockers)

    # The human gate: AWAITING_FINAL_REVIEW waits on the owner decision.
    gate_season, _ = world.season(approved=True)
    gate_episode = world.episode(gate_season, state="AWAITING_FINAL_REVIEW")
    gate_view = world.service.episode_progress(human, gate_episode)
    assert gate_view.production_stage.value == "WAITING"
    assert "Gate 2" in (gate_view.next_action or "")


def test_production_and_release_are_independent(world: World) -> None:
    season_id, episode_id, package = world.ready_episode()
    human = world.human()

    # Before Gate 2: production waits on the human decision, release not started.
    awaiting = world.service.episode_progress(human, episode_id)
    assert awaiting.production_stage.value == "WAITING"
    assert awaiting.release_stage.value == "PLANNED"

    # The real Gate 2 approval finishes production; release is still only planned.
    world.service.decide_episode(human, episode_id, world.gate2_command(episode_id, package))
    approved = world.service.episode_progress(human, episode_id)
    assert approved.production_stage.value == "COMPLETE"
    assert approved.release_stage.value == "PLANNED"
    assert approved.release_slots == []

    # A scheduled (not yet verified) post keeps release RUNNING.
    approval_id = world.approvals(episode_id)[0]["id"]
    master = package.media[0]
    with world.db.transaction() as tx:
        tx.execute(
            "INSERT INTO platform_posts (id, series_id, episode_id, part, locale, platform, "
            "account_ref, release_slot, dedupe_key, slot_kind, required, release_package_id, "
            "approval_event_id, asset_id, asset_sha256, state, iana_zone, local_time, "
            "scheduled_utc, client_token) VALUES (%s,%s,%s,0,'th-TH','YOUTUBE','acct:yt',"
            "'full',%s,'FULL_EPISODE',true,%s,%s,%s,%s,'SCHEDULED','Asia/Bangkok','18:00',"
            "%s,%s)",
            (
                uuid.uuid4(),
                season_id,
                episode_id,
                "a" * 64,
                package.package_id,
                approval_id,
                master.asset_id,
                master.sha256,
                world.clock.now(),
                f"probe-{uuid.uuid4().hex}",
            ),
        )
    scheduled = world.service.episode_progress(human, episode_id)
    assert scheduled.production_stage.value == "COMPLETE"
    assert scheduled.release_stage.value == "RUNNING"
    assert scheduled.release_slots[0].state is ReleaseState.SCHEDULED

    # Provider readback verified: release COMPLETE. A schedule alone never is.
    world.row_exec(
        "UPDATE platform_posts SET state = 'PUBLISHED_VERIFIED', external_id = 'yt-1', "
        "verified_at = clock_timestamp(), verified_fields = '[\"external_id\"]'::jsonb "
        "WHERE episode_id = %s",
        (episode_id,),
    )
    verified = world.service.episode_progress(human, episode_id)
    assert verified.release_stage.value == "COMPLETE"


def test_terminal_outcome_blocks_production(planned, world: World) -> None:
    _world, _season, episode_id, _outfit = planned
    world.row_exec(
        "UPDATE episodes SET state = 'RENDERING', outcome = 'BUDGET_EXHAUSTED' WHERE id = %s",
        (episode_id,),
    )
    view = world.service.episode_progress(world.human(), episode_id)
    assert view.production_stage.value == "BLOCKED"
    assert "BUDGET_EXHAUSTED" in view.blockers[0]


def test_cost_comes_from_the_budget_read(planned, world: World) -> None:
    _world, _season, episode_id, _outfit = planned
    view = world.service.episode_progress(world.human(), episode_id)
    assert view.cost is not None
    assert view.cost.remaining_micro_usd >= 0  # the real episode account read

    no_budget_season, _ = world.season(approved=True)
    no_budget_episode = world.episode(no_budget_season)
    unknown = world.service.episode_progress(world.human(), no_budget_episode)
    assert unknown.cost is None  # unknown, not zero


def test_season_progress_covers_every_episode(planned, world: World) -> None:
    _world, season_id, episode_id, _outfit = planned
    second = world.episode(season_id, number=2, state="PLANNED")
    view = world.service.season_progress(world.human(), season_id)
    assert view.season_id == season_id
    assert [item.episode_id for item in view.episodes] == [episode_id, second]
    assert view.episodes[1].production_stage.value == "PLANNED"


def test_direct_use_of_the_projection_matches_the_service(planned) -> None:
    world, _season, episode_id, _outfit = planned
    projection = ProgressProjection(world.db, world.budget)
    with world.db.transaction(readonly=True) as tx:
        row = dict(tx.fetchone("SELECT * FROM episodes WHERE id = %s", (episode_id,)))
    assert projection.episode_view(row) == world.service.episode_progress(world.human(), episode_id)

"""Schedule firing: due schedules become durable jobs or direct actions (T029).

``TriggerScheduler.fire`` is invoked by the deployment timer (systemd/service
loop calling ``python -m microdrama.scheduling.fire``, or the demo runner) and
is safe to call concurrently or after a crash:

- job-schedules discover their due work from durable state (seasons, episodes,
  posts, operations) and enqueue frozen job types with period-bucketed semantic
  keys — one enqueue per period per entity, ever;
- action-schedules run their sweep directly: they are the "independent timer"
  the SPEC requires, never queued behind a blocked queue (W05 render dispatch
  under the episode's owned pod lease, W05 render-op reconciliation, W12
  janitors, and W03's cadence episode creation);
- the progression is complete without any runner method (build-review F01):
  the cadence schedule creates the next approved episode, W05 dispatches the
  initial routed attempts and accepts verified outputs, W06 proposes assembly
  only for a complete accepted shot set, W07 chains technical → observation →
  comparison → repairs → package, and W09 submits due slots and polls both
  SUBMITTED and PROCESSING posts;
- firing state (``schedule_state`` rows) only prevents busy-spinning; missing
  state can never duplicate an effect because the semantic keys dedupe.

No schedule reads a secret, checks a capability or evaluates a gate: it only
proposes work. The owning services stay the sole authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from microdrama.contracts.jobs import EpisodeStepInput, SeasonStepInput
from microdrama.persistence.db import Tx


@dataclass
class FireReport:
    fired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    enqueued_jobs: int = 0
    actions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fired": self.fired,
            "skipped": self.skipped,
            "errors": self.errors,
            "enqueued_jobs": self.enqueued_jobs,
            "actions": self.actions,
        }


def load_last_fired(tx: Tx) -> dict[str, datetime]:
    rows = tx.fetchall("SELECT schedule_id, last_fired_at FROM schedule_state")
    return {row["schedule_id"]: row["last_fired_at"] for row in rows}


def record_fired(tx: Tx, schedule_id: str, now: datetime) -> None:
    tx.execute(
        "INSERT INTO schedule_state (schedule_id, last_fired_at, fired_count) "
        "VALUES (%s, %s, 1) ON CONFLICT (schedule_id) DO UPDATE "
        "SET last_fired_at = excluded.last_fired_at, "
        "fired_count = schedule_state.fired_count + 1",
        (schedule_id, now),
    )


def _manifest_loader(db):
    def load(episode_id):
        from microdrama.contracts.season import ShotManifest

        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
                (episode_id,),
            )
        if row is None:
            raise LookupError(f"no CURRENT shot manifest for episode {episode_id}")
        return ShotManifest.model_validate(row["body"])

    return load


def _accepted_render_assets(db, episode_id) -> set[str]:
    """Shot ids with at least one ACCEPTED render asset (object-key order stable)."""
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT object_key FROM assets WHERE episode_id = %s "
            "AND object_key LIKE 'renders/%%' AND state = 'ACCEPTED'",
            (episode_id,),
        )
    shots: set[str] = set()
    for row in rows:
        parts = str(row["object_key"]).split("/")
        if len(parts) >= 4:
            shots.add(parts[2])
    return shots


class TriggerScheduler:
    """Fires the due schedules of one catalog against the composed world."""

    def __init__(self, world, catalog) -> None:
        self.world = world
        self.catalog = catalog

    # --- public ---------------------------------------------------------------------------

    def fire(self, *, now: datetime | None = None, only: set[str] | None = None) -> FireReport:
        instant = now or self.world.fakes.clock.now()
        report = FireReport()
        with self.world.db.transaction(readonly=True) as tx:
            last_fired = load_last_fired(tx)
        for schedule in self.catalog.due(instant, last_fired=last_fired):
            if only is not None and schedule.schedule_id not in only:
                continue
            handler = getattr(self, f"_{schedule.schedule_id.replace('-', '_')}", None)
            if handler is None:
                report.skipped.append(schedule.schedule_id)
                continue
            # One schedule's failure never kills the timer: the error is
            # recorded (skipped, with detail) and the next firing retries from
            # durable state — semantic keys keep every effect single.
            try:
                handler(instant, report)
            except Exception as exc:  # noqa: BLE001 - the timer must survive
                report.skipped.append(schedule.schedule_id)
                report.errors.append(f"{schedule.schedule_id}: {exc}")
                continue
            report.fired.append(schedule.schedule_id)
            with self.world.db.transaction() as tx:
                record_fired(tx, schedule.schedule_id, instant)
        return report

    # --- enqueue helpers --------------------------------------------------------------------

    def _enqueue(
        self,
        job_type: str,
        payload,
        report: FireReport,
        *,
        semantic_key: str,
        episode_id=None,
        season_id=None,
    ) -> None:
        with self.world.db.transaction() as tx:
            result = self.world.jobs.enqueue(
                tx,
                job_type=job_type,
                semantic_key=semantic_key,
                payload=payload,
                episode_id=episode_id,
                season_id=season_id,
            )
        if result.created:
            report.enqueued_jobs += 1

    def _period(self, schedule_id: str, now: datetime) -> str:
        schedule = next(s for s in self.catalog.schedules if s.schedule_id == schedule_id)
        return self.catalog.period_key(schedule, now)

    # --- job schedules ------------------------------------------------------------------------

    def _w01_research(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            seasons = tx.fetchall(
                "SELECT id FROM seasons WHERE state = 'PROPOSED' ORDER BY created_at"
            )
        for season in seasons:
            self._enqueue(
                "research.collect_and_propose",
                SeasonStepInput(season_id=season["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w01-research', now)}:{season['id']}",
                season_id=season["id"],
            )

    def _w02_compile_backstop(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            seasons = tx.fetchall(
                "SELECT s.id, s.approved_scope_version FROM seasons s "
                "WHERE s.state = 'SEASON_APPROVED' AND NOT EXISTS ("
                "  SELECT 1 FROM canon_versions c WHERE c.season_id = s.id AND c.kind = 'PLANNED')"
            )
        for season in seasons:
            self._enqueue(
                "story.compile_season",
                SeasonStepInput(season_id=season["id"], trigger="backstop"),
                report,
                semantic_key=f"{self._period('w02-compile-backstop', now)}:{season['id']}",
                season_id=season["id"],
            )

    def _w03_episode_cadence(self, now: datetime, report: FireReport) -> None:
        """Create the next PLANNED episode inside the approved scope's count.

        F01: episode creation is cadence configuration, so the cadence schedule
        owns it — the same insert the integrator performed by hand (approved
        scope hash bound, sequential number), idempotent through the
        (season, episode_number) uniqueness the schema enforces.
        """
        from microdrama.contracts.season import SeasonScope
        from microdrama.persistence.db import insert_row

        with self.world.db.transaction(readonly=True) as tx:
            seasons = tx.fetchall(
                "SELECT s.id, s.approved_scope_hash, p.scope FROM seasons s "
                "JOIN season_proposals p ON p.season_id = s.id AND p.status = 'APPROVED' "
                "WHERE s.state = 'SEASON_APPROVED' ORDER BY s.created_at"
            )
        created = 0
        for season in seasons:
            scope = SeasonScope.model_validate(season["scope"])
            with self.world.db.transaction() as tx:
                count = int(
                    tx.fetchval(
                        "SELECT count(*) FROM episodes WHERE season_id = %s", (season["id"],)
                    )
                    or 0
                )
                if count >= scope.expected_episode_count:
                    continue
                insert_row(
                    tx,
                    "episodes",
                    {
                        "id": uuid4(),
                        "season_id": season["id"],
                        "episode_number": count + 1,
                        "state": "PLANNED",
                        "approved_scope_hash": season["approved_scope_hash"],
                    },
                )
                created += 1
        report.actions["w03-cadence"] = {"episodes_created": created}

    def _w03_write(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id FROM episodes e JOIN seasons s ON s.id = e.season_id "
                "WHERE e.state = 'PLANNED' AND s.state = 'SEASON_APPROVED' "
                "AND EXISTS (SELECT 1 FROM canon_versions c "
                "  WHERE c.season_id = s.id AND c.kind = 'PLANNED') "
                # IMP-01: later episodes wait for the episode-one identity lock —
                # proposing them earlier only produces typed refusals.
                "AND (e.episode_number = 1 OR e.identity_lock_id IS NOT NULL) "
                "AND e.id NOT IN (SELECT episode_id FROM scripts WHERE status = 'CURRENT')"
            )
        for episode in episodes:
            self._enqueue(
                "story.write_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="cadence"),
                report,
                semantic_key=f"{self._period('w03-write', now)}:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w04_references(self, now: datetime, report: FireReport) -> None:
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state IN ('SCRIPTING', 'REFERENCES') "
                "AND EXISTS (SELECT 1 FROM scripts s WHERE s.episode_id = e.id "
                "  AND s.status = 'CURRENT')"
            )
        for episode in episodes:
            self._enqueue(
                "references.prepare_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w04-references', now)}:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w06_edit(self, now: datetime, report: FireReport) -> None:
        """Assemble ONLY episodes whose accepted shot set is complete (F01).

        Proposing assembly before every manifest shot has an ACCEPTED render
        produced premature assemblies from partial media; completeness is
        established against the CURRENT manifest before the job is proposed.
        """
        from microdrama.contracts.season import ShotManifest

        with self.world.db.transaction(readonly=True) as tx:
            candidates = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'RENDERING' AND NOT EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main')"
            )
        assemble = []
        for row in candidates:
            with self.world.db.transaction(readonly=True) as tx:
                manifest_row = tx.fetchone(
                    "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
                    (row["id"],),
                )
            if manifest_row is None:
                continue
            manifest = ShotManifest.model_validate(manifest_row["body"])
            if {shot.shot_id for shot in manifest.shots} <= _accepted_render_assets(
                self.world.db, row["id"]
            ):
                assemble.append(row)
        with self.world.db.transaction(readonly=True) as tx:
            variants = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'AI_REVIEW' AND EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main' AND m.output_asset_id IS NOT NULL)"
                " AND NOT EXISTS (SELECT 1 FROM edit_manifests m2 "
                "  WHERE m2.episode_id = e.id AND m2.variant_key <> 'main')"
            )
        for episode in assemble:
            self._enqueue(
                "edit.assemble_episode",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w06-edit', now)}:a:{episode['id']}",
                episode_id=episode["id"],
            )
        for episode in variants:
            self._enqueue(
                "edit.variants_and_hooks",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{self._period('w06-edit', now)}:v:{episode['id']}",
                episode_id=episode["id"],
            )

    def _w07_qa(self, now: datetime, report: FireReport) -> None:
        """The full QA continuation: technical → observe → compare → repairs → package.

        F01: each stage discovers its own due work from durable state and
        enqueues the frozen job type with a period-bucketed key — no runner
        method supplies the progression. Media changes (new assets from any
        lane, repairs included) re-run the technical pass, so a repaired episode
        re-collects its evidence before a new package is sealed.
        """
        period = self._period("w07-qa", now)
        # --- Pass 0: technical QA on changed media --------------------------------------
        with self.world.db.transaction(readonly=True) as tx:
            technical = tx.fetchall(
                "SELECT e.id, "
                "(SELECT max(a.created_at) FROM assets a WHERE a.episode_id = e.id) AS media_at "
                "FROM episodes e WHERE e.state = 'AI_REVIEW' AND EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main' AND m.output_asset_id IS NOT NULL) "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM jobs j WHERE j.episode_id = e.id "
                "  AND j.job_type = 'qa.technical' AND j.status = 'SUCCEEDED' "
                "  AND j.updated_at >= (SELECT max(a.created_at) FROM assets a "
                "    WHERE a.episode_id = e.id))"
            )
        for episode in technical:
            self._enqueue(
                "qa.technical",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{period}:tech:{episode['id']}",
                episode_id=episode["id"],
            )

        # --- Pass A: observation of the CURRENT master ----------------------------------
        with self.world.db.transaction(readonly=True) as tx:
            observe = tx.fetchall(
                "SELECT e.id, m.output_asset_id FROM episodes e "
                "JOIN LATERAL (SELECT m2.output_asset_id FROM edit_manifests m2 "
                "  WHERE m2.episode_id = e.id AND m2.variant_key = 'main' "
                "  AND m2.output_asset_id IS NOT NULL "
                "  ORDER BY m2.version DESC LIMIT 1) m ON true "
                "WHERE e.state = 'AI_REVIEW' "
                "AND EXISTS (SELECT 1 FROM jobs j WHERE j.episode_id = e.id "
                "  AND j.job_type = 'qa.technical' AND j.status = 'SUCCEEDED')"
            )
        for episode in observe:
            asset = None
            with self.world.db.transaction(readonly=True) as tx:
                asset = tx.fetchone(
                    "SELECT sha256, descriptor FROM assets WHERE id = %s",
                    (episode["output_asset_id"],),
                )
            if asset is None:
                continue
            with self.world.db.transaction(readonly=True) as tx:
                observed = tx.fetchval(
                    "SELECT id FROM qa_observations WHERE episode_id = %s "
                    "AND media_sha256 ? %s LIMIT 1",
                    (episode["id"], asset["sha256"]),
                )
            if observed is not None:
                continue
            request = self._observation_request(episode["id"], episode["output_asset_id"], asset)
            self._enqueue(
                "qa.observe",
                request,
                report,
                semantic_key=f"{period}:obs:{episode['id']}",
                episode_id=episode["id"],
            )

        # --- Pass B: comparison of the latest observation -------------------------------
        with self.world.db.transaction(readonly=True) as tx:
            compare = tx.fetchall(
                "SELECT e.id, o.id AS observation_id, o.report_sha256 FROM episodes e "
                "JOIN LATERAL (SELECT o2.id, o2.report_sha256 FROM qa_observations o2 "
                "  WHERE o2.episode_id = e.id ORDER BY o2.frozen_at DESC LIMIT 1) o ON true "
                "WHERE e.state = 'AI_REVIEW' AND NOT EXISTS ("
                "  SELECT 1 FROM qa_findings f WHERE f.observation_id = o.id)"
            )
        for episode in compare:
            request = self._comparison_request(
                episode["id"], episode["observation_id"], episode["report_sha256"]
            )
            if request is None:
                continue
            self._enqueue(
                "qa.compare",
                request,
                report,
                semantic_key=f"{period}:cmp:{episode['observation_id']}",
                episode_id=episode["id"],
            )

        # --- Repairs: the latest cycle's REPAIRABLE findings, once per cycle -------------
        with self.world.db.transaction(readonly=True) as tx:
            repairable = tx.fetchall(
                "SELECT e.id, (SELECT max(f.qa_cycle) FROM qa_findings f "
                "  WHERE f.episode_id = e.id) AS cycle FROM episodes e "
                "WHERE e.state IN ('SCRIPTING', 'REFERENCES', 'RENDERING', 'ASSEMBLING', "
                "  'AI_REVIEW', 'AWAITING_FINAL_REVIEW') "
                "AND EXISTS (SELECT 1 FROM qa_findings f WHERE f.episode_id = e.id "
                "  AND f.outcome = 'REPAIRABLE' AND f.resolution = 'OPEN')"
            )
        for episode in repairable:
            with self.world.db.transaction(readonly=True) as tx:
                planned = tx.fetchone(
                    "SELECT id FROM repair_plans WHERE episode_id = %s "
                    "AND trigger = 'QA_FINDING' AND qa_cycle = %s "
                    "AND status IN ('PLANNED', 'RESERVED', 'EXECUTING')",
                    (episode["id"], episode["cycle"]),
                )
            if planned is not None:
                continue
            self._enqueue(
                "qa.plan_repairs",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{period}:rep:{episode['id']}:{episode['cycle']}",
                episode_id=episode["id"],
            )

        # --- Package: clean evidence, one open package at a time -------------------------
        with self.world.db.transaction(readonly=True) as tx:
            packaged = tx.fetchall(
                "SELECT e.id FROM episodes e WHERE e.state = 'AI_REVIEW' AND EXISTS ("
                "  SELECT 1 FROM edit_manifests m WHERE m.episode_id = e.id "
                "  AND m.variant_key = 'main' AND m.output_asset_id IS NOT NULL) "
                "AND NOT EXISTS (SELECT 1 FROM qa_findings f WHERE f.episode_id = e.id "
                "  AND f.resolution = 'OPEN' AND (f.outcome IN ('REPAIRABLE', 'BLOCKED') "
                "    OR f.severity = 'CRITICAL')) "
                # MD-010: no package before the comparison pass has produced its
                # findings for this media (a PASS row counts — the point is that
                # Pass A and Pass B both ran).
                "AND EXISTS (SELECT 1 FROM qa_findings f2 WHERE f2.episode_id = e.id) "
                "AND NOT EXISTS (SELECT 1 FROM release_packages p WHERE p.episode_id = e.id "
                "  AND p.status IN ('DRAFT', 'READY', 'BLOCKED')) "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.episode_id = e.id "
                "  AND j.job_type = 'review.prepare_package' AND j.status IN "
                "  ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'WAITING_EXTERNAL'))"
            )
        for episode in packaged:
            self._enqueue(
                "review.prepare_package",
                EpisodeStepInput(episode_id=episode["id"], trigger="scheduled"),
                report,
                semantic_key=f"{period}:pkg:{episode['id']}",
                episode_id=episode["id"],
            )

    @staticmethod
    def _observation_request(episode_id, asset_id, asset_row):
        from uuid import uuid4

        from microdrama.contracts.qa import (
            MediaUnderReview,
            NeutralQuestion,
            ObservationRequest,
        )

        duration = (asset_row["descriptor"] or {}).get("media", {}).get("duration_ms", 0)
        return ObservationRequest(
            request_id=uuid4(),
            episode_id=episode_id,
            media=[
                MediaUnderReview(
                    asset_id=asset_id, asset_sha256=asset_row["sha256"], duration_ms=duration
                )
            ],
            questions=[
                NeutralQuestion(question_id="q1", text="What is visibly present in the frame?")
            ],
        )

    def _comparison_request(self, episode_id, observation_id, report_sha256):
        from uuid import uuid4

        from microdrama.contracts.qa import ComparisonRequest

        with self.world.db.transaction(readonly=True) as tx:
            script = tx.fetchone(
                "SELECT id, version, body_hash FROM scripts WHERE episode_id = %s "
                "AND status = 'CURRENT'",
                (episode_id,),
            )
            canon = tx.fetchone(
                "SELECT version, facts_hash FROM canon_versions WHERE season_id = "
                "(SELECT season_id FROM episodes WHERE id = %s) AND kind = 'PLANNED' "
                "ORDER BY version DESC LIMIT 1",
                (episode_id,),
            )
        if script is None or canon is None:
            return None
        return ComparisonRequest(
            request_id=uuid4(),
            episode_id=episode_id,
            observation_report_id=observation_id,
            observation_report_sha256=report_sha256,
            script_id=script["id"],
            script_version=script["version"],
            script_sha256=script["body_hash"],
            canon_version=canon["version"],
            canon_sha256=canon["facts_hash"],
        )

    def _w09_publish_submit(self, now: datetime, report: FireReport) -> None:
        """Submit due SCHEDULED slots through the ordinary command path (F01).

        Discovery only: a slot is due when its scheduled instant passed and its
        dependency slots (if any) are verified; the publishing service remains
        the sole authority over capability, disclosure and idempotency.
        """
        from microdrama.publishing.commands import publication_command_for_post

        period = self._period("w09-publish-submit", now)
        with self.world.db.transaction(readonly=True) as tx:
            posts = tx.fetchall(
                "SELECT * FROM platform_posts WHERE state = 'SCHEDULED' "
                "AND scheduled_utc <= %s ORDER BY scheduled_utc",
                (now,),
            )
        submitted = held = 0
        for post in posts:
            deps = post["depends_on"] or []
            if deps:
                with self.world.db.transaction(readonly=True) as tx:
                    verified = {
                        row["dedupe_key"]
                        for row in tx.fetchall(
                            "SELECT dedupe_key FROM platform_posts WHERE episode_id = %s "
                            "AND state = 'PUBLISHED_VERIFIED'",
                            (post["episode_id"],),
                        )
                    }
                if not set(deps) <= verified:
                    held += 1
                    continue
            with self.world.db.transaction(readonly=True) as tx:
                package = tx.fetchone(
                    "SELECT id, body FROM release_packages WHERE episode_id = %s "
                    "AND status = 'APPROVED' ORDER BY version DESC LIMIT 1",
                    (post["episode_id"],),
                )
            if package is None:
                continue
            command = publication_command_for_post(
                None,
                post=dict(post),
                package_body=package["body"],
                approval_event_id=post["approval_event_id"],
            )
            self._enqueue(
                "publish.submit_slot",
                command,
                report,
                semantic_key=f"{period}:{post['id']}",
                episode_id=post["episode_id"],
            )
            submitted += 1
        report.actions["w09-submit"] = {"proposed": submitted, "waiting_deps": held}

    def _w09_publish_poll(self, now: datetime, report: FireReport) -> None:
        from microdrama.contracts.jobs import PlatformPostRef

        with self.world.db.transaction(readonly=True) as tx:
            # F01: an adapter may return PROCESSING directly at submission; that
            # row needs a poll job exactly like a SUBMITTED one.
            posts = tx.fetchall(
                "SELECT id FROM platform_posts WHERE state IN ('SUBMITTED', 'PROCESSING') "
                "AND updated_at <= %s ORDER BY updated_at",
                (now,),
            )
        for post in posts:
            self._enqueue(
                "publish.poll_status",
                PlatformPostRef(platform_post_id=post["id"]),
                report,
                semantic_key=f"{self._period('w09-publish-poll', now)}:{post['id']}",
            )

    def _w11_analytics(self, now: datetime, report: FireReport) -> None:
        from microdrama.contracts.jobs import MetricWindowInput

        with self.world.db.transaction(readonly=True) as tx:
            verified = tx.fetchall(
                "SELECT id FROM platform_posts WHERE state = 'PUBLISHED_VERIFIED'"
            )
        for row in verified:
            for window in self.world.analytics.due_windows(row["id"]):
                self._enqueue(
                    "analytics.snapshot",
                    MetricWindowInput(platform_post_id=row["id"], window=window.window),
                    report,
                    semantic_key=(
                        f"{self._period('w11-analytics', now)}:{row['id']}:{window.window.value}"
                    ),
                )

    # --- action schedules (never queued) --------------------------------------------------------

    def _w05_render_dispatch(self, now: datetime, report: FireReport) -> None:
        """Dispatch the initial routed attempts for un-dispatched manifest shots (F01).

        An episode entering RENDERING gets its pod lease first (claim + ensure:
        an OWNED pod exists before any paid dispatch), then every shot without a
        render.shot attempt dispatches through the ordinary router — the same
        reserve→request→job→submit path the repair lane uses. The lease is
        released by the existing stop-for-human-wait before Gate 2, so an owned
        pod demonstrably existed during rendering.
        """
        from microdrama.contracts.season import ShotManifest
        from microdrama.rendering.leases import PodLeaseClaimRequest
        from microdrama.rendering.routing import RouterShotDispatch

        dispatch_port = RouterShotDispatch(
            self.world.db,
            self.world.comfy,
            self.world.jobs,
            self.world.router,
            self.world.catalog,
            manifest_for=_manifest_loader(self.world.db),
            bindings_for=self.world.references.render_request_bindings,
        )
        with self.world.db.transaction(readonly=True) as tx:
            episodes = tx.fetchall(
                "SELECT e.id, e.episode_number FROM episodes e "
                "WHERE e.state = 'RENDERING' ORDER BY e.episode_number"
            )
        dispatched = leases = 0
        for episode in episodes:
            manifest_row = None
            with self.world.db.transaction(readonly=True) as tx:
                manifest_row = tx.fetchone(
                    "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
                    (episode["id"],),
                )
            if manifest_row is None:
                continue
            manifest = ShotManifest.model_validate(manifest_row["body"])
            pending = []
            for shot in manifest.shots:
                used = dispatch_port.attempts_used(
                    episode_number=int(episode["episode_number"]), shot_id=shot.shot_id
                )
                if used == 0:
                    pending.append(shot)
            if not pending:
                continue
            # The owned pod precedes every dispatch (pilot rule: one episode owns
            # the GPU window). Claim is idempotent per semantic key.
            handle = self.world.leases.claim(
                PodLeaseClaimRequest(
                    episode_id=episode["id"],
                    semantic_key=f"pod.lease:{episode['id']}:render",
                    gpu_type="FAKE-GPU-24GB",
                    host_ram_gb=32,
                )
            )
            self.world.leases.ensure_pod(handle.lease.lease_id)
            leases += 1
            for shot in pending:
                used = dispatch_port.attempts_used(
                    episode_number=int(episode["episode_number"]), shot_id=shot.shot_id
                )
                dispatch_port.dispatch_repair(
                    episode_id=episode["id"],
                    episode_number=int(episode["episode_number"]),
                    shot_id=shot.shot_id,
                    attempt_number=used + 1,
                )
                dispatched += 1
        report.actions["w05-dispatch"] = {"shots": dispatched, "leases": leases}

    def _w05_render_poll(self, now: datetime, report: FireReport) -> None:
        """Reconcile stale in-flight render operations (submit/poll/recover, T013)."""
        from microdrama.contracts.enums import PrincipalKind, ProviderOperationState
        from microdrama.contracts.principals import Principal

        monitor = Principal(principal_id="svc:schedule-render", kind=PrincipalKind.SCHEDULER)
        from microdrama.contracts.enums import AssetState
        from microdrama.persistence.assets import asset_revision, set_asset_state

        with self.world.db.transaction(readonly=True) as tx:
            # F01: filter by the job type that owns the operation, never by a
            # provider string — the composed fake persists 'fake-comfy', which
            # the old 'comfy' filter silently missed.
            stale = tx.fetchall(
                "SELECT po.id, po.job_id FROM provider_operations po "
                "WHERE po.state IN ('PENDING_SUBMIT', 'SUBMITTED', 'RUNNING') "
                "AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = po.job_id "
                "  AND j.job_type = 'render.shot') "
                "AND po.updated_at <= %s ORDER BY po.created_at",
                (now,),
            )
        polled = resolved = accepted = 0
        for operation in stale:
            try:
                status = self.world.comfy.poll(operation["id"])
            except Exception:  # noqa: BLE001 - ambiguous outcomes need reconcile, not death
                continue
            polled += 1
            if status.state is ProviderOperationState.SUCCEEDED and operation["job_id"]:
                for asset in status.assets:
                    with self.world.db.transaction() as tx:
                        set_asset_state(
                            tx,
                            asset.asset_id,
                            AssetState.ACCEPTED,
                            expected_revision=asset_revision(tx, asset.asset_id),
                        )
                    accepted += 1
                self.world.jobs.resolve_reconciliation(
                    operation["job_id"],
                    actor=monitor,
                    resolution="SUCCEEDED",
                    evidence=f"scheduled poll: operation {operation['id']} succeeded",
                    now=now,
                )
                resolved += 1
        report.actions["w05"] = {
            "polled": polled,
            "resolved": resolved,
            "assets_accepted": accepted,
        }

    def _w12_workers_janitor(self, now: datetime, report: FireReport) -> None:
        sweep = self.world.workers_janitor.sweep(now=now)
        report.actions["w12-workers"] = {
            "steps": len(sweep.steps),
            "failures": len(sweep.failures),
        }

    def _w12_gpu_janitor(self, now: datetime, report: FireReport) -> None:
        sweep = self.world.gpu_janitor.sweep()
        report.actions["w12-gpu"] = {
            "stopped_pods": len(sweep.stopped_pods),
            "orphan_pods": len(sweep.orphan_pods),
            "failures": len(sweep.failures),
        }


__all__ = ["FireReport", "TriggerScheduler", "load_last_fired", "record_fired"]

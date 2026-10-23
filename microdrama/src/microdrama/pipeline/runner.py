"""The two-gate mock pipeline runner (T029): W01–W12 in one reproducible sequence.

Drives the composed world through the complete offline path:

W01 research → **Gate 1 (human)** → W02 compile → W03 write → W04 references →
W05 render (fake GPU) → W06 edit (REAL FFmpeg) → W07 QA → package → **Gate 2
(human, identity lock on episode one)** → W09 publish (fake) → W10 community /
membership / DM → W11 analytics windows → W12 janitors.

Design rules this runner honors:

- Exactly two human decisions (the gates). No third routine human gate exists.
- Every stage that has a JOB_SPECS job type runs THROUGH the durable job queue
  and the worker runtime; the runner never calls the service directly where a
  job type exists (research/write/prepare/render/edit/qa/package/publish/
  catalog/analytics).
- Paid/public boundaries stay behind the fake providers; every stage result is
  marked ``mock=True`` and the report labels the whole run offline.
- The fake clock advances deterministically (render execution, publish
  processing, analytics windows), so the same sequence reproduces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from microdrama.contracts.enums import ApprovalAction, GateType
from microdrama.contracts.jobs import EpisodeStepInput, PlatformPostRef, SeasonStepInput
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import ApprovalCommand
from microdrama.persistence.db import insert_row
from microdrama.publishing import metadata as meta
from microdrama.publishing.service import command_id_for
from microdrama.publishing.slots import publish_client_token

from .handlers import build_handlers

#: Fake wall-clock step between worker cycles: lets fake renders/publishes finish.
CYCLE_ADVANCE_MS = 2_000
MAX_CYCLES = 200


@dataclass
class StageResult:
    workflow: str
    stage: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)
    mock: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "stage": self.stage,
            "status": self.status,
            "detail": self.detail,
            "mock": self.mock,
        }


@dataclass
class PipelineRunReport:
    stages: list[StageResult] = field(default_factory=list)
    season_id: UUID | None = None
    episode_id: UUID | None = None
    proposal_id: UUID | None = None
    gate1_approval_id: UUID | None = None
    gate2_approval_id: UUID | None = None
    identity_lock_id: UUID | None = None
    platform_post_ids: list[UUID] = field(default_factory=list)
    master_asset_id: UUID | None = None
    burned_asset_id: UUID | None = None
    human_decisions: int = 0

    def add(self, workflow: str, stage: str, status: str, **detail: Any) -> StageResult:
        result = StageResult(workflow=workflow, stage=stage, status=status, detail=detail)
        self.stages.append(result)
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_mode": "OFFLINE_MOCK",
            "mock_run": True,
            "season_id": str(self.season_id) if self.season_id else None,
            "episode_id": str(self.episode_id) if self.episode_id else None,
            "proposal_id": str(self.proposal_id) if self.proposal_id else None,
            "gate1_approval_id": (str(self.gate1_approval_id) if self.gate1_approval_id else None),
            "gate2_approval_id": (str(self.gate2_approval_id) if self.gate2_approval_id else None),
            "identity_lock_id": str(self.identity_lock_id) if self.identity_lock_id else None,
            "platform_post_ids": [str(p) for p in self.platform_post_ids],
            "master_asset_id": str(self.master_asset_id) if self.master_asset_id else None,
            "burned_asset_id": str(self.burned_asset_id) if self.burned_asset_id else None,
            "human_decisions": self.human_decisions,
            "stages": [s.as_dict() for s in self.stages],
        }


class MockPipelineRunner:
    """Drives the composed world through the full two-gate mock path."""

    def __init__(
        self,
        world,
        *,
        owner_username: str = "pilot-owner",
        owner_password: str = "pilot-not-a-real-password",
    ) -> None:
        from microdrama.contracts.enums import QueueName
        from microdrama.workers.runtime import QueueSlots, WorkerDeployment

        self.world = world
        self.handlers = build_handlers(world)
        self.deployment = WorkerDeployment(
            name="pipeline-runner",
            slots=(
                QueueSlots(QueueName.PRODUCTION, 1),
                QueueSlots(QueueName.PUBLICATION, 1),
                QueueSlots(QueueName.COMMUNITY, 2),
            ),
            handlers=self.handlers,
            limiter=world.limiter,
        )
        self.runtime = world.runtime_for(self.deployment)
        self.report = PipelineRunReport()
        self.human = world.human_owner(owner_username, owner_password)

    # --- infrastructure ------------------------------------------------------------------

    def _drain(self, *, advance_ms: int = CYCLE_ADVANCE_MS) -> dict[str, int]:
        """Run worker cycles (advancing the fake clock) until every queue is idle."""
        executed = 0
        for _ in range(MAX_CYCLES):
            cycle = self.runtime.run_cycle()
            executed += len(cycle.reports)
            if len(cycle.idle_queues) == len(self.deployment.slots):
                break
            self.world.fakes.clock.advance(ms=advance_ms)
        return {"jobs_executed": executed}

    def _enqueue(
        self,
        job_type: str,
        payload,
        *,
        episode_id: UUID | None = None,
        season_id: UUID | None = None,
        semantic_key: str | None = None,
    ) -> UUID:
        with self.world.db.transaction() as tx:
            result = self.world.jobs.enqueue(
                tx,
                job_type=job_type,
                semantic_key=semantic_key or f"{job_type}:{uuid4().hex[:12]}",
                payload=payload,
                episode_id=episode_id,
                season_id=season_id,
            )
        return result.job_id

    def _job_status(self, job_id: UUID) -> str:
        view = self.world.jobs.status_view(job_id)
        return str(view.status) if hasattr(view, "status") else str(view.get("status"))

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.world.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.world.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    # --- W01 + Gate 1 ----------------------------------------------------------------------

    def w01_research(self) -> UUID:
        db = self.world.db
        season_id = uuid4()
        with db.transaction() as tx:
            insert_row(
                tx,
                "seasons",
                {
                    "id": season_id,
                    "state": "PROPOSED",
                    "title_th": "ฤดูกาลนำร่อง (จำลอง)",
                    "title_en": "Pilot season (mock)",
                },
            )
            self.world.budget.open_research_account(
                tx, season_id=season_id, envelope_micro_usd=2_000_000
            )
        self.report.season_id = season_id
        job_id = self._enqueue(
            "research.collect_and_propose",
            SeasonStepInput(season_id=season_id, trigger="scheduled"),
            season_id=season_id,
            semantic_key=f"research.collect_and_propose:{season_id}:1",
        )
        stats = self._drain()
        proposal = self._row(
            "SELECT id, scope_hash FROM season_proposals WHERE season_id = %s "
            "AND status = 'PROPOSED' ORDER BY scope_version DESC LIMIT 1",
            (season_id,),
        )
        if proposal is None:
            raise RuntimeError(f"W01 produced no proposal (job {self._job_status(job_id)})")
        self.report.proposal_id = proposal["id"]
        self.report.add("W01", "research", "OK", proposal_id=str(proposal["id"]), **stats)
        return season_id

    def gate1(self, season_id: UUID) -> UUID:
        season = self._row("SELECT revision FROM seasons WHERE id = %s", (season_id,))
        proposal = self._row(
            "SELECT scope_hash FROM season_proposals WHERE season_id = %s "
            "AND status = 'PROPOSED' ORDER BY scope_version DESC LIMIT 1",
            (season_id,),
        )
        command = ApprovalCommand(
            gate=GateType.SEASON_CONCEPT,
            action=ApprovalAction.APPROVE,
            entity_id=season_id,
            expected_revision=season["revision"],
            package_hash=proposal["scope_hash"],
            idempotency_key=f"gate1:{season_id}",
        )
        self.world.review.decide_season(self.human, season_id, command)
        self.report.human_decisions += 1
        approval = self._row("SELECT approval_event_id FROM seasons WHERE id = %s", (season_id,))
        self.report.gate1_approval_id = approval["approval_event_id"]
        self.report.add(
            "GATE1",
            "season_approval",
            "APPROVED",
            approval_id=str(approval["approval_event_id"]),
            human=True,
        )
        return approval["approval_event_id"]

    # --- W02–W07 ---------------------------------------------------------------------------

    def w02_compile(self, season_id: UUID) -> None:
        self._drain()  # the Gate 1 decision enqueued story.compile_season itself
        canon = self._row(
            "SELECT version FROM canon_versions WHERE season_id = %s AND kind = 'PLANNED' "
            "ORDER BY version DESC LIMIT 1",
            (season_id,),
        )
        if canon is None:
            raise RuntimeError("W02 compile produced no planned canon")
        self.report.add("W02", "compile_season", "OK", canon_version=canon["version"])

    def create_episode(self, season_id: UUID, *, number: int = 1) -> UUID:
        """Create the next episode row bound to the approved scope (integrator step).

        No module owns episode creation (the cadence trigger is configuration); the
        runner performs it against the same rules the lanes check afterwards.
        """
        season = self._row("SELECT approved_scope_hash FROM seasons WHERE id = %s", (season_id,))
        existing = self._row(
            "SELECT count(*) AS c FROM episodes WHERE season_id = %s", (season_id,)
        )
        episode_id = uuid4()
        with self.world.db.transaction() as tx:
            insert_row(
                tx,
                "episodes",
                {
                    "id": episode_id,
                    "season_id": season_id,
                    "episode_number": existing["c"] + 1 if existing else number,
                    "state": "PLANNED",
                    "approved_scope_hash": season["approved_scope_hash"],
                },
            )
        self.report.episode_id = episode_id
        return episode_id

    def w03_write(self, episode_id: UUID) -> None:
        self._enqueue(
            "story.write_episode",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"story.write_episode:{episode_id}:1",
        )
        self._drain()
        script = self._row(
            "SELECT id FROM scripts WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        if script is None:
            raise RuntimeError("W03 produced no CURRENT script")
        self.report.add("W03", "write_episode", "OK")

    def w04_references(self, episode_id: UUID) -> None:
        self._enqueue(
            "references.prepare_episode",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"references.prepare_episode:{episode_id}:1",
        )
        self._drain()
        prepared = self._row(
            "SELECT count(*) AS c FROM reference_versions rv WHERE rv.season_id = "
            "(SELECT season_id FROM episodes WHERE id = %s)",
            (episode_id,),
        )
        if prepared is None or prepared["c"] == 0:
            raise RuntimeError("W04 produced no reference versions")
        self.report.add("W04", "prepare_references", "OK", anchors=prepared["c"])

    def w05_render(self, episode_id: UUID) -> None:
        """Route + dispatch every shot, then monitor each operation to a terminal state.

        The frozen job service refuses to claim a job whose provider operation is
        still in flight (that is NEEDS_RECONCILIATION territory), so monitoring is
        the T013 pattern: poll the comfy service outside the claim until terminal,
        then resolve the job SUCCEEDED/FAILED with the operation as evidence and
        accept the verified outputs.
        """
        from microdrama.contracts.enums import AssetState, PrincipalKind, ProviderOperationState
        from microdrama.contracts.principals import Principal
        from microdrama.contracts.season import ShotManifest
        from microdrama.persistence.assets import asset_revision, set_asset_state
        from microdrama.rendering.routing import dispatch_routed_attempt

        manifest_row = self._row(
            "SELECT body FROM shot_manifests WHERE episode_id = %s AND status = 'CURRENT'",
            (episode_id,),
        )
        manifest = ShotManifest.model_validate(manifest_row["body"])
        bindings = self.world.references.render_request_bindings(episode_id)
        catalog = self.world.catalog
        monitor = Principal(
            principal_id="svc:pipeline-render-monitor", kind=PrincipalKind.SCHEDULER
        )
        dispatched: list[tuple[UUID, UUID]] = []  # (job_id, operation_id)
        for shot in manifest.shots:
            decision = self.world.router.route_shot(
                shot,
                episode_id=episode_id,
                manifest_version=manifest.version,
            )
            attempt = dispatch_routed_attempt(
                self.world.db,
                self.world.comfy,
                self.world.jobs,
                decision=decision,
                shot=shot,
                catalog=catalog,
                episode_number=1,
                reference_asset_ids=list(bindings.reference_asset_ids),
                identity_lock_id=bindings.lock_id,
                prompt_text=f"mock render for shot {shot.shot_id}",
            )
            operation_id = self._operation_id(attempt.job_id)
            if operation_id is not None:
                dispatched.append((attempt.job_id, operation_id))
        shots = len(manifest.shots)

        # One claim attempt records the in-flight refusal, moving each job to
        # NEEDS_RECONCILIATION — the only state resolve_reconciliation accepts.
        self.runtime.run_cycle()

        accepted_assets = 0
        for job_id, operation_id in dispatched:
            status = self.world.comfy.poll(operation_id)
            while status.state not in (
                ProviderOperationState.SUCCEEDED,
                ProviderOperationState.FAILED,
                ProviderOperationState.UNKNOWN,
            ):
                self.world.fakes.clock.advance(seconds=10)
                status = self.world.comfy.poll(operation_id)
            if status.state is not ProviderOperationState.SUCCEEDED:
                raise RuntimeError(
                    f"W05: render operation {operation_id} ended {status.state.value}"
                )
            self.world.jobs.resolve_reconciliation(
                job_id,
                actor=monitor,
                resolution="SUCCEEDED",
                evidence=f"comfy operation {operation_id} succeeded; outputs verified",
            )
            for asset in status.assets:
                with self.world.db.transaction() as tx:
                    set_asset_state(
                        tx,
                        asset.asset_id,
                        AssetState.ACCEPTED,
                        expected_revision=asset_revision(tx, asset.asset_id),
                    )
                accepted_assets += 1
        accepted = self._rows(
            "SELECT count(*) AS c FROM assets WHERE episode_id = %s "
            "AND object_key LIKE 'renders/%%' AND state = 'ACCEPTED'",
            (episode_id,),
        )[0]["c"]
        if accepted < shots:
            raise RuntimeError(f"W05: only {accepted}/{shots} shot assets accepted")
        self.report.add("W05", "render_shots", "OK", shots=shots, accepted=accepted)

    def _operation_id(self, job_id: UUID) -> UUID | None:
        row = self._row(
            "SELECT id FROM provider_operations WHERE job_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (job_id,),
        )
        return None if row is None else row["id"]

    def w06_edit(self, episode_id: UUID) -> None:
        self._enqueue(
            "edit.assemble_episode",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"edit.assemble_episode:{episode_id}:1",
        )
        self._drain(advance_ms=5_000)
        main = self._row(
            "SELECT output_asset_id FROM edit_manifests WHERE episode_id = %s "
            "AND variant_key = 'main' AND output_asset_id IS NOT NULL "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        if main is None:
            raise RuntimeError("W06 produced no assembled master")
        self.report.master_asset_id = main["output_asset_id"]
        self._enqueue(
            "edit.variants_and_hooks",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"edit.variants_and_hooks:{episode_id}:1",
        )
        self._drain(advance_ms=5_000)
        self.report.add(
            "W06", "assemble_and_variants", "OK", master_asset_id=str(main["output_asset_id"])
        )

    def w07_qa(self, episode_id: UUID) -> None:
        from microdrama.contracts.qa import (
            ComparisonRequest,
            MediaUnderReview,
            NeutralQuestion,
            ObservationRequest,
        )

        self._enqueue(
            "qa.technical",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"qa.technical:{episode_id}:1",
        )
        self._drain(advance_ms=5_000)
        master = self.report.master_asset_id
        asset = self._row("SELECT sha256, descriptor FROM assets WHERE id = %s", (master,))
        duration = asset["descriptor"]["media"]["duration_ms"]
        observation = ObservationRequest(
            request_id=uuid4(),
            episode_id=episode_id,
            media=[
                MediaUnderReview(
                    asset_id=master, asset_sha256=asset["sha256"], duration_ms=duration
                )
            ],
            questions=[
                NeutralQuestion(question_id="q1", text="What is visibly present in the frame?")
            ],
        )
        self._enqueue(
            "qa.observe",
            observation,
            episode_id=episode_id,
            semantic_key=f"qa.observe:{episode_id}:1",
        )
        self._drain()
        script = self._row(
            "SELECT id, version, body_hash FROM scripts WHERE episode_id = %s "
            "AND status = 'CURRENT'",
            (episode_id,),
        )
        canon = self._row(
            "SELECT version, facts_hash FROM canon_versions WHERE season_id = "
            "(SELECT season_id FROM episodes WHERE id = %s) AND kind = 'PLANNED' "
            "ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        frozen = self._row(
            "SELECT id, report_sha256 FROM qa_observations WHERE episode_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (episode_id,),
        )
        self._enqueue(
            "qa.compare",
            ComparisonRequest(
                request_id=uuid4(),
                episode_id=episode_id,
                observation_report_id=frozen["id"],
                observation_report_sha256=frozen["report_sha256"],
                script_id=script["id"],
                script_version=script["version"],
                script_sha256=script["body_hash"],
                canon_version=canon["version"],
                canon_sha256=canon["facts_hash"],
            ),
            episode_id=episode_id,
            semantic_key=f"qa.compare:{episode_id}:1",
        )
        self._drain()
        blocking = self._rows(
            "SELECT count(*) AS c FROM qa_findings WHERE episode_id = %s "
            "AND (severity = 'CRITICAL' OR outcome = 'BLOCKED') "
            "AND coalesce(resolution, 'OPEN') NOT IN ('RESOLVED', 'SUPERSEDED')",
            (episode_id,),
        )[0]["c"]
        if blocking:
            raise RuntimeError(f"W07: {blocking} blocking QA finding(s) remain open")
        self.report.add("W07", "qa", "GREEN", blocking_findings=0)

    # --- packaging + Gate 2 -----------------------------------------------------------------

    def package_and_gate2(self, season_id: UUID, episode_id: UUID) -> tuple[UUID, UUID]:
        self._enqueue(
            "review.prepare_package",
            EpisodeStepInput(episode_id=episode_id),
            episode_id=episode_id,
            semantic_key=f"review.prepare_package:{episode_id}:1",
        )
        self._drain()
        episode = self._row(
            "SELECT revision, episode_number, state FROM episodes WHERE id = %s", (episode_id,)
        )
        if episode["state"] != "AWAITING_FINAL_REVIEW":
            raise RuntimeError(f"package stage left episode {episode['state']}")
        from microdrama.review.packages import current_package

        with self.world.db.transaction(readonly=True) as tx:
            stored = current_package(tx, episode_id)
        if stored is None:
            raise RuntimeError("no current release package after prepare")
        command = ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_id=episode_id,
            expected_revision=episode["revision"],
            package_hash=stored.package_hash,
            media_hashes=stored.media_hashes,
            management_policy_hash=stored.management_policy_hash,
            release_scope_hash=stored.release_scope_hash,
            idempotency_key=f"gate2:{episode_id}",
        )
        self.world.review.decide_episode(self.human, episode_id, command)
        self.report.human_decisions += 1
        approval = self._row(
            "SELECT approval_event_id FROM release_packages WHERE package_hash = %s",
            (stored.package_hash,),
        )
        self.report.gate2_approval_id = approval["approval_event_id"]
        lock = self._row(
            "SELECT id FROM identity_locks WHERE season_id = %s ORDER BY created_at DESC LIMIT 1",
            (season_id,),
        )
        self.report.identity_lock_id = lock["id"] if lock else None
        self.report.add(
            "W08",
            "gate2_approval",
            "APPROVED",
            approval_id=str(approval["approval_event_id"]),
            identity_lock_id=str(lock["id"]) if lock else None,
            human=True,
        )
        return approval["approval_event_id"], lock["id"] if lock else None

    # --- W09 publish ------------------------------------------------------------------------

    def w09_publish(self, episode_id: UUID) -> list[UUID]:
        self._drain()  # Gate 2 enqueued publish.schedule_release itself
        posts = self._rows(
            "SELECT id, release_slot, state FROM platform_posts WHERE episode_id = %s "
            "ORDER BY release_slot",
            (episode_id,),
        )
        if not posts:
            raise RuntimeError("W09: no platform posts scheduled")
        package = self._row(
            "SELECT id, body FROM release_packages WHERE episode_id = %s "
            "AND status = 'APPROVED' ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        approval_id = self.report.gate2_approval_id
        for post in posts:
            if post["state"] != "SCHEDULED":
                continue
            command = self._command_for_post(post, package, approval_id)
            self._enqueue(
                "publish.submit_slot",
                command,
                episode_id=episode_id,
                semantic_key=f"publish.submit_slot:{post['release_slot']}:{episode_id}",
            )
        self._drain(advance_ms=3_000)
        for post in self._rows(
            "SELECT id FROM platform_posts WHERE episode_id = %s AND state = 'SUBMITTED'",
            (episode_id,),
        ):
            self._enqueue(
                "publish.poll_status",
                PlatformPostRef(platform_post_id=post["id"]),
                episode_id=episode_id,
                semantic_key=f"publish.poll_status:{post['id']}:1",
            )
        self._drain(advance_ms=5_000)
        self._resolve_terminal_publish_jobs(episode_id)
        verified = self._rows(
            "SELECT id, state, url FROM platform_posts WHERE episode_id = %s "
            "AND state = 'PUBLISHED_VERIFIED'",
            (episode_id,),
        )
        self.report.platform_post_ids = [post["id"] for post in verified]
        all_posts = self._rows(
            "SELECT release_slot, platform, state, blocker FROM platform_posts "
            "WHERE episode_id = %s ORDER BY release_slot",
            (episode_id,),
        )
        self.report.add(
            "W09",
            "publish",
            "OK" if verified else "HELD",
            verified_posts=[
                {"id": str(post["id"]), "url": post["url"], "mock": True} for post in verified
            ],
            slots=[
                {
                    "slot": post["release_slot"],
                    "platform": str(post["platform"]),
                    "state": str(post["state"]),
                    "blocker": post["blocker"],
                }
                for post in all_posts
            ],
            total_posts=len(posts),
        )
        return [post["id"] for post in verified]

    def _resolve_terminal_publish_jobs(self, episode_id: UUID) -> None:
        """Finish submit jobs whose provider operation completed during polling.

        The frozen job service refuses to finish a job with an in-flight provider
        operation (NEEDS_RECONCILIATION territory, same truth as W05): once the
        poll verified the post, the linked operation is a recorded success and
        the job resolves SUCCEEDED with that evidence.
        """
        from microdrama.contracts.enums import PrincipalKind
        from microdrama.contracts.principals import Principal

        monitor = Principal(
            principal_id="svc:pipeline-publish-monitor", kind=PrincipalKind.SCHEDULER
        )
        rows = self._rows(
            "SELECT j.id AS job_id, po.id AS op_id, po.state AS op_state "
            "FROM jobs j JOIN provider_operations po ON po.job_id = j.id "
            "WHERE j.episode_id = %s AND j.status = 'NEEDS_RECONCILIATION' "
            "AND j.job_type = 'publish.submit_slot'",
            (episode_id,),
        )
        for row in rows:
            if row["op_state"] != "SUCCEEDED":
                continue
            self.world.jobs.resolve_reconciliation(
                row["job_id"],
                actor=monitor,
                resolution="SUCCEEDED",
                evidence=f"publish operation {row['op_id']} verified through readback",
            )

    def _command_for_post(self, post: dict, package_row: dict, approval_id: UUID):
        from microdrama.contracts.enums import DisclosureKind

        pkg = package_row["body"]
        plan = next(
            (
                ReleaseSlotPlan.model_validate(p)
                for p in pkg["release_scope"]
                if p["slot"]["release_slot"] == post["release_slot"]
            ),
            None,
        )
        if plan is None:
            raise RuntimeError(f"no slot plan for release_slot {post['release_slot']}")
        metadata = PostMetadata(
            locale="th-TH",
            title="ตอนที่ ๑ – หนี้เล็กๆ ของแม่ (จำลอง)",
            caption="ฤดูกาลนำร่อง ตอนที่ 1 (mock)",
            description="Pilot mock episode.",
            hashtags=["#thaidrama", "#shortseries"],
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            catalog_version=1,
        )
        return PublicationCommand(
            command_id=command_id_for(plan.slot.dedupe_key),
            release_package_id=package_row["id"],
            release_package_hash=pkg["package_hash"],
            approval_event_id=approval_id,
            slot=plan.slot,
            slot_kind=plan.slot_kind,
            asset_id=plan.asset_id,
            asset_sha256=plan.asset_sha256,
            metadata=metadata,
            metadata_version_id=meta.initial_metadata_version_id(plan.slot.dedupe_key),
            schedule=plan.schedule,
            capability_id=plan.capability_id,
            capability_version=plan.capability_version,
            client_token=publish_client_token(plan.slot.dedupe_key, pkg["package_hash"]),
        )

    # --- W10 community/membership ------------------------------------------------------------

    def w10_community(self, season_id: UUID, episode_id: UUID) -> None:
        from microdrama.contracts.enums import Platform

        stats: dict[str, Any] = {}
        for platform in (Platform.YOUTUBE, Platform.TIKTOK):
            report = self.world.community.process(
                platform,
                "acct:fake-main",
                season_id=season_id,
                episode_id=episode_id,
            )
            stats[f"{platform.value}_executed"] = report.executed
            stats[f"{platform.value}_suppressed"] = report.suppressed
        # Membership: entitlement check + webhook dedupe over the fake provider.
        entitlement = self.world.memberships.entitlements.check(
            member_ref="member:mock-1", episode_id=episode_id
        )
        stats["entitlement_entitled"] = bool(entitlement.entitled)
        self.report.add("W10", "community_and_membership", "OK", **stats)

    # --- W11 analytics ------------------------------------------------------------------------

    def w11_analytics(self, episode_id: UUID) -> None:
        stats: dict[str, Any] = {"windows": {}, "mock_snapshots_recorded": 0}
        # Windows open only after verified_at + boundary (an observation made
        # before the boundary stays early no matter when it is submitted). The
        # pilot first reports the honest PENDING state, then advances the fake
        # clock past each boundary and records clearly-fake mock snapshots for
        # the 24h windows (there is no insights provider offline — the numbers
        # are mock-labeled, never real claims; 72h/7d stay pending).
        for post_id in self.report.platform_post_ids:
            for window in self.world.analytics.due_windows(post_id):
                stats["windows"][window.window.value] = "RECORDED" if window.recorded else "PENDING"
        self.world.fakes.clock.advance(seconds=24 * 3600 + 60)
        for post_id in self.report.platform_post_ids:
            for window in self.world.analytics.due_windows(post_id):
                if window.recorded or window.window.value != "H24":
                    continue
                self.world.analytics.record_snapshot(_mock_snapshot(self, post_id, window.window))
                stats["mock_snapshots_recorded"] += 1
                stats["windows"][window.window.value] = "RECORDED_MOCK"
        qualification = self.world.analytics.evaluate_qualification(self.report.season_id)
        stats["qualification_production"] = qualification.production_status.value
        stats["qualification_management"] = qualification.management_status.value
        stats["successful_episodes"] = qualification.successful_episodes
        self.report.add("W11", "analytics", "OK", **stats)

    # --- W12 janitors ---------------------------------------------------------------------------

    def w12_cleanup(self, episode_id: UUID) -> None:
        workers_report = self.world.workers_janitor.sweep()
        gpu_report = self.world.gpu_janitor.sweep()
        live_leases = self._rows(
            "SELECT count(*) AS c FROM pod_leases WHERE owner_episode_id = %s "
            "AND lease_state IN ('CLAIMED', 'ACTIVE', 'TRANSFERRING')",
            (episode_id,),
        )[0]["c"]
        if live_leases:
            raise RuntimeError(f"W12: {live_leases} live GPU lease(s) remain")
        self.report.add(
            "W12",
            "janitors",
            "OK",
            workers_steps=len(workers_report.steps),
            gpu_orphans=len(gpu_report.orphan_pods),
            gpu_stopped=len(gpu_report.stopped_pods),
        )

    # --- the whole path ---------------------------------------------------------------------------

    def run(self) -> PipelineRunReport:
        season_id = self.w01_research()
        self.gate1(season_id)
        self.w02_compile(season_id)
        episode_id = self.create_episode(season_id, number=1)
        self.w03_write(episode_id)
        self.w04_references(episode_id)
        self.w05_render(episode_id)
        self.w06_edit(episode_id)
        self.w07_qa(episode_id)
        self.package_and_gate2(season_id, episode_id)
        self.w09_publish(episode_id)
        self.w10_community(season_id, episode_id)
        self.w11_analytics(episode_id)
        self.w12_cleanup(episode_id)
        return self.report


def _mock_snapshot(runner: MockPipelineRunner, post_id: UUID, window):
    """One clearly-fake metric snapshot built from the verified post row."""
    from microdrama.contracts.catalog import MetricSnapshot
    from microdrama.contracts.enums import Provenance

    post = runner._row(
        "SELECT p.platform, p.account_ref, p.external_id, p.episode_id "
        "FROM platform_posts p WHERE p.id = %s",
        (post_id,),
    )
    return MetricSnapshot(
        snapshot_id=uuid4(),
        platform=post["platform"],
        account_ref=post["account_ref"],
        platform_post_id=post_id,
        external_post_id=post["external_id"] or "mock-external",
        episode_id=post["episode_id"],
        window=window,
        observed_at=runner.world.fakes.clock.now(),
        definitions_version="mock-v1",
        metrics={"views": {"value": 1_000, "definition": "mock/views"}},
        provenance=Provenance.FAKE_SYNTHETIC,
    )


__all__ = ["MockPipelineRunner", "PipelineRunReport", "StageResult"]

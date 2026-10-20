"""Shared builders for the review tests. Plain helpers; fixtures live in conftest.py.

Every row is written through the real database (seeds for owners/sessions/seasons/episodes, SQL
for the rest). Media bytes go to a private filesystem object store. Nothing here touches the
network: fake providers never appear, and every asset is labelled FAKE_SYNTHETIC.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from microdrama.budget import BudgetService
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings
from microdrama.contracts.enums import (
    ApprovalAction,
    AssetKind,
    AssetState,
    BudgetCategory,
    BudgetScopeKind,
    CaptionTimingSource,
    CheckFamily,
    CoverageStatus,
    DisclosureKind,
    FeedbackCategory,
    GateType,
    Platform,
    PriceUnit,
    PrincipalKind,
    Provenance,
    QAOutcome,
    QAPass,
    Severity,
    SlotKind,
)
from microdrama.contracts.examples import ACCOUNT_YT, media_info, schedule, season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor, CaptionCue, CaptionTrack
from microdrama.contracts.principals import Principal
from microdrama.contracts.qa import CoverageWindow, ObservationReport
from microdrama.contracts.release import (
    CostSummary,
    MediaRef,
    QASummary,
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import ApprovalCommand, CostPolicy, TimecodedFeedback
from microdrama.core.auth import AuthService
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence import Database, Tx, insert_row, jsonb, register_asset
from microdrama.review.packages import store_release_package
from microdrama.review.service import ReviewService
from microdrama.testing.fakes import fake_price_quote
from microdrama.testing.seed import (
    seed_episode,
    seed_gate1_approval,
    seed_human_session,
    seed_owner,
)

FAKE = Provenance.FAKE_SYNTHETIC
MASTER_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-master-" * 64
THAI_CUE = "ทดสอบคำบรรยาย"


def new_key(prefix: str = "key") -> str:
    """An idempotency key that satisfies the contract pattern (letters, digits, . _ : -)."""
    return f"{prefix}-{uuid.uuid4().hex}"


class IdentityLockHook:
    """Stands in for T011: writes an identity lock inside the approval transaction.

    ``fail`` makes the hook raise after recording the call, to prove the approval rolls back.
    """

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[uuid.UUID] = []
        self.fail = fail

    def on_recorded(self, tx: Tx, *, approval_event_id, command, principal) -> None:
        self.calls.append(approval_event_id)
        if self.fail is not None:
            raise self.fail
        episode = tx.fetchone(
            "SELECT season_id, episode_number FROM episodes WHERE id = %s", (command.entity_id,)
        )
        lock_id = uuid.uuid4()
        body = {
            "lock_id": str(lock_id),
            "season_id": str(episode["season_id"]),
            "source_episode_id": str(command.entity_id),
            "version": 1,
            "approval_event_id": str(approval_event_id),
            "release_package_hash": command.package_hash,
            "locked_assets": [
                {
                    "asset_kind": "FACE",
                    "asset_id": str(uuid.uuid4()),
                    "asset_version": 1,
                    "content_sha256": canonical_hash({"face": str(lock_id)}),
                    "label": "lead face reference",
                }
            ],
            "created_at": "2026-10-20T00:00:00Z",
            "schema_version": "1.0",
        }
        insert_row(
            tx,
            "identity_locks",
            {
                "id": lock_id,
                "season_id": episode["season_id"],
                "source_episode_id": command.entity_id,
                "version": 1,
                "approval_event_id": approval_event_id,
                "release_package_hash": command.package_hash,
                "body": jsonb(body),
            },
        )


class World:
    """Builds a review scenario on the real database and exposes the service under test."""

    def __init__(self, db: Database, store: ObjectStore, clock, ids, settings) -> None:
        self.db = db
        self.store = store
        self.clock = clock
        self.ids = ids
        self.settings = settings
        self.auth = AuthService(db, clock, ids)
        self.jobs = JobService(db, clock, ids)
        self.idempotency = IdempotencyService(db)
        self.budget = BudgetService(db, clock, ids, settings)
        self.approval_hooks: list[Any] = []
        self.identity_lock_hook: Any = IdentityLockHook()
        # Tests stand in for T006: every rights/capability condition is satisfied unless a test
        # injects blockers. The fail-closed default is exercised separately.
        self.release_conditions: Any = lambda tx, episode_row, package: []

    @property
    def service(self) -> ReviewService:
        """A service built from the world's current hooks (cheap: attributes only)."""
        return ReviewService(
            self.db,
            self.clock,
            self.ids,
            jobs=self.jobs,
            idempotency=self.idempotency,
            budget=self.budget,
            store=self.store,
            release_conditions_fn=self.release_conditions,
            approval_hooks=self.approval_hooks,
            identity_lock_hook=self.identity_lock_hook,
        )

    # --- principals --------------------------------------------------------------------

    def human(self) -> Principal:
        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
        return Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )

    def service_principal(self, kind: PrincipalKind = PrincipalKind.SERVICE_WORKER) -> Principal:
        from microdrama.contracts.enums import RuntimeRole

        role = RuntimeRole.CRITIC if kind is PrincipalKind.RUNTIME_MODEL else None
        return Principal(
            principal_id=f"{kind.value.lower()}:{uuid.uuid4().hex[:10]}",
            kind=kind,
            runtime_role=role,
        )

    # --- seasons and episodes ----------------------------------------------------------

    def season(self, *, approved: bool, scope_version: int = 1) -> tuple[uuid.UUID, Any]:
        """A season with one proposal (PROPOSED, or APPROVED with the Gate 1 approval bound)."""
        season_id = uuid.uuid4()
        scope = season_scope().model_copy(
            update={"season_id": season_id, "scope_version": scope_version}
        )
        scope_hash = canonical_hash(scope)
        with self.db.transaction() as tx:
            approval_id = seed_gate1_approval(tx, season_id, scope_hash) if approved else None
            insert_row(
                tx,
                "seasons",
                {
                    "id": season_id,
                    "state": "SEASON_APPROVED" if approved else "PROPOSED",
                    "title_th": scope.title_th,
                    "title_en": scope.title_en,
                    "approved_scope_version": 1 if approved else None,
                    "approved_scope_hash": scope_hash if approved else None,
                    "approval_event_id": approval_id,
                    "approved_at": self.clock.now() if approved else None,
                },
                returning="id",
            )
            insert_row(
                tx,
                "season_proposals",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "scope_version": scope_version,
                    "scope": jsonb(scope),
                    "scope_hash": scope_hash,
                    "status": "APPROVED" if approved else "PROPOSED",
                },
                returning="id",
            )
        return season_id, scope

    def episode(
        self, season_id: uuid.UUID, *, number: int = 1, state: str = "AWAITING_FINAL_REVIEW"
    ):
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, number=number, state=state)
        return episode_id

    def episode_with_budget(
        self, season_id: uuid.UUID, *, number: int = 1, state: str = "AWAITING_FINAL_REVIEW"
    ) -> uuid.UUID:
        episode_id = self.episode(season_id, number=number, state=state)
        with self.db.transaction() as tx:
            self.budget.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
            )
        return episode_id

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def row_exec(self, sql: str, params: tuple = ()) -> None:
        with self.db.transaction() as tx:
            tx.execute(sql, params)

    def row_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def episode_state(self, episode_id: uuid.UUID) -> tuple[str, str | None, int]:
        row = self.row("SELECT state, outcome, revision FROM episodes WHERE id = %s", (episode_id,))
        assert row is not None
        return row["state"], row["outcome"], row["revision"]

    def episode_revision(self, episode_id: uuid.UUID) -> int:
        return self.episode_state(episode_id)[2]

    def jobs_of(self, job_type: str) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM jobs WHERE job_type = %s ORDER BY created_at, id", (job_type,)
            )

    def approvals(self, entity_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(
                "SELECT * FROM approval_events WHERE entity_id = %s ORDER BY created_at",
                (entity_id,),
            )

    # --- media, captions and packages --------------------------------------------------

    def asset(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID | None,
        kind: AssetKind = AssetKind.VIDEO,
        data: bytes = MASTER_BYTES,
        media_type: str = "video/mp4",
    ) -> tuple[uuid.UUID, str]:
        asset_id = uuid.uuid4()
        key = f"review-tests/{asset_id.hex}.bin"
        stored = self.store.put_bytes(key, data, media_type=media_type)
        measured = kind in (AssetKind.VIDEO, AssetKind.AUDIO)
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=kind,
            object_key=key,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            media_type=media_type,
            media=media_info() if measured else None,
            state=AssetState.ACCEPTED,
            provenance=FAKE,
            episode_id=episode_id,
            season_id=season_id,
            created_at=self.clock.now(),
        )
        with self.db.transaction() as tx:
            register_asset(tx, descriptor)
        return asset_id, stored.sha256

    def current_caption(self, episode_id: uuid.UUID) -> uuid.UUID:
        """The episode's CURRENT actual-audio Thai track, created on first use."""
        row = self.row(
            "SELECT id FROM caption_tracks WHERE episode_id = %s AND locale = 'th-TH' "
            "AND state = 'CURRENT'",
            (episode_id,),
        )
        return row["id"] if row is not None else self.caption(episode_id)

    def caption(
        self,
        episode_id: uuid.UUID,
        *,
        timing: CaptionTimingSource = CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
        state: str = "CURRENT",
        locale: str = "th-TH",
        text: str = THAI_CUE,
    ) -> uuid.UUID:
        track_id = uuid.uuid4()
        actual = timing is CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT
        track = CaptionTrack(
            track_id=track_id,
            episode_id=episode_id,
            version=1,
            locale=locale,
            timing_source=timing,
            derived_from_audio_sha256=[canonical_hash({"audio": str(track_id)})] if actual else [],
            cues=[CaptionCue(cue_id="c1", start_ms=0, end_ms=1_000, text=text)],
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "caption_tracks",
                {
                    "id": track_id,
                    "episode_id": episode_id,
                    "locale": locale,
                    "version": 1,
                    "timing_source": timing.value,
                    "body": jsonb(track),
                    "body_hash": canonical_hash(track),
                    "state": state,
                },
                returning="id",
            )
        return track_id

    def package(
        self,
        *,
        season_id: uuid.UUID,
        episode_id: uuid.UUID,
        number: int = 1,
        version: int = 1,
        master: tuple[uuid.UUID, str],
        extra_media: list[tuple[uuid.UUID, str, str]] | None = None,
        captions: list[uuid.UUID] | None = None,
        cast: list[uuid.UUID] | None = None,
        gate_blockers: list[str] | None = None,
        blocking_findings: list[uuid.UUID] | None = None,
        unknown_checks: list[str] | None = None,
        policy_hash: str | None = None,
    ) -> ReleasePackage:
        master_id, master_sha = master
        media = [MediaRef(asset_id=master_id, sha256=master_sha, role="master")]
        for asset_id, sha, role in extra_media or []:
            media.append(MediaRef(asset_id=asset_id, sha256=sha, role=role))
        scope_plan = ReleaseSlotPlan(
            slot=ReleaseSlotKey(
                series_id=season_id,
                episode_id=episode_id,
                part=0,
                locale="th-TH",
                platform=Platform.YOUTUBE,
                account_ref=ACCOUNT_YT,
                release_slot="full",
            ),
            slot_kind=SlotKind.FULL_EPISODE,
            required=True,
            asset_id=master_id,
            asset_sha256=master_sha,
            schedule=schedule(),
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            capability_id=uuid.uuid4(),
            capability_version=1,
        )
        cast_ids = list(cast or [])
        if number == 1 and not cast_ids:
            cast_ids = [
                self.asset(
                    season_id=season_id,
                    episode_id=episode_id,
                    kind=AssetKind.CONTACT_SHEET,
                    data=b"contact-sheet",
                    media_type="image/png",
                )[0]
            ]
        blockers = list(gate_blockers or [])
        findings = list(blocking_findings or [])
        if findings and not blockers:
            blockers = ["blocking QA finding in package"]
        return ReleasePackage.seal(
            package_id=uuid.uuid4(),
            episode_id=episode_id,
            season_id=season_id,
            episode_number=number,
            version=version,
            media=media,
            caption_track_ids=list(captions) if captions else [self.current_caption(episode_id)],
            cast_package_asset_ids=cast_ids,
            release_scope=[scope_plan],
            management_policy_hash=policy_hash or canonical_hash(season_scope().management_policy),
            qa=QASummary(
                blocking_finding_ids=findings,
                unknown_coverage_check_ids=list(unknown_checks or []),
                finding_count=len(findings),
                provenance=FAKE,
            ),
            cost=CostSummary(
                episode_cap_micro_usd=10_000_000,
                settled_micro_usd=4_100_000,
                accrued_micro_usd=0,
                reserved_outstanding_micro_usd=0,
                remaining_micro_usd=5_900_000,
                synthetic_fake_micro_usd=4_100_000,
            ),
            gate_blockers=blockers,
        )

    def store_package(self, package: ReleasePackage, *, status: str = "READY") -> None:
        with self.db.transaction() as tx:
            store_release_package(tx, package, status=status, now=self.clock.now())

    def ready_episode(self, *, number: int = 1, state: str = "AWAITING_FINAL_REVIEW"):
        """Season (approved), episode, master video, captions and a READY package, in one call."""
        season_id, _scope = self.season(approved=True)
        episode_id = self.episode_with_budget(season_id, number=number, state=state)
        master = self.asset(season_id=season_id, episode_id=episode_id)
        package = self.package(
            season_id=season_id, episode_id=episode_id, number=number, master=master
        )
        self.store_package(package)
        return season_id, episode_id, package

    def open_gpu_lease(
        self,
        episode_id: uuid.UUID,
        season_id: uuid.UUID,
        state: str = "ACTIVE",
        *,
        stop_verified: bool = False,
    ) -> uuid.UUID:
        """A live GPU lease bound to a real reservation (the way the pod lane creates them)."""
        request = BudgetReservationRequest(
            request_id=uuid.uuid4(),
            semantic_key=f"lease-{uuid.uuid4().hex}",
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=episode_id,
            category=BudgetCategory.GPU_GENERATION,
            queue="production",
            provider="fake-runpod",
            operation_kind="gpu.render_shot",
            price=fake_price_quote(PriceUnit.GPU_SECOND),
            ceilings=ExposureCeilings(timeout_ms=600_000, max_units=1),
            worst_case_micro_usd=700_000,
            is_shutdown_or_cleanup=False,
            expires_at=self.clock.now() + timedelta(hours=1),
        )
        reservation = self.budget.reserve(request)
        lease_id = uuid.uuid4()
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "pod_leases",
                {
                    "id": lease_id,
                    "provider": "fake-runpod",
                    "pod_id": f"pod-{lease_id.hex[:8]}",
                    "owned_tag": "md-owned",
                    "client_token": f"lease-{lease_id.hex}",
                    "owner_episode_id": episode_id,
                    "reservation_id": reservation.id,
                    "lease_state": state,
                    "pod_state": "RUNNING",
                    "gpu_type": "FAKE-GPU",
                    "hourly_price_micro_usd": 900_000,
                    "lease_expires_at": self.clock.now() + timedelta(hours=2),
                    "stop_verified_at": self.clock.now() if stop_verified else None,
                },
            )
        return lease_id

    def observation(
        self,
        episode_id: uuid.UUID,
        *,
        asset_id: uuid.UUID,
        asset_sha: str,
        status: CoverageStatus = CoverageStatus.UNSAMPLED,
    ) -> uuid.UUID:
        """A frozen Pass A report whose temporal coverage is ``status`` (default: not sampled)."""
        report_id = uuid.uuid4()
        request_id = uuid.uuid4()
        report = ObservationReport(
            report_id=report_id,
            request_id=request_id,
            request_sha256=canonical_hash({"request": str(request_id)}),
            episode_id=episode_id,
            media_sha256=[asset_sha],
            coverage=[
                CoverageWindow(
                    asset_id=asset_id,
                    check_family=CheckFamily.TEMPORAL,
                    start_ms=0,
                    end_ms=4_000,
                    status=status,
                    note="dense lip-sync sampling was not run",
                )
            ],
            model_config_ref="fake-observer-v1",
            provenance=FAKE,
            frozen_at=self.clock.now(),
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "qa_observations",
                {
                    "id": report_id,
                    "episode_id": episode_id,
                    "request_id": request_id,
                    "request_sha256": report.request_sha256,
                    "media_sha256": jsonb([asset_sha]),
                    "report": jsonb(report),
                    "report_sha256": canonical_hash(report),
                    "provenance": FAKE.value,
                    "frozen_at": self.clock.now(),
                },
                returning="id",
            )
        return report_id

    def qa_finding(
        self,
        episode_id: uuid.UUID,
        *,
        severity: Severity = Severity.CRITICAL,
        outcome: QAOutcome = QAOutcome.REPAIRABLE,
        coverage: CoverageStatus = CoverageStatus.CHECKED,
        check_id: str = "caption.critical_term_match",
        qa_cycle: int = 1,
        resolution: str = "OPEN",
    ) -> uuid.UUID:
        finding_id = uuid.uuid4()
        body = {
            "finding_id": str(finding_id),
            "episode_id": str(episode_id),
            "asset_id": str(uuid.uuid4()),
            "start_ms": 400,
            "end_ms": 3_600,
            "check_id": check_id,
            "check_family": CheckFamily.CAPTION.value,
            "source_pass": QAPass.PASS_B_COMPARISON.value,
            "severity": severity.value,
            "coverage": coverage.value,
            "outcome": outcome.value,
            "repair_targets": ["CAPTION"] if outcome is QAOutcome.REPAIRABLE else [],
            "provenance": FAKE.value,
            "schema_version": "1.0",
        }
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "qa_findings",
                {
                    "id": finding_id,
                    "episode_id": episode_id,
                    "qa_cycle": qa_cycle,
                    "asset_id": uuid.uuid4(),
                    "start_ms": 400,
                    "end_ms": 3_600,
                    "check_id": check_id,
                    "check_family": CheckFamily.CAPTION.value,
                    "source_pass": QAPass.PASS_B_COMPARISON.value,
                    "severity": severity.value,
                    "coverage": coverage.value,
                    "outcome": outcome.value,
                    "body": jsonb(body),
                    "resolution": resolution,
                },
                returning="id",
            )
        return finding_id

    # --- commands ----------------------------------------------------------------------

    def gate2_command(
        self,
        episode_id: uuid.UUID,
        package: ReleasePackage | None,
        action: ApprovalAction = ApprovalAction.APPROVE,
        *,
        revision: int | None = None,
        **overrides: Any,
    ) -> ApprovalCommand:
        rev = self.episode_revision(episode_id) if revision is None else revision
        base: dict[str, Any] = dict(
            gate=GateType.EPISODE_FINAL,
            action=action,
            entity_id=episode_id,
            expected_revision=rev,
            package_hash=package.package_hash if package else "0" * 64,
            idempotency_key=new_key("gate2"),
        )
        if action is ApprovalAction.APPROVE and package is not None:
            base.update(
                media_hashes=package.media_hashes,
                management_policy_hash=package.management_policy_hash,
                release_scope_hash=package.release_scope_hash,
            )
        if action is ApprovalAction.REVISE:
            base["feedback"] = [
                TimecodedFeedback(
                    category=FeedbackCategory.SUBTITLES,
                    start_ms=12_000,
                    end_ms=15_500,
                    comment="English subtitle says 5,000 baht; Fon says 50,000.",
                )
            ]
        if action is ApprovalAction.REJECT:
            base["reason"] = "continuity break in the final cut"
        base.update(overrides)
        return ApprovalCommand(**base)

    def gate1_command(
        self,
        season_id: uuid.UUID,
        scope_hash: str,
        revision: int,
        *,
        action: ApprovalAction = ApprovalAction.APPROVE,
        **overrides: Any,
    ):
        base: dict[str, Any] = dict(
            gate=GateType.SEASON_CONCEPT,
            action=action,
            entity_id=season_id,
            expected_revision=revision,
            package_hash=scope_hash,
            idempotency_key=new_key("gate1"),
        )
        if action is ApprovalAction.REJECT:
            base["reason"] = "not this concept"
        base.update(overrides)
        return ApprovalCommand(**base)


__all__ = ["FAKE", "MASTER_BYTES", "World", "new_key"]

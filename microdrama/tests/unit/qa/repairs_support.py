"""Shared builders for the T019 repair tests. Not a test module.

Extends the T017 QA world with the seeds this lane needs: CURRENT caption tracks
with line-bound cues, real ``qa_findings`` rows (T017's ``build_finding`` bodies),
a READY release package, deterministic line-audio assets, durable ``render.shot``
ledger rows (the render service's own attempt ledger), a real Gate 2 REVISE
approval written through ``core.approvals`` (the only ``feedback_events`` writer),
and a recording shot-dispatch port so tests can assert ZERO render operations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qa_support import T0, QAWorld

from microdrama.contracts.enums import (
    ApprovalAction,
    AssetKind,
    AssetState,
    CheckFamily,
    CoverageStatus,
    EvidenceSource,
    GateType,
    PrincipalKind,
    Provenance,
    QAOutcome,
    RepairTarget,
    Severity,
)
from microdrama.contracts.examples import release_package as example_package
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import (
    AssetDescriptor,
    CaptionCue,
    CaptionTrack,
    MediaInfo,
)
from microdrama.contracts.primitives import ProductionLimits
from microdrama.contracts.principals import Principal
from microdrama.contracts.release import MediaRef
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.core.approvals import record_approval_event
from microdrama.persistence import insert_row, jsonb, register_asset
from microdrama.qa.models import build_finding
from microdrama.qa.repairs import RepairsConfig, RepairService, ShotDispatchPort
from microdrama.references.anchors import ref_id_for
from microdrama.review.packages import store_release_package
from microdrama.testing.seed import seed_episode, seed_human_session, seed_owner

# The example script's first two lines (contracts.examples.script).
L1 = "s1-l1"
L2 = "s1-l2"
THAI_L1 = "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คือระไรคะ"  # deliberate wrong text for defect seeds
EN_L1 = "Uncle Lek, what is this fifty-thousand-baht debt?"


class RecordingShotDispatch:
    """ShotDispatchPort stand-in: counts every render-side operation.

    ``attempts`` presets the ledger count; ``fail_dispatch`` makes the requeue raise
    after recording the call. A caption/line repair must leave both counters at 0.
    """

    def __init__(self, *, attempts: int = 0, fail_dispatch: Exception | None = None) -> None:
        self.attempts = attempts
        self.count_calls = 0
        self.dispatch_calls: list[dict[str, Any]] = []
        self._fail = fail_dispatch

    def attempts_used(self, *, episode_number: int, shot_id: str) -> int:
        self.count_calls += 1
        return self.attempts

    def dispatch_repair(
        self, *, episode_id: UUID, episode_number: int, shot_id: str, attempt_number: int
    ) -> UUID:
        self.dispatch_calls.append(
            {
                "episode_id": episode_id,
                "episode_number": episode_number,
                "shot_id": shot_id,
                "attempt_number": attempt_number,
            }
        )
        if self._fail is not None:
            raise self._fail
        return uuid.uuid4()


class RepairsWorld(QAWorld):
    """QAWorld plus the T019 seeds and service builders."""

    def repairs(
        self,
        *,
        config: RepairsConfig | None = None,
        limits: ProductionLimits | None = None,
        shot_dispatch: ShotDispatchPort | None = None,
    ) -> RepairService:
        return RepairService(
            self.db,
            self.clock,
            self.ids,
            self.settings,
            budget=self.budget,
            config=config,
            limits=limits,
            shot_dispatch=shot_dispatch,
        )

    # --- seeds -------------------------------------------------------------------------

    def caption_track(
        self,
        episode_id: UUID,
        locale: str,
        cues: list[tuple[int, int, str, str]],
        *,
        version: int = 1,
        state: str = "CURRENT",
    ) -> UUID:
        """One caption track row; each cue is (start, end, text, line_id) and the
        cue id follows the house pattern ``{line_id}.{locale-slug}``."""
        slug = locale.lower().replace("-", "")
        track_id = uuid.uuid4()
        body = CaptionTrack(
            track_id=track_id,
            episode_id=episode_id,
            version=version,
            locale=locale,
            timing_source="ACTUAL_AUDIO_ALIGNMENT",
            derived_from_audio_sha256=[
                canonical_hash({"line-audio": line_id}) for _s, _e, _t, line_id in cues if line_id
            ],
            cues=[
                CaptionCue(
                    cue_id=f"{line_id}.{slug}",
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    line_id=line_id,
                )
                for start, end, text, line_id in cues
            ],
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "caption_tracks",
                {
                    "id": track_id,
                    "episode_id": episode_id,
                    "locale": locale,
                    "version": version,
                    "timing_source": body.timing_source.value,
                    "body": jsonb(body),
                    "body_hash": canonical_hash(body),
                    "state": state,
                },
                returning="id",
            )
        return track_id

    def finding(
        self,
        episode_id: UUID,
        *,
        check_id: str,
        repair_targets: list[str],
        start_ms: int,
        end_ms: int,
        cycle: int = 1,
        outcome: str = "REPAIRABLE",
        severity: str = "CRITICAL",
        observed: str = "5,000 baht",
        expected: str = "50,000 baht",
    ) -> UUID:
        asset_id = uuid.uuid4()
        body = build_finding(
            run_key="repairs-test-run",
            episode_id=episode_id,
            asset_id=asset_id,
            start_ms=start_ms,
            end_ms=end_ms,
            check_id=check_id,
            family=CheckFamily.CAPTION if check_id.startswith("caption.") else CheckFamily.ASR,
            severity=Severity(severity),
            outcome=QAOutcome(outcome),
            coverage=CoverageStatus.CHECKED,
            expected=expected,
            observed=observed,
            evidence_source=EvidenceSource.FAKE_FIXTURE,
            evidence_ref="repairs-test",
            evidence_note="seeded for T019 planning tests",
            provenance=Provenance.FAKE_SYNTHETIC,
            repair_targets=[RepairTarget(t) for t in repair_targets],
        )
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "qa_findings",
                {
                    "id": body.finding_id,
                    "episode_id": episode_id,
                    "qa_cycle": cycle,
                    "asset_id": asset_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "check_id": check_id,
                    "check_family": body.check_family.value,
                    "source_pass": body.source_pass.value,
                    "severity": severity,
                    "coverage": "CHECKED",
                    "outcome": outcome,
                    "body": jsonb(body),
                    "resolution": "OPEN",
                },
                returning="id",
            )
        return body.finding_id

    def ready_package(self, episode_id: UUID, season_id: UUID) -> UUID:
        """A stored READY package (the example contract body, bound to this episode)."""
        package = example_package().model_copy(
            update={"episode_id": episode_id, "season_id": season_id}
        )
        with self.db.transaction() as tx:
            store_release_package(tx, package, status="READY", now=T0)
        return package.package_id

    def approve_episode(
        self, episode_id: UUID, season_id: UUID, caption_track_ids: list[UUID]
    ) -> UUID:
        """Drive the REAL Gate 2 APPROVE (T008's ReviewService) for episode number 2.

        Produces an APPROVED package and a RELEASE_APPROVED episode — the state a
        material media change must be refused from (no path back to Gate 2).
        """
        from microdrama.core.idempotency import IdempotencyService
        from microdrama.core.jobs import JobService
        from microdrama.review.service import ReviewService

        # one real, persisted master asset the approval can bind
        asset_id = uuid.uuid4()
        key = f"repairs/{asset_id.hex}.mp4"
        stored = self.store.put_bytes(key, b"fake-master-mp4-bytes", media_type="video/mp4")
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
                    provenance=Provenance.FAKE_SYNTHETIC,
                    episode_id=episode_id,
                    season_id=season_id,
                    created_at=T0,
                ),
            )
        example = example_package()
        slot = example.release_scope[0].model_copy(
            update={"asset_id": asset_id, "asset_sha256": stored.sha256}
        )
        draft = example.model_copy(
            update={
                "package_id": uuid.uuid4(),
                "episode_id": episode_id,
                "season_id": season_id,
                "episode_number": 2,
                "version": 1,
                "media": [MediaRef(asset_id=asset_id, sha256=stored.sha256, role="master")],
                "caption_track_ids": list(caption_track_ids),
                "cast_package_asset_ids": [],
                "hook_experiment_id": None,
                "release_scope": [slot],
            }
        )
        package = draft.model_copy(update={"package_hash": draft.compute_hash()})
        with self.db.transaction() as tx:
            store_release_package(tx, package, status="READY", now=T0)

        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            revision = tx.fetchone("SELECT revision FROM episodes WHERE id = %s", (episode_id,))[
                "revision"
            ]
        principal = Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )
        service = ReviewService(
            self.db,
            self.clock,
            self.ids,
            jobs=JobService(self.db, self.clock, self.ids),
            idempotency=IdempotencyService(self.db),
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
            idempotency_key=f"approve-{uuid.uuid4().hex}",
        )
        service.decide_episode(principal, episode_id, command)
        return package.package_id

    def line_audio_asset(self, episode_id: UUID, line_id: str, text_th: str) -> UUID:
        """The line-audio asset at the deterministic id the editing lane resolves."""
        asset_id = ref_id_for(
            "line-audio", f"{episode_id}:{line_id}:{canonical_hash(text_th)[:12]}"
        )
        key = f"repairs/{asset_id.hex}.wav"
        stored = self.store.put_bytes(key, b"fake-line-audio", media_type="audio/wav")
        with self.db.transaction() as tx:
            register_asset(
                tx,
                AssetDescriptor(
                    asset_id=asset_id,
                    asset_kind=AssetKind.AUDIO,
                    object_key=key,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type="audio/wav",
                    media=MediaInfo(duration_ms=3_000, has_video=False, has_audio=True),
                    state=AssetState.ACCEPTED,
                    provenance=Provenance.FAKE_SYNTHETIC,
                    episode_id=episode_id,
                    created_at=T0,
                ),
            )
        return asset_id

    def render_attempt_jobs(self, episode_number: int, shot_id: str, attempts: int) -> None:
        """Seed the render service's own durable attempt ledger (jobs rows).

        Inserted at the SQL level: the jobs table carries the ledger the router's
        ``attempt_semantic_key`` writes; only the typed enqueue validation is bypassed
        (the payload here is a fixture, not a real RenderRequest).
        """
        with self.db.transaction() as tx:
            for attempt in range(1, attempts + 1):
                key = f"render.shot:ep{episode_number}:{shot_id}:attempt{attempt}"
                tx.execute(
                    "INSERT INTO jobs (id, job_type, queue, semantic_key, input_hash, input, "
                    "status, episode_id) VALUES (%s, 'render.shot', 'production', %s, %s, %s, "
                    "'SUCCEEDED', NULL) ON CONFLICT (semantic_key) DO NOTHING",
                    (
                        uuid.uuid5(uuid.NAMESPACE_URL, key),
                        key,
                        canonical_hash({"fixture": key}),
                        jsonb({"schema_version": "1.0", "fixture": key}),
                    ),
                )

    def revise_feedback(
        self,
        episode_id: UUID,
        feedback: list[TimecodedFeedback],
    ) -> UUID:
        """A REAL Gate 2 REVISE decision (the only feedback_events writer)."""
        with self.db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            revision = tx.fetchone("SELECT revision FROM episodes WHERE id = %s", (episode_id,))[
                "revision"
            ]
        principal = Principal(
            principal_id=f"owner:{owner}", kind=PrincipalKind.HUMAN_OWNER, session_id=session
        )
        # The DB requires every Gate 2 decision to name the episode's current package.
        package_row = self.row(
            "SELECT package_hash FROM release_packages WHERE episode_id = %s "
            "AND status IN ('READY','BLOCKED') ORDER BY version DESC LIMIT 1",
            (episode_id,),
        )
        command = ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.REVISE,
            entity_id=episode_id,
            expected_revision=int(revision),
            package_hash=package_row["package_hash"] if package_row else "0" * 64,
            idempotency_key=f"revise-{uuid.uuid4().hex}",
            feedback=feedback,
        )
        with self.db.transaction() as tx:
            return record_approval_event(
                tx,
                principal=principal,
                command=command,
                now=datetime.now(UTC),
                correlation_id=uuid.uuid4(),
            )

    def released_episode_with_tracks(self) -> tuple[UUID, UUID, UUID, UUID]:
        """Episode 2 genuinely PAST Gate 2 (real APPROVE → RELEASE_APPROVED)."""
        episode_id, thai, english, _unused = self.episode_with_tracks(
            state="AWAITING_FINAL_REVIEW", number=2, with_package=False
        )
        season_row = self.row("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        package = self.approve_episode(episode_id, season_row["season_id"], [thai, english])
        return episode_id, thai, english, package

    def feedback_rows(self, approval_event_id: UUID) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM feedback_events WHERE approval_event_id = %s ORDER BY id",
            (approval_event_id,),
        )

    # episode with a pristine script, two CURRENT tracks and a READY package
    def episode_with_tracks(
        self,
        *,
        state: str = "AI_REVIEW",
        thai_l1_text: str | None = None,
        en_l1_text: str | None = None,
        thai_l2_text: str | None = None,
        en_l2_text: str | None = None,
        with_package: bool = True,
        number: int = 1,
    ) -> tuple[UUID, UUID, UUID, UUID | None]:
        """Pristine script + CURRENT th-TH/en-US tracks (L1 defective by default)
        + a READY package. Returns (episode_id, thai_track, en_track, package_id)."""
        season_id = self.season()
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, state=state, number=number)
        self.seed_script(episode_id)
        thai = self.caption_track(
            episode_id,
            "th-TH",
            [
                (10_000, 13_000, thai_l1_text or "หนี้ห้าพันบาท", L1),
                (14_000, 16_500, thai_l2_text or "แม่หนูไม่อยากให้หนูรู้", L2),
            ],
        )
        english = self.caption_track(
            episode_id,
            "en-US",
            [
                (10_000, 13_000, en_l1_text or "5,000 baht", L1),
                (14_000, 16_500, en_l2_text or "Your mother didn't want you to know.", L2),
            ],
        )
        package = self.ready_package(episode_id, season_id) if with_package else None
        return episode_id, thai, english, package


__all__ = [
    "EN_L1",
    "L1",
    "L2",
    "RecordingShotDispatch",
    "RepairsWorld",
    "THAI_L1",
]

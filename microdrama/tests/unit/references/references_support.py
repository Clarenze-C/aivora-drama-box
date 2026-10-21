"""Shared builders for the references tests (T011). Not a test module.

Real PostgreSQL, the real BudgetService, the real ReviewService (with THIS lane's
identity-lock hook wired in — the thing T008 stubbed), the T007 FakeGenerationProvider
for image and voice, and a filesystem object store. Scripts/manifests are seeded
directly in the shape T010 leaves them (voice_id/actual_duration_ms None,
voice_ids/required_reference_asset_ids empty) so this lane proves it fills them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    CaptionTimingSource,
    DisclosureKind,
    EvidenceSource,
    Platform,
    PrincipalKind,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
    SlotKind,
)
from microdrama.contracts.examples import ACCOUNT_YT, media_info, schedule, season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor, CaptionCue, CaptionTrack
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.release import (
    CostSummary,
    MediaRef,
    QASummary,
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
)
from microdrama.contracts.season import (
    ApprovalCommand,
    CriticalTerm,
    DialogueLine,
    Scene,
    Script,
    Shot,
    ShotManifest,
)
from microdrama.core.auth import AuthService
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.core.registry.rights import RightsRegistry
from microdrama.persistence import Database, insert_row, jsonb, register_asset
from microdrama.references import ReferencesService, build_references_service
from microdrama.references.config import ReferencesConfig as Cfg
from microdrama.review.packages import store_release_package
from microdrama.review.service import ReviewService
from microdrama.testing.fakes import (
    FakeClock,
    FakeGenerationProvider,
    SequentialIds,
)
from microdrama.testing.seed import seed_episode, seed_gate1_approval

T0 = datetime(2026, 10, 21, tzinfo=UTC)
FAKE = Provenance.FAKE_SYNTHETIC
FAKE_EVIDENCE = EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:references-lane")
MASTER_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-master-" * 64

# Episode-one dialogue: three speakers, two locations (matches the contracts example scope).
SCENE_1_LINES: list[tuple[str, str, str]] = [
    ("sc1-l1", "fon", "ลุงเล็ก ร้านข้าวมันไก่ของแม่เปิดได้อีกไหมคะ"),
    ("sc1-l2", "lek", "เปิดได้ แต่ต้องรีบเก็บรายได้ก่อนสิ้นเดือนนะหนู"),
    ("sc1-l3", "fon", "ทำไมลุงถึงเคร่งเครียดแบบนี้คะ"),
]
SCENE_2_LINES: list[tuple[str, str, str]] = [
    ("sc2-l1", "fon", "ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ"),
    ("sc2-l2", "lek", "แม่หนูไม่อยากให้หนูรู้"),
    ("sc2-l3", "nok", "ภายในวันศุกร์นะครับ"),
]


def _estimate(text: str) -> int:
    from microdrama.story.prompts import estimate_line_ms

    return estimate_line_ms(text)


class World:
    """One references service + review wiring, on the real database and fakes."""

    def __init__(self, db: Database, store: ObjectStore, settings: Settings) -> None:
        self.db = db
        self.store = store
        self.settings = settings
        self.clock = FakeClock(T0)
        self.ids = SequentialIds("references-tests")
        self.budget = BudgetService(db, self.clock, SequentialIds("references-budget"), settings)
        self.image = FakeGenerationProvider(clock=self.clock, ids=SequentialIds("ref-image"))
        self.voice = FakeGenerationProvider(clock=self.clock, ids=SequentialIds("ref-voice"))
        self.rights = RightsRegistry(db, self.clock, settings)
        self.seed_rights()
        self.service: ReferencesService = build_references_service(
            db,
            self.clock,
            self.ids,
            settings,
            budget=self.budget,
            store=store,
            image_provider=self.image,
            voice_provider=self.voice,
            rights=self.rights,
        )
        # Review wiring with THIS lane's real hook (T008 consumed a stub).
        self.auth = AuthService(db, self.clock, SequentialIds("references-auth"))
        self.jobs = JobService(db, self.clock, SequentialIds("references-jobs"))
        self.idempotency = IdempotencyService(db)
        self.release_conditions: Any = lambda tx, episode_row, package: []

    def review_service(self) -> ReviewService:
        return ReviewService(
            self.db,
            self.clock,
            SequentialIds("references-review"),
            jobs=self.jobs,
            idempotency=self.idempotency,
            budget=self.budget,
            store=self.store,
            release_conditions_fn=self.release_conditions,
            approval_hooks=[],
            identity_lock_hook=self.service.identity_lock_hook(),
        )

    # --- seeds -------------------------------------------------------------------------

    def seed_rights(self) -> None:
        for route, model in (
            (Cfg().image_rights_route_id, Cfg().image_model_config_ref),
            (Cfg().voice_rights_route_id, Cfg().voice_model_config_ref),
        ):
            for kind in (RightsSubjectKind.MODEL, RightsSubjectKind.MODEL_OUTPUT):
                self.rights.record(
                    RightsRecord(
                        record_id=uuid.uuid4(),
                        rights_route_id=route,
                        version=1,
                        subject_kind=kind,
                        subject_ref=model,
                        territories=["WORLDWIDE"],
                        commercial_use=True,
                        output_release_allowed=True,
                        required_disclosures=[DisclosureKind.SYNTHETIC_VOICE],
                        expires_at=T0 + timedelta(days=365),
                        evidence=[FAKE_EVIDENCE],
                        status=RightsStatus.ELIGIBLE,
                        recorded_at=T0,
                    ),
                    source_provenance=FAKE,
                )

    def season(self, *, approved: bool = True, scope: Any = None) -> tuple[uuid.UUID, Any]:
        season_id = uuid.uuid4()
        scope = (scope or season_scope()).model_copy(
            update={"season_id": season_id, "scope_version": 1}
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
                    "approved_at": T0 if approved else None,
                },
                returning="id",
            )
            insert_row(
                tx,
                "season_proposals",
                {
                    "id": uuid.uuid4(),
                    "season_id": season_id,
                    "scope_version": 1,
                    "scope": jsonb(scope),
                    "scope_hash": scope_hash,
                    "status": "APPROVED" if approved else "PROPOSED",
                },
                returning="id",
            )
            for character in scope.characters:
                tx.execute(
                    "INSERT INTO characters (id, season_id, character_key, name_th, name_en, "
                    "brief, state, first_episode_number) VALUES (%s, %s, %s, %s, %s, %s, "
                    "'PROVISIONAL', 1) ON CONFLICT (season_id, character_key) DO NOTHING",
                    (
                        uuid.uuid4(),
                        season_id,
                        character.character_id,
                        character.name_th,
                        character.name_en,
                        jsonb(character.model_dump(mode="json")),
                    ),
                )
        return season_id, scope

    def episode(
        self,
        season_id: uuid.UUID,
        scope: Any,
        *,
        number: int = 1,
        state: str = "SCRIPTING",
        identity_lock_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        with self.db.transaction() as tx:
            episode_id = seed_episode(tx, season_id, number=number, state=state)
            tx.execute(
                "UPDATE episodes SET approved_scope_hash = %s, identity_lock_id = %s WHERE id = %s",
                (canonical_hash(scope), identity_lock_id, episode_id),
            )
        return episode_id

    def seed_script_and_manifest(
        self,
        *,
        episode_id: uuid.UUID,
        scope: Any,
        number: int = 1,
        identity_lock_id: uuid.UUID | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """CURRENT script/manifest exactly as T010 leaves them (all reference fields open)."""
        script = Script(
            script_id=uuid.uuid4(),
            episode_id=episode_id,
            version=1,
            approved_scope_hash=canonical_hash(scope),
            canon_version=1,
            scenes=[
                Scene(
                    scene_id="sc1",
                    location_id="stall",
                    summary="Fon asks Uncle Lek about reopening.",
                    lines=[
                        DialogueLine(
                            line_id=line_id,
                            speaker_character_id=speaker,
                            voice_id=None,
                            text_th=text,
                            text_en=f"EN({line_id})",
                            estimated_duration_ms=_estimate(text),
                            actual_duration_ms=None,
                            critical_terms=(
                                [CriticalTerm(kind="NAME", value_th="ลุงเล็ก")]
                                if "ลุงเล็ก" in text
                                else []
                            ),
                        )
                        for line_id, speaker, text in SCENE_1_LINES
                    ],
                ),
                Scene(
                    scene_id="sc2",
                    location_id="shophouse-room",
                    summary="The hidden debt surfaces; Nok sets a deadline.",
                    lines=[
                        DialogueLine(
                            line_id=line_id,
                            speaker_character_id=speaker,
                            voice_id=None,
                            text_th=text,
                            text_en=f"EN({line_id})",
                            estimated_duration_ms=_estimate(text),
                            actual_duration_ms=None,
                            critical_terms=[],
                        )
                        for line_id, speaker, text in SCENE_2_LINES
                    ],
                ),
            ],
            estimated_runtime_ms=sum(_estimate(t) for _, _, t in [*SCENE_1_LINES, *SCENE_2_LINES])
            + 3_000,
        )
        shots = [
            Shot(
                shot_id="sh1",
                sequence=1,
                scene_id="sc1",
                shot_pattern_id="quiet_confession_v1",
                coverage_role="master",
                purpose="Fon gently probes Uncle Lek.",
                dramatic_importance="HIGH",
                dialogue_complexity="TWO_SPEAKER",
                temporal_risk="LOW",
                required_identity_controls=["TEXT_PROMPT", "CHARACTER_REFERENCE"],
                preferred_render_tier="quality_eight_step",
                fallback_edit="CUT_TO_REACTION",
                reference_lock_version=None,
                line_ids=["sc1-l1", "sc1-l2"],
                speaker_ids=["fon", "lek"],
                voice_ids=[],
                target_duration_ms=6_000,
                framing="medium two-shot",
                eyelines="fon to lek",
                location_id="stall",
                outfit_ids=[],
                prop_ids=[],
                required_reference_asset_ids=[],
                sound="morning market",
                acceptance_criteria=["both faces consistent"],
                depends_on_shot_ids=[],
            ),
            Shot(
                shot_id="sh2",
                sequence=2,
                scene_id="sc1",
                shot_pattern_id="comic_reaction_v1",
                coverage_role="reaction",
                purpose="Fon reacts to the deflection.",
                dramatic_importance="MEDIUM",
                dialogue_complexity="SINGLE_SPEAKER",
                temporal_risk="LOW",
                required_identity_controls=["TEXT_PROMPT"],
                preferred_render_tier="fast_four_step",
                fallback_edit="HOLD_PREVIOUS_FRAME",
                reference_lock_version=None,
                line_ids=["sc1-l3"],
                speaker_ids=["fon"],
                voice_ids=[],
                target_duration_ms=3_000,
                framing="close-up",
                eyelines="fon to lek",
                location_id="stall",
                outfit_ids=[],
                prop_ids=[],
                required_reference_asset_ids=[],
                sound="room tone",
                acceptance_criteria=["fon face matches sh1"],
                depends_on_shot_ids=["sh1"],
            ),
            Shot(
                shot_id="sh3",
                sequence=3,
                scene_id="sc2",
                shot_pattern_id="confrontation_v1",
                coverage_role="master",
                purpose="The debt lands; Nok's deadline sharpens it.",
                dramatic_importance="CRITICAL",
                dialogue_complexity="TWO_SPEAKER",
                temporal_risk="MEDIUM",
                required_identity_controls=[
                    "TEXT_PROMPT",
                    "CHARACTER_REFERENCE",
                    "VOICE_REFERENCE",
                ],
                preferred_render_tier="quality_eight_step",
                fallback_edit="WIDE_SHOT_OVER_DIALOGUE",
                reference_lock_version=None,
                line_ids=["sc2-l1", "sc2-l2", "sc2-l3"],
                speaker_ids=["fon", "lek", "nok"][:2],
                voice_ids=[],
                target_duration_ms=8_000,
                framing="wide three-shot",
                eyelines="triangle",
                location_id="shophouse-room",
                outfit_ids=[],
                prop_ids=[],
                required_reference_asset_ids=[],
                sound="quiet room tone",
                acceptance_criteria=["nok appears distinct"],
                depends_on_shot_ids=["sh1"],
            ),
        ]
        manifest = ShotManifest(
            manifest_id=uuid.uuid4(),
            episode_id=episode_id,
            episode_number=number,
            script_id=script.script_id,
            script_version=1,
            version=1,
            identity_lock_id=identity_lock_id,
            shots=shots,
        )
        with self.db.transaction() as tx:
            script_id = insert_row(
                tx,
                "scripts",
                {
                    "id": script.script_id,
                    "episode_id": episode_id,
                    "version": 1,
                    "canon_version": 1,
                    "body": jsonb(script),
                    "body_hash": canonical_hash(script),
                    "status": "CURRENT",
                },
                returning="id",
            )["id"]
            manifest_id = insert_row(
                tx,
                "shot_manifests",
                {
                    "id": manifest.manifest_id,
                    "episode_id": episode_id,
                    "script_id": script.script_id,
                    "version": 1,
                    "identity_lock_id": identity_lock_id,
                    "body": jsonb(manifest),
                    "body_hash": canonical_hash(manifest),
                    "status": "CURRENT",
                },
                returning="id",
            )["id"]
            tx.execute(
                "UPDATE episodes SET current_script_id = %s, current_manifest_id = %s "
                "WHERE id = %s",
                (script_id, manifest_id, episode_id),
            )
        return script_id, manifest_id

    def prepared_episode(self, *, number: int = 1, state: str = "SCRIPTING"):
        """Season + episode + seeded script/manifest + a successful prepare."""
        season_id, scope = self.season()
        episode_id = self.episode(season_id, scope, number=number, state=state)
        self.seed_script_and_manifest(episode_id=episode_id, scope=scope, number=number)
        outcome = self.service.prepare_episode(episode_id)
        return season_id, scope, episode_id, outcome

    # --- review packaging ----------------------------------------------------------------

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
        key = f"references-tests/{asset_id.hex}.bin"
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

    def caption(self, episode_id: uuid.UUID) -> uuid.UUID:
        existing = self.row(
            "SELECT id FROM caption_tracks WHERE episode_id = %s AND locale = 'th-TH' "
            "AND state = 'CURRENT'",
            (episode_id,),
        )
        if existing is not None:
            return existing["id"]
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
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "caption_tracks",
                {
                    "id": track_id,
                    "episode_id": episode_id,
                    "locale": "th-TH",
                    "version": 1,
                    "timing_source": CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT.value,
                    "body": jsonb(track),
                    "body_hash": canonical_hash(track),
                    "state": "CURRENT",
                },
                returning="id",
            )
        return track_id

    def store_review_package(
        self,
        *,
        season_id: uuid.UUID,
        scope: Any,
        episode_id: uuid.UUID,
        number: int = 1,
        cast: list[uuid.UUID] | None = None,
        version: int = 1,
    ) -> ReleasePackage:
        master_id, master_sha = self.asset(season_id=season_id, episode_id=episode_id)
        if cast is None:
            cast = self.service.cast_package_assets(episode_id)
        package = ReleasePackage.seal(
            package_id=uuid.uuid4(),
            episode_id=episode_id,
            season_id=season_id,
            episode_number=number,
            version=version,
            media=[MediaRef(asset_id=master_id, sha256=master_sha, role="master")],
            caption_track_ids=[self.caption(episode_id)],
            cast_package_asset_ids=list(cast),
            release_scope=[
                ReleaseSlotPlan(
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
            ],
            management_policy_hash=canonical_hash(scope.management_policy),
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
        with self.db.transaction() as tx:
            store_release_package(tx, package, status="READY", now=self.clock.now())
        return package

    def human(self):
        from microdrama.contracts.principals import Principal

        with self.db.transaction() as tx:
            from microdrama.testing.seed import seed_human_session, seed_owner

            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
        return Principal(
            principal_id=f"owner:{owner}",
            kind=PrincipalKind.HUMAN_OWNER,
            session_id=session,
        )

    def to_awaiting_review(self, episode_id: uuid.UUID) -> int:
        from microdrama.contracts.enums import EpisodeState
        from microdrama.contracts.principals import Principal, PrincipalKind
        from microdrama.core.state_machine import transition_episode

        actor = Principal(principal_id="svc:references-tests", kind=PrincipalKind.SERVICE_WORKER)
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "SELECT revision, state FROM episodes WHERE id = %s FOR UPDATE", (episode_id,)
            )
            revision = row["revision"]
            for target in (
                EpisodeState.ASSEMBLING,
                EpisodeState.AI_REVIEW,
                EpisodeState.AWAITING_FINAL_REVIEW,
            ):
                revision = transition_episode(
                    tx,
                    episode_id=episode_id,
                    to=target,
                    expected_revision=revision,
                    actor=actor,
                    now=self.clock.now(),
                    correlation_id=uuid.uuid4(),
                )
        return revision

    def approve_episode(
        self, episode_id: uuid.UUID, package: ReleasePackage, revision: int | None = None
    ):
        from microdrama.contracts.enums import ApprovalAction, GateType

        del revision  # the current revision is read fresh: package storage bumps it
        fresh = self.row("SELECT revision FROM episodes WHERE id = %s", (episode_id,))
        assert fresh is not None
        command = ApprovalCommand(
            gate=GateType.EPISODE_FINAL,
            action=ApprovalAction.APPROVE,
            entity_id=episode_id,
            expected_revision=fresh["revision"],
            package_hash=package.package_hash,
            media_hashes=package.media_hashes,
            management_policy_hash=package.management_policy_hash,
            release_scope_hash=package.release_scope_hash,
            idempotency_key=f"gate2-{uuid.uuid4().hex}",
        )
        return self.review_service().decide_episode(self.human(), episode_id, command)

    # --- reads --------------------------------------------------------------------------

    def row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchone(sql, params)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.db.transaction(readonly=True) as tx:
            return int(tx.fetchval(sql, params) or 0)

    def episode_state(self, episode_id: uuid.UUID) -> str:
        row = self.row("SELECT state FROM episodes WHERE id = %s", (episode_id,))
        assert row is not None
        return row["state"]

    def events(self, aggregate_id: uuid.UUID, event_type: str) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT payload FROM domain_events WHERE aggregate_id = %s AND event_type = %s "
            "ORDER BY sequence",
            (aggregate_id, event_type),
        )
        return [dict(row["payload"]) for row in rows]


__all__ = ["FAKE", "MASTER_BYTES", "SCENE_1_LINES", "SCENE_2_LINES", "T0", "World"]

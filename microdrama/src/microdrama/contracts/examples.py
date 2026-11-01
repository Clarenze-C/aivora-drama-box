"""Deterministic valid/invalid examples for every cross-module payload (SPEC §4.2).

Valid examples double as fixtures for consumer lanes: import ``valid_examples()``
or a specific builder instead of hand-writing payloads. All example data is
synthetic and labelled FAKE_SYNTHETIC/ORIGINAL_FIXTURE where provenance applies.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from microdrama.contracts.catalog import (
    EpisodeQualification,
    MemberPrice,
    MembershipCatalogEntry,
    MetricSnapshot,
    MetricValue,
    QualificationResult,
)
from microdrama.contracts.cost import (
    BillingAllocationBasis,
    BillingComponent,
    BillingFinalityState,
    BillingInvoiceVerification,
    BillingQueryState,
    BillingVerificationResult,
    BudgetReservationRequest,
    ExposureCeilings,
    OutputRef,
    PodLease,
    PriceQuote,
    ProviderOperation,
    ProviderOperationResult,
    RenderRequest,
    RunpodBillingAllocation,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    UsageReceipt,
    runpod_bucket_identity_sha256,
)
from microdrama.contracts.enums import (
    ApprovalAction,
    AssetKind,
    AssetState,
    BudgetCategory,
    BudgetScopeKind,
    CapabilityOperation,
    CapabilitySupport,
    CaptionTimingSource,
    CatalogPublicState,
    CheckFamily,
    ControlKind,
    CostBasis,
    CoverageStatus,
    CriticalTermKind,
    DialogueComplexity,
    DisclosureKind,
    EpisodeState,
    EvidenceSource,
    FallbackEdit,
    FeedbackCategory,
    FeedbackScope,
    GateType,
    IdentityAssetKind,
    LeaseState,
    Level,
    ManagementActionKind,
    MembershipProviderKind,
    Platform,
    PodState,
    PriceSource,
    PriceUnit,
    Provenance,
    ProviderOperationState,
    QAOutcome,
    QAPass,
    QualificationStatus,
    QueueName,
    ReceiptKind,
    RenderTier,
    RepairTarget,
    RepairTrigger,
    RightsStatus,
    RightsSubjectKind,
    Severity,
    ShotPattern,
    SlotKind,
    SnapshotWindow,
    TrackKind,
    TrafficKind,
)
from microdrama.contracts.events import DomainEvent
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import (
    AssetDescriptor,
    CaptionCue,
    CaptionTrack,
    EditDecisionList,
    EdlClip,
    HookCandidate,
    HookExperiment,
    MediaInfo,
    OutputFormat,
)
from microdrama.contracts.primitives import EvidenceRef, ScheduleInstant
from microdrama.contracts.qa import (
    ComparisonRequest,
    CoverageWindow,
    MediaUnderReview,
    NeutralQuestion,
    Observation,
    ObservationReport,
    ObservationRequest,
    QAFinding,
    RepairPlan,
    RepairStep,
    TranscriptSegment,
)
from microdrama.contracts.registries import PresetMeasurements, PresetRecord, RightsRecord
from microdrama.contracts.release import (
    CapabilityRecord,
    CostSummary,
    CreativeDerivativeRef,
    DerivativeSourceRef,
    ManagementAction,
    MediaRef,
    PlatformSafeZone,
    PostMetadata,
    PublicationCommand,
    QASummary,
    ReleasePackage,
    ReleaseSlotKey,
    ReleaseSlotPlan,
    SafeZoneTextBox,
)
from microdrama.contracts.routes import EpisodeReviewView
from microdrama.contracts.season import (
    ApprovalCommand,
    ArcBeat,
    CharacterBrief,
    CriticalTerm,
    DestinationSlotPlan,
    DialogueLine,
    EpisodePlan,
    IdentityLock,
    LockedAsset,
    ManagementPolicy,
    ReleaseCadence,
    Scene,
    Script,
    SeasonScope,
    Shot,
    ShotManifest,
    TimecodedFeedback,
)
from microdrama.contracts.v2 import (
    ApprovedMetadataPolicy,
    ApprovedSlotMetadata,
    AssetSheet,
    ConceptCandidate,
    ConceptIntake,
    DirectingManifest,
    DirectingSection,
    DirectingShot,
    EpisodePack,
    EpisodeScene,
    LocationLayout,
    OutfitDefinition,
    PackBeat,
    PayoffDebt,
    ProgressSnapshot,
    ProgressStage,
    PromptManifest,
    PropSheet,
    ReferenceRole,
    ReleaseApprovalManifest,
    RightsGrant,
    SceneWardrobeAssignment,
    SeasonEscalation,
    SeasonStoryLedger,
    SecretEntry,
    SecretLedger,
    ShotReferenceBinding,
    StateEvent,
    StateValue,
    StyleBible,
    V1ManifestReadback,
    WardrobeBible,
)
from microdrama.contracts.v2 import (
    CharacterLogic as V2CharacterLogic,
)
from microdrama.contracts.v2 import (
    RightsStatus as V2RightsStatus,
)
from microdrama.contracts.v2 import (
    StoryTime as V2StoryTime,
)

T0 = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
V2_T0 = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
FAKE = Provenance.FAKE_SYNTHETIC


def uid(name: str) -> UUID:
    """Deterministic example UUID."""
    return uuid5(NAMESPACE_URL, f"https://microdrama.invalid/examples/{name}")


def h(name: str) -> str:
    """Deterministic example SHA-256."""
    return canonical_hash({"example": name})


def _v2_record(model, name: str, **values):
    """Build an example with a reproducible hash over the completed record."""
    defaults = {
        "record_id": uid(f"v2-{name}"),
        "version": 1,
        "content_sha256": h(f"placeholder-{name}"),
        "created_at": V2_T0,
        "updated_at": V2_T0,
        "valid_from": V2_T0,
    }
    defaults.update(values)
    return model.seal(**defaults)


def v2_rights() -> RightsGrant:
    return RightsGrant(
        rights_route_id="original-fiction",
        subject_kind="MODEL_OUTPUT",
        subject_ref="original-fiction-output",
        rights_version=1,
        status=V2RightsStatus.ELIGIBLE,
        territories=["TH"],
        commercial_use=True,
        output_release_allowed=True,
        evidence_sha256=[h("v2-rights-evidence")],
    )


def v2_concept_intake() -> ConceptIntake:
    return _v2_record(
        ConceptIntake,
        "intake",
        story_idea="A daughter returns to save her mother's stall.",
        genre_tags=["family_drama"],
        tone="Warm, grounded",
        requested_episode_count=10,
    )


def v2_character_logic() -> V2CharacterLogic:
    return _v2_record(
        V2CharacterLogic,
        "character-logic",
        character_id="fon",
        season_id=SEASON_ID,
        observable_goal="Keep the family stall open.",
        strategy="Negotiate with creditors.",
        flaw="Hides fear behind control.",
        secret_id="co_signed_debt",
        relationship_pressures=["Uncle Lek wants the truth kept quiet."],
        knowledge_by_episode={"1": ["debt_exists"]},
    )


def v2_concept_candidate() -> ConceptCandidate:
    intake = v2_concept_intake()
    return _v2_record(
        ConceptCandidate,
        "candidate",
        intake_id=intake.record_id,
        title_th="ร้านของแม่",
        title_en="Mother's Stall",
        logline="A daughter returns to save a family stall.",
        promise="Each debt reveals a family choice.",
        payoff_debt=["Who co-signed the loan"],
        escalation=["The creditor shortens the deadline."],
        episode_count=10,
        scope_sha256=h("candidate-scope"),
        rights=v2_rights(),
    )


def v2_concept_candidate_pending_rights() -> ConceptCandidate:
    candidate = v2_concept_candidate()
    values = candidate.model_dump(mode="python")
    values["rights"] = {
        "status": "PENDING",
        "note": "Confirm commercial output release and territories before production.",
    }
    return ConceptCandidate.seal(**values)


def v2_secret_ledger() -> SecretLedger:
    return _v2_record(
        SecretLedger,
        "secret-ledger",
        season_id=SEASON_ID,
        secrets=[
            SecretEntry(
                secret_id="co_signed_debt",
                held_by_character_id="lek",
                fact="Lek co-signed the loan.",
                planned_reveal_episode=2,
                known_by_character_ids=["lek"],
            )
        ],
    )


def v2_season_story_ledger() -> SeasonStoryLedger:
    character = v2_character_logic()
    secrets = v2_secret_ledger()
    return _v2_record(
        SeasonStoryLedger,
        "season-story-ledger",
        season_id=SEASON_ID,
        approved_scope_hash=h("approved-season-scope"),
        promise="Each debt reveals a family choice.",
        payoff_debts=[
            PayoffDebt(
                debt_id="co_signed_debt",
                description="Reveal who co-signed the loan.",
                due_episode=2,
                status="OPEN",
            )
        ],
        escalations=[
            SeasonEscalation(episode_number=1, description="The creditor arrives early."),
            SeasonEscalation(episode_number=2, description="The deadline is shortened."),
        ],
        character_logic_record_ids=[character.record_id],
        secret_ledger_id=secrets.record_id,
    )


def v2_story_time() -> V2StoryTime:
    return _v2_record(
        V2StoryTime, "story-time", story_day=1, local_time="09:30", setting="Morning at the stall"
    )


def v2_state_value(entity: str, field: str, value: str) -> StateValue:
    return StateValue(entity_id=entity, field=field, value=value)


def v2_episode_pack() -> EpisodePack:
    character = v2_character_logic()
    scene = EpisodeScene(
        scene_id="scene-1",
        scene_number=1,
        story_time=v2_story_time(),
        location_id="stall",
        visible_character_ids=["fon"],
        beats=[
            PackBeat(
                beat_id="beat-1",
                function="revelation",
                visible_action="Fon reads the debt ledger.",
                state_in=[v2_state_value("ledger", "open", "closed")],
                state_out=[v2_state_value("ledger", "open", "open")],
            )
        ],
        state_in=[v2_state_value("ledger", "open", "closed")],
        state_out=[v2_state_value("ledger", "open", "open")],
    )
    return _v2_record(
        EpisodePack,
        "episode-pack",
        episode_id=EP1_ID,
        season_id=SEASON_ID,
        approved_scope_hash=h("approved-season-scope"),
        episode_number=1,
        duration_target_ms=220_000,
        character_logic=[character],
        promise="Each debt reveals a family choice.",
        payoff_debt=["Who co-signed"],
        escalation="The creditor arrives early.",
        scenes=[scene],
    )


def v2_outfit() -> OutfitDefinition:
    return OutfitDefinition(
        outfit_id="fon-apron",
        version=1,
        asset_id=uid("fon-apron-asset"),
        asset_version=1,
        asset_sha256=h("fon-apron-image"),
        story_day_from=1,
        setting_tags=["stall"],
        rights=v2_rights(),
    )


def v2_wardrobe_bible() -> WardrobeBible:
    return _v2_record(
        WardrobeBible, "wardrobe", season_id=SEASON_ID, character_id="fon", outfits=[v2_outfit()]
    )


def v2_wardrobe_assignment() -> SceneWardrobeAssignment:
    return _v2_record(
        SceneWardrobeAssignment,
        "wardrobe-assignment",
        episode_id=EP1_ID,
        scene_id="scene-1",
        character_id="fon",
        story_day=1,
        setting="stall",
        wardrobe_bible_id=uid("v2-wardrobe"),
        wardrobe_bible_version=1,
        outfit_id="fon-apron",
        outfit_version=1,
        asset_id=uid("fon-apron-asset"),
        asset_version=1,
        asset_sha256=h("fon-apron-image"),
        rights=v2_rights(),
    )


def v2_state_event() -> StateEvent:
    return _v2_record(
        StateEvent,
        "state-event",
        episode_id=EP1_ID,
        sequence=1,
        entity_id="ledger",
        field="open",
        before="closed",
        after="open",
        scene_id="scene-1",
        effective_from_ms=0,
        effective_until_ms=4000,
        evidence_sha256=h("ledger-state-observation"),
    )


def v2_directing_manifest() -> DirectingManifest:
    pack = v2_episode_pack()
    scene = pack.scenes[0]
    beat = scene.beats[0]
    event = v2_state_event()
    scene_source_hash = canonical_hash(scene.model_copy(update={"beats": []}))
    shot_source_hashes = sorted({scene_source_hash, canonical_hash(beat), event.content_sha256})
    source_hashes = sorted({pack.content_sha256, *shot_source_hashes})
    shot_id = "shot-example-1"
    section_id = "section-example-1"
    shot = DirectingShot(
        shot_id=shot_id,
        scene_id=scene.scene_id,
        beat_id=beat.beat_id,
        sequence=1,
        duration_ms=15_000,
        section_id=section_id,
        state_in=beat.state_in,
        events=[event],
        state_out=beat.state_out,
        screen_axis="stall-counter-axis",
        screen_direction="STATIC",
        eyeline="Fon looks down at the debt ledger.",
        action_handoff="Fon opens the ledger and holds on the debt entry.",
        sound_intent="Quiet stall ambience under the paper movement.",
        edit_intent="Cut to a close insert on the ledger entry.",
        framing="medium_close_up",
        source_dependency_ids=[pack.record_id.hex, scene.scene_id, beat.beat_id],
        source_hashes=shot_source_hashes,
    )
    return _v2_record(
        DirectingManifest,
        "directing-manifest",
        episode_id=pack.episode_id,
        pack_id=pack.record_id,
        pack_version=pack.version,
        pack_hash=pack.content_sha256,
        approved_scope_hash=pack.approved_scope_hash,
        shots=[shot],
        sections=[
            DirectingSection(
                section_id=section_id,
                sequence=1,
                shot_ids=[shot_id],
                duration_ms=15_000,
            )
        ],
        source_hashes=source_hashes,
    )


def v2_directing_shot() -> DirectingShot:
    return v2_directing_manifest().shots[0]


def v2_directing_section() -> DirectingSection:
    return v2_directing_manifest().sections[0]


def v2_asset_sheet() -> AssetSheet:
    return _v2_record(
        AssetSheet,
        "asset-sheet",
        asset_role="outfit",
        subject_id="fon-apron",
        asset_id=uid("fon-apron-asset"),
        asset_version=1,
        asset_sha256=h("fon-apron-image"),
        view_name="front",
        rights=v2_rights(),
        validity_from=V2_T0,
    )


def v2_prop_sheet() -> PropSheet:
    return _v2_record(
        PropSheet,
        "prop-sheet",
        prop_id="ledger",
        purpose="Carries the debt evidence Fon reads.",
        visual_anchor="Dark green cloth ledger with a brass corner.",
        owner_character_id="fon",
        dimensions="A5 notebook",
        known_states=["closed", "open"],
        text_layer_sha256=h("ledger-text-layer"),
        asset_id=uid("ledger-prop-asset"),
        asset_version=1,
        asset_sha256=h("ledger-prop-image"),
        rights=v2_rights(),
    )


def v2_style_bible() -> StyleBible:
    return _v2_record(
        StyleBible,
        "style-bible",
        season_id=SEASON_ID,
        medium="Live-action cinematic short drama",
        realism="Grounded naturalistic performances",
        palette=["warm rice gold", "deep teal"],
        lighting_language="Soft window daylight with motivated practicals.",
        lens_and_movement="Restrained handheld, eye-level lenses, motivated pushes.",
        material_rules=["Natural fabric texture", "Readable paper and food surfaces"],
        typography_rules=["Thai captions use approved readable type"],
        subtitle_safe_top_bp=500,
        subtitle_safe_bottom_bp=1200,
        sound_motifs=["Bangkok morning traffic", "Stall kitchen rhythm"],
        exclusions=["No glossy luxury-ad lighting", "No unreadable generated text"],
        moving_sample_asset_id=uid("style-moving-sample"),
        moving_sample_sha256=h("style-moving-sample"),
        rights=v2_rights(),
    )


def v2_location_layout() -> LocationLayout:
    return _v2_record(
        LocationLayout,
        "location-layout",
        location_id="stall",
        geometry_sha256=h("stall-geometry"),
        entrance_ids=["front-door"],
        camera_zones=["counter", "door"],
        light_states=["morning"],
        prop_ownership={"ledger": "fon"},
        rights=v2_rights(),
    )


def v2_reference_binding(
    role: ReferenceRole, subject: str, asset: str, image_hash: str
) -> ShotReferenceBinding:
    return _v2_record(
        ShotReferenceBinding,
        f"binding-{role.value}-{subject}",
        role=role,
        subject_id=subject,
        asset_id=uid(asset),
        asset_version=1,
        asset_sha256=h(image_hash),
        rights=v2_rights(),
        valid_from=V2_T0,
    )


def v2_binding_example() -> ShotReferenceBinding:
    return v2_reference_binding(ReferenceRole.CHARACTER_IDENTITY, "fon", "fon-id", "fon-id-image")


def v2_prompt_manifest() -> PromptManifest:
    return _v2_record(
        PromptManifest,
        "prompt-manifest",
        episode_id=EP1_ID,
        shot_id="shot-1",
        shot_sequence=1,
        shot_duration_ms=10_000,
        prompt_text="Fon reads the ledger in the morning stall.",
        bindings=[
            v2_reference_binding(ReferenceRole.CHARACTER_IDENTITY, "fon", "fon-id", "fon-id-image"),
            v2_reference_binding(ReferenceRole.OUTFIT, "fon", "fon-apron", "fon-apron-image"),
            v2_reference_binding(ReferenceRole.LOCATION, "stall", "stall-front", "stall-image"),
        ],
        source_hashes=[h("story-source"), h("wardrobe-source")],
    )


def v2_progress_snapshot() -> ProgressSnapshot:
    return _v2_record(
        ProgressSnapshot,
        "progress",
        aggregate_id=EP1_ID,
        projection_revision=1,
        source_event_ids=[uid("event-1")],
        source_job_ids=[uid("job-1")],
        production_stage=ProgressStage.RUNNING,
        release_stage=ProgressStage.PLANNED,
        accepted_work=1,
        required_work=4,
        blocker_ids=[],
        next_action="Render next shot",
        progress_bp=2500,
    )


def _v2_release_approval_manifest(source: str) -> ReleaseApprovalManifest:
    package_id = uid("v2-release-package")
    package_hash = h("v1-release-package-hash")
    policy = ApprovedMetadataPolicy.seal(
        policy_id="approved-slot-metadata",
        version=1,
        mutable_fields=["title", "caption", "description", "hashtags", "cover", "cta"],
    )
    slot = _v2_record(
        ApprovedSlotMetadata,
        "approved-metadata-tiktok",
        release_package_id=package_id,
        release_package_hash=package_hash,
        slot_id="tiktok-acct-main-full_episode",
        metadata_id=uid("metadata-v1"),
        metadata_version=1,
        locale="th-TH",
        title="ร้านของแม่ ตอนที่ 1",
        caption="เรื่องราวต้นฉบับภาษาไทย",
        description="ละครสั้นเรื่องใหม่",
        hashtags=["ละครไทย"],
        links=["https://example.invalid/episode/1"],
        disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
        catalog_version=1,
        cover_asset_id=uid("cover-v1"),
        cover_asset_version=1,
        cover_asset_sha256=h("cover-image"),
        cta_text="ดูตอนต่อไป",
        cover_rights=v2_rights(),
        metadata_policy_id=policy.policy_id,
        metadata_policy_version=policy.version,
        metadata_policy_sha256=policy.policy_sha256,
        source=source,
    )
    return ReleaseApprovalManifest.seal(
        schema_version="2.0",
        manifest_id=uid("release-manifest-pre-gate"),
        version=1,
        created_at=V2_T0,
        release_package_id=package_id,
        release_package_hash=package_hash,
        metadata_policy=policy,
        slots=[slot],
        approval_manifest_sha256=h("placeholder-approval"),
    )


def v2_release_approval_manifest() -> ReleaseApprovalManifest:
    return _v2_release_approval_manifest("EXAMPLE")


def v2_owner_approved_release_approval_manifest() -> ReleaseApprovalManifest:
    return _v2_release_approval_manifest("OWNER_APPROVED")


def v1_manifest_readback() -> V1ManifestReadback:
    payload = shot_manifest().model_dump(mode="json")
    return V1ManifestReadback(
        source_schema_version="1.0", manifest_sha256=canonical_hash(payload), manifest=payload
    )


V2_VALID_BUILDERS: dict[str, Callable[[], BaseModel]] = {
    "ConceptIntake": v2_concept_intake,
    "ConceptCandidate": v2_concept_candidate,
    "CharacterLogic": v2_character_logic,
    "SecretLedger": v2_secret_ledger,
    "SeasonStoryLedger": v2_season_story_ledger,
    "EpisodePack": v2_episode_pack,
    "DirectingManifest": v2_directing_manifest,
    "StoryTime": v2_story_time,
    "WardrobeBible": v2_wardrobe_bible,
    "SceneWardrobeAssignment": v2_wardrobe_assignment,
    "StateEvent": v2_state_event,
    "AssetSheet": v2_asset_sheet,
    "PropSheet": v2_prop_sheet,
    "StyleBible": v2_style_bible,
    "LocationLayout": v2_location_layout,
    "ShotReferenceBinding": v2_binding_example,
    "PromptManifest": v2_prompt_manifest,
    "ProgressSnapshot": v2_progress_snapshot,
    "ReleaseApprovalManifest": v2_release_approval_manifest,
    "V1ManifestReadback": v1_manifest_readback,
}


SEASON_ID = uid("season")
EP1_ID = uid("episode-1")
EP2_ID = uid("episode-2")
ACCOUNT_TT = "acct:tiktok-main"
ACCOUNT_YT = "acct:youtube-main"


# --- builders (valid) ------------------------------------------------------------------------


def management_policy() -> ManagementPolicy:
    return ManagementPolicy(
        allowed_actions=frozenset(
            {
                ManagementActionKind.TITLE_EDIT,
                ManagementActionKind.CAPTION_EDIT,
                ManagementActionKind.HASHTAG_EDIT,
                ManagementActionKind.PUBLIC_REPLY,
                ManagementActionKind.DM_SEND,
                ManagementActionKind.MODERATE_HIDE,
            }
        ),
        dm_keywords=["ตอนต่อไป", "next"],
    )


def season_scope() -> SeasonScope:
    return SeasonScope(
        season_id=SEASON_ID,
        scope_version=1,
        source_proposal_id=uid("proposal"),
        title_th="ร้านข้าวมันไก่ของแม่",
        title_en="Mother's Chicken Rice Stall",
        logline="A daughter returns to Bangkok to save her late mother's food stall from a debt she never knew about.",
        premise="Original fiction. Family obligation, money pressure and quiet reconciliation over ten episodes.",
        genre_tags=["family", "drama"],
        expected_episode_count=10,
        arc=[
            ArcBeat(
                episode_number=1,
                summary="Fon discovers the stall's hidden debt.",
                cliffhanger="The lender arrives early.",
            ),
            ArcBeat(
                episode_number=2,
                summary="Fon negotiates for time and learns who co-signed.",
                planned_reveals=["Uncle Lek co-signed"],
            ),
        ],
        characters=[
            CharacterBrief(
                character_id="fon",
                name_th="ฝน",
                name_en="Fon",
                role="lead",
                description="Returning daughter, pragmatic, guarded.",
                voice_direction="warm, clipped when stressed",
            ),
            CharacterBrief(
                character_id="lek",
                name_th="ลุงเล็ก",
                name_en="Uncle Lek",
                role="supporting",
                description="Stall cook, loyal, hiding guilt.",
                voice_direction="low, gentle",
            ),
            CharacterBrief(
                character_id="nok",
                name_th="นก",
                name_en="Nok",
                role="antagonist",
                description="Lender's collector, polite and relentless.",
                voice_direction="even, formal",
            ),
        ],
        destinations=[
            DestinationSlotPlan(
                platform=Platform.TIKTOK, account_ref=ACCOUNT_TT, slot_kind=SlotKind.PART
            ),
            DestinationSlotPlan(
                platform=Platform.YOUTUBE, account_ref=ACCOUNT_YT, slot_kind=SlotKind.FULL_EPISODE
            ),
        ],
        release_cadence=ReleaseCadence(
            iana_zone="Asia/Bangkok", weekdays=[2, 5], local_times=["19:30"]
        ),
        management_policy=management_policy(),
        rights_route_id=None,
        research_evidence_refs=["fixture:source/thai-family-drama-themes"],
        originality_statement="Premise, characters and plot are original; comparables were used only for theme coding.",
        uncertainty_notes=[
            "Audience response is untested; theme signals come from fixture sources."
        ],
    )


def approval_gate1() -> ApprovalCommand:
    return ApprovalCommand(
        gate=GateType.SEASON_CONCEPT,
        action=ApprovalAction.APPROVE,
        entity_id=SEASON_ID,
        expected_revision=3,
        package_hash=canonical_hash(season_scope()),
        idempotency_key="gate1-approve-season-0001",
    )


def approval_gate2_revise() -> ApprovalCommand:
    return ApprovalCommand(
        gate=GateType.EPISODE_FINAL,
        action=ApprovalAction.REVISE,
        entity_id=EP1_ID,
        expected_revision=7,
        package_hash=release_package().package_hash,
        idempotency_key="gate2-revise-ep1-0001",
        feedback=[
            TimecodedFeedback(
                category=FeedbackCategory.SUBTITLES,
                start_ms=12_000,
                end_ms=15_500,
                comment="English subtitle says 5,000 baht; Fon says 50,000.",
                scope=FeedbackScope.EPISODE,
            )
        ],
    )


def episode_plan() -> EpisodePlan:
    return EpisodePlan(
        episode_id=EP1_ID,
        season_id=SEASON_ID,
        approved_scope_hash=canonical_hash(season_scope()),
        episode_number=1,
        title_th="หนี้ที่ไม่มีใครบอก",
        title_en="The Debt Nobody Mentioned",
        synopsis="Fon reopens the stall and finds a ledger page showing a 50,000 baht debt.",
        target_duration_ms=240_000,
        featured_character_ids=["fon", "lek", "nok"],
        location_ids=["stall", "shophouse-room"],
        planned_beats=["Reopening", "Ledger discovery", "Collector arrives"],
        cliffhanger="Nok sets a deadline for Friday.",
    )


def script() -> Script:
    return Script(
        script_id=uid("script-ep1"),
        episode_id=EP1_ID,
        version=1,
        approved_scope_hash=canonical_hash(season_scope()),
        canon_version=1,
        estimated_runtime_ms=240_000,
        scenes=[
            Scene(
                scene_id="s1",
                location_id="stall",
                summary="Fon finds the ledger.",
                lines=[
                    DialogueLine(
                        line_id="s1-l1",
                        speaker_character_id="fon",
                        voice_id="voice-fon-v1",
                        text_th="ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ",
                        text_en="Uncle Lek, what is this fifty-thousand-baht debt?",
                        estimated_duration_ms=3_200,
                        critical_terms=[
                            CriticalTerm(
                                kind=CriticalTermKind.MONEY,
                                value_th="ห้าหมื่นบาท",
                                value_en="50,000 baht",
                            )
                        ],
                    ),
                    DialogueLine(
                        line_id="s1-l2",
                        speaker_character_id="lek",
                        voice_id="voice-lek-v1",
                        text_th="แม่หนูไม่อยากให้หนูรู้",
                        text_en="Your mother didn't want you to know.",
                        estimated_duration_ms=2_600,
                        critical_terms=[
                            CriticalTerm(kind=CriticalTermKind.NEGATION, value_th="ไม่อยาก")
                        ],
                    ),
                ],
            ),
            Scene(
                scene_id="s2",
                location_id="shophouse-room",
                summary="Nok arrives.",
                lines=[
                    DialogueLine(
                        line_id="s2-l1",
                        speaker_character_id="nok",
                        voice_id="voice-nok-v1",
                        text_th="ภายในวันศุกร์นะครับ",
                        text_en="By Friday, please.",
                        estimated_duration_ms=1_800,
                        critical_terms=[
                            CriticalTerm(
                                kind=CriticalTermKind.DATE_TIME, value_th="วันศุกร์", value_en="Friday"
                            )
                        ],
                    ),
                ],
            ),
        ],
    )


def shot(shot_id: str = "sh1", sequence: int = 1) -> Shot:
    return Shot(
        shot_id=shot_id,
        sequence=sequence,
        scene_id="s1",
        shot_pattern_id=ShotPattern.REVELATION,
        coverage_role="evidence_or_action",
        purpose="Fon reads the ledger amount.",
        dramatic_importance=Level.HIGH,
        dialogue_complexity=DialogueComplexity.SINGLE_SPEAKER,
        temporal_risk=Level.MEDIUM,
        required_identity_controls=[ControlKind.CHARACTER_REFERENCE, ControlKind.FIRST_FRAME],
        preferred_render_tier=RenderTier.QUALITY_EIGHT_STEP,
        fallback_edit=FallbackEdit.COMPOSITE_TEXT_INSERT,
        reference_lock_version=None,
        line_ids=["s1-l1"],
        speaker_ids=["fon"],
        voice_ids=["voice-fon-v1"],
        target_duration_ms=4_000,
        framing="medium close-up, ledger in lower third",
        eyelines="Fon looks down-left at ledger",
        location_id="stall",
        outfit_ids=["fon-apron-v1"],
        prop_ids=["ledger-v1"],
        required_reference_asset_ids=[uid("ref-fon-face")],
        sound="stall ambience, distant traffic",
        acceptance_criteria=[
            "ledger amount readable via composite insert",
            "Fon identity matches anchor",
        ],
    )


def shot_manifest() -> ShotManifest:
    return ShotManifest(
        manifest_id=uid("manifest-ep1"),
        episode_id=EP1_ID,
        episode_number=1,
        script_id=uid("script-ep1"),
        script_version=1,
        version=1,
        shots=[shot(), shot("sh2", 2).model_copy(update={"depends_on_shot_ids": ["sh1"]})],
    )


def identity_lock() -> IdentityLock:
    return IdentityLock(
        lock_id=uid("lock-1"),
        season_id=SEASON_ID,
        source_episode_id=EP1_ID,
        version=1,
        approval_event_id=uid("approval-ep1"),
        release_package_hash=release_package().package_hash,
        locked_assets=[
            LockedAsset(
                asset_kind=IdentityAssetKind.FACE,
                asset_id=uid("ref-fon-face"),
                asset_version=1,
                content_sha256=h("fon-face"),
                character_id="fon",
                label="Fon face anchor",
            ),
            LockedAsset(
                asset_kind=IdentityAssetKind.VOICE,
                asset_id=uid("voice-fon-anchor"),
                asset_version=1,
                content_sha256=h("fon-voice"),
                character_id="fon",
                label="Fon voice anchor",
            ),
        ],
        created_at=T0,
    )


def price_quote() -> PriceQuote:
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=250,
        source=PriceSource.FAKE_SYNTHETIC,
        price_table_version="fake-prices-v1",
        as_of=T0,
    )


def budget_reservation_request() -> BudgetReservationRequest:
    return BudgetReservationRequest(
        request_id=uid("reservation-request-1"),
        semantic_key="render.shot:ep1:sh1:attempt1",
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=EP1_ID,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        job_id=uid("job-render-sh1"),
        provider="fake-runpod",
        operation_kind="gpu.render_shot",
        price=price_quote(),
        ceilings=ExposureCeilings(timeout_ms=600_000, max_units=600, max_duration_ms=4_000),
        worst_case_micro_usd=150_000,
        expires_at=T0 + timedelta(hours=1),
    )


def runpod_billing_bucket_observation() -> RunpodBillingBucketObservation:
    return RunpodBillingBucketObservation(
        observation_id=uid("runpod-billing-bucket-r1"),
        query_id=uid("runpod-billing-query-1"),
        provider_account_ref="acct:runpod-fixture",
        pod_id="pod-fixture-001",
        bucket_start=T0,
        bucket_end=T0 + timedelta(seconds=3600),
        bucket_size_seconds=3600,
        bucket_identity_sha256=runpod_bucket_identity_sha256(
            "acct:runpod-fixture",
            "pod-fixture-001",
            T0,
            T0 + timedelta(seconds=3600),
            3600,
        ),
        revision=1,
        provider_resolved_window_start=T0,
        provider_resolved_window_end=T0 + timedelta(seconds=3600),
        raw_response_sha256=h("runpod-billing-response-r1"),
        observed_at=T0 + timedelta(seconds=3601),
        currency="USD",
        total_amount_micro_usd=1_000_000,
        gpu_amount_micro_usd=500_000,
        cpu_amount_micro_usd=300_000,
        disk_amount_micro_usd=200_000,
        finality_state=BillingFinalityState.ALLOCATED_PROVIDER_REPORTED,
    )


def runpod_billing_bucket_invoice_verified() -> RunpodBillingBucketObservation:
    bucket = runpod_billing_bucket_observation()
    payload = bucket.model_dump(mode="python")
    payload.update(
        finality_state=BillingFinalityState.INVOICE_VERIFIED,
        invoice_verification_id=uid("runpod-invoice-verification-1"),
    )
    return RunpodBillingBucketObservation.model_validate(payload)


def runpod_billing_bucket_disputed() -> RunpodBillingBucketObservation:
    bucket = runpod_billing_bucket_observation().model_dump(mode="python")
    bucket.update(
        total_amount_micro_usd=1_000_001,
        finality_state=BillingFinalityState.DISPUTED,
        dispute_reason="Provider total differs from component sum.",
    )
    return RunpodBillingBucketObservation.model_validate(bucket)


def runpod_billing_query_observation() -> RunpodBillingQueryObservation:
    return RunpodBillingQueryObservation(
        query_id=uid("runpod-billing-query-1"),
        provider_account_ref="acct:runpod-fixture",
        requested_window_start=T0,
        requested_window_end=T0 + timedelta(hours=1),
        provider_resolved_window_start=T0,
        provider_resolved_window_end=T0 + timedelta(hours=1),
        bucket_size_seconds=3600,
        raw_response_sha256=h("runpod-billing-response-r1"),
        observed_at=T0 + timedelta(seconds=3601),
        result_state=BillingQueryState.BUCKETS,
        bucket_observation_ids=[uid("runpod-billing-bucket-r1")],
    )


def runpod_billing_query_empty() -> RunpodBillingQueryObservation:
    query = runpod_billing_query_observation().model_dump(mode="python")
    query.update(result_state=BillingQueryState.EMPTY, bucket_observation_ids=[])
    return RunpodBillingQueryObservation.model_validate(query)


def runpod_billing_query_unknown() -> RunpodBillingQueryObservation:
    query = runpod_billing_query_observation().model_dump(mode="python")
    query.update(
        result_state=BillingQueryState.UNKNOWN,
        bucket_observation_ids=[],
        unknown_reason="Provider response was unavailable.",
    )
    return RunpodBillingQueryObservation.model_validate(query)


def runpod_billing_allocation(
    component: BillingComponent = BillingComponent.GPU,
) -> RunpodBillingAllocation:
    amounts = {
        BillingComponent.GPU: 500_000,
        BillingComponent.CPU: 300_000,
        BillingComponent.DISK: 200_000,
    }
    basis = (
        BillingAllocationBasis.STORAGE_OWNER
        if component is BillingComponent.DISK
        else BillingAllocationBasis.MEASURED_OVERLAP
    )
    return RunpodBillingAllocation(
        allocation_id=uid(f"runpod-allocation-{component.value.lower()}"),
        bucket_identity_sha256=runpod_billing_bucket_observation().bucket_identity_sha256,
        bucket_observation_id=uid("runpod-billing-bucket-r1"),
        bucket_revision=1,
        component=component,
        owner_kind="EPISODE",
        owner_id=EP1_ID,
        allocation_basis=basis,
        delta_micro_usd=amounts[component],
        allocated_at=T0 + timedelta(hours=2),
    )


def runpod_billing_recovery_allocation() -> RunpodBillingAllocation:
    return RunpodBillingAllocation(
        allocation_id=uid("runpod-allocation-recovery-gpu"),
        bucket_identity_sha256=runpod_billing_bucket_observation().bucket_identity_sha256,
        bucket_observation_id=uid("runpod-billing-bucket-r1"),
        bucket_revision=1,
        component=BillingComponent.GPU,
        owner_kind="RECOVERY",
        owner_id="recovery_pool",
        allocation_basis=BillingAllocationBasis.UNCOVERED,
        delta_micro_usd=500_000,
        allocated_at=T0 + timedelta(hours=2),
    )


def billing_invoice_verification() -> BillingInvoiceVerification:
    bucket = runpod_billing_bucket_invoice_verified()
    return BillingInvoiceVerification(
        verification_id=uid("runpod-invoice-verification-1"),
        provider_account_ref=bucket.provider_account_ref,
        bucket_identity_sha256=bucket.bucket_identity_sha256,
        bucket_observation_id=bucket.observation_id,
        bucket_revision=bucket.revision,
        evidence_source="CONSOLE",
        evidence_sha256=h("runpod-invoice-evidence"),
        evidence_observed_at=T0 + timedelta(days=1),
        verified_at=T0 + timedelta(days=1, minutes=5),
        currency="USD",
        amount_micro_usd=bucket.total_amount_micro_usd,
        result=BillingVerificationResult.MATCHED,
    )


def usage_receipt() -> UsageReceipt:
    return UsageReceipt(
        receipt_id=uid("receipt-1"),
        provider="fake-runpod",
        provider_receipt_id="fake-usage-0001",
        kind=ReceiptKind.SETTLEMENT,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=uid("reservation-1"),
        episode_id=EP1_ID,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=97_500,
        units=390,
        unit=PriceUnit.GPU_SECOND,
        interval_start=T0,
        interval_end=T0 + timedelta(seconds=390),
        observed_at=T0 + timedelta(seconds=400),
        provenance=FAKE,
    )


def pod_lease() -> PodLease:
    return PodLease(
        lease_id=uid("lease-1"),
        provider="fake-runpod",
        pod_id="fake-pod-0001",
        owned_tag="microdrama-owned:env-test",
        client_token="lease-1-create",
        owner_episode_id=EP1_ID,
        owner_job_id=uid("job-render-sh1"),
        reservation_id=uid("reservation-1"),
        lease_state=LeaseState.ACTIVE,
        pod_state=PodState.RUNNING,
        gpu_type="FAKE-GPU-24GB",
        hourly_price_micro_usd=900_000,
        heartbeat_at=T0 + timedelta(minutes=5),
        lease_expires_at=T0 + timedelta(minutes=20),
        accrued_until=T0 + timedelta(minutes=5),
        created_at=T0,
    )


def render_request() -> RenderRequest:
    return RenderRequest(
        render_id=uid("render-sh1-a1"),
        semantic_key="render.shot:ep1:sh1:attempt1",
        episode_id=EP1_ID,
        episode_number=1,
        shot_id="sh1",
        manifest_version=1,
        attempt_number=1,
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        required_controls=[ControlKind.CHARACTER_REFERENCE, ControlKind.FIRST_FRAME],
        reference_asset_ids=[uid("ref-fon-face")],
        audio_asset_id=uid("audio-s1-l1"),
        workflow_sha256=h("workflow"),
        seed=1234,
        width=720,
        height=1280,
        fps=24,
        duration_ms=4_000,
        reservation_id=uid("reservation-1"),
        prompt_text="Medium close-up of Fon reading a ledger at a street food stall at dusk.",
    )


def render_request_v2_prompt_bound() -> RenderRequest:
    payload = render_request().model_dump(mode="python")
    payload.update(
        prompt_manifest_id=uid("prompt-manifest-v2"),
        prompt_manifest_sha256=h("prompt-manifest-v2"),
        semantic_workflow_sha256=h("semantic-workflow-v2"),
    )
    return RenderRequest.model_validate(payload)


def provider_operation() -> ProviderOperation:
    return ProviderOperation(
        operation_id=uid("op-1"),
        provider="fake-comfy",
        operation_kind="comfy.queue_prompt",
        client_token="render-sh1-a1",
        request_sha256=canonical_hash(render_request()),
        job_id=uid("job-render-sh1"),
        reservation_id=uid("reservation-1"),
        state=ProviderOperationState.SUBMITTED,
        external_id="fake-prompt-0001",
        submitted_at=T0,
        deadline_at=T0 + timedelta(minutes=10),
    )


def provider_operation_result() -> ProviderOperationResult:
    return ProviderOperationResult(
        operation_id=uid("op-1"),
        state=ProviderOperationState.SUCCEEDED,
        external_id="fake-prompt-0001",
        outputs=[
            OutputRef(
                name="sh1_00001.mp4",
                media_type="video/mp4",
                provider_ref="output/sh1_00001.mp4",
                complete=True,
            )
        ],
        usage=[usage_receipt()],
        provenance=FAKE,
    )


def media_info(duration_ms: int = 4_000) -> MediaInfo:
    return MediaInfo(
        duration_ms=duration_ms,
        has_video=True,
        has_audio=True,
        width=720,
        height=1280,
        fps_num=24,
        fps_den=1,
        video_codec="h264",
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
    )


def asset_descriptor() -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=uid("asset-sh1-a1"),
        asset_kind=AssetKind.VIDEO,
        object_key="episodes/ep1/shots/sh1/attempt1.mp4",
        sha256=h("asset-sh1-a1"),
        size_bytes=1_234_567,
        media_type="video/mp4",
        media=media_info(),
        state=AssetState.ACCEPTED,
        provenance=FAKE,
        episode_id=EP1_ID,
        lineage=[uid("ref-fon-face")],
        created_at=T0,
    )


def edit_decision_list() -> EditDecisionList:
    return EditDecisionList(
        edl_id=uid("edl-ep1-master"),
        episode_id=EP1_ID,
        version=1,
        purpose=SlotKind.FULL_EPISODE,
        output=OutputFormat(width=720, height=1280, fps_num=24),
        clips=[
            EdlClip(
                clip_id="v1",
                track=TrackKind.VIDEO,
                source_asset_id=uid("asset-sh1-a1"),
                source_in_ms=0,
                source_out_ms=4_000,
                timeline_in_ms=0,
                dialogue_line_ids=["s1-l1"],
            ),
            EdlClip(
                clip_id="v2",
                track=TrackKind.VIDEO,
                source_asset_id=uid("asset-sh2-a1"),
                source_in_ms=0,
                source_out_ms=3_000,
                timeline_in_ms=4_000,
            ),
            EdlClip(
                clip_id="d1",
                track=TrackKind.DIALOGUE,
                source_asset_id=uid("audio-s1-l1"),
                source_in_ms=0,
                source_out_ms=3_200,
                timeline_in_ms=400,
                dialogue_line_ids=["s1-l1"],
            ),
            EdlClip(
                clip_id="a1",
                track=TrackKind.AMBIENCE,
                source_asset_id=uid("ambience-stall"),
                source_in_ms=0,
                source_out_ms=7_000,
                timeline_in_ms=0,
                gain_millibel=-1800,
            ),
        ],
        caption_track_ids=[uid("captions-th"), uid("captions-en")],
    )


def caption_track() -> CaptionTrack:
    return CaptionTrack(
        track_id=uid("captions-en"),
        episode_id=EP1_ID,
        version=1,
        locale="en-US",
        timing_source=CaptionTimingSource.ACTUAL_AUDIO_ALIGNMENT,
        derived_from_audio_sha256=[h("audio-s1-l1")],
        cues=[
            CaptionCue(
                cue_id="c1",
                start_ms=400,
                end_ms=3_600,
                text="Uncle Lek, what is this fifty-thousand-baht debt?",
                line_id="s1-l1",
            ),
            CaptionCue(
                cue_id="c2",
                start_ms=3_700,
                end_ms=6_300,
                text="Your mother didn't want you to know.",
                line_id="s1-l2",
            ),
        ],
    )


def hook_experiment() -> HookExperiment:
    return HookExperiment(
        experiment_id=uid("hooks-ep1"),
        episode_id=EP1_ID,
        candidates=[
            HookCandidate(
                candidate_id="hook-a",
                edl_id=uid("edl-hook-a"),
                duration_ms=25_000,
                source_asset_ids=[uid("asset-sh1-a1")],
                treatment="cold open on ledger",
                changed_framing=False,
                reading_load_note="one subtitle line per cue",
            ),
            HookCandidate(
                candidate_id="hook-b",
                edl_id=uid("edl-hook-b"),
                duration_ms=32_000,
                source_asset_ids=[uid("asset-sh2-a1")],
                treatment="collector arrival first",
                changed_framing=True,
                reading_load_note="crop to 9:16 center",
            ),
            HookCandidate(
                candidate_id="hook-c",
                edl_id=uid("edl-hook-c"),
                duration_ms=38_000,
                source_asset_ids=[uid("asset-sh1-a1"), uid("asset-sh2-a1")],
                treatment="question caption over reaction",
                changed_framing=False,
                reading_load_note="adds title card",
            ),
        ],
    )


def observation_request() -> ObservationRequest:
    return ObservationRequest(
        request_id=uid("obs-req-ep1"),
        episode_id=EP1_ID,
        media=[
            MediaUnderReview(
                asset_id=uid("master-ep1"), asset_sha256=h("master-ep1"), duration_ms=240_000
            )
        ],
        questions=[
            NeutralQuestion(
                question_id="q-speakers",
                text="Who is speaking in each interval, and what do they say?",
            ),
            NeutralQuestion(
                question_id="q-amounts",
                text="List any numbers or amounts that are spoken or shown on screen.",
            ),
        ],
        asr_vocabulary=["ฝน", "ลุงเล็ก"],
    )


def observation_report() -> ObservationReport:
    return ObservationReport(
        report_id=uid("obs-report-ep1"),
        request_id=uid("obs-req-ep1"),
        request_sha256=canonical_hash(observation_request()),
        episode_id=EP1_ID,
        media_sha256=[h("master-ep1")],
        transcript=[
            TranscriptSegment(
                start_ms=400,
                end_ms=3_600,
                text="ลุงเล็ก หนี้ห้าหมื่นบาทนี่คืออะไรคะ",
                speaker_label="speaker_1",
                confidence_bp=8_200,
            )
        ],
        observations=[
            Observation(
                observation_id="o1",
                question_id="q-amounts",
                asset_id=uid("master-ep1"),
                start_ms=400,
                end_ms=3_600,
                description="A woman says an amount: ห้าหมื่นบาท.",
                confidence_bp=7_000,
            )
        ],
        coverage=[
            CoverageWindow(
                asset_id=uid("master-ep1"),
                check_family=CheckFamily.ASR,
                start_ms=0,
                end_ms=240_000,
                status=CoverageStatus.CHECKED,
            ),
            CoverageWindow(
                asset_id=uid("master-ep1"),
                check_family=CheckFamily.TEMPORAL,
                start_ms=0,
                end_ms=240_000,
                status=CoverageStatus.UNAVAILABLE,
                note="no lip-sync detector configured",
            ),
        ],
        model_config_ref="fake-observer-v1",
        provenance=FAKE,
        frozen_at=T0,
    )


def comparison_request() -> ComparisonRequest:
    return ComparisonRequest(
        request_id=uid("cmp-req-ep1"),
        episode_id=EP1_ID,
        observation_report_id=uid("obs-report-ep1"),
        observation_report_sha256=canonical_hash(observation_report()),
        script_id=uid("script-ep1"),
        script_version=1,
        script_sha256=canonical_hash(script()),
        canon_version=1,
        canon_sha256=h("canon-v1"),
        acceptance_criteria=["amounts spoken match script", "speakers match script"],
    )


def qa_finding() -> QAFinding:
    return QAFinding(
        finding_id=uid("finding-1"),
        episode_id=EP1_ID,
        asset_id=uid("captions-en"),
        start_ms=400,
        end_ms=3_600,
        check_id="caption.critical_term_match",
        check_family=CheckFamily.CAPTION,
        source_pass=QAPass.PASS_B_COMPARISON,
        expected="50,000 baht",
        observed="5,000 baht",
        evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="obs-report-ep1#o1")],
        severity=Severity.CRITICAL,
        confidence_bp=9_000,
        coverage=CoverageStatus.CHECKED,
        outcome=QAOutcome.REPAIRABLE,
        repair_targets=[RepairTarget.CAPTION],
        provenance=FAKE,
    )


def repair_plan() -> RepairPlan:
    return RepairPlan(
        plan_id=uid("repair-1"),
        episode_id=EP1_ID,
        trigger=RepairTrigger.QA_FINDING,
        finding_ids=[uid("finding-1")],
        round_number=1,
        steps=[
            RepairStep(
                step_id="r1",
                target=RepairTarget.CAPTION,
                target_ids=["c1"],
                action="retime and retranslate cue c1 from actual audio",
                category=BudgetCategory.QA_CAPTIONS,
                estimated_cost_micro_usd=20_000,
                invalidates_asset_ids=[uid("captions-en")],
                recheck_check_ids=["caption.critical_term_match"],
            )
        ],
        total_estimated_micro_usd=20_000,
        remaining_budget_micro_usd=4_200_000,
        created_at=T0,
    )


def slot_key(
    platform: Platform = Platform.YOUTUBE, account: str = ACCOUNT_YT, slot: str = "full"
) -> ReleaseSlotKey:
    return ReleaseSlotKey(
        series_id=SEASON_ID,
        episode_id=EP1_ID,
        part=0,
        locale="th-TH",
        platform=platform,
        account_ref=account,
        release_slot=slot,
    )


def schedule() -> ScheduleInstant:
    return ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 27, 19, 30))


def release_slot_plan() -> ReleaseSlotPlan:
    return ReleaseSlotPlan(
        slot=slot_key(),
        slot_kind=SlotKind.FULL_EPISODE,
        required=True,
        asset_id=uid("master-ep1"),
        asset_sha256=h("master-ep1"),
        schedule=schedule(),
        disclosures=[DisclosureKind.AI_GENERATED_CONTENT, DisclosureKind.SYNTHETIC_VOICE],
        capability_id=uid("cap-youtube"),
        capability_version=1,
    )


def release_package() -> ReleasePackage:
    draft = dict(
        package_id=uid("package-ep1-v1"),
        episode_id=EP1_ID,
        season_id=SEASON_ID,
        episode_number=1,
        version=1,
        media=[
            MediaRef(asset_id=uid("master-ep1"), sha256=h("master-ep1"), role="master"),
            MediaRef(
                asset_id=uid("contact-sheet"), sha256=h("contact-sheet"), role="contact_sheet"
            ),
        ],
        caption_track_ids=[uid("captions-th"), uid("captions-en")],
        hook_experiment_id=uid("hooks-ep1"),
        cast_package_asset_ids=[uid("contact-sheet"), uid("voice-fon-anchor")],
        release_scope=[release_slot_plan()],
        management_policy_hash=canonical_hash(management_policy()),
        qa=QASummary(
            finding_count=0, unknown_coverage_check_ids=["temporal.lip_sync"], provenance=FAKE
        ),
        cost=CostSummary(
            episode_cap_micro_usd=10_000_000,
            settled_micro_usd=4_100_000,
            accrued_micro_usd=0,
            reserved_outstanding_micro_usd=0,
            remaining_micro_usd=5_900_000,
            synthetic_fake_micro_usd=4_100_000,
        ),
    )
    return ReleasePackage.seal(**draft)


def _creative_safe_zone(platform: Platform, *, poster: bool) -> PlatformSafeZone:
    return PlatformSafeZone(
        platform=platform,
        top_bp=600,
        right_bp=500,
        bottom_bp=1200,
        left_bp=500,
        title_box=(
            SafeZoneTextBox(x_bp=700, y_bp=1500, width_bp=5600, height_bp=900) if poster else None
        ),
        cta_box=SafeZoneTextBox(x_bp=700, y_bp=7400, width_bp=5600, height_bp=900),
    )


def creative_derivative_ref() -> CreativeDerivativeRef:
    source_id = uid("master-ep1")
    return CreativeDerivativeRef(
        derivative_type="EPISODE_ONE_PREVIEW",
        asset_id=uid("episode-one-preview"),
        asset_version=1,
        asset_sha256=h("episode-one-preview"),
        derivation_manifest_sha256=h("preview-derivation-plan"),
        approved_reveal_episode=1,
        sources=[
            DerivativeSourceRef(
                role="FOOTAGE",
                asset_id=source_id,
                asset_version=1,
                asset_sha256=h("master-ep1"),
                source_in_ms=30_000,
                source_out_ms=35_000,
                rights=v2_rights(),
            ),
            DerivativeSourceRef(
                role="AUDIO",
                asset_id=uid("dialogue-audio-ep1"),
                asset_version=1,
                asset_sha256=h("dialogue-audio-ep1"),
                source_in_ms=0,
                source_out_ms=5_000,
                rights=v2_rights(),
            ),
        ],
        duration_ms=5_000,
        reveal_boundary_ms=40_000,
        platform_safe_zones=[_creative_safe_zone(Platform.TIKTOK, poster=False)],
        cta_text="Watch the full episode",
        no_release_obligation=True,
    )


def creative_poster_ref() -> CreativeDerivativeRef:
    return CreativeDerivativeRef(
        derivative_type="POSTER",
        asset_id=uid("poster-ep1"),
        asset_version=1,
        asset_sha256=h("poster-ep1"),
        derivation_manifest_sha256=h("poster-derivation-plan"),
        approved_reveal_episode=1,
        readability_evidence_sha256=h("poster-readability-evidence"),
        sources=[
            DerivativeSourceRef(
                role="CHARACTER",
                asset_id=uid("contact-sheet"),
                asset_version=1,
                asset_sha256=h("contact-sheet"),
                rights=v2_rights(),
            )
        ],
        platform_safe_zones=[
            _creative_safe_zone(Platform.TIKTOK, poster=True),
            _creative_safe_zone(Platform.YOUTUBE, poster=True),
        ],
        title_text="Mother's Stall",
        cta_text="Watch episode one",
        no_release_obligation=True,
    )


def release_package_with_derivatives() -> ReleasePackage:
    base = release_package()
    poster = creative_poster_ref()
    preview = creative_derivative_ref()
    values = {name: getattr(base, name) for name in ReleasePackage.model_fields}
    values["media"] = [
        *base.media,
        MediaRef(
            asset_id=uid("dialogue-audio-ep1"),
            sha256=h("dialogue-audio-ep1"),
            role="dialogue_audio",
        ),
    ]
    values["creative_derivatives"] = [poster, preview]
    return ReleasePackage.seal(**values)


def publication_command() -> PublicationCommand:
    pkg = release_package()
    return PublicationCommand(
        command_id=uid("pub-cmd-1"),
        release_package_id=pkg.package_id,
        release_package_hash=pkg.package_hash,
        approval_event_id=uid("approval-ep1"),
        slot=slot_key(),
        slot_kind=SlotKind.FULL_EPISODE,
        asset_id=uid("master-ep1"),
        asset_sha256=h("master-ep1"),
        metadata=PostMetadata(
            locale="th-TH",
            title="หนี้ที่ไม่มีใครบอก | EP1",
            description="Original AI-assisted Thai micro-drama.",
            hashtags=["#ละครสั้น"],
            links=["https://example.invalid/episode/1"],
            disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            catalog_version=1,
        ),
        metadata_version_id=uid("metadata-v1"),
        schedule=schedule(),
        capability_id=uid("cap-youtube"),
        capability_version=1,
        client_token="pub-ep1-youtube-full",
    )


def publication_command_v2_no_cover_no_cta() -> PublicationCommand:
    manifest = v2_owner_approved_release_approval_manifest()
    slot = manifest.slots[0]
    slot_values = slot.model_dump(mode="python")
    slot_values.update(
        cover_asset_id=None,
        cover_asset_version=None,
        cover_asset_sha256=None,
        cover_rights=None,
        cta_text=None,
    )
    slot = ApprovedSlotMetadata.seal(**slot_values)
    manifest_values = manifest.model_dump(mode="python")
    manifest_values["slots"] = [slot]
    manifest = ReleaseApprovalManifest.seal(**manifest_values)

    command_values = publication_command().model_dump(mode="python")
    command_values.update(
        release_package_id=manifest.release_package_id,
        release_package_hash=manifest.release_package_hash,
        metadata_version_id=slot.metadata_id,
        release_manifest_id=manifest.manifest_id,
        release_manifest_version=manifest.version,
        release_manifest_sha256=manifest.approval_manifest_sha256,
        approved_metadata_version=slot.metadata_version,
        approved_metadata_sha256=slot.content_sha256,
        metadata_policy_id=manifest.metadata_policy.policy_id,
        metadata_policy_version=manifest.metadata_policy.version,
        metadata_policy_sha256=manifest.metadata_policy.policy_sha256,
        metadata=PostMetadata(
            locale=slot.locale,
            title=slot.title,
            caption=slot.caption,
            description=slot.description,
            hashtags=slot.hashtags,
            links=slot.links,
            disclosures=slot.disclosures,
            catalog_version=slot.catalog_version,
            cover_asset_id=None,
            cover_asset_version=None,
            cover_asset_sha256=None,
            cta_text=None,
        ),
    )
    return PublicationCommand.model_validate(command_values)


def episode_review_view() -> EpisodeReviewView:
    return EpisodeReviewView(
        episode_id=EP1_ID,
        episode_number=1,
        state=EpisodeState.AWAITING_FINAL_REVIEW,
        revision=7,
        gate_enabled=True,
        release_approval_manifest=v2_release_approval_manifest(),
    )


def capability_record() -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=uid("cap-youtube"),
        version=1,
        platform=Platform.YOUTUBE,
        provider_route="fake-youtube-data-api",
        account_ref=ACCOUNT_YT,
        account_type="channel",
        operations={
            CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_TESTED,
            CapabilityOperation.SCHEDULE: CapabilitySupport.SUPPORTED_TESTED,
            CapabilityOperation.AI_DISCLOSURE: CapabilitySupport.SUPPORTED_TESTED,
            CapabilityOperation.DM_SEND: CapabilitySupport.UNSUPPORTED,
        },
        supported_disclosures=[DisclosureKind.AI_GENERATED_CONTENT, DisclosureKind.SYNTHETIC_VOICE],
        evidence=[
            EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:fake-youtube-capability")
        ],
        verified_at=T0,
        enabled=True,
    )


def management_action() -> ManagementAction:
    return ManagementAction(
        action_id=uid("action-1"),
        kind=ManagementActionKind.PUBLIC_REPLY,
        platform=Platform.TIKTOK,
        account_ref=ACCOUNT_TT,
        platform_post_id=uid("post-tt-1"),
        target_external_id="fake-comment-0001",
        community_event_id=uid("community-event-1"),
        content="ตอนที่ 2 มาวันศุกร์นี้ 19:30 น. ค่ะ",
        catalog_version=1,
        management_policy_hash=canonical_hash(management_policy()),
        dedupe_key="reply:fake-comment-0001",
    )


def membership_catalog_entry() -> MembershipCatalogEntry:
    return MembershipCatalogEntry(
        entry_id=uid("catalog-ep2"),
        season_id=SEASON_ID,
        episode_id=EP2_ID,
        episode_number=2,
        catalog_version=1,
        public_state=CatalogPublicState.EARLY_ACCESS_MEMBERS,
        media_finished_and_approved=True,
        approval_event_id=uid("approval-ep2"),
        member_provider=MembershipProviderKind.PATREON,
        member_post_id="fake-member-post-2",
        member_price=MemberPrice(amount_micro_usd=3_000_000),
        free_release=ScheduleInstant.from_local("Asia/Bangkok", datetime(2026, 10, 31, 19, 30)),
        member_url="https://members.fake.invalid/posts/2",
        provenance=FAKE,
    )


def metric_snapshot() -> MetricSnapshot:
    return MetricSnapshot(
        snapshot_id=uid("snapshot-1"),
        platform=Platform.TIKTOK,
        account_ref=ACCOUNT_TT,
        platform_post_id=uid("post-tt-1"),
        external_post_id="fake-video-0001",
        episode_id=EP1_ID,
        window=SnapshotWindow.H24,
        observed_at=T0 + timedelta(hours=24),
        definitions_version="fake-tiktok-metrics-v1",
        metrics={
            "views": MetricValue(value=1200, definition="fake.video_views"),
            "avg_watch_ms": MetricValue(value=None, definition="fake.average_watch_time"),
        },
        traffic=TrafficKind.ORGANIC,
        provenance=FAKE,
    )


def qualification_result() -> QualificationResult:
    return QualificationResult(
        run_id=uid("qualification-1"),
        season_id=SEASON_ID,
        evaluated_at=T0 + timedelta(days=8),
        consecutive_qualifying_production=1,
        production_status=QualificationStatus.NOT_QUALIFIED,
        management_status=QualificationStatus.PENDING,
        episodes=[
            EpisodeQualification(
                episode_id=EP1_ID,
                episode_number=1,
                production_qualifies=True,
                management_window_status=QualificationStatus.PENDING,
                management_window_ends_at=T0 + timedelta(days=14),
                variable_cost_micro_usd=4_100_000,
            )
        ],
        total_variable_spend_micro_usd=4_100_000,
        successful_episodes=1,
        effective_cost_per_successful_episode_micro_usd=4_100_000,
        provenance=FAKE,
    )


def domain_event() -> DomainEvent:
    return DomainEvent(
        event_id=uid("event-1"),
        event_type="episode.state_changed",
        aggregate_type="episode",
        aggregate_id=EP1_ID,
        sequence=4,
        correlation_id=uid("correlation-ep1"),
        causation_id=uid("event-0"),
        occurred_at=T0,
        payload={"from": "ASSEMBLING", "to": "AI_REVIEW"},
    )


def rights_record() -> RightsRecord:
    return RightsRecord(
        record_id=uid("rights-voice-fake"),
        rights_route_id="fake-voice-route",
        version=1,
        subject_kind=RightsSubjectKind.VOICE,
        subject_ref="fake-thai-voice-v1",
        territories=["TH", "US"],
        commercial_use=True,
        output_release_allowed=True,
        required_disclosures=[DisclosureKind.SYNTHETIC_VOICE],
        expires_at=T0 + timedelta(days=365),
        evidence=[
            EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:fake-voice-license")
        ],
        status=RightsStatus.ELIGIBLE,
        recorded_at=T0,
    )


def preset_record() -> PresetRecord:
    return PresetRecord(
        preset_id="fake-quality-8step",
        version=1,
        tier=RenderTier.QUALITY_EIGHT_STEP,
        workflow_sha256=h("workflow"),
        model_mode="image_to_video",
        gpu_type="FAKE-GPU-24GB",
        min_vram_gb=24,
        host_ram_gb=64,
        precision="bf16",
        width=720,
        height=1280,
        frames=97,
        fps=24,
        steps=8,
        attention_backend="sdpa",
        supported_controls=[
            ControlKind.TEXT_PROMPT,
            ControlKind.FIRST_FRAME,
            ControlKind.CHARACTER_REFERENCE,
        ],
        supports_thai_dialogue=None,
        rights_route_id="fake-video-route",
        measured=PresetMeasurements(
            sample_count=12,
            cold_start_ms=180_000,
            warm_full_job_ms=95_000,
            cost_per_accepted_shot_micro_usd=120_000,
            cost_per_retained_second_micro_usd=30_000,
            acceptance_bp_by_shot_class={"dialogue_two_speaker": 6_500, "insert": 9_000},
            critical_quality_pass_bp=7_000,
            measured_with_references=True,
            measured_at=T0,
        ),
        evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:fake-benchmark")],
        enabled=True,
    )


VALID_BUILDERS: dict[str, Callable[[], BaseModel]] = {
    "SeasonScope": season_scope,
    "ApprovalCommand": approval_gate1,
    "EpisodePlan": episode_plan,
    "Script": script,
    "ShotManifest": shot_manifest,
    "IdentityLock": identity_lock,
    "BudgetReservationRequest": budget_reservation_request,
    "UsageReceipt": usage_receipt,
    "RunpodBillingQueryObservation": runpod_billing_query_observation,
    "RunpodBillingBucketObservation": runpod_billing_bucket_observation,
    "RunpodBillingAllocation": runpod_billing_allocation,
    "BillingInvoiceVerification": billing_invoice_verification,
    "PodLease": pod_lease,
    "RenderRequest": render_request,
    "ProviderOperation": provider_operation,
    "ProviderOperationResult": provider_operation_result,
    "AssetDescriptor": asset_descriptor,
    "EditDecisionList": edit_decision_list,
    "CaptionTrack": caption_track,
    "HookExperiment": hook_experiment,
    "ObservationRequest": observation_request,
    "ObservationReport": observation_report,
    "ComparisonRequest": comparison_request,
    "QAFinding": qa_finding,
    "RepairPlan": repair_plan,
    "ReleasePackage": release_package,
    "PublicationCommand": publication_command,
    "CapabilityRecord": capability_record,
    "ManagementAction": management_action,
    "MembershipCatalogEntry": membership_catalog_entry,
    "MetricSnapshot": metric_snapshot,
    "QualificationResult": qualification_result,
    "DomainEvent": domain_event,
}

EXTRA_VALID: dict[str, Callable[[], BaseModel]] = {
    "ApprovalCommand__gate2_revise": approval_gate2_revise,
    "RightsRecord": rights_record,
    "PresetRecord": preset_record,
    "ConceptCandidate__pending_rights": v2_concept_candidate_pending_rights,
    "EpisodeReviewView": episode_review_view,
    "PublicationCommand__v2_no_cover_no_cta": publication_command_v2_no_cover_no_cta,
    "CreativeDerivativeRef": creative_derivative_ref,
    "CreativeDerivativeRef__poster": creative_poster_ref,
    "DirectingShot": v2_directing_shot,
    "DirectingSection": v2_directing_section,
    "ReleasePackage__creative_derivatives": release_package_with_derivatives,
    "RunpodBillingQueryObservation__empty": runpod_billing_query_empty,
    "RunpodBillingQueryObservation__unknown": runpod_billing_query_unknown,
    "RunpodBillingBucketObservation__invoice_verified": runpod_billing_bucket_invoice_verified,
    "RunpodBillingBucketObservation__disputed": runpod_billing_bucket_disputed,
    "RunpodBillingAllocation__cpu": lambda: runpod_billing_allocation(BillingComponent.CPU),
    "RunpodBillingAllocation__disk": lambda: runpod_billing_allocation(BillingComponent.DISK),
    "RunpodBillingAllocation__recovery": runpod_billing_recovery_allocation,
    "RenderRequest__v2_prompt_manifest_bound": render_request_v2_prompt_bound,
}


# --- invalid cases ------------------------------------------------------------------------------


def _json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _mutate(base: Callable[[], BaseModel], fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    data = copy.deepcopy(_json(base()))
    fn(data)
    return data


def _set(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def apply(data: dict[str, Any]) -> None:
        node: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        last = parts[-1]
        if last.isdigit():
            node[int(last)] = value
        else:
            node[last] = value

    return apply


def _del(path: str) -> Callable[[dict[str, Any]], None]:
    def apply(data: dict[str, Any]) -> None:
        node: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        del node[parts[-1]]

    return apply


def _many(*fns: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def apply(data: dict[str, Any]) -> None:
        for fn in fns:
            fn(data)

    return apply


def _resealed_without_cast_package() -> dict[str, Any]:
    """Episode-one package with a *correct* hash but no cast package (isolates IMP-01)."""
    pkg = release_package()
    unsealed = ReleasePackage.model_construct(**{**pkg.__dict__, "cast_package_asset_ids": []})
    data = _json(pkg)
    data["cast_package_asset_ids"] = []
    data["package_hash"] = unsealed.compute_hash()
    return data


def invalid_cases() -> list[tuple[str, str, str, dict[str, Any]]]:
    """(model_name, case_id, reason, payload) tuples that MUST fail validation."""
    m = _mutate

    def invalid_pack(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        base = v2_episode_pack()
        payload = _json(base)
        change(payload)
        scenes = [EpisodeScene.model_validate(scene) for scene in payload["scenes"]]
        mutated = base.model_copy(update={"scenes": scenes})
        mutated = mutated.model_copy(update={"content_sha256": mutated.calculated_content_sha256()})
        return mutated.model_dump(mode="json")

    def invalid_derivative_package_reveal() -> dict[str, Any]:
        package = release_package_with_derivatives()
        poster = package.creative_derivatives[0].model_copy(update={"approved_reveal_episode": 2})
        mutated = package.model_copy(
            update={"creative_derivatives": [poster, package.creative_derivatives[1]]}
        )
        payload = mutated.model_dump(mode="json")
        payload["package_hash"] = mutated.compute_hash()
        return payload

    def cyclic_beats(payload: dict[str, Any]) -> None:
        first = payload["scenes"][0]["beats"][0]
        first["dependency_beat_ids"] = ["beat-2"]
        second = copy.deepcopy(first)
        second["beat_id"] = "beat-2"
        second["dependency_beat_ids"] = ["beat-1"]
        payload["scenes"][0]["beats"].append(second)

    def cyclic_scenes(payload: dict[str, Any]) -> None:
        first = payload["scenes"][0]
        first["dependency_scene_ids"] = ["scene-2"]
        second = copy.deepcopy(first)
        second["scene_id"] = "scene-2"
        second["scene_number"] = 2
        second["dependency_scene_ids"] = ["scene-1"]
        second["beats"][0]["beat_id"] = "beat-2"
        second["dependency_scene_ids"] = ["scene-1"]
        payload["scenes"].append(second)

    gate2_approve_no_media = _json(approval_gate1())
    gate2_approve_no_media.update(gate="EPISODE_FINAL", entity_id=str(EP1_ID))
    cases: list[tuple[str, str, str, dict[str, Any]]] = [
        (
            "SeasonScope",
            "episode_too_long",
            "MD-002 max 300 s",
            m(season_scope, _set("episode_max_duration_ms", 400_000)),
        ),
        (
            "SeasonScope",
            "unknown_field",
            "closed schema rejects unknown fields",
            m(season_scope, _set("surprise", 1)),
        ),
        (
            "SeasonScope",
            "stale_schema_version",
            "unsupported schema version",
            m(season_scope, _set("schema_version", "0.9")),
        ),
        (
            "SeasonScope",
            "cap_above_ten_dollars",
            "cap > US$10",
            m(season_scope, _set("cost_policy.episode_cap_micro_usd", 12_000_000)),
        ),
        (
            "SeasonScope",
            "paid_ads",
            "MD-018 paid ads zero",
            m(season_scope, _set("cost_policy.paid_advertising_budget_micro_usd", 1)),
        ),
        (
            "ApprovalCommand",
            "gate1_revise",
            "Gate 1 has no Revise",
            m(
                approval_gate1,
                _many(
                    _set("action", "REVISE"),
                    _set(
                        "feedback",
                        [{"category": "pacing", "start_ms": 0, "end_ms": 1, "comment": "x"}],
                    ),
                ),
            ),
        ),
        (
            "ApprovalCommand",
            "gate2_approve_without_media",
            "Gate 2 approval must bind media hashes",
            gate2_approve_no_media,
        ),
        (
            "ApprovalCommand",
            "float_revision",
            "integers only",
            m(approval_gate1, _set("expected_revision", 3.0)),
        ),
        (
            "ApprovalCommand",
            "series_feedback_without_explicit_scope",
            "no inferred globalization",
            m(approval_gate2_revise, _set("feedback.0.scope", "SERIES")),
        ),
        (
            "EpisodePlan",
            "four_featured_speakers",
            "max three featured speaking characters",
            m(episode_plan, _set("featured_character_ids", ["a", "b", "c", "d"])),
        ),
        (
            "Script",
            "duplicate_line_id",
            "line ids unique",
            m(script, _set("scenes.1.lines.0.line_id", "s1-l1")),
        ),
        (
            "ShotManifest",
            "later_episode_without_lock",
            "IMP-01 identity lock required",
            m(shot_manifest, _set("episode_number", 2)),
        ),
        (
            "ShotManifest",
            "unknown_control",
            "unknown controls cannot be silently discarded",
            m(
                shot_manifest,
                _set("shots.0.required_identity_controls", ["CHARACTER_REFERENCE", "TELEPATHY"]),
            ),
        ),
        (
            "ShotManifest",
            "three_speakers_in_shot",
            "max two speakers per shot",
            m(shot_manifest, _many(_set("shots.0.speaker_ids", ["fon", "lek", "nok"]))),
        ),
        (
            "ShotManifest",
            "shot_over_15s",
            "15 s unit",
            m(shot_manifest, _set("shots.0.target_duration_ms", 16_000)),
        ),
        (
            "IdentityLock",
            "empty_lock",
            "lock must include assets",
            m(identity_lock, _set("locked_assets", [])),
        ),
        (
            "BudgetReservationRequest",
            "float_money",
            "money must be integer micro-USD",
            m(budget_reservation_request, _set("worst_case_micro_usd", 150000.5)),
        ),
        (
            "BudgetReservationRequest",
            "under_bounded_exposure",
            "worst case below price x units",
            m(budget_reservation_request, _set("worst_case_micro_usd", 1)),
        ),
        (
            "BudgetReservationRequest",
            "no_timeout",
            "timeout ceiling required",
            m(budget_reservation_request, _del("ceilings.timeout_ms")),
        ),
        (
            "BudgetReservationRequest",
            "gpu_time_beyond_reserved_units",
            "GPU-second exposure is bounded by the timeout, not by max_units alone",
            m(
                budget_reservation_request,
                _many(_set("ceilings.max_units", 1), _set("ceilings.timeout_ms", 3_600_000)),
            ),
        ),
        (
            "BudgetReservationRequest",
            "token_price_without_token_ceiling",
            "token pricing needs the matching token ceiling (uncertain exposure)",
            m(budget_reservation_request, _set("price.unit", "OUTPUT_TOKEN_1K")),
        ),
        (
            "BudgetReservationRequest",
            "token_ceiling_beyond_reserved_units",
            "1,000,000 output tokens cannot be held for a 600-unit reservation",
            m(
                budget_reservation_request,
                _many(
                    _set("price.unit", "OUTPUT_TOKEN_1K"),
                    _set("ceilings.max_output_tokens", 1_000_000),
                ),
            ),
        ),
        (
            "BudgetReservationRequest",
            "render_claiming_cleanup",
            "a render cannot draw on the shutdown reserve by flagging itself as cleanup",
            m(budget_reservation_request, _set("is_shutdown_or_cleanup", True)),
        ),
        (
            "BudgetReservationRequest",
            "zero_unit_price",
            "a zero unit price is not a known price",
            m(budget_reservation_request, _set("price.unit_price_micro_usd", 0)),
        ),
        (
            "BudgetReservationRequest",
            "gpu_priced_per_request",
            "GPU generation must be priced per GPU second so the timeout bounds it",
            m(
                budget_reservation_request,
                _many(_set("price.unit", "REQUEST"), _set("ceilings.max_units", 1)),
            ),
        ),
        (
            "BudgetReservationRequest",
            "community_cleanup_flag",
            "only production GPU/recovery/storage cleanup may use the shutdown reserve",
            m(
                budget_reservation_request,
                _many(
                    _set("queue", "community"),
                    _set("category", "METERED_MANAGEMENT"),
                    _set("is_shutdown_or_cleanup", True),
                ),
            ),
        ),
        (
            "UsageReceipt",
            "fake_claims_billed",
            "fake usage cannot claim measured cost",
            m(usage_receipt, _set("cost_basis", "BILLED")),
        ),
        (
            "UsageReceipt",
            "negative_amount",
            "non-negative micro-USD",
            m(usage_receipt, _set("amount_micro_usd", -5)),
        ),
        (
            "PodLease",
            "float_price",
            "integer micro-USD",
            m(pod_lease, _set("hourly_price_micro_usd", 0.9)),
        ),
        (
            "RenderRequest",
            "fourth_attempt",
            "max three paid attempts",
            m(render_request, _set("attempt_number", 4)),
        ),
        (
            "RenderRequest",
            "later_episode_without_lock",
            "IMP-01",
            m(render_request, _set("episode_number", 2)),
        ),
        (
            "RenderRequest",
            "unknown_control",
            "unknown control",
            m(render_request, _set("required_controls", ["TELEPATHY"])),
        ),
        (
            "RunpodBillingQueryObservation",
            "empty_query_with_bucket",
            "EMPTY billing query cannot claim bucket observations",
            m(runpod_billing_query_observation, _set("result_state", "EMPTY")),
        ),
        (
            "RunpodBillingBucketObservation",
            "component_total_mismatch",
            "provider bucket total must equal GPU + CPU + disk",
            m(runpod_billing_bucket_observation, _set("total_amount_micro_usd", 1_000_001)),
        ),
        (
            "RunpodBillingBucketObservation",
            "float_component_amount",
            "billing money is integer micro-USD; floats are rejected",
            m(runpod_billing_bucket_observation, _set("gpu_amount_micro_usd", 500_000.5)),
        ),
        (
            "RunpodBillingAllocation",
            "gpu_with_disk_basis",
            "GPU/CPU allocation must use measured overlap",
            m(runpod_billing_allocation, _set("allocation_basis", "STORAGE_OWNER")),
        ),
        (
            "BillingInvoiceVerification",
            "mismatch_without_reason",
            "mismatched invoice evidence needs an explicit reason",
            m(billing_invoice_verification, _set("result", "MISMATCHED")),
        ),
        (
            "RenderRequest",
            "partial_prompt_manifest_binding",
            "prompt manifest ID and hash must be provided together",
            m(render_request, _set("prompt_manifest_id", str(uid("prompt-manifest")))),
        ),
        (
            "RenderRequest",
            "v2_missing_semantic_workflow_hash",
            "V2 manifest-bound render request needs pinned semantic workflow hash",
            m(
                render_request_v2_prompt_bound,
                _del("semantic_workflow_sha256"),
            ),
        ),
        (
            "RenderRequest",
            "semantic_hash_without_manifest",
            "semantic workflow hash requires a V2 prompt manifest locator",
            m(render_request, _set("semantic_workflow_sha256", h("semantic-workflow-v2"))),
        ),
        (
            "ProviderOperation",
            "missing_client_token",
            "idempotent token required",
            m(provider_operation, _del("client_token")),
        ),
        (
            "ProviderOperationResult",
            "failed_without_error",
            "typed failure",
            m(provider_operation_result, _many(_set("state", "FAILED"), _set("usage", []))),
        ),
        (
            "AssetDescriptor",
            "video_without_media_info",
            "measured media facts required",
            m(asset_descriptor, _set("media", None)),
        ),
        (
            "AssetDescriptor",
            "path_traversal_key",
            "private relative keys only",
            m(asset_descriptor, _set("object_key", "episodes/../../etc/passwd")),
        ),
        (
            "EditDecisionList",
            "overlapping_video",
            "video clips cannot overlap",
            m(edit_decision_list, _set("clips.1.timeline_in_ms", 2_000)),
        ),
        (
            "EditDecisionList",
            "inverted_source_range",
            "out > in",
            m(edit_decision_list, _set("clips.0.source_out_ms", 0)),
        ),
        (
            "CaptionTrack",
            "overlapping_cues",
            "cues ordered, non-overlapping",
            m(caption_track, _set("cues.1.start_ms", 1_000)),
        ),
        (
            "CaptionTrack",
            "actual_timing_without_audio",
            "must name aligned audio",
            m(caption_track, _set("derived_from_audio_sha256", [])),
        ),
        (
            "HookExperiment",
            "two_candidates",
            "exactly three candidates",
            m(hook_experiment, lambda d: d["candidates"].pop()),
        ),
        (
            "HookExperiment",
            "new_render_jobs",
            "no new video renders for hooks",
            m(hook_experiment, _set("new_video_render_job_ids", [str(uid("job-x"))])),
        ),
        (
            "HookExperiment",
            "hook_too_long",
            "20-40 s",
            m(hook_experiment, _set("candidates.0.duration_ms", 45_000)),
        ),
        (
            "ObservationRequest",
            "includes_intended_script",
            "Pass A excludes intended script",
            m(observation_request, _set("intended_script", "ลุงเล็ก หนี้ห้าหมื่นบาท")),
        ),
        (
            "ObservationRequest",
            "includes_expected_dialogue",
            "Pass A excludes expected dialogue",
            m(observation_request, _set("expected_dialogue", ["s1-l1"])),
        ),
        (
            "ObservationReport",
            "no_coverage",
            "coverage must be explicit",
            m(observation_report, _set("coverage", [])),
        ),
        (
            "ComparisonRequest",
            "bad_hash",
            "sha256 hex",
            m(comparison_request, _set("observation_report_sha256", "not-a-hash")),
        ),
        (
            "QAFinding",
            "unsampled_pass",
            "unsampled coverage is UNKNOWN, never PASS",
            m(qa_finding, _many(_set("coverage", "UNSAMPLED"), _set("outcome", "PASS"))),
        ),
        (
            "QAFinding",
            "partial_pass",
            "PASS requires CHECKED",
            m(qa_finding, _many(_set("coverage", "PARTIAL"), _set("outcome", "PASS"))),
        ),
        (
            "RepairPlan",
            "third_qa_round",
            "max two automatic repair rounds",
            m(repair_plan, _set("round_number", 3)),
        ),
        (
            "RepairPlan",
            "over_budget",
            "cannot exceed remaining budget",
            m(repair_plan, _set("remaining_budget_micro_usd", 10_000)),
        ),
        (
            "RepairPlan",
            "shot_rerender_without_attempt",
            "tier promotion consumes ordinary attempt",
            m(repair_plan, _set("steps.0.target", "SHOT")),
        ),
        (
            "ReleasePackage",
            "tampered_hash",
            "package hash must match content",
            m(release_package, _set("media.0.sha256", h("tampered"))),
        ),
        (
            "ReleasePackage",
            "episode1_without_cast_package",
            "IMP-01 cast package",
            _resealed_without_cast_package(),
        ),
        (
            "ReleasePackage",
            "missing_ai_disclosure",
            "MD-015",
            m(release_package, _set("release_scope.0.disclosures", ["SYNTHETIC_VOICE"])),
        ),
        (
            "PublicationCommand",
            "dst_gap_schedule",
            "nonexistent local time",
            m(
                publication_command,
                _set(
                    "schedule",
                    {
                        "iana_zone": "America/New_York",
                        "local_time": "2026-03-08T02:30:00",
                        "fold": None,
                        "utc_instant": "2026-03-08T07:30:00Z",
                    },
                ),
            ),
        ),
        (
            "PublicationCommand",
            "dst_ambiguous_without_fold",
            "ambiguous local time needs fold",
            m(
                publication_command,
                _set(
                    "schedule",
                    {
                        "iana_zone": "America/New_York",
                        "local_time": "2026-11-01T01:30:00",
                        "fold": None,
                        "utc_instant": "2026-11-01T05:30:00Z",
                    },
                ),
            ),
        ),
        (
            "PublicationCommand",
            "utc_mismatch",
            "utc_instant must match zone conversion",
            m(publication_command, _set("schedule.utc_instant", "2026-10-27T19:30:00Z")),
        ),
        (
            "PublicationCommand",
            "partial_v2_manifest_binding",
            "V2 stale-queue binding must include exact manifest, metadata and policy",
            m(publication_command, _set("release_manifest_id", str(uid("manifest-id")))),
        ),
        (
            "PublicationCommand",
            "partial_v2_cover_binding",
            "V2 command cover must be fully bound or explicitly absent",
            m(
                publication_command_v2_no_cover_no_cta,
                _set("metadata.cover_asset_id", str(uid("partial-cover"))),
            ),
        ),
        (
            "EpisodeReviewView",
            "invalid_release_approval_manifest",
            "nested review manifest must validate as V2",
            m(
                episode_review_view,
                _set("release_approval_manifest.schema_version", "1.0"),
            ),
        ),
        (
            "CapabilityRecord",
            "enabled_without_evidence",
            "enabled needs evidence",
            m(capability_record, _set("evidence", [])),
        ),
        (
            "CapabilityRecord",
            "tested_claim_from_documentation",
            "SUPPORTED_TESTED needs a controlled account test, not documentation",
            m(
                capability_record,
                _set("evidence", [{"source": "OFFICIAL_DOCUMENTATION", "ref": "docs:upload-api"}]),
            ),
        ),
        (
            "ManagementAction",
            "reply_without_content",
            "replies need content",
            m(management_action, _set("content", None)),
        ),
        (
            "ManagementAction",
            "suppressed_without_reason",
            "suppression must be explained",
            m(management_action, _set("decision", "SUPPRESSED")),
        ),
        (
            "MembershipCatalogEntry",
            "early_access_unapproved",
            "cannot sell unapproved media",
            m(membership_catalog_entry, _set("media_finished_and_approved", False)),
        ),
        (
            "MembershipCatalogEntry",
            "token_in_link",
            "no secret playback token in links",
            m(
                membership_catalog_entry,
                _set("member_url", "https://members.fake.invalid/posts/2?token=abc"),
            ),
        ),
        (
            "MembershipCatalogEntry",
            "fake_with_real_url",
            "fakes only report .invalid URLs",
            m(membership_catalog_entry, _set("member_url", "https://www.patreon.com/posts/2")),
        ),
        (
            "MetricSnapshot",
            "float_metric",
            "integers or null only",
            m(metric_snapshot, _set("metrics.views.value", 1200.5)),
        ),
        (
            "QualificationResult",
            "qualified_after_one",
            "ten consecutive episodes required",
            m(qualification_result, _set("production_status", "QUALIFIED")),
        ),
        (
            "QualificationResult",
            "required_not_ten",
            "requirement fixed at ten",
            m(qualification_result, _set("required_consecutive", 1)),
        ),
        (
            "DomainEvent",
            "bad_event_type",
            "dotted lowercase type",
            m(domain_event, _set("event_type", "EpisodeChanged")),
        ),
        (
            "DomainEvent",
            "oversized_payload",
            "bounded payload",
            m(domain_event, _set("payload", {"blob": "x" * 20_000})),
        ),
        # contract 1.2.0 (M0 validator findings V-5/6/7/16/17/18/19/21/25)
        (
            "PostReadback",
            "fake_real_link",
            "fake readbacks may only report .invalid links",
            {
                "external_id": "fake-1",
                "links": ["https://www.youtube.com/watch?v=REAL"],
                "provenance": "FAKE_SYNTHETIC",
            },
        ),
        (
            "QualificationResult",
            "management_qualified_without_windows",
            "ten corresponding management windows required",
            m(qualification_result, _set("management_status", "QUALIFIED")),
        ),
        (
            "QualificationResult",
            "streak_not_derived",
            "consecutive count must equal the trailing streak",
            m(qualification_result, _set("consecutive_qualifying_production", 7)),
        ),
        (
            "QualificationResult",
            "manual_fix_counted_in_streak",
            "a manual technical fix resets the streak",
            m(qualification_result, _set("episodes.0.manual_interventions", 1)),
        ),
        (
            "PresetRecord",
            "dialogue_preset_thai_unknown",
            "enabled dialogue presets need measured Thai support",
            m(
                preset_record,
                _set(
                    "supported_controls",
                    ["TEXT_PROMPT", "FIRST_FRAME", "CHARACTER_REFERENCE", "VOICE_REFERENCE"],
                ),
            ),
        ),
        (
            "PresetRecord",
            "zero_quality_enabled",
            "enabled presets need non-zero measured quality",
            m(preset_record, _set("measured.critical_quality_pass_bp", 0)),
        ),
        (
            "PublishResult",
            "verified_without_coverage",
            "verified publication must name verified fields",
            {
                "state": "PUBLISHED_VERIFIED",
                "external_id": "yt-1",
                "verified_fields": [],
                "provenance": "FAKE_SYNTHETIC",
            },
        ),
        (
            "RightsRecord",
            "eligible_already_expired",
            "expired records cannot be ELIGIBLE",
            m(rights_record, _set("expires_at", "2020-01-01T00:00:00Z")),
        ),
        (
            "Principal",
            "model_with_approval_scope",
            "non-human principals cannot hold approval scopes",
            {
                "principal_id": "critic",
                "kind": "RUNTIME_MODEL",
                "runtime_role": "CRITIC",
                "scopes": ["gate2:approve"],
            },
        ),
        (
            "UsageReceipt",
            "fixture_with_billed_cost",
            "measured cost bases only from live providers",
            m(
                usage_receipt,
                _many(_set("provenance", "ORIGINAL_FIXTURE"), _set("cost_basis", "BILLED")),
            ),
        ),
        (
            "MembershipCatalogEntry",
            "token_in_path",
            "no token-like path segments in links",
            m(
                membership_catalog_entry,
                _set(
                    "member_url",
                    "https://members.fake.invalid/watch/abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                ),
            ),
        ),
        (
            "SeasonScope",
            "constraint_above_enforced_limit",
            "scope limits above the enforced hard limits are rejected, not ignored",
            m(season_scope, _set("creative_constraints.max_active_locations_per_episode", 5)),
        ),
        # contract 1.1.0 registry records
        (
            "RightsRecord",
            "unknown_marked_eligible",
            "unknown commercial use cannot be ELIGIBLE",
            m(rights_record, _set("commercial_use", None)),
        ),
        (
            "RightsRecord",
            "eligible_without_evidence",
            "eligibility needs evidence",
            m(rights_record, _set("evidence", [])),
        ),
        (
            "RightsRecord",
            "bad_territory",
            "ISO alpha-2 or WORLDWIDE",
            m(rights_record, _set("territories", ["Thailand"])),
        ),
        (
            "PresetRecord",
            "enabled_unmeasured",
            "presets stay disabled until measured",
            m(preset_record, _set("measured", None)),
        ),
        (
            "PresetRecord",
            "reference_preset_measured_text_only",
            "text-only speed cannot certify reference workflows",
            m(preset_record, _set("measured.measured_with_references", False)),
        ),
        (
            "PresetRecord",
            "enabled_without_rights",
            "enabled preset needs a rights route",
            m(preset_record, _set("rights_route_id", None)),
        ),
    ]
    v2_specific = {
        "ConceptIntake": (
            v2_concept_intake,
            _set("requested_episode_count", 11),
            "episode count is bounded",
        ),
        "ConceptCandidate": (
            v2_concept_candidate,
            _set("rights.status", "UNKNOWN"),
            "rights must be eligible",
        ),
        "CharacterLogic": (
            v2_character_logic,
            _set("schema_version", "1.0"),
            "V1 payload is not V2",
        ),
        "SecretLedger": (v2_secret_ledger, _set("schema_version", "1.0"), "V1 payload is not V2"),
        "SeasonStoryLedger": (
            v2_season_story_ledger,
            _set("payoff_debts.0.status", "UNKNOWN"),
            "payoff debt status is closed",
        ),
        "EpisodePack": (
            v2_episode_pack,
            _set("duration_target_ms", 301_000),
            "episode duration is 180-300 seconds",
        ),
        "DirectingManifest": (
            v2_directing_manifest,
            _set("shots.0.duration_ms", 15_001),
            "renderable directing shots are at most 15 seconds",
        ),
        "StoryTime": (v2_story_time, _set("schema_version", "1.0"), "V1 payload is not V2"),
        "WardrobeBible": (v2_wardrobe_bible, _set("schema_version", "1.0"), "V1 payload is not V2"),
        "SceneWardrobeAssignment": (
            v2_wardrobe_assignment,
            _set("rights.status", "EXPIRED"),
            "expired outfit rights block use",
        ),
        "StateEvent": (v2_state_event, _set("after", "closed"), "state event must change state"),
        "AssetSheet": (
            v2_asset_sheet,
            _set("rights.status", "INELIGIBLE"),
            "retired/ineligible rights block use",
        ),
        "PropSheet": (
            v2_prop_sheet,
            _set("known_states", []),
            "prop requires typed state variants",
        ),
        "StyleBible": (
            v2_style_bible,
            _set("palette", []),
            "series style requires a defined palette",
        ),
        "LocationLayout": (
            v2_location_layout,
            _set("entrance_ids", []),
            "location requires entrance geometry",
        ),
        "ShotReferenceBinding": (
            v2_binding_example,
            _set("role", "untyped"),
            "references require a semantic role",
        ),
        "PromptManifest": (
            v2_prompt_manifest,
            _set(
                "bindings",
                [b for b in _json(v2_prompt_manifest())["bindings"] if b["role"] != "outfit"],
            ),
            "assigned outfit reference required",
        ),
        "ProgressSnapshot": (
            v2_progress_snapshot,
            _set("required_work", 0),
            "progress cannot invent a denominator",
        ),
        "ReleaseApprovalManifest": (
            v2_release_approval_manifest,
            _set("slots.0.title", "Changed after approval"),
            "Gate-2 hash binds exact metadata",
        ),
    }
    for model_name, (builder, mutate, reason) in v2_specific.items():
        cases.append((model_name, "v2_invalid_" + model_name.lower(), reason, m(builder, mutate)))
    cases.append(
        (
            "ConceptCandidate",
            "pending_rights_without_status",
            "candidate rights uncertainty must use an explicit PENDING or UNKNOWN status",
            m(
                v2_concept_candidate,
                _set(
                    "rights",
                    {"note": "Rights status has not been established."},
                ),
            ),
        )
    )
    cases.extend(
        [
            (
                "CreativeDerivativeRef",
                "missing_source_rights",
                "each derivative source needs its own eligible rights grant",
                m(creative_derivative_ref, _del("sources.0.rights")),
            ),
            (
                "CreativeDerivativeRef",
                "missing_derivation_manifest",
                "derivative must bind its deterministic derivation manifest",
                m(creative_derivative_ref, _del("derivation_manifest_sha256")),
            ),
            (
                "CreativeDerivativeRef",
                "poster_missing_readability_evidence",
                "poster requires readability evidence hash",
                m(creative_poster_ref, _del("readability_evidence_sha256")),
            ),
            (
                "CreativeDerivativeRef",
                "unsafe_platform_text_box",
                "CTA text box must remain within its platform mobile safe zone",
                m(creative_derivative_ref, _set("platform_safe_zones.0.cta_box.x_bp", 4000)),
            ),
            (
                "CreativeDerivativeRef",
                "unknown_source_role",
                "derivative source role is closed",
                m(creative_derivative_ref, _set("sources.1.role", "SFX")),
            ),
            (
                "CreativeDerivativeRef",
                "preview_without_footage_source",
                "episode-one preview needs at least one footage source",
                m(creative_derivative_ref, _set("sources.0.role", "AUDIO")),
            ),
            (
                "CreativeDerivativeRef",
                "reveal_boundary_outside_footage",
                "footage source must end before its approved source-timeline cutoff",
                m(creative_derivative_ref, _set("sources.0.source_out_ms", 41_000)),
            ),
            (
                "EpisodePack",
                "missing_beat_dependency",
                "beat dependencies must resolve inside the same pack",
                invalid_pack(_set("scenes.0.beats.0.dependency_beat_ids", ["missing-beat"])),
            ),
            (
                "ReleasePackage",
                "episode_one_poster_wrong_reveal_episode",
                "episode-one poster must bind approved reveal episode 1",
                invalid_derivative_package_reveal(),
            ),
            (
                "EpisodePack",
                "cyclic_beat_dependencies",
                "beat dependency graphs must be acyclic",
                invalid_pack(cyclic_beats),
            ),
            (
                "EpisodePack",
                "unknown_proof_object",
                "proof objects must reference props in the containing scene",
                invalid_pack(_set("scenes.0.beats.0.proof_object_ids", ["missing-prop"])),
            ),
            (
                "EpisodePack",
                "missing_scene_dependency",
                "scene dependencies must resolve inside the same pack",
                invalid_pack(_set("scenes.0.dependency_scene_ids", ["missing-scene"])),
            ),
            (
                "EpisodePack",
                "cyclic_scene_dependencies",
                "scene dependency graphs must be acyclic",
                invalid_pack(cyclic_scenes),
            ),
            (
                "EpisodePack",
                "missing_approved_scope_hash",
                "episode packs must bind the exact Gate 1 approved scope hash",
                m(v2_episode_pack, _del("approved_scope_hash")),
            ),
        ]
    )
    cases.append(
        (
            "ConceptIntake",
            "stale_content_hash",
            "V2 canonical content hash must match payload on readback",
            m(v2_concept_intake, _set("story_idea", "tampered without resealing")),
        )
    )
    cases.append(
        (
            "V1ManifestReadback",
            "claims_v2_ready",
            "legacy V1 readback is never V2-ready",
            _mutate(v1_manifest_readback, _set("v2_ready", True)),
        )
    )
    return cases

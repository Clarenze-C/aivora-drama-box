"""Season scope, approval commands, episode plans, scripts, shot manifests, identity locks."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from pydantic import Field, PlainSerializer, field_validator, model_validator

from microdrama.contracts.enums import (
    ApprovalAction,
    BudgetCategory,
    ControlKind,
    CriticalTermKind,
    DialogueComplexity,
    FallbackEdit,
    FeedbackCategory,
    FeedbackScope,
    GateType,
    IdentityAssetKind,
    Level,
    ManagementActionKind,
    Platform,
    RenderTier,
    ShotPattern,
    SlotKind,
)
from microdrama.contracts.primitives import (
    DEFAULT_BUDGET_ALLOCATION_MICRO_USD,
    DEFAULT_LIMITS,
    EPISODE_CAP_MICRO_USD,
    AccountRef,
    ContractModel,
    Count,
    DurationMs,
    IanaZone,
    IdempotencyKey,
    Identifier,
    LocaleTag,
    LongText,
    MicroUSD,
    PositiveInt,
    PositiveMs,
    Revision,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.states import GATE_ACTIONS

# --- Season scope (what Gate 1 approves) ---------------------------------------------


class ArcBeat(ContractModel):
    episode_number: PositiveInt
    summary: LongText
    planned_reveals: list[ShortText] = Field(
        default_factory=list, description="Planned only; not published canon"
    )
    cliffhanger: ShortText | None = None


class CharacterBrief(ContractModel):
    character_id: Identifier
    name_th: ShortText
    name_en: ShortText
    role: ShortText
    description: LongText
    voice_direction: ShortText
    featured: bool = True


class CreativeConstraints(ContractModel):
    max_active_locations_per_episode: PositiveInt = DEFAULT_LIMITS.max_active_locations
    max_featured_speaking_characters_per_episode: PositiveInt = (
        DEFAULT_LIMITS.max_featured_speaking_characters
    )
    max_speakers_per_shot: PositiveInt = DEFAULT_LIMITS.max_speakers_per_shot
    original_fiction_only: bool = True
    retain_thai_performances: bool = True
    content_rules: list[ShortText] = Field(default_factory=list)
    style_rules: list[ShortText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _within_initial_limits(self) -> CreativeConstraints:
        if not self.original_fiction_only or not self.retain_thai_performances:
            raise ValueError("MD-001: original fiction with Thai performances is mandatory")
        return self


class CostPolicy(ContractModel):
    episode_cap_micro_usd: MicroUSD = EPISODE_CAP_MICRO_USD
    allocation_micro_usd: dict[BudgetCategory, MicroUSD] = Field(
        default_factory=lambda: dict(DEFAULT_BUDGET_ALLOCATION_MICRO_USD)
    )
    shutdown_reserve_micro_usd: MicroUSD = 250_000
    max_attempts_per_shot: PositiveInt = DEFAULT_LIMITS.max_attempts_per_shot
    max_final_repair_rounds: Count = DEFAULT_LIMITS.max_final_repair_rounds
    max_transport_attempts: PositiveInt = DEFAULT_LIMITS.max_transport_attempts
    paid_advertising_budget_micro_usd: MicroUSD = 0
    automatic_cap_increase: bool = False

    @model_validator(mode="after")
    def _bounded(self) -> CostPolicy:
        if self.episode_cap_micro_usd > EPISODE_CAP_MICRO_USD:
            raise ValueError("episode cap cannot exceed US$10")
        if set(self.allocation_micro_usd) != set(BudgetCategory):
            raise ValueError("allocation must name every budget category exactly once")
        if sum(self.allocation_micro_usd.values()) != self.episode_cap_micro_usd:
            raise ValueError("allocation must sum exactly to the episode cap")
        if (
            self.shutdown_reserve_micro_usd
            > self.allocation_micro_usd[BudgetCategory.RECOVERY_HEADROOM]
        ):
            raise ValueError("shutdown reserve must fit inside recovery headroom")
        if (
            self.max_attempts_per_shot > 3
            or self.max_final_repair_rounds > 2
            or self.max_transport_attempts > 3
        ):
            raise ValueError("retry settings exceed accepted policy v2 maxima")
        if self.paid_advertising_budget_micro_usd != 0:
            raise ValueError("MD-018: initial paid-ad budget is zero")
        if self.automatic_cap_increase:
            raise ValueError("automatic cap increase is forbidden")
        return self


class DestinationSlotPlan(ContractModel):
    platform: Platform
    account_ref: AccountRef
    slot_kind: SlotKind
    locale: LocaleTag = "th-TH"
    required: bool = True


class ReleaseCadence(ContractModel):
    iana_zone: IanaZone = "Asia/Bangkok"
    weekdays: list[int] = Field(description="ISO weekdays 1..7", min_length=1)
    local_times: list[str] = Field(min_length=1, description="HH:MM wall-clock times")

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(type(d) is not int or not 1 <= d <= 7 for d in v):
            raise ValueError("weekdays must be integers 1..7")
        return v

    @field_validator("local_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        for t in v:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise ValueError(f"invalid HH:MM time {t!r}")
        return v


class ManagementPolicy(ContractModel):
    """The mutable-metadata/community scope Gate 2 approval binds by hash."""

    allowed_actions: Annotated[
        frozenset[ManagementActionKind],
        PlainSerializer(sorted, return_type=list[ManagementActionKind]),
    ]
    metadata_cooldown_hours: PositiveInt = DEFAULT_LIMITS.metadata_cooldown_hours
    max_substantive_edits_first_7_days: Count = (
        DEFAULT_LIMITS.max_substantive_metadata_edits_first_7_days
    )
    dm_keywords: list[ShortText] = Field(default_factory=list)
    moderation_policy_id: Identifier = "moderate-clear-spam-scams-threats-v1"
    automatic_account_bans: bool = False
    remove_ordinary_criticism: bool = False
    cold_outbound_dms: bool = False
    accept_contracts_sponsors_refunds: bool = False
    max_replies_per_post_per_day: Count = 50
    max_dms_per_conversation: Count = 3

    @model_validator(mode="after")
    def _organic_bounds(self) -> ManagementPolicy:
        if self.metadata_cooldown_hours < 24:
            raise ValueError("metadata cooldown below 24h")
        if self.max_substantive_edits_first_7_days > 2:
            raise ValueError("more than two substantive edits in first 7 days")
        if (
            self.automatic_account_bans
            or self.remove_ordinary_criticism
            or self.cold_outbound_dms
            or self.accept_contracts_sponsors_refunds
        ):
            raise ValueError("MD-018: forbidden organic-management capability enabled")
        return self


class SeasonScope(VersionedPayload):
    """Versioned season concept/arc/policy. Gate 1 approves ``scope_hash`` of this."""

    season_id: UUID
    scope_version: PositiveInt
    source_proposal_id: UUID
    title_th: ShortText
    title_en: ShortText
    logline: LongText
    premise: LongText
    genre_tags: list[Identifier] = Field(default_factory=list)
    expected_episode_count: PositiveInt = 10
    episode_min_duration_ms: PositiveMs = DEFAULT_LIMITS.episode_min_duration_ms
    episode_max_duration_ms: PositiveMs = DEFAULT_LIMITS.episode_max_duration_ms
    arc: list[ArcBeat] = Field(min_length=1)
    characters: list[CharacterBrief] = Field(min_length=1)
    creative_constraints: CreativeConstraints = Field(default_factory=CreativeConstraints)
    cost_policy: CostPolicy = Field(default_factory=CostPolicy)
    destinations: list[DestinationSlotPlan] = Field(min_length=1)
    release_cadence: ReleaseCadence
    management_policy: ManagementPolicy
    rights_route_id: Identifier | None = None
    research_evidence_refs: list[ShortText] = Field(default_factory=list)
    originality_statement: LongText
    uncertainty_notes: list[ShortText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _md002(self) -> SeasonScope:
        if not (180_000 <= self.episode_min_duration_ms <= self.episode_max_duration_ms <= 300_000):
            raise ValueError("MD-002: episodes must be 180-300 seconds")
        numbers = [b.episode_number for b in self.arc]
        if len(set(numbers)) != len(numbers) or max(numbers) > self.expected_episode_count:
            raise ValueError("arc episode numbers must be unique and within expected_episode_count")
        ids = [c.character_id for c in self.characters]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate character_id")
        return self


# --- Approval commands (Gate 1 / Gate 2) ------------------------------------------------


class TimecodedFeedback(ContractModel):
    """One Gate 2 revision note. Defaults to the smallest scope (shot/episode)."""

    category: FeedbackCategory
    start_ms: DurationMs
    end_ms: DurationMs
    asset_id: UUID | None = None
    shot_id: Identifier | None = None
    comment: str = Field(min_length=1, max_length=2000)
    scope: FeedbackScope = FeedbackScope.EPISODE
    explicit_recurring_instruction: bool = Field(
        default=False, description="User explicitly asked for this to apply to the series"
    )

    @model_validator(mode="after")
    def _scope(self) -> TimecodedFeedback:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        if self.scope is FeedbackScope.SERIES and not self.explicit_recurring_instruction:
            raise ValueError("series-wide feedback requires an explicit recurring instruction")
        if self.scope is FeedbackScope.SHOT and self.shot_id is None:
            raise ValueError("shot-scoped feedback must name shot_id")
        return self


class ApprovalCommand(VersionedPayload):
    """A human gate decision. The actor comes from the authenticated session, not here."""

    gate: GateType
    action: ApprovalAction
    entity_id: UUID = Field(description="season_id for Gate 1, episode_id for Gate 2")
    expected_revision: Revision
    package_hash: Sha256Hex = Field(description="Gate 1 scope hash / Gate 2 release package hash")
    media_hashes: list[Sha256Hex] = Field(default_factory=list)
    management_policy_hash: Sha256Hex | None = None
    release_scope_hash: Sha256Hex | None = None
    idempotency_key: IdempotencyKey
    feedback: list[TimecodedFeedback] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _gate_rules(self) -> ApprovalCommand:
        if self.action not in GATE_ACTIONS[self.gate]:
            raise ValueError(f"{self.action.value} is not a valid action for {self.gate.value}")
        if self.gate is GateType.EPISODE_FINAL and self.action is ApprovalAction.APPROVE:
            if not self.media_hashes:
                raise ValueError("Gate 2 approval must bind the immutable media hashes")
            if self.management_policy_hash is None or self.release_scope_hash is None:
                raise ValueError("Gate 2 approval must bind management policy and release scope")
        if self.action is ApprovalAction.REVISE and not self.feedback:
            raise ValueError("Revise requires at least one timecoded feedback item")
        if self.action is not ApprovalAction.REVISE and self.feedback:
            raise ValueError("feedback is only accepted with Revise")
        if len(set(self.media_hashes)) != len(self.media_hashes):
            raise ValueError("duplicate media hash")
        return self


# --- Episode plan / script / shots -----------------------------------------------------


class EpisodePlan(VersionedPayload):
    episode_id: UUID
    season_id: UUID
    approved_scope_hash: Sha256Hex
    episode_number: PositiveInt
    title_th: ShortText
    title_en: ShortText
    synopsis: LongText
    target_duration_ms: PositiveMs
    featured_character_ids: list[Identifier] = Field(min_length=1)
    location_ids: list[Identifier] = Field(min_length=1)
    planned_beats: list[ShortText] = Field(min_length=1)
    planned_reveals: list[ShortText] = Field(default_factory=list)
    cliffhanger: ShortText | None = None
    canon_version: Count = 0

    @model_validator(mode="after")
    def _limits(self) -> EpisodePlan:
        if not 180_000 <= self.target_duration_ms <= 300_000:
            raise ValueError("MD-002: target duration must be 180-300 s")
        if len(set(self.featured_character_ids)) > DEFAULT_LIMITS.max_featured_speaking_characters:
            raise ValueError("more than three featured speaking characters")
        if len(set(self.location_ids)) > DEFAULT_LIMITS.max_active_locations:
            raise ValueError("more than two active locations")
        return self


class CriticalTerm(ContractModel):
    kind: CriticalTermKind
    value_th: ShortText
    value_en: ShortText | None = None


class DialogueLine(ContractModel):
    line_id: Identifier
    speaker_character_id: Identifier
    voice_id: Identifier | None = None
    text_th: str = Field(min_length=1, max_length=1000, description="Exact Thai line")
    text_en: str = Field(min_length=1, max_length=1000, description="English translation")
    estimated_duration_ms: PositiveMs
    actual_duration_ms: PositiveMs | None = Field(
        default=None, description="From actual synthesized audio; None until measured"
    )
    critical_terms: list[CriticalTerm] = Field(default_factory=list)


class Scene(ContractModel):
    scene_id: Identifier
    location_id: Identifier
    summary: ShortText
    lines: list[DialogueLine] = Field(default_factory=list)


class Script(VersionedPayload):
    script_id: UUID
    episode_id: UUID
    version: PositiveInt
    approved_scope_hash: Sha256Hex
    canon_version: Count
    scenes: list[Scene] = Field(min_length=1)
    estimated_runtime_ms: PositiveMs

    @model_validator(mode="after")
    def _unique_ids(self) -> Script:
        line_ids = [ln.line_id for sc in self.scenes for ln in sc.lines]
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("duplicate line_id")
        scene_ids = [sc.scene_id for sc in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("duplicate scene_id")
        speakers = {ln.speaker_character_id for sc in self.scenes for ln in sc.lines}
        if len(speakers) > DEFAULT_LIMITS.max_featured_speaking_characters:
            raise ValueError("more than three speaking characters in one episode")
        locations = {sc.location_id for sc in self.scenes}
        if len(locations) > DEFAULT_LIMITS.max_active_locations:
            raise ValueError("more than two active locations in one episode")
        return self


class Shot(ContractModel):
    """One generated unit. Carries every directing-playbook/routing field (SPEC §7)."""

    shot_id: Identifier
    sequence: PositiveInt
    scene_id: Identifier
    shot_pattern_id: ShotPattern
    coverage_role: Identifier
    purpose: ShortText
    dramatic_importance: Level
    dialogue_complexity: DialogueComplexity
    temporal_risk: Level
    required_identity_controls: list[ControlKind] = Field(min_length=1)
    preferred_render_tier: RenderTier
    fallback_edit: FallbackEdit
    reference_lock_version: Count | None = Field(
        default=None, description="Identity lock version this shot must use (None = provisional)"
    )
    line_ids: list[Identifier] = Field(default_factory=list)
    speaker_ids: list[Identifier] = Field(default_factory=list)
    voice_ids: list[Identifier] = Field(default_factory=list)
    target_duration_ms: PositiveMs
    framing: ShortText
    eyelines: ShortText
    location_id: Identifier
    outfit_ids: list[Identifier] = Field(default_factory=list)
    prop_ids: list[Identifier] = Field(default_factory=list)
    required_reference_asset_ids: list[UUID] = Field(default_factory=list)
    sound: ShortText
    acceptance_criteria: list[ShortText] = Field(min_length=1)
    depends_on_shot_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _limits(self) -> Shot:
        if self.target_duration_ms > DEFAULT_LIMITS.max_shot_duration_ms:
            raise ValueError("shot exceeds the supported 15-second unit")
        if len(set(self.speaker_ids)) > DEFAULT_LIMITS.max_speakers_per_shot:
            raise ValueError("more than two speakers in one shot")
        expected = {
            0: DialogueComplexity.NONE,
            1: DialogueComplexity.SINGLE_SPEAKER,
            2: DialogueComplexity.TWO_SPEAKER,
        }[len(set(self.speaker_ids))]
        if self.dialogue_complexity is not expected:
            raise ValueError("dialogue_complexity does not match speaker_ids")
        if self.line_ids and not self.speaker_ids:
            raise ValueError("shots with dialogue lines must name speakers")
        if len(set(self.required_identity_controls)) != len(self.required_identity_controls):
            raise ValueError("duplicate required control")
        return self


class ShotManifest(VersionedPayload):
    manifest_id: UUID
    episode_id: UUID
    episode_number: PositiveInt
    script_id: UUID
    script_version: PositiveInt
    version: PositiveInt
    identity_lock_id: UUID | None = None
    shots: list[Shot] = Field(min_length=1)

    @model_validator(mode="after")
    def _graph(self) -> ShotManifest:
        ids = [s.shot_id for s in self.shots]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate shot_id")
        known = set(ids)
        for s in self.shots:
            missing = set(s.depends_on_shot_ids) - known
            if missing:
                raise ValueError(f"shot {s.shot_id} depends on unknown shots {sorted(missing)}")
        seqs = [s.sequence for s in self.shots]
        if len(set(seqs)) != len(seqs):
            raise ValueError("duplicate shot sequence")
        if self.episode_number > 1 and self.identity_lock_id is None:
            raise ValueError("IMP-01: later-episode manifests must reference the identity lock")
        return self


# --- Identity lock -------------------------------------------------------------------


class LockedAsset(ContractModel):
    asset_kind: IdentityAssetKind
    asset_id: UUID
    asset_version: PositiveInt
    content_sha256: Sha256Hex
    character_id: Identifier | None = None
    label: ShortText


class IdentityLock(VersionedPayload):
    """Created atomically by the episode-one Gate 2 approval (SPEC §5 rule 6)."""

    lock_id: UUID
    season_id: UUID
    source_episode_id: UUID
    version: PositiveInt
    approval_event_id: UUID
    release_package_hash: Sha256Hex
    locked_assets: list[LockedAsset] = Field(min_length=1)
    created_at: UtcDateTime

    @model_validator(mode="after")
    def _unique(self) -> IdentityLock:
        ids = [a.asset_id for a in self.locked_assets]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate locked asset")
        return self

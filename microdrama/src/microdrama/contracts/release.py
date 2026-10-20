"""Release packages, publication commands, capability records and management actions."""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    ActionDecision,
    CapabilityOperation,
    CapabilitySupport,
    CostBasis,
    DisclosureKind,
    EvidenceSource,
    ManagementActionKind,
    Platform,
    Provenance,
    ReleaseState,
    SlotKind,
)
from microdrama.contracts.hashing import canonical_hash, model_hash
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    DurationMs,
    EvidenceRef,
    Identifier,
    LocaleTag,
    MicroUSD,
    PositiveInt,
    PositiveMs,
    ScheduleInstant,
    SemanticKey,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)

FAKE_URL_SUFFIX = ".invalid"  # RFC 2606 reserved TLD; fakes may only emit these URLs


def check_url_provenance(url: str | None, provenance: Provenance) -> None:
    """Fakes must never report real URLs; live results must never use fake hosts."""
    if url is None:
        return
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("URLs must be absolute https URLs")
    is_fake_host = parsed.hostname.endswith(FAKE_URL_SUFFIX)
    if provenance is Provenance.FAKE_SYNTHETIC and not is_fake_host:
        raise ValueError("fake results may only report *.invalid URLs")
    if provenance is not Provenance.FAKE_SYNTHETIC and is_fake_host:
        raise ValueError("non-fake results cannot report *.invalid URLs")


class ReleaseSlotKey(ContractModel):
    """Unique publication slot: (series, episode, part, locale, platform, account, slot)."""

    series_id: UUID
    episode_id: UUID
    part: Count = Field(description="0 = full episode; 1..n = parts")
    locale: LocaleTag
    platform: Platform
    account_ref: AccountRef
    release_slot: Identifier

    @property
    def dedupe_key(self) -> str:
        return canonical_hash(self)


class ReleaseSlotPlan(ContractModel):
    slot: ReleaseSlotKey
    slot_kind: SlotKind
    required: bool
    asset_id: UUID
    asset_sha256: Sha256Hex
    schedule: ScheduleInstant
    depends_on: list[Sha256Hex] = Field(
        default_factory=list, description="dedupe_keys that must be PUBLISHED_VERIFIED first"
    )
    disclosures: list[DisclosureKind] = Field(min_length=1)
    capability_id: UUID
    capability_version: PositiveInt

    @model_validator(mode="after")
    def _ai_disclosure(self) -> ReleaseSlotPlan:
        if DisclosureKind.AI_GENERATED_CONTENT not in self.disclosures:
            raise ValueError("MD-015: synthetic-content disclosure is required on every route")
        if DisclosureKind.SPONSORED in self.disclosures:
            raise ValueError("MD-018: no sponsorships are in organic scope")
        if self.slot.dedupe_key in self.depends_on:
            raise ValueError("a slot cannot depend on itself")
        return self


class MediaRef(ContractModel):
    asset_id: UUID
    sha256: Sha256Hex
    role: Identifier = Field(
        description="master/variant/cover/caption/hook/contact_sheet/voice_anchor"
    )


class QASummary(ContractModel):
    blocking_finding_ids: list[UUID] = Field(default_factory=list)
    unknown_coverage_check_ids: list[Identifier] = Field(default_factory=list)
    finding_count: Count = 0
    provenance: Provenance


class CostSummary(ContractModel):
    episode_cap_micro_usd: MicroUSD
    settled_micro_usd: MicroUSD
    accrued_micro_usd: MicroUSD
    reserved_outstanding_micro_usd: MicroUSD
    remaining_micro_usd: MicroUSD
    synthetic_fake_micro_usd: MicroUSD = Field(
        default=0, description="Portion from fake providers (not real money)"
    )


class ReleasePackage(VersionedPayload):
    """What Gate 2 reviews. ``package_hash`` covers every immutable field."""

    package_id: UUID
    episode_id: UUID
    season_id: UUID
    episode_number: PositiveInt
    version: PositiveInt
    media: list[MediaRef] = Field(min_length=1)
    caption_track_ids: list[UUID] = Field(min_length=1)
    hook_experiment_id: UUID | None = None
    cast_package_asset_ids: list[UUID] = Field(
        default_factory=list, description="Episode one: contact sheet, voice anchors, outfits/sets"
    )
    release_scope: list[ReleaseSlotPlan] = Field(min_length=1)
    management_policy_hash: Sha256Hex
    qa: QASummary
    cost: CostSummary
    gate_blockers: list[ShortText] = Field(
        default_factory=list, description="Reasons Gate 2 approval is disabled (empty = enabled)"
    )
    package_hash: Sha256Hex

    @model_validator(mode="after")
    def _hash_and_rules(self) -> ReleasePackage:
        if self.package_hash != self.compute_hash():
            raise ValueError("package_hash does not match package content")
        if self.episode_number == 1 and not self.cast_package_asset_ids:
            raise ValueError("IMP-01: episode-one package must include the cast/identity package")
        keys = [p.slot.dedupe_key for p in self.release_scope]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate release slot")
        media_ids = {m.asset_id: m.sha256 for m in self.media}
        for plan in self.release_scope:
            if media_ids.get(plan.asset_id) != plan.asset_sha256:
                raise ValueError("release slot references media outside the package")
        if self.qa.blocking_finding_ids and not self.gate_blockers:
            raise ValueError("blocking findings must appear as gate blockers")
        return self

    def compute_hash(self) -> str:
        return model_hash(self, exclude={"package_hash", "gate_blockers", "cost"})

    @classmethod
    def seal(cls, **fields: object) -> ReleasePackage:
        """Build a package with ``package_hash`` computed from its content."""
        fields.pop("package_hash", None)
        fields.setdefault("gate_blockers", [])
        probe = cls.model_construct(**fields, package_hash="0" * 64)
        return cls(**fields, package_hash=probe.compute_hash())

    @property
    def media_hashes(self) -> list[str]:
        return sorted(m.sha256 for m in self.media)

    @property
    def release_scope_hash(self) -> str:
        return canonical_hash([p for p in self.release_scope])

    @property
    def gate_ready(self) -> bool:
        return not self.gate_blockers


class PostMetadata(ContractModel):
    locale: LocaleTag
    title: str = Field(min_length=1, max_length=200)
    caption: str = Field(default="", max_length=5000)
    description: str = Field(default="", max_length=5000)
    hashtags: list[ShortText] = Field(default_factory=list, max_length=30)
    cover_asset_id: UUID | None = None
    links: list[ShortText] = Field(default_factory=list)
    disclosures: list[DisclosureKind] = Field(min_length=1)
    catalog_version: PositiveInt


class PublicationCommand(VersionedPayload):
    command_id: UUID
    release_package_id: UUID
    release_package_hash: Sha256Hex
    approval_event_id: UUID
    slot: ReleaseSlotKey
    slot_kind: SlotKind
    asset_id: UUID
    asset_sha256: Sha256Hex
    metadata: PostMetadata
    metadata_version_id: UUID
    schedule: ScheduleInstant
    capability_id: UUID
    capability_version: PositiveInt
    client_token: ShortText

    @property
    def dedupe_key(self) -> str:
        return self.slot.dedupe_key


class PublishResult(VersionedPayload):
    state: ReleaseState
    external_id: ShortText | None = None
    url: str | None = None
    error_code: ShortText | None = None
    transient: bool = False
    retry_after_ms: DurationMs | None = None
    verified_fields: list[Identifier] = Field(default_factory=list)
    unverified_fields: list[Identifier] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def _url(self) -> PublishResult:
        check_url_provenance(self.url, self.provenance)
        if self.state is ReleaseState.PUBLISHED_VERIFIED:
            if self.external_id is None:
                raise ValueError("verified publication needs an external id")
            if not self.verified_fields:
                raise ValueError("verified publication must name the fields it verified")
        return self


class CapabilityLimits(ContractModel):
    max_duration_ms: PositiveMs | None = None
    min_duration_ms: DurationMs | None = None
    max_file_bytes: PositiveInt | None = None
    video_codecs: list[ShortText] = Field(default_factory=list)
    aspect_ratios: list[ShortText] = Field(default_factory=list)
    daily_post_quota: Count | None = None


class CapabilityRecord(VersionedPayload):
    """Per account/provider route. Research-date claims are not live evidence."""

    capability_id: UUID
    version: PositiveInt
    platform: Platform
    provider_route: Identifier
    account_ref: AccountRef
    account_type: ShortText
    operations: dict[CapabilityOperation, CapabilitySupport]
    limits: CapabilityLimits = Field(default_factory=CapabilityLimits)
    supported_disclosures: list[DisclosureKind] = Field(default_factory=list)
    dm_window_hours: Count | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    verified_at: UtcDateTime | None = None
    enabled: bool = False

    @model_validator(mode="after")
    def _enabled_needs_evidence(self) -> CapabilityRecord:
        if self.enabled:
            if not self.evidence:
                raise ValueError("an enabled capability needs evidence")
            if self.verified_at is None:
                raise ValueError("an enabled capability needs verified_at")
        return self

    def support(self, op: CapabilityOperation) -> CapabilitySupport:
        return self.operations.get(op, CapabilitySupport.UNKNOWN)

    @property
    def evidence_is_fake_only(self) -> bool:
        return bool(self.evidence) and all(
            e.source is EvidenceSource.FAKE_FIXTURE for e in self.evidence
        )


DESTRUCTIVE_ACTIONS = frozenset(
    {ManagementActionKind.MODERATE_HIDE, ManagementActionKind.MODERATE_DELETE}
)
METADATA_ACTIONS = frozenset(
    {
        ManagementActionKind.TITLE_EDIT,
        ManagementActionKind.CAPTION_EDIT,
        ManagementActionKind.DESCRIPTION_EDIT,
        ManagementActionKind.HASHTAG_EDIT,
        ManagementActionKind.COVER_CHANGE,
        ManagementActionKind.LINK_UPDATE,
    }
)

CONTENT_ACTIONS = (METADATA_ACTIONS - {ManagementActionKind.COVER_CHANGE}) | {
    ManagementActionKind.PUBLIC_REPLY,
    ManagementActionKind.DM_SEND,
}


class ManagementAction(VersionedPayload):
    action_id: UUID
    kind: ManagementActionKind
    platform: Platform
    account_ref: AccountRef
    platform_post_id: UUID | None = None
    target_external_id: ShortText | None = None
    community_event_id: UUID | None = None
    content: str | None = Field(default=None, max_length=5000)
    catalog_version: PositiveInt
    management_policy_hash: Sha256Hex
    dedupe_key: SemanticKey
    reservation_id: UUID | None = None
    estimated_cost_micro_usd: MicroUSD = 0
    cost_basis: CostBasis = CostBasis.ESTIMATED
    decision: ActionDecision = ActionDecision.PROPOSED
    reason: ShortText | None = None
    classifier_confidence_bp: int | None = Field(default=None, ge=0, le=10_000, strict=True)

    @model_validator(mode="after")
    def _shape(self) -> ManagementAction:
        if self.kind in CONTENT_ACTIONS and not self.content:
            raise ValueError(f"{self.kind.value} requires content")
        if self.decision is ActionDecision.SUPPRESSED and not self.reason:
            raise ValueError("suppressed actions must record a reason")
        if (
            self.estimated_cost_micro_usd > 0
            and self.reservation_id is None
            and self.decision is ActionDecision.EXECUTED
        ):
            raise ValueError("metered actions need a budget reservation before execution")
        return self

    @property
    def destructive(self) -> bool:
        return self.kind in DESTRUCTIVE_ACTIONS

"""Release packages, publication commands, capability records and management actions."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, Strict, model_validator

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
    BasisPoints,
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
from microdrama.contracts.v2 import RightsGrant

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
    remaining_micro_usd: MicroUSD = Field(
        description="Headroom for paid dispatch: cap - committed - shutdown reserve, never < 0"
    )
    shutdown_reserve_micro_usd: MicroUSD = Field(
        default=0, description="Protected shutdown/cleanup reserve, shown separately"
    )
    synthetic_fake_micro_usd: MicroUSD = Field(
        default=0, description="Portion from fake providers (not real money)"
    )


class DerivativeSourceRef(ContractModel):
    role: Literal["CHARACTER", "FOOTAGE", "AUDIO", "PROP", "TITLE", "CTA", "BACKGROUND"]
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    source_in_ms: DurationMs | None = None
    source_out_ms: PositiveMs | None = None
    rights: RightsGrant

    @model_validator(mode="after")
    def _source_range(self) -> DerivativeSourceRef:
        if (self.source_in_ms is None) != (self.source_out_ms is None):
            raise ValueError("derivative source range needs both in and out points")
        if (
            self.source_in_ms is not None
            and self.source_out_ms is not None
            and self.source_out_ms <= self.source_in_ms
        ):
            raise ValueError("derivative source range must be non-empty")
        return self


class SafeZoneTextBox(ContractModel):
    x_bp: BasisPoints
    y_bp: BasisPoints
    width_bp: Annotated[int, Strict(), Field(gt=0, le=10_000)]
    height_bp: Annotated[int, Strict(), Field(gt=0, le=10_000)]

    @model_validator(mode="after")
    def _bounds(self) -> SafeZoneTextBox:
        if self.x_bp + self.width_bp > 10_000 or self.y_bp + self.height_bp > 10_000:
            raise ValueError("text box extends beyond normalized canvas")
        return self


class PlatformSafeZone(ContractModel):
    platform: Platform
    top_bp: BasisPoints
    right_bp: BasisPoints
    bottom_bp: BasisPoints
    left_bp: BasisPoints
    title_box: SafeZoneTextBox | None = None
    cta_box: SafeZoneTextBox | None = None

    @model_validator(mode="after")
    def _usable_area(self) -> PlatformSafeZone:
        if self.top_bp + self.bottom_bp >= 10_000 or self.left_bp + self.right_bp >= 10_000:
            raise ValueError("platform safe zone leaves no usable text area")
        return self


class CreativeDerivativeRef(ContractModel):
    derivative_type: Literal["POSTER", "EPISODE_ONE_PREVIEW"]
    asset_id: UUID
    asset_version: PositiveInt
    asset_sha256: Sha256Hex
    derivation_manifest_sha256: Sha256Hex
    approved_reveal_episode: PositiveInt
    readability_evidence_sha256: Sha256Hex | None = None
    sources: list[DerivativeSourceRef] = Field(min_length=1)
    duration_ms: PositiveMs | None = Field(default=None, le=90_000)
    reveal_boundary_ms: DurationMs | None = None
    platform_safe_zones: list[PlatformSafeZone] = Field(min_length=1)
    title_text: ShortText | None = None
    cta_text: ShortText
    no_release_obligation: Literal[True] = True

    @model_validator(mode="after")
    def _creative_contract(self) -> CreativeDerivativeRef:
        if self.asset_id in {source.asset_id for source in self.sources}:
            raise ValueError("derivative asset cannot be its own source")
        platforms = [zone.platform for zone in self.platform_safe_zones]
        if len(set(platforms)) != len(platforms):
            raise ValueError("duplicate derivative platform safe zone")
        is_poster = self.derivative_type == "POSTER"
        if is_poster:
            if self.duration_ms is not None:
                raise ValueError("poster cannot have video duration")
            if self.title_text is None:
                raise ValueError("poster requires approved title text")
            if self.readability_evidence_sha256 is None:
                raise ValueError("poster requires readability evidence hash")
            if not any(source.role == "CHARACTER" for source in self.sources):
                raise ValueError("poster requires an approved character source")
            footage_sources = [source for source in self.sources if source.role == "FOOTAGE"]
            if not footage_sources and self.reveal_boundary_ms is not None:
                raise ValueError("poster without footage cannot have a timecode reveal boundary")
            if any(
                source.source_in_ms is None or source.source_out_ms is None
                for source in footage_sources
            ):
                raise ValueError("poster footage sources need exact source ranges")
            if self.reveal_boundary_ms is not None and any(
                source.source_out_ms > self.reveal_boundary_ms for source in footage_sources
            ):
                raise ValueError("poster footage source exceeds approved reveal cutoff")
        else:
            if self.duration_ms is None or self.reveal_boundary_ms is None:
                raise ValueError("episode-one preview needs duration and reveal boundary")
            if any(
                source.source_in_ms is None or source.source_out_ms is None
                for source in self.sources
            ):
                raise ValueError("preview sources need exact source ranges")
            if any(source.role not in {"FOOTAGE", "AUDIO"} for source in self.sources):
                raise ValueError("episode-one preview sources must be footage or audio")
            footage_sources = [source for source in self.sources if source.role == "FOOTAGE"]
            if not footage_sources:
                raise ValueError("episode-one preview requires at least one footage source")
            if any(source.source_out_ms > self.reveal_boundary_ms for source in footage_sources):
                raise ValueError("preview footage source exceeds approved reveal cutoff")

        for zone in self.platform_safe_zones:
            if zone.cta_box is None:
                raise ValueError("CTA text box is required for each platform safe zone")
            if is_poster and zone.title_box is None:
                raise ValueError("poster title text box is required for each platform safe zone")
            for box in (zone.title_box, zone.cta_box):
                if box is None:
                    continue
                if (
                    box.x_bp < zone.left_bp
                    or box.y_bp < zone.top_bp
                    or box.x_bp + box.width_bp > 10_000 - zone.right_bp
                    or box.y_bp + box.height_bp > 10_000 - zone.bottom_bp
                ):
                    raise ValueError("text box falls outside its platform safe zone")
        return self


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
    creative_derivatives: list[CreativeDerivativeRef] | None = None
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
        derivatives = self.creative_derivatives or []
        if len({item.asset_id for item in derivatives}) != len(derivatives):
            raise ValueError("duplicate creative derivative asset")
        if len({item.derivative_type for item in derivatives}) != len(derivatives):
            raise ValueError("duplicate creative derivative type")
        release_assets = {plan.asset_id for plan in self.release_scope}
        media_hashes = {item.asset_id: item.sha256 for item in self.media}
        cast_assets = set(self.cast_package_asset_ids)
        for derivative in derivatives:
            if derivative.asset_id in release_assets:
                raise ValueError("creative derivative cannot create a release obligation")
            if derivative.derivative_type == "EPISODE_ONE_PREVIEW" and self.episode_number != 1:
                raise ValueError("episode-one preview can appear only in episode one package")
            if (
                derivative.derivative_type == "POSTER"
                and self.episode_number == 1
                and derivative.approved_reveal_episode != 1
            ):
                raise ValueError("episode-one poster must bind approved reveal episode 1")
            if derivative.approved_reveal_episode > self.episode_number:
                raise ValueError("derivative reveal episode exceeds package episode number")
            for source in derivative.sources:
                if source.asset_id in media_hashes:
                    if media_hashes[source.asset_id] != source.asset_sha256:
                        raise ValueError(
                            "derivative source hash differs from accepted package media"
                        )
                elif derivative.derivative_type != "POSTER" or source.asset_id not in cast_assets:
                    raise ValueError("derivative source is outside accepted package assets")
        return self

    def compute_hash(self) -> str:
        excluded = {"package_hash", "gate_blockers", "cost"}
        if self.creative_derivatives is None:
            excluded.add("creative_derivatives")
        return model_hash(self, exclude=excluded)

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
    cover_asset_version: PositiveInt | None = None
    cover_asset_sha256: Sha256Hex | None = None
    cta_text: ShortText | None = None
    links: list[ShortText] = Field(default_factory=list)
    disclosures: list[DisclosureKind] = Field(min_length=1)
    catalog_version: PositiveInt

    @model_validator(mode="after")
    def _cover_projection(self) -> PostMetadata:
        # V1 callers may still supply only cover_asset_id. V2 publication commands
        # require the exact version/hash tuple at their boundary.
        if (self.cover_asset_version is None) != (self.cover_asset_sha256 is None):
            raise ValueError("cover version and hash must be provided together")
        if self.cover_asset_id is None and self.cover_asset_version is not None:
            raise ValueError("cover version/hash require a cover asset id")
        return self


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
    release_manifest_id: UUID | None = None
    release_manifest_version: PositiveInt | None = None
    release_manifest_sha256: Sha256Hex | None = None
    approved_metadata_version: PositiveInt | None = None
    approved_metadata_sha256: Sha256Hex | None = None
    metadata_policy_id: Identifier | None = None
    metadata_policy_version: PositiveInt | None = None
    metadata_policy_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _v2_manifest_binding(self) -> PublicationCommand:
        binding_values = (
            self.release_manifest_id,
            self.release_manifest_version,
            self.release_manifest_sha256,
            self.approved_metadata_version,
            self.approved_metadata_sha256,
            self.metadata_policy_id,
            self.metadata_policy_version,
            self.metadata_policy_sha256,
        )
        if any(value is not None for value in binding_values) and any(
            value is None for value in binding_values
        ):
            raise ValueError(
                "V2 publication binding must include exact manifest, metadata and policy"
            )
        if self.release_manifest_id is not None:
            cover_values = (
                self.metadata.cover_asset_id,
                self.metadata.cover_asset_version,
                self.metadata.cover_asset_sha256,
            )
            if any(value is not None for value in cover_values) and any(
                value is None for value in cover_values
            ):
                raise ValueError(
                    "V2 publication binding cover must be fully bound or explicitly absent"
                )
        return self

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


# Evidence that can back a SUPPORTED_TESTED claim (FAKE_FIXTURE only ever counts in OFFLINE_MOCK).
TESTED_EVIDENCE_SOURCES = frozenset(
    {EvidenceSource.CONTROLLED_ACCOUNT_TEST, EvidenceSource.FAKE_FIXTURE}
)


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
        tested = any(s is CapabilitySupport.SUPPORTED_TESTED for s in self.operations.values())
        if tested and not any(e.source in TESTED_EVIDENCE_SOURCES for e in self.evidence):
            raise ValueError(
                "SUPPORTED_TESTED operations need CONTROLLED_ACCOUNT_TEST evidence "
                "(FAKE_FIXTURE for mock fixtures); documentation alone is not a test"
            )
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

"""Membership catalog, metric snapshots and qualification results."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.enums import (
    CatalogPublicState,
    MembershipProviderKind,
    Platform,
    Provenance,
    QualificationStatus,
    SnapshotWindow,
    TrafficKind,
)
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    CurrencyCode,
    Identifier,
    MicroUSD,
    PositiveInt,
    ScheduleInstant,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.release import check_url_provenance

_SECRET_QUERY_KEYS = {"token", "access_token", "auth", "key", "signature", "sig", "secret", "code"}


def _no_secret_in_link(url: str) -> None:
    query = parse_qs(urlparse(url).query)
    if _SECRET_QUERY_KEYS & {k.lower() for k in query}:
        raise ValueError("public links cannot carry playback tokens or secrets")


class MemberPrice(ContractModel):
    amount_micro_usd: MicroUSD
    currency: CurrencyCode = "USD"
    interval: Identifier = Field(default="month")


class MembershipCatalogEntry(VersionedPayload):
    """Truthful public/early-access state for one episode (MD-016)."""

    entry_id: UUID
    season_id: UUID
    episode_id: UUID
    episode_number: PositiveInt
    catalog_version: PositiveInt
    public_state: CatalogPublicState
    media_finished_and_approved: bool
    approval_event_id: UUID | None = None
    member_provider: MembershipProviderKind | None = None
    member_post_id: ShortText | None = None
    member_price: MemberPrice | None = None
    free_release: ScheduleInstant | None = Field(
        default=None, description="Announced free date; cannot silently move"
    )
    public_url: str | None = None
    member_url: str | None = None
    entitlement_verified_at: UtcDateTime | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _truthful(self) -> MembershipCatalogEntry:
        if self.public_state is CatalogPublicState.EARLY_ACCESS_MEMBERS:
            if not self.media_finished_and_approved or self.approval_event_id is None:
                raise ValueError("cannot sell early access to unfinished/unapproved media")
            if self.member_provider is None or self.member_price is None:
                raise ValueError("early access needs a provider and truthful recurring price")
            if self.free_release is None:
                raise ValueError("early access must preserve the announced free release date")
        if self.public_state is CatalogPublicState.PUBLIC_FREE and self.public_url is None:
            raise ValueError("a public-free entry needs a verified public URL")
        for url in (self.public_url, self.member_url):
            if url is not None:
                check_url_provenance(url, self.provenance)
                _no_secret_in_link(url)
        return self


class MetricValue(ContractModel):
    value: int | None = Field(default=None, strict=True, description="None = missing, not zero")
    definition: ShortText = Field(description="Platform's own metric definition id")
    denominator: Count | None = None


class MetricSnapshot(VersionedPayload):
    snapshot_id: UUID
    platform: Platform
    account_ref: AccountRef
    platform_post_id: UUID
    external_post_id: ShortText
    episode_id: UUID
    window: SnapshotWindow
    observed_at: UtcDateTime
    definitions_version: ShortText
    metrics: dict[Identifier, MetricValue]
    country: ShortText | None = None
    traffic: TrafficKind = TrafficKind.UNKNOWN
    sample_count: Count | None = None
    provenance: Provenance


class EpisodeQualification(ContractModel):
    episode_id: UUID
    episode_number: PositiveInt
    production_qualifies: bool | None = Field(description="None = still pending")
    production_reasons: list[ShortText] = Field(default_factory=list)
    management_window_status: QualificationStatus
    management_window_ends_at: UtcDateTime | None = None
    variable_cost_micro_usd: MicroUSD
    failed_attempt_cost_micro_usd: MicroUSD = 0
    manual_interventions: Count = 0
    human_review_minutes: Count | None = None
    published_minutes_ms: Count = 0


class QualificationResult(VersionedPayload):
    """Rolling ten-episode qualification (IMP-08). One success is never enough."""

    run_id: UUID
    season_id: UUID
    evaluated_at: UtcDateTime
    required_consecutive: int = Field(default=10, ge=10, le=10, strict=True)
    consecutive_qualifying_production: Count
    production_status: QualificationStatus
    management_status: QualificationStatus
    episodes: list[EpisodeQualification] = Field(default_factory=list)
    streak_resets: list[ShortText] = Field(default_factory=list)
    total_variable_spend_micro_usd: MicroUSD
    successful_episodes: Count
    effective_cost_per_successful_episode_micro_usd: MicroUSD | None = None
    effective_cost_per_published_minute_micro_usd: MicroUSD | None = None
    fixed_costs_reported_separately: bool = True
    provenance: Provenance

    @model_validator(mode="after")
    def _rules(self) -> QualificationResult:
        if (
            self.production_status is QualificationStatus.QUALIFIED
            and self.consecutive_qualifying_production < self.required_consecutive
        ):
            raise ValueError("production qualification needs ten consecutive qualifying episodes")
        if (
            self.successful_episodes == 0
            and self.effective_cost_per_successful_episode_micro_usd is not None
        ):
            raise ValueError("no successful episodes: effective cost per episode is undefined")
        if not self.fixed_costs_reported_separately:
            raise ValueError("fixed costs must be reported separately")
        return self

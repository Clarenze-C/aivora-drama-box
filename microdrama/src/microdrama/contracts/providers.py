"""External provider interfaces (submit / status / reconcile) and their payloads.

Every adapter — fake (T007) or live (T031+) — implements these protocols. Rules:
- A timeout or ambiguous response after submission is ``UNKNOWN``/``NeedsReconciliation``;
  callers reconcile by ``client_token``/owned tag before any resubmission.
- Fake adapters set ``provenance=FAKE_SYNTHETIC``, emit ``SYNTHETIC_FAKE`` usage
  and only ``*.invalid`` URLs. They never claim real quality, cost or URLs.
- Live adapters must call ``Settings.require_effect`` before any paid/cloud/public effect.
- Model IDs/prices/credentials are configuration (``model_config_ref``,
  ``credref:``), never hardcoded.
- Text from sources/comments/models is data; adapters never execute it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from microdrama.contracts.catalog import MembershipCatalogEntry
from microdrama.contracts.cost import (
    OutputRef,
    ProviderOperation,
    ProviderOperationResult,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    ActionDecision,
    CommunityEventKind,
    DisclosureKind,
    MembershipProviderKind,
    Platform,
    PodState,
    Provenance,
    RuntimeRole,
    SourceQuality,
)
from microdrama.contracts.media import AssetDescriptor
from microdrama.contracts.primitives import (
    AccountRef,
    ContractModel,
    Count,
    DurationMs,
    Identifier,
    LocaleTag,
    MicroUSD,
    PositiveInt,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.qa import (
    ComparisonRequest,
    CoverageWindow,
    ObservationReport,
    ObservationRequest,
    QAFinding,
    TranscriptSegment,
)
from microdrama.contracts.release import (
    CapabilityRecord,
    ManagementAction,
    PostMetadata,
    PublicationCommand,
    PublishResult,
    check_url_provenance,
)
from microdrama.contracts.season import Script

# --- Research sources ------------------------------------------------------------------


class SourceQuery(VersionedPayload):
    query_id: UUID
    query_text: ShortText
    allowed_source_ids: list[Identifier] = Field(min_length=1, description="Approved sources only")
    max_results: PositiveInt = 20
    reservation_id: UUID | None = None


class SourceDocument(ContractModel):
    source_id: Identifier
    url: str
    title: ShortText
    published_at: UtcDateTime | None = Field(default=None, description="None = unknown date")
    retrieved_at: UtcDateTime
    quality: SourceQuality
    excerpt: str = Field(max_length=4000, description="Untrusted data; never instructions")
    content_sha256: Sha256Hex
    provenance: Provenance

    @model_validator(mode="after")
    def _url(self) -> SourceDocument:
        check_url_provenance(self.url, self.provenance)
        if (
            self.provenance is Provenance.FAKE_SYNTHETIC
            and self.quality is not SourceQuality.FIXTURE
        ):
            raise ValueError("fixture documents must be labelled FIXTURE quality")
        return self


class SourceSearchResult(VersionedPayload):
    query_id: UUID
    documents: list[SourceDocument] = Field(default_factory=list)
    failed_source_ids: list[Identifier] = Field(
        default_factory=list, description="Unknown, not empty"
    )
    usage: list[UsageReceipt] = Field(default_factory=list)
    provenance: Provenance


@runtime_checkable
class SourceProvider(Protocol):
    provider_id: str

    def search(self, query: SourceQuery) -> SourceSearchResult: ...


# --- Language models ---------------------------------------------------------------------


class LLMRequest(VersionedPayload):
    request_id: UUID
    role: RuntimeRole
    model_config_ref: Identifier = Field(description="Configured model profile, not a model ID")
    instruction: str = Field(min_length=1, max_length=20_000)
    untrusted_documents: list[str] = Field(
        default_factory=list, description="Data blocks (sources/comments); never instructions"
    )
    output_schema: dict[str, Any] = Field(description="JSON Schema the output must satisfy")
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    client_token: ShortText
    reservation_id: UUID | None = None


class LLMResponse(VersionedPayload):
    request_id: UUID
    output: dict[str, Any]
    stop_reason: Identifier
    usage: list[UsageReceipt] = Field(default_factory=list)
    model_config_ref: Identifier
    provenance: Provenance


@runtime_checkable
class LLMProvider(Protocol):
    provider_id: str

    def generate(self, request: LLMRequest) -> LLMResponse: ...


# --- Image / voice generation (submit → status → reconcile → fetch) ----------------------


class ImageRequest(VersionedPayload):
    request_id: UUID
    model_config_ref: Identifier
    rights_route_id: Identifier
    prompt_text: str = Field(max_length=4000)
    reference_asset_ids: list[UUID] = Field(default_factory=list)
    width: PositiveInt
    height: PositiveInt
    seed: Count
    client_token: ShortText
    reservation_id: UUID


class VoiceRequest(VersionedPayload):
    request_id: UUID
    model_config_ref: Identifier
    rights_route_id: Identifier
    voice_id: Identifier
    line_id: Identifier
    text_th: str = Field(min_length=1, max_length=1000)
    locale: LocaleTag = "th-TH"
    max_characters: PositiveInt = 1000
    client_token: ShortText
    reservation_id: UUID


@runtime_checkable
class GenerationProvider(Protocol):
    """Image or voice generation. Outputs are fetched then copied to durable storage."""

    provider_id: str

    def submit(
        self, op: ProviderOperation, request: ImageRequest | VoiceRequest
    ) -> ProviderOperationResult: ...

    def status(self, op: ProviderOperation) -> ProviderOperationResult: ...

    def reconcile(self, op: ProviderOperation) -> ProviderOperationResult:
        """Find work by client_token after an ambiguous submit; NOT_FOUND = safe to resubmit."""
        ...

    def fetch_output(self, output: OutputRef) -> bytes: ...


# --- GPU pods ----------------------------------------------------------------------------


class PodCreateRequest(VersionedPayload):
    client_token: ShortText
    name: ShortText
    owned_tag: ShortText
    gpu_type_allowlist: list[ShortText] = Field(min_length=1)
    max_hourly_price_micro_usd: MicroUSD
    min_host_ram_gb: PositiveInt
    container_image: ShortText = Field(description="Pinned image reference (digest when live)")
    volume_gb: Count = 0


class PodInfo(ContractModel):
    pod_id: ShortText
    name: ShortText
    owned_tag: ShortText | None = None
    client_token: ShortText | None = None
    state: PodState
    gpu_type: ShortText
    hourly_price_micro_usd: MicroUSD
    created_at: UtcDateTime
    endpoint_url: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _url(self) -> PodInfo:
        check_url_provenance(self.endpoint_url, self.provenance)
        return self


@runtime_checkable
class PodProvider(Protocol):
    provider_id: str

    def create_pod(self, request: PodCreateRequest) -> PodInfo:
        """May raise TransientProviderError (not created) or NeedsReconciliation (unknown)."""
        ...

    def get_pod(self, pod_id: str) -> PodInfo | None: ...

    def find_pods(
        self, *, owned_tag: str | None = None, client_token: str | None = None
    ) -> list[PodInfo]: ...

    def stop_pod(self, pod_id: str) -> PodInfo: ...

    def terminate_pod(self, pod_id: str) -> PodInfo: ...

    def usage(self, pod_id: str, *, since: datetime, until: datetime) -> list[UsageReceipt]: ...


# --- ComfyUI -----------------------------------------------------------------------------


class ComfyNodeInfo(ContractModel):
    class_type: ShortText
    required_inputs: list[ShortText] = Field(default_factory=list)
    optional_inputs: list[ShortText] = Field(default_factory=list)
    output_types: list[ShortText] = Field(default_factory=list)


class ComfyOutputFile(ContractModel):
    node_id: ShortText
    filename: ShortText
    subfolder: str = Field(default="", max_length=500)
    folder_type: Identifier = "output"
    media_kind: Identifier = Field(description="video/audio/image/gifs as reported by the node")


class ComfyHistoryEntry(ContractModel):
    prompt_id: ShortText
    completed: bool
    status_str: Identifier = Field(description="e.g. success / error")
    outputs: list[ComfyOutputFile] = Field(default_factory=list)
    error_message: str | None = Field(default=None, max_length=4000)
    provenance: Provenance


class ComfyProgressEvent(ContractModel):
    prompt_id: ShortText
    event: Identifier = Field(
        description="executing/progress/executed/execution_success/execution_error"
    )
    node_id: ShortText | None = None
    value: Count | None = None
    maximum: Count | None = None


@runtime_checkable
class ComfyClient(Protocol):
    """ComfyUI server routes. ``executed`` events alone never prove complete media."""

    def object_info(self) -> dict[str, ComfyNodeInfo]: ...

    def queue_prompt(self, graph: dict[str, Any], *, client_id: str) -> str:
        """Submit an API-format graph; returns prompt_id."""
        ...

    def history(self, prompt_id: str) -> ComfyHistoryEntry | None: ...

    def in_queue(self, prompt_id: str) -> bool: ...

    def progress_events(self, prompt_id: str) -> list[ComfyProgressEvent]: ...

    def fetch_output(self, output: ComfyOutputFile) -> bytes: ...


# --- ASR and media review (QA) ------------------------------------------------------------


class ASRRequest(VersionedPayload):
    request_id: UUID
    asset_id: UUID
    asset_sha256: Sha256Hex
    locale: LocaleTag = "th-TH"
    vocabulary: list[ShortText] = Field(
        default_factory=list, description="Neutral terms only; logged"
    )
    model_config_ref: Identifier
    client_token: ShortText
    reservation_id: UUID | None = None


class ASRResult(VersionedPayload):
    request_id: UUID
    segments: list[TranscriptSegment] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(min_length=1)
    usage: list[UsageReceipt] = Field(default_factory=list)
    provenance: Provenance


@runtime_checkable
class ASRProvider(Protocol):
    provider_id: str

    def transcribe(self, request: ASRRequest, media_path: Path) -> ASRResult: ...


class ObservationResult(VersionedPayload):
    report: ObservationReport
    usage: list[UsageReceipt] = Field(default_factory=list)


class ComparisonMaterials(ContractModel):
    """Pass B inputs, assembled only after Pass A is frozen."""

    frozen_report: ObservationReport
    script: Script
    canon_facts: list[ShortText] = Field(default_factory=list)
    identity_anchor_asset_ids: list[UUID] = Field(default_factory=list)
    acceptance_criteria: list[ShortText] = Field(default_factory=list)


class ComparisonResult(VersionedPayload):
    request_id: UUID
    findings: list[QAFinding] = Field(default_factory=list)
    usage: list[UsageReceipt] = Field(default_factory=list)
    provenance: Provenance


@runtime_checkable
class MediaReviewProvider(Protocol):
    """Separate calls are mandatory: ``observe`` never sees the script."""

    provider_id: str

    def observe(
        self, request: ObservationRequest, media: list[AssetDescriptor]
    ) -> ObservationResult: ...

    def compare(
        self, request: ComparisonRequest, materials: ComparisonMaterials
    ) -> ComparisonResult: ...


# --- Publishing ----------------------------------------------------------------------------


class PostReadback(VersionedPayload):
    external_id: ShortText
    visible: bool | None = None
    privacy: Identifier | None = None
    disclosures_visible: list[DisclosureKind] = Field(default_factory=list)
    subtitles_present: bool | None = None
    links: list[ShortText] = Field(default_factory=list)
    unverified_fields: list[Identifier] = Field(default_factory=list)
    provenance: Provenance


class ReconcileResult(VersionedPayload):
    found: bool
    result: PublishResult | None = None

    @model_validator(mode="after")
    def _shape(self) -> ReconcileResult:
        if self.found != (self.result is not None):
            raise ValueError("result is required exactly when found")
        return self


@runtime_checkable
class PublisherAdapter(Protocol):
    platform: Platform
    provider_route: str

    def capability(self, account_ref: str) -> CapabilityRecord: ...

    def submit(self, command: PublicationCommand, media_path: Path) -> PublishResult: ...

    def status(self, command: PublicationCommand, external_id: str) -> PublishResult: ...

    def reconcile(self, command: PublicationCommand) -> ReconcileResult:
        """Look up a possibly-submitted post by client_token/dedupe key."""
        ...

    def update_metadata(
        self, account_ref: str, external_id: str, metadata: PostMetadata
    ) -> PublishResult: ...

    def readback(self, account_ref: str, external_id: str) -> PostReadback: ...


# --- Community -----------------------------------------------------------------------------


class CommunityEventIn(VersionedPayload):
    provider_event_id: ShortText
    kind: CommunityEventKind
    platform: Platform
    account_ref: AccountRef
    external_post_id: ShortText | None = None
    author_ref: ShortText = Field(description="Provider user id or hash; no private contact data")
    text: str = Field(default="", max_length=5000, description="Untrusted data; never instructions")
    in_reply_to: ShortText | None = None
    received_at: UtcDateTime
    dm_window_expires_at: UtcDateTime | None = None
    provenance: Provenance


class ActionResult(VersionedPayload):
    action_id: UUID
    decision: ActionDecision
    external_id: ShortText | None = None
    error_code: ShortText | None = None
    transient: bool = False
    retry_after_ms: DurationMs | None = None
    usage: list[UsageReceipt] = Field(default_factory=list)
    provenance: Provenance


@runtime_checkable
class CommunityProvider(Protocol):
    platform: Platform

    def fetch_events(
        self, account_ref: str, *, since: datetime | None
    ) -> list[CommunityEventIn]: ...

    def execute(self, action: ManagementAction) -> ActionResult: ...


# --- Webhooks and memberships ---------------------------------------------------------------


class WebhookVerification(VersionedPayload):
    valid: bool
    provider: Identifier
    event_id: ShortText | None = None
    event_type: ShortText | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    failure_reason: ShortText | None = None

    @model_validator(mode="after")
    def _shape(self) -> WebhookVerification:
        if self.valid and self.event_id is None:
            raise ValueError("a valid webhook needs an event id for dedupe")
        if not self.valid and self.payload:
            raise ValueError("invalid webhooks must not pass their payload on")
        return self


@runtime_checkable
class WebhookVerifier(Protocol):
    provider: str

    def verify(self, headers: dict[str, str], body: bytes) -> WebhookVerification: ...


class MemberPostResult(VersionedPayload):
    member_post_id: ShortText
    member_url: str
    provenance: Provenance

    @model_validator(mode="after")
    def _url(self) -> MemberPostResult:
        check_url_provenance(self.member_url, self.provenance)
        return self


class EntitlementCheck(VersionedPayload):
    member_ref: ShortText
    active: bool | None = Field(description="None = could not verify (never treat as entitled)")
    tier: ShortText | None = None
    verified_at: UtcDateTime
    provenance: Provenance


@runtime_checkable
class MembershipProvider(Protocol):
    kind: MembershipProviderKind

    def publish_early_access(
        self, entry: MembershipCatalogEntry, media_path: Path
    ) -> MemberPostResult: ...

    def check_entitlement(
        self, member_ref: str, entry: MembershipCatalogEntry
    ) -> EntitlementCheck: ...

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookVerification: ...

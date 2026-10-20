"""Service API route signatures (SPEC §4.3) and shared response/view models.

Module owners implement FastAPI routers for the routes they own and export a
factory ``build_router(deps) -> fastapi.APIRouter``; only the integrator
registers them in ``microdrama.api``. A contract test checks the composed app
exposes exactly these routes (plus the owner's ``/ui`` pages for review).

Status-code contract: 202 queued, 200 replay of an identical successful command,
409 stale/conflicting revision or idempotency-key reuse with different content,
422 invalid schema, 403 unauthorized/policy denial, 401 unauthenticated.
Asynchronous submission is never reported as completed success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from microdrama.contracts.catalog import MembershipCatalogEntry
from microdrama.contracts.enums import (
    EpisodeOutcome,
    EpisodeState,
    FeedbackCategory,
    JobStatus,
    QueueName,
    ReleaseState,
    SeasonState,
)
from microdrama.contracts.events import DomainEvent
from microdrama.contracts.primitives import (
    ContractModel,
    Count,
    IdempotencyKey,
    Identifier,
    MicroUSD,
    Revision,
    SemanticKey,
    Sha256Hex,
    ShortText,
    UtcDateTime,
    VersionedPayload,
)
from microdrama.contracts.qa import CoverageWindow, QAFinding
from microdrama.contracts.release import CostSummary, ReleasePackage
from microdrama.contracts.season import ApprovalCommand, ManagementPolicy, SeasonScope


class AuthKind(StrEnum):
    HUMAN_SESSION = "HUMAN_SESSION"  # owner review session cookie + CSRF on writes
    SERVICE_TOKEN = "SERVICE_TOKEN"  # internal bearer token (worker/n8n); never approves
    HUMAN_OR_SERVICE = "HUMAN_OR_SERVICE"
    PROVIDER_SIGNATURE = "PROVIDER_SIGNATURE"
    PUBLIC = "PUBLIC"


# --- Response/view models -----------------------------------------------------------------


class ErrorBody(ContractModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CommandAccepted(VersionedPayload):
    status: Literal["QUEUED", "REPLAYED", "RECORDED"]
    entity_id: UUID | None = None
    job_id: UUID | None = None
    event_id: UUID | None = None
    revision: Revision | None = None


class ComponentState(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class HealthView(ContractModel):
    status: Literal["ok"] = "ok"
    version: ShortText
    execution_mode: ShortText


class ReadinessView(ContractModel):
    ready: bool
    database: ComponentState
    queue: ComponentState
    config: ComponentState
    object_store: ComponentState


class SeasonProposalSummary(VersionedPayload):
    season_id: UUID
    proposal_id: UUID
    state: SeasonState
    revision: Revision
    scope_version: Count
    scope_hash: Sha256Hex
    title_th: ShortText
    title_en: ShortText
    logline: str
    research_spend_micro_usd: MicroUSD
    uncertainty_notes: list[ShortText] = Field(default_factory=list)


class SeasonView(VersionedPayload):
    summary: SeasonProposalSummary
    scope: SeasonScope
    evidence_refs: list[ShortText] = Field(default_factory=list)


class ReviewMediaLink(ContractModel):
    asset_id: UUID
    role: Identifier
    sha256: Sha256Hex
    review_path: ShortText = Field(description="Owner-scoped private path; not a public URL")


class EpisodeReviewView(VersionedPayload):
    episode_id: UUID
    episode_number: int
    state: EpisodeState
    outcome: EpisodeOutcome | None = None
    revision: Revision
    package: ReleasePackage | None = None
    gate_enabled: bool
    gate_blockers: list[ShortText] = Field(default_factory=list)
    media: list[ReviewMediaLink] = Field(default_factory=list)
    findings: list[QAFinding] = Field(default_factory=list)
    coverage: list[CoverageWindow] = Field(default_factory=list)
    cost: CostSummary | None = None
    management_policy: ManagementPolicy | None = None
    catalog_entry: MembershipCatalogEntry | None = None
    feedback_categories: list[FeedbackCategory] = Field(
        default_factory=lambda: list(FeedbackCategory)
    )


class EventsView(VersionedPayload):
    aggregate_id: UUID
    events: list[DomainEvent] = Field(default_factory=list)
    unknown_states: list[ShortText] = Field(default_factory=list, description="Explicitly unknown")


class CostLine(ContractModel):
    receipt_id: UUID
    category: Identifier
    amount_micro_usd: MicroUSD
    cost_basis: Identifier
    kind: Identifier
    observed_at: UtcDateTime


class CostView(VersionedPayload):
    episode_id: UUID
    summary: CostSummary
    lines: list[CostLine] = Field(default_factory=list)
    overruns: list[ShortText] = Field(default_factory=list)
    unknowns: list[ShortText] = Field(default_factory=list)


class ReleaseSlotStatus(ContractModel):
    dedupe_key: Sha256Hex
    platform: Identifier
    account_ref: ShortText
    release_slot: Identifier
    required: bool
    state: ReleaseState
    external_id: ShortText | None = None
    url: str | None = None
    verified_fields: list[Identifier] = Field(default_factory=list)
    unverified_fields: list[Identifier] = Field(default_factory=list)
    blocker: ShortText | None = None


class ReleasesView(VersionedPayload):
    episode_id: UUID
    slots: list[ReleaseSlotStatus] = Field(default_factory=list)
    all_required_verified: bool


class JobEnqueueRequest(VersionedPayload):
    job_type: Identifier
    semantic_key: SemanticKey
    input: dict[str, Any]
    episode_id: UUID | None = None
    correlation_id: UUID | None = None
    idempotency_key: IdempotencyKey


class JobStatusView(VersionedPayload):
    job_id: UUID
    job_type: Identifier
    queue: QueueName
    status: JobStatus
    attempt: Count
    external_id: ShortText | None = None
    error_code: ShortText | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


# --- Route table -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteSpec:
    method: str
    path: str
    auth: AuthKind
    owner_module: str
    request_model: type[ContractModel] | None
    response_model: type[ContractModel] | None
    success_statuses: tuple[int, ...]
    description: str


ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec(
        "GET",
        "/seasons/proposals",
        AuthKind.HUMAN_SESSION,
        "review",
        None,
        SeasonProposalSummary,
        (200,),
        "List versioned proposals (no secrets); the body is a JSON array of the response model",
    ),
    RouteSpec(
        "GET",
        "/seasons/{season_id}",
        AuthKind.HUMAN_SESSION,
        "review",
        None,
        SeasonView,
        (200,),
        "Proposal scope, evidence, cost and status",
    ),
    RouteSpec(
        "POST",
        "/seasons/{season_id}/approval",
        AuthKind.HUMAN_SESSION,
        "review",
        ApprovalCommand,
        CommandAccepted,
        (200, 202),
        "Gate 1 approve/reject",
    ),
    RouteSpec(
        "GET",
        "/episodes/{episode_id}/review",
        AuthKind.HUMAN_SESSION,
        "review",
        None,
        EpisodeReviewView,
        (200,),
        "Gate 2 package with media/QA/cost/policy",
    ),
    RouteSpec(
        "POST",
        "/episodes/{episode_id}/review",
        AuthKind.HUMAN_SESSION,
        "review",
        ApprovalCommand,
        CommandAccepted,
        (200, 202),
        "Gate 2 approve/revise/reject",
    ),
    RouteSpec(
        "GET",
        "/episodes/{episode_id}/events",
        AuthKind.HUMAN_OR_SERVICE,
        "core",
        None,
        EventsView,
        (200,),
        "Auditable event history",
    ),
    RouteSpec(
        "GET",
        "/episodes/{episode_id}/costs",
        AuthKind.HUMAN_OR_SERVICE,
        "budget",
        None,
        CostView,
        (200,),
        "Receipts, reservations, overruns; unknowns explicit",
    ),
    RouteSpec(
        "GET",
        "/episodes/{episode_id}/releases",
        AuthKind.HUMAN_OR_SERVICE,
        "publishing",
        None,
        ReleasesView,
        (200,),
        "Per-slot release state and verification coverage",
    ),
    RouteSpec(
        "POST",
        "/internal/jobs",
        AuthKind.SERVICE_TOKEN,
        "core",
        JobEnqueueRequest,
        CommandAccepted,
        (200, 202),
        "Deterministic enqueue; cannot bypass policy",
    ),
    RouteSpec(
        "GET",
        "/internal/jobs/{job_id}",
        AuthKind.SERVICE_TOKEN,
        "core",
        None,
        JobStatusView,
        (200,),
        "Durable job status",
    ),
    RouteSpec(
        "POST",
        "/webhooks/{provider}",
        AuthKind.PROVIDER_SIGNATURE,
        "api",
        None,
        CommandAccepted,
        (200, 202),
        "Verify signature, dedupe, enqueue",
    ),
    RouteSpec(
        "GET", "/health", AuthKind.PUBLIC, "api", None, HealthView, (200,), "Liveness; no secrets"
    ),
    RouteSpec(
        "GET",
        "/ready",
        AuthKind.PUBLIC,
        "api",
        None,
        ReadinessView,
        (200, 503),
        "Readiness: database/queue/config/object store",
    ),
)

# Extra owner-module pages permitted outside ROUTES (server-rendered review UI, login).
MODULE_ROUTE_PREFIXES: dict[str, tuple[str, ...]] = {"review": ("/ui", "/auth")}

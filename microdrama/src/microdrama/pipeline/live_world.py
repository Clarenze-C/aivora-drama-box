"""Explicit, effect-gated composition for a T045 paid benchmark.

Construction wires clients and services but performs no provider I/O. Callers must
provide current, independently resolved rights/preset/workflow evidence and the
operator's quote; this module never manufactures those attestations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from microdrama.budget import BudgetService
from microdrama.budget.billing import BillingRepository, lease_billing_readiness
from microdrama.config import Settings
from microdrama.contracts.enums import EffectKind, ExecutionMode, RightsSubjectKind
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.registry.presets import PresetRegistry
from microdrama.core.registry.rights import RightsRegistry
from microdrama.persistence.db import Database
from microdrama.rendering.comfy_jobs import (
    ComfyRenderConfig,
    ComfyRenderService,
    build_comfy_render_service,
)
from microdrama.rendering.comfy_transport import ComfyHttpClient, HttpTransport
from microdrama.rendering.finality import RunpodInvoiceFinality
from microdrama.rendering.janitor import Janitor, build_janitor
from microdrama.rendering.leases import LeaseService, PodLeaseConfig, build_lease_service
from microdrama.rendering.pods import PodManager
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.runpod_billing import durable_pod_ownership_probe
from microdrama.rendering.runpod_transport import (
    RunpodQuoteAttestation,
    RunpodRestProvider,
    RunpodTransport,
)
from microdrama.rendering.workflows import template_sha256


@dataclass(frozen=True)
class RunpodQuoteEvidence:
    """Operator quote snapshot; values must match the provider attestation exactly."""

    quote_id: str
    currency: str
    captured_at: datetime
    expires_at: datetime
    compute_micro_usd_per_hour: int
    container_disk_gb: int
    container_storage_micro_usd_per_gb_month: int
    persistent_volume_gb: int
    persistent_storage_micro_usd_per_gb_month: int
    max_storage_exposure_micro_usd: int
    allowed_gpu_types: frozenset[str]
    host_ram_gb_by_gpu: dict[str, int]
    maximum_runtime_ms: int
    maximum_exposure_micro_usd: int

    def check(self, *, now: datetime, attestation: RunpodQuoteAttestation) -> None:
        dates = (
            now,
            self.captured_at,
            self.expires_at,
            attestation.quote_as_of,
            attestation.expires_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in dates):
            raise PolicyDenied("Runpod quote timestamps must be timezone aware")
        if not (self.captured_at <= now < self.expires_at):
            raise PolicyDenied("Runpod compute/storage quote is not current")
        if self.captured_at != attestation.quote_as_of or self.expires_at != attestation.expires_at:
            raise PolicyDenied("quote evidence window differs from provider attestation")
        if self.currency != "USD":
            raise PolicyDenied("Runpod quote evidence currency must be USD")
        # T045 R10: every attested quote field is cross-checked both ways — the evidence
        # names the same quote, currency, volume size and storage exposure the operator
        # attested, or composition refuses.
        if (
            self.quote_id != attestation.quote_id
            or self.currency != attestation.currency
            or self.persistent_volume_gb != attestation.persistent_volume_gb
            or self.max_storage_exposure_micro_usd != attestation.max_storage_exposure_micro_usd
        ):
            raise PolicyDenied(
                "quote evidence differs from provider attestation on quote id, currency, "
                "persistent volume or storage exposure"
            )
        if (
            self.compute_micro_usd_per_hour != attestation.quote_micro_usd_per_hour
            or self.container_disk_gb != attestation.container_disk_gb
            or self.container_storage_micro_usd_per_gb_month
            != attestation.container_storage_micro_usd_per_gb_month
            or self.persistent_storage_micro_usd_per_gb_month
            != attestation.persistent_storage_micro_usd_per_gb_month
            or self.allowed_gpu_types != attestation.allowed_gpu_types
            or self.host_ram_gb_by_gpu != dict(attestation.host_ram_gb_by_gpu)
        ):
            raise PolicyDenied("quote evidence differs from provider compute/storage attestation")
        if (
            min(
                self.compute_micro_usd_per_hour,
                self.container_disk_gb,
                self.container_storage_micro_usd_per_gb_month,
                self.persistent_storage_micro_usd_per_gb_month,
                self.maximum_runtime_ms,
                self.maximum_exposure_micro_usd,
            )
            <= 0
            or self.persistent_volume_gb < 0
        ):
            raise PolicyDenied("quote must include positive compute, storage and exposure bounds")
        # Conservative whole-second compute and 30-day-month storage ceiling.
        runtime_seconds = (self.maximum_runtime_ms + 999) // 1000
        compute = (self.compute_micro_usd_per_hour * runtime_seconds + 3599) // 3600
        storage_numerator = (
            self.container_disk_gb * self.container_storage_micro_usd_per_gb_month
            + self.persistent_volume_gb * self.persistent_storage_micro_usd_per_gb_month
        ) * self.maximum_runtime_ms
        storage = (storage_numerator + 30 * 24 * 60 * 60 * 1000 - 1) // (30 * 24 * 60 * 60 * 1000)
        if self.maximum_exposure_micro_usd < compute + storage:
            raise PolicyDenied("quote exposure ceiling does not cover compute and storage")
        if self.max_storage_exposure_micro_usd < storage:
            raise PolicyDenied("attested storage exposure ceiling does not cover quoted storage")


@dataclass(frozen=True)
class LiveBenchmarkEvidence:
    """Pins selected from current rights/preset registries and T031 quote evidence."""

    rights_route_id: str
    rights_subject_ref: str
    rights_subject_kind: RightsSubjectKind
    rights_version: int
    territories: tuple[str, ...]
    preset_id: str
    preset_version: int
    workflow_sha256: str
    image_digest: str
    node_schema_sha256: str
    output_controls_sha256: str
    eligible_until: datetime
    required_controls: tuple[str, ...]
    quote: RunpodQuoteEvidence
    maximum_exposure_micro_usd: int

    def check(self, *, now: datetime, attestation: RunpodQuoteAttestation) -> None:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (now, self.eligible_until)
        ):
            raise PolicyDenied("benchmark evidence timestamps must be timezone aware")
        if now >= self.eligible_until:
            raise PolicyDenied("benchmark rights/preset evidence is expired")
        if not attestation.pinned_image.endswith("@sha256:" + self.image_digest):
            raise PolicyDenied("benchmark image digest differs from the Runpod pin")
        if not all(
            (
                self.rights_route_id,
                self.rights_subject_ref,
                self.rights_version > 0,
                self.preset_id,
                self.preset_version,
                self.workflow_sha256,
                self.node_schema_sha256,
                self.output_controls_sha256,
                self.quote.quote_id,
                self.territories,
                self.required_controls,
                self.maximum_exposure_micro_usd > 0,
            )
        ):
            raise PolicyDenied("benchmark evidence is incomplete")
        self.quote.check(now=now, attestation=attestation)
        if self.maximum_exposure_micro_usd != self.quote.maximum_exposure_micro_usd:
            raise PolicyDenied("benchmark exposure cap differs from quoted maximum exposure")


def validate_registry_evidence(
    *,
    db: Database,
    settings: Settings,
    evidence: LiveBenchmarkEvidence,
    now: datetime,
    attestation: RunpodQuoteAttestation,
    clock: Clock,
) -> None:
    """Resolve exact current rights/preset versions and their declared workflow contract."""

    rights = RightsRegistry(db, clock, settings)
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT version FROM rights_registry WHERE rights_route_id = %s "
            "AND subject_kind = %s AND subject_ref = %s AND current",
            (
                evidence.rights_route_id,
                evidence.rights_subject_kind.value,
                evidence.rights_subject_ref,
            ),
        )
    if row is None or int(row["version"]) != evidence.rights_version:
        raise PolicyDenied("rights route/subject/version is not the selected current record")
    decision = rights.evaluate(
        rights_route_id=evidence.rights_route_id,
        subjects=[(evidence.rights_subject_kind, evidence.rights_subject_ref)],
        territories=evidence.territories,
        at=now,
    )
    if not decision.eligible:
        raise PolicyDenied("current rights evidence is not eligible", blockers=decision.blockers)

    registry = PresetRegistry(db, settings)
    record = registry.get(evidence.preset_id)
    if record is None or not record.enabled or record.version != evidence.preset_version:
        raise PolicyDenied("preset is missing, disabled or not the selected current version")
    if record.workflow_sha256 != evidence.workflow_sha256:
        raise PolicyDenied("preset workflow hash differs from the selected evidence")
    if record.rights_route_id != evidence.rights_route_id:
        raise PolicyDenied("preset rights route differs from selected rights evidence")
    required = set(evidence.required_controls)
    supported = {control.value for control in record.supported_controls}
    if not required or not required.issubset(supported):
        raise PolicyDenied("enabled preset does not support all required controls")
    view = PresetCatalog(db, registry).view(record)
    if view is None or template_sha256(view.template) != record.workflow_sha256:
        raise PolicyDenied("preset has no exact mapped workflow template")
    computed_node_hash = canonical_hash(
        {
            "template_id": view.template.template_id,
            "template_sha256": template_sha256(view.template),
            "node_classes": sorted(view.template.node_classes),
        }
    )
    if computed_node_hash != evidence.node_schema_sha256:
        raise PolicyDenied("node-class contract hash differs from mapped workflow")
    computed_controls_hash = canonical_hash(
        {
            "required_controls": sorted(required),
            "supported_controls": sorted(supported),
            "control_ports": dict(view.template.control_ports),
        }
    )
    if computed_controls_hash != evidence.output_controls_sha256:
        raise PolicyDenied("output/control hash differs from enabled preset workflow")
    if record.gpu_type not in evidence.quote.allowed_gpu_types:
        raise PolicyDenied("selected preset GPU is outside the current quote allowlist")
    if record.host_ram_gb > evidence.quote.host_ram_gb_by_gpu.get(record.gpu_type, 0):
        raise PolicyDenied("selected preset host RAM exceeds the current quote profile")


@dataclass(frozen=True)
class LiveBenchmarkWorld:
    """Services needed by the T045/T031 bounded canary path."""

    settings: Settings
    db: Database
    provider: RunpodRestProvider
    manager: PodManager
    leases: LeaseService
    comfy_client: ComfyHttpClient
    comfy: ComfyRenderService
    janitor: Janitor
    billing: BillingRepository

    def billing_readiness(self) -> list[Any]:
        """Per-lease billing readiness (T045 R7) for every runpod lease, oldest first."""
        with self.db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT id FROM pod_leases WHERE provider = 'runpod' ORDER BY created_at"
            )
        return [lease_billing_readiness(self.db, row["id"]) for row in rows]

    @property
    def billing_state(self) -> str:
        """The worst readiness any runpod lease reports; honest before any run too.

        With no lease yet nothing has reached provider finality, so the aggregate is
        ``PENDING_PROVIDER_FINALITY`` — never a pretend BILLED.
        """
        worst_rank = 0
        ranking = {
            "BILLED": 1,
            "AWAITING_INVOICE": 2,
            "PENDING_PROVIDER_FINALITY": 3,
            "RECOVERY_REQUIRED": 4,
            "DISPUTED": 5,
        }
        for readiness in self.billing_readiness():
            worst_rank = max(worst_rank, ranking.get(readiness.state, 3))
        return (
            next(state for state, rank in ranking.items() if rank == worst_rank)
            if worst_rank
            else "PENDING_PROVIDER_FINALITY"
        )


def build_live_benchmark_world(
    settings: Settings,
    db: Database,
    budget: BudgetService,
    store: ObjectStore,
    *,
    attestation: RunpodQuoteAttestation,
    evidence: LiveBenchmarkEvidence,
    billing: BillingRepository,
    runpod_credential_ref: str,
    comfy_credential_ref: str,
    credential_resolver: Callable[[str], str | None],
    pod_config: PodLeaseConfig,
    render_config: ComfyRenderConfig,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    runpod_transport: RunpodTransport | None = None,
    comfy_transport: HttpTransport | None = None,
) -> LiveBenchmarkWorld:
    """Compose a paid benchmark; no external effect occurs during this call.

    Credential resolvers are retained by the clients and only called after durable
    reservation/operation guards. ``billing`` (T045 R9) is the durable reconciliation
    repository the janitor ingests provider buckets into and the world computes its
    billing state from; the lease service and janitor settle exclusively through
    ``RunpodInvoiceFinality``.

    T045-FIX B-B2: the Comfy client is composed UNBOUND — its base URL is derived
    from the created Pod (``ComfyHttpClient.bind_pod_endpoint``) and nothing else can
    set it. T045-FIX B-B1: a render on this world's leased Runpod Pod must be
    lease-covered (the Pod lease's BILLED settlement is the only GPU cost), so a
    render config that would charge per GPU-second is refused here.
    """

    if settings.execution_mode is not ExecutionMode.PAID_BENCHMARK:
        raise EffectDenied("live benchmark composition requires PAID_BENCHMARK mode")
    settings.require_effect(EffectKind.PAID_REQUEST, what="live benchmark composition")
    settings.require_effect(EffectKind.CLOUD_RESOURCE, what="live benchmark composition")
    if settings.public_actions_enabled:
        raise EffectDenied("paid benchmark cannot enable public actions")
    for name, value in (
        ("Runpod", runpod_credential_ref),
        ("ComfyUI", comfy_credential_ref),
    ):
        if not value.startswith("credref:") or len(value) <= len("credref:"):
            raise EffectDenied(f"{name} credential must be a credref name")
    # T045 R9: only the durable reconciliation repository may back a live world — a
    # synthetic-finality object (offline recorded usage) must never settle real money.
    if not isinstance(billing, BillingRepository):
        raise PolicyDenied(
            "live benchmark composition requires a BillingRepository for durable billing finality"
        )

    live_clock, live_ids = clock or SystemClock(), ids or UuidIds()
    now = live_clock.now()
    attestation.check_current(now)
    evidence.check(now=now, attestation=attestation)
    if attestation.quote_micro_usd_per_hour > pod_config.max_hourly_price_micro_usd:
        raise PolicyDenied("current operator quote exceeds the configured reservation ceiling")
    if render_config.price is None or render_config.price.unit_price_micro_usd <= 0:
        raise PolicyDenied("Comfy render price must be known and positive")
    if not render_config.lease_covered:
        # T045-FIX B-B1: this world's Comfy endpoint IS the leased Runpod Pod, whose
        # GPU time the provider invoice already bills. A render config that would
        # settle measured GPU-seconds on top of the Pod lease's BILLED settlement
        # double-counts the same GPU time, so only a lease-covered config may compose.
        raise PolicyDenied(
            "a render on a leased Runpod Pod must be lease-covered: the Pod lease's "
            "BILLED settlement is the only GPU cost"
        )
    if evidence.maximum_exposure_micro_usd > settings.episode_cap_micro_usd:
        raise PolicyDenied("benchmark exposure exceeds the configured episode budget cap")
    if pod_config.owned_tag != f"microdrama-owned:{attestation.namespace}":
        raise PolicyDenied("lease ownership tag differs from isolated provider namespace")
    if pod_config.provider_account_ref != attestation.provider_account_ref:
        # T045 R10: the lease's durable account label must be exactly the attested one so
        # billing buckets reconcile against the account that actually billed the Pod.
        raise PolicyDenied("lease provider account differs from the attested account label")
    if pod_config.container_image != attestation.pinned_image:
        raise PolicyDenied("lease container image differs from attested digest")
    if not pod_config.allowed_gpu_types or not pod_config.allowed_gpu_types.issubset(
        attestation.allowed_gpu_types
    ):
        raise PolicyDenied("lease GPU allowlist differs from attested hardware")
    validate_registry_evidence(
        db=db,
        settings=settings,
        evidence=evidence,
        now=now,
        attestation=attestation,
        clock=live_clock,
    )

    def reservation_guard(request: Any, _quote: RunpodQuoteAttestation) -> None:
        # LeaseService creates and commits the reservation before PodManager invokes
        # provider.create_pod. The token and durable lease row bind the effect.
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT id, reservation_id, lease_state FROM pod_leases "
                "WHERE provider = 'runpod' AND client_token = %s",
                (request.client_token,),
            )
            if row is None or row["reservation_id"] is None:
                raise EffectDenied("Runpod create has no durable lease/reservation")
            reservation = tx.fetchone(
                "SELECT state FROM reservations WHERE id = %s", (row["reservation_id"],)
            )
        if reservation is None or reservation["state"] != "ACTIVE":
            raise EffectDenied("Runpod create reservation is not active")

    def cleanup_guard(operation_kind: str, pod_id: str) -> None:
        with db.transaction(readonly=True) as tx:
            lease = tx.fetchone(
                "SELECT id, lease_state FROM pod_leases WHERE provider = 'runpod' "
                "AND pod_id = %s ORDER BY created_at DESC LIMIT 1",
                (pod_id,),
            )
            if lease is None:
                raise EffectDenied("Runpod cleanup has no durable owned lease")
            if operation_kind not in {"pod.stop", "pod.terminate"}:
                raise EffectDenied("unsupported Runpod cleanup operation")

    owned_tag = f"microdrama-owned:{attestation.namespace}"

    provider = RunpodRestProvider(
        settings,
        credential_ref=runpod_credential_ref,
        credential_resolver=credential_resolver,
        attestation=attestation,
        now=live_clock.now,
        reservation_guard=reservation_guard,
        cleanup_guard=cleanup_guard,
        absent_pod_ownership_probe=durable_pod_ownership_probe(
            db, owned_tag=owned_tag, provider_account_ref=attestation.provider_account_ref
        ),
        transport=runpod_transport,
    )
    manager = PodManager(provider, live_clock, pod_config)
    # T045 R8/R9: the lease service and janitor settle only through the Runpod
    # invoice finality port. A caller-supplied repository keeps its settle lag.
    finality = (
        billing
        if isinstance(billing, RunpodInvoiceFinality)
        else RunpodInvoiceFinality(db, budget_service=budget, settle_lag=billing.settle_lag)
    )
    leases = build_lease_service(
        db, budget, manager, live_clock, live_ids, settings, pod_config, finality
    )

    def comfy_request_guard(path: str, authorization_key: str | None, authorization: Any) -> None:
        with db.transaction(readonly=True) as tx:
            reservation = tx.fetchone(
                "SELECT state, operation_kind, episode_id, job_id FROM reservations WHERE id = %s",
                (authorization.reservation_id,),
            )
            job = tx.fetchone(
                "SELECT id, episode_id FROM jobs WHERE id = %s", (authorization.job_id,)
            )
            operation = None
            if authorization.operation_id is not None:
                operation = tx.fetchone(
                    "SELECT provider, operation_kind, state, external_id, reservation_id, job_id "
                    "FROM provider_operations WHERE id = %s",
                    (authorization.operation_id,),
                )
        if (
            reservation is None
            or reservation["state"] != "ACTIVE"
            or reservation["operation_kind"] != "comfy.queue_prompt"
            or reservation["episode_id"] != authorization.episode_id
            or job is None
        ):
            raise EffectDenied("ComfyUI HTTP request lacks a matching active reservation/job")
        if authorization.operation_id is None:
            # Only the catalog read may run before a durable operation exists; the
            # job must still belong to the same episode as the reservation (a canary
            # reserves one prompt hold shared by its bounded prompt jobs).
            if path != "/object_info":
                raise EffectDenied("ComfyUI request requires a durable provider operation")
            if job["episode_id"] != authorization.episode_id:
                raise EffectDenied("ComfyUI catalog read is scoped to a foreign job")
            return
        if (
            operation is None
            or operation["provider"] != "comfyui"
            or operation["operation_kind"] != "comfy.queue_prompt"
            or operation["reservation_id"] != authorization.reservation_id
            or operation["job_id"] != authorization.job_id
            or operation["state"] in {"FAILED", "CANCELLED", "SUCCEEDED"}
        ):
            raise EffectDenied("ComfyUI HTTP request lacks a matching durable operation")
        if (
            authorization_key is not None
            and operation["external_id"] is not None
            # The prompt-id equality control applies where the request key names the
            # prompt (dispatch, status, history). A /view fetch keys its output file
            # (node:filename), which the operation match above already binds.
            and (path == "/prompt" or path.startswith("/history") or path == "/queue")
            and authorization_key != operation["external_id"]
        ):
            raise EffectDenied("ComfyUI request key differs from durable prompt ID")

    def comfy_dispatch_guard(authorization: Any) -> None:
        if authorization.operation_id is None:
            raise EffectDenied("ComfyUI prompt dispatch requires a durable operation ID")
        comfy_request_guard("/prompt", None, authorization)

    comfy_client = ComfyHttpClient(
        settings,
        credential_ref=comfy_credential_ref,
        credential_resolver=credential_resolver,
        request_guard=comfy_request_guard,
        dispatch_guard=comfy_dispatch_guard,
        transport=comfy_transport,
    )
    comfy = build_comfy_render_service(
        db, budget, comfy_client, live_clock, live_ids, settings, render_config, store
    )
    janitor = build_janitor(
        db, budget, provider, live_clock, live_ids, settings, pod_config, finality
    )
    return LiveBenchmarkWorld(
        settings=settings,
        db=db,
        provider=provider,
        manager=manager,
        leases=leases,
        comfy_client=comfy_client,
        comfy=comfy,
        janitor=janitor,
        billing=billing,
    )


__all__ = ["LiveBenchmarkEvidence", "LiveBenchmarkWorld", "build_live_benchmark_world"]

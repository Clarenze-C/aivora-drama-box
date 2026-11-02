"""The T045 R11 canary runner: preflight, one bounded execute, and invoice entry.

``python -m microdrama.pipeline.canary {preflight,execute,invoice} --authorization
<file.json>`` — preflight is the default. The authorization schema is exactly the R11
list (see ``canary_authorization.py`` and the runbook); an example with obviously fake
values ships beside the runbook at ``runbooks/canary-authorization.example.json``.

Safety posture (T045): preflight resolves no credential value and touches no network;
``execute`` refuses on a sha mismatch, a passed hard stop, an expired quote, a mode
other than PAID_BENCHMARK (or a missing paid/cloud flag) and a cap above the episode
cap — all before any transport call. Ambiguity stops for a human and is never retried
blind; the janitor is the backstop. Nothing here prints credential values,
``Authorization`` headers or the environment: credential refs are names only, and the
default resolver refuses (T031 supplies the real one under the operator's authority).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote, RenderRequest
from microdrama.contracts.enums import (
    ControlKind,
    EffectKind,
    ExecutionMode,
    PriceSource,
    PriceUnit,
    RightsSubjectKind,
)
from microdrama.contracts.errors import (
    EffectDenied,
    MicrodramaError,
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, ObjectStore
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.jobs import JobService
from microdrama.core.registry.presets import PresetRegistry
from microdrama.persistence import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.canary_authorization import (
    CanaryAuthorization,
    load_canary_authorization,
    prompt_pin,
)
from microdrama.pipeline.live_world import (
    LiveBenchmarkEvidence,
    LiveBenchmarkWorld,
    RunpodQuoteEvidence,
    build_live_benchmark_world,
)
from microdrama.rendering.comfy_jobs import ComfyRenderConfig, render_id_for
from microdrama.rendering.comfy_transport import HttpTransport
from microdrama.rendering.finality import RunpodInvoiceFinality
from microdrama.rendering.janitor import JanitorReport
from microdrama.rendering.leases import PodLeaseClaimRequest, PodLeaseConfig
from microdrama.rendering.presets import PresetCatalog
from microdrama.rendering.runpod_transport import RunpodQuoteAttestation, RunpodTransport
from microdrama.rendering.workflows import WorkflowTemplate, template_sha256

#: Where execute writes its canary record (overridable for tests).
DEFAULT_EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "evidence" / "provider-qualification"

#: Divisibility guard: GPU-second prices are integer micro-USD, so the hourly quote
#: must be a whole number of micro-USD per second or the ledger could not represent it.
MICRO_USD_PER_HOUR_DENOMINATOR = 3600


def _refusing_resolver(_ref: str) -> str | None:
    """The default resolver: nothing resolves outside T031's operator packet."""
    raise EffectDenied(
        "no credential resolver is configured; T031 supplies one under the operator's authorization"
    )


def canary_attestation(authorization: CanaryAuthorization) -> RunpodQuoteAttestation:
    quote = authorization.quote
    return RunpodQuoteAttestation(
        namespace=authorization.namespace,
        quote_id=quote.quote_id,
        currency=quote.currency,
        provider_account_ref=authorization.provider_account_ref,
        quote_micro_usd_per_hour=quote.compute_micro_usd_per_hour,
        quote_as_of=quote.captured_at,
        expires_at=quote.expires_at,
        container_disk_gb=quote.container_disk_gb,
        container_storage_micro_usd_per_gb_month=quote.container_storage_micro_usd_per_gb_month,
        persistent_volume_gb=quote.persistent_volume_gb,
        persistent_storage_micro_usd_per_gb_month=quote.persistent_storage_micro_usd_per_gb_month,
        max_storage_exposure_micro_usd=quote.max_storage_exposure_micro_usd,
        # T045-FIX B-B2: the full pinned reference, sent as-is on create.
        pinned_image=authorization.pins.image_ref,
        allowed_gpu_types=frozenset(quote.allowed_gpu_types),
        host_ram_gb_by_gpu=dict(quote.host_ram_gb_by_gpu),
        rights_evidence_id=authorization.rights.rights_evidence_id,
        preset_evidence_id=f"preset:{authorization.pins.preset_id}"
        f":v{authorization.pins.preset_version}",
        activation_enabled=True,
    )


def canary_evidence(authorization: CanaryAuthorization) -> LiveBenchmarkEvidence:
    quote = authorization.quote
    rights = authorization.rights
    return LiveBenchmarkEvidence(
        rights_route_id=rights.rights_route_id,
        rights_subject_ref=rights.rights_subject_ref,
        rights_subject_kind=RightsSubjectKind(rights.rights_subject_kind),
        rights_version=rights.rights_version,
        territories=tuple(rights.territories),
        preset_id=authorization.pins.preset_id,
        preset_version=authorization.pins.preset_version,
        workflow_sha256=authorization.pins.workflow_sha256,
        image_digest=authorization.pins.image_ref.rsplit("@sha256:", 1)[1],
        node_schema_sha256=authorization.pins.node_schema_sha256,
        output_controls_sha256=authorization.pins.output_controls_sha256,
        eligible_until=rights.eligible_until,
        required_controls=tuple(authorization.pins.required_controls),
        quote=RunpodQuoteEvidence(
            quote_id=quote.quote_id,
            currency=quote.currency,
            captured_at=quote.captured_at,
            expires_at=quote.expires_at,
            compute_micro_usd_per_hour=quote.compute_micro_usd_per_hour,
            container_disk_gb=quote.container_disk_gb,
            container_storage_micro_usd_per_gb_month=quote.container_storage_micro_usd_per_gb_month,
            persistent_volume_gb=quote.persistent_volume_gb,
            persistent_storage_micro_usd_per_gb_month=quote.persistent_storage_micro_usd_per_gb_month,
            max_storage_exposure_micro_usd=quote.max_storage_exposure_micro_usd,
            allowed_gpu_types=frozenset(quote.allowed_gpu_types),
            host_ram_gb_by_gpu=dict(quote.host_ram_gb_by_gpu),
            maximum_runtime_ms=quote.maximum_runtime_ms,
            maximum_exposure_micro_usd=quote.maximum_exposure_micro_usd,
        ),
        maximum_exposure_micro_usd=quote.maximum_exposure_micro_usd,
    )


def _gpu_second_price(authorization: CanaryAuthorization) -> PriceQuote:
    hourly = authorization.quote.compute_micro_usd_per_hour
    per_second, remainder = divmod(hourly, MICRO_USD_PER_HOUR_DENOMINATOR)
    if remainder or per_second <= 0:
        raise SchemaInvalid(
            "the canary hourly rate must be a whole number of micro-USD per GPU-second"
        )
    return PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=per_second,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version=f"canary:{authorization.quote.quote_id}",
        as_of=authorization.quote.captured_at,
    )


def canary_pod_config(authorization: CanaryAuthorization) -> PodLeaseConfig:
    return PodLeaseConfig(
        owned_tag=f"microdrama-owned:{authorization.namespace}",
        allowed_gpu_types=frozenset(authorization.quote.allowed_gpu_types),
        min_host_ram_gb=min(authorization.quote.host_ram_gb_by_gpu.values()),
        container_image=authorization.pins.image_ref,
        max_hourly_price_micro_usd=authorization.quote.compute_micro_usd_per_hour,
        price=_gpu_second_price(authorization),
        provider_account_ref=authorization.provider_account_ref,
        lease_ttl_ms=authorization.max_wall_seconds * 1000,
        shutdown_margin_ms=60_000,
    )


def canary_render_config(authorization: CanaryAuthorization) -> ComfyRenderConfig:
    """T045-FIX B-B1: the canary renders on a leased Runpod Pod, so the render is
    lease-covered - the prompt holds reserve at the real quote but settle at zero
    charge; the Pod lease's BILLED settlement is the only GPU cost."""
    return ComfyRenderConfig(price=_gpu_second_price(authorization), lease_covered=True)


def compose_canary_world(
    authorization: CanaryAuthorization,
    *,
    settings: Settings,
    db: Database,
    budget: BudgetService,
    store: ObjectStore,
    clock: Clock,
    ids: Any,
    credential_resolver: Callable[[str], str | None],
    runpod_transport: RunpodTransport | None = None,
    comfy_transport: HttpTransport | None = None,
) -> LiveBenchmarkWorld:
    """The composed world — every live_world gate runs here, no transport call."""
    return build_live_benchmark_world(
        settings,
        db,
        budget,
        store,
        attestation=canary_attestation(authorization),
        evidence=canary_evidence(authorization),
        billing=RunpodInvoiceFinality(db, budget_service=budget),
        runpod_credential_ref=authorization.runpod_credential_ref,
        comfy_credential_ref=authorization.comfy_credential_ref,
        credential_resolver=credential_resolver,
        pod_config=canary_pod_config(authorization),
        render_config=canary_render_config(authorization),
        clock=clock,
        ids=ids,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )


def resolve_canary_episode(db: Database) -> UUID:
    """The canary database's single seeded episode (oldest with a budget account)."""
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT e.id FROM episodes e JOIN budget_accounts a "
            "ON a.episode_id = e.id AND a.scope_kind = 'EPISODE' "
            "ORDER BY e.created_at LIMIT 1"
        )
    if row is None:
        raise NotFound(
            "the canary database has no episode with a budget account; seed it (make canary-db)"
        )
    return row["id"]


def resolve_pinned_template(
    db: Database, settings: Settings, authorization: CanaryAuthorization
) -> WorkflowTemplate:
    """The enabled preset's mapped workflow template behind the node-schema pin."""
    registry = PresetRegistry(db, settings)
    record = registry.get(authorization.pins.preset_id)
    if record is None or not record.enabled:
        raise PolicyDenied("canary preset is missing or disabled in the registry")
    view = PresetCatalog(db, registry).view(record)
    if view is None:
        raise PolicyDenied("canary preset has no exact mapped workflow template")
    return view.template


def node_schema_digest(template: WorkflowTemplate) -> str:
    """The mapped node-class digest (R10 limitation: not a ComfyUI input-schema digest)."""
    return canonical_hash(
        {
            "template_id": template.template_id,
            "template_sha256": template_sha256(template),
            "node_classes": sorted(template.node_classes),
        }
    )


def _refuse_unaffordable(authorization: CanaryAuthorization, prompt_count: int) -> None:
    """T045-FIX B-S2: the computed worst-case holds must fit the authorized spend cap.

    Lease hold + every prompt hold + the quoted storage ceiling + the shutdown
    margin, all integer micro-USD. Refuses before the first reservation is taken, so
    nothing is held and no transport call is made.
    """
    pod = canary_pod_config(authorization)
    render = canary_render_config(authorization)
    assert pod.price is not None and render.price is not None
    lease_hold = pod.price.unit_price_micro_usd * authorization.max_wall_seconds
    prompt_units = -(-render.timeout_ms // 1000)  # ceil, integer ms->s
    prompt_holds = render.price.unit_price_micro_usd * prompt_units * prompt_count
    storage_ceiling = authorization.quote.max_storage_exposure_micro_usd
    shutdown_margin = pod.price.unit_price_micro_usd * (-(-pod.shutdown_margin_ms // 1000))
    total = lease_hold + prompt_holds + storage_ceiling + shutdown_margin
    if total > authorization.caps.max_spend_micro_usd:
        raise PolicyDenied(
            "the computed worst-case holds exceed the authorized spend cap",
            total_micro_usd=total,
            cap_micro_usd=authorization.caps.max_spend_micro_usd,
            lease_hold_micro_usd=lease_hold,
            prompt_holds_micro_usd=prompt_holds,
            storage_ceiling_micro_usd=storage_ceiling,
            shutdown_margin_micro_usd=shutdown_margin,
        )


def _refuse_execute(
    authorization: CanaryAuthorization,
    *,
    expected_sha256: str,
    actual_sha256: str,
    settings: Settings,
    now: datetime,
) -> None:
    """Every pre-world refusal (R11): none of them may reach a transport."""
    if expected_sha256 != actual_sha256:
        raise PolicyDenied("authorization sha256 mismatch; re-run preflight and copy its value")
    if now.tzinfo is None or now.utcoffset() is None:
        raise PolicyDenied("execute needs a timezone-aware clock")
    if now >= authorization.hard_stop_utc:
        raise PolicyDenied("the canary hard stop has passed; nothing may start")
    if now >= authorization.quote.expires_at:
        raise PolicyDenied("the canary quote is expired")
    if settings.execution_mode is not ExecutionMode.PAID_BENCHMARK:
        raise EffectDenied("canary execute requires PAID_BENCHMARK mode")
    settings.require_effect(EffectKind.PAID_REQUEST, what="canary execute")
    settings.require_effect(EffectKind.CLOUD_RESOURCE, what="canary execute")
    if settings.public_actions_enabled:
        raise EffectDenied("a canary can never enable public actions")
    if authorization.caps.max_spend_micro_usd > settings.episode_cap_micro_usd:
        raise PolicyDenied(
            "the canary spend cap exceeds the configured episode cap",
            cap_micro_usd=authorization.caps.max_spend_micro_usd,
            episode_cap_micro_usd=settings.episode_cap_micro_usd,
        )


def load_prompts(
    authorization: CanaryAuthorization, prompts_path: str | Path
) -> list[dict[str, Any]]:
    """Verify every prompt object against its pinned content hash before anything."""
    try:
        prompts = json.loads(Path(prompts_path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaInvalid("the canary prompts file is unreadable JSON") from exc
    if not isinstance(prompts, list) or not prompts:
        raise SchemaInvalid("the canary prompts file must be a non-empty JSON list")
    if len(prompts) > authorization.caps.max_prompts:
        raise PolicyDenied(
            "the prompts file exceeds the authorized prompt cap",
            prompts=len(prompts),
            cap=authorization.caps.max_prompts,
        )
    pinned = set(authorization.prompt_sha256)
    for entry in prompts:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            raise SchemaInvalid("each prompt object needs at least a text field")
        if prompt_pin(entry) not in pinned:
            raise PolicyDenied("a prompt object does not match any pinned content hash; refusing")
    return prompts


def resolve_reference_assets(db: Database, authorization: CanaryAuthorization) -> list[UUID]:
    """Reference pins must name registered, accepted assets — content-addressed."""
    if not authorization.reference_sha256:
        return []
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id, sha256 FROM assets WHERE sha256 = ANY(%s) AND state = 'ACCEPTED'",
            (list(authorization.reference_sha256),),
        )
    found = {row["sha256"]: UUID(str(row["id"])) for row in rows}
    missing = [pin for pin in authorization.reference_sha256 if pin not in found]
    if missing:
        raise PolicyDenied(
            "pinned reference inputs are not registered accepted assets",
            missing=missing,
        )
    return [found[pin] for pin in authorization.reference_sha256]


@dataclass(frozen=True)
class CanaryRunResult:
    record: dict[str, Any]
    record_path: Path


def run_preflight(
    authorization_path: str | Path,
    *,
    settings: Settings,
    db: Database,
    store: ObjectStore,
    clock: Clock | None = None,
    ids: Any = None,
) -> str:
    """Validate the authorization and every live_world gate; print the plan.

    No network, no credential value resolution: the resolver refuses, and the
    composed transports are never called during construction.
    """
    authorization, digest = load_canary_authorization(authorization_path)
    clock = clock or SystemClock()
    world = compose_canary_world(
        authorization,
        settings=settings,
        db=db,
        budget=BudgetService(db, clock, ids or UuidIds(), settings),
        store=store,
        clock=clock,
        ids=ids or UuidIds(),
        credential_resolver=_refusing_resolver,
    )
    lines = [
        "canary preflight OK",
        f"operator: {authorization.operator}",
        f"change_ref: {authorization.change_ref}",
        f"hard_stop_utc: {authorization.hard_stop_utc.isoformat()}",
        f"max_wall_seconds: {authorization.max_wall_seconds}",
        f"quote: {authorization.quote.quote_id} USD "
        f"{authorization.quote.compute_micro_usd_per_hour} micro-USD/hour "
        f"expires {authorization.quote.expires_at.isoformat()}",
        f"caps: spend={authorization.caps.max_spend_micro_usd} micro-USD "
        f"storage_gb={authorization.caps.max_storage_gb} "
        f"prompts={authorization.caps.max_prompts} "
        f"attempts={authorization.caps.max_attempts}",
        f"pins: image={authorization.pins.image_ref} "
        f"workflow={authorization.pins.workflow_sha256} "
        f"node_schema={authorization.pins.node_schema_sha256} "
        f"output_controls={authorization.pins.output_controls_sha256} "
        f"preset={authorization.pins.preset_id} v{authorization.pins.preset_version}",
        f"namespace: {authorization.namespace} account: {authorization.provider_account_ref}",
        f"credrefs: runpod={authorization.runpod_credential_ref} "
        f"comfy={authorization.comfy_credential_ref} (names only; values not resolved)",
        f"prompts pinned: {len(authorization.prompt_sha256)} "
        f"references pinned: {len(authorization.reference_sha256)}",
        f"billing_state: {world.billing_state}",
        f"authorization_sha256={digest}",
    ]
    return "\n".join(lines)


def run_execute(
    authorization_path: str | Path,
    *,
    expected_sha256: str,
    settings: Settings,
    db: Database,
    store: ObjectStore,
    prompts_path: str | Path,
    clock: Clock | None = None,
    ids: Any = None,
    credential_resolver: Callable[[str], str | None] = _refusing_resolver,
    runpod_transport: RunpodTransport | None = None,
    comfy_transport: HttpTransport | None = None,
    evidence_dir: Path | None = None,
    sleep: Callable[[float], None] = lambda _s: None,
) -> CanaryRunResult:
    """Run runbook steps 1-6 through the composed world only (R11).

    Refuses (typed, before any transport call) on a sha mismatch, a passed hard
    stop, an expired quote, a wrong mode/flag or a cap above the episode cap.
    The run itself is bounded by ``min(hard_stop_utc, start + max_wall_seconds)``;
    the deadline and every ambiguity stop and terminate the owned Pod and submit
    nothing further. The janitor is the backstop.
    """
    authorization, digest = load_canary_authorization(authorization_path)
    clock = clock or SystemClock()
    ids = ids or UuidIds()
    started = clock.now()
    _refuse_execute(
        authorization,
        expected_sha256=expected_sha256,
        actual_sha256=digest,
        settings=settings,
        now=started,
    )
    prompts = load_prompts(authorization, prompts_path)
    _refuse_unaffordable(authorization, prompt_count=len(prompts))
    references = resolve_reference_assets(db, authorization)
    episode_id = resolve_canary_episode(db)
    template = resolve_pinned_template(db, settings, authorization)
    preset_record = PresetRegistry(db, settings).get(authorization.pins.preset_id)
    assert preset_record is not None  # resolve_pinned_template refused otherwise

    # T045-FIX B-N3: the rights record's eligible_until bounds the run exactly like
    # the hard stop - the quote's expiry already gates the start.
    deadline = min(
        authorization.hard_stop_utc,
        started + timedelta(seconds=authorization.max_wall_seconds),
        authorization.rights.eligible_until,
    )
    budget = BudgetService(db, clock, ids, settings)
    world = compose_canary_world(
        authorization,
        settings=settings,
        db=db,
        budget=budget,
        store=store,
        clock=clock,
        ids=ids,
        credential_resolver=credential_resolver,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    jobs = JobService(db, clock, ids)
    job_for_key: dict[str, UUID] = {}

    def ensure_job(request: RenderRequest) -> UUID:
        key = (request.semantic_key, request.attempt_number)
        if key not in job_for_key:
            with db.transaction() as tx:
                job = jobs.enqueue(
                    tx,
                    job_type="render.shot",
                    semantic_key=f"{request.semantic_key}:a{request.attempt_number}",
                    payload=request,
                )
            job_for_key[key] = job.job_id
        return job_for_key[key]

    def prompt_semantic_key(index: int) -> str:
        return f"canary:{authorization.change_ref}:{index}"

    prompt_holds: dict[int, UUID] = {}

    def prompt_hold(index: int) -> UUID:
        """One prompt hold per prompt, reserved on first use and reused by retries."""
        if index not in prompt_holds:
            reservation = world.comfy.reserve_attempt(
                episode_id=episode_id, semantic_key=prompt_semantic_key(index)
            )
            prompt_holds[index] = reservation.id
            if str(reservation.id) not in record["reservation_ids"]:
                record["reservation_ids"].append(str(reservation.id))
        return prompt_holds[index]

    def request_for(index: int, prompt: dict[str, Any], attempt_number: int) -> RenderRequest:
        return _render_request(
            authorization,
            preset_record,
            episode_id,
            prompt_hold(index),
            template_sha256(template),
            prompt=prompt,
            attempt_number=attempt_number,
            index=index,
            references=references,
        )

    record: dict[str, Any] = {
        "authorization_sha256": digest,
        "operator": authorization.operator,
        "change_ref": authorization.change_ref,
        "started_at_utc": started.isoformat(),
        "hard_stop_utc": authorization.hard_stop_utc.isoformat(),
        "max_wall_seconds": authorization.max_wall_seconds,
        "deadline_utc": deadline.isoformat(),
        "quote": authorization.quote.model_dump(mode="json"),
        "caps": authorization.caps.model_dump(mode="json"),
        "rights": authorization.rights.model_dump(mode="json"),
        "pins": authorization.pins.model_dump(mode="json"),
        "namespace": authorization.namespace,
        "provider_account_ref": authorization.provider_account_ref,
        "prompt_sha256": authorization.prompt_sha256,
        "reference_sha256": authorization.reference_sha256,
        "episode_id": str(episode_id),
        "steps": [],
        "prompt_ids": [],
        "output_objects": [],
        "provider_operation_ids": [],
        "client_tokens": [],
        "reservation_ids": [],
        "pod_id": None,
        "stop_verified_at": None,
        "terminate_verified_at": None,
        "janitor_summary": None,
        "billing_readiness": None,
        "node_schema_mismatch": False,
        "deadline_hit": False,
        "ambiguous": [],
        "blocked_or_uncertain": "",
    }

    def step(name: str, detail: Any) -> None:
        record["steps"].append({"step": name, "detail": detail})

    lease_id: UUID | None = None
    prompts_done = 0
    attempts_used = 0
    run_error: MicrodramaError | None = None

    def submit_prompt(prompt: dict[str, Any], index: int) -> bool:
        """Bounded submits for one prompt: <= max_attempts, no blind retries.

        Returns True when the prompt produced a SUCCEEDED attempt. Ambiguity
        (NeedsReconciliation) records itself and stops — a human decides.
        """
        nonlocal attempts_used
        attempt_number = 1
        while attempt_number <= authorization.caps.max_attempts:
            if attempts_used >= authorization.caps.max_attempts:
                record["blocked_or_uncertain"] += " attempt cap reached;"
                return False
            request = request_for(index, prompt, attempt_number)
            job_id = ensure_job(request)
            attempts_used += 1
            try:
                status = world.comfy.submit(request, job_id=job_id)
                record["provider_operation_ids"].append(str(status.operation_id))
                if status.prompt_id:
                    record["prompt_ids"].append(status.prompt_id)
                while status.state.value not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    if clock.now() >= deadline:
                        record["deadline_hit"] = True
                        return False
                    sleep(0.05)
                    status = world.comfy.poll(status.operation_id)
            except NeedsReconciliation as exc:
                record["ambiguous"].append(
                    {
                        "prompt_index": index,
                        "attempt": attempt_number,
                        "detail": f"{exc.code}: {exc.message}",
                    }
                )
                record["blocked_or_uncertain"] += " ambiguous submit/poll stopped for a human;"
                return False
            if status.state.value == "SUCCEEDED":
                for asset in status.assets:
                    record["output_objects"].append(
                        {
                            "object_key": asset.object_key,
                            "sha256": asset.sha256,
                            "size_bytes": asset.size_bytes,
                        }
                    )
                step("prompt_succeeded", {"prompt_index": index, "attempt": attempt_number})
                return True
            step(
                "prompt_failed",
                {
                    "prompt_index": index,
                    "attempt": attempt_number,
                    "state": status.state.value,
                    "error": status.error_code,
                },
            )
            if clock.now() >= deadline:
                record["deadline_hit"] = True
                return False
            attempt_number += 1
        return False

    try:
        # Runbook step 1: reserve and create the owned-name Pod.
        handle = world.leases.claim(
            PodLeaseClaimRequest(
                episode_id=episode_id,
                semantic_key=f"canary:{authorization.change_ref}",
                gpu_type=preset_record.gpu_type,
                host_ram_gb=preset_record.host_ram_gb,
                lease_ttl_ms=authorization.max_wall_seconds * 1000,
            )
        )
        lease_id = handle.lease.lease_id
        record["reservation_ids"].append(str(handle.lease.reservation_id))
        record["client_tokens"].append(handle.lease.client_token)
        step("reserve", {"lease_id": str(lease_id)})
        handle = world.leases.ensure_pod(lease_id)
        record["pod_id"] = handle.lease.pod_id
        step("create_pod", {"pod_id": record["pod_id"]})
        # T045-FIX B-B2: the Comfy base URL is late-bound from the created Pod and
        # must be exactly its own proxy URL; anything else refuses before any
        # ComfyUI call (the bearer token never reaches an unvalidated host).
        pod_info = world.manager.get(handle.lease.pod_id)
        world.comfy_client.bind_pod_endpoint(handle.lease.pod_id, pod_info.endpoint_url)
        step("comfy_endpoint_bound", {"endpoint": pod_info.endpoint_url})

        # Runbook step 2 (before the first prompt): the /object_info digest gate.
        # The first prompt's hold and durable job exist before any ComfyUI request.
        first_request = request_for(0, prompts[0], attempt_number=1)
        first_job_id = ensure_job(first_request)
        with world.comfy_client.authorization_scope(
            reservation_id=first_request.reservation_id,
            episode_id=episode_id,
            job_id=first_job_id,
            operation_id=None,
        ):
            catalog = world.comfy_client.object_info()
        missing_classes = [node for node in sorted(template.node_classes) if node not in catalog]
        mapped_digest = node_schema_digest(template)
        if missing_classes or mapped_digest != authorization.pins.node_schema_sha256:
            record["node_schema_mismatch"] = True
            record["blocked_or_uncertain"] = (
                "object_info does not expose the mapped node classes "
                f"(missing: {missing_classes}) or the mapped node-class digest "
                "differs from the pinned node_schema_sha256; nothing was submitted"
            )
            step("object_info_check", {"outcome": "MISMATCH", "missing": missing_classes})
        else:
            step("object_info_check", {"outcome": "MATCH"})

        # Runbook step 3: bounded prompt submits, at most max_prompts/max_attempts.
        if not record["node_schema_mismatch"]:
            for index, prompt in enumerate(prompts):
                if clock.now() >= deadline:
                    record["deadline_hit"] = True
                    break
                if submit_prompt(prompt, index):
                    prompts_done += 1
                if record["deadline_hit"] or record["ambiguous"]:
                    break
            step(
                "prompts",
                {
                    "submitted": prompts_done,
                    "attempts_used": attempts_used,
                    "cap_prompts": authorization.caps.max_prompts,
                    "cap_attempts": authorization.caps.max_attempts,
                },
            )
    except MicrodramaError as exc:
        run_error = exc
        record["blocked_or_uncertain"] += f" run stopped: {exc.code}: {exc.message};"
    finally:
        record["attempts_used"] = attempts_used
        if lease_id is not None:
            # Runpod final release: stop -> terminate -> verified read-back (T045-A).
            shutdown = world.leases.shutdown(lease_id, reason="canary complete")
            record["stop_verified_at"] = (
                shutdown.stop_verified_at.isoformat() if shutdown.stop_verified_at else None
            )
            record["billing_pending"] = shutdown.billing_pending
            step(
                "shutdown",
                {
                    "settled_micro_usd": shutdown.settled_micro_usd,
                    "billing_pending": shutdown.billing_pending,
                },
            )
            with db.transaction(readonly=True) as tx:
                row = tx.fetchone(
                    "SELECT terminate_verified_at FROM pod_leases WHERE id = %s", (lease_id,)
                )
            if row is not None and row["terminate_verified_at"] is not None:
                record["terminate_verified_at"] = row["terminate_verified_at"].isoformat()
        report: JanitorReport = world.janitor.sweep()
        record["janitor_summary"] = {
            "failures": [f.to_dict() for f in report.failures],
            "billing_ingests": [a.to_dict() for a in report.billing_ingests],
            "budget_holds": [a.to_dict() for a in report.budget_holds],
        }
        record["billing_readiness"] = [
            {
                "lease_id": str(r.lease_id),
                "state": r.state,
                "pending_since": r.pending_since.isoformat() if r.pending_since else None,
            }
            for r in world.billing_readiness()
        ]
        record["billing_state"] = world.billing_state
        if not record["blocked_or_uncertain"]:
            record["blocked_or_uncertain"] = (
                "billing is PENDING_PROVIDER_FINALITY until the period invoice is "
                "verified (canary invoice)"
            )

    record_path = _write_canary_record(record, evidence_dir=evidence_dir, now=clock.now())
    if run_error is not None:
        raise run_error
    return CanaryRunResult(record=record, record_path=record_path)


def _render_request(
    authorization: CanaryAuthorization,
    preset_record: Any,
    episode_id: UUID,
    reservation_id: UUID,
    workflow_sha: str,
    *,
    prompt: dict[str, Any],
    attempt_number: int,
    index: int,
    references: list[UUID],
) -> RenderRequest:
    duration_ms = max(1, min(15_000, preset_record.frames * 1000 // max(1, preset_record.fps)))
    semantic_key = f"canary:{authorization.change_ref}:{index}"
    return RenderRequest(
        render_id=render_id_for(semantic_key),
        semantic_key=semantic_key,
        episode_id=episode_id,
        episode_number=1,
        shot_id=f"canary-{index}",
        manifest_version=1,
        attempt_number=attempt_number,
        preset_id=authorization.pins.preset_id,
        tier=preset_record.tier,
        required_controls=[
            ControlKind(control) for control in authorization.pins.required_controls
        ],
        reference_asset_ids=references,
        audio_asset_id=None,
        identity_lock_id=None,
        workflow_sha256=workflow_sha,
        seed=int(prompt.get("seed", 0)),
        width=preset_record.width,
        height=preset_record.height,
        fps=preset_record.fps,
        duration_ms=duration_ms,
        reservation_id=reservation_id,
        prompt_text=prompt["text"],
        negative_prompt_text=str(prompt.get("negative", "")),
    )


def _write_canary_record(
    record: dict[str, Any], *, evidence_dir: Path | None, now: datetime
) -> Path:
    directory = evidence_dir or DEFAULT_EVIDENCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-canary.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def run_invoice(
    *,
    settings: Settings,
    db: Database,
    provider_account_ref: str,
    pod_id: str,
    period_start: datetime,
    period_end: datetime,
    amount_micro_usd: int,
    evidence_path: str | Path,
    source: str,
    observed_at: datetime | None = None,
    supersedes_evidence_id: UUID | None = None,
    actor_ref: str | None = None,
    reason: str | None = None,
) -> str:
    """Wrap verify_invoice_period from operator evidence (R5/R11).

    Only the sha256 of the evidence file is stored — the file itself never enters
    the database or the log.
    """
    import hashlib

    evidence_sha256 = hashlib.sha256(Path(evidence_path).read_bytes()).hexdigest()
    # T045-FIX B-S5: invoice verification runs with a real budget service, so the
    # matched periods write their runpod_billing_budget_finalizations rows.
    repository = RunpodInvoiceFinality(
        db, budget_service=BudgetService(db, SystemClock(), UuidIds(), settings)
    )
    result = repository.verify_invoice_period(
        provider_account_ref=provider_account_ref,
        pod_id=pod_id,
        period_start=period_start,
        period_end=period_end,
        amount_micro_usd=amount_micro_usd,
        currency="USD",
        evidence_sha256=evidence_sha256,
        source=source,
        observed_at=observed_at or datetime.now(UTC),
        supersedes_evidence_id=supersedes_evidence_id,
        actor_ref=actor_ref,
        reason=reason,
    )
    return (
        f"invoice {result.outcome}: period {period_start.isoformat()}.."
        f"{period_end.isoformat()} pod {pod_id} amount {result.amount_micro_usd} "
        f"micro-USD (bucket sum {result.bucket_sum_micro_usd}) "
        f"{'[replayed]' if result.replayed else ''} evidence_sha256={evidence_sha256}"
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaInvalid("timestamps must be timezone-aware ISO-8601")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="microdrama.pipeline.canary")
    parser.add_argument(
        "command",
        nargs="?",
        default="preflight",
        choices=("preflight", "execute", "invoice"),
    )
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--prompts")
    parser.add_argument("--pod-id")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--amount-micro-usd", type=int)
    parser.add_argument("--evidence")
    parser.add_argument("--source", choices=("INVOICE", "CONSOLE"))
    parser.add_argument("--supersedes")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--observed-at")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    # T045-FIX B-N2: the DSN comes from MICRODRAMA_DATABASE_URL only - never from
    # argv (where every process listing would see it) and never printed with a
    # password.
    database_url = settings.database_url
    if not database_url:
        print("canary: MICRODRAMA_DATABASE_URL is required", file=sys.stderr)
        return 2
    store_root = settings.object_store_root or Path("canary-objects")
    store = FilesystemObjectStore(Path(store_root))

    try:
        if args.command == "preflight":
            print(
                run_preflight(
                    args.authorization,
                    settings=settings,
                    db=Database(database_url),
                    store=store,
                )
            )
            return 0
        if args.command == "execute":
            if not args.authorization_sha256 or not args.prompts:
                print(
                    "canary execute requires --authorization-sha256 (from preflight) and --prompts",
                    file=sys.stderr,
                )
                return 2
            result = run_execute(
                args.authorization,
                expected_sha256=args.authorization_sha256,
                settings=settings,
                db=Database(database_url),
                store=store,
                prompts_path=args.prompts,
                credential_resolver=_refusing_resolver,
            )
            print(f"canary execute complete; record: {result.record_path}")
            print(f"billing_state: {result.record.get('billing_state')}")
            return 0
        # invoice
        missing = [
            name
            for name, value in (
                ("--pod-id", args.pod_id),
                ("--period-start", args.period_start),
                ("--period-end", args.period_end),
                # T045-FIX B-S7: only None is missing - a zero amount is the billed-
                # zero period (R5 MATCHED_ZERO) and must reach the verification.
                ("--amount-micro-usd", args.amount_micro_usd),
                ("--evidence", args.evidence),
                ("--source", args.source),
            )
            if value is None
        ]
        if missing:
            print(f"canary invoice requires {', '.join(missing)}", file=sys.stderr)
            return 2
        authorization, _ = load_canary_authorization(args.authorization)
        print(
            run_invoice(
                settings=settings,
                db=Database(database_url),
                provider_account_ref=authorization.provider_account_ref,
                pod_id=args.pod_id,
                period_start=_parse_datetime(args.period_start),
                period_end=_parse_datetime(args.period_end),
                amount_micro_usd=args.amount_micro_usd,
                evidence_path=args.evidence,
                source=args.source,
                observed_at=_parse_datetime(args.observed_at) if args.observed_at else None,
                supersedes_evidence_id=UUID(args.supersedes) if args.supersedes else None,
                actor_ref=args.actor,
                reason=args.reason,
            )
        )
        return 0
    except MicrodramaError as exc:
        print(f"canary {args.command} refused: {exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

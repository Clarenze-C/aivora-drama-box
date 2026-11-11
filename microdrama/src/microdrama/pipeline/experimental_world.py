"""Separate durable experiment coordinator over the canonical rendering services.

Factories supply immutable request/binding inputs; they never supply reservation,
job, operation or experiment state. Provider effects remain in LeaseService and
ComfyRenderService. No live world is constructed implicitly by a local CLI.

World modes (spec §3.1): EXECUTE admits every effect; RECOVERY and CLEANUP are
built from durable records only, run identity checks only (no expiry, rights or
quote-freshness revalidation) and refuse create, upload POST, prompt POST and new
reservations (except the canonical cleanup grant) with EffectDenied at the
composition guard, the request guard and the transport-call guard. Every mode
requires a non-null durable object store. The Comfy client refuses rebinding, so
recovery composes a separate RECOVERY world, with its own client, per acquisition
it touches.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.contracts.cost import BudgetReservationRequest, RenderRequest
from microdrama.contracts.enums import EffectKind, ExecutionMode, PodState
from microdrama.contracts.errors import Conflict, EffectDenied, NeedsReconciliation, PolicyDenied
from microdrama.contracts.v2 import (
    PromptManifest,
    ReferenceRole,
    ShotReferenceBinding,
    validate_current_rights_grant,
)
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.persistence.db import jsonb
from microdrama.pipeline.benchmark_authorization import (
    AcquisitionQuote,
    BenchmarkAuthorization,
    BenchmarkPlan,
    BenchmarkSeal,
    document_sha256,
)
from microdrama.rendering.benchmark_experiments import document, experiment_row
from microdrama.rendering.leases import RENDERING_NAMESPACE, PodLeaseClaimRequest


class CanonicalExperimentWorld:
    """Thin composition: actual jobs, reservations, lease and Comfy services.

    request_factory(sample, acquisition, reservation_id) -> RenderRequest
    binding_factory(sample, acquisition, request) -> BoundWorkflow
    stage_inputs(acquisition) -> None (verified durable receipts, no submit)
    The latter two are the native binder/guarded uploader, not a renderer.
    """

    # HB-11: the world's mode is part of its identity; EXECUTE is the default
    # for directly constructed worlds (the builder overrides it for
    # RECOVERY/CLEANUP, whose boundaries refuse create-path entry).
    _mode = "EXECUTE"

    def __init__(
        self,
        *,
        db: Any,
        jobs: Any,
        leases: Any,
        comfy: Any,
        budget: Any,
        request_factory: Callable,
        binding_factory: Callable | None = None,
        stage_inputs: Callable | None = None,
        billing_readiness: Callable | None = None,
        reconcile_uploads: Callable | None = None,
    ):
        self.db, self.jobs, self.leases, self.comfy, self.budget = db, jobs, leases, comfy, budget
        self.request_factory, self.binding_factory = request_factory, binding_factory
        self.stage_inputs = stage_inputs or (lambda acquisition: None)
        self.reconcile_uploads = reconcile_uploads or (lambda acquisition: None)
        self.billing_readiness = billing_readiness

    def acquisition_requests(
        self, exp: dict, quote: Any, acquisition_id: UUID, generation: int, now: Any
    ) -> dict:
        from microdrama.contracts.cost import ExposureCeilings, PriceQuote
        from microdrama.contracts.enums import (
            BudgetCategory,
            BudgetScopeKind,
            PriceUnit,
            QueueName,
        )

        q = document(quote)
        ttl = int(q["maximum_runtime_ms"])
        price = self.leases._config.price
        if price is None:
            raise Conflict("acquisition compute price is unknown")
        window = ttl + self.leases._config.shutdown_margin_ms
        key = f"benchmark:{exp['experiment_id']}:acq:{generation}"
        claim = {
            "episode_id": str(exp["episode_id"]),
            "semantic_key": key,
            "gpu_type": q["gpu_type"],
            "host_ram_gb": q["host_ram_gb"],
            "lease_ttl_ms": ttl,
        }
        compute = BudgetReservationRequest(
            request_id=uuid5(RENDERING_NAMESPACE, f"claim:{key}"),
            semantic_key=key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=exp["episode_id"],
            season_id=None,
            category=BudgetCategory.GPU_GENERATION,
            queue=QueueName.PRODUCTION,
            job_id=None,
            provider=self.leases._manager.provider_id,
            operation_kind="pod.lease",
            price=price,
            ceilings=ExposureCeilings(timeout_ms=window, max_units=1),
            worst_case_micro_usd=price.unit_price_micro_usd * ((window + 999) // 1000),
            expires_at=now + timedelta(milliseconds=window),
            is_shutdown_or_cleanup=False,
        )
        # A protective financial hold, not a second storage charge. Its provenance
        # is the attested allocation ceiling, never a default zero/mock live price.
        ceiling = q["max_storage_exposure_micro_usd"]
        storage_price = PriceQuote(
            unit=PriceUnit.REQUEST,
            unit_price_micro_usd=ceiling,
            currency="USD",
            source=price.source,
            price_table_version=price.price_table_version,
            as_of=price.as_of,
        )
        storage = BudgetReservationRequest(
            request_id=uuid5(RENDERING_NAMESPACE, f"storage:{key}"),
            semantic_key=f"{key}:storage",
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=exp["episode_id"],
            season_id=None,
            category=BudgetCategory.CPU_STORAGE_TRANSFER,
            queue=QueueName.PRODUCTION,
            job_id=None,
            provider=self.leases._manager.provider_id,
            operation_kind="benchmark.storage_exposure",
            price=storage_price,
            ceilings=ExposureCeilings(timeout_ms=window, max_units=1),
            worst_case_micro_usd=ceiling,
            expires_at=exp["hard_stop"] + timedelta(hours=72),
            is_shutdown_or_cleanup=False,
        )
        return {"claim": claim, "compute": document(compute), "storage": document(storage)}

    def materialize_acquisition(self, acquisition: dict) -> UUID:
        claim = dict(acquisition["intent"]["claim"])
        claim["episode_id"] = UUID(claim["episode_id"])
        reservation_id = UUID(acquisition["intent"]["compute_reservation_id"])
        handle = self.leases.claim_pre_reserved(PodLeaseClaimRequest(**claim), reservation_id)
        return handle.lease.lease_id

    def acquire(self, acquisition: dict) -> Any:
        if self._mode != "EXECUTE":
            # HB-11 (I5): a recovery/cleanup world may only ADOPT an
            # already-bound pod. A podless lease must never ENTER the create
            # path here - the canonical create-intent write would precede any
            # guard refusal and manufacture U1 out of nothing.
            with self.db.transaction(readonly=True) as tx:
                bound_pod = tx.fetchval(
                    "SELECT pod_id FROM pod_leases WHERE id=%s", (acquisition["lease_id"],)
                )
            if bound_pod is None:
                raise EffectDenied(
                    f"{self._mode.lower()} world cannot enter the pod-create path (I5)"
                )
        handle = self.leases.ensure_pod(acquisition["lease_id"])
        # H-1 (2026-11-10, GLM harness review): the live client MUST bind - the
        # hasattr guard hid a signature drift (one-arg call vs the real
        # (pod_id, endpoint_url)) that crashed every default live execution
        # after the paid pod was already created. A client without the method
        # now fails loudly instead of silently skipping the binding that gates
        # every later authenticated call.
        pod = self.leases._manager.get(handle.lease.pod_id)
        if pod is None:
            raise NeedsReconciliation("owned acquired pod disappeared before endpoint binding")
        self.comfy._client.bind_pod_endpoint(pod.pod_id, pod.endpoint_url)
        return handle

    def bind_for_recovery(self, acquisition_id: UUID) -> str:
        """§3.4 recovery binding. BOUND, VERIFIED_SOURCE_GONE or INDETERMINATE.

        Never calls ``ensure_pod``: recovery adopts a durable pod or reports the
        source gone; it never creates, and a manager error stays INDETERMINATE.
        """
        with self.db.transaction(readonly=True) as tx:
            lease_id = tx.fetchval(
                "SELECT lease_id FROM benchmark_acquisitions WHERE acquisition_id=%s",
                (acquisition_id,),
            )
            lease = (
                tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
                if lease_id is not None
                else None
            )
        if lease is not None and lease["pod_id"] is None:
            # A podless lease whose create intent is positively resolved - nothing
            # was ever sent (the durable pre-dispatch record), or the audited
            # no-create resolution exists - has no source left to verify.
            with self.db.transaction(readonly=True) as tx:
                resolved = tx.fetchval(
                    "SELECT 1 FROM runpod_podless_create_resolutions WHERE lease_id=%s",
                    (lease["id"],),
                )
            if lease["create_requested_at"] is None or resolved:
                return "VERIFIED_SOURCE_GONE"
            return "INDETERMINATE"
        if lease is not None and lease["terminate_verified_at"] is not None:
            return "VERIFIED_SOURCE_GONE"
        if lease is not None:
            try:
                pod = self.leases._manager.get(lease["pod_id"])
            except Exception:
                return "INDETERMINATE"
            if pod is None:
                # The owned GET positively reports the pod absent. Only proof of
                # a verified termination makes that absence final.
                if lease["terminate_verified_at"] is not None:
                    return "VERIFIED_SOURCE_GONE"
                return "INDETERMINATE"
            if pod.state is not PodState.RUNNING:
                # §3.4 (HB-2): BOUND requires a RUNNING pod with an endpoint.
                # A stopped/terminated/releasing pod without a verified
                # termination proves nothing about its server - INDETERMINATE.
                return "INDETERMINATE"
            if pod.endpoint_url:
                try:
                    self.comfy._client.bind_pod_endpoint(pod.pod_id, pod.endpoint_url)
                except Exception:
                    return "INDETERMINATE"
                return "BOUND"
            return "INDETERMINATE"
        return "INDETERMINATE"

    def prompt_reservation(self, exp: dict, sample: dict) -> BudgetReservationRequest:
        key = f"benchmark:{exp['experiment_id']}:sample:{sample['sample_id']}:a1"
        return self.comfy._reservation_request(episode_id=exp["episode_id"], semantic_key=key)

    def request(self, sample: dict, acquisition: dict, reservation_id: UUID) -> RenderRequest:
        request = self.request_factory(sample, acquisition, reservation_id)
        key = f"benchmark:{sample['experiment_id']}:sample:{sample['sample_id']}:a1"
        if (
            request.semantic_key != key
            or request.reservation_id != reservation_id
            or request.attempt_number != 1
            or request.seed != sample["seed"]
        ):
            raise Conflict("request factory changed fixed sample identity, seed or hold")
        return request

    def materialize_sample(self, sample: dict) -> UUID:
        request = RenderRequest.model_validate(sample["request"])
        with self.db.transaction() as tx:
            result = self.jobs.enqueue(
                tx,
                job_type="render.shot",
                semantic_key=request.semantic_key,
                payload=request,
                max_attempts=1,
            )
            tx.execute(
                "UPDATE benchmark_samples SET job_id=%s WHERE experiment_id=%s AND sample_id=%s",
                (result.job_id, sample["experiment_id"], sample["sample_id"]),
            )
        self.comfy.adopt_reserved_attempt(request, request.reservation_id)
        return result.job_id

    def submit(
        self,
        sample: dict,
        acquisition: dict,
        *,
        send_authorizer: Any = None,
    ) -> Any:
        request = RenderRequest.model_validate(sample["request"])
        if request.prompt_manifest_id is not None:
            if self.binding_factory is None:
                raise Conflict("native semantic binding factory is required")
            bound = self.binding_factory(sample, acquisition, request)
            return self.comfy.submit_v2(
                request, bound, job_id=sample["job_id"], send_authorizer=send_authorizer
            )
        if self.binding_factory is not None:
            raise Conflict("native semantic binding requires a PromptManifest")
        # Existing actual service path remains available to offline composition
        # tests; the executable preflight only accepts the native sealed profile.
        return self.comfy.submit(request, job_id=sample["job_id"], send_authorizer=send_authorizer)

    def poll(self, sample: dict) -> Any:
        return self.comfy.poll(sample["operation_id"])

    def cleanup(self, acquisition: dict) -> dict:
        self.leases.shutdown(acquisition["lease_id"], reason="benchmark boundary/cleanup")
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        verified = bool(row["terminate_verified_at"])
        ready = self.billing_readiness(acquisition["lease_id"]) if self.billing_readiness else None
        state = getattr(ready, "state", "PENDING_PROVIDER_FINALITY")
        return {
            "verified": verified,
            "compute_window_end": row["compute_window_end_at"],
            "billing_state": state,
            "storage_final": verified and state == "BILLED",
        }


# The executable adapter is deliberately local to this benchmark. Production
# selection continues to require enabled, measured presets in live_world.py.


@dataclass(frozen=True)
class ExperimentalPresetPolicy:
    plan: BenchmarkPlan
    seal: BenchmarkSeal
    authorization: BenchmarkAuthorization

    def validate(self, db, settings, clock, quote):
        from microdrama.core.registry.presets import PresetRegistry
        from microdrama.rendering.pika_transport import mapped_schema_sha256
        from microdrama.rendering.workflows.pika_h3_flex import PikaGraphConfig
        from microdrama.rendering.workflows.templates import PIKA_TEMPLATE, template_sha256

        self.authorization.validate_for(self.plan, self.seal, now=clock.now(), quote=quote)
        profile = self.seal.runtime_profile
        if document_sha256(profile) != self.plan.runtime_profile_sha256:
            raise PolicyDenied("sealed runtime profile differs from prepared hash")
        preset_id = profile.get("preset_id")
        record = PresetRegistry(db, settings).get(preset_id) if preset_id else None
        if (
            record is None
            or record.version != profile.get("preset_version")
            or record.enabled
            or record.measured is not None
            or record.supports_thai_dialogue is not None
        ):
            raise PolicyDenied("experiment requires the exact current disabled, unmeasured preset")
        if (
            record.workflow_sha256 != template_sha256(PIKA_TEMPLATE)
            or profile.get("workflow_sha256") != record.workflow_sha256
            or profile.get("configuration_sha256") != PikaGraphConfig().sha256
        ):
            raise PolicyDenied("experimental workflow/configuration pin differs")
        if (record.width, record.height, record.frames, record.fps) != (
            self.seal.width,
            self.seal.height,
            self.seal.frames,
            self.seal.fps,
        ):
            raise PolicyDenied("experimental preset pixel/frame grid differs")
        if (
            record.gpu_type not in self.authorization.allowed_gpu_types
            or record.host_ram_gb > quote.host_ram_gb
        ):
            raise PolicyDenied("experimental preset hardware differs from acquisition quote")
        if (
            mapped_schema_sha256(self.seal.raw_object_info, PIKA_TEMPLATE.node_classes)
            != self.seal.node_schema_sha256
        ):
            raise PolicyDenied("sealed actual runtime schema hash differs")
        _validate_model_rights(db, settings, clock, profile, record, self.seal.territories)
        _validated_sources(db, settings, clock, self.plan, self.seal)
        return record


def _validate_model_rights(db, settings, clock, profile, record, territories):
    """Reference licenses never substitute for current model-output rights."""
    from microdrama.contracts.enums import RightsSubjectKind
    from microdrama.contracts.hashing import canonical_hash
    from microdrama.core.registry.rights import RightsRegistry

    subject = profile.get("model_rights_subject_ref")
    version = profile.get("model_rights_version")
    evidence_hash = profile.get("model_rights_evidence_sha256")
    if (
        not record.rights_route_id
        or not isinstance(subject, str)
        or not subject
        or profile.get("model_rights_subject_kind") != "MODEL_OUTPUT"
        or type(version) is not int
        or version < 1
        or not isinstance(evidence_hash, str)
        or len(evidence_hash) != 64
    ):
        raise PolicyDenied("current model-output rights pins are required before benchmark effects")
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT version,payload FROM rights_registry WHERE rights_route_id=%s "
            "AND subject_kind=%s AND subject_ref=%s AND current",
            (record.rights_route_id, RightsSubjectKind.MODEL_OUTPUT.value, subject),
        )
    if row is None or row["version"] != version or canonical_hash(row["payload"]) != evidence_hash:
        raise PolicyDenied("model-output rights evidence/version differs from sealed profile")
    decision = RightsRegistry(db, clock, settings).evaluate(
        rights_route_id=record.rights_route_id,
        subjects=[(RightsSubjectKind.MODEL_OUTPUT, subject)],
        territories=territories,
        at=clock.now(),
    )
    if not decision.eligible:
        raise PolicyDenied("model-output rights are not eligible for benchmark access")


def _rights_resolver(db, settings, clock, territories):
    from microdrama.contracts.registries import RightsRecord
    from microdrama.core.registry.rights import RightsRegistry, _ensure_intact

    def resolve(route, kind, subject):
        decision = RightsRegistry(db, clock, settings).evaluate(
            rights_route_id=route,
            subjects=[(kind, subject)],
            territories=territories,
            at=clock.now(),
        )
        if not decision.eligible:
            raise PolicyDenied(
                "current sealed reference rights are not eligible", blockers=decision.blockers
            )
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM rights_registry WHERE rights_route_id=%s AND subject_kind=%s AND subject_ref=%s AND current",
                (route, kind.value, subject),
            )
        if row is None:
            return None
        _ensure_intact(row, name=f"{route}:{subject}")
        return RightsRecord(
            record_id=row["id"],
            rights_route_id=route,
            version=row["version"],
            subject_kind=kind,
            subject_ref=subject,
            territories=row["territories"],
            commercial_use=row["commercial_use"],
            output_release_allowed=row["output_release_allowed"],
            required_disclosures=row["required_disclosures"],
            expires_at=row["expires_at"],
            evidence=row["evidence"],
            status=row["status"],
            recorded_at=row["created_at"],
        )

    return resolve


def _validated_sources(db, settings, clock, plan, seal, *, shot_id=None):
    """Sealed semantic roles resolve to exact current private canonical assets/rights."""
    resolver = _rights_resolver(db, settings, clock, seal.territories)
    bindings = []
    assets = {}
    with db.transaction(readonly=True) as tx:
        episode = tx.fetchone(
            "SELECT season_id, episode_number, identity_lock_id FROM episodes WHERE id=%s",
            (plan.episode_id,),
        )
        for source in seal.references:
            # A sealed reference is the typed binding itself. Its content hash,
            # validity and grant are verified by the existing V2 model.
            binding = ShotReferenceBinding.model_validate(source)
            asset = tx.fetchone("SELECT * FROM assets WHERE id=%s", (binding.asset_id,))
            if (
                episode is None
                or asset is None
                or asset["version"] != binding.asset_version
                or asset["sha256"] != binding.asset_sha256
                or asset["state"] not in {"ACCEPTED", "LOCKED"}
                or asset["provenance"] == "FAKE_SYNTHETIC"
                or (
                    asset["episode_id"] != plan.episode_id
                    and (
                        asset["episode_id"] is not None
                        or asset["season_id"] != episode["season_id"]
                    )
                )
            ):
                raise PolicyDenied(
                    "sealed reference is not the exact current owned canonical asset"
                )
            kind = "AUDIO" if binding.role is ReferenceRole.VOICE else "IMAGE"
            if asset["asset_kind"] != kind or asset["media_type"] != (
                "audio/wav" if kind == "AUDIO" else "image/png"
            ):
                raise PolicyDenied("sealed reference requires exact PNG/WAV canonical media")
            bindings.append(binding)
            assets[binding.asset_id] = asset
    for binding in bindings:
        if binding.valid_from > clock.now() or (
            binding.valid_until and clock.now() >= binding.valid_until
        ):
            raise PolicyDenied("sealed reference is not current")
        validate_current_rights_grant(
            binding.rights, resolver, at=clock.now(), territories=seal.territories
        )
    rights_hash = document_sha256(
        {
            "rights": [b.rights.model_dump(mode="json") for b in bindings],
            "territories": seal.territories,
        }
    )
    if rights_hash != seal.rights_evidence_hash:
        raise PolicyDenied("sealed reference rights evidence hash differs")
    reference_keys = {
        (b.role.value, b.subject_id, str(b.asset_id), b.asset_version, b.asset_sha256)
        for b in bindings
    }
    mapped_keys = {
        (p["role"], p["subject_id"], str(p["asset_id"]), p["asset_version"], p["asset_sha256"])
        for p in seal.port_map
    }
    if mapped_keys != reference_keys:
        raise PolicyDenied("explicit ports do not cover exact sealed semantic assets")
    selected = [p for p in seal.port_map if shot_id is None or p.get("shot_id") in (None, shot_id)]
    selected_keys = {
        (p["role"], p["subject_id"], str(p["asset_id"]), p["asset_version"], p["asset_sha256"])
        for p in selected
    }
    if shot_id is not None and not selected:
        raise PolicyDenied("sealed port map has no references for this shot")
    bindings = [
        b
        for b in bindings
        if (b.role.value, b.subject_id, str(b.asset_id), b.asset_version, b.asset_sha256)
        in selected_keys
    ]
    assets = {b.asset_id: assets[b.asset_id] for b in bindings}
    return tuple(bindings), assets, resolver, episode


class _SealedNativeInputs:
    def __init__(self, db, settings, store, clock, plan, seal, policy, quote, client, mode):
        self.db, self.settings, self.store, self.clock = db, settings, store, clock
        self.plan, self.seal, self.policy, self.quote, self.client = (
            plan,
            seal,
            policy,
            quote,
            client,
        )
        self.mode = mode

    def current(self):
        if self.mode != "EXECUTE":
            raise EffectDenied(f"{self.mode.lower()} experiment world cannot admit new work")
        return self.policy.validate(self.db, self.settings, self.clock, self.quote)

    def manifest(self, sample):
        self.current()
        bindings, assets, resolver, episode = _validated_sources(
            self.db,
            self.settings,
            self.clock,
            self.plan,
            self.seal,
            shot_id=sample["shot_id"],
        )
        shot = next((s for s in self.plan.shots if s["shot_id"] == sample["shot_id"]), None)
        if shot is None:
            raise Conflict("sample has no fixed logical shot")
        # The native prompt explicitly retains the frozen Thai line and speaker
        # identities. It cannot infer a speaker from anchor list position.
        speakers = shot.get("speaker_subject_ids")
        voices = {b.subject_id for b in bindings if b.role is ReferenceRole.VOICE}
        if (
            not isinstance(speakers, list)
            or not speakers
            or set(speakers) != voices
            or len(speakers) != len(set(speakers))
        ):
            raise PolicyDenied(
                "logical shot requires explicit speaker subjects matching voice anchors"
            )
        english = shot.get("english_prompt")
        if not isinstance(english, str) or not english.strip():
            raise PolicyDenied("logical shot requires its exact English visual prompt")
        prompt = (
            english + "\nSpeakers: " + ", ".join(speakers) + "\nThai dialogue: " + shot["thai_line"]
        )
        # All IDs/timestamps derive from frozen inputs, never the resume clock.
        instant = max(b.valid_from for b in bindings)
        manifest = PromptManifest.seal(
            record_id=uuid5(
                RENDERING_NAMESPACE,
                f"benchmark:{self.plan.experiment_id}:manifest:{sample['sample_id']}",
            ),
            version=1,
            created_at=instant,
            updated_at=instant,
            valid_from=instant,
            valid_until=self.seal.eligible_until,
            episode_id=self.plan.episode_id,
            shot_id=f"bench-{sample['sample_id'].lower()}",
            shot_sequence=(int(sample["shot_id"][1:]) - 1) * 3 + sample["repeat"],
            shot_duration_ms=(self.seal.frames * 1000 + self.seal.fps - 1) // self.seal.fps,
            prompt_text=prompt,
            bindings=list(bindings),
            source_hashes=sorted(
                {
                    self.plan.plan_sha256,
                    self.seal.sealed_sha256,
                    *[b.asset_sha256 for b in bindings],
                }
            ),
        )
        # The manifest is a durable V2 contract document: ``submit_v2`` loads
        # and verifies it from the ledger, so persist it here, idempotently by
        # record id - the manifest derives entirely from frozen inputs, so a
        # replay rebuilds the identical payload (I6) and only the first build
        # writes the row.
        from microdrama.contracts.hashing import canonical_hash

        with self.db.transaction() as tx:
            existing = tx.fetchone(
                "SELECT 1 FROM v2_contract_documents "
                "WHERE contract_type = 'PromptManifest' AND record_id = %s AND current",
                (manifest.record_id,),
            )
            if existing is None:
                rights = manifest.bindings[0].rights if manifest.bindings else None
                tx.execute(
                    "INSERT INTO v2_contract_documents "
                    "(contract_type, record_id, version, payload, payload_sha256, "
                    "rights_route_id, rights_version, valid_from, valid_until, current) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)",
                    (
                        "PromptManifest",
                        manifest.record_id,
                        manifest.version,
                        jsonb(manifest.model_dump(mode="json")),
                        canonical_hash(manifest),
                        rights.rights_route_id if rights is not None else None,
                        rights.rights_version if rights is not None else None,
                        manifest.valid_from,
                        manifest.valid_until,
                    ),
                )
        return manifest, assets, resolver, episode

    def request(self, sample, acquisition, reservation_id):
        from microdrama.contracts.enums import ControlKind
        from microdrama.rendering.workflows.templates import (
            PIKA_TEMPLATE,
            semantic_template_sha256,
            template_sha256,
        )
        from microdrama.rendering.workflows.v2_binding import ROLE_CONTROL

        manifest, _, _, episode = self.manifest(sample)
        record = self.current()
        controls = {ControlKind.TEXT_PROMPT, ControlKind.SEED}
        controls.update(ROLE_CONTROL[b.role] for b in manifest.bindings if b.role in ROLE_CONTROL)
        if not controls.issubset(record.supported_controls):
            raise PolicyDenied(
                "experimental preset does not declare every required semantic control"
            )
        key = f"benchmark:{self.plan.experiment_id}:sample:{sample['sample_id']}:a1"
        return RenderRequest(
            render_id=uuid5(RENDERING_NAMESPACE, f"render:{key}"),
            semantic_key=key,
            episode_id=self.plan.episode_id,
            episode_number=episode["episode_number"],
            shot_id=f"bench-{sample['sample_id'].lower()}",
            manifest_version=1,
            attempt_number=1,
            preset_id=record.preset_id,
            tier=record.tier,
            required_controls=sorted(controls, key=lambda c: c.value),
            reference_asset_ids=list(dict.fromkeys(b.asset_id for b in manifest.bindings)),
            identity_lock_id=episode["identity_lock_id"],
            workflow_sha256=template_sha256(PIKA_TEMPLATE),
            seed=sample["seed"],
            width=self.seal.width,
            height=self.seal.height,
            fps=self.seal.fps,
            duration_ms=manifest.shot_duration_ms,
            reservation_id=reservation_id,
            prompt_manifest_id=manifest.record_id,
            prompt_manifest_sha256=manifest.content_sha256,
            semantic_workflow_sha256=semantic_template_sha256(PIKA_TEMPLATE),
            prompt_text=manifest.prompt_text,
        )

    def _scope(self, acquisition):
        with self.db.transaction(readonly=True) as tx:
            sample = tx.fetchone(
                "SELECT s.* FROM benchmark_dispatch_slots d JOIN benchmark_samples s ON s.experiment_id=d.experiment_id AND s.sample_id=d.sample_id WHERE d.experiment_id=%s AND s.acquisition_id=%s",
                (self.plan.experiment_id, acquisition["acquisition_id"]),
            )
        if sample is None or sample["job_id"] is None or sample["reservation_id"] is None:
            raise EffectDenied("native staging requires the current canonical sample job/hold")
        return self.client.authorization_scope(
            reservation_id=sample["reservation_id"],
            episode_id=self.plan.episode_id,
            job_id=sample["job_id"],
            operation_id=sample["operation_id"],
        )

    def stage(self, acquisition):
        from microdrama.rendering.pika_transport import upload_key_for, validate_input_bytes

        self.current()
        bindings, assets, _, _ = _validated_sources(
            self.db, self.settings, self.clock, self.plan, self.seal
        )
        by_key = {
            (b.role.value, b.subject_id, str(b.asset_id), b.asset_version, b.asset_sha256): b
            for b in bindings
        }
        with self._scope(acquisition):
            self.client.attest_schema()
            for port in self.seal.port_map:
                binding = by_key[
                    (
                        port["role"],
                        port["subject_id"],
                        str(port["asset_id"]),
                        port["asset_version"],
                        port["asset_sha256"],
                    )
                ]
                kind = port["media_kind"]
                digest = binding.asset_sha256
                key = upload_key_for(
                    self.plan.experiment_id, acquisition["acquisition_id"], digest, kind
                )
                identity = (
                    acquisition["acquisition_id"],
                    digest,
                    kind,
                    binding.role.value,
                    binding.subject_id,
                )
                with self.db.transaction() as tx:
                    # R5 (§6.1): upload-intent insertion serialises through the
                    # locked acquisition ownership row, so a gate's query for
                    # an absent intent cannot race this row into existence.
                    tx.fetchone(
                        "SELECT acquisition_id FROM benchmark_acquisitions "
                        "WHERE acquisition_id=%s FOR UPDATE",
                        (acquisition["acquisition_id"],),
                    )
                    row = tx.fetchone(
                        "SELECT * FROM benchmark_uploads WHERE acquisition_id=%s AND asset_sha256=%s AND media_kind=%s AND role=%s AND subject_id=%s",
                        identity,
                    )
                    if row is None:
                        tx.execute(
                            "INSERT INTO benchmark_uploads(acquisition_id,asset_sha256,media_kind,role,subject_id,destination_slot,upload_key,state) VALUES(%s,%s,%s,%s,%s,%s,%s,'INTENT')",
                            (*identity, port["destination_slot"], key),
                        )
                if row is not None:
                    # INTENT itself may have crossed the network before a crash.
                    # Any durable prior intent is reconciliation-only, never POST.
                    self.client.reconcile_input(expected_sha256=digest, upload_key=key)
                else:
                    data = self.store.get_bytes(assets[binding.asset_id]["object_key"])
                    validate_input_bytes(data, kind, digest)
                    # Mark UNKNOWN before POST. A timeout/crash cannot repeat it.
                    with self.db.transaction() as tx:
                        tx.fetchone(
                            "SELECT acquisition_id FROM benchmark_acquisitions "
                            "WHERE acquisition_id=%s FOR UPDATE",
                            (acquisition["acquisition_id"],),
                        )
                        tx.execute(
                            "UPDATE benchmark_uploads SET state='UNKNOWN' WHERE acquisition_id=%s AND asset_sha256=%s AND media_kind=%s AND role=%s AND subject_id=%s",
                            identity,
                        )
                    self.client.upload_input(data, kind, digest, key)
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE benchmark_uploads SET state='VERIFIED',locator=%s,verified_readback_sha256=%s WHERE acquisition_id=%s AND asset_sha256=%s AND media_kind=%s AND role=%s AND subject_id=%s",
                        (jsonb({"locator": key}), digest, *identity),
                    )

    def readback(self, acquisition):
        """§5.3: existing upload intents reconcile ONLY by checksum readback.

        One GET ``/view?type=input`` per open intent (``INTENT``/``UNKNOWN``)
        through the real client scope: verified exact bytes mark the intent
        done. Nothing else may happen here - no POST (the request guard
        refuses it outside EXECUTE at its own layer), no intent is invented
        for a port without a durable row, and no prompt operation appears.
        The scope is the acquisition's current dispatched sample, exactly the
        one staging used, so the readback proves the same linkage the upload
        intent committed (§3.3/R4).
        """
        with self.db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT asset_sha256,media_kind,role,subject_id,upload_key "
                "FROM benchmark_uploads WHERE acquisition_id=%s "
                "AND state IN ('INTENT','UNKNOWN') "
                "ORDER BY asset_sha256,media_kind,role,subject_id",
                (acquisition["acquisition_id"],),
            )
        if not rows:
            return
        with self._scope(acquisition):
            for row in rows:
                self.client.reconcile_input(
                    expected_sha256=row["asset_sha256"], upload_key=row["upload_key"]
                )
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE benchmark_uploads SET state='VERIFIED',locator=%s,"
                        "verified_readback_sha256=%s WHERE acquisition_id=%s "
                        "AND asset_sha256=%s AND media_kind=%s AND role=%s AND subject_id=%s",
                        (
                            jsonb({"locator": row["upload_key"]}),
                            row["asset_sha256"],
                            acquisition["acquisition_id"],
                            row["asset_sha256"],
                            row["media_kind"],
                            row["role"],
                            row["subject_id"],
                        ),
                    )

    def bind(self, sample, acquisition, request):
        from microdrama.references.v2_binding import ExpectedReference
        from microdrama.rendering.workflows.pika_h3_flex import (
            PikaBindingContext,
            PikaPortMap,
            PikaUploadReceipt,
        )
        from microdrama.rendering.workflows.templates import PIKA_TEMPLATE
        from microdrama.rendering.workflows.v2_binding import bind_v2_workflow

        manifest, _, resolver, _ = self.manifest(sample)
        with self._scope(acquisition):
            raw = self.client.attest_schema()
        with self.db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT * FROM benchmark_uploads WHERE acquisition_id=%s",
                (acquisition["acquisition_id"],),
            )
            lease = tx.fetchone(
                "SELECT pod_id FROM pod_leases WHERE id=%s", (acquisition["lease_id"],)
            )
        # L-2 (GLM Luna review): the upload lookup keys the FULL slot identity
        # stage uses (role, subject, asset bytes, media kind) - the same
        # (role, subject) may legitimately bind different assets in different
        # shots (a same-subject costume change), and a collapsed lookup bound
        # the wrong receipt after pod acquisition.
        by_key = {(r["role"], r["subject_id"], r["asset_sha256"], r["media_kind"]): r for r in rows}
        staged = []
        for item in self.seal.port_map:
            if item.get("shot_id") not in (None, sample["shot_id"]):
                continue
            port = PikaPortMap(
                role=ReferenceRole(item["role"]),
                subject_id=item["subject_id"],
                asset_id=UUID(item["asset_id"]),
                asset_version=item["asset_version"],
                asset_sha256=item["asset_sha256"],
                media_kind=item["media_kind"],
                destination_slot=item["destination_slot"],
            )
            row = by_key.get((port.role.value, port.subject_id, port.asset_sha256, port.media_kind))
            if row is None or row["state"] != "VERIFIED":
                raise NeedsReconciliation("native prompt has unverified acquisition input")
            staged.append(
                (
                    port,
                    PikaUploadReceipt(
                        experiment_id=self.plan.experiment_id,
                        acquisition_id=acquisition["acquisition_id"],
                        pod_id=lease["pod_id"],
                        asset_sha256=row["asset_sha256"],
                        media_kind=row["media_kind"],
                        role=port.role,
                        subject_id=port.subject_id,
                        # The durable source upload is acquisition-scoped; the exact
                        # destination is shot-scoped and comes from the immutable seal.
                        destination_slot=port.destination_slot,
                        upload_key=row["upload_key"],
                        locator=row["locator"]["locator"],
                        state=row["state"],
                        verified_readback_sha256=row["verified_readback_sha256"],
                    ),
                )
            )

        # L-1 (GLM Luna review): the binder counts per-media-kind ordinals in
        # list order while the seal validator only requires the per-shot
        # destination SET to be contiguous - present the shot's ports per media
        # kind in destination-ordinal order so every validator-legal seal binds.
        def _destination_ordinal(pair):
            port = pair[0]
            return (
                0 if port.role is ReferenceRole.VOICE else 1,
                int(port.destination_slot.rsplit("_", 1)[1]),
            )

        staged.sort(key=_destination_ordinal)
        ports = [port for port, _ in staged]
        uploads = [receipt for _, receipt in staged]
        context = PikaBindingContext(
            experiment_id=self.plan.experiment_id,
            acquisition_id=acquisition["acquisition_id"],
            pod_id=lease["pod_id"],
            ports=tuple(ports),
            uploads=tuple(uploads),
            expected_references={
                (b.role, b.subject_id): ExpectedReference(
                    b.asset_id,
                    b.asset_version,
                    b.asset_sha256,
                    b.rights,
                    b.valid_from,
                    b.valid_until,
                )
                for b in manifest.bindings
            },
            resolve_current_rights=resolver,
            at=self.clock.now(),
            territories=tuple(self.seal.territories),
            raw_object_info=raw,
            expected_schema_sha256=self.seal.node_schema_sha256,
            schema_evidence="LIVE",
        )
        return bind_v2_workflow(PIKA_TEMPLATE, request, manifest, pika_context=context)


# --- recovery provenance and the EXPIRED recovery-read exception (spec §3.2/§3.3) ---


def load_recovery_authorization(db: Any, acquisition_id: UUID) -> BenchmarkAuthorization:
    """§3.2: load THIS acquisition's authorization row and verify it from its bytes.

    The acquisition's recorded ``authorization_sha256`` selects the row - never
    "latest by timestamp". The stored bytes must hash to that SHA and parse to
    the stored payload; anything else refuses and requires the original file.
    """
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT z.authorization_sha256, z.payload, z.source_bytes "
            "FROM benchmark_acquisitions a JOIN benchmark_authorizations z "
            "ON z.experiment_id=a.experiment_id "
            "AND z.authorization_sha256=a.authorization_sha256 "
            "WHERE a.acquisition_id=%s",
            (acquisition_id,),
        )
    if row is None or row["source_bytes"] is None:
        raise Conflict(
            "recovery requires the acquisition's original authorization "
            "(--authorization with matching byte SHA); no durable provenance row"
        )
    if hashlib.sha256(bytes(row["source_bytes"])).hexdigest() != row["authorization_sha256"]:
        raise Conflict("stored authorization bytes do not hash to the recorded byte SHA")
    try:
        parsed = json.loads(bytes(row["source_bytes"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Conflict("stored authorization bytes are not the original JSON document") from None
    if parsed != row["payload"]:
        raise Conflict("parsing the stored authorization bytes differs from the stored payload")
    return BenchmarkAuthorization.model_validate(parsed)


def load_recovery_quote(db: Any, acquisition_id: UUID) -> Any:
    """§3.2: this acquisition's own recorded quote, never the latest generation."""
    with db.transaction(readonly=True) as tx:
        quote = tx.fetchval(
            "SELECT quote FROM benchmark_acquisitions WHERE acquisition_id=%s",
            (acquisition_id,),
        )
    if quote is None:
        raise Conflict("the acquisition has no durable quote to recover with")
    return AcquisitionQuote.model_validate(quote)


def expired_recovery_read_allowed(
    db: Any,
    experiment_id: UUID,
    mode: str,
    path: str,
    authorization_key: str | None,
    auth: Any,
) -> bool:
    """§3.3 + R4: benchmark RECOVERY may read through an EXPIRED-but-retained hold.

    Authorises ONLY scoped recovery GETs (``/queue``, ``/history``, ``/view``)
    and output persistence on that basis - never operation creation, pod
    creation, upload POST or prompt POST (callers still refuse those for this
    mode before reaching here). The linkage proved depends on the read:
    output/history recovery proves the exact experiment, acquisition,
    reservation, job, operation and pod linkage; a checksum input readback
    before any prompt operation exists proves the experiment, acquisition,
    reservation, job, pod and durable upload-intent linkage instead.
    """
    if mode != "RECOVERY":
        return False
    if not (path == "/queue" or path.startswith("/history") or path.startswith("/view")):
        return False
    with db.transaction(readonly=True) as tx:
        if auth.operation_id is not None:
            row = tx.fetchone(
                "SELECT r.state AS reservation_state FROM provider_operations o "
                "JOIN reservations r ON r.id=o.reservation_id "
                "JOIN benchmark_reservation_links k ON k.reservation_id=o.reservation_id "
                "AND k.experiment_id=%s AND k.purpose='PROMPT' "
                "JOIN benchmark_samples s ON s.experiment_id=k.experiment_id "
                "AND s.sample_id=k.sample_id AND s.reservation_id=o.reservation_id "
                "AND s.job_id=o.job_id "
                "JOIN benchmark_acquisitions a ON a.acquisition_id=s.acquisition_id "
                "JOIN pod_leases l ON l.id=a.lease_id "
                "WHERE o.id=%s AND o.job_id=%s AND o.reservation_id=%s "
                "AND l.pod_id IS NOT NULL",
                (experiment_id, auth.operation_id, auth.job_id, auth.reservation_id),
            )
        elif path.startswith("/view") and authorization_key is not None:
            # Checksum input readback before a prompt operation exists.
            row = tx.fetchone(
                "SELECT r.state AS reservation_state "
                "FROM benchmark_reservation_links k "
                "JOIN reservations r ON r.id=k.reservation_id "
                "JOIN benchmark_samples s ON s.experiment_id=k.experiment_id "
                "AND s.sample_id=k.sample_id AND s.reservation_id=k.reservation_id "
                "AND s.job_id=%s "
                "JOIN benchmark_acquisitions a ON a.acquisition_id=s.acquisition_id "
                "JOIN pod_leases l ON l.id=a.lease_id "
                "JOIN benchmark_uploads u ON u.acquisition_id=a.acquisition_id "
                "AND u.upload_key=%s "
                "WHERE k.experiment_id=%s AND k.reservation_id=%s "
                "AND k.purpose='PROMPT' AND l.pod_id IS NOT NULL",
                (auth.job_id, authorization_key, experiment_id, auth.reservation_id),
            )
        else:
            return False
    # Exposure retained: EXPIRED (the canonical expired-accrual state), never
    # settled or released.
    return row is not None and row["reservation_state"] == "EXPIRED"


def build_experiment_world(
    settings,
    db,
    budget,
    store,
    *,
    experiment_id,
    authorization=None,
    quote=None,
    mode="EXECUTE",
    acquisition_id=None,
    clock=None,
    ids=None,
    runpod_transport=None,
    comfy_transport=None,
):
    """Compose canonical services without resolving credentials or doing HTTP.

    ``mode`` is EXECUTE, RECOVERY or CLEANUP (spec §3.1). EXECUTE uses only the
    narrow disabled-preset policy and may cause every effect. RECOVERY and
    CLEANUP are built from durable records only (per acquisition when
    ``acquisition_id`` names one), run identity checks only, and refuse create,
    upload POST, prompt POST and new reservations at every guard layer. Every
    mode requires a non-null durable object store.
    """
    from microdrama.budget.billing import lease_billing_readiness
    from microdrama.contracts.cost import PriceQuote
    from microdrama.contracts.enums import PriceSource, PriceUnit
    from microdrama.core.jobs import JobService
    from microdrama.pipeline.canary import _canary_credential_resolver
    from microdrama.pipeline.live_world import durable_comfy_request_guard
    from microdrama.rendering.benchmark_experiments import decode_seal
    from microdrama.rendering.comfy_jobs import ComfyRenderConfig, build_comfy_render_service
    from microdrama.rendering.finality import RunpodInvoiceFinality
    from microdrama.rendering.leases import (
        PodLeaseConfig,
        build_lease_service,
        durable_created_pod_recorder,
    )
    from microdrama.rendering.pika_transport import PikaHttpClient
    from microdrama.rendering.pods import PodManager
    from microdrama.rendering.runpod_billing import durable_pod_ownership_probe
    from microdrama.rendering.runpod_transport import RunpodQuoteAttestation, RunpodRestProvider

    if mode not in ("EXECUTE", "RECOVERY", "CLEANUP"):
        raise Conflict(f"unknown experiment world mode: {mode}")
    if store is None:
        raise EffectDenied("every experiment world mode requires a non-null durable object store")
    live_clock, live_ids = clock or SystemClock(), ids or UuidIds()
    with db.transaction(readonly=True) as tx:
        exp = experiment_row(tx, experiment_id)
        sealed = decode_seal(
            tx.fetchone("SELECT * FROM benchmark_seals WHERE experiment_id=%s", (experiment_id,))
        )
        if mode != "EXECUTE":
            # HB-3 (§3.2): recovery/cleanup provenance is the ACQUISITION'S OWN
            # durable record, verified from its stored bytes. Caller-supplied
            # new-generation documents never replace it, and "latest by
            # timestamp" is never selected: an experiment with acquisitions
            # must name the acquisition being touched. (An acquisition-less
            # experiment composes no recovery world at all - its status,
            # reconciliation and cleanup are no-effect operations.)
            if acquisition_id is not None:
                authorization = load_recovery_authorization(db, acquisition_id)
                quote = load_recovery_quote(db, acquisition_id)
            elif tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s",
                (experiment_id,),
            ):
                raise Conflict(
                    "recovery and cleanup must name the acquisition whose durable "
                    "records they recover (never latest-by-timestamp)"
                )
    if sealed is None or authorization is None or quote is None:
        raise PolicyDenied(
            "experiment world needs a durable seal, recorded authorization and acquisition quote"
        )
    plan = BenchmarkPlan.model_validate(exp["plan"])
    seal = BenchmarkSeal.model_validate(sealed["manifest"])
    if not isinstance(authorization, BenchmarkAuthorization):
        authorization = BenchmarkAuthorization.model_validate(authorization)
    if not isinstance(quote, AcquisitionQuote):
        quote = AcquisitionQuote.model_validate(quote)
    # These identity checks never expire. Cleanup must still prove which account,
    # immutable experiment and isolated namespace it is allowed to act for.
    if (
        authorization.experiment_id != experiment_id
        or plan.experiment_id != experiment_id
        or authorization.episode_id != plan.episode_id
        or authorization.plan_sha256 != plan.plan_sha256
        or authorization.sealed_sha256 != seal.sealed_sha256
    ):
        raise PolicyDenied(
            "experiment world authorization identity differs from durable seal/account"
        )
    if (
        settings.execution_mode is not ExecutionMode.PAID_BENCHMARK
        or settings.public_actions_enabled
    ):
        raise EffectDenied("experiment world requires private PAID_BENCHMARK settings")
    # Cleanup retains its cloud effect gate; expiry only removes admission.
    settings.require_effect(EffectKind.CLOUD_RESOURCE, what="experiment resource composition")
    if mode == "EXECUTE":
        settings.require_effect(EffectKind.PAID_REQUEST, what="experiment generation composition")
    policy = ExperimentalPresetPolicy(plan, seal, authorization)
    if mode == "EXECUTE":
        policy.validate(db, settings, live_clock, quote)
    hourly = quote.compute_micro_usd_per_hour
    price = PriceQuote(
        currency="USD",
        unit=PriceUnit.GPU_SECOND,
        unit_price_micro_usd=hourly // 3600,
        source=PriceSource.PROVIDER_QUOTE,
        price_table_version=f"benchmark:{quote.quote_id}",
        as_of=quote.captured_at,
    )
    attestation = RunpodQuoteAttestation(
        namespace=authorization.namespace,
        quote_id=quote.quote_id,
        currency="USD",
        provider_account_ref=authorization.provider_account_ref,
        quote_micro_usd_per_hour=hourly,
        quote_as_of=quote.captured_at,
        expires_at=quote.expires_at,
        container_disk_gb=quote.container_disk_gb,
        container_storage_micro_usd_per_gb_month=quote.container_storage_micro_usd_per_gb_month,
        persistent_volume_gb=quote.persistent_volume_gb,
        persistent_storage_micro_usd_per_gb_month=quote.persistent_storage_micro_usd_per_gb_month,
        max_storage_exposure_micro_usd=quote.max_storage_exposure_micro_usd,
        pinned_image=seal.image_ref,
        allowed_gpu_types=frozenset([quote.gpu_type]),
        host_ram_gb_by_gpu={quote.gpu_type: quote.host_ram_gb},
        rights_evidence_id=seal.rights_evidence_hash,
        preset_evidence_id=seal.sealed_sha256,
        activation_enabled=mode == "EXECUTE",
    )
    owned_tag = f"microdrama-owned:{authorization.namespace}"
    config = PodLeaseConfig(
        owned_tag=owned_tag,
        allowed_gpu_types=(quote.gpu_type,),
        min_host_ram_gb=quote.host_ram_gb,
        container_image=seal.image_ref,
        max_hourly_price_micro_usd=authorization.max_hourly_micro_usd,
        price=price,
        provider_account_ref=authorization.provider_account_ref,
        lease_ttl_ms=quote.maximum_runtime_ms,
        shutdown_margin_ms=60_000,
        create_attempts=1,
    )

    def owned_lease(pod_id):
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT l.* FROM benchmark_acquisitions a JOIN pod_leases l ON l.id=a.lease_id "
                "WHERE a.experiment_id=%s AND l.provider='runpod' AND l.pod_id=%s AND l.owned_tag=%s AND l.provider_account_ref=%s",
                (experiment_id, pod_id, owned_tag, authorization.provider_account_ref),
            )
        if row is None:
            raise EffectDenied(
                "resource has no durable experiment lease/account/namespace ownership"
            )
        return row

    def create_guard(request, _attestation):
        if mode != "EXECUTE":
            raise EffectDenied(f"{mode.lower()} experiment world cannot create resources")
        policy.validate(db, settings, live_clock, quote)
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT l.*,r.state reservation_state,r.account_id FROM benchmark_acquisitions a "
                "JOIN pod_leases l ON l.id=a.lease_id JOIN reservations r ON r.id=l.reservation_id "
                "JOIN benchmark_reservation_links k ON k.reservation_id=r.id AND k.acquisition_id=a.acquisition_id "
                "WHERE a.experiment_id=%s AND l.client_token=%s AND k.purpose='COMPUTE'",
                (experiment_id, request.client_token),
            )
        if (
            row is None
            or row["reservation_state"] != "ACTIVE"
            or row["account_id"] != exp["account_id"]
            or row["owned_tag"] != owned_tag
            or row["provider_account_ref"] != authorization.provider_account_ref
        ):
            raise EffectDenied(
                "resource create lacks its canonical experiment acquisition hold/lease"
            )

    def cleanup_guard(kind, pod_id):
        if kind not in {"pod.stop", "pod.terminate"}:
            raise EffectDenied("unsupported experiment cleanup operation")
        owned_lease(pod_id)

    resolver = _canary_credential_resolver(db, settings)
    provider = RunpodRestProvider(
        settings,
        credential_ref=authorization.runpod_credential_ref,
        credential_resolver=resolver,
        attestation=attestation,
        now=live_clock.now,
        reservation_guard=create_guard,
        cleanup_guard=cleanup_guard,
        absent_pod_ownership_probe=durable_pod_ownership_probe(
            db, owned_tag=owned_tag, provider_account_ref=authorization.provider_account_ref
        ),
        # CN-2 (2026-11-09): bind a created pod id to its lease before any
        # secondary verification GET can fail.
        created_pod_recorder=durable_created_pod_recorder(db, live_clock.now),
        # CN-5 (2026-11-09): the pod env carries the Comfy gateway token, resolved
        # from the same credential ref the ComfyUI client authenticates with.
        comfy_token_provider=lambda: resolver(authorization.comfy_credential_ref),
        transport=runpod_transport,
    )
    manager = PodManager(provider, live_clock, config)
    billing = RunpodInvoiceFinality(db, budget_service=budget)
    leases = build_lease_service(
        db, budget, manager, live_clock, live_ids, settings, config, billing
    )
    canonical_guard = durable_comfy_request_guard(db)
    client = None

    def request_guard(path, key, auth):
        # Every HTTP scope must resolve through this experiment's exact canonical
        # sample/hold/job and active acquired lease; arbitrary jobs cannot borrow it.
        with db.transaction(readonly=True) as tx:
            sample = tx.fetchone(
                "SELECT s.*,l.pod_id,l.owned_tag,l.provider_account_ref,a.state acquisition_state "
                "FROM benchmark_samples s JOIN benchmark_acquisitions a ON a.acquisition_id=s.acquisition_id "
                "JOIN pod_leases l ON l.id=a.lease_id WHERE s.experiment_id=%s AND s.job_id=%s AND s.reservation_id=%s",
                (experiment_id, auth.job_id, auth.reservation_id),
            )
        if (
            sample is None
            or auth.episode_id != plan.episode_id
            or sample["pod_id"] != client._bound_pod_id
            or sample["owned_tag"] != owned_tag
            or sample["provider_account_ref"] != authorization.provider_account_ref
        ):
            raise EffectDenied("Comfy request differs from experiment sample/acquisition ownership")
        input_route = path == "/upload/image" or (
            path.startswith("/view") and key and key.startswith("t031/")
        )
        if input_route:
            if path == "/upload/image":
                # I5: recovery and cleanup never send an upload POST; a durable
                # prior intent is reconciliation-only through the readback below.
                if mode != "EXECUTE":
                    raise EffectDenied(f"{mode.lower()} world cannot upload generation inputs")
                policy.validate(db, settings, live_clock, quote)
            with db.transaction(readonly=True) as tx:
                row = tx.fetchone(
                    "SELECT * FROM benchmark_uploads WHERE acquisition_id=%s AND upload_key=%s",
                    (sample["acquisition_id"], key),
                )
            if row is None:
                raise EffectDenied("input key lacks exact durable acquisition upload intent")
            if path == "/upload/image" and row["state"] != "UNKNOWN":
                raise EffectDenied("input POST lacks precommitted UNKNOWN intent")
            if path.startswith("/view"):
                # Checksum readback is a permitted recovery/cleanup read; it may
                # run against an EXPIRED-but-retained hold only in RECOVERY
                # (§3.3/R4), and independent of any reservation state accepted.
                if not expired_recovery_read_allowed(db, experiment_id, mode, path, key, auth):
                    canonical_guard("/object_info", None, auth)
            else:
                canonical_guard("/object_info", None, auth)
        else:
            if path == "/prompt":
                if mode != "EXECUTE":
                    raise EffectDenied(f"{mode.lower()} world cannot dispatch prompts")
                policy.validate(db, settings, live_clock, quote)
            if not expired_recovery_read_allowed(db, experiment_id, mode, path, key, auth):
                canonical_guard(path, key, auth)

    def dispatch_guard(auth):
        if auth.operation_id is None:
            raise EffectDenied("native dispatch requires canonical provider operation")
        request_guard("/prompt", None, auth)

    client = PikaHttpClient(
        settings,
        credential_ref=authorization.comfy_credential_ref,
        credential_resolver=resolver,
        request_guard=request_guard,
        dispatch_guard=dispatch_guard,
        schema_sha256=seal.node_schema_sha256,
        transport=comfy_transport,
    )
    comfy = build_comfy_render_service(
        db,
        budget,
        client,
        live_clock,
        live_ids,
        settings,
        ComfyRenderConfig(price=price, lease_covered=True),
        store,
    )
    native = _SealedNativeInputs(
        db, settings, store, live_clock, plan, seal, policy, quote, client, mode
    )
    world = CanonicalExperimentWorld(
        db=db,
        jobs=JobService(db, live_clock, live_ids),
        leases=leases,
        comfy=comfy,
        budget=budget,
        request_factory=native.request,
        binding_factory=native.bind,
        stage_inputs=native.stage,
        billing_readiness=lambda lease_id: lease_billing_readiness(db, lease_id),
        reconcile_uploads=native.readback,
    )
    world._native = native
    world._provider = provider
    world._billing = billing
    world._clock = live_clock
    world._owned_lease = owned_lease
    world._mode = mode
    # HB-3: the resolved provenance is part of the world's identity - which
    # authorization and quote every guard, namespace and settlement in this
    # world acts for. In RECOVERY/CLEANUP this is always the named
    # acquisition's own durable record (§3.2).
    world.authorization = authorization
    world.quote = quote
    world.acquisition_id = acquisition_id
    return world


def build_experiment_world_factory(db, settings, store, clock=None, ids=None):
    """Default CLI factory, with no credential reads or network during construction."""

    def factory(
        *,
        experiment_id,
        budget,
        authorization=None,
        quote=None,
        mode="EXECUTE",
        acquisition_id=None,
    ):
        return build_experiment_world(
            settings,
            db,
            budget,
            store,
            experiment_id=experiment_id,
            authorization=authorization,
            quote=quote,
            mode=mode,
            acquisition_id=acquisition_id,
            clock=clock,
            ids=ids,
        )

    return factory

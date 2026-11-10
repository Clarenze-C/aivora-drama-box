"""Separate durable experiment coordinator over the canonical rendering services.

Factories supply immutable request/binding inputs; they never supply reservation,
job, operation or experiment state. Provider effects remain in LeaseService and
ComfyRenderService. No live world is constructed implicitly by a local CLI.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget.ledger import lock_account, lock_categories
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest
from microdrama.contracts.enums import EffectKind, ExecutionMode
from microdrama.contracts.errors import Conflict, EffectDenied, NeedsReconciliation, NotFound
from microdrama.contracts.hashing import canonical_hash
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.persistence.db import jsonb
from microdrama.rendering.benchmark_experiments import (
    SCREEN_IDS,
    TERMINAL_SAMPLES,
    BenchmarkRepository,
    ExperimentBudgetService,
    document,
    experiment_row,
    gpu_ms,
)
from microdrama.rendering.leases import RENDERING_NAMESPACE


class BenchmarkService:
    def __init__(
        self,
        db: Any,
        settings: Settings,
        store: Any = None,
        clock: Any = None,
        ids: Any = None,
        world_factory: Callable | None = None,
    ):
        self.db, self.settings, self.store = db, settings, store
        self.clock, self.ids = clock or SystemClock(), ids or UuidIds()
        self.repo = BenchmarkRepository(db, self.clock)
        self.world_factory = world_factory

    def prepare(self, plan: Any):
        return self.repo.prepare(plan)

    def seal(self, experiment_id: UUID, manifest: Any):
        return self.repo.seal(experiment_id, manifest)

    def status(self, experiment_id: UUID):
        return self.repo.status(experiment_id)

    def record_screening(self, experiment_id: UUID, decision: Any):
        return self.repo.screening(experiment_id, decision)

    def preflight(self, experiment_id: UUID, authorization: Any = None, quote: Any = None):
        status = self.status(experiment_id)
        reasons = []
        seal = (status["seal"] or {}).get("manifest")
        if seal is None:
            reasons.append("execution manifest is not sealed")
        else:
            if seal.get("schema_evidence") != "LIVE_PROVIDER":
                reasons.append("actual live node schema attestation is missing")
            if not seal.get("references") or not seal.get("port_map"):
                reasons.append("actual reference bytes and role map are unresolved")
            if self.clock.now() >= status["hard_stop"]:
                reasons.append("absolute experiment deadline expired")
        if authorization is None:
            reasons.append("operator byte-SHA authorization is missing")
        if quote is None:
            reasons.append("current acquisition quote is missing")
        if (
            self.settings.execution_mode is not ExecutionMode.PAID_BENCHMARK
            or not self.settings.paid_requests_enabled
            or not self.settings.cloud_resources_enabled
        ):
            reasons.append("PAID_BENCHMARK and explicit effect flags are required")
        if authorization is not None and seal is not None and quote is not None:
            try:
                self._validate_authorization(status, authorization, quote)
                # Readiness must use the same live policy as the default world
                # factory. Authorization identity alone does not prove current
                # preset, model-rights, reference-rights, or schema eligibility.
                from microdrama.pipeline.benchmark_authorization import (
                    BenchmarkPlan,
                    BenchmarkSeal,
                )
                from microdrama.pipeline.experimental_world import ExperimentalPresetPolicy

                plan = BenchmarkPlan.model_validate(status["plan"])
                manifest = BenchmarkSeal.model_validate(seal)
                policy = ExperimentalPresetPolicy(plan, manifest, authorization)
                policy.validate(self.db, self.settings, self.clock, quote)
            except Exception:
                # Validation failures may include input values; never expose a
                # pasted credential or the sealed document in diagnostics.
                reasons.append("authorization or sealed-manifest validation failed")
        return {
            "experiment_id": str(experiment_id),
            "ready": not reasons,
            "reasons": reasons,
            "plan_sha256": status["plan_sha256"],
            "sealed_sha256": status["sealed_sha256"],
            "exposure": status["exposure"],
            "gpu_ms": status["gpu_ms"],
            "authorization_sha256": getattr(authorization, "authorization_sha256", None),
        }

    def _validate_authorization(self, status: dict, authorization: Any, quote: Any):
        from microdrama.pipeline.benchmark_authorization import BenchmarkPlan, BenchmarkSeal

        plan = BenchmarkPlan.model_validate(status["plan"])
        seal = BenchmarkSeal.model_validate(status["seal"]["manifest"])
        authorization.validate_for(plan, seal, now=self.clock.now(), quote=quote)
        if str(authorization.experiment_id) != str(status["experiment_id"]):
            raise Conflict("authorization belongs to another experiment")

    def _world(
        self,
        experiment_id: UUID,
        authorization: Any = None,
        quote: Any = None,
        *,
        mode: str = "EXECUTE",
        acquisition_id: UUID | None = None,
    ):
        if self.world_factory is None:
            raise EffectDenied(
                "no attested experimental world configured; local preparation remains available"
            )
        budget = ExperimentBudgetService(
            self.db,
            self.clock,
            self.ids,
            self.settings,
            experiment_id=experiment_id,
            cleanup_floor_micro_usd=getattr(authorization, "shutdown_reserve_micro_usd", 0),
            authorization_cap_micro_usd=getattr(authorization, "max_new_exposure_micro_usd", None),
            authorization_gpu_ms=getattr(authorization, "max_gpu_ms", None),
            authorization_deadline=getattr(authorization, "hard_stop_utc", None),
        )
        return self.world_factory(
            experiment_id=experiment_id,
            budget=budget,
            authorization=authorization,
            quote=quote,
            mode=mode,
            acquisition_id=acquisition_id,
        )

    def execute(
        self,
        experiment_id: UUID,
        *,
        phase: str,
        authorization: Any,
        quote: Any,
        expected_sha256: str,
        source_bytes: bytes | None = None,
    ):
        self.settings.require_effect(EffectKind.PAID_REQUEST, what="benchmark execute")
        self.settings.require_effect(EffectKind.CLOUD_RESOURCE, what="benchmark execute")
        if phase not in ("screen", "full"):
            raise Conflict("phase must be screen or full")
        if getattr(authorization, "authorization_sha256", None) != expected_sha256:
            raise Conflict("operator authorization byte SHA differs")
        if source_bytes is None:
            # Provenance default: the canonical serialization of the validated
            # payload. A caller that loaded a file passes its exact bytes.
            from microdrama.pipeline.benchmark_authorization import canonical_document_bytes

            source_bytes = canonical_document_bytes(authorization)
        if hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
            raise Conflict("authorization source bytes do not hash to the byte SHA")
        check = self.preflight(experiment_id, authorization, quote)
        if not check["ready"]:
            raise EffectDenied("experiment preflight is NOT_READY", blockers=check["reasons"])
        status = self.status(experiment_id)
        if status["execution_outcome"] is not None:
            raise Conflict("experiment outcome is terminal")
        if phase == "full":
            with self.db.transaction(readonly=True) as tx:
                decisions = tx.fetchall(
                    "SELECT decision FROM benchmark_screenings WHERE experiment_id=%s",
                    (experiment_id,),
                )
            if not any(r["decision"]["decision"] == "PASS" for r in decisions):
                raise Conflict("explicit same-experiment screen PASS required")
        world = self._world(experiment_id, authorization, quote)
        with self.db.transaction() as tx:
            experiment_row(tx, experiment_id, lock=True)
            # The stored payload is the parse of the accepted bytes (spec §3.2:
            # "the validated file's exact bytes, the byte SHA and the parsed
            # payload in one row") - recovery re-verifies all three agree.
            try:
                payload = json.loads(source_bytes.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise Conflict("authorization source bytes are not a JSON document") from None
            existing = tx.fetchone(
                "SELECT payload FROM benchmark_authorizations WHERE experiment_id=%s AND authorization_sha256=%s",
                (experiment_id, expected_sha256),
            )
            if existing and existing["payload"] != payload:
                raise Conflict("authorization hash reused with changed content")
            tx.execute(
                "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    experiment_id,
                    expected_sha256,
                    jsonb(payload),
                    source_bytes,
                    self.clock.now(),
                ),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state=%s,revision=revision+1 WHERE experiment_id=%s",
                ("SCREEN_RUNNING" if phase == "screen" else "FULL_RUNNING", experiment_id),
            )
        # The authorization accepted for this execution is the provenance every
        # acquisition admitted by it records (spec §3.2).
        self._authorization_sha256 = expected_sha256
        return self._advance(experiment_id, world, phase, quote)

    def _acquisition(self, experiment_id: UUID, world: Any, quote: Any):
        # Account/category locks precede experiment/slot locks in every admission.
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            exp = experiment_row(tx, experiment_id, lock=True)
            active = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s AND state NOT IN ('CLOSED','NO_CREATE_PROVEN') FOR UPDATE",
                (experiment_id,),
            )
            if active:
                return active
            generation = int(
                tx.fetchval(
                    "SELECT COALESCE(MAX(generation),0)+1 FROM benchmark_acquisitions WHERE experiment_id=%s",
                    (experiment_id,),
                )
            )
            acquisition_id = uuid5(
                RENDERING_NAMESPACE, f"benchmark:{experiment_id}:acq:{generation}"
            )
            intent = world.acquisition_requests(
                exp, quote, acquisition_id, generation, self.clock.now()
            )
            window = int(intent["claim"]["lease_ttl_ms"]) + world.leases._config.shutdown_margin_ms
            if gpu_ms(tx, experiment_id, self.clock.now()) + window > min(
                exp["gpu_limit_ms"], world.budget.authorization_gpu_ms or exp["gpu_limit_ms"]
            ):
                raise Conflict("new acquisition would exceed remaining aggregate GPU time")
            if self.clock.now() + timedelta(milliseconds=window) > min(
                exp["hard_stop"], world.budget.authorization_deadline or exp["hard_stop"]
            ):
                raise Conflict("new acquisition cannot fit absolute deadline and shutdown")
            # IDs of canonical reservations are deterministic only after reserve.
            # Persist intent with the exact request/expiry, then insert linked holds
            # in this same transaction; the immutable final intent is inserted once.
            authorization_sha256 = self._admission_authorization_sha256(tx, experiment_id)
            tx.execute(
                "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,quote,quote_sha256,intent,state,create_intent_at,authorization_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    acquisition_id,
                    experiment_id,
                    generation,
                    jsonb(document(quote)),
                    canonical_hash(document(quote)),
                    jsonb(intent),
                    "ADMITTED_WITHOUT_JOB",
                    self.clock.now(),
                    authorization_sha256,
                ),
            )
            world.budget.reserve_linked(
                tx,
                BudgetReservationRequest.model_validate(intent["compute"]),
                acquisition_id=acquisition_id,
                purpose="COMPUTE",
            )
            world.budget.reserve_linked(
                tx,
                BudgetReservationRequest.model_validate(intent["storage"]),
                acquisition_id=acquisition_id,
                purpose="STORAGE",
            )
            # Canonical reservation linkage is the durable identity, so materialize
            # reads it rather than mutating the immutable acquisition request.
            return tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s", (acquisition_id,)
            )

    def _admission_authorization_sha256(self, tx: Any, experiment_id: UUID) -> str:
        """The authorization accepted for this admission (spec §3.2), or a refusal.

        The executing run's validated authorization comes first; an independently
        restarted admission falls back to the newest recorded provenance row.
        """
        sha = getattr(self, "_authorization_sha256", None)
        if sha is None:
            sha = tx.fetchval(
                "SELECT authorization_sha256 FROM benchmark_authorizations "
                "WHERE experiment_id=%s ORDER BY authorized_at DESC LIMIT 1",
                (experiment_id,),
            )
        if sha is None:
            raise Conflict(
                "admission requires a recorded operator authorization (run execute first)"
            )
        return sha

    def _advance(self, experiment_id: UUID, world: Any, phase: str, quote: Any):
        token = self.ids.new_id()
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            slot = tx.fetchone(
                "SELECT * FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            if (
                slot["coordinator_token"] is not None
                and slot["coordinator_lease_until"] > self.clock.now()
            ):
                return self.status(experiment_id)
            tx.execute(
                "UPDATE benchmark_dispatch_slots SET coordinator_token=%s,coordinator_lease_until=%s,revision=revision+1 WHERE experiment_id=%s",
                (token, self.clock.now() + timedelta(hours=1), experiment_id),
            )
        try:
            return self._advance_owned(experiment_id, world, phase, quote, token)
        finally:
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE benchmark_dispatch_slots SET coordinator_token=NULL,coordinator_lease_until=NULL WHERE experiment_id=%s AND coordinator_token=%s",
                    (experiment_id, token),
                )

    def _advance_owned(self, experiment_id: UUID, world: Any, phase: str, quote: Any, token: UUID):
        status = self.status(experiment_id)
        if status["execution_state"] == "NEEDS_RECONCILIATION":
            # H-2: resolve every UNKNOWN provider effect before any new dispatch;
            # a still-ambiguous state refuses here instead of looping forever.
            status = self.reconcile(experiment_id, world=world)
            if status["execution_state"] == "NEEDS_RECONCILIATION":
                return status
        eligible = (
            set(SCREEN_IDS) if phase == "screen" else {s["sample_id"] for s in status["samples"]}
        )
        if all(
            s["state"] in TERMINAL_SAMPLES for s in status["samples"] if s["sample_id"] in eligible
        ):
            return self._finish_phase(experiment_id, world, phase)
        acquisition = self._acquisition(experiment_id, world, quote)
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_acquisitions SET coordinator_token=%s,coordinator_lease_until=%s WHERE acquisition_id=%s",
                (token, self.clock.now() + timedelta(hours=1), acquisition["acquisition_id"]),
            )
        try:
            if acquisition["lease_id"] is None:
                with self.db.transaction(readonly=True) as tx:
                    reservation_id = tx.fetchval(
                        "SELECT reservation_id FROM benchmark_reservation_links WHERE acquisition_id=%s AND purpose='COMPUTE'",
                        (acquisition["acquisition_id"],),
                    )
                acquisition["intent"]["compute_reservation_id"] = str(reservation_id)
                lease_id = world.materialize_acquisition(acquisition)
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE benchmark_acquisitions SET lease_id=%s WHERE acquisition_id=%s",
                        (lease_id, acquisition["acquisition_id"]),
                    )
                acquisition["lease_id"] = lease_id
            world.acquire(acquisition)
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE benchmark_acquisitions SET state='ACTIVE' WHERE acquisition_id=%s",
                    (acquisition["acquisition_id"],),
                )
            # At most one active prompt. Resume polls operation IDs before any submit.
            for _ in range(24):
                sample = self._claim_sample(experiment_id, world, acquisition, eligible)
                if sample is None:
                    return self._finish_phase(experiment_id, world, phase)
                if sample["job_id"] is None:
                    sample["job_id"] = world.materialize_sample(sample)
                if not sample["operation_id"]:
                    world.stage_inputs(acquisition)
                result = (
                    world.poll(sample)
                    if sample["operation_id"]
                    else world.submit(sample, acquisition)
                )
                self._observe(experiment_id, sample, result)
                state = getattr(result.state, "value", result.state)
                if state not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    return self.status(experiment_id)
                if state != "SUCCEEDED":
                    self.repo.outcome(experiment_id, "FAILED")
                    return self.sweep(experiment_id, world=world)
            return self.status(experiment_id)
        except NeedsReconciliation:
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE benchmark_acquisitions SET state='UNKNOWN' WHERE acquisition_id=%s",
                    (acquisition["acquisition_id"],),
                )
                tx.execute(
                    "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' WHERE experiment_id=%s",
                    (experiment_id,),
                )
            return self.sweep(experiment_id, world=world)
        except BaseException:
            self.repo.outcome(experiment_id, "FAILED")
            try:
                self.sweep(experiment_id, world=world)
            except Exception:
                pass
            raise

    def _claim_sample(self, experiment_id: UUID, world: Any, acquisition: dict, eligible: set[str]):
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            exp = experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                (acquisition["acquisition_id"],),
            )
            slot = tx.fetchone(
                "SELECT * FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            if slot["sample_id"]:
                return tx.fetchone(
                    "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s FOR UPDATE",
                    (experiment_id, slot["sample_id"]),
                )
            sample = tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=ANY(%s) AND state='PLANNED' ORDER BY sample_id LIMIT 1 FOR UPDATE",
                (experiment_id, list(eligible)),
            )
            if sample is None:
                return None
            reservation = world.budget.reserve_linked(
                tx,
                world.prompt_reservation(exp, sample),
                acquisition_id=acquisition["acquisition_id"],
                sample_id=sample["sample_id"],
                purpose="PROMPT",
            )
            request = world.request(sample, acquisition, reservation.id)
            tx.execute(
                "UPDATE benchmark_samples SET state='CLAIMED',reservation_id=%s,acquisition_id=%s,request=%s WHERE experiment_id=%s AND sample_id=%s",
                (
                    reservation.id,
                    acquisition["acquisition_id"],
                    jsonb(request),
                    experiment_id,
                    sample["sample_id"],
                ),
            )
            tx.execute(
                "UPDATE benchmark_dispatch_slots SET sample_id=%s,revision=revision+1 WHERE experiment_id=%s",
                (sample["sample_id"], experiment_id),
            )
            return tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
                (experiment_id, sample["sample_id"]),
            )

    def _observe(self, experiment_id: UUID, sample: dict, result: Any):
        state = getattr(result.state, "value", result.state)
        output = None
        if state == "SUCCEEDED":
            assets = getattr(result, "assets", ())
            if not assets:
                raise Conflict("provider success without durable output is not sample completion")
            asset = assets[0]
            output = document(asset)
            if not output.get("sha256"):
                raise Conflict("durable output hash is missing")
        if state in ("FAILED", "CANCELLED"):
            output = {"error_code": getattr(result, "error_code", None) or "UNKNOWN_FAILURE"}
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_samples SET state=%s,operation_id=%s,output=COALESCE(%s,output),coverage=COALESCE(coverage,%s) WHERE experiment_id=%s AND sample_id=%s",
                (
                    state,
                    result.operation_id,
                    jsonb(output) if output else None,
                    jsonb({"quality": "UNKNOWN"}),
                    experiment_id,
                    sample["sample_id"],
                ),
            )
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                tx.execute(
                    "UPDATE benchmark_dispatch_slots SET sample_id=NULL,revision=revision+1 WHERE experiment_id=%s AND sample_id=%s",
                    (experiment_id, sample["sample_id"]),
                )

    def _finish_phase(self, experiment_id: UUID, world: Any, phase: str):
        status = self.sweep(experiment_id, world=world)
        if status["cleanup_state"] != "VERIFIED":
            return status
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id, lock=True)
            if exp["execution_outcome"] is None:
                tx.execute(
                    "UPDATE benchmark_experiments SET execution_state=%s,execution_outcome=%s WHERE experiment_id=%s",
                    (
                        "SCREEN_REVIEW" if phase == "screen" else "COMPUTE_COMPLETE",
                        None if phase == "screen" else "SUCCEEDED",
                        experiment_id,
                    ),
                )
        return self.status(experiment_id)

    def resume(
        self,
        experiment_id: UUID,
        *,
        cleanup_only: bool = False,
        authorization: Any = None,
        quote: Any = None,
        expected_sha256: str | None = None,
        phase: str | None = None,
        source_bytes: bytes | None = None,
    ):
        """Recovery-first resume (spec §4.2 order).

        1. Identity-checked RECOVERY from durable records runs BEFORE any
           new-generation argument, flag, authorization file or quote is
           validated: reconcile, then cleanup. Nothing is dispatched here.
        2. If admission is not currently permitted (flags, authorization, quote,
           rights or deadline), the recovered durable status is returned together
           with the admission blockers, and nothing is dispatched.
        3. Only then does execute-style admission run, with the phase derived
           from durable state (a current screening PASS means ``full``).
        """
        if cleanup_only:
            return self.sweep(experiment_id)
        self.reconcile(experiment_id)
        status = self.sweep(experiment_id)
        blockers = self._admission_blockers(experiment_id, authorization, quote, expected_sha256)
        if blockers:
            status = dict(status)
            status["admission"] = {"permitted": False, "blockers": blockers}
            return status
        derived = self._derive_phase(experiment_id)
        result = self.execute(
            experiment_id,
            phase=derived,
            authorization=authorization,
            quote=quote,
            expected_sha256=expected_sha256,
            source_bytes=source_bytes,
        )
        if isinstance(result, dict):
            result.setdefault("admission", {"permitted": True, "blockers": []})
        return result

    def _derive_phase(self, experiment_id: UUID) -> str:
        """Durable phase derivation: a recorded screening PASS means full."""
        with self.db.transaction(readonly=True) as tx:
            has_pass = tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_screenings WHERE experiment_id=%s "
                "AND decision->>'decision'='PASS'",
                (experiment_id,),
            )
        return "full" if has_pass else "screen"

    def _admission_blockers(
        self,
        experiment_id: UUID,
        authorization: Any,
        quote: Any,
        expected_sha256: str | None,
    ) -> list[str]:
        """Why execute-style admission is not permitted right now, without raising."""
        blockers: list[str] = []
        status = self.status(experiment_id)
        seal = (status["seal"] or {}).get("manifest")
        if seal is None:
            blockers.append("execution manifest is not sealed")
        if status["execution_outcome"] is not None:
            blockers.append("experiment outcome is terminal")
        if status["hard_stop"] is not None and self.clock.now() >= status["hard_stop"]:
            blockers.append("absolute experiment deadline expired")
        if (
            self.settings.execution_mode is not ExecutionMode.PAID_BENCHMARK
            or not self.settings.paid_requests_enabled
            or not self.settings.cloud_resources_enabled
        ):
            blockers.append("PAID_BENCHMARK and explicit effect flags are required")
        if authorization is None:
            blockers.append("operator byte-SHA authorization is missing")
        elif expected_sha256 is None:
            blockers.append("operator authorization byte SHA-256 is missing")
        elif getattr(authorization, "authorization_sha256", None) != expected_sha256:
            blockers.append("operator authorization byte SHA differs")
        if quote is None:
            blockers.append("current acquisition quote is missing")
        return blockers

    def sweep(
        self,
        experiment_id: UUID,
        *,
        world: Any = None,
        authorization: Any = None,
        quote: Any = None,
    ):
        status = self.status(experiment_id)
        verified = True
        billed = True
        for acquisition in status["acquisitions"]:
            if acquisition["state"] == "NO_CREATE_PROVEN":
                continue
            # The world is composed lazily, per acquisition needing it: an
            # acquisition-less experiment never constructs one (spec §3.2).
            if world is None:
                world = self._world(
                    experiment_id,
                    authorization,
                    quote,
                    mode="CLEANUP",
                    acquisition_id=acquisition["acquisition_id"],
                )
            if acquisition["lease_id"] is None:
                # Materializing an owned lease is local recovery; it cannot acquire.
                with self.db.transaction(readonly=True) as tx:
                    reservation_id = tx.fetchval(
                        "SELECT reservation_id FROM benchmark_reservation_links WHERE acquisition_id=%s AND purpose='COMPUTE'",
                        (acquisition["acquisition_id"],),
                    )
                acquisition["intent"]["compute_reservation_id"] = str(reservation_id)
                acquisition["lease_id"] = world.materialize_acquisition(acquisition)
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE benchmark_acquisitions SET lease_id=%s WHERE acquisition_id=%s",
                        (acquisition["lease_id"], acquisition["acquisition_id"]),
                    )
            receipt = world.cleanup(acquisition)
            verified = verified and receipt["verified"]
            billed = billed and receipt["billing_state"] == "BILLED"
            # H-2 (2026-11-10, GLM harness review): an UNKNOWN create whose Pod was
            # positively found during cleanup (the shutdown reconciled it by token,
            # or the janitor late-adopted it) is RESOLVED - it closes like any
            # cleaned acquisition. Only a create that stayed PODLESS keeps the
            # UNKNOWN marker and its partial-index slot: the reconciler adopts a
            # Pod that appears later, and only positive proof (the audited operator
            # CLI, or the durable no-create record) may set NO_CREATE_PROVEN.
            with self.db.transaction(readonly=True) as tx:
                lease_pod = tx.fetchval(
                    "SELECT pod_id FROM pod_leases WHERE id=%s", (acquisition["lease_id"],)
                )
            unresolved = acquisition["state"] == "UNKNOWN" and lease_pod is None
            if unresolved:
                verified = False
            with self.db.transaction() as tx:
                exp = experiment_row(tx, experiment_id)
                lock_account(tx, exp["account_id"])
                lock_categories(tx, exp["account_id"])
                experiment_row(tx, experiment_id, lock=True)
                tx.fetchone(
                    "SELECT acquisition_id FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                    (acquisition["acquisition_id"],),
                )
                if receipt["verified"] and receipt["storage_final"] and not unresolved:
                    ids = tx.fetchall(
                        "SELECT r.id,r.state FROM benchmark_reservation_links l JOIN reservations r ON r.id=l.reservation_id WHERE l.acquisition_id=%s AND l.purpose='STORAGE' ORDER BY r.id FOR UPDATE OF r",
                        (acquisition["acquisition_id"],),
                    )
                    for row in ids:
                        if row["state"] == "ACTIVE":
                            world.budget.release_in_transaction(
                                tx,
                                row["id"],
                                reason="benchmark storage deletion and invoice finality verified",
                            )
                tx.execute(
                    "UPDATE benchmark_acquisitions SET compute_window_end=COALESCE(compute_window_end,%s),state=%s WHERE acquisition_id=%s",
                    (
                        receipt["compute_window_end"],
                        "UNKNOWN"
                        if unresolved
                        else (
                            "CLOSED"
                            if receipt["verified"] and receipt["storage_final"]
                            else "CLEANUP_PENDING"
                        ),
                        acquisition["acquisition_id"],
                    ),
                )
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_experiments SET cleanup_state=%s,billing_state=%s WHERE experiment_id=%s",
                (
                    "VERIFIED" if verified else "PENDING",
                    "BILLED" if billed and status["acquisitions"] else "PENDING_PROVIDER_FINALITY",
                    experiment_id,
                ),
            )
        return self.status(experiment_id)

    def reconcile(
        self,
        experiment_id: UUID,
        *,
        world: Any = None,
        authorization: Any = None,
        quote: Any = None,
    ):
        """H-2 (2026-11-10, GLM harness review): the §E provider-operation reconciler.

        Resolves every UNKNOWN provider effect an earlier run left behind, never
        creating a second effect: an UNKNOWN pod create is re-sought by its
        durable client token (positive find adopts, binds and opens storage
        ownership); an UNKNOWN prompt is re-polled by durable prompt id, or its
        id is adopted through the deterministic client id's queue/history scan.
        When every UNKNOWN is resolved the experiment leaves
        NEEDS_RECONCILIATION and execution resumes; otherwise the status is
        returned with the unresolved acquisitions still UNKNOWN (the operator
        CLI records the audited resolution). Holds stay retained throughout.
        """
        status = self.status(experiment_id)
        unknown = [a for a in status["acquisitions"] if a["state"] == "UNKNOWN"]
        slot_stuck = self._slot_sample_unknown(experiment_id)
        unresolved: list[str] = []
        for acquisition in unknown:
            # One world per acquisition (spec §3.1): the Comfy client refuses
            # rebinding, so each acquisition it touches gets its own RECOVERY
            # world and client, composed from that acquisition's durable records.
            per = world
            if per is None:
                per = self._world(
                    experiment_id,
                    authorization,
                    quote,
                    mode="RECOVERY",
                    acquisition_id=acquisition["acquisition_id"],
                )
            if not self._reconcile_acquisition(experiment_id, per, acquisition):
                unresolved.append(str(acquisition["acquisition_id"]))
        if not unresolved and slot_stuck:
            per = world
            if per is None:
                per = self._world(experiment_id, authorization, quote, mode="RECOVERY")
            self._reconcile_slot_sample(experiment_id, per)
        slot_stuck_after = self._slot_sample_unknown(experiment_id)
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id, lock=True)
            still_unknown = tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s AND state='UNKNOWN'",
                (experiment_id,),
            )
            if (
                exp["execution_state"] == "NEEDS_RECONCILIATION"
                and not still_unknown
                and not slot_stuck_after
            ):
                # The phase to resume is derived from durable screening evidence,
                # never from memory: a recorded PASS admits FULL, else SCREEN.
                if exp["execution_outcome"] is None:
                    has_pass = tx.fetchval(
                        "SELECT COUNT(*) FROM benchmark_screenings WHERE experiment_id=%s "
                        "AND decision->>'decision'='PASS'",
                        (experiment_id,),
                    )
                    tx.execute(
                        "UPDATE benchmark_experiments SET execution_state=%s WHERE experiment_id=%s",
                        ("FULL_RUNNING" if has_pass else "SCREEN_RUNNING", experiment_id),
                    )
        return self.status(experiment_id)

    def _reconcile_acquisition(self, experiment_id: UUID, world: Any, acquisition: dict) -> bool:
        """Adopt a positively-found pod for an UNKNOWN create; False keeps UNKNOWN.

        Only the LIVE-lease case resumes here: the durable client token resolves
        to an owned Pod, which is bound and ownership-opened before the normal
        acquire verifies/activates it. A terminal lease is not the reconciler's
        to resurrect: a Pod that appears after a podless close belongs to the
        janitor's late-pod adoption, and absence is never proof - both keep the
        UNKNOWN marker for the audited operator CLI."""
        from microdrama.contracts.errors import Conflict
        from microdrama.rendering.leases import LIVE_LEASE_STATES, open_storage_ownership

        with self.db.transaction(readonly=True) as tx:
            lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (acquisition["lease_id"],))
        if lease is None or lease["lease_state"] not in LIVE_LEASE_STATES:
            return False
        if lease["pod_id"] is None:
            pod = world.leases._manager.reconcile_by_token(lease["client_token"])
            if pod is None:
                return False
            world.leases._record_pod_id(lease["id"], pod.pod_id)
            open_storage_ownership(self.db, lease["id"], pod.pod_id)
        try:
            world.acquire(acquisition)
        except (NeedsReconciliation, Conflict):
            return False
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='ACTIVE' WHERE acquisition_id=%s",
                (acquisition["acquisition_id"],),
            )
        return True

    def _slot_sample_unknown(self, experiment_id: UUID) -> bool:
        """Whether the dispatch slot holds a sample whose operation is UNKNOWN.

        The sample's own ``operation_id`` link is written by ``_observe`` - a
        submit that raised NEVER got there - so the operation is resolved through
        the sample's fixed PROMPT reservation (attempts_per_sample is 1)."""
        with self.db.transaction(readonly=True) as tx:
            operation = tx.fetchval(
                "SELECT o.state FROM benchmark_dispatch_slots d "
                "JOIN benchmark_samples s ON s.experiment_id=d.experiment_id "
                "AND s.sample_id=d.sample_id "
                "LEFT JOIN provider_operations o ON o.reservation_id=s.reservation_id "
                "WHERE d.experiment_id=%s",
                (experiment_id,),
            )
        return operation == "UNKNOWN"

    def _reconcile_slot_sample(self, experiment_id: UUID, world: Any) -> None:
        """Re-poll the dispatched sample's UNKNOWN operation by durable identity."""
        with self.db.transaction(readonly=True) as tx:
            sample = tx.fetchone(
                "SELECT s.* FROM benchmark_dispatch_slots d JOIN benchmark_samples s "
                "ON s.experiment_id=d.experiment_id AND s.sample_id=d.sample_id "
                "WHERE d.experiment_id=%s",
                (experiment_id,),
            )
            operation = (
                tx.fetchone(
                    "SELECT id, state FROM provider_operations WHERE reservation_id=%s",
                    (sample["reservation_id"],),
                )
                if sample
                else None
            )
        if sample is None or operation is None or operation["state"] != "UNKNOWN":
            return
        try:
            result = world.comfy.reconcile_unknown(operation["id"])
        except NeedsReconciliation:
            return
        self._observe(experiment_id, sample, result)

    def resolve_create(
        self,
        experiment_id: UUID,
        *,
        acquisition_id: UUID,
        actor_ref: str,
        reason: str,
        evidence_sha256: str,
    ):
        """H-2: the audited OPERATOR resolution for an UNKNOWN pod create (§E).

        Mirrors the canary's resolve_podless_create: the operator attests, with
        a sha256 evidence hash, that the provider console shows no Pod and no
        charge for the owned name and period. NO_CREATE_PROVEN is set ONLY on
        that positive proof (or the durable proof that no create was ever sent),
        freeing the partial-index slot so a new acquisition may be admitted.
        """
        from microdrama.budget import BudgetService
        from microdrama.budget.billing import BillingRepository
        from microdrama.contracts.errors import SchemaInvalid

        for value in (actor_ref, reason):
            if not str(value or "").strip():
                raise SchemaInvalid("a podless-create resolution requires an actor and reason")
        if not (
            isinstance(evidence_sha256, str)
            and len(evidence_sha256) == 64
            and all(c in "0123456789abcdef" for c in evidence_sha256)
        ):
            raise SchemaInvalid("a podless-create resolution requires a sha256 evidence hash")
        with self.db.transaction() as tx:
            experiment_row(tx, experiment_id, lock=True)
            acquisition = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s "
                "AND acquisition_id=%s FOR UPDATE",
                (experiment_id, acquisition_id),
            )
            if acquisition is None:
                raise NotFound("benchmark acquisition not found")
            if acquisition["state"] == "NO_CREATE_PROVEN":
                return self.status(experiment_id)
            if acquisition["state"] != "UNKNOWN":
                raise Conflict(
                    "only an UNKNOWN create can be resolved as podless",
                    acquisition_state=acquisition["state"],
                )
            lease = tx.fetchone(
                "SELECT * FROM pod_leases WHERE id=%s FOR UPDATE", (acquisition["lease_id"],)
            )
            if lease is not None and lease["pod_id"] is not None:
                raise Conflict(
                    "the acquisition's lease has a Pod attached; reconcile adopts it",
                    pod_id=lease["pod_id"],
                )
            create_requested = lease["create_requested_at"] if lease is not None else None
        if create_requested is not None:
            # The audited attestation posts the deterministic BILLED 0 settlement
            # (freeing the compute hold's remainder) and bounds the window.
            repository = BillingRepository(
                self.db, budget_service=BudgetService(self.db, self.clock, self.ids, self.settings)
            )
            repository.resolve_podless_create(
                acquisition["lease_id"],
                actor_ref=actor_ref,
                reason=reason,
                evidence_sha256=evidence_sha256,
                now=self.clock.now(),
            )
        with self.db.transaction() as tx:
            experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT acquisition_id FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                (acquisition_id,),
            )
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='NO_CREATE_PROVEN',"
                "compute_window_end=COALESCE(compute_window_end,create_intent_at) "
                "WHERE acquisition_id=%s",
                (acquisition_id,),
            )
            # No Pod ever existed for this acquisition: its protective storage
            # hold has nothing to guard. Release it in the same resolution.
            storage = tx.fetchall(
                "SELECT r.id FROM benchmark_reservation_links l JOIN reservations r "
                "ON r.id=l.reservation_id WHERE l.acquisition_id=%s AND l.purpose='STORAGE' "
                "AND r.state='ACTIVE' ORDER BY r.id FOR UPDATE OF r",
                (acquisition_id,),
            )
            for row in storage:
                ExperimentBudgetService(
                    self.db,
                    self.clock,
                    self.ids,
                    self.settings,
                    experiment_id=experiment_id,
                ).release_in_transaction(
                    tx, row["id"], reason="benchmark storage hold released at proven no-create"
                )
            if not tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_acquisitions WHERE experiment_id=%s "
                "AND state='UNKNOWN'",
                (experiment_id,),
            ):
                tx.execute(
                    "UPDATE benchmark_experiments SET execution_state="
                    "'SCREEN_RUNNING' WHERE experiment_id=%s AND execution_state="
                    "'NEEDS_RECONCILIATION'",
                    (experiment_id,),
                )
        return self.status(experiment_id)

    def resolve_sample(
        self,
        experiment_id: UUID,
        *,
        sample_id: str,
        actor_ref: str,
        reason: str,
        evidence_sha256: str,
        world: Any = None,
    ):
        """H-2: the audited OPERATOR resolution for a sample's UNKNOWN operation.

        Records the terminal FAILED outcome (no output is adopted), settles the
        attempt exactly like a provider-reported failure, and frees the dispatch
        slot so the experiment can continue with the next sample. Runs in a
        cleanup-only world: an operator resolution is recovery, never new work.
        """
        with self.db.transaction(readonly=True) as tx:
            sample = tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
                (experiment_id, sample_id),
            )
            if sample is None:
                raise NotFound("benchmark sample not found")
            # The operation link is written by _observe; a submit that raised
            # never got there, so resolve through the fixed PROMPT reservation.
            operation_id = sample["operation_id"] or tx.fetchval(
                "SELECT id FROM provider_operations WHERE reservation_id=%s",
                (sample["reservation_id"],),
            )
            if operation_id is None:
                raise Conflict("the sample has no provider operation to resolve")
        world = world or self._world(experiment_id, mode="CLEANUP")
        status = world.comfy.resolve_unknown_operation(
            operation_id,
            actor_ref=actor_ref,
            reason=reason,
            evidence_sha256=evidence_sha256,
        )
        self._observe(experiment_id, sample, status)
        return self.status(experiment_id)

    def export(self, experiment_id: UUID):
        status = self.status(experiment_id)
        return {
            "experiment_id": str(experiment_id),
            "execution_state": status["execution_state"],
            "execution_outcome": status["execution_outcome"],
            "cleanup_state": status["cleanup_state"],
            "billing_state": status["billing_state"],
            "gpu_ms": status["gpu_ms"],
            "costs": status["exposure"],
            "billed_micro_usd": status["exposure"]["settled"]
            + status["exposure"]["unreserved_settled"]
            if status["billing_state"] == "BILLED"
            else None,
            "samples": [
                {
                    "sample_id": s["sample_id"],
                    "state": s["state"],
                    "output": s["output"],
                    "quality": (s["coverage"] or {}).get("quality", "UNKNOWN"),
                    "cost_micro_usd": None,
                }
                for s in status["samples"]
            ],
        }

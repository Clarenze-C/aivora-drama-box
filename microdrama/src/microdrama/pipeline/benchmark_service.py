"""Separate durable experiment coordinator over the canonical rendering services.

Factories supply immutable request/binding inputs; they never supply reservation,
job, operation or experiment state. Provider effects remain in LeaseService and
ComfyRenderService. No live world is constructed implicitly by a local CLI.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget.ledger import lock_account, lock_categories
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest
from microdrama.contracts.enums import EffectKind, ExecutionMode
from microdrama.contracts.errors import Conflict, EffectDenied, NeedsReconciliation
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
        cleanup_only: bool = False,
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
            cleanup_only=cleanup_only,
        )

    def execute(
        self,
        experiment_id: UUID,
        *,
        phase: str,
        authorization: Any,
        quote: Any,
        expected_sha256: str,
    ):
        self.settings.require_effect(EffectKind.PAID_REQUEST, what="benchmark execute")
        self.settings.require_effect(EffectKind.CLOUD_RESOURCE, what="benchmark execute")
        if phase not in ("screen", "full"):
            raise Conflict("phase must be screen or full")
        if getattr(authorization, "authorization_sha256", None) != expected_sha256:
            raise Conflict("operator authorization byte SHA differs")
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
            payload = document(authorization)
            existing = tx.fetchone(
                "SELECT payload FROM benchmark_authorizations WHERE experiment_id=%s AND authorization_sha256=%s",
                (experiment_id, expected_sha256),
            )
            if existing and existing["payload"] != payload:
                raise Conflict("authorization hash reused with changed content")
            tx.execute(
                "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,payload,authorized_at) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (experiment_id, expected_sha256, jsonb(payload), self.clock.now()),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state=%s,revision=revision+1 WHERE experiment_id=%s",
                ("SCREEN_RUNNING" if phase == "screen" else "FULL_RUNNING", experiment_id),
            )
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
            tx.execute(
                "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,quote,quote_sha256,intent,state,create_intent_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    acquisition_id,
                    experiment_id,
                    generation,
                    jsonb(document(quote)),
                    canonical_hash(document(quote)),
                    jsonb(intent),
                    "ADMITTED_WITHOUT_JOB",
                    self.clock.now(),
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
        cleanup_only: bool = True,
        authorization: Any = None,
        quote: Any = None,
        expected_sha256: str | None = None,
        phase: str | None = None,
    ):
        if cleanup_only:
            return self.sweep(experiment_id)
        status = self.status(experiment_id)
        phase = phase or ("screen" if status["execution_state"] == "SCREEN_RUNNING" else "full")
        return self.execute(
            experiment_id,
            phase=phase,
            authorization=authorization,
            quote=quote,
            expected_sha256=expected_sha256,
        )

    def sweep(
        self,
        experiment_id: UUID,
        *,
        world: Any = None,
        authorization: Any = None,
        quote: Any = None,
    ):
        world = world or self._world(experiment_id, authorization, quote, cleanup_only=True)
        status = self.status(experiment_id)
        verified = True
        billed = True
        for acquisition in status["acquisitions"]:
            if acquisition["state"] == "NO_CREATE_PROVEN":
                continue
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
            with self.db.transaction() as tx:
                exp = experiment_row(tx, experiment_id)
                lock_account(tx, exp["account_id"])
                lock_categories(tx, exp["account_id"])
                experiment_row(tx, experiment_id, lock=True)
                tx.fetchone(
                    "SELECT acquisition_id FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                    (acquisition["acquisition_id"],),
                )
                if receipt["verified"] and receipt["storage_final"]:
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
                        "CLOSED"
                        if receipt["verified"] and receipt["storage_final"]
                        else "CLEANUP_PENDING",
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

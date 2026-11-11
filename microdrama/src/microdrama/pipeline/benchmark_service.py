"""Separate durable experiment coordinator over the canonical rendering services.

Factories supply immutable request/binding inputs; they never supply reservation,
job, operation or experiment state. Provider effects remain in LeaseService and
ComfyRenderService. No live world is constructed implicitly by a local CLI.

T031 H-2 §6.1/R5 - the transaction inventory (function -> locks in order ->
writes), rewritten from the actual SQL after the HCF round (HC-6). The shared
order is: 1 account, 2 categories, 3 E (benchmark_experiments), 4 A
(benchmark_acquisitions, by id), 5 billing advisory then L (pod_leases, by
id), 6 D (benchmark_dispatch_slots), 7 S (benchmark_samples, by id), 8 R
(reservations, by id); the R5 suffix continues with provider operation rows
(O, by id) and upload rows (by their immutable key). No network call is made
while these locks are held.

``_lock_gate_rows`` is the ONE ordered row-lock helper for steps 4-8 plus the
R5 suffix (A rows by id -> the experiment's L rows by id -> D -> S rows by id
-> linked R rows by id -> O rows by id -> upload rows by key); every
transaction below that evaluates or writes gate rows takes it, after the
caller's account/category/E prefix locks.

Full-order benchmark transactions (actual locks in the shared order):

- ``execute``                      account, categories, E; the predicated
                                   state write (never from
                                   NEEDS_RECONCILIATION); then ``_advance``.
- ``_advance``                     account, categories, E, D; takes the slot
                                   coordinator token (control write) or
                                   returns the status while a live token held.
- ``_advance_owned`` coordination  account, categories, E, A(row), D(slot);
                                   writes the acquisition coordinator token
                                   (HC-6: A before D, the fence's own order).
- ``_activate_acquisition``        account, categories, E, A(row), D(slot);
                                   HC-5 ownership assertion (BOTH tokens,
                                   live leases), then the ACTIVE write.
- ``_acquisition``                 account, categories, E, helper (A, L, D, S,
                                   R, O, uploads); returns the existing
                                   acquisition only without U1/U5 on it, or
                                   admits (gate + intent + linked
                                   COMPUTE/STORAGE holds via reserve_linked).
- ``_claim_sample``                account, categories, E, helper; HC-5
                                   ownership assertion, then the occupied-slot
                                   return or the fresh claim (PROMPT hold,
                                   sample CLAIMED write, slot occupancy) with
                                   ``unresolved_items`` re-evaluated under the
                                   same locks.
- ``_gate`` / ``_gate_in_tx``      account, categories, E, helper; read-only
                                   decision (plus the HC-5 ownership assertion
                                   for dispatch), refuses before any effect.
- ``_observe``                     E, D(slot), S(row) - a shared-order suffix;
                                   token assertion, monotonic projection, slot
                                   clear and the R6 outcome write.
- ``finalize_terminal`` (3+4)      account, categories, E, D(slot), S(row);
                                   projection + slot clear + R6 outcome in one
                                   transaction (settlement ran before, through
                                   the canonical receipts).
- ``_mark_upload_ambiguity``       account, categories, E (+ A, D and the HC-5
                                   ownership assertion when a coordinator drove
                                   the upload); E state write only.
- ``_mark_create_ambiguity``       account, categories, E, A(row) (+ D and the
                                   HC-5 ownership assertion when a coordinator
                                   drove the create); A + E state writes.
- ``_enter_grace`` (§5.4)          account, categories, E, A(row) (+ the
                                   ownership assertion when a coordinator drove
                                   the ambiguity); persists
                                   recovery_started_at / recovery_deadline.
- ``_deadline_fence`` (R3)         account, categories, E, A(row), helper;
                                   recomputes under lock (shorten-only), then
                                   revokes the coordinator + slot tokens.
- ``resolve_create`` (§6.2)        account, categories, E, A(row), billing
                                   advisory (billing.py key 451051), L(row);
                                   SC2-3 replay, preconditions,
                                   resolve_podless_create_in_tx (audit + window
                                   end + zero-BILLED compute settlement) and
                                   the NO_CREATE_PROVEN write in ONE
                                   transaction. Never releases STORAGE.
- ``sweep`` NO_CREATE finalization (§6.3)  account, categories, E, helper (the
                                   lease row the decision reads is L-locked
                                   inside it); re-checks under lock and
                                   releases the single original STORAGE hold -
                                   the only place that may.
- ``sweep`` cleanup finalization   account, categories, E, helper; storage
                                   release, upload fence, failed-sample
                                   projection, slot clear, outcome write and
                                   prompt-hold releases, all on rows the
                                   helper already locked in the shared order
                                   (HC-6: the previous shape locked R and
                                   uploads before the D/S writes).

Canonical transactions kept suffix-only (they lock only R5-suffix rows and
never take earlier-order benchmark or budget locks afterwards):

- ``provider_ops.begin``/``record_result`` (comfy_jobs)  the reservation row
  (FOR SHARE on begin) then the O row; a benchmark gate that locks R before O
  serialises with them at R.
- ``_submit_bound_graph``'s first-send claim (comfy_jobs, HB-7/HC-5)  the O
  row via ``begin``; the optional ``send_authorizer`` predicate runs inside
  the claim transaction (reads the coordinator ownership, takes no locks).
- ``_SealedNativeInputs.stage`` upload-intent INSERT/UNKNOWN write  the
  acquisition ownership row (A, R5 insertion serialization) then the upload
  row; never earlier-order locks afterwards.
- ``BillingRepository.resolve_podless_create_in_tx``  assumes the caller holds
  locks 1-5 (account, categories, E, A, advisory); takes L (re-entrantly with
  the advisory), writes the audit row, lease window and zero-BILLED
  settlement receipt.
- operator terminal transitions (``resolve_sample`` -> comfy_jobs)  the O row;
  the terminal transition commits BEFORE financial finalization is invoked.
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
from microdrama.contracts.errors import (
    Conflict,
    EffectDenied,
    MicrodramaError,
    NeedsReconciliation,
    NotFound,
    PolicyDenied,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.persistence.db import jsonb
from microdrama.rendering.benchmark_experiments import (
    SCREEN_IDS,
    TERMINAL_SAMPLES,
    BenchmarkRepository,
    ExperimentBudgetService,
    blocking,
    discovered_resource_billing_final,
    document,
    experiment_row,
    gpu_ms,
    unresolved_items,
)
from microdrama.rendering.leases import LIVE_LEASE_STATES, RENDERING_NAMESPACE

RECOVERY_GRACE_MAX_S = 600  # §5.4: the documented maximum recovery grace


class AdmissionBlocked(MicrodramaError):
    """§4.2/I3: unresolved items block this admission, claim or dispatch.

    Raised inside the locked transaction that evaluated the items, so nothing
    was written when it fires. ``_advance_owned`` converts it into a
    reconciliation status instead of a failed experiment.
    """

    def __init__(self, blockers: list[str]):
        super().__init__("; ".join(blockers) or "unresolved items block this action")
        self.blockers = blockers


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
        if self.settings.public_actions_enabled:
            # L-4: the factory refuses PAID_BENCHMARK with public actions on;
            # readiness must say so instead of reporting ready.
            reasons.append("public actions must stay disabled for the paid benchmark")
        # L-4: no budget headroom means the first acquire would refuse - both
        # are local durable reads, so readiness reports them without reserving.
        plan_doc = status.get("plan") or {}
        if plan_doc:
            exposure_total = int((status.get("exposure") or {}).get("total") or 0)
            if exposure_total >= int(plan_doc["max_new_exposure_micro_usd"]):
                reasons.append("new-exposure cap already committed - no headroom")
            if int(status.get("gpu_ms") or 0) >= int(plan_doc["max_gpu_ms"]):
                reasons.append("aggregate GPU budget exhausted - no headroom")
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
        # HB-3 (§3.2): for mode != EXECUTE, build_experiment_world itself loads
        # the named acquisition's OWN durable authorization and quote - the
        # caller-supplied documents below never replace recovery provenance
        # (they only parameterize the budget service's admission caps, which
        # recovery worlds never exercise: recovery makes no new reservations).
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
            cleanup_grants_only=mode != "EXECUTE",
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
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            # §4.2: the gate runs under the §6.1 lock order, before any state
            # write. Anything that blocks admission refuses the whole execute.
            self._gate_in_tx(tx, experiment_id, "admission")
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
            # §4.2: predicate the running-state write on its source - PREPARED,
            # SCREEN_REVIEW with a current PASS (full phase only), or the same
            # phase already running. Never from NEEDS_RECONCILIATION: reconcile
            # is the only writer back to a running state.
            running = "SCREEN_RUNNING" if phase == "screen" else "FULL_RUNNING"
            has_pass = bool(
                phase == "full"
                and tx.fetchval(
                    "SELECT 1 FROM benchmark_screenings WHERE experiment_id=%s "
                    "AND decision->>'decision'='PASS' LIMIT 1",
                    (experiment_id,),
                )
            )
            updated = tx.fetchval(
                "UPDATE benchmark_experiments SET execution_state=%s,revision=revision+1 "
                "WHERE experiment_id=%s AND (execution_state IN ('PREPARED',%s) "
                "OR (execution_state='SCREEN_REVIEW' AND %s)) RETURNING 1",
                (running, experiment_id, running, has_pass),
            )
            if not updated:
                raise Conflict(
                    "execution state does not admit this phase from its current source state"
                )
        # The authorization accepted for this execution is the provenance every
        # acquisition admitted by it records (spec §3.2).
        self._authorization_sha256 = expected_sha256
        return self._advance(experiment_id, world, phase, quote)

    def _lock_gate_rows(self, tx: Any, experiment_id: UUID) -> None:
        """The ONE §6.1 ordered row-lock helper (HC-6): steps 4-8 plus the R5 suffix.

        Every benchmark transaction that evaluates or writes gate rows locks
        them through this helper, in the shared order: the acquisition
        ownership rows (step 4 - upload-intent insertion serialises through
        them, R5), the experiment's lease rows (L, step 5 - a canonical L-only
        janitor adoption cannot bind a pod or contradict a resolution while a
        gate or finalization transaction proceeds), the dispatch slot (D, step
        6), the samples (S, step 7), the linked reservations (R, step 8), then
        the provider operations (O) and upload intents (R5 suffix) - the
        complete canonical set a gate decision evaluates. No network call is
        ever made under these locks: refusal raises before any effect.
        """
        tx.fetchall(
            "SELECT acquisition_id FROM benchmark_acquisitions WHERE experiment_id=%s "
            "ORDER BY acquisition_id FOR UPDATE",
            (experiment_id,),
        )
        tx.fetchall(
            "SELECT l.id FROM pod_leases l JOIN benchmark_acquisitions a "
            "ON a.lease_id=l.id WHERE a.experiment_id=%s ORDER BY l.id FOR UPDATE",
            (experiment_id,),
        )
        tx.fetchone(
            "SELECT * FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
            (experiment_id,),
        )
        tx.fetchall(
            "SELECT sample_id FROM benchmark_samples WHERE experiment_id=%s "
            "ORDER BY sample_id FOR UPDATE",
            (experiment_id,),
        )
        tx.fetchall(
            "SELECT r.id FROM reservations r JOIN benchmark_reservation_links l "
            "ON l.reservation_id=r.id WHERE l.experiment_id=%s ORDER BY r.id FOR UPDATE OF r",
            (experiment_id,),
        )
        tx.fetchall(
            "SELECT o.id FROM provider_operations o JOIN benchmark_samples s "
            "ON s.reservation_id=o.reservation_id WHERE s.experiment_id=%s "
            "ORDER BY o.id FOR UPDATE OF o",
            (experiment_id,),
        )
        tx.fetchall(
            "SELECT u.acquisition_id FROM benchmark_uploads u JOIN benchmark_acquisitions a "
            "ON a.acquisition_id=u.acquisition_id WHERE a.experiment_id=%s "
            "ORDER BY u.acquisition_id, u.asset_sha256, u.media_kind, u.role, u.subject_id "
            "FOR UPDATE OF u",
            (experiment_id,),
        )

    def _assert_coordination(
        self, tx: Any, experiment_id: UUID, acquisition_id: UUID | None, token: UUID
    ) -> None:
        """R3 deadline fence + HB-7 ownership validity: a coordinator control
        write or first-send authorisation is valid only while BOTH durable
        tokens - the dispatch slot's and the acquisition's - still match the
        caller's token AND their ownership leases are still live. Matching
        values with a NULL/expired lease are a stale coordinator (HB-7's
        probe accepted them). The fence committed at deadline exhaustion
        revokes exactly those two tokens; revocation never proves an
        already-authorised external send never happened (I2) - such effects
        stay with reconciliation - it only strips the right to control or
        dispatch further."""
        slot = tx.fetchone(
            "SELECT coordinator_token, coordinator_lease_until "
            "FROM benchmark_dispatch_slots WHERE experiment_id=%s",
            (experiment_id,),
        )
        acquisition = (
            tx.fetchone(
                "SELECT coordinator_token, coordinator_lease_until "
                "FROM benchmark_acquisitions WHERE acquisition_id=%s",
                (acquisition_id,),
            )
            if acquisition_id is not None
            else None
        )
        now = self.clock.now()

        def _owned(row) -> bool:
            return (
                row is not None
                and row["coordinator_token"] == token
                and row["coordinator_lease_until"] is not None
                and row["coordinator_lease_until"] > now
            )

        if not _owned(slot) or not _owned(acquisition):
            raise AdmissionBlocked(
                ["R3 fence: the coordinator token was revoked at the recovery deadline"]
            )

    def _activate_acquisition(
        self, experiment_id: UUID, acquisition_id: UUID, *, coordinator_token: UUID
    ) -> None:
        """HC-5: the ACTIVE control write, under the A and D row locks.

        The write is authorised only by the FULL live ownership - both durable
        tokens with live ownership leases (``_assert_coordination``), not the
        acquisition row's token alone: a coordinator whose dispatch-slot token
        was fenced at the recovery deadline writes no control state. Effects
        authorized before fencing stay with reconciliation; the fence only
        strips the right to control further.
        """
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT acquisition_id FROM benchmark_acquisitions "
                "WHERE acquisition_id=%s FOR UPDATE",
                (acquisition_id,),
            )
            tx.fetchone(
                "SELECT coordinator_token, coordinator_lease_until "
                "FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            self._assert_coordination(tx, experiment_id, acquisition_id, coordinator_token)
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='ACTIVE' WHERE acquisition_id=%s",
                (acquisition_id,),
            )

    def _gate_in_tx(
        self,
        tx: Any,
        experiment_id: UUID,
        action: str,
        *,
        coordinator_token: UUID | None = None,
        **scope: Any,
    ) -> None:
        """Evaluate the §4.1 blocking items under the caller's locked transaction.

        The caller has already taken the account/category/E locks (§6.1).
        A dispatch decision additionally re-checks its coordinator token in
        this same transaction (§5.4/R3): a fenced or expired coordinator never
        authorises a first send.
        """
        self._lock_gate_rows(tx, experiment_id)
        if coordinator_token is not None:
            self._assert_coordination(
                tx, experiment_id, scope.get("acquisition_id"), coordinator_token
            )
        items = unresolved_items(tx, experiment_id, now=self.clock.now())
        blockers = blocking(items, action, **scope)
        if blockers:
            raise AdmissionBlocked([item.describe() for item in blockers])

    def _gate(
        self,
        experiment_id: UUID,
        action: str,
        *,
        coordinator_token: UUID | None = None,
        **scope: Any,
    ) -> None:
        """A standalone gate transaction for the dispatch step (§4.2)."""
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            self._gate_in_tx(
                tx, experiment_id, action, coordinator_token=coordinator_token, **scope
            )

    def _acquisition(self, experiment_id: UUID, world: Any, quote: Any):
        # Account/category locks precede experiment/slot locks in every admission.
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            exp = experiment_row(tx, experiment_id, lock=True)
            # HC-6: the ONE shared-order helper locks A rows, the experiment's
            # lease rows (L - the Q3/§6.4 prior-lease serialization this
            # admission evaluates U1/U5 under), D, S, R, O and uploads before
            # any evaluation. A row read below re-acquires rows it holds.
            self._lock_gate_rows(tx, experiment_id)
            active = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s AND state NOT IN ('CLOSED','NO_CREATE_PROVEN') FOR UPDATE",
                (experiment_id,),
            )
            if active:
                # Returning an existing acquisition is not an admission - the
                # in-flight work on it must stay pollable (U3p/U4 block fresh
                # admission only) - but a create that is uncertain (U1) or a
                # reopened liability (U5) on it forbids proceeding at all:
                # reconciliation owns that acquisition next.
                items = unresolved_items(tx, experiment_id, now=self.clock.now())
                owning = {
                    item.acquisition_id
                    for item in items
                    if item.kind in ("U1", "U5") and item.acquisition_id == active["acquisition_id"]
                }
                if owning:
                    raise AdmissionBlocked(
                        [
                            item.describe()
                            for item in items
                            if item.acquisition_id == active["acquisition_id"]
                            and item.kind in ("U1", "U5")
                        ]
                    )
                return active
            # Fresh admission: every admission-blocking kind refuses (U1, U2,
            # U3, U3p, U3u, U4, U5 - §4.1 R2). U6 never blocks other work.
            self._gate_in_tx(tx, experiment_id, "admission")
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
                import os as _os

                if _os.environ.get("T031_DEBUG"):
                    import sys as _sys

                    print("DBG advance token-held", file=_sys.stderr)
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

    def _needs_finalization(self, experiment_id: UUID, acquisition: dict) -> bool:
        """Whether this acquisition must be finalized before ANY work continues.

        AT-5/I3: a CLEANUP_PENDING/UNKNOWN acquisition, or one whose lease is
        terminal, is never acquired again - cleanup and finalization own it, and
        the next generation is admitted only after that completes (U2).
        """
        if acquisition["state"] in ("CLEANUP_PENDING", "UNKNOWN"):
            return True
        if acquisition["lease_id"] is None:
            return False
        with self.db.transaction(readonly=True) as tx:
            lease = tx.fetchone(
                "SELECT lease_state, terminate_verified_at FROM pod_leases WHERE id=%s",
                (acquisition["lease_id"],),
            )
        return (
            lease is None
            or lease["lease_state"] not in LIVE_LEASE_STATES
            or lease["terminate_verified_at"] is not None
        )

    def _close_undispatchable_sample(self, experiment_id: UUID, world: Any, sample: dict):
        """§4.1 U6: a claim whose pre-effect hold is no longer adoptable.

        Replay adopts an ACTIVE hold (returns None so the caller materializes
        and submits). A hold that expired before anything was dispatched has no
        operation under it - the send right was never exercised - so only its
        positively unused liability closes (§F): a zero-charge settlement, the
        sample FAILED, the slot freed, and the experiment outcome set once
        (§7.4 fail-fast). No effect is ever sent.
        """
        with self.db.transaction(readonly=True) as tx:
            state = tx.fetchval(
                "SELECT state FROM reservations WHERE id=%s", (sample["reservation_id"],)
            )
            operations = tx.fetchval(
                "SELECT COUNT(*) FROM provider_operations WHERE reservation_id=%s",
                (sample["reservation_id"],),
            )
        if state == "ACTIVE" or operations:
            return None
        if state == "EXPIRED":
            world.budget.settle_expired_unused_hold(
                sample["reservation_id"],
                reason=f"benchmark sample {sample['sample_id']} hold expired before dispatch",
            )
        elif state not in ("SETTLED", "RELEASED"):
            raise Conflict(
                "undispatched sample hold is in an unexpected canonical state",
                reservation_state=state,
            )
        from types import SimpleNamespace

        self._observe(
            experiment_id,
            sample,
            SimpleNamespace(
                state="FAILED",
                operation_id=None,
                error_code="HOLD_EXPIRED_BEFORE_DISPATCH",
                assets=(),
            ),
        )
        self.repo.outcome(experiment_id, "FAILED")
        return self.sweep(experiment_id, world=world)

    def _shutdown_margin_ms(self, world: Any = None) -> int:
        config = getattr(getattr(world, "leases", None), "_config", None)
        return int(getattr(config, "shutdown_margin_ms", 60_000))

    def _effective_recovery_deadline(
        self,
        experiment_id: UUID,
        acquisition_id: UUID,
        *,
        tx=None,
        margin_ms: int | None = None,
    ):
        """HB-6 (R3): the earliest absolute recovery deadline, from the
        EFFECTIVE limits - the tighter of the plan row and the acquisition's
        ACCEPTED AUTHORIZATION for both the hard stop and the aggregate GPU
        limit - with the funded-work window's shutdown allowance excluded and
        the aggregate GPU deadline RESERVING the shutdown GPU time (all
        durable acquisition windows, including reopened ones, are inside
        ``gpu_ms``). Returns None when nothing durable bounds the episode
        beyond the clock (the caller still applies the 600 s maximum)."""
        from microdrama.pipeline.experimental_world import load_recovery_authorization

        now = self.clock.now()
        try:
            authorization = load_recovery_authorization(self.db, acquisition_id)
        except Exception:  # noqa: BLE001 - a missing record falls back to plan limits
            authorization = None
        auth_gpu = getattr(authorization, "max_gpu_ms", None)
        auth_deadline = getattr(authorization, "hard_stop_utc", None)
        if margin_ms is None:
            margin_ms = 60_000
        margin = timedelta(milliseconds=margin_ms)
        open_windows_sql = (
            "SELECT COUNT(*) FROM benchmark_acquisitions a "
            "LEFT JOIN pod_leases l ON l.id=a.lease_id "
            "WHERE a.experiment_id=%s AND a.create_intent_at IS NOT NULL "
            "AND (a.state<>'NO_CREATE_PROVEN' OR EXISTS ("
            "SELECT 1 FROM runpod_podless_create_resolutions r WHERE r.lease_id=a.lease_id "
            "AND r.contradicted_at IS NOT NULL)) "
            "AND (CASE WHEN a.state<>'NO_CREATE_PROVEN' THEN a.compute_window_end IS NULL "
            "ELSE l.terminate_verified_at IS NULL END)"
        )
        if tx is not None:
            exp = experiment_row(tx, experiment_id)
            compute_expires = tx.fetchval(
                "SELECT r.expires_at FROM benchmark_reservation_links l "
                "JOIN reservations r ON r.id=l.reservation_id "
                "WHERE l.acquisition_id=%s AND l.purpose='COMPUTE' "
                # HC-9: only a hold that still owns funds bounds the funded
                # window. A SETTLED/RELEASED hold's expiry is history - in the
                # late-contradiction scenario the reopened generation-1 hold is
                # settled at the podless resolution's zero while its REOPENED
                # window is counted by the aggregate gpu_ms bound below;
                # letting the dead expiry into the min() would collapse the
                # effective deadline onto a closed window's past expiry.
                "AND r.state IN ('ACTIVE','EXPIRED')",
                (acquisition_id,),
            )
            used_gpu_ms = gpu_ms(tx, experiment_id, now)
            open_windows = int(tx.fetchval(open_windows_sql, (experiment_id,)) or 0)
        else:
            with self.db.transaction(readonly=True) as readonly:
                exp = experiment_row(readonly, experiment_id)
                compute_expires = readonly.fetchval(
                    "SELECT r.expires_at FROM benchmark_reservation_links l "
                    "JOIN reservations r ON r.id=l.reservation_id "
                    "WHERE l.acquisition_id=%s AND l.purpose='COMPUTE' "
                    "AND r.state IN ('ACTIVE','EXPIRED')",
                    (acquisition_id,),
                )
                used_gpu_ms = gpu_ms(readonly, experiment_id, now)
                open_windows = int(readonly.fetchval(open_windows_sql, (experiment_id,)) or 0)
        effective_gpu_limit = exp["gpu_limit_ms"]
        if auth_gpu is not None:
            effective_gpu_limit = min(effective_gpu_limit, auth_gpu)
        effective_hard_stop = exp["hard_stop"]
        if auth_deadline is not None:
            effective_hard_stop = (
                min(effective_hard_stop, auth_deadline)
                if effective_hard_stop is not None
                else auth_deadline
            )
        candidates: list = []
        if effective_hard_stop is not None:
            candidates.append(effective_hard_stop - margin)
        if compute_expires is not None:
            candidates.append(compute_expires - margin)  # shutdown allowance excluded
        # The aggregate GPU deadline reserves the shutdown GPU time: the
        # funded window must still leave room to stop the pod inside the
        # effective limit (HB-6: 50 s of allowance under a 60 s shutdown
        # reserve is immediate exhaustion, not another 50 s of grace).
        # HC-9: EVERY open window consumes the allowance concurrently and each
        # requires its own shutdown tail - the exhaustion point is when the
        # combined windows plus ALL required shutdown margins reach the limit
        # (the late-contradiction scenario has two open windows at once: the
        # reopened original and the newer generation).
        remaining_gpu_ms = effective_gpu_limit - used_gpu_ms
        consumers = max(open_windows, 1)
        reserved = max(open_windows, 1) * margin_ms
        candidates.append(
            now + timedelta(milliseconds=max((remaining_gpu_ms - reserved) / consumers, 0))
        )
        return min(candidates) if candidates else None

    def _enter_grace(
        self,
        experiment_id: UUID,
        acquisition: dict,
        world: Any,
        *,
        coordinator_token: UUID | None = None,
    ) -> None:
        """§5.4 (SC-5/R3): persist the durable recovery grace BEFORE recovery.

        ``recovery_deadline`` is the EARLIEST of the first ambiguity +
        RECOVERY_GRACE_MAX_S and the HB-6 effective bound (the tighter of the
        plan row and the acquisition's ACCEPTED AUTHORIZATION for the hard
        stop and the aggregate GPU limit, with the shutdown GPU time
        reserved). A restart or takeover never re-grants:
        ``recovery_started_at`` keeps its first value and the deadline may
        only be shortened (SC2-2 keeps it for a later ambiguity).
        """
        now = self.clock.now()
        margin_ms = self._shutdown_margin_ms(world)
        effective = self._effective_recovery_deadline(
            experiment_id, acquisition["acquisition_id"], margin_ms=margin_ms
        )
        candidates = [now + timedelta(seconds=RECOVERY_GRACE_MAX_S)]
        if effective is not None:
            candidates.append(effective)
        deadline = min(candidates)
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT acquisition_id FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                (acquisition["acquisition_id"],),
            )
            if coordinator_token is not None:
                # HB-8: the ambiguity/grace control write applies the
                # matching-token predicate in its OWN transaction - a fenced
                # or replaced coordinator never stamps ambiguity state over
                # the current owner's (its in-flight send's outcome stays
                # with reconciliation, which needs no token).
                self._assert_coordination(
                    tx, experiment_id, acquisition.get("acquisition_id"), coordinator_token
                )
            tx.execute(
                "UPDATE benchmark_acquisitions SET "
                "recovery_started_at=COALESCE(recovery_started_at,%s),"
                "recovery_deadline=COALESCE(LEAST(COALESCE(recovery_deadline,%s),%s),%s) "
                "WHERE acquisition_id=%s",
                (now, deadline, deadline, deadline, acquisition["acquisition_id"]),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
                "WHERE experiment_id=%s",
                (experiment_id,),
            )

    def _mark_submit_ambiguity(
        self,
        experiment_id: UUID,
        acquisition: dict,
        world: Any,
        *,
        coordinator_token: UUID | None = None,
    ):
        """§5.1: a submit/poll ambiguity keeps the acquisition ACTIVE and enters
        the durable grace; the experiment moves to NEEDS_RECONCILIATION in the
        same transaction. The pod stays for recovery - no cleanup here, UNLESS
        the persisted deadline has already elapsed (SC2-2: a later ambiguity
        on the same acquisition reuses it and starts cleanup immediately)."""
        self._enter_grace(experiment_id, acquisition, world, coordinator_token=coordinator_token)
        row = self._recovery_deadline(acquisition["acquisition_id"])
        if row is not None and row["recovery_deadline"] is not None:
            if self.clock.now() >= row["recovery_deadline"]:
                return self.sweep(experiment_id, world=world)
        return self.status(experiment_id)

    def _mark_upload_ambiguity(
        self,
        experiment_id: UUID,
        acquisition: dict | None = None,
        *,
        coordinator_token: UUID | None = None,
    ):
        """§5.1: an upload ambiguity keeps the intent INTENT/UNKNOWN (U3u) and
        the acquisition unlabelled; no prompt operation is invented. The pod
        stays for the checksum readback. HC-5: when a coordinator drove the
        upload, the E control write validates its FULL live ownership (both
        tokens) under the A and D row locks - a fenced or replaced coordinator
        stamps no ambiguity state (takeover handlers stay tokenless, §5.2)."""
        with self.db.transaction() as tx:
            # §6.1: account/categories before the E write.
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            if coordinator_token is not None:
                if acquisition is None:
                    raise Conflict(
                        "an upload ambiguity driven by a coordinator names its acquisition"
                    )
                tx.fetchone(
                    "SELECT acquisition_id FROM benchmark_acquisitions "
                    "WHERE acquisition_id=%s FOR UPDATE",
                    (acquisition["acquisition_id"],),
                )
                tx.fetchone(
                    "SELECT coordinator_token, coordinator_lease_until "
                    "FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                    (experiment_id,),
                )
                self._assert_coordination(
                    tx, experiment_id, acquisition["acquisition_id"], coordinator_token
                )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
                "WHERE experiment_id=%s",
                (experiment_id,),
            )
        return self.status(experiment_id)

    def _mark_create_ambiguity(
        self,
        experiment_id: UUID,
        acquisition: dict,
        world: Any,
        *,
        coordinator_token: UUID | None = None,
    ):
        """§5.1: a create ambiguity labels the acquisition UNKNOWN (no grace)
        and sweeps - the reconciler owns the podless create from here. HC-5:
        when a coordinator drove the create, the A control write validates its
        FULL live ownership (both tokens) under the A and D row locks - a
        stalled original create that returns after takeover and fencing must
        not rewrite its acquisition to UNKNOWN (a newer acquisition may hold
        the partial-index slot; the stale write could collide with it).
        Takeover handlers stay tokenless (§5.2)."""
        with self.db.transaction() as tx:
            # §6.1: E is locked before the A write (account/categories first).
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT acquisition_id FROM benchmark_acquisitions "
                "WHERE acquisition_id=%s FOR UPDATE",
                (acquisition["acquisition_id"],),
            )
            if coordinator_token is not None:
                tx.fetchone(
                    "SELECT coordinator_token, coordinator_lease_until "
                    "FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                    (experiment_id,),
                )
                self._assert_coordination(
                    tx, experiment_id, acquisition["acquisition_id"], coordinator_token
                )
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='UNKNOWN' WHERE acquisition_id=%s",
                (acquisition["acquisition_id"],),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET execution_state='NEEDS_RECONCILIATION' "
                "WHERE experiment_id=%s",
                (experiment_id,),
            )
        return self.sweep(experiment_id, world=world)

    def _advance_owned(self, experiment_id: UUID, world: Any, phase: str, quote: Any, token: UUID):
        import os as _os

        if _os.environ.get("T031_DEBUG"):
            import sys as _sys

            print("DBG advance_owned enter", phase, file=_sys.stderr)
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
        # I3/AT-5: never acquire on an acquisition awaiting finalization.
        if self._needs_finalization(experiment_id, acquisition):
            return self.sweep(experiment_id, world=world)
        with self.db.transaction() as tx:
            # HB-8/§6.1 shared order: account -> categories -> E -> A -> D -
            # the SAME order the R3 fence takes. The previous D-then-A could
            # deadlock against the fence's A-then-D (a worker holding D and
            # waiting for A while the sweep holds A and waits for D). Taking
            # the coordination is itself a control write: it must not
            # resurrect a token the deadline fence revoked, and the values
            # must sit inside a LIVE ownership lease (HB-7).
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            tx.fetchone(
                "SELECT acquisition_id FROM benchmark_acquisitions "
                "WHERE acquisition_id=%s FOR UPDATE",
                (acquisition["acquisition_id"],),
            )
            slot = tx.fetchone(
                "SELECT coordinator_token, coordinator_lease_until "
                "FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            now = self.clock.now()
            # Taking coordination: the slot token must still be this call's
            # own AND inside a live lease (the fence must not have revoked it
            # mid-flight; HB-7). The acquisition row is this transaction's own
            # lease writer - sequential passes retake it (the per-call slot,
            # cleared in _advance's finally, is what preemption protection
            # hangs on).
            if (
                slot is None
                or slot["coordinator_token"] != token
                or slot["coordinator_lease_until"] is None
                or slot["coordinator_lease_until"] <= now
            ):
                raise AdmissionBlocked(
                    ["R3 fence: the coordinator token was revoked at the recovery deadline"]
                )
            tx.execute(
                "UPDATE benchmark_acquisitions SET coordinator_token=%s,coordinator_lease_until=%s WHERE acquisition_id=%s",
                (token, now + timedelta(hours=1), acquisition["acquisition_id"]),
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
            # Dispatch gate before the create send (§4.2): a fresh process never
            # holds a first-send right of its own (SC2-1) - an uncertain create
            # (U1), a reopened liability (U5) or cleanup owed on this acquisition
            # (U2) reconciles instead of dispatching.
            self._gate(
                experiment_id,
                "dispatch",
                coordinator_token=token,
                acquisition_id=acquisition["acquisition_id"],
            )
            try:
                world.acquire(acquisition)
            except NeedsReconciliation:
                # §5.1: a create ambiguity labels the acquisition UNKNOWN and
                # gets NO grace - the sweep's token reconciliation owns it.
                # HC-5: the control write validates this coordinator's live
                # ownership; a stalled create returning after fencing refuses.
                return self._mark_create_ambiguity(
                    experiment_id, acquisition, world, coordinator_token=token
                )
            self._activate_acquisition(
                experiment_id, acquisition["acquisition_id"], coordinator_token=token
            )
            # At most one active prompt. Resume polls operation IDs before any submit.
            for _ in range(24):
                sample = self._claim_sample(
                    experiment_id, world, acquisition, eligible, coordinator_token=token
                )
                if sample is None:
                    return self._finish_phase(experiment_id, world, phase)
                if sample["job_id"] is None:
                    closed = self._close_undispatchable_sample(experiment_id, world, sample)
                    if closed is not None:
                        return closed
                    sample["job_id"] = world.materialize_sample(sample)
                if not sample["operation_id"]:
                    # Dispatch gate before the upload send (§4.2/U3u): an
                    # unverified intent on this acquisition is read-back-only.
                    self._gate(
                        experiment_id,
                        "dispatch",
                        coordinator_token=token,
                        acquisition_id=acquisition["acquisition_id"],
                        sample_id=sample["sample_id"],
                    )
                    try:
                        world.stage_inputs(acquisition)
                    except NeedsReconciliation:
                        # §5.1: an upload ambiguity keeps the intent open (U3u)
                        # and invents no prompt operation; the pod stays for the
                        # checksum readback (§5.3). HC-5: the E control write
                        # validates this coordinator's live ownership.
                        return self._mark_upload_ambiguity(
                            experiment_id, acquisition, coordinator_token=token
                        )
                if sample["operation_id"]:
                    try:
                        result = world.poll(sample)
                    except NeedsReconciliation:
                        return self._mark_submit_ambiguity(
                            experiment_id, acquisition, world, coordinator_token=token
                        )
                else:
                    # Dispatch gate before the prompt send (§4.2/U3).
                    self._gate(
                        experiment_id,
                        "dispatch",
                        coordinator_token=token,
                        acquisition_id=acquisition["acquisition_id"],
                        sample_id=sample["sample_id"],
                    )
                    try:
                        # HC-5: the first-send right is consumed only inside a
                        # transaction that still sees this coordinator's FULL
                        # live ownership (both tokens) - a coordinator fenced
                        # between the dispatch gate and the claim sends
                        # nothing and consumes nothing.
                        result = world.submit(
                            sample,
                            acquisition,
                            send_authorizer=(
                                lambda tx, _token=token, _acq=acquisition["acquisition_id"]: (
                                    self._assert_coordination(tx, experiment_id, _acq, _token)
                                )
                            ),
                        )
                    except NeedsReconciliation:
                        # §5.1/§5.4: the acquisition stays ACTIVE and the
                        # durable grace is persisted before any recovery.
                        return self._mark_submit_ambiguity(
                            experiment_id, acquisition, world, coordinator_token=token
                        )
                self._observe(experiment_id, sample, result, coordinator_token=token)
                state = getattr(result.state, "value", result.state)
                if state not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    return self.status(experiment_id)
                if state != "SUCCEEDED":
                    self.repo.outcome(experiment_id, "FAILED")
                    return self.sweep(experiment_id, world=world)
            return self.status(experiment_id)
        except NeedsReconciliation:
            # Any ambiguity the stage handlers above did not classify (a new
            # call site) keeps the conservative create treatment: labelled
            # UNKNOWN and swept for token reconciliation. HC-5: the control
            # write validates this coordinator's live ownership.
            return self._mark_create_ambiguity(
                experiment_id, acquisition, world, coordinator_token=token
            )
        except AdmissionBlocked as refused:
            # I3: the gate refused inside its locked transaction; nothing was
            # written and nothing dispatched. Return the reconciliation status
            # (with the blockers) instead of failing the experiment.
            status = self.status(experiment_id)
            status["admission"] = {"permitted": False, "blockers": refused.blockers}
            import os as _os

            if _os.environ.get("T031_DEBUG"):
                import sys as _sys

                print("DBG advance blocked", refused.blockers, file=_sys.stderr)
            return status
        except BaseException:
            self.repo.outcome(experiment_id, "FAILED")
            try:
                self.sweep(experiment_id, world=world)
            except Exception:
                pass
            raise

    def _claim_sample(
        self,
        experiment_id: UUID,
        world: Any,
        acquisition: dict,
        eligible: set[str],
        *,
        coordinator_token: UUID | None = None,
    ):
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            exp = experiment_row(tx, experiment_id, lock=True)
            # HC-6: the ONE shared-order helper first (A rows, L, D, S, R, O,
            # uploads); the site's own row reads below re-acquire held rows.
            self._lock_gate_rows(tx, experiment_id)
            tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE acquisition_id=%s FOR UPDATE",
                (acquisition["acquisition_id"],),
            )
            slot = tx.fetchone(
                "SELECT * FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            if coordinator_token is not None:
                # HC-5: a claim is authorised only by the FULL live ownership -
                # BOTH durable tokens (values and live ownership leases), not
                # the slot token's value alone. A returning stale worker may
                # not claim or control anything.
                self._assert_coordination(
                    tx, experiment_id, acquisition["acquisition_id"], coordinator_token
                )
            if slot["sample_id"]:
                # Returning the slot's occupied sample is not a new claim - the
                # in-flight work on it must stay pollable (§4.1 U3p/U4).
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
            # §4.2: a fresh claim re-evaluates the blocking items inside this
            # locked transaction (I3). The occupied-slot path above is exempt:
            # polling existing work is recovery, not admission.
            items = unresolved_items(tx, experiment_id, now=self.clock.now())
            blockers = blocking(
                items,
                "claims",
                acquisition_id=acquisition["acquisition_id"],
                sample_id=sample["sample_id"],
            )
            if blockers:
                raise AdmissionBlocked([item.describe() for item in blockers])
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

    def _observe(
        self,
        experiment_id: UUID,
        sample: dict,
        result: Any,
        *,
        coordinator_token: UUID | None = None,
    ):
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
        # §7.2 mapping: FAILED, CANCELLED and NOT_FOUND all project FAILED with
        # the original reason kept; NOT_FOUND never enables resubmission.
        # Nonterminal observations project as observed (mid-flight states).
        if state in ("FAILED", "CANCELLED", "NOT_FOUND"):
            output = {"error_code": getattr(result, "error_code", None) or "UNKNOWN_FAILURE"}
            projected = "FAILED"
        else:
            projected = state
        with self.db.transaction() as tx:
            # §6.1: E first - this transaction's R6 write updates the
            # experiment row (outcome/fail-fast), so its lock is taken before
            # any later-order row (an E write after D/S could deadlock against
            # the admission gate, which locks E -> ... -> D).
            experiment_row(tx, experiment_id, lock=True)
            # §6.1: D before S - the dispatch slot is locked (and its token
            # re-checked) before any sample projection writes.
            tx.fetchone(
                "SELECT sample_id, coordinator_token FROM benchmark_dispatch_slots "
                "WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            if coordinator_token is not None:
                # R3 + HB-7: projection is a coordinator control write -
                # predicated on BOTH durable tokens (values AND live ownership
                # leases; matching values with a lapsed lease are a stale
                # coordinator). Recovery observes without a token; it never
                # held one.
                self._assert_coordination(
                    tx, experiment_id, sample.get("acquisition_id"), coordinator_token
                )
            # §7.2 monotonic projection: a stale nonterminal observation never
            # overwrites a terminal sample.
            current = tx.fetchone(
                "SELECT state FROM benchmark_samples WHERE experiment_id=%s "
                "AND sample_id=%s FOR UPDATE",
                (experiment_id, sample["sample_id"]),
            )
            if (
                current is not None
                and current["state"] in ("SUCCEEDED", "FAILED")
                and (state not in ("SUCCEEDED", "FAILED", "CANCELLED", "NOT_FOUND"))
            ):
                return
            tx.execute(
                "UPDATE benchmark_samples SET state=%s,operation_id=%s,output=COALESCE(%s,output),coverage=COALESCE(coverage,%s) WHERE experiment_id=%s AND sample_id=%s",
                (
                    projected,
                    result.operation_id,
                    jsonb(output) if output else None,
                    jsonb({"quality": "UNKNOWN"}),
                    experiment_id,
                    sample["sample_id"],
                ),
            )
            if projected in ("SUCCEEDED", "FAILED"):
                tx.execute(
                    "UPDATE benchmark_dispatch_slots SET sample_id=NULL,revision=revision+1 WHERE experiment_id=%s AND sample_id=%s",
                    (experiment_id, sample["sample_id"]),
                )
            if projected == "FAILED":
                # §7.4 fail-fast: however the failure was observed (normal
                # polling included), the outcome is set once and generation
                # stops - in the same transaction as the projection (R6).
                tx.execute(
                    "UPDATE benchmark_experiments SET "
                    "execution_outcome=COALESCE(execution_outcome,'FAILED'),"
                    "execution_state=CASE WHEN execution_outcome IS NULL THEN 'FAILED' "
                    "ELSE execution_state END,revision=revision+1,updated_at=%s "
                    "WHERE experiment_id=%s",
                    (self.clock.now(), experiment_id),
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
        # 1. Identity-checked RECOVERY from durable records, before any
        #    new-generation argument matters (the CLI defers its argument
        #    validation for resume the same way - spec §4.2).
        self.reconcile(experiment_id)
        # Cleanup runs only when it is owed (a U2 item): a healthy ACTIVE
        # acquisition inside its window is never swept mid-run (SC-2).
        with self.db.transaction(readonly=True) as tx:
            owed = any(
                item.kind == "U2"
                for item in unresolved_items(tx, experiment_id, now=self.clock.now())
            )
        if owed:
            self.sweep(experiment_id)
        # 2. Blocking items remaining after reconciliation: return the durable
        #    reconciliation status and dispatch nothing.
        with self.db.transaction(readonly=True) as tx:
            items = unresolved_items(tx, experiment_id, now=self.clock.now())
        item_blockers = [item.describe() for item in blocking(items, "admission")]
        blockers = self._admission_blockers(experiment_id, authorization, quote, expected_sha256)
        if item_blockers or blockers:
            status = dict(self.status(experiment_id))
            status["admission"] = {"permitted": False, "blockers": item_blockers + blockers}
            return status
        # A finished phase has nothing to admit: the durable state is the answer
        # (the derived phase never re-runs a completed screen; a SCREEN_REVIEW
        # WITH a durable PASS derives full and proceeds - §4.2).
        state = self.status(experiment_id)["execution_state"]
        derived = self._derive_phase(experiment_id)
        if state == "COMPUTE_COMPLETE" or (state == "SCREEN_REVIEW" and derived == "screen"):
            status = dict(self.status(experiment_id))
            status["admission"] = {"permitted": True, "blockers": []}
            return status
        try:
            result = self.execute(
                experiment_id,
                phase=derived,
                authorization=authorization,
                quote=quote,
                expected_sha256=expected_sha256,
                source_bytes=source_bytes,
            )
        except AdmissionBlocked as refused:
            # A blocking item appeared between the pre-check and the locked
            # gate (raced writer). Nothing was written; converge idempotently.
            status = dict(self.status(experiment_id))
            status["admission"] = {"permitted": False, "blockers": refused.blockers}
            return status
        except (EffectDenied, PolicyDenied) as refused:
            # HB-10: current authorization/quote/rights eligibility refused the
            # NEW work after recovery completed (e.g. a well-formed but expired
            # quote). The recovered durable status is returned together with
            # the admission blocker - recovery happened; the CLI must not turn
            # this into an error exit.
            status = dict(self.status(experiment_id))
            status["admission"] = {
                "permitted": False,
                "blockers": [f"admission refused ({refused.code})"],
            }
            return status
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

    def _deadline_fence(self, experiment_id: UUID, acquisition_id: UUID) -> bool:
        """R3 deadline fence (§5.4): at ``recovery_deadline`` exhaustion, with
        an ambiguity on this acquisition still unresolved, sweep or the janitor
        first COMMITS the fence - revoke the acquisition's coordinator token
        and the matching dispatch-slot token under the §6.1 lock order - and
        only then runs cleanup outside the transaction.

        This is the explicit exception to "never preempt a valid coordinator".
        Revoking the token never proves an already-authorised external send
        never happened: such effects stay subject to reconciliation and get no
        replacement send right (I2). Every later coordinator control write and
        first-send authorisation checks the matching token in its own
        transaction (``_assert_coordination``)."""
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            acquisition = tx.fetchone(
                "SELECT recovery_deadline FROM benchmark_acquisitions "
                "WHERE acquisition_id=%s FOR UPDATE",
                (acquisition_id,),
            )
            if acquisition is None or acquisition["recovery_deadline"] is None:
                return False
            # HB-6: re-evaluate the effective bound UNDER the fence's locks -
            # liability discovered since persistence (a late adoption, a
            # reopened window) may have exhausted the allowance. The persisted
            # deadline only ever SHORTENS.
            recomputed = self._effective_recovery_deadline(experiment_id, acquisition_id, tx=tx)
            if recomputed is not None and recomputed < acquisition["recovery_deadline"]:
                tx.execute(
                    "UPDATE benchmark_acquisitions SET recovery_deadline=%s "
                    "WHERE acquisition_id=%s",
                    (recomputed, acquisition_id),
                )
                acquisition = {**acquisition, "recovery_deadline": recomputed}
            if self.clock.now() < acquisition["recovery_deadline"]:
                return False
            self._lock_gate_rows(tx, experiment_id)
            items = unresolved_items(tx, experiment_id, now=self.clock.now())
            if not any(
                item.acquisition_id == acquisition_id and item.kind in ("U1", "U3", "U3u")
                for item in items
            ):
                # SC2-2: the fence bites only while an ambiguity on THIS
                # acquisition remains unresolved; a recovered episode's
                # historical deadline never fences later healthy work.
                return False
            tx.execute(
                "UPDATE benchmark_acquisitions SET coordinator_token=NULL,"
                "coordinator_lease_until=NULL WHERE acquisition_id=%s",
                (acquisition_id,),
            )
            tx.execute(
                "UPDATE benchmark_dispatch_slots SET coordinator_token=NULL,"
                "coordinator_lease_until=NULL WHERE experiment_id=%s",
                (experiment_id,),
            )
            return True

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
            # HB-3: when no caller world is supplied, each acquisition composes
            # its own CLEANUP world from its own durable provenance; the
            # variable is per-iteration and never carried to another
            # acquisition (§3.1 one world per acquisition).
            cleanup_world = world
            if acquisition["state"] == "NO_CREATE_PROVEN":
                # R1 (spec §4.1): sweep finalizes these rows too - their
                # exclusion from the partial unique index never authorizes the
                # next acquisition while the STORAGE hold is still open.
                # Contradicted resolutions (U5) get their discovered pod
                # cleaned through the normal shutdown path first; the storage
                # release below then also requires the verified termination.
                with self.db.transaction(readonly=True) as tx:
                    contradicted = tx.fetchval(
                        "SELECT contradicted_at IS NOT NULL FROM runpod_podless_create_resolutions "
                        "WHERE lease_id=%s",
                        (acquisition["lease_id"],),
                    )
                if contradicted and acquisition["lease_id"] is not None:
                    with self.db.transaction(readonly=True) as tx:
                        lease_row = tx.fetchone(
                            "SELECT lease_state, pod_id, terminate_verified_at "
                            "FROM pod_leases WHERE id=%s",
                            (acquisition["lease_id"],),
                        )
                    if lease_row is not None and lease_row["lease_state"] in (
                        "CLAIMED",
                        "ACTIVE",
                        "TRANSFERRING",
                    ):
                        # A live lease with the discovered pod: the normal
                        # shutdown path stops, verifies and settles it.
                        # HB-3: one CLEANUP world PER acquisition - its
                        # provenance, namespace and credentials are the
                        # acquisition's own durable records (§3.2), never the
                        # first acquisition's reused world.
                        cleanup_world = (
                            world
                            if world is not None
                            else self._world(
                                experiment_id,
                                authorization,
                                quote,
                                mode="CLEANUP",
                                acquisition_id=acquisition["acquisition_id"],
                            )
                        )
                        receipt = cleanup_world.cleanup(acquisition)
                        verified = verified and receipt["verified"]
                        billed = billed and receipt["billing_state"] == "BILLED"
                    else:
                        # A TERMINAL lease: the discovered pod's
                        # stop->terminate->verify tail is the janitor's
                        # (shutdown on a terminal lease replays without
                        # stopping anything); the sweep finalizes only against
                        # the durable verified termination, and until then U5
                        # keeps the storage held (I4 - provider failure can
                        # delay verified termination, never declare it).
                        done = bool(lease_row and lease_row["terminate_verified_at"])
                        verified = verified and done
                        billed = billed and done
                else:
                    with self.db.transaction(readonly=True) as tx:
                        live_lease = (
                            tx.fetchval(
                                "SELECT l.lease_state FROM pod_leases l WHERE l.id=%s "
                                "AND l.lease_state IN ('CLAIMED','ACTIVE','TRANSFERRING')",
                                (acquisition["lease_id"],),
                            )
                            if acquisition["lease_id"] is not None
                            else None
                        )
                    if live_lease:
                        # The proven-no-create lease is still live: close it through
                        # the canonical podless shutdown (U2; the pilot single-live-
                        # lease rule forbids any new lease until it is RELEASED).
                        cleanup_world = (
                            world
                            if world is not None
                            else self._world(
                                experiment_id,
                                authorization,
                                quote,
                                mode="CLEANUP",
                                acquisition_id=acquisition["acquisition_id"],
                            )
                        )
                        cleanup_world.leases.shutdown(
                            acquisition["lease_id"],
                            reason="benchmark proven-no-create lease close",
                        )
                budget = (
                    cleanup_world.budget
                    if cleanup_world is not None
                    else ExperimentBudgetService(
                        self.db,
                        self.clock,
                        self.ids,
                        self.settings,
                        experiment_id=experiment_id,
                    )
                )
                # §6.3: ONLY this finalization transaction may release the
                # acquisition's single original STORAGE hold, and it re-checks
                # under the §6.1 locks: the acquisition is still
                # NO_CREATE_PROVEN, an uncontradicted no-create proof or a
                # verified termination of the discovered pod (with its storage
                # ownership closed AND its canonical invoice final - HC-1: the
                # pre-contradiction zero settlement is never billing
                # evidence), the lease is no longer live, and no U5 remains
                # for it. HC-6: the ONE shared-order helper locks the lease row
                # (L) this decision reads inside the locked finalization - the
                # previous FOR UPDATE OF a join read the lease row without
                # locking it - plus D, S and R before any release.
                # HC-1: the EXPIRED financial closure runs INSIDE this same
                # decision - zero-settling the EXPIRED STORAGE hold before it
                # (including for a contradicted acquisition whose discovered
                # pod's disk invoice was still pending) discharged liability
                # the decision had not yet proven final.
                with self.db.transaction() as tx:
                    exp = experiment_row(tx, experiment_id)
                    lock_account(tx, exp["account_id"])
                    lock_categories(tx, exp["account_id"])
                    experiment_row(tx, experiment_id, lock=True)
                    self._lock_gate_rows(tx, experiment_id)
                    current = tx.fetchone(
                        "SELECT a.state, l.lease_state, l.terminate_verified_at "
                        "FROM benchmark_acquisitions a LEFT JOIN pod_leases l "
                        "ON l.id=a.lease_id WHERE a.acquisition_id=%s FOR UPDATE OF a",
                        (acquisition["acquisition_id"],),
                    )
                    contradiction = tx.fetchone(
                        "SELECT contradicted_at IS NOT NULL AS contradicted "
                        "FROM runpod_podless_create_resolutions WHERE lease_id=%s",
                        (acquisition["lease_id"],),
                    )
                    ownership_open = tx.fetchval(
                        "SELECT 1 FROM pod_storage_ownership o JOIN pod_leases l "
                        "ON l.provider=o.provider AND l.pod_id=o.pod_id "
                        "WHERE l.id=%s AND o.valid_until IS NULL",
                        (acquisition["lease_id"],),
                    )
                    finalizable = current is not None and current["state"] == "NO_CREATE_PROVEN"
                    if contradiction is not None and contradiction["contradicted"]:
                        # HC-1 (ruling 2): "billing ready" for the CONTRADICTED
                        # case is the canonical invoice finality of the
                        # DISCOVERED RESOURCE - readiness BILLED with no
                        # reopened liability, or a reopened window covered by
                        # MATCHED invoice evidence. The compute reservation's
                        # SETTLED state is never evidence (the podless
                        # resolution settled it at zero BEFORE the
                        # contradiction, while the discovered pod's disk and
                        # compute invoices may still be pending).
                        readiness_billed = False
                        if current["terminate_verified_at"] is not None and not ownership_open:
                            lease_full = tx.fetchone(
                                "SELECT * FROM pod_leases WHERE id=%s",
                                (acquisition["lease_id"],),
                            )
                            readiness_billed = (
                                lease_full is not None
                                and lease_full["pod_id"] is not None
                                and discovered_resource_billing_final(tx, lease_full)
                            )
                        finalizable = finalizable and readiness_billed
                    elif current is not None and current["lease_state"] in (
                        "CLAIMED",
                        "ACTIVE",
                        "TRANSFERRING",
                    ):
                        finalizable = False
                    if finalizable:
                        ids = tx.fetchall(
                            "SELECT r.id,r.state FROM benchmark_reservation_links l "
                            "JOIN reservations r ON r.id=l.reservation_id "
                            "WHERE l.acquisition_id=%s AND l.purpose='STORAGE' "
                            "ORDER BY r.id FOR UPDATE OF r",
                            (acquisition["acquisition_id"],),
                        )
                        for row in ids:
                            if row["state"] == "ACTIVE":
                                budget.release_in_transaction(
                                    tx,
                                    row["id"],
                                    reason="benchmark proven-no-create storage hold finalized (R1)",
                                )
                            elif row["state"] == "EXPIRED":
                                # HC-1: the EXPIRED financial closure rides the
                                # same locked decision (I4: never a release);
                                # the deterministic receipt makes a race with
                                # the locked release replay.
                                budget.settle_expired_unused_hold_in_tx(
                                    tx,
                                    row["id"],
                                    reason="benchmark proven-no-create storage hold expired unused (R1)",
                                )
                    tx.execute(
                        "UPDATE benchmark_acquisitions SET "
                        "compute_window_end=COALESCE(compute_window_end,create_intent_at) "
                        "WHERE acquisition_id=%s",
                        (acquisition["acquisition_id"],),
                    )
                continue
            # R3 deadline fence (§5.4): at deadline exhaustion with an
            # unresolved ambiguity on this acquisition, commit the cleanup
            # fence FIRST - revoke the acquisition coordinator token and the
            # matching dispatch-slot token under the §6.1 order - so cleanup
            # then runs outside the transaction against a fenced coordinator.
            self._deadline_fence(experiment_id, acquisition["acquisition_id"])
            # The world is composed lazily, per acquisition needing it: an
            # acquisition-less experiment never constructs one (spec §3.2).
            # HB-3: composed lazily but PER acquisition (initialized at the
            # top of each iteration) - never retained for later acquisitions.
            if cleanup_world is None:
                cleanup_world = self._world(
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
                acquisition["lease_id"] = cleanup_world.materialize_acquisition(acquisition)
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE benchmark_acquisitions SET lease_id=%s WHERE acquisition_id=%s",
                        (acquisition["lease_id"], acquisition["acquisition_id"]),
                    )
            receipt = cleanup_world.cleanup(acquisition)
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
                # HC-6: the ONE shared-order helper (A, L, D, S, R, then O and
                # uploads) - the upload-fence, sample, slot and reservation
                # writes below all touch rows locked in the shared order; the
                # previous shape locked the STORAGE reservations (R) before the
                # upload rows and wrote D/S after both.
                self._lock_gate_rows(tx, experiment_id)
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
                            cleanup_world.budget.release_in_transaction(
                                tx,
                                row["id"],
                                reason="benchmark storage deletion and invoice finality verified",
                            )
                if receipt["verified"]:
                    # HB-12/§5.3: the fenced failure path for unrecoverable
                    # uploads. The verified cleanup removed the pod (and its
                    # server with it): an upload intent still open can NEVER
                    # verify by readback again. Its send right is durably
                    # fenced here, the affected samples fail under §7.4 (the
                    # outcome is set once; generation stops), and their
                    # positively-unused prompt holds are released. Liability
                    # was retained through the cleanup; U3u stops blocking
                    # only NOW, with the episode finalized.
                    open_intents = tx.fetchall(
                        "SELECT asset_sha256 FROM benchmark_uploads "
                        "WHERE acquisition_id=%s AND state IN ('INTENT','UNKNOWN')",
                        (acquisition["acquisition_id"],),
                    )
                    if open_intents:
                        tx.execute(
                            "UPDATE benchmark_uploads SET state='FENCED' "
                            "WHERE acquisition_id=%s AND state IN ('INTENT','UNKNOWN')",
                            (acquisition["acquisition_id"],),
                        )
                        stuck = tx.fetchall(
                            "SELECT sample_id, reservation_id FROM benchmark_samples "
                            "WHERE acquisition_id=%s AND state NOT IN ('SUCCEEDED','FAILED') "
                            "AND reservation_id IS NOT NULL",
                            (acquisition["acquisition_id"],),
                        )
                        now = self.clock.now()
                        for row in stuck:
                            tx.execute(
                                "UPDATE benchmark_samples SET state='FAILED',"
                                "output=COALESCE(output,%s) WHERE experiment_id=%s "
                                "AND sample_id=%s",
                                (
                                    jsonb({"error_code": "UPLOAD_UNRECOVERABLE"}),
                                    experiment_id,
                                    row["sample_id"],
                                ),
                            )
                            tx.execute(
                                "UPDATE benchmark_dispatch_slots SET sample_id=NULL,"
                                "revision=revision+1 WHERE experiment_id=%s AND sample_id=%s",
                                (experiment_id, row["sample_id"]),
                            )
                            tx.execute(
                                "UPDATE benchmark_experiments SET "
                                "execution_outcome=COALESCE(execution_outcome,'FAILED'),"
                                "execution_state=CASE WHEN execution_outcome IS NULL "
                                "THEN 'FAILED' ELSE execution_state END,"
                                "revision=revision+1,updated_at=%s WHERE experiment_id=%s",
                                (now, experiment_id),
                            )
                    # The fenced samples' prompt holds are positively unused
                    # (no operation was ever dispatched for them): released IN
                    # this transaction (a nested standalone release would
                    # self-deadlock on the locks already held here).
                    for row in tx.fetchall(
                        "SELECT s.sample_id, s.reservation_id FROM benchmark_samples s "
                        "WHERE s.acquisition_id=%s AND s.state='FAILED' "
                        "AND s.output->>'error_code'='UPLOAD_UNRECOVERABLE'",
                        (acquisition["acquisition_id"],),
                    ):
                        try:
                            cleanup_world.budget.release_in_transaction(
                                tx,
                                row["reservation_id"],
                                reason=(
                                    "benchmark upload unrecoverable after verified "
                                    f"cleanup (sample {row['sample_id']})"
                                ),
                            )
                        except Conflict:
                            pass  # already terminal - a replay converges
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
        # §4.1/SC-3: an uncertain create is selected by its canonical predicate
        # (committed create intent, no pod, no resolution) - NOT by the
        # acquisition label. A worker that died before the ambiguity handler
        # wrote anything still reconciles by its durable token (AT-13).
        with self.db.transaction(readonly=True) as tx:
            derived_items = unresolved_items(tx, experiment_id, now=self.clock.now())
            derived_u1 = {item.acquisition_id for item in derived_items if item.kind == "U1"}
            upload_acquisitions = {
                item.acquisition_id for item in derived_items if item.kind == "U3u"
            }
        by_id = {a["acquisition_id"]: a for a in status["acquisitions"]}
        unknown = [
            by_id[acquisition_id]
            for acquisition_id in (
                derived_u1
                | {a["acquisition_id"] for a in status["acquisitions"] if a["state"] == "UNKNOWN"}
            )
            if acquisition_id in by_id
        ]
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
        # §5.3: existing upload intents reconcile ONLY by checksum-verified
        # input readback (/view?type=input) through the recovery world - never
        # a second upload POST, never an invented prompt operation. An
        # unverifiable readback leaves the U3u item blocking every dependent
        # sample until cleanup or an audited resolution.
        for acquisition_id in sorted(upload_acquisitions):
            acquisition = by_id.get(acquisition_id)
            if acquisition is None:
                continue
            per = world
            if per is None:
                per = self._world(
                    experiment_id,
                    authorization,
                    quote,
                    mode="RECOVERY",
                    acquisition_id=acquisition_id,
                )
            self._heartbeat_grace(experiment_id, per, acquisition_id)
            if hasattr(per, "bind_for_recovery"):
                try:
                    per.bind_for_recovery(acquisition_id)
                except Exception:  # noqa: BLE001 - best-effort binding, item stays blocked
                    pass
            # HC-9: recompute the bound under the locks before the readback
            # work; an exhausted episode routes through the fenced cleanup.
            deadline = self._shorten_recovery_deadline(
                experiment_id, acquisition_id, margin_ms=self._shutdown_margin_ms(per)
            )
            if deadline is not None and self.clock.now() >= deadline:
                return self.sweep(experiment_id, world=world)
            bound = self._recovery_request_bound(experiment_id, acquisition_id)
            try:
                if bound is not None:
                    with bound:
                        per.reconcile_uploads(acquisition)
                else:
                    per.reconcile_uploads(acquisition)
            except (NeedsReconciliation, EffectDenied, Conflict):
                # Unverifiable readback: the intent stays open (U3u) and the
                # dependent samples stay blocked; nothing was re-sent.
                unresolved.append(str(acquisition_id))
        if not unresolved and slot_stuck:
            per = world
            if per is None:
                # HB-3: slot recovery derives the acquisition from the sample it
                # recovers - its world composes from THAT acquisition's durable
                # provenance (§3.2), never from supplied new-generation docs.
                with self.db.transaction(readonly=True) as tx:
                    slot_acquisition = tx.fetchval(
                        "SELECT s.acquisition_id FROM benchmark_dispatch_slots d "
                        "JOIN benchmark_samples s ON s.experiment_id=d.experiment_id "
                        "AND s.sample_id=d.sample_id WHERE d.experiment_id=%s",
                        (experiment_id,),
                    )
                per = self._world(
                    experiment_id,
                    authorization,
                    quote,
                    mode="RECOVERY",
                    acquisition_id=slot_acquisition,
                )
            self._reconcile_slot_sample(experiment_id, per)
        # §7.1: reconcile runs finalize_terminal for every U4 item - a terminal
        # operation whose settlement/projection/slot work is incomplete (a
        # crash between the terminal commit and the finalization). Network-free
        # and idempotent: a replay repairs the same outcome.
        with self.db.transaction(readonly=True) as tx:
            u4_items = [
                item
                for item in unresolved_items(tx, experiment_id, now=self.clock.now())
                if item.kind == "U4" and item.operation_id is not None
            ]
        u4_worlds: dict[UUID | None, Any] = {}
        for item in u4_items:
            per = world
            if per is None:
                # HB-3 (§3.1): a RECOVERY world NAMES the acquisition whose
                # durable records it recovers - an acquisition-less recovery
                # world refuses when acquisitions exist. One world per
                # acquisition (the comfy client never rebinds), reused across
                # that acquisition's U4 items.
                per = u4_worlds.get(item.acquisition_id)
                if per is None:
                    per = self._world(
                        experiment_id,
                        authorization,
                        quote,
                        mode="RECOVERY",
                        acquisition_id=item.acquisition_id,
                    )
                    u4_worlds[item.acquisition_id] = per
            self.finalize_terminal(item.operation_id, world=per)
        # HB-5 (§5.4): cleanup STARTS at the deadline even when intermediate
        # recovery reads failed - an exhausted deadline with an unresolved
        # ambiguity is an owed U2, and reconcile routes it through the sweep's
        # R3 fence + cleanup exactly like the janitor would.
        with self.db.transaction(readonly=True) as tx:
            owed = any(
                item.kind == "U2"
                for item in unresolved_items(tx, experiment_id, now=self.clock.now())
            )
        if owed:
            return self.sweep(experiment_id, world=world)
        with self.db.transaction() as tx:
            # HB-9: the NEEDS_RECONCILIATION -> running transition is
            # predicated on ZERO canonical blocking items (every kind except
            # U6's local materialization), evaluated through the common
            # repository function UNDER the full §6.1 gate locks - the
            # separate label/slot/upload conditions missed, e.g., a U5 that
            # survives a late adoption while all three are clear.
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            exp = experiment_row(tx, experiment_id, lock=True)
            self._lock_gate_rows(tx, experiment_id)
            items = unresolved_items(tx, experiment_id, now=self.clock.now())
            canonical_blockers = [
                item for item in items if item.kind in ("U1", "U2", "U3", "U3p", "U3u", "U4", "U5")
            ]
            if exp["execution_state"] == "NEEDS_RECONCILIATION" and not canonical_blockers:
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
        """Whether the dispatch slot holds a sample whose operation is UNKNOWN
        or still in flight (U3/U3p - recovery owns both)."""
        with self.db.transaction(readonly=True) as tx:
            operation = tx.fetchval(
                "SELECT o.state FROM benchmark_dispatch_slots d "
                "JOIN benchmark_samples s ON s.experiment_id=d.experiment_id "
                "AND s.sample_id=d.sample_id "
                "LEFT JOIN provider_operations o ON o.reservation_id=s.reservation_id "
                "WHERE d.experiment_id=%s",
                (experiment_id,),
            )
        return operation in ("UNKNOWN", "SUBMITTED", "RUNNING", "PENDING_SUBMIT")

    def _uploads_open(self, experiment_id: UUID) -> bool:
        """Whether any upload intent lacks its checksum-verified readback (U3u)."""
        with self.db.transaction(readonly=True) as tx:
            open_uploads = tx.fetchval(
                "SELECT COUNT(*) FROM benchmark_uploads u "
                "JOIN benchmark_acquisitions a ON a.acquisition_id=u.acquisition_id "
                "WHERE a.experiment_id=%s AND u.state IN ('INTENT','UNKNOWN')",
                (experiment_id,),
            )
        return bool(open_uploads)

    def _recovery_deadline(self, acquisition_id: UUID):
        """The persisted §5.4 grace deadline of this acquisition, if any."""
        with self.db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT recovery_started_at, recovery_deadline, lease_id "
                "FROM benchmark_acquisitions WHERE acquisition_id=%s",
                (acquisition_id,),
            )
        return row

    def _heartbeat_grace(self, experiment_id: UUID, world: Any, acquisition_id: UUID) -> None:
        """§5.4 during grace: heartbeat the owned lease - proof of life only.

        The heartbeat extends NOTHING: not the lease expiry, not any
        reservation and not the GPU window (``PodLeaseService.heartbeat``
        writes ``heartbeat_at`` alone), and canonical lease usage keeps
        accruing through the ordinary billing path."""
        row = self._recovery_deadline(acquisition_id)
        if row is None or row["recovery_deadline"] is None or row["lease_id"] is None:
            return
        if self.clock.now() >= row["recovery_deadline"]:
            return
        try:
            world.leases.heartbeat(row["lease_id"])
        except Exception:  # noqa: BLE001 - a terminal/foreign lease simply is not heartbeatable
            pass

    def _recovery_request_bound(self, experiment_id: UUID, acquisition_id: UUID):
        """§5.4: bound every nested recovery HTTP request by the time left
        before the persisted ``recovery_deadline`` (R3: absolute timestamps).

        Returns a context manager, or None when this acquisition has no
        persisted grace (nothing to bound by)."""
        from contextlib import contextmanager

        from microdrama.rendering.diagnostics import (
            reset_request_deadline,
            set_request_deadline,
        )

        row = self._recovery_deadline(acquisition_id)
        deadline = row["recovery_deadline"] if row is not None else None
        if deadline is None:
            return None

        @contextmanager
        def _bound():
            token = set_request_deadline(deadline, self.clock.now)
            try:
                yield
            finally:
                reset_request_deadline(token)

        return _bound()

    def _shorten_recovery_deadline(
        self,
        experiment_id: UUID,
        acquisition_id: UUID,
        *,
        margin_ms: int | None = None,
    ):
        """HC-9 (R3): recompute the effective deadline UNDER the §6.1 locks
        before bounded recovery work, persist ONLY a shortening, and return
        the effective deadline.

        Liability discovered since the episode was persisted (a late
        adoption's reopened window, a second open acquisition) can exhaust the
        remaining allowance BEFORE the stored deadline: ordinary recovery must
        not keep polling against a stale, longer bound. The caller fences
        immediately when the returned deadline has already elapsed."""
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            current = tx.fetchone(
                "SELECT recovery_deadline FROM benchmark_acquisitions "
                "WHERE acquisition_id=%s FOR UPDATE",
                (acquisition_id,),
            )
            if current is None or current["recovery_deadline"] is None:
                return None
            recomputed = self._effective_recovery_deadline(
                experiment_id, acquisition_id, tx=tx, margin_ms=margin_ms
            )
            deadline = current["recovery_deadline"]
            if recomputed is not None and recomputed < deadline:
                tx.execute(
                    "UPDATE benchmark_acquisitions SET recovery_deadline=%s "
                    "WHERE acquisition_id=%s",
                    (recomputed, acquisition_id),
                )
                deadline = recomputed
            return deadline

    def _reconcile_slot_sample(self, experiment_id: UUID, world: Any) -> None:
        """Reconcile the dispatched sample's operation by durable identity.

        An UNKNOWN operation is re-sought by its deterministic client identity
        (never re-POSTed). A known in-flight operation (U3p, §4.1 R2) is
        POLLED - recovery adopts the existing linkage and polls it before any
        other sample or acquisition may start - after binding the recovery
        client to the durable pod when binding is required.
        """
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
        if sample is None or operation is None:
            return
        if operation["state"] not in ("UNKNOWN", "SUBMITTED", "RUNNING", "PENDING_SUBMIT"):
            return
        if operation["state"] == "PENDING_SUBMIT":
            # §5.2 (SC-4): only a TAKEOVER may convert it - the coordinator
            # token must be gone or expired; a live coordinator is never
            # preempted. PENDING_SUBMIT alone never proves the send did not
            # happen (I2), so it becomes UNKNOWN with every hold retained.
            with self.db.transaction(readonly=True) as tx:
                slot = tx.fetchone(
                    "SELECT coordinator_token, coordinator_lease_until "
                    "FROM benchmark_dispatch_slots WHERE experiment_id=%s",
                    (experiment_id,),
                )
            live_coordinator = (
                slot is not None
                and slot["coordinator_token"] is not None
                and slot["coordinator_lease_until"] is not None
                and slot["coordinator_lease_until"] > self.clock.now()
            )
            if live_coordinator:
                return
            world.comfy.mark_operation_unknown(operation["id"])
            operation = {**operation, "state": "UNKNOWN"}
            # HB-5: the takeover DISCOVERED a submit ambiguity - it enters the
            # same durable classification and grace the dispatch-time handler
            # would have written (§5.1/§5.4), BEFORE recovery proceeds: a
            # worker that died before its handler ran left no deadline, and
            # without one the blocking operation would never bound its
            # episode. Idempotent and shorten-only on later episodes.
            if sample.get("acquisition_id") is not None:
                self._enter_grace(
                    experiment_id, {"acquisition_id": sample["acquisition_id"]}, world
                )
                row = self._recovery_deadline(sample["acquisition_id"])
                if (
                    row is not None
                    and row["recovery_deadline"] is not None
                    and self.clock.now() >= row["recovery_deadline"]
                ):
                    # SC2-2: the reused/persisted deadline has already elapsed -
                    # cleanup starts immediately (reconcile's owed-U2 sweep runs
                    # it); no doomed bounded lookup against a dead window.
                    return
        # HB-2: bind the owning acquisition's durable pod BEFORE both the
        # UNKNOWN client-id lookup and the known-id poll - a fresh recovery
        # client is unbound and its first authenticated call would refuse
        # (the effect was then silently swallowed and the accepted prompt
        # stayed unrecovered). The §3.4 result is handled explicitly: only
        # BOUND may reconcile; VERIFIED_SOURCE_GONE/INDETERMINATE leave the
        # item blocked - nothing adopted, nothing re-sent.
        if hasattr(world, "bind_for_recovery") and sample.get("acquisition_id") is not None:
            try:
                binding = world.bind_for_recovery(sample["acquisition_id"])
            except Exception:
                binding = "INDETERMINATE"
            if binding != "BOUND":
                # HC-8: a failed binding still owns its durable ambiguity
                # episode. An UNKNOWN operation whose pod cannot be bound (the
                # worker died before its handler, or the pod is temporarily
                # unreachable) gets the SAME bounded episode the discovery
                # handlers write - without it, repeated public recovery leaves
                # the item blocked with no persisted deadline and no
                # deadline-driven cleanup (HB-5's exit gap). In-flight work a
                # live pod cannot currently bind gets the episode too: SC2-2
                # reuses it for the later ambiguity, and the fence only bites
                # while an ambiguity is unresolved. Idempotent, shorten-only.
                self._enter_grace(
                    experiment_id, {"acquisition_id": sample["acquisition_id"]}, world
                )
                row = self._recovery_deadline(sample["acquisition_id"])
                if (
                    row is not None
                    and row["recovery_deadline"] is not None
                    and self.clock.now() >= row["recovery_deadline"]
                ):
                    # SC2-2: the episode is already exhausted - route through
                    # the fenced cleanup sweep instead of a doomed bounded
                    # lookup against a dead window.
                    return self.sweep(experiment_id, world=world)
                return
        # §5.4/SC2-2 (HB-4): the grace heartbeat and request bound apply
        # ONLY while an ambiguity on this acquisition is unresolved (the
        # operation is UNKNOWN - including a PENDING_SUBMIT just taken over).
        # A healthy SUBMITTED/RUNNING poll after an earlier episode recovered
        # successfully is NOT bounded by the historical deadline: its ordinary
        # execution limits (hold, lease and hard-stop windows) still apply
        # independently. The persisted timestamp itself is kept for a later
        # ambiguity (SC2-2 reuse), which may only shorten it.
        if sample.get("acquisition_id") is not None and operation["state"] == "UNKNOWN":
            # HC-9: recompute the effective deadline under the locks BEFORE
            # the bounded work - liability discovered since the episode was
            # persisted may have exhausted the allowance. An exhausted
            # episode routes through the fenced cleanup sweep immediately.
            deadline = self._shorten_recovery_deadline(
                experiment_id,
                sample["acquisition_id"],
                margin_ms=self._shutdown_margin_ms(world),
            )
            if deadline is not None and self.clock.now() >= deadline:
                return self.sweep(experiment_id, world=world)
            # during grace: heartbeat the owned lease (never extending
            # anything) and bound every nested recovery HTTP request by the
            # time left before the persisted recovery_deadline.
            self._heartbeat_grace(experiment_id, world, sample["acquisition_id"])
            bound = self._recovery_request_bound(experiment_id, sample["acquisition_id"])
        else:
            bound = None
        try:
            if bound is not None:
                with bound:
                    result = (
                        world.comfy.reconcile_unknown(operation["id"])
                        if operation["state"] == "UNKNOWN"
                        else world.comfy.poll(operation["id"])
                    )
            else:
                result = (
                    world.comfy.reconcile_unknown(operation["id"])
                    if operation["state"] == "UNKNOWN"
                    else world.comfy.poll(operation["id"])
                )
        except Conflict as exc:
            # HB-14 (§5.2 rule 3): a multi-match conflict from the
            # deterministic client-id finder is a DISTINCT diagnostic - it is
            # durably recorded (bounded, nonsecret: the exception's own code
            # and message carry only the client id and match count), so the
            # operator sees WHY the operation stays UNKNOWN with its exposure
            # instead of an ordinary unresolved item. Nothing is adopted and
            # nothing re-sent.
            from microdrama.core.events import append_event

            detail = f"{getattr(exc, 'code', 'CONFLICT')}: {exc}"[:200]
            try:
                with self.db.transaction() as tx:
                    append_event(
                        tx,
                        aggregate_type="provider_operation",
                        aggregate_id=operation["id"],
                        event_type="provider_operation.reconcile_conflict",
                        payload={"detail": detail},
                        correlation_id=sample["reservation_id"],
                        occurred_at=self.clock.now(),
                    )
            except Exception:  # noqa: BLE001 - the diagnostic never blocks recovery
                pass
            if sample.get("acquisition_id") is not None:
                if operation["state"] in ("SUBMITTED", "RUNNING"):
                    try:
                        world.comfy.mark_operation_unknown(operation["id"])
                    except Exception:
                        pass
                try:
                    self._enter_grace(
                        experiment_id, {"acquisition_id": sample["acquisition_id"]}, world
                    )
                except Exception:
                    pass
            return
        except (NeedsReconciliation, EffectDenied):
            # Stays ambiguous (or unbindable in this world): the item keeps
            # blocking; nothing is adopted and nothing re-sent.
            # HB-5: a NeedsReconciliation raised while polling a positively
            # in-flight operation is the §5.1 poll-ambiguity classification -
            # the op moves to UNKNOWN under the lock (its prompt id kept) -
            # and EVERY discovery exit persists the durable grace, so the
            # bounded episode exists even when the original worker died
            # before its handler wrote anything (idempotent, shorten-only).
            if sample.get("acquisition_id") is not None:
                if operation["state"] in ("SUBMITTED", "RUNNING"):
                    try:
                        world.comfy.mark_operation_unknown(operation["id"])
                    except Exception:
                        pass
                try:
                    self._enter_grace(
                        experiment_id, {"acquisition_id": sample["acquisition_id"]}, world
                    )
                except Exception:
                    pass
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
        """§6.2: the audited OPERATOR resolution for an uncertain pod create.

        ONE transaction in the §6.1 order (account -> categories -> E -> A ->
        billing advisory -> L). Replay first (SC2-3): an existing uncontradicted
        resolution with an identical actor, reason and evidence SHA returns a
        successful replay with no new audit or settlement; a different
        attestation, a bound pod, or a contradicted resolution is a Conflict.
        A FIRST resolution re-checks under lock (A UNKNOWN or the label-free U1
        predicate, no pod, not contradicted), then calls the canonical
        ``resolve_podless_create_in_tx`` (audit, window end, zero-BILLED compute
        settlement) and writes NO_CREATE_PROVEN. The STORAGE hold is NOT
        released here - only the sweep finalization (§6.3) may release it.
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
        repository = BillingRepository(
            self.db, budget_service=BudgetService(self.db, self.clock, self.ids, self.settings)
        )
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            acquisition = tx.fetchone(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s "
                "AND acquisition_id=%s FOR UPDATE",
                (experiment_id, acquisition_id),
            )
            if acquisition is None:
                raise NotFound("benchmark acquisition not found")
            # HC-6/§6.1 step 5: the billing advisory comes BEFORE the L rows -
            # the same order the canonical wrapper takes. The advisory key is
            # billing.py's own (resolve_podless_create_in_tx re-takes it
            # re-entrantly inside this transaction; xact locks are re-entrant).
            if acquisition["lease_id"] is not None:
                tx.fetchval(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 451051))",
                    (str(acquisition["lease_id"]),),
                )
            lease = (
                tx.fetchone(
                    "SELECT * FROM pod_leases WHERE id=%s FOR UPDATE", (acquisition["lease_id"],)
                )
                if acquisition["lease_id"] is not None
                else None
            )
            resolution = (
                tx.fetchone(
                    "SELECT actor_ref, reason, evidence_sha256, contradicted_at "
                    "FROM runpod_podless_create_resolutions WHERE lease_id=%s",
                    (lease["id"],),
                )
                if lease is not None
                else None
            )
            if resolution is not None:
                # SC2-3 replay: before any unresolved-state precondition, and
                # only for the identical attestation on an uncontradicted,
                # podless resolution.
                if resolution["contradicted_at"] is not None:
                    raise Conflict(
                        "the no-create resolution was contradicted by a later pod; "
                        "the incident path (U5) owns this acquisition",
                        lease_id=str(lease["id"]),
                    )
                if lease["pod_id"] is not None:
                    raise Conflict(
                        "a pod is bound to the lease; the resolution cannot replay",
                        lease_id=str(lease["id"]),
                        pod_id=lease["pod_id"],
                    )
                if (
                    resolution["actor_ref"],
                    resolution["reason"],
                    resolution["evidence_sha256"],
                ) != (actor_ref.strip(), reason.strip(), evidence_sha256):
                    raise Conflict(
                        "a different attestation for the same resolution is a conflict",
                        lease_id=str(lease["id"]),
                    )
            else:
                if lease is not None and lease["pod_id"] is not None:
                    raise Conflict(
                        "the acquisition's lease has a Pod attached; reconcile adopts it",
                        pod_id=lease["pod_id"],
                    )
                # §4.1 U1 is label-independent: the audited resolution accepts
                # the canonical predicate (committed create intent, no pod, no
                # resolution) even when the ambiguity handler never labelled the
                # acquisition UNKNOWN (AT-13's crash-before-label state).
                u1_holds = (
                    lease is not None
                    and lease["create_requested_at"] is not None
                    and lease["pod_id"] is None
                )
                if acquisition["state"] != "UNKNOWN" and not u1_holds:
                    raise Conflict(
                        "only an uncertain (U1) create can be resolved as podless",
                        acquisition_state=acquisition["state"],
                    )
                # Locks 1-5 are held: the canonical core runs inside this
                # transaction (audit, window end, zero-BILLED compute
                # settlement); on replay its receipt id makes it a no-op.
                repository.resolve_podless_create_in_tx(
                    tx,
                    acquisition["lease_id"],
                    actor_ref=actor_ref,
                    reason=reason,
                    evidence_sha256=evidence_sha256,
                    now=self.clock.now(),
                )
            tx.execute(
                "UPDATE benchmark_acquisitions SET state='NO_CREATE_PROVEN',"
                "compute_window_end=COALESCE(compute_window_end,create_intent_at) "
                "WHERE acquisition_id=%s",
                (acquisition_id,),
            )
            # §6.2 step 4 / §6.3: the STORAGE hold is NEVER released here. It
            # is released only by the sweep finalization transaction, after its
            # locked re-checks (R1); with nothing to delete, that finalization
            # can run immediately after the resolution, in a later sweep.
            # §4.2: no shortcut write back to a running state here - reconcile
            # is the only NEEDS_RECONCILIATION -> running writer, and only with
            # zero blocking items under the lock.
        return self.status(experiment_id)

    def finalize_terminal(self, operation_id: UUID, *, world: Any = None) -> None:
        """§7.1 + R6 (spec v3 §7): network-free, idempotent terminal finalization.

        1. Complete the canonical settlement/release for the operation's
           reservation (deterministic receipts; a replay is a no-op).
        2. Load the existing durable outputs (nothing is fetched - only results
           already persisted on the operation row count).
        3+4. Project the sample and clear the matching dispatch slot in ONE
           transaction, D before S, monotonically (a stale nonterminal
           observation never overwrites a terminal sample). R6: projecting an
           eligible failed fixed sample sets ``execution_outcome=FAILED`` if
           unset and stops generation in the SAME transaction.
        """
        with self.db.transaction(readonly=True) as tx:
            operation = tx.fetchone(
                "SELECT o.*, s.experiment_id, s.sample_id, s.acquisition_id "
                "FROM provider_operations o "
                "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
                "WHERE o.id=%s",
                (operation_id,),
            )
        if operation is None or operation["state"] not in (
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "NOT_FOUND",
        ):
            return
        experiment_id = operation["experiment_id"]
        if world is None:
            # HB-3 (§3.1): the recovery world names the acquisition whose
            # operation is being finalized.
            world = self._world(
                experiment_id, mode="RECOVERY", acquisition_id=operation["acquisition_id"]
            )
        # 1. Financial finalization first, from durable state alone.
        world.comfy.settle_terminal(operation_id)
        # 2. Load the EXISTING durable assets (HC-4: the operation row's
        # last_result.outputs is not evidence - a SUCCEEDED result without a
        # registered asset never projects; only results already persisted for
        # the attempt count, fetched from the durable asset registry alone).
        output = None
        if operation["state"] == "SUCCEEDED":
            with self.db.transaction(readonly=True) as tx:
                asset = tx.fetchone(
                    "SELECT descriptor FROM assets WHERE generation_key=%s ORDER BY id LIMIT 1",
                    (operation["request_hash"],),
                )
            if asset is None:
                # Nothing durable to project: the finalization is incomplete
                # and U4 keeps blocking the sample (never a fabricated
                # success).
                return
            first = asset["descriptor"]
            output = {
                "object_key": first.get("object_key"),
                "sha256": first.get("sha256"),
                "media_type": first.get("media_type"),
                "size_bytes": first.get("size_bytes"),
            }
        sample_state = "SUCCEEDED" if operation["state"] == "SUCCEEDED" else "FAILED"
        if sample_state == "FAILED":
            # §7.2: the original reason is kept - FAILED, CANCELLED and
            # NOT_FOUND all project FAILED with the recorded error code.
            output = {
                "error_code": (operation["last_result"] or {}).get("error_code")
                or "UNKNOWN_FAILURE"
            }
        # 3+4. Projection and slot clear in one transaction (D before S),
        # monotonic; R6's outcome write rides the same transaction. HC-4: a
        # replay on an ALREADY-terminal sample completes every unfinished
        # stage - linkage/output repair (set-once), the matching-slot clear
        # and the R6 fail-fast restore - while the terminal state itself is
        # never overwritten.
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id)
            lock_account(tx, exp["account_id"])
            lock_categories(tx, exp["account_id"])
            experiment_row(tx, experiment_id, lock=True)
            slot = tx.fetchone(
                "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
                (experiment_id,),
            )
            current = tx.fetchone(
                "SELECT state FROM benchmark_samples WHERE experiment_id=%s "
                "AND sample_id=%s FOR UPDATE",
                (experiment_id, operation["sample_id"]),
            )
            if current is None:
                return
            if current["state"] in ("SUCCEEDED", "FAILED"):
                # Monotonic projection: the terminal state stands; only the
                # missing linkage/output are repaired (HC-4).
                tx.execute(
                    "UPDATE benchmark_samples SET operation_id=COALESCE(operation_id,%s),"
                    "output=COALESCE(output,%s),coverage=COALESCE(coverage,%s) "
                    "WHERE experiment_id=%s AND sample_id=%s",
                    (
                        operation_id,
                        jsonb(output) if output else None,
                        jsonb({"quality": "UNKNOWN"}),
                        experiment_id,
                        operation["sample_id"],
                    ),
                )
            else:
                tx.execute(
                    "UPDATE benchmark_samples SET state=%s,operation_id=%s,"
                    "output=COALESCE(%s,output),coverage=COALESCE(coverage,%s) "
                    "WHERE experiment_id=%s AND sample_id=%s",
                    (
                        sample_state,
                        operation_id,
                        jsonb(output) if output else None,
                        jsonb({"quality": "UNKNOWN"}),
                        experiment_id,
                        operation["sample_id"],
                    ),
                )
            if slot is not None and slot["sample_id"] == operation["sample_id"]:
                tx.execute(
                    "UPDATE benchmark_dispatch_slots SET sample_id=NULL,revision=revision+1 "
                    "WHERE experiment_id=%s AND sample_id=%s",
                    (experiment_id, operation["sample_id"]),
                )
            if sample_state == "FAILED":
                # R6 atomic fail-fast: the outcome is set once, generation
                # stops, in the same transaction as the projection; the
                # COALESCE restores it idempotently on every replay (HC-4).
                tx.execute(
                    "UPDATE benchmark_experiments SET "
                    "execution_outcome=COALESCE(execution_outcome,'FAILED'),"
                    "execution_state=CASE WHEN execution_outcome IS NULL THEN 'FAILED' "
                    "ELSE execution_state END,revision=revision+1,updated_at=%s "
                    "WHERE experiment_id=%s",
                    (self.clock.now(), experiment_id),
                )

    def resolve_sample(
        self,
        experiment_id: UUID,
        *,
        sample_id: str,
        actor_ref: str,
        reason: str,
        evidence_sha256: str,
        world: Any = None,
        force_unrecoverable: bool = False,
    ):
        """§7.3 (spec v3): the audited OPERATOR resolution for a sample's
        UNKNOWN operation, with the R7 live-source matrix.

        Replay first: an identical attestation replays successfully before any
        live-source check. Ordinary resolution requires
        ``bind_for_recovery == VERIFIED_SOURCE_GONE``. BOUND with positively
        recoverable work or usable output refuses EVEN WITH force
        (reconciliation owns it); reachable-but-unrecoverable and INDETERMINATE
        sources require ``force_unrecoverable`` (recorded in the audit). The
        audit and the terminal transition commit together; financial
        finalization, slot clearing and the §7.4 fail-fast follow through
        ``finalize_terminal``.
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
        # HB-3: the operator resolution's CLEANUP world is the sample's OWN
        # acquisition's (its provenance, namespace and credentials - §3.2).
        world = world or self._world(
            experiment_id, mode="CLEANUP", acquisition_id=sample["acquisition_id"]
        )
        # §7.3 replay BEFORE any live-source check: the identical attestation
        # on an already-terminal operation succeeds idempotently.
        with self.db.transaction(readonly=True) as tx:
            terminal = tx.fetchval(
                "SELECT state FROM provider_operations WHERE id=%s", (operation_id,)
            )
        if terminal in ("SUCCEEDED", "FAILED", "CANCELLED", "NOT_FOUND"):
            world.comfy.resolve_unknown_operation(
                operation_id,
                actor_ref=actor_ref,
                reason=reason,
                evidence_sha256=evidence_sha256,
            )
            self.finalize_terminal(operation_id, world=world)
            return self.status(experiment_id)
        # R7 live-source matrix (only a first resolution reaches here).
        binding = None
        if sample["acquisition_id"] is not None and hasattr(world, "bind_for_recovery"):
            try:
                binding = world.bind_for_recovery(sample["acquisition_id"])
            except Exception:  # noqa: BLE001 - binding failures are INDETERMINATE
                binding = "INDETERMINATE"
        if binding == "BOUND":
            # HC-3 (T031 HCF): recoverability is determined through the
            # RECOVERY path - the deterministic client-id reconciliation, never
            # a bare poll (which raises on UNKNOWN-without-id before ever
            # querying the server, letting force fail a sample whose accepted
            # prompt is positively recoverable by client id) - and read through
            # a RECOVERY composition (the EXPIRED recovery-read exception
            # admits RECOVERY only; this resolution's CLEANUP world cannot read
            # a recoverable EXPIRED operation at all, making it look
            # unreachable). Positively recoverable work or usable output
            # belongs to reconciliation - never to an operator attestation,
            # even forced.
            # A factory-less service (local preparation) cannot compose the
            # RECOVERY world; its caller-supplied world is the recovery path
            # it has (production always wires the factory).
            recovery_probe = (
                self._world(experiment_id, mode="RECOVERY", acquisition_id=sample["acquisition_id"])
                if self.world_factory is not None
                else world
            )
            probed_state = None
            try:
                probed = recovery_probe.comfy.reconcile_unknown(operation_id)
                probed_state = getattr(probed.state, "value", probed.state)
            except Exception:  # noqa: BLE001 - unreachable/ambiguous history
                probed_state = None
            if probed_state is not None:
                raise Conflict(
                    "a bound source with recoverable work requires reconciliation, "
                    "not an operator resolution (R7)",
                    operation_id=str(operation_id),
                    probed_state=probed_state,
                )
            if not force_unrecoverable:
                raise PolicyDenied(
                    "the source is reachable but unrecoverable; resolving it "
                    "requires --force-unrecoverable with the recorded attestation (R7)"
                )
        elif binding != "VERIFIED_SOURCE_GONE":
            if not force_unrecoverable:
                raise PolicyDenied(
                    "the source is indeterminate; resolving it requires "
                    "--force-unrecoverable with the recorded attestation (R7)"
                )
        world.comfy.resolve_unknown_operation(
            operation_id,
            actor_ref=actor_ref,
            reason=reason,
            evidence_sha256=evidence_sha256,
            forced=force_unrecoverable,
        )
        self.finalize_terminal(operation_id, world=world)
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

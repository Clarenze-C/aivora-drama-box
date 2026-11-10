"""Durable T031 coordination. No provider calls or secondary money ledger live here."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from microdrama.budget.ledger import episode_account_id, lock_account, lock_categories
from microdrama.budget.service import BudgetService
from microdrama.contracts.cost import BudgetReservationRequest
from microdrama.contracts.errors import BudgetExhausted, Conflict, EffectDenied, NotFound
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence.db import Database, Tx, jsonb

SCREEN_IDS = ("S01-R1", "S03-R1", "S07-R1")
TERMINAL_SAMPLES = {"SUCCEEDED", "FAILED"}

TERMINAL_LEASE_STATES = ("RELEASED", "EXPIRED", "ORPHANED")
TERMINAL_OPERATION_STATES = ("SUCCEEDED", "FAILED", "CANCELLED", "NOT_FOUND")


@dataclass(frozen=True)
class UnresolvedItem:
    """One blocking or replayable item derived from canonical records (spec §4.1).

    Derived only through immutable linkage - the acquisition's COMPUTE/STORAGE
    reservation and lease, each sample's fixed ``:a1`` reservation and its job
    and operation, the durable upload intents and the podless-create
    resolutions - never from a benchmark state label alone.
    """

    kind: str  # U1, U2, U3, U3p, U3u, U4, U5, U6
    experiment_id: UUID
    detail: str
    acquisition_id: UUID | None = None
    sample_id: str | None = None
    reservation_id: UUID | None = None
    operation_id: UUID | None = None
    lease_id: UUID | None = None

    def describe(self) -> str:
        target = self.sample_id or (str(self.acquisition_id) if self.acquisition_id else "-")
        return f"{self.kind}({target}): {self.detail}"


# Blocking scopes (spec §4.1 R2). Actions: "admission" (a new acquisition
# generation), "claims" (admitting the next sample), "dispatch" (sending a
# create, upload or prompt effect). U6 never appears here: it gates only the
# effect on its own item until local replay repairs it (§4.1/SC2-1), so
# callers evaluate U6 item-wise, never as a blanket block.
BLOCKING_SCOPES: dict[str, frozenset[str]] = {
    "U1": frozenset({"admission", "claims", "dispatch"}),
    # U2 blocks admission of the NEXT acquisition and any dispatch on its own
    # acquisition - never claims on a healthy one (SC-2).
    "U2": frozenset({"admission", "dispatch"}),
    "U3": frozenset({"admission", "claims", "dispatch"}),
    # In-flight work is polled by recovery, not blocked: U3p stops fresh
    # admission only, until the existing work is recovered and finalised (R2).
    "U3p": frozenset({"admission", "claims"}),
    # Upload uncertainty is acquisition-scoped for the dependent samples, but
    # blocks fresh admission across the whole experiment (R2 bullet 1).
    "U3u": frozenset({"admission", "claims", "dispatch"}),
    "U4": frozenset({"admission", "claims"}),
    "U5": frozenset({"admission", "claims", "dispatch"}),
    "U6": frozenset(),
}

# Kinds whose block applies only to the named acquisition for that action.
# Admission is deliberately absent: U2 blocks the NEXT acquisition whatever it
# is, and U3u/U1/U3/U5 block new generation experiment-wide.
ACQUISITION_SCOPED: dict[str, frozenset[str]] = {
    "claims": frozenset({"U3u"}),
    "dispatch": frozenset({"U2", "U3u"}),
    "admission": frozenset(),
}


def blocking(
    items: list[UnresolvedItem],
    action: str,
    *,
    acquisition_id: UUID | None = None,
    sample_id: str | None = None,
) -> list[UnresolvedItem]:
    """The items that block ``action`` ("admission"/"claims"/"dispatch").

    ``sample_id`` never narrows a block: the dispatch slot already serialises
    one in-flight sample; it is accepted for call-site symmetry and ignored.
    """
    result: list[UnresolvedItem] = []
    for item in items:
        if action not in BLOCKING_SCOPES.get(item.kind, frozenset()):
            continue
        if (
            item.kind in ACQUISITION_SCOPED.get(action, frozenset())
            and acquisition_id is not None
            and item.acquisition_id != acquisition_id
        ):
            continue
        result.append(item)
    return result


def unresolved_items(tx: Tx, experiment_id: UUID, *, now: datetime) -> list[UnresolvedItem]:
    """Every unresolved item, derived from canonical lease/reservation/
    operation/upload rows (spec §4.1). One repository function used by every
    caller. ``now`` comes from the caller's clock so the sweep and every gate
    agree on time; no label is trusted where a canonical predicate exists.
    """
    items: list[UnresolvedItem] = []
    acquisitions = tx.fetchall(
        "SELECT a.*, l.lease_state, l.pod_id, l.create_requested_at, "
        "l.terminate_verified_at FROM benchmark_acquisitions a "
        "LEFT JOIN pod_leases l ON l.id=a.lease_id WHERE a.experiment_id=%s "
        "ORDER BY generation",
        (experiment_id,),
    )
    outcome = tx.fetchval(
        "SELECT execution_outcome FROM benchmark_experiments WHERE experiment_id=%s",
        (experiment_id,),
    )
    samples = tx.fetchall(
        "SELECT s.sample_id, s.state, s.job_id, s.operation_id, s.reservation_id, "
        "s.acquisition_id, s.output FROM benchmark_samples s WHERE s.experiment_id=%s "
        "AND s.reservation_id IS NOT NULL ORDER BY s.sample_id",
        (experiment_id,),
    )
    operations: dict[UUID, list[dict[str, Any]]] = {}
    for row in tx.fetchall(
        "SELECT o.id, o.state, o.reservation_id FROM provider_operations o "
        "JOIN benchmark_samples s ON s.reservation_id=o.reservation_id "
        "WHERE s.experiment_id=%s ORDER BY o.id",
        (experiment_id,),
    ):
        operations.setdefault(row["reservation_id"], []).append(row)
    open_uploads = {
        row["acquisition_id"]: row["open"]
        for row in tx.fetchall(
            "SELECT u.acquisition_id, COUNT(*) AS open FROM benchmark_uploads u "
            "JOIN benchmark_acquisitions a ON a.acquisition_id=u.acquisition_id "
            "WHERE a.experiment_id=%s AND u.state IN ('INTENT','UNKNOWN') "
            "GROUP BY u.acquisition_id",
            (experiment_id,),
        )
    }
    storage_open = {
        row["acquisition_id"]: row["open"]
        for row in tx.fetchall(
            "SELECT l.acquisition_id, COUNT(*) AS open FROM benchmark_reservation_links l "
            "JOIN reservations r ON r.id=l.reservation_id "
            "WHERE l.experiment_id=%s AND l.purpose='STORAGE' AND r.state='ACTIVE' "
            "GROUP BY l.acquisition_id",
            (experiment_id,),
        )
    }
    reservation_states = {
        row["id"]: row["state"]
        for row in tx.fetchall(
            "SELECT r.id, r.state FROM reservations r JOIN benchmark_samples s "
            "ON s.reservation_id=r.id WHERE s.experiment_id=%s",
            (experiment_id,),
        )
    }
    slot_sample = tx.fetchval(
        "SELECT sample_id FROM benchmark_dispatch_slots WHERE experiment_id=%s",
        (experiment_id,),
    )

    # ---- per-acquisition create liability (U1, U5) --------------------------
    # ambiguity per acquisition, reused by U2's deadline clause (SC2-2): an
    # unresolved create, submit or upload uncertainty on that acquisition.
    ambiguous_acquisition: set[UUID] = set()
    for row in acquisitions:
        if row["lease_id"] is None:
            continue
        resolution = tx.fetchone(
            "SELECT contradicted_at IS NOT NULL AS contradicted, contradicted_pod_id, "
            "actor_ref, evidence_sha256 "
            "FROM runpod_podless_create_resolutions WHERE lease_id=%s",
            (row["lease_id"],),
        )
        if row["create_requested_at"] is not None and row["pod_id"] is None and resolution is None:
            # U1 - create uncertain: committed create intent, no pod, and no
            # resolution (positive adoption binds pod_id; audited NO_CREATE_PROVEN
            # writes the resolution row). Independent of the acquisition label.
            ambiguous_acquisition.add(row["acquisition_id"])
            items.append(
                UnresolvedItem(
                    kind="U1",
                    experiment_id=experiment_id,
                    acquisition_id=row["acquisition_id"],
                    lease_id=row["lease_id"],
                    detail="committed podless create intent without resolution",
                )
            )
        if resolution is not None and resolution["contradicted"]:
            ownership_open = tx.fetchval(
                "SELECT 1 FROM pod_storage_ownership WHERE pod_id=%s AND valid_until IS NULL",
                (resolution["contradicted_pod_id"],),
            )
            if row["terminate_verified_at"] is None or ownership_open:
                # U5 - reopened liability: the no-create attestation was
                # contradicted by a later pod binding and the discovered
                # resource is not final yet (terminate verified, ownership
                # closed; billing follows the verified termination). Historical
                # contradicted_at alone does not block after finalization.
                items.append(
                    UnresolvedItem(
                        kind="U5",
                        experiment_id=experiment_id,
                        acquisition_id=row["acquisition_id"],
                        lease_id=row["lease_id"],
                        detail=(
                            "contradicted no-create attestation "
                            f"(actor {resolution['actor_ref']}, evidence "
                            f"{resolution['evidence_sha256'][:12]}) with an unfinalized pod"
                        ),
                    )
                )

    # ---- per-sample operation linkage (U3, U3p, U4, U6-sample) --------------
    for sample in samples:
        ops = operations.get(sample["reservation_id"], [])
        if not ops:
            if sample["state"] == "CLAIMED" and sample["job_id"] is None:
                # U6 - a claim and hold committed without job or operation
                # (§F ADMITTED_WITHOUT_JOB at sample level). Local-only: replay
                # materializes and adopts; it never blocks other work.
                items.append(
                    UnresolvedItem(
                        kind="U6",
                        experiment_id=experiment_id,
                        acquisition_id=sample["acquisition_id"],
                        sample_id=sample["sample_id"],
                        reservation_id=sample["reservation_id"],
                        detail="sample claim+hold committed without job/operation",
                    )
                )
            continue
        states = {operation["state"] for operation in ops}
        uncertain = states & {"UNKNOWN", "PENDING_SUBMIT"}
        in_flight = states & {"SUBMITTED", "RUNNING"}
        if uncertain:
            # U3 - submit uncertain. PENDING_SUBMIT always counts: a durable
            # pre-dispatch refusal transitions the operation to FAILED before
            # any send could be accepted, so a still-pending operation has no
            # refusal proof (I2: PENDING_SUBMIT alone proves nothing).
            if states & {"UNKNOWN", "PENDING_SUBMIT"}:
                ambiguous_acquisition.add(sample["acquisition_id"])
            items.append(
                UnresolvedItem(
                    kind="U3",
                    experiment_id=experiment_id,
                    acquisition_id=sample["acquisition_id"],
                    sample_id=sample["sample_id"],
                    reservation_id=sample["reservation_id"],
                    detail=f"operation {','.join(sorted(uncertain))} without a proven outcome",
                )
            )
        elif in_flight:
            # U3p - known in flight: recovery adopts the linkage and polls it
            # before any other sample or acquisition may start (R2).
            items.append(
                UnresolvedItem(
                    kind="U3p",
                    experiment_id=experiment_id,
                    acquisition_id=sample["acquisition_id"],
                    sample_id=sample["sample_id"],
                    reservation_id=sample["reservation_id"],
                    detail=f"operation {','.join(sorted(in_flight))} in flight",
                )
            )
        else:
            terminal = states & set(TERMINAL_OPERATION_STATES)
            projected = sample["state"] in TERMINAL_SAMPLES
            slot_held = slot_sample is not None and slot_sample == sample["sample_id"]
            settled = reservation_states.get(sample["reservation_id"]) in ("SETTLED", "RELEASED")
            output_missing = any(
                operation["state"] == "SUCCEEDED" and not (sample["output"] or {}).get("sha256")
                for operation in ops
                if operation["state"] == "SUCCEEDED"
            )
            if terminal and (not projected or slot_held or not settled or output_missing):
                # U4 - terminal operation whose settlement/release, projection
                # or dispatch slot is not final yet (§7.1 finalize_terminal).
                items.append(
                    UnresolvedItem(
                        kind="U4",
                        experiment_id=experiment_id,
                        acquisition_id=sample["acquisition_id"],
                        sample_id=sample["sample_id"],
                        reservation_id=sample["reservation_id"],
                        detail="terminal operation not fully finalized/projected",
                    )
                )

    # ---- upload uncertainty (U3u), acquisition-scoped (R2) ------------------
    for acquisition_id, count in open_uploads.items():
        ambiguous_acquisition.add(acquisition_id)
        items.append(
            UnresolvedItem(
                kind="U3u",
                experiment_id=experiment_id,
                acquisition_id=acquisition_id,
                detail=f"{count} upload intent(s) without checksum-verified readback",
            )
        )

    # ---- cleanup owed (U2) --------------------------------------------------
    for row in acquisitions:
        if row["state"] == "CLOSED":
            continue
        reasons: list[str] = []
        if row["state"] == "CLEANUP_PENDING":
            reasons.append("cleanup pending")
        if row["state"] == "NO_CREATE_PROVEN" and storage_open.get(row["acquisition_id"], 0):
            # R1: the partial unique index excludes NO_CREATE_PROVEN, but that
            # never authorizes the next acquisition - the original STORAGE
            # reservation must be canonically finalized first.
            reasons.append("resolved no-create storage hold not yet finalized (R1)")
        if row["state"] == "NO_CREATE_PROVEN" and row["lease_state"] in (
            "CLAIMED",
            "ACTIVE",
            "TRANSFERRING",
        ):
            # The proven-no-create lease is still live: cleanup is required (the
            # canonical podless close must run before any new lease may exist).
            reasons.append("resolved no-create lease still awaits its canonical close")
        if row["state"] != "NO_CREATE_PROVEN":
            if row["lease_state"] in TERMINAL_LEASE_STATES or row["terminate_verified_at"]:
                reasons.append("terminal lease awaits acquisition finalization")
            if outcome is not None:
                reasons.append("experiment outcome set; cleanup owed")
        deadline = row["recovery_deadline"]
        if (
            deadline is not None
            and now >= deadline
            and row["acquisition_id"] in ambiguous_acquisition
        ):
            # SC2-2: the deadline only bites while an ambiguity on THIS
            # acquisition remains unresolved; a recovered episode's historical
            # deadline never blocks later healthy work.
            reasons.append("recovery deadline passed with an unresolved ambiguity")
        if reasons:
            items.append(
                UnresolvedItem(
                    kind="U2",
                    experiment_id=experiment_id,
                    acquisition_id=row["acquisition_id"],
                    lease_id=row["lease_id"],
                    detail="; ".join(reasons),
                )
            )

    # ---- acquisition materialization (U6) -----------------------------------
    for row in acquisitions:
        if row["lease_id"] is None and row["state"] not in ("CLOSED", "NO_CREATE_PROVEN"):
            # §F ADMITTED_WITHOUT_JOB: intent and holds are committed, the
            # canonical lease/job links are not. Replay is local; U6 never
            # blocks other work (SC2-1).
            items.append(
                UnresolvedItem(
                    kind="U6",
                    experiment_id=experiment_id,
                    acquisition_id=row["acquisition_id"],
                    detail="acquisition intent+holds committed without lease/job links",
                )
            )
    return items


def document(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


def decode_seal(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    payload = result["manifest"]
    if set(payload) == {"canonical_document_json"}:
        payload = json.loads(payload["canonical_document_json"])
    from microdrama.pipeline.benchmark_authorization import document_sha256

    if document_sha256(payload) != result["sealed_sha256"]:
        raise Conflict("durable seal document failed hash verification")
    result["manifest"] = payload
    return result


def experiment_row(tx: Tx, experiment_id: UUID, *, lock: bool = False) -> dict[str, Any]:
    row = tx.fetchone(
        "SELECT * FROM benchmark_experiments WHERE experiment_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (experiment_id,),
    )
    if row is None:
        raise NotFound("benchmark experiment not found")
    return row


def exposure(tx: Tx, experiment_id: UUID) -> dict[str, int]:
    """Canonical counters, each linked reservation once. CREDIT never replenishes."""
    row = tx.fetchone(
        "SELECT COALESCE(SUM(r.accrued_micro_usd),0)::bigint accrued, "
        "COALESCE(SUM(r.settled_micro_usd),0)::bigint settled, "
        "COALESCE(SUM(CASE WHEN r.state='ACTIVE' THEN "
        "GREATEST(r.reserved_micro_usd-r.accrued_micro_usd,0) ELSE 0 END),0)::bigint holds "
        "FROM benchmark_reservation_links l JOIN reservations r ON r.id=l.reservation_id "
        "WHERE l.experiment_id=%s",
        (experiment_id,),
    )
    assert row is not None
    # Disk/CPU allocations may be posted without a reservation. Attribute only a
    # canonical charge identity observed on this experiment's actual owned pods.
    unreserved = tx.fetchval(
        "SELECT COALESCE(SUM(c.amount_micro_usd),0)::bigint FROM charges c "
        "WHERE c.reservation_id IS NULL AND c.kind<>'CREDIT' AND c.id IN ("
        "SELECT p.charge_id FROM runpod_billing_budget_postings p "
        "JOIN runpod_billing_allocations a USING(allocation_id) "
        "JOIN runpod_billing_buckets b ON b.observation_id=a.bucket_observation_id "
        "JOIN pod_leases pl ON pl.pod_id=b.pod_id "
        "JOIN benchmark_acquisitions ba ON ba.lease_id=pl.id "
        "WHERE ba.experiment_id=%s)",
        (experiment_id,),
    )
    row["unreserved_settled"] = int(unreserved)
    row["total"] = sum(int(row[k]) for k in ("accrued", "settled", "holds", "unreserved_settled"))
    return {k: int(v) for k, v in row.items()}


def gpu_ms(tx: Tx, experiment_id: UUID, now: datetime) -> int:
    """Aggregate GPU milliseconds across the experiment's acquisitions (§6.4).

    A CONTRADICTED no-create acquisition counts from its original
    ``create_intent_at`` through the discovered pod's verified termination
    (the lease's own compute window - the disproved no-create window end on the
    acquisition row is ignored, and discovery grants no new allowance). An
    uncontradicted NO_CREATE_PROVEN acquisition is excluded: its liability was
    positively proven absent.
    """
    return int(
        tx.fetchval(
            "SELECT COALESCE(SUM(GREATEST(0,EXTRACT(EPOCH FROM ("
            "CASE WHEN a.state<>'NO_CREATE_PROVEN' THEN COALESCE(a.compute_window_end,%s) "
            "ELSE COALESCE(l.terminate_verified_at,%s) END"
            "-a.create_intent_at))*1000)),0)::bigint "
            "FROM benchmark_acquisitions a "
            "LEFT JOIN pod_leases l ON l.id=a.lease_id "
            "WHERE a.experiment_id=%s "
            "AND (a.state<>'NO_CREATE_PROVEN' OR EXISTS ("
            "SELECT 1 FROM runpod_podless_create_resolutions r "
            "WHERE r.lease_id=a.lease_id AND r.contradicted_at IS NOT NULL))",
            (now, now, experiment_id),
        )
    )


class ExperimentBudgetService(BudgetService):
    """Canonical reserve plus experiment sub-limit in the same account transaction."""

    def __init__(
        self,
        *args: Any,
        experiment_id: UUID,
        cleanup_floor_micro_usd: int = 0,
        authorization_cap_micro_usd: int | None = None,
        authorization_gpu_ms: int | None = None,
        authorization_deadline: datetime | None = None,
        cleanup_grants_only: bool = False,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.experiment_id = experiment_id
        self.cleanup_floor_micro_usd = cleanup_floor_micro_usd
        self.authorization_cap_micro_usd = authorization_cap_micro_usd
        self.authorization_gpu_ms = authorization_gpu_ms
        self.authorization_deadline = authorization_deadline
        # HB-11 (I5): a RECOVERY/CLEANUP world's budget may take ONLY the
        # canonical cleanup grant - every other reservation is refused at the
        # service boundary, with otherwise valid ownership and scope.
        self.cleanup_grants_only = cleanup_grants_only

    def reserve(self, request: BudgetReservationRequest):
        with self._db.transaction() as tx:
            return self.reserve_linked(tx, request)

    def reserve_linked(
        self,
        tx: Tx,
        request: BudgetReservationRequest,
        *,
        acquisition_id: UUID | None = None,
        sample_id: str | None = None,
        purpose: str | None = None,
    ):
        account_id = episode_account_id(tx, request.episode_id)
        acct = lock_account(tx, account_id)
        lock_categories(tx, account_id)
        exp = experiment_row(tx, self.experiment_id, lock=True)
        if exp["account_id"] != acct.id or exp["episode_id"] != request.episode_id:
            raise Conflict("experiment reservation account differs")
        acquisitions = tx.fetchall(
            "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s AND state NOT IN ('CLOSED','NO_CREATE_PROVEN') ORDER BY acquisition_id FOR UPDATE",
            (self.experiment_id,),
        )
        tx.fetchone(
            "SELECT * FROM benchmark_dispatch_slots WHERE experiment_id=%s FOR UPDATE",
            (self.experiment_id,),
        )
        if sample_id is not None:
            tx.fetchone(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s FOR UPDATE",
                (self.experiment_id, sample_id),
            )
        tx.fetchall(
            "SELECT r.id FROM reservations r JOIN benchmark_reservation_links l ON l.reservation_id=r.id WHERE l.experiment_id=%s ORDER BY r.id FOR UPDATE OF r",
            (self.experiment_id,),
        )
        cleanup = request.is_shutdown_or_cleanup
        if self.cleanup_grants_only and not cleanup:
            # HB-11 (I5): recovery and cleanup worlds never open new work
            # holds - the canonical cleanup grant is the only reservation a
            # mode-restricted budget may take.
            raise EffectDenied(
                f"recovery/cleanup world cannot reserve new work ({request.operation_kind})"
            )
        if not cleanup:
            if exp["execution_outcome"] is not None or exp["execution_state"] in (
                "NEEDS_RECONCILIATION",
                "SCREEN_REVIEW",
            ):
                raise BudgetExhausted(
                    f"experiment does not admit new work ({exp['execution_state']}, {exp['execution_outcome']})"
                )
            if exp["hard_stop"] is None or self._now() >= min(
                exp["hard_stop"], self.authorization_deadline or exp["hard_stop"]
            ):
                raise BudgetExhausted("experiment deadline reached or unsealed")
            if gpu_ms(tx, self.experiment_id, self._now()) >= min(
                exp["gpu_limit_ms"], self.authorization_gpu_ms or exp["gpu_limit_ms"]
            ):
                raise BudgetExhausted("aggregate experiment GPU time exhausted")
            if any(a["state"] == "UNKNOWN" for a in acquisitions):
                raise BudgetExhausted("unresolved provider liability blocks experiment work")
        result = super().reserve_in_transaction(tx, request)
        if purpose is None:
            purpose = (
                "CLEANUP"
                if cleanup
                else ("COMPUTE" if request.operation_kind == "pod.lease" else "PROMPT")
            )
        if acquisition_id is None and cleanup and request.operation_kind == "pod.stop":
            # The canonical stop key is lease-scoped. Preserve that ownership
            # instead of choosing acquisitions[0] (UUID order is not generation
            # order and may point at a different lease after a retry).
            lease_id = request.semantic_key.removeprefix("pod.stop:")
            acquisition_id = tx.fetchval(
                "SELECT acquisition_id FROM benchmark_acquisitions "
                "WHERE experiment_id=%s AND lease_id=%s",
                (self.experiment_id, lease_id),
            )
        if acquisition_id is None and acquisitions:
            acquisition_id = acquisitions[0]["acquisition_id"]
        existing = tx.fetchone(
            "SELECT * FROM benchmark_reservation_links WHERE reservation_id=%s", (result.id,)
        )
        if existing is not None:
            if (
                existing["experiment_id"] != self.experiment_id
                or existing["purpose"] != purpose
                or (sample_id is not None and existing["sample_id"] != sample_id)
            ):
                raise Conflict("reservation already linked to another experiment intent")
        else:
            tx.execute(
                "INSERT INTO benchmark_reservation_links(reservation_id,experiment_id,acquisition_id,sample_id,purpose) VALUES(%s,%s,%s,%s,%s)",
                (result.id, self.experiment_id, acquisition_id, sample_id, purpose),
            )
        # Candidate is already in canonical projection. Never add worst_case again.
        floor = 0 if cleanup else max(acct.shutdown_reserve, self.cleanup_floor_micro_usd)
        if not cleanup and exposure(tx, self.experiment_id)["total"] + floor > min(
            exp["cap_micro_usd"], self.authorization_cap_micro_usd or exp["cap_micro_usd"]
        ):
            raise BudgetExhausted("experiment shared sub-limit exhausted")
        if not cleanup:
            current = tx.fetchone(
                "SELECT reserved_outstanding_micro_usd+accrued_micro_usd+settled_micro_usd committed FROM budget_accounts WHERE id=%s",
                (acct.id,),
            )
            if current["committed"] + floor > acct.cap:
                raise BudgetExhausted("episode allowance must retain cleanup floor")
        return result

    def settle_expired_unused_hold(self, reservation_id: UUID, *, reason: str) -> bool:
        """§4.1 U6/§F: zero-settle an EXPIRED hold whose effect never dispatched.

        An expired pre-effect intent that cannot be materialized closes only its
        positively unused liability: no lease, job or provider operation was ever
        begun under the hold, so the canonical settlement is the deterministic
        zero-charge receipt (never a release - an EXPIRED hold keeps its
        exposure until settled). Idempotent: a hold that is settled, released,
        ACTIVE or absent is a no-op returning False. The caller proves under the
        §6.1 locks that nothing was dispatched.
        """
        from uuid import uuid5

        from microdrama.budget import policy
        from microdrama.contracts.cost import ReceiptKind, UsageReceipt
        from microdrama.contracts.enums import BudgetCategory, CostBasis, PriceUnit, Provenance
        from microdrama.core.events import append_event
        from microdrama.rendering.leases import RENDERING_NAMESPACE

        with self._db.transaction(readonly=True) as tx:
            reservation = tx.fetchone("SELECT * FROM reservations WHERE id=%s", (reservation_id,))
        if reservation is None or reservation["state"] != "EXPIRED":
            return False
        now = self._now()
        provenance = (
            Provenance.FAKE_SYNTHETIC
            if self._settings.is_offline_mock
            else Provenance.LIVE_PROVIDER
        )
        receipt = UsageReceipt(
            receipt_id=uuid5(RENDERING_NAMESPACE, f"bench-settle-unused:{reservation_id}"),
            provider=reservation["provider"],
            provider_receipt_id=f"bench-settle-unused:{reservation_id}",
            kind=ReceiptKind.SETTLEMENT,
            cost_basis=(
                CostBasis.SYNTHETIC_FAKE
                if provenance is Provenance.FAKE_SYNTHETIC
                else CostBasis.BILLED
            ),
            reservation_id=reservation_id,
            episode_id=reservation["episode_id"],
            season_id=None,
            job_id=None,
            category=BudgetCategory(reservation["category"]),
            amount_micro_usd=0,
            currency="USD",
            units=0,
            unit=PriceUnit.GPU_SECOND,
            # An undispatched hold measures no interval; leaving both None also
            # never mixes the caller's clock with DB-stamped times.
            interval_start=None,
            interval_end=None,
            observed_at=now,
            provenance=provenance,
        )
        policy.check_receipt_admissible(receipt, self._settings)
        with self._db.transaction() as tx:
            result = self.record_usage_in_transaction(tx, receipt)
            if not result.replayed:
                append_event(
                    tx,
                    aggregate_type="prompt_hold",
                    aggregate_id=uuid5(
                        RENDERING_NAMESPACE, f"bench-settle-unused:{reservation_id}"
                    ),
                    event_type="prompt_hold.zero_settled",
                    payload={
                        "reason": reason,
                        "reservation_id": str(reservation_id),
                        "amount_micro_usd": 0,
                    },
                    correlation_id=reservation_id,
                    occurred_at=now,
                )
        return True


class BenchmarkRepository:
    def __init__(self, db: Database, clock: Any):
        self.db, self.clock = db, clock

    def prepare(self, plan: Any) -> dict[str, Any]:
        from microdrama.pipeline.benchmark_authorization import BenchmarkPlan

        plan = BenchmarkPlan.model_validate(document(plan))
        data = document(plan)
        experiment_id, episode_id = UUID(str(data["experiment_id"])), UUID(str(data["episode_id"]))
        identity = dict(data)
        identity.pop("experiment_id", None)
        digest = canonical_hash(identity)
        with self.db.transaction() as tx:
            account_id = episode_account_id(tx, episode_id)
            lock_account(tx, account_id)
            existing = tx.fetchone(
                "SELECT * FROM benchmark_experiments WHERE experiment_id=%s", (experiment_id,)
            )
            if existing:
                if existing["plan_sha256"] != digest:
                    raise Conflict("experiment UUID reused with changed canonical plan")
                return existing
            alias = tx.fetchone(
                "SELECT * FROM benchmark_experiments WHERE episode_id=%s AND plan_sha256=%s",
                (episode_id, digest),
            )
            if alias:
                return alias
            samples = data["samples"]
            if len(samples) != 24 or set(data["screen_sample_ids"]) != set(SCREEN_IDS):
                raise Conflict("benchmark requires exact 24 samples and three frozen screening IDs")
            tx.execute(
                "INSERT INTO benchmark_experiments(experiment_id,episode_id,account_id,plan_sha256,plan,cap_micro_usd,gpu_limit_ms) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    experiment_id,
                    episode_id,
                    account_id,
                    digest,
                    jsonb(data),
                    data["max_new_exposure_micro_usd"],
                    data["max_gpu_ms"],
                ),
            )
            shots = {s["shot_id"]: s for s in data["shots"]}
            for sample in samples:
                frozen = {"sample": sample, "shot": shots[sample["shot_id"]]}
                tx.execute(
                    "INSERT INTO benchmark_samples(experiment_id,sample_id,shot_id,repeat,seed,input,input_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        experiment_id,
                        sample["sample_id"],
                        sample["shot_id"],
                        sample["repeat"],
                        sample["seed"],
                        jsonb(frozen),
                        canonical_hash(frozen),
                    ),
                )
            tx.execute(
                "INSERT INTO benchmark_dispatch_slots(experiment_id) VALUES(%s)", (experiment_id,)
            )
            return experiment_row(tx, experiment_id)

    def seal(self, experiment_id: UUID, manifest: Any) -> dict[str, Any]:
        from microdrama.pipeline.benchmark_authorization import BenchmarkSeal

        manifest = BenchmarkSeal.model_validate(document(manifest))
        data = document(manifest)
        from microdrama.pipeline.benchmark_authorization import (
            canonical_document_bytes,
            document_sha256,
        )

        digest = document_sha256(data)
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id, lock=True)
            if (
                str(data["experiment_id"]) != str(experiment_id)
                or data["plan_sha256"] != exp["plan_sha256"]
            ):
                raise Conflict("seal plan hash differs")
            existing = tx.fetchone(
                "SELECT * FROM benchmark_seals WHERE experiment_id=%s", (experiment_id,)
            )
            if existing:
                if existing["sealed_sha256"] != digest:
                    raise Conflict("execution seal is immutable")
                return decode_seal(existing)
            tx.execute(
                "INSERT INTO benchmark_seals(experiment_id,manifest,sealed_sha256) VALUES(%s,%s,%s)",
                (
                    experiment_id,
                    jsonb(
                        {"canonical_document_json": canonical_document_bytes(data).decode("utf-8")}
                    ),
                    digest,
                ),
            )
            tx.execute(
                "UPDATE benchmark_experiments SET sealed_sha256=%s,hard_stop=%s,revision=revision+1,updated_at=%s WHERE experiment_id=%s",
                (digest, data["hard_stop_utc"], self.clock.now(), experiment_id),
            )
            return {"experiment_id": experiment_id, "sealed_sha256": digest, "manifest": data}

    def status(self, experiment_id: UUID) -> dict[str, Any]:
        with self.db.transaction(readonly=True) as tx:
            exp = experiment_row(tx, experiment_id)
            exp["samples"] = tx.fetchall(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s ORDER BY sample_id",
                (experiment_id,),
            )
            exp["acquisitions"] = tx.fetchall(
                "SELECT * FROM benchmark_acquisitions WHERE experiment_id=%s ORDER BY generation",
                (experiment_id,),
            )
            exp["exposure"] = exposure(tx, experiment_id)
            exp["gpu_ms"] = gpu_ms(tx, experiment_id, self.clock.now())
            exp["seal"] = decode_seal(
                tx.fetchone(
                    "SELECT * FROM benchmark_seals WHERE experiment_id=%s", (experiment_id,)
                )
            )
            return exp

    def outcome(self, experiment_id: UUID, outcome: str) -> None:
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE benchmark_experiments SET execution_outcome=COALESCE(execution_outcome,%s),execution_state=%s,revision=revision+1,updated_at=%s WHERE experiment_id=%s",
                (outcome, outcome, self.clock.now(), experiment_id),
            )

    def screening(self, experiment_id: UUID, decision: Any) -> dict[str, Any]:
        data = document(decision)
        with self.db.transaction() as tx:
            exp = experiment_row(tx, experiment_id, lock=True)
            if exp["execution_state"] != "SCREEN_REVIEW" or exp["cleanup_state"] != "VERIFIED":
                raise Conflict("screening requires verified GPU shutdown before human wait")
            if data.get("sealed_sha256") != exp["sealed_sha256"] or not data.get("actor_ref"):
                raise Conflict("screening must bind seal and actor")
            rows = tx.fetchall(
                "SELECT * FROM benchmark_samples WHERE experiment_id=%s AND sample_id=ANY(%s) ORDER BY sample_id",
                (experiment_id, list(SCREEN_IDS)),
            )
            hashes = {r["sample_id"]: (r["output"] or {}).get("sha256") for r in rows}
            if (
                len(rows) != 3
                or any(r["state"] != "SUCCEEDED" or not hashes[r["sample_id"]] for r in rows)
                or data.get("output_hashes") != hashes
            ):
                raise Conflict("screening must bind all three current durable output hashes")
            if data.get("decision") not in ("PASS", "FAIL") or not data.get("rubric_version"):
                raise Conflict("screening needs PASS/FAIL and rubric")
            if data["decision"] == "PASS" and (
                not data.get("coverage") or any(v != "PASS" for v in data["coverage"].values())
            ):
                raise Conflict("unknown or failed critical screening coverage blocks continuation")
            digest = canonical_hash(data)
            tx.execute(
                "INSERT INTO benchmark_screenings(experiment_id,decision_sha256,decision,sealed_sha256,actor_ref,observed_at) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    experiment_id,
                    digest,
                    jsonb(data),
                    exp["sealed_sha256"],
                    data["actor_ref"],
                    self.clock.now(),
                ),
            )
            if data["decision"] == "FAIL":
                tx.execute(
                    "UPDATE benchmark_experiments SET execution_outcome=COALESCE(execution_outcome,'FAILED'),execution_state='FAILED' WHERE experiment_id=%s",
                    (experiment_id,),
                )
            return {"decision_sha256": digest, **data}

    def record_billing_evidence(
        self, experiment_id: UUID, acquisition_id: UUID, evidence: dict[str, Any]
    ) -> str:
        # Whitelist fields: never store arbitrary body/headers/provider credentials.
        allowed = {
            "observation_identity",
            "amounts",
            "pod_id",
            "interval_start",
            "interval_end",
            "normalization_policy",
            "discrepancy",
        }
        if set(evidence) != allowed or not all(
            isinstance(v, str) for v in evidence["amounts"].values()
        ):
            raise Conflict("raw billing evidence requires exact nonsecret amount strings")
        digest = canonical_hash(evidence)
        with self.db.transaction() as tx:
            owned = tx.fetchval(
                "SELECT 1 FROM benchmark_acquisitions a JOIN pod_leases p ON p.id=a.lease_id WHERE a.experiment_id=%s AND a.acquisition_id=%s AND p.pod_id=%s",
                (experiment_id, acquisition_id, evidence["pod_id"]),
            )
            if not owned:
                raise Conflict("billing evidence does not belong to experiment acquisition")
            tx.execute(
                "INSERT INTO benchmark_billing_evidence(experiment_id,acquisition_id,observation_identity,raw_commit_sha256,amounts,pod_id,interval_start,interval_end,normalization_policy,discrepancy) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    experiment_id,
                    acquisition_id,
                    evidence["observation_identity"],
                    digest,
                    jsonb(evidence["amounts"]),
                    evidence["pod_id"],
                    evidence["interval_start"],
                    evidence["interval_end"],
                    evidence["normalization_policy"],
                    evidence["discrepancy"],
                ),
            )
        return digest

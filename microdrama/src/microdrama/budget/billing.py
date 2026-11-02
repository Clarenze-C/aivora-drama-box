"""Durable reconciliation of time-bucketed Runpod billing observations.

Provider amounts are parsed from their JSON lexical representation. This module never
turns provider buckets into GPU interval receipts: buckets can cross lease transfers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from microdrama.contracts.cost import (
    BillingAllocationBasis,
    BillingComponent,
    BillingFinalityState,
    BillingInvoiceVerification,
    BillingQueryState,
    BillingVerificationResult,
    RunpodBillingAllocation,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    UsageReceipt,
    validate_billing_invoice_verification,
    validate_runpod_billing_allocations,
    validate_runpod_billing_query,
    validate_runpod_billing_revision,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    PriceUnit,
    Provenance,
    ReceiptKind,
)
from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    IdempotencyConflict,
    NotFound,
    SchemaInvalid,
)
from microdrama.contracts.hashing import sha256_hex
from microdrama.core.events import append_event
from microdrama.persistence.db import Database, Tx, jsonb

MICRO_USD = Decimal(1_000_000)
# T045 R4: how long a billing bucket stays "open" after its end before it is stored
# as settled provider evidence. An unverified assumption about Runpod settlement,
# configurable per repository instance and documented in the runbook.
DEFAULT_SETTLE_LAG = timedelta(minutes=15)


@dataclass(frozen=True)
class InvoicePeriodResult:
    """Outcome of one pod-scoped period invoice verification (T045 R5)."""

    period_evidence_id: UUID
    outcome: str  # MATCHED | MATCHED_ZERO | MISMATCHED
    amount_micro_usd: int
    bucket_sum_micro_usd: int
    replayed: bool = False


@dataclass(frozen=True)
class LeaseBillingReadiness:
    """Per-lease billing finality (T045 R7); BILLED is the only spend-release signal.

    ``REOPENED`` is derived, never stored: it means some covering bucket revision is
    newer than the lease's BILLED settlement (its positive delta posts an ADJUSTMENT on
    the closed reservation; a negative one is evidence only).
    """

    lease_id: UUID
    state: (
        str  # PENDING_PROVIDER_FINALITY | AWAITING_INVOICE | DISPUTED | RECOVERY_REQUIRED | BILLED
    )
    pending_since: datetime | None
    billed_micro_usd: int | None = None
    reopened: bool = False
    missing_windows: tuple[tuple[datetime, datetime], ...] = ()


def amount_to_micro_usd(value: str | int | Decimal) -> int:
    """Convert a JSON number lexeme to integer micro-USD using half-up rounding."""
    if isinstance(value, float):
        raise ValueError("billing money must not pass through binary float")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("malformed billing amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("billing amount must be finite and non-negative")
    return int((amount * MICRO_USD).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_provider_bucket(raw: dict[str, Any]) -> dict[str, int]:
    """Parse provider bucket component fields without float arithmetic."""
    if any(
        isinstance(raw.get(key), float)
        for key in ("totalAmount", "gpuAmount", "cpuAmount", "diskAmount")
    ):
        # JSON callers should use parse_float=Decimal; reject already-rounded values.
        raise ValueError("provider billing JSON must be decoded with Decimal")
    if raw.get("currency", "USD") != "USD":
        raise ValueError("only USD provider buckets can be allocated")
    amounts = {
        name: amount_to_micro_usd(raw[key])
        for name, key in (
            ("total", "totalAmount"),
            ("gpu", "gpuAmount"),
            ("cpu", "cpuAmount"),
            ("disk", "diskAmount"),
        )
    }
    if amounts["total"] != amounts["gpu"] + amounts["cpu"] + amounts["disk"]:
        raise ValueError("provider bucket total does not equal GPU + CPU + disk")
    return amounts


def decode_provider_json(body: str) -> Any:
    """Decode provider JSON retaining decimal number lexemes exactly."""
    return json.loads(body, parse_float=Decimal, parse_int=int)


def largest_remainder(total: int, weights: list[tuple[str, int]]) -> dict[str, int]:
    """Split signed integer micro-USD deterministically, conserving the exact total."""
    if not weights or any(weight < 0 for _, weight in weights):
        raise ValueError("allocation weights must be non-empty and non-negative")
    denominator = sum(weight for _, weight in weights)
    if denominator == 0:
        return {key: 0 for key, _ in weights}
    sign = -1 if total < 0 else 1
    magnitude = abs(total)
    floors = {key: magnitude * weight // denominator for key, weight in weights}
    remainder = magnitude - sum(floors.values())
    ranking = sorted(weights, key=lambda item: (-(magnitude * item[1] % denominator), item[0]))
    for key, _ in ranking[:remainder]:
        floors[key] += 1
    return {key: sign * value for key, value in floors.items()}


def _ceil_seconds(delta: timedelta) -> int:
    """Whole seconds, rounding a sub-second interval up to one (never zero)."""
    return max(1, -(-int(delta.total_seconds() * 1_000_000) // 1_000_000))


class BillingRepository:
    """Append-only persistence for canonical 2.13 billing records."""

    def __init__(
        self,
        db: Database,
        budget_service: Any | None = None,
        *,
        settle_lag: timedelta = DEFAULT_SETTLE_LAG,
    ) -> None:
        self.db = db
        self.budget_service = budget_service
        # An unverified assumption about how long Runpod keeps reshaping a bucket: a
        # bucket is only "closed" (storable) once its end is this far behind the
        # observation. Configurable because it is an assumption, not a documented fact.
        self.settle_lag = settle_lag

    def _classify(
        self,
        query: RunpodBillingQueryObservation,
        buckets: list[RunpodBillingBucketObservation],
    ) -> tuple[
        RunpodBillingQueryObservation,
        list[RunpodBillingBucketObservation],
        list[RunpodBillingBucketObservation],
    ]:
        """T045 R4: split the response into closed (stored) and open (skipped) buckets."""
        closed, open_buckets = [], []
        for bucket in buckets:
            if bucket.bucket_end <= bucket.observed_at - self.settle_lag:
                closed.append(bucket)
            else:
                open_buckets.append(bucket)
        effective = query
        if open_buckets:
            update: dict[str, Any] = {}
            if not closed:
                # Every returned bucket is open: the query as a whole is UNKNOWN — it
                # is not evidence of zero and not coverage.
                update = {
                    "result_state": BillingQueryState.UNKNOWN,
                    "unknown_reason": "every returned bucket was still open at observed_at",
                    "bucket_observation_ids": [],
                }
            else:
                update = {"bucket_observation_ids": [b.observation_id for b in closed]}
            effective = RunpodBillingQueryObservation.model_validate(
                effective.model_dump(mode="python") | update
            )
        return effective, closed, open_buckets

    def ingest(
        self,
        query: RunpodBillingQueryObservation,
        buckets: list[RunpodBillingBucketObservation],
        allocations: list[RunpodBillingAllocation] | None = None,
        *,
        _verified_finality: bool = False,
    ) -> None:
        """Store one provider response. The repository derives the stored state (R4).

        Only closed buckets (``bucket_end`` at least ``settle_lag`` behind the
        observation) are stored, as ``ALLOCATED_PROVIDER_REPORTED``; malformed ones stay
        ``DISPUTED``. Open buckets are recorded in the skipped table instead, and an
        all-open response is recorded as an ``UNKNOWN`` query. A bucket presented as
        ``INVOICE_VERIFIED`` or ``PENDING_PROVIDER_FINALITY`` is refused: finality is
        derived here or written by the internal invoice path only.
        """
        for bucket in buckets:
            if (
                bucket.finality_state is BillingFinalityState.INVOICE_VERIFIED
                and not _verified_finality
            ):
                raise SchemaInvalid(
                    "INVOICE_VERIFIED is written only by the invoice verification path; "
                    "API ingest must present an unsettled bucket"
                )
            if bucket.finality_state is BillingFinalityState.PENDING_PROVIDER_FINALITY:
                raise SchemaInvalid(
                    "PENDING_PROVIDER_FINALITY is a lease readiness state; ingest must "
                    "present an allocatable or disputed bucket"
                )
        query, buckets, open_buckets = self._classify(query, buckets)
        allocations = allocations or []

        def operation(tx: Tx) -> None:
            self._ingest_in_transaction(
                tx,
                query,
                buckets,
                open_buckets,
                allocations,
                verified_finality=_verified_finality,
            )

        self.db.run_in_transaction(operation)

    def _ingest_in_transaction(
        self,
        tx: Tx,
        query: RunpodBillingQueryObservation,
        buckets: list[RunpodBillingBucketObservation],
        open_buckets: list[RunpodBillingBucketObservation],
        allocations: list[RunpodBillingAllocation],
        *,
        verified_finality: bool = False,
    ) -> None:
        """The ingest core, inside a caller-owned transaction (R5 composes it)."""
        tx.fetchval(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 451045))",
            (str(query.query_id),),
        )
        existing_query = tx.fetchone(
            "SELECT payload FROM runpod_billing_queries WHERE query_id=%s FOR UPDATE",
            (query.query_id,),
        )
        if existing_query is not None:
            if RunpodBillingQueryObservation.model_validate(existing_query["payload"]) != query:
                raise IdempotencyConflict("billing query ID replayed with different content")
            return
        tx.execute(
            "INSERT INTO runpod_billing_queries (query_id,provider_account_ref,observed_at,result_state,payload) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (query_id) DO NOTHING",
            (
                query.query_id,
                query.provider_account_ref,
                query.observed_at,
                query.result_state.value,
                jsonb(query),
            ),
        )
        for bucket in open_buckets:
            tx.execute(
                "INSERT INTO runpod_billing_query_skipped_buckets (skip_id,query_id,"
                "provider_account_ref,pod_id,bucket_start,bucket_end,bucket_size_seconds,"
                "observed_at,reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'OPEN_BUCKET') "
                "ON CONFLICT (query_id,pod_id,bucket_start,bucket_end) DO NOTHING",
                (
                    uuid4(),
                    query.query_id,
                    query.provider_account_ref,
                    bucket.pod_id,
                    bucket.bucket_start,
                    bucket.bucket_end,
                    bucket.bucket_size_seconds,
                    bucket.observed_at,
                ),
            )
        for bucket in buckets:
            tx.fetchval(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 451046))",
                (bucket.bucket_identity_sha256,),
            )
            prior = tx.fetchone(
                "SELECT * FROM runpod_billing_buckets WHERE bucket_identity_sha256=%s "
                "ORDER BY revision DESC LIMIT 1 FOR UPDATE",
                (bucket.bucket_identity_sha256,),
            )
            if (
                prior
                and prior["raw_response_sha256"] == bucket.raw_response_sha256
                and not verified_finality
            ):
                if RunpodBillingBucketObservation.model_validate(prior["payload"]) != bucket:
                    raise IdempotencyConflict(
                        "billing response hash replayed with different bucket content"
                    )
                continue
            prior_model = (
                RunpodBillingBucketObservation.model_validate(prior["payload"]) if prior else None
            )
            validate_runpod_billing_revision(prior_model, bucket)
            bucket_allocations = [
                a for a in allocations if a.bucket_observation_id == bucket.observation_id
            ]
            if not bucket_allocations and bucket.finality_state in (
                BillingFinalityState.ALLOCATED_PROVIDER_REPORTED,
                BillingFinalityState.INVOICE_VERIFIED,
            ):
                bucket_allocations = self.derive_allocations(tx, bucket, prior_model)
            validate_runpod_billing_allocations(bucket, bucket_allocations, prior=prior_model)
            tx.execute(
                "INSERT INTO runpod_billing_buckets (observation_id,bucket_identity_sha256,revision,prior_observation_id,query_id,provider_account_ref,pod_id,bucket_start,bucket_end,bucket_size_seconds,raw_response_sha256,observed_at,currency,total_amount_micro_usd,gpu_amount_micro_usd,cpu_amount_micro_usd,disk_amount_micro_usd,finality_state,invoice_verification_id,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    bucket.observation_id,
                    bucket.bucket_identity_sha256,
                    bucket.revision,
                    bucket.prior_observation_id,
                    bucket.query_id,
                    bucket.provider_account_ref,
                    bucket.pod_id,
                    bucket.bucket_start,
                    bucket.bucket_end,
                    bucket.bucket_size_seconds,
                    bucket.raw_response_sha256,
                    bucket.observed_at,
                    bucket.currency,
                    bucket.total_amount_micro_usd,
                    bucket.gpu_amount_micro_usd,
                    bucket.cpu_amount_micro_usd,
                    bucket.disk_amount_micro_usd,
                    bucket.finality_state.value,
                    bucket.invoice_verification_id,
                    jsonb(bucket),
                ),
            )
            for allocation in bucket_allocations:
                tx.execute(
                    "INSERT INTO runpod_billing_allocations (allocation_id,bucket_observation_id,bucket_identity_sha256,bucket_revision,component,owner_kind,owner_id,allocation_basis,delta_micro_usd,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        allocation.allocation_id,
                        allocation.bucket_observation_id,
                        allocation.bucket_identity_sha256,
                        allocation.bucket_revision,
                        allocation.component.value,
                        allocation.owner_kind,
                        str(allocation.owner_id),
                        allocation.allocation_basis.value,
                        allocation.delta_micro_usd,
                        jsonb(allocation),
                    ),
                )
                if self.budget_service is not None:
                    self.budget_service.reconcile_provider_allocation_in_transaction(
                        tx, bucket, allocation
                    )
        effective_allocations = list(allocations)
        effective_allocations.extend(
            a
            for bucket in buckets
            for a in tx.fetchall(
                "SELECT payload FROM runpod_billing_allocations WHERE bucket_observation_id=%s",
                (bucket.observation_id,),
            )
            for a in [RunpodBillingAllocation.model_validate(a["payload"])]
            if a not in effective_allocations
        )
        prior_observations: dict[Any, RunpodBillingBucketObservation] = {}
        for bucket in buckets:
            if bucket.prior_observation_id is not None:
                row = tx.fetchone(
                    "SELECT payload FROM runpod_billing_buckets WHERE observation_id=%s",
                    (bucket.prior_observation_id,),
                )
                if row is None:
                    raise SchemaInvalid("billing bucket revision references a missing prior")
                prior_observations[bucket.observation_id] = (
                    RunpodBillingBucketObservation.model_validate(row["payload"])
                )
        validate_runpod_billing_query(
            query, buckets, effective_allocations, prior_observations=prior_observations
        )

    def verify_invoice(
        self, bucket: RunpodBillingBucketObservation, verification: BillingInvoiceVerification
    ) -> None:
        validate_billing_invoice_verification(bucket, verification)

        def operation(tx: Tx) -> None:
            row = tx.fetchone(
                "SELECT payload FROM runpod_billing_buckets WHERE observation_id=%s FOR UPDATE",
                (bucket.observation_id,),
            )
            if (
                row is None
                or RunpodBillingBucketObservation.model_validate(row["payload"]) != bucket
            ):
                raise ValueError(
                    "invoice verification bucket is not the persisted current observation"
                )
            tx.execute(
                "INSERT INTO runpod_billing_invoice_verifications (verification_id,bucket_observation_id,bucket_identity_sha256,evidence_sha256,verified_at,result,payload) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    verification.verification_id,
                    bucket.observation_id,
                    bucket.bucket_identity_sha256,
                    verification.evidence_sha256,
                    verification.verified_at,
                    verification.result.value,
                    jsonb(verification),
                ),
            )
            if (
                self.budget_service is not None
                and verification.result is BillingVerificationResult.MATCHED
            ):
                # Only matched evidence may finalize budget accruals. Mismatched
                # evidence is the dispute record itself: it must commit durably
                # (above) and must never post a finalization or touch the ledger.
                self.budget_service.record_provider_invoice_verification_in_transaction(
                    tx, bucket, verification
                )

        self.db.run_in_transaction(operation)

    def verify_invoice_period(
        self,
        *,
        provider_account_ref: str,
        pod_id: str,
        period_start: datetime,
        period_end: datetime,
        amount_micro_usd: int,
        currency: str,
        evidence_sha256: str,
        source: str,
        observed_at: datetime,
        supersedes_evidence_id: UUID | None = None,
        actor_ref: str | None = None,
        reason: str | None = None,
    ) -> InvoicePeriodResult:
        """Verify one invoice against the Pod's billed buckets over a period (R5).

        Account-wide scope is dropped on purpose: invoice totals include work this
        pipeline never ingests. One transaction, serialized per Pod, writes the period
        evidence row and - on a match - the internal INVOICE_VERIFIED bucket revisions,
        per-bucket verifications and budget finalizations. Mismatches persist the period
        row only. Replay is idempotent; conflicting or superseding evidence follows R6.
        """
        for label, value in (
            ("period_start", period_start),
            ("period_end", period_end),
            ("observed_at", observed_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise SchemaInvalid(f"{label} must be timezone-aware")
        if period_end <= period_start:
            raise SchemaInvalid("invoice period must be non-empty")
        if amount_micro_usd < 0:
            raise SchemaInvalid("invoice amount must be non-negative")
        if source not in ("INVOICE", "CONSOLE"):
            raise SchemaInvalid("invoice evidence source must be INVOICE or CONSOLE")
        audit = (supersedes_evidence_id, actor_ref, reason)
        if any(item is not None for item in audit) and not all(
            item is not None and str(item).strip() for item in audit
        ):
            raise SchemaInvalid(
                "an explicit supersede requires supersedes_evidence_id, actor and reason"
            )

        def operation(tx: Tx) -> InvoicePeriodResult:
            tx.fetchval(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 451050))",
                (f"{provider_account_ref}:{pod_id}",),
            )
            existing = tx.fetchone(
                "SELECT * FROM runpod_billing_period_evidence WHERE provider_account_ref=%s "
                "AND pod_id=%s AND period_start=%s AND period_end=%s AND evidence_sha256=%s",
                (provider_account_ref, pod_id, period_start, period_end, evidence_sha256),
            )
            if existing is not None:
                if (
                    existing["amount_micro_usd"] != amount_micro_usd
                    or existing["currency"] != currency
                ):
                    raise IdempotencyConflict(
                        "invoice evidence replayed with a different amount or currency"
                    )
                return InvoicePeriodResult(
                    period_evidence_id=existing["period_evidence_id"],
                    outcome=existing["outcome"],
                    amount_micro_usd=existing["amount_micro_usd"],
                    bucket_sum_micro_usd=existing["bucket_sum_micro_usd"],
                    replayed=True,
                )
            if currency != "USD":
                raise SchemaInvalid("invoice verification must be denominated in USD")
            if supersedes_evidence_id is not None:
                target = tx.fetchone(
                    "SELECT * FROM runpod_billing_period_evidence WHERE period_evidence_id=%s",
                    (supersedes_evidence_id,),
                )
                if (
                    target is None
                    or target["provider_account_ref"] != provider_account_ref
                    or target["pod_id"] != pod_id
                    or target["period_start"] >= period_end
                    or target["period_end"] <= period_start
                ):
                    raise SchemaInvalid("superseded evidence must exist for the same Pod period")
            else:
                verified_overlap = tx.fetchone(
                    "SELECT period_evidence_id FROM runpod_billing_period_evidence "
                    "WHERE provider_account_ref=%s AND pod_id=%s AND period_start < %s "
                    "AND period_end > %s AND outcome IN ('MATCHED','MATCHED_ZERO')",
                    (provider_account_ref, pod_id, period_end, period_start),
                )
                if verified_overlap is not None:
                    raise Conflict(
                        "new invoice evidence for an already-verified period requires an "
                        "explicit supersede",
                        period_evidence_id=str(verified_overlap["period_evidence_id"]),
                    )
            covering_query = tx.fetchone(
                # T045-FIX A-N3: the covering query must be Pod-scoped — a BUCKETS
                # query counts only when it observed this Pod and no other. An EMPTY
                # query carries no bucket evidence either way (the query contract has
                # no pod field), so it stays valid coverage for the billed-zero route.
                "SELECT * FROM runpod_billing_queries q WHERE q.provider_account_ref=%s "
                "AND q.result_state IN ('BUCKETS','EMPTY') "
                "AND (q.payload->>'requested_window_start')::timestamptz <= %s "
                "AND (q.payload->>'requested_window_end')::timestamptz >= %s "
                "AND q.observed_at >= %s "
                "AND (q.result_state = 'EMPTY' OR ("
                "EXISTS (SELECT 1 FROM runpod_billing_buckets b "
                "WHERE b.query_id = q.query_id AND b.pod_id = %s) "
                "AND NOT EXISTS (SELECT 1 FROM runpod_billing_buckets b "
                "WHERE b.query_id = q.query_id AND b.pod_id <> %s))) "
                "ORDER BY q.observed_at DESC LIMIT 1",
                (
                    provider_account_ref,
                    period_start,
                    period_end,
                    period_end + self.settle_lag,
                    pod_id,
                    pod_id,
                ),
            )
            if covering_query is None:
                raise Conflict("no completed billing query covers the period after the settle lag")
            # T045-FIX A-B1: a skip only refuses the period while no stored closed
            # bucket of the same identity was observed at or after the skip. Once a
            # later poll closed it, the skip is historical, not an open question.
            unresolved_skip = tx.fetchone(
                "SELECT s.skip_id FROM runpod_billing_query_skipped_buckets s "
                "WHERE s.provider_account_ref=%s AND s.pod_id=%s AND s.bucket_start < %s "
                "AND s.bucket_end > %s AND NOT EXISTS ("
                "SELECT 1 FROM runpod_billing_buckets b "
                "WHERE b.provider_account_ref = s.provider_account_ref "
                "AND b.pod_id = s.pod_id AND b.bucket_start = s.bucket_start "
                "AND b.bucket_end = s.bucket_end "
                "AND b.bucket_size_seconds = s.bucket_size_seconds "
                "AND b.observed_at >= s.observed_at) LIMIT 1",
                (provider_account_ref, pod_id, period_end, period_start),
            )
            if unresolved_skip is not None:
                raise Conflict(
                    "the period still contains skipped-open buckets; retry once they settle"
                )
            rows = tx.fetchall(
                "SELECT DISTINCT ON (bucket_identity_sha256) * FROM runpod_billing_buckets "
                "WHERE provider_account_ref=%s AND pod_id=%s AND bucket_start < %s "
                "AND bucket_end > %s ORDER BY bucket_identity_sha256, revision DESC",
                (provider_account_ref, pod_id, period_end, period_start),
            )
            # T045-FIX A-N4: a bucket that straddles a period edge must refuse the
            # verification even when aligned buckets exist at both edges — its amount
            # is not this period's.
            straddling = [
                row
                for row in rows
                if row["bucket_start"] < period_start or row["bucket_end"] > period_end
            ]
            if straddling:
                raise SchemaInvalid(
                    "a billing bucket straddles the period edge; pick a period on bucket "
                    "boundaries"
                )
            if rows:
                if not (
                    any(row["bucket_start"] == period_start for row in rows)
                    and any(row["bucket_end"] == period_end for row in rows)
                ):
                    raise SchemaInvalid("invoice period edges must lie on bucket boundaries")
            bucket_sum = sum(int(row["total_amount_micro_usd"]) for row in rows)
            matched_zero = amount_micro_usd == 0 and not rows
            if matched_zero and covering_query["result_state"] != "EMPTY":
                raise Conflict(
                    "a billed-zero period requires an EMPTY query covering it after the lag"
                )
            outcome = (
                "MATCHED"
                if rows and bucket_sum == amount_micro_usd
                else "MATCHED_ZERO"
                if matched_zero
                else "MISMATCHED"
            )
            evidence_id = uuid4()
            tx.execute(
                "INSERT INTO runpod_billing_period_evidence (period_evidence_id,"
                "provider_account_ref,pod_id,period_start,period_end,amount_micro_usd,currency,"
                "evidence_sha256,evidence_source,observed_at,outcome,bucket_sum_micro_usd,"
                "supersedes_evidence_id,actor_ref,reason) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    evidence_id,
                    provider_account_ref,
                    pod_id,
                    period_start,
                    period_end,
                    amount_micro_usd,
                    currency,
                    evidence_sha256,
                    source,
                    observed_at,
                    outcome,
                    bucket_sum,
                    supersedes_evidence_id,
                    actor_ref.strip() if actor_ref else None,
                    reason.strip() if reason else None,
                ),
            )
            if outcome == "MATCHED":
                for row in rows:
                    self._verify_bucket_revision_in_transaction(
                        tx,
                        row=row,
                        provider_account_ref=provider_account_ref,
                        evidence_id=evidence_id,
                        evidence_sha256=evidence_sha256,
                        source=source,
                        observed_at=observed_at,
                        period=(period_start, period_end),
                    )
            return InvoicePeriodResult(
                period_evidence_id=evidence_id,
                outcome=outcome,
                amount_micro_usd=amount_micro_usd,
                bucket_sum_micro_usd=bucket_sum,
            )

        try:
            return self.db.run_in_transaction(operation)
        except DuplicateSemanticKey as exc:
            # A concurrent verification won the unique keys: surface the typed replay
            # answer instead of an integrity error (R6).
            constraint = str(exc.details.get("constraint") or "")
            if "period_evidence" in constraint:
                raise IdempotencyConflict(
                    "invoice evidence was already recorded for this period"
                ) from exc
            raise Conflict("invoice evidence conflicts with an existing verification") from exc

    def _verify_bucket_revision_in_transaction(
        self,
        tx: Tx,
        *,
        row: Any,
        provider_account_ref: str,
        evidence_id: UUID,
        evidence_sha256: str,
        source: str,
        observed_at: datetime,
        period: tuple[datetime, datetime],
    ) -> None:
        """Write one bucket's internal INVOICE_VERIFIED revision and its evidence (R5)."""
        if row["finality_state"] == "DISPUTED":
            raise Conflict(
                "a disputed bucket cannot be invoice-matched until the provider data is corrected"
            )
        prior = RunpodBillingBucketObservation.model_validate(row["payload"])
        if row["finality_state"] == "INVOICE_VERIFIED":
            return  # already verified by an earlier overlapping period
        verification_id = uuid5(
            NAMESPACE_URL,
            f"runpod-period-verification:{evidence_id}:{row['bucket_identity_sha256']}",
        )
        verified_payload = prior.model_dump(mode="python")
        verified_payload.update(
            observation_id=uuid5(
                NAMESPACE_URL,
                f"runpod-verified:{evidence_id}:{row['bucket_identity_sha256']}",
            ),
            query_id=uuid5(
                NAMESPACE_URL,
                f"runpod-period-query:{evidence_id}:{row['bucket_identity_sha256']}",
            ),
            revision=prior.revision + 1,
            prior_observation_id=prior.observation_id,
            prior_raw_response_sha256=prior.raw_response_sha256,
            observed_at=observed_at,
            finality_state=BillingFinalityState.INVOICE_VERIFIED,
            invoice_verification_id=verification_id,
        )
        verified = RunpodBillingBucketObservation.model_validate(verified_payload)
        query = RunpodBillingQueryObservation(
            query_id=verified.query_id,
            provider_account_ref=provider_account_ref,
            requested_window_start=period[0],
            requested_window_end=period[1],
            provider_resolved_window_start=period[0],
            provider_resolved_window_end=period[1],
            bucket_size_seconds=verified.bucket_size_seconds,
            raw_response_sha256=sha256_hex(
                f"runpod-period-evidence:{evidence_sha256}:{row['bucket_identity_sha256']}".encode()
            ),
            observed_at=observed_at,
            result_state=BillingQueryState.BUCKETS,
            bucket_observation_ids=[verified.observation_id],
        )
        self._ingest_in_transaction(tx, query, [verified], [], [], verified_finality=True)
        verification = BillingInvoiceVerification(
            verification_id=verification_id,
            provider_account_ref=provider_account_ref,
            bucket_identity_sha256=verified.bucket_identity_sha256,
            bucket_observation_id=verified.observation_id,
            bucket_revision=verified.revision,
            evidence_source=source,  # type: ignore[arg-type]
            evidence_sha256=evidence_sha256,
            evidence_observed_at=observed_at,
            verified_at=observed_at,
            currency="USD",
            amount_micro_usd=verified.total_amount_micro_usd,
            result=BillingVerificationResult.MATCHED,
        )
        validate_billing_invoice_verification(verified, verification)
        tx.execute(
            "INSERT INTO runpod_billing_invoice_verifications (verification_id,bucket_observation_id,bucket_identity_sha256,evidence_sha256,verified_at,result,payload) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                verification.verification_id,
                verified.observation_id,
                verified.bucket_identity_sha256,
                verification.evidence_sha256,
                verification.verified_at,
                verification.result.value,
                jsonb(verification),
            ),
        )
        if self.budget_service is not None:
            self.budget_service.record_provider_invoice_verification_in_transaction(
                tx, verified, verification
            )

    @staticmethod
    def matched_invoice_periods(
        tx: Tx, lease: Any, window_start: datetime, coverage_end: datetime
    ) -> list[Any]:
        """MATCHED/MATCHED_ZERO period evidence overlapping the lease's coverage."""
        account_ref = lease["provider_account_ref"]
        return tx.fetchall(
            "SELECT * FROM runpod_billing_period_evidence WHERE pod_id=%s "
            "AND (%s::text IS NULL OR provider_account_ref=%s) AND period_start < %s "
            "AND period_end > %s AND outcome IN ('MATCHED','MATCHED_ZERO') "
            "AND NOT EXISTS (SELECT 1 FROM runpod_billing_period_evidence s "
            "WHERE s.supersedes_evidence_id = runpod_billing_period_evidence.period_evidence_id) "
            "ORDER BY period_start, period_end",
            (lease["pod_id"], account_ref, account_ref, coverage_end, window_start),
        )

    @staticmethod
    def derive_allocations(
        tx: Tx,
        bucket: RunpodBillingBucketObservation,
        prior: RunpodBillingBucketObservation | None = None,
    ) -> list[RunpodBillingAllocation]:
        """Build signed revision deltas from durable lease windows and storage ownership.

        T045 R1 (G1): Runpod reports no usage intervals, so lease episodes come from
        ``pod_leases`` compute windows. The GPU/CPU denominator is the Pod's existence
        seconds inside the bucket - from the chain root's ``create_requested_at`` to the
        last lease's verified stop or terminate - never the bucket length: a partly used
        hour is allocated to the episodes that existed in it. Existence covered by no
        lease goes to the root lease's episode, or to the recovery pool when the Pod has
        no root lease. Disk is allocated by storage-ownership seconds; existence the
        ownership rows do not cover is recovery, never a neighbouring episode.
        """
        start, end = bucket.bucket_start, bucket.bucket_end
        duration = max(1, int((end - start).total_seconds()))
        leases = tx.fetchall(
            "SELECT id, owner_episode_id::text AS owner, transferred_from, "
            "COALESCE(compute_window_start_at, create_requested_at, created_at) AS window_start, "
            "COALESCE(compute_window_end_at, stop_verified_at, terminate_verified_at) AS window_end "
            "FROM pod_leases WHERE provider='runpod' AND pod_id=%s ORDER BY created_at",
            (bucket.pod_id,),
        )
        root = next((row for row in leases if row["transferred_from"] is None), None)

        def clip(window_start: datetime, window_end: datetime | None) -> tuple[datetime, datetime]:
            return max(start, window_start), min(end, window_end or end)

        gpu_cpu_weights: dict[str, int] = {}
        existence: tuple[datetime, datetime] | None = None
        if leases:
            # The chain exists from the root's create request (the earliest lease window
            # when no root is recorded) until the last lease's verified stop or
            # terminate; while that is still unknown, the bucket end is the
            # conservative bound.
            chain_start = (
                root["window_start"] if root is not None else min(r["window_start"] for r in leases)
            )
            lo, hi = clip(chain_start, max((row["window_end"] or end) for row in leases))
            if hi > lo:
                existence = (lo, hi)
        if existence is not None:
            for row in leases:
                lo, hi = clip(row["window_start"], row["window_end"])
                if hi > lo:
                    seconds = _ceil_seconds(hi - lo)
                    gpu_cpu_weights[row["owner"]] = gpu_cpu_weights.get(row["owner"], 0) + seconds
            covered = sum(gpu_cpu_weights.values())
            existence_seconds = _ceil_seconds(existence[1] - existence[0])
            if covered < existence_seconds:
                # Existence covered by no lease belongs to the root lease's episode,
                # or to the recovery pool when the Pod has no root lease.
                uncovered = existence_seconds - covered
                if root is not None:
                    gpu_cpu_weights[root["owner"]] = (
                        gpu_cpu_weights.get(root["owner"], 0) + uncovered
                    )
                else:
                    gpu_cpu_weights["recovery_pool"] = uncovered
        if not gpu_cpu_weights:
            # No recorded existence at all: a non-zero bucket is 100% recovery.
            gpu_cpu_weights = {"recovery_pool": duration}

        disk_owners = tx.fetchall(
            "SELECT owner_episode_id::text AS owner, "
            "CEIL(EXTRACT(EPOCH FROM LEAST(COALESCE(valid_until,%s),%s)"
            "-GREATEST(valid_from,%s)))::bigint AS seconds "
            "FROM pod_storage_ownership WHERE provider='runpod' AND pod_id=%s "
            "AND valid_from<%s AND COALESCE(valid_until,%s)>%s",
            # 5 is ``valid_from < end`` and 6 is ``COALESCE(valid_until, end) > start``:
            # an open row (valid_until NULL) extends to the bucket end and stays
            # eligible — the pre-T045 binding excluded exactly those rows. CEIL so a
            # sub-second ownership (a canary that lived seconds) still counts as one
            # second of owner weight instead of vanishing to a zero-weight row.
            (end, end, start, bucket.pod_id, end, end, start),
        )
        disk_weights: dict[str, int] = {}
        for row in disk_owners:
            seconds = max(0, int(row["seconds"]))
            if seconds > 0:
                # A zero-second ownership row carries no weight: a zero-weight owner
                # must not swallow the component as a zero delta — uncovered disk is
                # recovery, and conservation holds.
                disk_weights[row["owner"]] = disk_weights.get(row["owner"], 0) + seconds
        if existence is not None:
            disk_covered = sum(disk_weights.values())
            if disk_covered < existence_seconds:
                disk_weights["recovery_pool"] = (
                    disk_weights.get("recovery_pool", 0) + existence_seconds - disk_covered
                )
        if not disk_weights:
            disk_weights = {"recovery_pool": duration}

        created = datetime.now(UTC)
        fields = {
            BillingComponent.GPU: "gpu_amount_micro_usd",
            BillingComponent.CPU: "cpu_amount_micro_usd",
            BillingComponent.DISK: "disk_amount_micro_usd",
        }
        prior_amounts = {
            BillingComponent.GPU: prior.gpu_amount_micro_usd if prior else 0,
            BillingComponent.CPU: prior.cpu_amount_micro_usd if prior else 0,
            BillingComponent.DISK: prior.disk_amount_micro_usd if prior else 0,
        }
        output: list[RunpodBillingAllocation] = []
        for component, field in fields.items():
            weights = disk_weights if component is BillingComponent.DISK else gpu_cpu_weights
            basis = (
                BillingAllocationBasis.STORAGE_OWNER
                if component is BillingComponent.DISK
                else BillingAllocationBasis.MEASURED_OVERLAP
            )
            delta = int(getattr(bucket, field)) - prior_amounts[component]
            shares = largest_remainder(delta, sorted(weights.items()))
            for owner, amount in shares.items():
                recovery = owner == "recovery_pool"
                output.append(
                    RunpodBillingAllocation(
                        allocation_id=uuid4(),
                        bucket_identity_sha256=bucket.bucket_identity_sha256,
                        bucket_observation_id=bucket.observation_id,
                        bucket_revision=bucket.revision,
                        component=component,
                        owner_kind="RECOVERY" if recovery else "EPISODE",
                        owner_id="recovery_pool" if recovery else owner,
                        allocation_basis=BillingAllocationBasis.UNCOVERED if recovery else basis,
                        delta_micro_usd=amount,
                        allocated_at=created,
                    )
                )
        return output


def _lease_readiness_in_transaction(tx: Tx, lease: Any) -> LeaseBillingReadiness:
    """R7 readiness for one lease row, inside a caller-owned read transaction."""
    lease_id = lease["id"]
    pending_since = lease["compute_window_end_at"] or lease["updated_at"]
    window_start = lease["compute_window_start_at"] or lease["create_requested_at"]
    if window_start is None:
        # Nothing was ever sent for this lease: no compute window, nothing to bill.
        return LeaseBillingReadiness(lease_id, "BILLED", None, billed_micro_usd=0)
    if lease["compute_window_end_at"] is None:
        return LeaseBillingReadiness(lease_id, "PENDING_PROVIDER_FINALITY", pending_since)
    window_end = lease["compute_window_end_at"]

    storage_rows = tx.fetchall(
        "SELECT valid_until FROM pod_storage_ownership WHERE provider=%s AND pod_id=%s "
        "AND owner_episode_id=%s",
        (lease["provider"], lease["pod_id"], lease["owner_episode_id"]),
    )
    storage_end = window_end
    for row in storage_rows:
        end = row["valid_until"] or lease["terminate_verified_at"]
        if end is None:
            # Storage is still owned with no verified terminate: the window is open.
            return LeaseBillingReadiness(lease_id, "PENDING_PROVIDER_FINALITY", pending_since)
        storage_end = max(storage_end, end)
    coverage_end = max(window_end, storage_end)

    buckets = tx.fetchall(
        "SELECT DISTINCT ON (bucket_identity_sha256) observation_id, bucket_start, "
        "bucket_end, total_amount_micro_usd, finality_state, revision, observed_at "
        "FROM runpod_billing_buckets WHERE pod_id=%s "
        "AND (%s::text IS NULL OR provider_account_ref=%s) AND bucket_start < %s "
        "AND bucket_end > %s ORDER BY bucket_identity_sha256, revision DESC",
        (
            lease["pod_id"],
            lease["provider_account_ref"],
            lease["provider_account_ref"],
            coverage_end,
            window_start,
        ),
    )
    if any(row["finality_state"] == "DISPUTED" for row in buckets):
        return LeaseBillingReadiness(lease_id, "DISPUTED", pending_since)
    mismatched_open = tx.fetchone(
        "SELECT period_evidence_id FROM runpod_billing_period_evidence WHERE pod_id=%s "
        "AND (%s::text IS NULL OR provider_account_ref=%s) AND outcome='MISMATCHED' "
        "AND period_start < %s AND period_end > %s AND NOT EXISTS ("
        "SELECT 1 FROM runpod_billing_period_evidence newer WHERE newer.pod_id=%s "
        "AND newer.supersedes_evidence_id = runpod_billing_period_evidence.period_evidence_id)",
        (
            lease["pod_id"],
            lease["provider_account_ref"],
            lease["provider_account_ref"],
            coverage_end,
            window_start,
            lease["pod_id"],
        ),
    )
    if mismatched_open is not None:
        return LeaseBillingReadiness(lease_id, "DISPUTED", pending_since)
    unresolved_recovery = tx.fetchval(
        "SELECT EXISTS (SELECT 1 FROM runpod_billing_allocations a "
        "JOIN runpod_billing_buckets b ON b.observation_id=a.bucket_observation_id "
        "LEFT JOIN runpod_billing_recovery_resolutions r USING (allocation_id) "
        "WHERE b.pod_id=%s AND a.owner_kind='RECOVERY' AND a.delta_micro_usd>0 "
        "AND r.allocation_id IS NULL)",
        (lease["pod_id"],),
    )
    if unresolved_recovery:
        return LeaseBillingReadiness(lease_id, "RECOVERY_REQUIRED", pending_since)

    posted_gpu = lambda: int(  # noqa: E731 - local readability
        tx.fetchval(
            "SELECT COALESCE(SUM(amount_micro_usd),0)::bigint FROM charges "
            "WHERE reservation_id=%s AND category='GPU_GENERATION' "
            "AND kind IN ('ACCRUAL','ADJUSTMENT')",
            (lease["reservation_id"],),
        )
        or 0
    )
    # REOPENED is derived: a settled lease whose covering evidence moved again. The
    # revision's positive delta posts an ADJUSTMENT on the closed reservation; the
    # state stays BILLED because the settlement already released the remainder.
    reservation_state = tx.fetchval(
        "SELECT state FROM reservations WHERE id=%s", (lease["reservation_id"],)
    )
    if reservation_state == "SETTLED":
        settled_at = tx.fetchval(
            "SELECT created_at FROM charges WHERE reservation_id=%s "
            "AND kind='SETTLEMENT' ORDER BY created_at DESC LIMIT 1",
            (lease["reservation_id"],),
        )
        if settled_at is not None:
            newer_revision = tx.fetchval(
                "SELECT EXISTS (SELECT 1 FROM runpod_billing_buckets b "
                "WHERE b.pod_id=%s AND b.observed_at > %s AND b.bucket_start < %s "
                "AND b.bucket_end > %s)",
                (lease["pod_id"], settled_at, coverage_end, window_start),
            )
            later_adjustment = tx.fetchval(
                "SELECT EXISTS (SELECT 1 FROM charges WHERE reservation_id=%s "
                "AND kind='ADJUSTMENT' AND created_at > %s)",
                (lease["reservation_id"], settled_at),
            )
            if newer_revision or later_adjustment:
                return LeaseBillingReadiness(
                    lease_id, "BILLED", None, billed_micro_usd=posted_gpu(), reopened=True
                )

    evidence = BillingRepository.matched_invoice_periods(tx, lease, window_start, coverage_end)
    cursor = window_start
    missing: list[tuple[datetime, datetime]] = []
    for row in sorted(evidence, key=lambda item: (item["period_start"], item["period_end"])):
        start = max(window_start, row["period_start"])
        end = min(coverage_end, row["period_end"])
        if end <= cursor:
            continue
        if start > cursor:
            missing.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < coverage_end:
        missing.append((cursor, coverage_end))
    all_verified = all(row["finality_state"] == "INVOICE_VERIFIED" for row in buckets)
    if not missing and all_verified:
        return LeaseBillingReadiness(
            lease_id, "BILLED", None, billed_micro_usd=posted_gpu(), reopened=False
        )
    # Buckets missing or unverified: awaiting an invoice when the missing time has
    # already been queried past the settle lag, pending provider finality otherwise.
    for gap_start, gap_end in missing:
        # T045-FIX A-N3 (readiness side): the gap query must be Pod-scoped like the
        # verification covering query — another Pod's response is not this lease's
        # coverage. Conservative: an unscoped-looking query leaves the lease pending.
        queried = tx.fetchval(
            "SELECT EXISTS (SELECT 1 FROM runpod_billing_queries q WHERE "
            "(%s::text IS NULL OR q.provider_account_ref=%s) "
            "AND q.result_state IN ('BUCKETS','EMPTY') "
            "AND (q.payload->>'requested_window_start')::timestamptz <= %s "
            "AND (q.payload->>'requested_window_end')::timestamptz >= %s "
            "AND q.observed_at >= %s "
            "AND (q.result_state = 'EMPTY' OR ("
            "EXISTS (SELECT 1 FROM runpod_billing_buckets b WHERE b.query_id=q.query_id "
            "AND b.pod_id=%s) "
            "AND NOT EXISTS (SELECT 1 FROM runpod_billing_buckets b WHERE b.query_id=q.query_id "
            "AND b.pod_id<>%s))))",
            (
                lease["provider_account_ref"],
                lease["provider_account_ref"],
                gap_start,
                gap_end,
                gap_end + DEFAULT_SETTLE_LAG,
                lease["pod_id"],
                lease["pod_id"],
            ),
        )
        if not queried:
            return LeaseBillingReadiness(
                lease_id,
                "PENDING_PROVIDER_FINALITY",
                pending_since,
                missing_windows=tuple(missing),
            )
    return LeaseBillingReadiness(
        lease_id, "AWAITING_INVOICE", pending_since, missing_windows=tuple(missing)
    )


def lease_billing_readiness(db: Database, lease_id: UUID) -> LeaseBillingReadiness:
    """Readiness for one lease (R7). Read-only; never a spend-release side effect."""
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
        if lease is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
        return _lease_readiness_in_transaction(tx, lease)


def settle_billed_lease(db: Database, budget: Any, *, lease_id: UUID, context: str) -> int:
    """Post the deterministic BILLED settlement for a final lease (R7).

    The amount is the sum of GPU ACCRUAL + ADJUSTMENT postings on the lease's
    reservation — no new money; it may be 0. The ledger's SETTLEMENT releases exactly
    the unused remainder (including from an EXPIRED reservation). A replay is a no-op.
    Any posted-versus-invoice overstatement is stored as evidence.
    """
    with db.transaction(readonly=True) as tx:
        lease = tx.fetchone("SELECT * FROM pod_leases WHERE id=%s", (lease_id,))
        if lease is None:
            raise NotFound("pod lease not found", lease_id=str(lease_id))
        readiness = _lease_readiness_in_transaction(tx, lease)
        if readiness.state != "BILLED":
            raise Conflict(
                "lease billing is not final; the hold stays",
                lease_id=str(lease_id),
                state=readiness.state,
            )
        total = readiness.billed_micro_usd or 0
        invoice_rows = BillingRepository.matched_invoice_periods(
            tx,
            lease,
            lease["compute_window_start_at"] or lease["create_requested_at"],
            lease["compute_window_end_at"],
        )
        invoice_sum = max((int(row["amount_micro_usd"]) for row in invoice_rows), default=0)
    receipt = UsageReceipt(
        receipt_id=uuid5(NAMESPACE_URL, f"runpod-billed-settle:{lease_id}"),
        provider=lease["provider"],
        provider_receipt_id=f"podlease-billed:{lease_id}",
        kind=ReceiptKind.SETTLEMENT,
        cost_basis=CostBasis.BILLED,
        reservation_id=lease["reservation_id"],
        episode_id=lease["owner_episode_id"],
        season_id=None,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=total,
        currency="USD",
        units=0,
        unit=PriceUnit.GPU_SECOND,
        interval_start=None,
        interval_end=None,
        observed_at=lease["updated_at"],
        provenance=Provenance.LIVE_PROVIDER,
    )
    result = budget.record_usage(receipt)
    if not result.replayed and total > invoice_sum:
        with db.transaction() as tx:
            append_event(
                tx,
                aggregate_type="pod_lease",
                aggregate_id=lease_id,
                event_type="billing.overstatement_recorded",
                payload={
                    "posted_micro_usd": total,
                    "invoice_micro_usd": invoice_sum,
                    "overstatement_micro_usd": total - invoice_sum,
                    "context": context,
                },
                correlation_id=lease_id,
                occurred_at=datetime.now(UTC),
            )
    return total


def raw_body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()

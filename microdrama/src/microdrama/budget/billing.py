"""Durable reconciliation of time-bucketed Runpod billing observations.

Provider amounts are parsed from their JSON lexical representation. This module never
turns provider buckets into GPU interval receipts: buckets can cross lease transfers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from microdrama.contracts.cost import (
    BillingAllocationBasis,
    BillingComponent,
    BillingFinalityState,
    BillingInvoiceVerification,
    BillingVerificationResult,
    RunpodBillingAllocation,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    validate_billing_invoice_verification,
    validate_runpod_billing_allocations,
    validate_runpod_billing_query,
    validate_runpod_billing_revision,
)
from microdrama.persistence.db import Database, Tx, jsonb

MICRO_USD = Decimal(1_000_000)


@dataclass(frozen=True)
class BillingAccountingReadiness:
    """Read-only accounting evidence for one pod/window; never a spend-release signal."""

    state: str
    covered: bool
    provider_reported_micro_usd: int
    invoice_verified_micro_usd: int
    pending_exposure_held: bool
    unresolved_recovery: bool
    missing_windows: tuple[tuple[datetime, datetime], ...]
    observation_ids: tuple[str, ...]


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


class BillingRepository:
    """Append-only persistence for canonical 2.13 billing records."""

    def __init__(self, db: Database, budget_service: Any | None = None) -> None:
        self.db = db
        self.budget_service = budget_service

    def ingest(
        self,
        query: RunpodBillingQueryObservation,
        buckets: list[RunpodBillingBucketObservation],
        allocations: list[RunpodBillingAllocation] | None = None,
    ) -> None:
        allocations = allocations or []

        def operation(tx: Tx) -> None:
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
                    raise ValueError("billing query ID replayed with different content")
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
                if prior and prior["raw_response_sha256"] == bucket.raw_response_sha256:
                    if RunpodBillingBucketObservation.model_validate(prior["payload"]) != bucket:
                        raise ValueError(
                            "billing response hash replayed with different bucket content"
                        )
                    continue
                prior_model = (
                    RunpodBillingBucketObservation.model_validate(prior["payload"])
                    if prior
                    else None
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
                        raise ValueError("billing bucket revision references a missing prior")
                    prior_observations[bucket.observation_id] = (
                        RunpodBillingBucketObservation.model_validate(row["payload"])
                    )
            validate_runpod_billing_query(
                query, buckets, effective_allocations, prior_observations=prior_observations
            )

        self.db.run_in_transaction(operation)

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
                "INSERT INTO runpod_billing_invoice_verifications (verification_id,bucket_observation_id,evidence_sha256,verified_at,result,payload) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    verification.verification_id,
                    bucket.observation_id,
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

    def accounting_readiness(
        self, provider_account_ref: str, pod_id: str, since: datetime, until: datetime
    ) -> BillingAccountingReadiness:
        """Describe observed/final billing coverage; pending or absent evidence keeps exposure held."""
        if until <= since:
            raise ValueError("billing readiness window must be non-empty")
        with self.db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT observation_id,bucket_start,bucket_end,total_amount_micro_usd,finality_state "
                "FROM runpod_billing_buckets WHERE provider_account_ref=%s AND pod_id=%s "
                "AND bucket_start<%s AND bucket_end>%s ORDER BY bucket_start,bucket_end,revision",
                (provider_account_ref, pod_id, until, since),
            )
            unresolved_recovery = bool(
                tx.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM runpod_billing_allocations a "
                    "JOIN runpod_billing_buckets b ON b.observation_id=a.bucket_observation_id "
                    "LEFT JOIN runpod_billing_recovery_resolutions r USING (allocation_id) "
                    "WHERE b.provider_account_ref=%s AND b.pod_id=%s AND b.bucket_start<%s "
                    "AND b.bucket_end>%s AND a.owner_kind='RECOVERY' AND a.delta_micro_usd>0 "
                    "AND r.allocation_id IS NULL)",
                    (provider_account_ref, pod_id, until, since),
                )
            )
        latest_by_bucket: dict[tuple[datetime, datetime], Any] = {}
        for row in rows:
            latest_by_bucket[(row["bucket_start"], row["bucket_end"])] = row
        latest = list(latest_by_bucket.values())
        buckets = [row for row in latest if row["finality_state"] != "DISPUTED"]
        cursor = since
        missing: list[tuple[datetime, datetime]] = []
        for row in buckets:
            start = max(since, row["bucket_start"])
            end = min(until, row["bucket_end"])
            if end <= cursor:
                continue
            if start > cursor:
                missing.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < until:
            missing.append((cursor, until))
        covered = not missing
        relevant = [
            row for row in buckets if row["bucket_start"] >= since and row["bucket_end"] <= until
        ]
        latest = relevant
        reported = sum(int(row["total_amount_micro_usd"]) for row in latest)
        verified = sum(
            int(row["total_amount_micro_usd"])
            for row in latest
            if row["finality_state"] == "INVOICE_VERIFIED"
        )
        fully_verified = (
            covered
            and bool(latest)
            and all(row["finality_state"] == "INVOICE_VERIFIED" for row in latest)
        )
        pending = not fully_verified or unresolved_recovery
        return BillingAccountingReadiness(
            state=(
                "RECOVERY_REQUIRED"
                if unresolved_recovery
                else "INVOICE_VERIFIED"
                if fully_verified
                else "PENDING"
                if latest
                else "UNKNOWN"
            ),
            covered=covered,
            provider_reported_micro_usd=reported,
            invoice_verified_micro_usd=verified,
            pending_exposure_held=pending,
            unresolved_recovery=unresolved_recovery,
            missing_windows=tuple(missing),
            observation_ids=tuple(str(row["observation_id"]) for row in latest),
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
                seconds = int((hi - lo).total_seconds())
                if seconds > 0:
                    gpu_cpu_weights[row["owner"]] = gpu_cpu_weights.get(row["owner"], 0) + seconds
            covered = sum(gpu_cpu_weights.values())
            existence_seconds = int((existence[1] - existence[0]).total_seconds())
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
            "EXTRACT(EPOCH FROM LEAST(COALESCE(valid_until,%s),%s)-GREATEST(valid_from,%s))::bigint AS seconds "
            "FROM pod_storage_ownership WHERE provider='runpod' AND pod_id=%s "
            "AND valid_from<%s AND COALESCE(valid_until,%s)>%s",
            # 5 is ``valid_from < end`` and 6 is ``COALESCE(valid_until, end) > start``:
            # an open row (valid_until NULL) extends to the bucket end and stays
            # eligible — the pre-T045 binding excluded exactly those rows.
            (end, end, start, bucket.pod_id, end, end, start),
        )
        disk_weights: dict[str, int] = {}
        for row in disk_owners:
            disk_weights[row["owner"]] = disk_weights.get(row["owner"], 0) + max(
                0, int(row["seconds"])
            )
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


def raw_body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()

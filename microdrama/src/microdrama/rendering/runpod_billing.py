"""Runpod billing-history ingestion helpers (T045 R9, G10).

Maps the provider's time-bucketed ``RunpodBillingRecord`` rows to canonical
``RunpodBillingBucketObservation`` objects with exact integer micro-USD — no float
arithmetic, no rounding — so the janitor can store them through the R4 ingest path.
Revision lineage is resolved against the durable table: an identical response is an
exact replay (it adds nothing) and a changed one maps to revision N+1 with its prior
links, so only the delta posts (R2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from microdrama.contracts.cost import (
    BillingFinalityState,
    BillingQueryState,
    RunpodBillingBucketObservation,
    RunpodBillingQueryObservation,
    runpod_bucket_identity_sha256,
)
from microdrama.contracts.errors import Conflict
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence.db import Database
from microdrama.rendering.runpod_transport import RunpodBillingHistory

#: The bucket size the live adapter requests (Runpod documents hourly buckets).
REQUESTED_BUCKET_SIZE_SECONDS = 3600


@dataclass(frozen=True)
class MappedBillingIngest:
    """One mapped provider response: its query plus the observations it contributes."""

    query: RunpodBillingQueryObservation
    buckets: list[RunpodBillingBucketObservation]
    replayed_records: int = 0


def _record_hash(record: object) -> str:
    """Content hash of one provider record: deterministic across runs and revisions."""
    return canonical_hash(
        {
            "pod_id": record.pod_id,
            "interval_start": record.interval_start,
            "interval_end": record.interval_end,
            "total_micro_usd": record.total_micro_usd,
            "gpu_micro_usd": record.gpu_micro_usd,
            "cpu_micro_usd": record.cpu_micro_usd,
            "disk_micro_usd": record.disk_micro_usd,
        }
    )


def durable_pod_ownership_probe(
    db: Database, *, owned_tag: str, provider_account_ref: str
) -> Callable[[str], bool]:
    """The R9 absent-Pod ownership proof as a provider callback.

    A terminated Pod is gone from the provider, so ownership must come from the
    durable row: a ``pod_leases`` entry with this pod id, the owned-tag namespace,
    the attested account label and a verified terminate.
    """

    def probe(pod_id: str) -> bool:
        with db.transaction(readonly=True) as tx:
            return (
                tx.fetchone(
                    "SELECT 1 FROM pod_leases WHERE provider = 'runpod' AND pod_id = %s "
                    "AND owned_tag = %s AND provider_account_ref = %s "
                    "AND terminate_verified_at IS NOT NULL",
                    (pod_id, owned_tag, provider_account_ref),
                )
                is not None
            )

    return probe


def _delta_microseconds(delta: timedelta) -> int:
    """Exact microseconds of a timedelta, pure integer arithmetic (T045-FIX B-N1)."""
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


#: The integer-epoch reference instant for the bucket rounding below.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def round_up_to_bucket_end(until: datetime) -> datetime:
    """Round a window end up to the end of its final hourly bucket (T045-FIX B-N1).

    The provider returns whole buckets, so an invoice period can only sit on bucket
    boundaries if the durable query window covers the full last bucket of the lease
    (R5 precondition). Pure integer microseconds - never a float epoch second.
    """
    bucket_us = REQUESTED_BUCKET_SIZE_SECONDS * 1_000_000
    until_us = _delta_microseconds(until - _EPOCH)
    remainder = until_us % bucket_us
    if remainder:
        return until + timedelta(microseconds=bucket_us - remainder)
    return until


def map_billing_history(
    db: Database,
    history: RunpodBillingHistory,
    *,
    provider_account_ref: str,
) -> MappedBillingIngest | None:
    """Map one billing-history response onto canonical observations (G10).

    Returns ``None`` for an exact full replay — the response adds nothing. An empty
    response maps to an ``UNKNOWN`` query: missing buckets are unknown, never zero
    (the billing contract forbids reading them as zero-cost evidence).
    """
    query_id = uuid4()
    if not history.records:
        query = RunpodBillingQueryObservation(
            query_id=query_id,
            provider_account_ref=provider_account_ref,
            requested_window_start=history.requested_start,
            requested_window_end=history.requested_end,
            provider_resolved_window_start=history.resolved_start,
            provider_resolved_window_end=history.resolved_end,
            bucket_size_seconds=REQUESTED_BUCKET_SIZE_SECONDS,
            raw_response_sha256=canonical_hash(
                {
                    "resolved_start": history.resolved_start,
                    "resolved_end": history.resolved_end,
                    "records": [],
                }
            ),
            observed_at=history.observed_at,
            result_state=BillingQueryState.UNKNOWN,
            unknown_reason="provider returned no billing buckets for the resolved window",
        )
        return MappedBillingIngest(query=query, buckets=[])

    sizes = {
        # T045-FIX B-N1: integer arithmetic - the window rounding never passes
        # through a binary float.
        _delta_microseconds(record.interval_end - record.interval_start) // 1_000_000
        for record in history.records
    }
    if len(sizes) != 1:
        raise Conflict(
            "provider returned mixed bucket sizes in one billing response",
            sizes=sorted(sizes),
        )
    size = sizes.pop()
    raw_response = canonical_hash(
        {
            "resolved_start": history.resolved_start,
            "resolved_end": history.resolved_end,
            "records": [_record_hash(record) for record in history.records],
        }
    )

    buckets: list[RunpodBillingBucketObservation] = []
    seen: dict[str, str] = {}
    replayed = 0
    for record in history.records:
        identity = runpod_bucket_identity_sha256(
            provider_account_ref,
            record.pod_id,
            record.interval_start,
            record.interval_end,
            size,
        )
        record_hash = _record_hash(record)
        if identity in seen:
            if seen[identity] != record_hash:
                raise Conflict(
                    "provider returned two different amounts for one billing bucket "
                    "in a single response",
                    bucket_identity_sha256=identity,
                )
            continue  # a duplicated row in one response is not a second observation
        seen[identity] = record_hash
        with db.transaction(readonly=True) as tx:
            prior = tx.fetchone(
                "SELECT observation_id, revision, raw_response_sha256 FROM "
                "runpod_billing_buckets WHERE bucket_identity_sha256 = %s "
                "ORDER BY revision DESC LIMIT 1",
                (identity,),
            )
        if prior is not None and prior["raw_response_sha256"] == record_hash:
            replayed += 1
            continue  # exact replay of the stored latest revision: adds nothing
        components_match = record.total_micro_usd == (
            record.gpu_micro_usd + record.cpu_micro_usd + record.disk_micro_usd
        )
        buckets.append(
            RunpodBillingBucketObservation(
                observation_id=uuid4(),
                query_id=query_id,
                provider_account_ref=provider_account_ref,
                pod_id=record.pod_id,
                bucket_start=record.interval_start,
                bucket_end=record.interval_end,
                bucket_size_seconds=size,
                bucket_identity_sha256=identity,
                revision=(prior["revision"] + 1) if prior is not None else 1,
                prior_observation_id=UUID(str(prior["observation_id"])) if prior else None,
                prior_raw_response_sha256=prior["raw_response_sha256"] if prior else None,
                provider_resolved_window_start=history.resolved_start,
                provider_resolved_window_end=history.resolved_end,
                raw_response_sha256=record_hash,
                observed_at=history.observed_at,
                currency="USD",
                total_amount_micro_usd=record.total_micro_usd,
                gpu_amount_micro_usd=record.gpu_micro_usd,
                cpu_amount_micro_usd=record.cpu_micro_usd,
                disk_amount_micro_usd=record.disk_micro_usd,
                finality_state=(
                    BillingFinalityState.ALLOCATED_PROVIDER_REPORTED
                    if components_match
                    else BillingFinalityState.DISPUTED
                ),
                dispute_reason=None
                if components_match
                else "provider bucket total does not equal GPU + CPU + disk",
            )
        )

    if not buckets:
        return None  # every record was an exact replay of stored revisions
    query = RunpodBillingQueryObservation(
        query_id=query_id,
        provider_account_ref=provider_account_ref,
        requested_window_start=history.requested_start,
        requested_window_end=history.requested_end,
        provider_resolved_window_start=history.resolved_start,
        provider_resolved_window_end=history.resolved_end,
        bucket_size_seconds=size,
        raw_response_sha256=raw_response,
        observed_at=history.observed_at,
        result_state=BillingQueryState.BUCKETS,
        bucket_observation_ids=[bucket.observation_id for bucket in buckets],
    )
    return MappedBillingIngest(query=query, buckets=buckets, replayed_records=replayed)

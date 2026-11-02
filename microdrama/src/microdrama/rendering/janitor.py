"""The independent GPU janitor (T012, MD-013): stops owned leaks no worker will stop.

Separately invokable (``python -m microdrama.rendering.janitor``): it needs only the
database, the budget service, a pod provider and configuration — never a worker process,
queue or the main service. One ``sweep()``:

1. cleans live ``pod_leases`` rows whose worker is gone — expired lease, expired
   heartbeat, or an episode sitting in a human wait (SPEC §5 rule 8 backstop) — accruing
   final usage, stopping/terminating the pod with verification, closing the lease with a
   terminal state and settling its budget hold;
2. stops provider-side orphans: pods carrying the pipeline's owned tag with no live lease;
3. releases budget holds of the pod lifecycle (``pod.lease`` / ``pod.stop``) that were
   never bound to a lease row (a crash between reserve and insert) once past a grace
   period;
4. ingests provider billing history for owned Runpod pods whose leases are not BILLED
   (T045 R9), mapping exact micro-USD buckets into the durable repository so the next
   phase can settle on provider-final evidence;
5. settles holds of already-terminal leases a crash left unsettled.

Every action appends an evidence event. The janitor only ever manages pods that carry its
configured owned tag: foreign pods (another team's tag, or untagged) are never returned by
its queries and never stopped. A failing step is recorded and does not block the rest of
the sweep.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from microdrama.budget import BudgetService
from microdrama.budget.billing import BillingRepository
from microdrama.config import Settings
from microdrama.contracts.enums import EpisodeState, LeaseState, PodState
from microdrama.contracts.errors import MicrodramaError
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.providers import PodProvider
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.events import append_event, list_events
from microdrama.persistence.db import Database, Tx, update_with_revision
from microdrama.rendering.finality import (
    LeaseBillingFinality,
    check_finality_pairing,
)
from microdrama.rendering.leases import (
    RENDERING_NAMESPACE,
    PodLeaseConfig,
    accrue_lease_usage,
    close_storage_ownership,
    open_storage_ownership,
)
from microdrama.rendering.pods import (
    LEASE_OPERATION_KIND,
    STOP_OPERATION_KIND,
    PodManager,
    resolve_pod_provider,
)
from microdrama.rendering.runpod_billing import (
    REQUESTED_BUCKET_SIZE_SECONDS,
    map_billing_history,
)


@dataclass(frozen=True)
class JanitorAction:
    subject: str
    action: str
    outcome: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "subject": self.subject,
            "action": self.action,
            "outcome": self.outcome,
            "detail": self.detail,
        }


@dataclass
class JanitorReport:
    swept_at: datetime
    lease_candidates: int = 0
    stopped_pods: list[str] = field(default_factory=list)
    lease_outcomes: list[JanitorAction] = field(default_factory=list)
    orphan_pods: list[JanitorAction] = field(default_factory=list)
    budget_holds: list[JanitorAction] = field(default_factory=list)
    billing_ingests: list[JanitorAction] = field(default_factory=list)
    failures: list[JanitorAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "swept_at": self.swept_at.isoformat(),
            "lease_candidates": self.lease_candidates,
            "stopped_pods": self.stopped_pods,
            "lease_outcomes": [a.to_dict() for a in self.lease_outcomes],
            "orphan_pods": [a.to_dict() for a in self.orphan_pods],
            "budget_holds": [a.to_dict() for a in self.budget_holds],
            "billing_ingests": [a.to_dict() for a in self.billing_ingests],
            "failures": [a.to_dict() for a in self.failures],
        }


class Janitor:
    """Owns nothing; cleans everything the pod lifecycle may have leaked."""

    def __init__(
        self,
        db: Database,
        budget: BudgetService,
        provider: PodProvider,
        clock: Clock,
        ids: IdGenerator,
        settings: Settings,
        config: PodLeaseConfig,
        finality: LeaseBillingFinality,
    ) -> None:
        check_finality_pairing(finality, provider.provider_id)
        self._finality = finality
        self._db = db
        self._budget = budget
        self._provider = provider
        self._clock = clock
        self._settings = settings
        self._config = config
        self._manager = PodManager(provider, clock, config, stop_attempts=config.stop_attempts)

    # --- evidence ----------------------------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise MicrodramaError("janitor clock must be timezone-aware")
        return now

    def _lease_event(
        self, tx: Tx, lease_id: UUID, event_type: str, payload: dict[str, Any], now: datetime
    ) -> None:
        append_event(
            tx,
            aggregate_type="pod_lease",
            aggregate_id=lease_id,
            event_type=event_type,
            payload=payload,
            correlation_id=lease_id,
            occurred_at=now,
        )

    def _evidence(
        self, subject_key: str, event_type: str, payload: dict[str, Any], now: datetime
    ) -> None:
        aggregate_id = uuid5(RENDERING_NAMESPACE, f"janitor:{subject_key}")
        with self._db.transaction() as tx:
            append_event(
                tx,
                aggregate_type="janitor_action",
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=payload,
                correlation_id=aggregate_id,
                occurred_at=now,
            )

    # --- sweep -------------------------------------------------------------------------

    def sweep(self) -> JanitorReport:
        now = self._now()
        report = JanitorReport(swept_at=now)
        self._sweep_leases(now, report)
        self._sweep_provider_orphans(now, report)
        self._sweep_unbound_holds(now, report)
        self._sweep_billing_ingestion(now, report)
        self._sweep_terminal_leases(now, report)
        return report

    # --- phase 1: live leases whose worker is gone ---------------------------------------

    def _sweep_leases(self, now: datetime, report: JanitorReport) -> None:
        stale_before = now - timedelta(milliseconds=self._config.heartbeat_timeout_ms)
        rows = self._db_query(
            "SELECT l.*, e.state AS episode_state FROM pod_leases l "
            "LEFT JOIN episodes e ON e.id = l.owner_episode_id "
            "WHERE l.lease_state IN ('CLAIMED', 'ACTIVE', 'TRANSFERRING') "
            "AND (l.lease_expires_at <= %s OR COALESCE(l.heartbeat_at, l.created_at) < %s "
            "OR e.state = %s OR l.pod_state = 'RELEASING') ORDER BY l.created_at",
            (now, stale_before, EpisodeState.AWAITING_FINAL_REVIEW.value),
        )
        report.lease_candidates = len(rows)
        for row in rows:
            cause = self._cause(row, now)
            if cause is None:
                continue
            try:
                action = self._clean_lease(row, cause, now)
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"lease:{row['id']}",
                        action=f"clean:{cause}",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                self._evidence(
                    f"lease:{row['id']}",
                    "janitor.action_failed",
                    {"cause": cause, "error": exc.code, "detail": str(exc.message)},
                    now,
                )
                continue
            report.lease_outcomes.append(action)

    def _cause(self, row: dict[str, Any], now: datetime) -> str | None:
        """Why this live lease has no live worker — or None when it is still protected."""
        if row["episode_state"] == EpisodeState.AWAITING_FINAL_REVIEW.value:
            return "human_wait"
        if row["lease_expires_at"] <= now:
            return "lease_expired"
        if row["pod_state"] == PodState.RELEASING.value and self._stop_failed(row["id"]):
            # Durable proof the intended stop already exhausted its retries: the worker's
            # shutdown is dead, so the janitor may take over immediately. A RELEASING
            # lease without the event may still be mid-shutdown in a live worker; a stale
            # heartbeat (below) is that crash signal instead.
            return "stop_failed"
        stale_before = now - timedelta(milliseconds=self._config.heartbeat_timeout_ms)
        last_seen = row["heartbeat_at"] or row["created_at"]
        if last_seen >= stale_before:
            return None
        if row["lease_state"] == "CLAIMED":
            # A claim without a pod may simply be between reserve and create; give it the
            # same grace as an unbound hold before declaring the worker dead.
            grace_before = now - timedelta(milliseconds=self._config.unbound_grace_ms)
            if row["created_at"] >= grace_before:
                return None
        return "heartbeat_expired"

    def _stop_failed(self, lease_id: UUID) -> bool:
        with self._db.transaction(readonly=True) as tx:
            return any(
                event.event_type == "pod_lease.stop_failed" for event in list_events(tx, lease_id)
            )

    def _clean_lease(self, row: dict[str, Any], cause: str, now: datetime) -> JanitorAction:
        lease_id: UUID = row["id"]
        terminal = {
            "heartbeat_expired": LeaseState.ORPHANED.value,
            "stop_failed": LeaseState.ORPHANED.value,
            "lease_expired": LeaseState.EXPIRED.value,
            "human_wait": LeaseState.RELEASED.value,
        }[cause]
        if row["pod_id"] is None:
            stray = self._manager.reconcile_by_token(row["client_token"])
            if stray is None:
                return self._close_without_compute(lease_id, terminal, cause, now)
            self._attach_stray(lease_id, stray, now)
            pod_id = stray.pod_id
        else:
            pod_id = row["pod_id"]
        self._accrue(lease_id, now)
        self._mark_release_started(lease_id, now)
        pod_state = self._manager.stop(pod_id)
        terminate_verified = None
        window_end = now
        if self._manager.is_runpod():
            # T045 R8: the janitor's cleanup of a Runpod chain also terminates, so the
            # volume stops billing and the compute window has a verified end.
            pod_state = self._manager.terminate(pod_id)
            terminate_verified = self._now()
            window_end = terminate_verified
            close_storage_ownership(self._db, "runpod", pod_id, terminate_verified)
        self._accrue(lease_id, now)
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            if current is None:
                raise MicrodramaError("lease vanished during janitor cleanup")
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                current["revision"],
                {
                    "lease_state": terminal,
                    "pod_state": pod_state.value,
                    "stop_verified_at": current["stop_verified_at"] or now,
                    "compute_window_end_at": current["compute_window_end_at"] or window_end,
                    "terminate_verified_at": current["terminate_verified_at"] or terminate_verified,
                },
                now=now,
            )
            self._lease_event(
                tx,
                lease_id,
                f"pod_lease.{terminal.lower()}",
                {"cause": cause, "pod_state": pod_state.value},
                now,
            )
        outcome = self._finality.settle_lease(
            self._db,
            self._budget,
            self._settings,
            lease_id=lease_id,
            context=f"janitor:{cause}",
            now=now,
        )
        return JanitorAction(
            subject=f"lease:{lease_id}",
            action=f"clean:{cause}",
            outcome=terminal,
            detail=(
                f"pod {pod_state.value}, settled {outcome.settled_micro_usd} micro-USD"
                + (", billing pending" if outcome.pending else "")
            ),
        )

    def _close_without_compute(
        self, lease_id: UUID, terminal: str, cause: str, now: datetime
    ) -> JanitorAction:
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert current is not None
            # T045-FIX A-S1: bound a sent-but-podless create's window at the close
            # instant, exactly like LeaseService._close_claim_without_pod.
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                current["revision"],
                {
                    "lease_state": LeaseState.RELEASED.value,
                    "compute_window_end_at": current["compute_window_end_at"]
                    or (now if current["create_requested_at"] is not None else None),
                },
                now=now,
            )
            self._lease_event(
                tx,
                lease_id,
                "pod_lease.released",
                {"cause": cause, "compute": "none"},
                now,
            )
        outcome = self._finality.settle_lease(
            self._db,
            self._budget,
            self._settings,
            lease_id=lease_id,
            context=f"janitor:{cause}",
            now=now,
        )
        return JanitorAction(
            subject=f"lease:{lease_id}",
            action=f"clean:{cause}",
            outcome="RELEASED" if outcome.released else "PENDING",
            detail=(
                "no compute was ever acquired"
                if outcome.released
                else "no compute acquired; billing finality pending"
            ),
        )

    def _attach_stray(self, lease_id: UUID, pod, now: datetime) -> None:
        """Record the pod an ambiguous create left behind so accounting can see it."""
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert current is not None
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                current["revision"],
                {
                    "pod_id": pod.pod_id,
                    "pod_state": PodState.RUNNING.value
                    if pod.state is PodState.RUNNING
                    else PodState.UNKNOWN.value,
                    "lease_state": LeaseState.ACTIVE.value,
                },
                now=now,
            )
            self._lease_event(
                tx,
                lease_id,
                "pod_lease.activated",
                {"pod_id": pod.pod_id, "adopted_by": "janitor"},
                now,
            )
        # An adopted stray pod is storage the pipeline owns from its create request
        # (T045 R3): open (or confirm) its ownership interval for the chain root.
        open_storage_ownership(self._db, lease_id, pod.pod_id)

    def _mark_release_started(self, lease_id: UUID, now: datetime) -> None:
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert row is not None
            events = list_events(tx, lease_id)
            started = any(e.event_type == "pod_lease.release_started" for e in events)
            if not started:
                self._lease_event(
                    tx, lease_id, "pod_lease.release_started", {"reason": "janitor"}, now
                )
            if row["pod_state"] != PodState.RELEASING.value and row["pod_id"] is not None:
                update_with_revision(
                    tx,
                    "pod_leases",
                    lease_id,
                    row["revision"],
                    {"pod_state": PodState.RELEASING.value},
                    now=now,
                )

    def _accrue(self, lease_id: UUID, now: datetime) -> None:
        accrue_lease_usage(self._db, self._budget, self._manager, lease_id=lease_id, until=now)

    # --- phase 2: provider-side orphans ---------------------------------------------------

    def _sweep_provider_orphans(self, now: datetime, report: JanitorReport) -> None:
        try:
            pods = self._manager.find_owned()
        except MicrodramaError as exc:
            report.failures.append(
                JanitorAction(
                    subject="provider:find_owned",
                    action="scan",
                    outcome="failed",
                    detail=f"{exc.code}: {exc.message}",
                )
            )
            return
        for pod in pods:
            if pod.owned_tag != self._config.owned_tag:
                continue  # defence in depth: never touch anything not exactly ours
            live = self._db_query(
                "SELECT 1 AS present FROM pod_leases WHERE provider = %s AND pod_id = %s "
                "AND lease_state IN ('CLAIMED', 'ACTIVE', 'TRANSFERRING')",
                (self._manager.provider_id, pod.pod_id),
            )
            if live:
                continue
            if pod.state is not PodState.RUNNING:
                continue
            try:
                state = self._manager.stop(pod.pod_id)
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod.pod_id}",
                        action="stop_orphan",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                self._evidence(
                    f"pod:{pod.pod_id}",
                    "janitor.action_failed",
                    {"error": exc.code, "detail": str(exc.message)},
                    now,
                )
                continue
            action = JanitorAction(
                subject=f"pod:{pod.pod_id}",
                action="stop_orphan",
                outcome=state.value,
            )
            report.orphan_pods.append(action)
            report.stopped_pods.append(pod.pod_id)
            self._evidence(
                f"pod:{pod.pod_id}",
                "janitor.orphan_pod_stopped",
                {
                    "provider": self._manager.provider_id,
                    "pod_id": pod.pod_id,
                    "owned_tag": pod.owned_tag,
                    "outcome": state.value,
                },
                now,
            )

    # --- phase 3: unbound lifecycle holds ---------------------------------------------------

    def _sweep_unbound_holds(self, now: datetime, report: JanitorReport) -> None:
        grace_before = now - timedelta(milliseconds=self._config.unbound_grace_ms)
        rows = self._db_query(
            "SELECT * FROM reservations WHERE operation_kind IN (%s, %s) AND state = 'ACTIVE' "
            "AND created_at < %s ORDER BY created_at",
            (LEASE_OPERATION_KIND, STOP_OPERATION_KIND, grace_before),
        )
        for row in rows:
            if row["operation_kind"] == LEASE_OPERATION_KIND:
                bound = self._db_query(
                    "SELECT 1 AS present FROM pod_leases WHERE reservation_id = %s",
                    (row["id"],),
                )
                if bound:
                    continue  # its lease owns the settlement (phase 4)
            try:
                self._budget.release(
                    row["id"],
                    reason=f"janitor: unbound {row['operation_kind']} hold "
                    f"(crash between reserve and use)",
                )
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"reservation:{row['id']}",
                        action="release_unbound",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                continue
            action = JanitorAction(
                subject=f"reservation:{row['id']}",
                action="release_unbound",
                outcome="RELEASED",
                detail=row["operation_kind"],
            )
            report.budget_holds.append(action)
            self._evidence(
                f"reservation:{row['id']}",
                "janitor.reservation_released",
                {
                    "operation_kind": row["operation_kind"],
                    "semantic_key": row["semantic_key"],
                    "reserved_micro_usd": row["reserved_micro_usd"],
                },
                now,
            )

    # --- phase 4: provider billing ingestion for unfinal leases (T045 R9) -------------------

    def _sweep_billing_ingestion(self, now: datetime, report: JanitorReport) -> None:
        """Pull provider billing for owned Runpod pods whose leases are not BILLED.

        Effect-gated at the provider (a billing query is a live provider call) and
        paced by the same per-lease finality backoff that paces settlement retries,
        so a pending pod cannot hot-loop the billing endpoint. Only the durable
        repository may receive the mapped buckets; the fake provider path (no
        ``billing_history``) is untouched. Ingest runs before the terminal-lease
        sweep so the same sweep's finality pass sees the fresh buckets.
        """
        billing_history = getattr(self._provider, "billing_history", None)
        if billing_history is None or not isinstance(self._finality, BillingRepository):
            return
        pods = self._db_query(
            "SELECT l.pod_id, MIN(l.provider_account_ref) AS account_ref, "
            "MIN(COALESCE(l.create_requested_at, l.created_at)) AS window_start, "
            "GREATEST(MAX(l.compute_window_end_at), MAX(l.terminate_verified_at)) "
            "AS window_end, MIN(l.next_finality_check_at) AS backoff "
            "FROM pod_leases l JOIN reservations r ON r.id = l.reservation_id "
            "WHERE l.provider = 'runpod' AND l.pod_id IS NOT NULL "
            "AND l.owned_tag = %s AND r.state IN ('ACTIVE', 'EXPIRED') "
            "GROUP BY l.pod_id "
            "HAVING MIN(l.next_finality_check_at) IS NULL "
            "OR MIN(l.next_finality_check_at) <= %s "
            "ORDER BY MIN(l.created_at)",
            (self._config.owned_tag, now),
        )
        for row in pods:
            pod_id = row["pod_id"]
            if not row["account_ref"]:
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="failed",
                        detail="lease has no provider account label; billing cannot be attributed",
                    )
                )
                continue
            since = row["window_start"]
            until = row["window_end"] or now
            if until <= since:
                until = since + timedelta(seconds=1)
            # Round the request up to the end of the final hourly bucket: the
            # provider returns whole buckets, so an invoice period can only sit on
            # bucket boundaries if the durable query window covers the full last
            # bucket of the lease (R5 precondition).
            remainder = until.timestamp() % REQUESTED_BUCKET_SIZE_SECONDS
            until = until + timedelta(
                seconds=REQUESTED_BUCKET_SIZE_SECONDS - remainder if remainder else 0
            )
            try:
                history = billing_history(pod_id, since=since, until=until)
                mapped = map_billing_history(
                    self._db, history, provider_account_ref=row["account_ref"]
                )
                ingested = 0
                if mapped is not None:
                    self._finality.ingest(mapped.query, mapped.buckets)
                    ingested = len(mapped.buckets)
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                continue
            except ValueError as exc:
                # Malformed provider data (contract validators raise plain
                # ValueError) fails this pod's ingest without crashing the sweep.
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="failed",
                        detail=f"PROVIDER_DATA_INVALID: {exc}",
                    )
                )
                continue
            action = JanitorAction(
                subject=f"pod:{pod_id}",
                action="billing_ingest",
                outcome="INGESTED" if ingested else "REPLAY",
                detail=f"{ingested} bucket(s) stored over the lease window",
            )
            report.billing_ingests.append(action)
            self._evidence(
                f"pod:{pod_id}",
                "janitor.billing_ingested",
                {
                    "pod_id": pod_id,
                    "buckets_stored": ingested,
                    "window_start": since.isoformat(),
                    "window_end": until.isoformat(),
                },
                now,
            )

    # --- phase 5: terminal leases with unsettled holds --------------------------------------

    def _sweep_terminal_leases(self, now: datetime, report: JanitorReport) -> None:
        # T045 R8/G15: a hold that EXPIRED while it waited for an invoice is revisited
        # here too, and the backoff column keeps pending retries from hot-looping.
        rows = self._db_query(
            "SELECT l.id AS lease_id, l.reservation_id, l.lease_state FROM pod_leases l "
            "JOIN reservations r ON r.id = l.reservation_id "
            "WHERE l.lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') "
            "AND r.state IN ('ACTIVE', 'EXPIRED') "
            "AND (l.next_finality_check_at IS NULL OR l.next_finality_check_at <= %s) "
            "ORDER BY l.created_at",
            (now,),
        )
        for row in rows:
            try:
                outcome = self._finality.settle_lease(
                    self._db,
                    self._budget,
                    self._settings,
                    lease_id=row["lease_id"],
                    context="janitor:terminal-lease",
                    now=now,
                )
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"lease:{row['lease_id']}",
                        action="settle_terminal",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                continue
            if outcome.pending:
                outcome_label, detail = "PENDING", "billing finality not reached"
            elif outcome.released:
                outcome_label, detail = "RELEASED", "no usage, released"
            else:
                outcome_label, detail = (
                    "SETTLED",
                    f"{outcome.settled_micro_usd} micro-USD",
                )
            action = JanitorAction(
                subject=f"lease:{row['lease_id']}",
                action="settle_terminal",
                outcome=outcome_label,
                detail=detail,
            )
            report.budget_holds.append(action)

    # --- plumbing ------------------------------------------------------------------------------

    def _db_query(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._db.transaction(readonly=True) as tx:
            return tx.fetchall(sql, params)


def build_janitor(
    db: Database,
    budget: BudgetService,
    provider: PodProvider,
    clock: Clock,
    ids: IdGenerator,
    settings: Settings,
    config: PodLeaseConfig,
    finality: LeaseBillingFinality,
) -> Janitor:
    """Composition factory for the integrator / scheduler registration."""
    return Janitor(db, budget, provider, clock, ids, settings, config, finality)


def main(argv: list[str] | None = None) -> int:
    """``python -m microdrama.rendering.janitor --dsn ... --owned-tag ...`` (one sweep).

    Uses the runtime settings and the (structurally disabled until T031) live adapter, so
    an offline run performs the accounting-only cleanup and honestly reports every stop it
    could not perform. Exits 0 when the sweep had no failures, 1 when some action failed,
    2 on a configuration error.
    """
    parser = argparse.ArgumentParser(
        prog="microdrama-rendering-janitor",
        description="Independent GPU leak cleanup: expired leases, dead workers, orphans.",
    )
    parser.add_argument(
        "--dsn", default=os.environ.get("MICRODRAMA_DATABASE_URL"), help="PostgreSQL DSN"
    )
    parser.add_argument(
        "--owned-tag",
        required=True,
        help="The pipeline ownership tag; only pods carrying it are ever touched",
    )
    parser.add_argument("--grace-ms", type=int, default=60_000)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=300_000)
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn or MICRODRAMA_DATABASE_URL is required")
    try:
        settings = Settings.from_env()
        config = PodLeaseConfig(
            owned_tag=args.owned_tag,
            allowed_gpu_types=frozenset(),
            min_host_ram_gb=1,
            container_image="unconfigured:image",
            max_hourly_price_micro_usd=1,
            price=None,
            unbound_grace_ms=args.grace_ms,
            heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        )
        provider = resolve_pod_provider(settings)
        db = Database(args.dsn).open()
        try:
            budget = BudgetService(db, SystemClock(), UuidIds(), settings)
            janitor = build_janitor(
                db, budget, provider, SystemClock(), UuidIds(), settings, config
            )
            report = janitor.sweep()
        finally:
            db.close()
    except MicrodramaError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc.message)}), file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if report.failures else 0


__all__ = ["Janitor", "JanitorAction", "JanitorReport", "build_janitor", "main"]

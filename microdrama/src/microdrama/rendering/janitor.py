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
    record_terminate_verified,
)
from microdrama.rendering.pods import (
    LEASE_OPERATION_KIND,
    STOP_OPERATION_KIND,
    PodManager,
    resolve_pod_provider,
)
from microdrama.rendering.runpod_billing import (
    map_billing_history,
    round_up_to_bucket_end,
)
from microdrama.rendering.runpod_transport import pod_name

#: T045-FIX B-S4: the per-Pod billing-ingest backoff doubles from 5 minutes to 1 hour.
INGEST_BACKOFF_BASE = timedelta(minutes=5)
INGEST_BACKOFF_CAP = timedelta(hours=1)
DEFAULT_SETTLE_LAG = timedelta(minutes=15)


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
        # T045-FIX F-1: owned Pod ids the current sweep's orphan scan still sees
        # (None until a scan runs or when the scan failed - never an empty set,
        # which would claim the provider listed nothing).
        self._present_owned_pod_ids: frozenset[str] | None = None

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
        self._complete_absent_terminal_terminates(now, report)
        self._sweep_unbound_holds(now, report)
        self._sweep_billing_ingestion(now, report)
        self._sweep_open_ownership(now, report)
        self._sweep_terminal_leases(now, report)
        return report

    def _sweep_open_ownership(self, now: datetime, report: JanitorReport) -> None:
        """T045-FIX A-S6: finish an ownership close a crash left behind.

        A shutdown or janitor clean that died between the terminate write and the
        ownership close leaves the pod's storage interval open with a durable
        ``terminate_verified_at``. Close it at exactly that stored instant — never a
        fresh clock read. Idempotent: rows whose interval is already closed are not
        selected.
        """
        rows = self._db_query(
            "SELECT DISTINCT ON (l.pod_id) l.pod_id, l.terminate_verified_at "
            "FROM pod_leases l JOIN pod_storage_ownership o "
            "ON o.provider = l.provider AND o.pod_id = l.pod_id AND o.valid_until IS NULL "
            "WHERE l.provider = 'runpod' AND l.pod_id IS NOT NULL "
            "AND l.terminate_verified_at IS NOT NULL "
            "ORDER BY l.pod_id, l.terminate_verified_at",
            (),
        )
        for row in rows:
            close_storage_ownership(self._db, "runpod", row["pod_id"], row["terminate_verified_at"])
            self._evidence(
                f"pod:{row['pod_id']}",
                "janitor.ownership_closed",
                {
                    "pod_id": row["pod_id"],
                    "closed_at": row["terminate_verified_at"].isoformat(),
                    "cause": "crash-between-terminate-and-close",
                },
                now,
            )
            report.stopped_pods.append(
                JanitorAction(
                    subject=f"pod:{row['pod_id']}",
                    action="close_storage_ownership",
                    outcome="closed",
                    detail=f"ownership closed at the persisted terminate "
                    f"{row['terminate_verified_at'].isoformat()}",
                )
            )

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
            # T045-FIX A-S6: the verified terminate is durable BEFORE the ownership
            # close, and the close reads the stored value back — never a fresh clock.
            terminate_verified = record_terminate_verified(self._db, lease_id, self._now())
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

    def _terminal_podless_lease(self, pod) -> dict[str, Any] | None:
        """T045-FIX RR-S4: the terminal lease a late owned Pod belongs to.

        Every owned Pod has a lease row and a client token from before its create was
        sent. A Pod no live lease holds, whose create token names a terminal lease with
        no Pod attached, is that lease's late Pod - not a foreign orphan.
        """
        rows = self._db_query(
            "SELECT id, client_token FROM pod_leases WHERE provider = %s AND owned_tag = %s "
            "AND pod_id IS NULL AND create_requested_at IS NOT NULL "
            "AND lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') "
            "ORDER BY created_at DESC",
            (self._manager.provider_id, self._config.owned_tag),
        )
        namespace = self._config.owned_tag.removeprefix("microdrama-owned:")
        for row in rows:
            if pod.client_token is not None and pod.client_token == row["client_token"]:
                return row
            if pod.name == pod_name(namespace, row["client_token"]):
                return row
        return None

    def _adopt_late_pod(self, pod, lease_id: UUID, now: datetime, report: JanitorReport) -> None:
        """Attach a late Pod to its terminal lease, then stop/terminate/verify it.

        The lease stays terminal (its hold may already be SETTLED at 0 by a podless
        resolution); the accounting continues through the Pod's own billing: the
        resolution is marked contradicted, the cost is ingested as an ADJUSTMENT on
        the settled reservation (the ledger allows it), and readiness is computed from
        the Pod's billing - never BILLED 0 from the contradicted resolution.
        """
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            if current is None or current["pod_id"] is not None:
                return  # raced: attached (or gone) while we looked it up
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
                },
                now=now,
            )
            self._lease_event(
                tx,
                lease_id,
                "pod_lease.activated",
                {"pod_id": pod.pod_id, "adopted_by": "janitor:late-pod"},
                now,
            )
            contradicted = tx.execute(
                "UPDATE runpod_podless_create_resolutions SET contradicted_at=%s, "
                "contradicted_pod_id=%s WHERE lease_id=%s AND contradicted_at IS NULL",
                (now, pod.pod_id, lease_id),
            )
            if contradicted:
                self._lease_event(
                    tx,
                    lease_id,
                    "billing.podless_resolution_contradicted",
                    {"pod_id": pod.pod_id, "contradicted_at": now.isoformat()},
                    now,
                )
        # An owned Pod is storage the pipeline owns from its create request (T045 R3).
        open_storage_ownership(self._db, lease_id, pod.pod_id)
        state = self._stop_terminate_and_verify(pod, lease_id, now, report, action="adopt_late_pod")
        if state is None:
            return
        report.orphan_pods.append(
            JanitorAction(
                subject=f"pod:{pod.pod_id}",
                action="adopt_late_pod",
                outcome=state.value,
                detail=f"late Pod adopted onto terminal lease {lease_id}",
            )
        )
        report.stopped_pods.append(pod.pod_id)
        self._evidence(
            f"pod:{pod.pod_id}",
            "janitor.late_pod_adopted",
            {
                "provider": self._manager.provider_id,
                "pod_id": pod.pod_id,
                "lease_id": str(lease_id),
                "pod_state": state.value,
            },
            now,
        )

    def _stop_terminate_and_verify(
        self,
        pod,
        lease_id: UUID,
        now: datetime,
        report: JanitorReport,
        *,
        action: str,
    ) -> PodState | None:
        """T045 R8 + RR-S4 + F-1: the shared stop -> terminate -> verify -> close tail.

        Writes the durable terminate the billing window and the ownership close read
        back. Returns the verified terminal state, or ``None`` when the tail failed:
        the failure is recorded (per-Pod, like every stop/terminate failure) and the
        next sweep retries - ``terminate_verified_at`` stays NULL and storage
        ownership stays open until the tail completes.
        """
        try:
            state = self._manager.stop(pod.pod_id)
            if self._manager.is_runpod():
                # T045 R8 + RR-S4: stop, terminate and verify, writing the durable
                # terminate the billing window and the ownership close read back.
                state = self._manager.terminate(pod.pod_id)
                terminate_verified = record_terminate_verified(self._db, lease_id, now)
                close_storage_ownership(self._db, "runpod", pod.pod_id, terminate_verified)
        except MicrodramaError as exc:
            report.failures.append(
                JanitorAction(
                    subject=f"pod:{pod.pod_id}",
                    action=action,
                    outcome="failed",
                    detail=f"{exc.code}: {exc.message}",
                )
            )
            self._evidence(
                f"pod:{pod.pod_id}",
                "janitor.action_failed",
                {"error": exc.code, "detail": str(exc.message), "lease_id": str(lease_id)},
                now,
            )
            return None
        return state

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
            # The scan's view of which owned Pods still exist is unknown; the
            # billing phase must not defer on it (None, not an empty set).
            self._present_owned_pod_ids = None
            return
        # T045-FIX F-1: the pods this sweep's scan can still see - only these can
        # re-run the stop -> terminate -> verify tail, so only these may defer
        # their billing ingest on an unverified terminal terminate (below).
        self._present_owned_pod_ids = frozenset(pod.pod_id for pod in pods)
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
            unverified = (
                self._db_query(
                    "SELECT id FROM pod_leases cur WHERE cur.provider = %s AND cur.pod_id = %s "
                    "AND cur.lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') "
                    "AND cur.terminate_verified_at IS NULL "
                    # T045-FIX CR-3: a lease superseded by a later lease on the same
                    # Pod (a warm transfer, a reclaim) is history - the FINAL holder
                    # owns the terminate. A transferred-away lease's NULL terminate
                    # is by design (leases.py: it has no verified stop of its own);
                    # re-terminating on its behalf can block ingest and invoice
                    # finality with an unnecessary DELETE.
                    "AND NOT EXISTS (SELECT 1 FROM pod_leases sup WHERE "
                    "sup.provider = cur.provider AND sup.pod_id = cur.pod_id "
                    "AND sup.id <> cur.id AND sup.created_at > cur.created_at)",
                    (self._manager.provider_id, pod.pod_id),
                )
                if self._manager.is_runpod()
                else []
            )
            if unverified:
                # T045-FIX F-1: an owned Pod held by a terminal lease whose terminate
                # never verified (the adoption or the shutdown died mid-tail) gets the
                # same stop -> terminate -> verify -> close tail - never the plain
                # orphan stop, which would leave terminate_verified_at NULL, storage
                # ownership open and the volume cost accruing forever. This covers
                # every terminal lease, not only adopted ones; a failure is recorded
                # per Pod and the next sweep retries the tail. Runpod only: the tail
                # writes terminate_verified_at just there, so on any other provider
                # the retry could never complete and would re-stop every sweep (the
                # plain orphan path - stop RUNNING pods only - keeps idempotency).
                lease_id = unverified[0]["id"]
                state = self._stop_terminate_and_verify(
                    pod, lease_id, now, report, action="terminate_terminal_pod"
                )
                if state is not None:
                    report.orphan_pods.append(
                        JanitorAction(
                            subject=f"pod:{pod.pod_id}",
                            action="terminate_terminal_pod",
                            outcome=state.value,
                            detail=f"terminal lease {lease_id} terminate verified, "
                            "storage ownership closed",
                        )
                    )
                    report.stopped_pods.append(pod.pod_id)
                    self._evidence(
                        f"pod:{pod.pod_id}",
                        "janitor.terminal_pod_terminate_verified",
                        {
                            "provider": self._manager.provider_id,
                            "pod_id": pod.pod_id,
                            "lease_id": str(lease_id),
                            "pod_state": state.value,
                        },
                        now,
                    )
                continue
            if pod.state is not PodState.RUNNING:
                continue
            terminal = self._terminal_podless_lease(pod)
            if terminal is not None:
                # T045-FIX RR-S4: this Pod belongs to a sent create whose lease closed
                # podless - adopt it so its cost is ingested, never stopped as a
                # nameless orphan whose charge is lost.
                self._adopt_late_pod(pod, terminal["id"], now, report)
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

    def _complete_absent_terminal_terminates(self, now: datetime, report: JanitorReport) -> None:
        """T045-FIX CR-2: finish a terminal lease whose Pod the scan no longer sees.

        An ambiguous terminate (the DELETE took effect at Runpod, the answer was a
        503) leaves the lease terminal with ``terminate_verified_at`` NULL and
        storage ownership open - and the Pod absent from ``find_owned()``, so the
        F-1 retry tail can never run over it again. The sweep completes that tail
        BY ABSENCE: the durable lease row plus this sweep's successful scan is the
        evidence the Pod is gone, so the verified terminate is written and storage
        ownership closed WITHOUT a provider DELETE that could double-bill.

        Runpod-scoped like the rest of the tail. Superseded (transferred-away)
        leases are excluded exactly as in the F-1 selection (CR-3): the final
        holder owns the terminate.
        """
        if not self._manager.is_runpod():
            return
        if self._present_owned_pod_ids is None:
            # The scan failed or never ran: absence is not knowable this sweep.
            return
        rows = self._db_query(
            "SELECT cur.id, cur.pod_id FROM pod_leases cur "
            "WHERE cur.provider = %s AND cur.owned_tag = %s AND cur.pod_id IS NOT NULL "
            "AND cur.lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') "
            "AND cur.terminate_verified_at IS NULL "
            # T045-FIX CR-3: the same superseded-lease exclusion as the F-1 tail.
            "AND NOT EXISTS (SELECT 1 FROM pod_leases sup WHERE "
            "sup.provider = cur.provider AND sup.pod_id = cur.pod_id "
            "AND sup.id <> cur.id AND sup.created_at > cur.created_at) "
            "ORDER BY cur.created_at",
            (self._manager.provider_id, self._config.owned_tag),
        )
        for row in rows:
            pod_id = row["pod_id"]
            if pod_id in self._present_owned_pod_ids:
                # The scan still sees this Pod: the F-1 tail in the orphan sweep
                # owns it (stop -> terminate -> verify), never this pass.
                continue
            lease_id = row["id"]
            try:
                verified = record_terminate_verified(self._db, lease_id, now)
                close_storage_ownership(self._db, "runpod", pod_id, verified)
            except MicrodramaError as exc:
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="terminate_verified_by_absence",
                        outcome="failed",
                        detail=f"{exc.code}: {exc.message}",
                    )
                )
                self._evidence(
                    f"pod:{pod_id}",
                    "janitor.action_failed",
                    {"error": exc.code, "detail": str(exc.message), "lease_id": str(lease_id)},
                    now,
                )
                continue
            report.orphan_pods.append(
                JanitorAction(
                    subject=f"pod:{pod_id}",
                    action="terminate_verified_by_absence",
                    outcome="TERMINATED",
                    detail=f"terminal lease {lease_id} completed by absence (the scan no "
                    "longer sees the Pod); storage ownership closed",
                )
            )
            report.stopped_pods.append(pod_id)
            self._evidence(
                f"pod:{pod_id}",
                "janitor.terminal_pod_terminate_verified_by_absence",
                {
                    "provider": self._manager.provider_id,
                    "pod_id": pod_id,
                    "lease_id": str(lease_id),
                    "terminate_verified_at": verified.isoformat(),
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
            "AS window_end, MIN(l.next_finality_check_at) AS backoff, "
            "MAX(l.terminate_verified_at) AS terminated_at, "
            "BOOL_OR(l.lease_state IN ('CLAIMED', 'ACTIVE', 'TRANSFERRING')) "
            "AS has_live_lease, "
            "BOOL_OR(l.lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') "
            "AND l.terminate_verified_at IS NULL) AS has_unverified_terminal_lease, "
            "b.next_ingest_at, b.attempts AS ingest_attempts, "
            "b.post_terminate_ingest_done "
            "FROM pod_leases l JOIN reservations r ON r.id = l.reservation_id "
            "LEFT JOIN runpod_billing_ingest_backoff b ON b.pod_id = l.pod_id "
            "WHERE l.provider = 'runpod' AND l.pod_id IS NOT NULL "
            "AND l.owned_tag = %s AND (r.state IN ('ACTIVE', 'EXPIRED') "
            # T045-FIX RR-S4: a Pod adopted after a podless resolution is ingested
            # although its hold is SETTLED - its cost posts as an ADJUSTMENT on the
            # settled reservation, which the ledger allows.
            "OR (r.state = 'SETTLED' AND EXISTS (SELECT 1 FROM "
            "runpod_podless_create_resolutions p WHERE p.lease_id = l.id "
            "AND p.contradicted_at IS NOT NULL))) "
            "GROUP BY l.pod_id, b.next_ingest_at, b.attempts, b.post_terminate_ingest_done "
            "HAVING MIN(l.next_finality_check_at) IS NULL "
            "OR MIN(l.next_finality_check_at) <= %s "
            "ORDER BY MIN(l.created_at)",
            (self._config.owned_tag, now),
        )
        settle_lag = getattr(self._finality, "settle_lag", DEFAULT_SETTLE_LAG)
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
            if (
                row["has_unverified_terminal_lease"]
                and not row["has_live_lease"]
                and self._present_owned_pod_ids is not None
                and pod_id in self._present_owned_pod_ids
            ):
                # T045-FIX F-1: a terminal lease's billing window is final only at
                # its verified terminate. A Pod the scan still sees, held by a
                # terminal lease whose terminate never verified (the adoption or
                # the shutdown died mid-tail), is re-run by the orphan sweep's
                # stop -> terminate -> verify tail, which runs before this phase;
                # ingesting now would stamp this Pod's buckets with the narrower
                # pre-terminate window, which a later covering query cannot
                # re-stamp (the repository replays an already-stored bucket by
                # raw-response hash). The ingest defers to the tail - no provider
                # call, no backoff row; the next sweep re-evaluates for free. A
                # Pod the scan no longer sees was completed by absence (CR-2)
                # before this phase, so its window is final here.
                report.billing_ingests.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="DEFERRED",
                        detail="terminal lease terminate not verified yet; "
                        "waiting for the stop/terminate/verify tail",
                    )
                )
                continue
            # T045-FIX B-S4: the persisted per-Pod ingest backoff paces the provider
            # billing endpoint across sweeps (and across janitor restarts) - on
            # success, replay and failure alike.
            if row["next_ingest_at"] is not None and row["next_ingest_at"] > now:
                continue
            attempts = int(row["ingest_attempts"] or 0)
            terminated = row["terminated_at"] is not None
            window_end = row["window_end"]
            if (
                window_end is not None
                and (now - window_end) < settle_lag
                and not (terminated and not row["post_terminate_ingest_done"])
            ):
                # The window's last bucket cannot have settled yet; retry when it
                # can. A terminated Pod gets exactly one ingest inside the lag
                # (its terminal read), then waits like everything else.
                self._record_ingest_backoff(
                    pod_id,
                    row["account_ref"],
                    now=now,
                    attempts=attempts,
                    outcome="SKIPPED_OPEN",
                    detail="window end is within the settle lag",
                    next_ingest_at=window_end + settle_lag,
                    post_terminate_ingest_done=bool(row["post_terminate_ingest_done"]),
                )
                report.billing_ingests.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="SKIPPED_OPEN",
                        detail="window end is within the settle lag; no provider call",
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
            # bucket of the lease (R5 precondition). T045-FIX B-N1: integer
            # microseconds - never a float epoch second.
            until = round_up_to_bucket_end(until)
            try:
                history = billing_history(pod_id, since=since, until=until)
                mapped = map_billing_history(
                    self._db, history, provider_account_ref=row["account_ref"]
                )
                ingested = 0
                skipped_open = 0
                if mapped is not None:
                    self._finality.ingest(mapped.query, mapped.buckets)
                    # T045-FIX B-S4: count what actually settled - the repository
                    # stores only buckets past the settle lag and skips open ones.
                    closed = [
                        bucket
                        for bucket in mapped.buckets
                        if bucket.bucket_end <= mapped.query.observed_at - settle_lag
                    ]
                    ingested = len(closed)
                    skipped_open = len(mapped.buckets) - ingested
            except MicrodramaError as exc:
                # T045-FIX B-S4: the failure is durable (hold-keeping evidence) and
                # backed off; the hold stays.
                self._record_ingest_backoff(
                    pod_id,
                    row["account_ref"],
                    now=now,
                    attempts=attempts,
                    outcome="FAILED",
                    detail=f"{exc.code}: {exc.message}",
                    next_ingest_at=None,
                    post_terminate_ingest_done=bool(
                        row["post_terminate_ingest_done"] or terminated
                    ),
                )
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
                self._record_ingest_backoff(
                    pod_id,
                    row["account_ref"],
                    now=now,
                    attempts=attempts,
                    outcome="FAILED",
                    detail=f"PROVIDER_DATA_INVALID: {exc}",
                    next_ingest_at=None,
                    post_terminate_ingest_done=bool(
                        row["post_terminate_ingest_done"] or terminated
                    ),
                )
                report.failures.append(
                    JanitorAction(
                        subject=f"pod:{pod_id}",
                        action="billing_ingest",
                        outcome="failed",
                        detail=f"PROVIDER_DATA_INVALID: {exc}",
                    )
                )
                continue
            # T045-FIX B-S4: stored, skipped-open and replayed are reported
            # separately - an all-open response is never "INGESTED".
            if ingested:
                outcome, detail = "INGESTED", f"{ingested} bucket(s) stored"
            elif skipped_open:
                outcome, detail = "SKIPPED_OPEN", f"{skipped_open} open bucket(s) skipped"
            else:
                outcome, detail = "REPLAYED", "nothing new over the lease window"
            if skipped_open and ingested:
                detail += f", {skipped_open} open bucket(s) skipped"
            self._record_ingest_backoff(
                pod_id,
                row["account_ref"],
                now=now,
                attempts=attempts,
                outcome=(
                    "STORED" if ingested else "REPLAYED" if not skipped_open else "SKIPPED_OPEN"
                ),
                detail=detail,
                next_ingest_at=None,
                post_terminate_ingest_done=bool(row["post_terminate_ingest_done"] or terminated),
            )
            action = JanitorAction(
                subject=f"pod:{pod_id}",
                action="billing_ingest",
                outcome=outcome,
                detail=detail,
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

    def _record_ingest_backoff(
        self,
        pod_id: str,
        account_ref: str,
        *,
        now: datetime,
        attempts: int,
        outcome: str,
        detail: str,
        next_ingest_at: datetime | None,
        post_terminate_ingest_done: bool,
    ) -> None:
        """T045-FIX B-S4: persist the per-Pod ingest attempt and its backoff.

        The delay doubles from a 5-minute base to a one-hour cap; ``next_ingest_at``
        overrides the doubling when the caller knows the earliest useful retry (a
        window that must first pass the settle lag).
        """
        delay = min(INGEST_BACKOFF_BASE * (2 ** min(attempts, 12)), INGEST_BACKOFF_CAP)
        when = next_ingest_at or (now + delay)
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO runpod_billing_ingest_backoff "
                "(pod_id, provider_account_ref, next_ingest_at, attempts, "
                "post_terminate_ingest_done, last_outcome, last_detail, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pod_id) DO UPDATE SET next_ingest_at = EXCLUDED.next_ingest_at, "
                "attempts = EXCLUDED.attempts, post_terminate_ingest_done = "
                "EXCLUDED.post_terminate_ingest_done, last_outcome = EXCLUDED.last_outcome, "
                "last_detail = EXCLUDED.last_detail, updated_at = EXCLUDED.updated_at",
                (
                    pod_id,
                    account_ref,
                    when,
                    attempts + 1,
                    post_terminate_ingest_done,
                    outcome,
                    detail[:500],
                    now,
                ),
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

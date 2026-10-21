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
4. settles holds of already-terminal leases a crash left unsettled.

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
from microdrama.config import Settings
from microdrama.contracts.enums import EpisodeState, LeaseState, PodState
from microdrama.contracts.errors import MicrodramaError
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.providers import PodProvider
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.events import append_event, list_events
from microdrama.persistence.db import Database, Tx, update_with_revision
from microdrama.rendering.leases import (
    RENDERING_NAMESPACE,
    PodLeaseConfig,
    accrue_lease_usage,
    settle_reservation_for_lease,
)
from microdrama.rendering.pods import (
    LEASE_OPERATION_KIND,
    STOP_OPERATION_KIND,
    PodManager,
    resolve_pod_provider,
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
    failures: list[JanitorAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "swept_at": self.swept_at.isoformat(),
            "lease_candidates": self.lease_candidates,
            "stopped_pods": self.stopped_pods,
            "lease_outcomes": [a.to_dict() for a in self.lease_outcomes],
            "orphan_pods": [a.to_dict() for a in self.orphan_pods],
            "budget_holds": [a.to_dict() for a in self.budget_holds],
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
    ) -> None:
        self._db = db
        self._budget = budget
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
        settled = settle_reservation_for_lease(
            self._db,
            self._budget,
            self._settings,
            lease_id=lease_id,
            context=f"janitor:{cause}",
        )
        return JanitorAction(
            subject=f"lease:{lease_id}",
            action=f"clean:{cause}",
            outcome=terminal,
            detail=f"pod {pod_state.value}, settled {settled} micro-USD",
        )

    def _close_without_compute(
        self, lease_id: UUID, terminal: str, cause: str, now: datetime
    ) -> JanitorAction:
        with self._db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM pod_leases WHERE id = %s FOR UPDATE", (lease_id,))
            assert current is not None
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                current["revision"],
                {"lease_state": LeaseState.RELEASED.value},
                now=now,
            )
            self._lease_event(
                tx,
                lease_id,
                "pod_lease.released",
                {"cause": cause, "compute": "none"},
                now,
            )
        settle_reservation_for_lease(
            self._db, self._budget, self._settings, lease_id=lease_id, context=f"janitor:{cause}"
        )
        return JanitorAction(
            subject=f"lease:{lease_id}",
            action=f"clean:{cause}",
            outcome="RELEASED",
            detail="no compute was ever acquired",
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

    # --- phase 4: terminal leases with unsettled holds --------------------------------------

    def _sweep_terminal_leases(self, now: datetime, report: JanitorReport) -> None:
        rows = self._db_query(
            "SELECT l.id AS lease_id, l.reservation_id, l.lease_state FROM pod_leases l "
            "JOIN reservations r ON r.id = l.reservation_id "
            "WHERE l.lease_state IN ('RELEASED', 'EXPIRED', 'ORPHANED') AND r.state = 'ACTIVE' "
            "ORDER BY l.created_at",
            (),
        )
        for row in rows:
            try:
                settled = settle_reservation_for_lease(
                    self._db,
                    self._budget,
                    self._settings,
                    lease_id=row["lease_id"],
                    context="janitor:terminal-lease",
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
            action = JanitorAction(
                subject=f"lease:{row['lease_id']}",
                action="settle_terminal",
                outcome="SETTLED" if settled else "RELEASED",
                detail=f"{settled} micro-USD",
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
) -> Janitor:
    """Composition factory for the integrator / scheduler registration."""
    return Janitor(db, budget, provider, clock, ids, settings, config)


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

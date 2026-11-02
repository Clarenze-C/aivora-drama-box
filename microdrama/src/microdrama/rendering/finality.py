"""T045 R8: the structural settlement gate between lease lifecycle and billing.

A required ``LeaseBillingFinality`` port decides how a lease's budget hold closes.
There is no boolean and no default: the lease service, the janitor and
``settle_reservation_for_lease`` all receive one, and their constructors check the
provider pairing so a direct construction cannot bypass the gate.

- ``SyntheticUsageFinality`` keeps the offline behaviour exactly (settle to recorded
  usage, release an unused hold) and refuses construction outside OFFLINE_MOCK.
- ``RunpodInvoiceFinality`` keeps the hold until R7 readiness is BILLED (Runpod
  ``usage()`` returns ``[]``: an unknown is never zero), releases only on durable
  no-create proof, and settles BILLED leases with the deterministic BILLED receipt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from microdrama.budget.billing import (
    DEFAULT_SETTLE_LAG,
    BillingRepository,
    lease_billing_readiness,
    settle_billed_lease,
)
from microdrama.budget.service import BudgetService
from microdrama.config import Settings
from microdrama.contracts.errors import Conflict, NotFound
from microdrama.persistence.db import Database, update_with_revision

# Backoff for "finality not reached yet" retries: doubles from five minutes up to an
# hour. Pending is not an error; the sweep must not hot-loop on it.
FINALITY_BACKOFF_BASE = timedelta(minutes=5)
FINALITY_BACKOFF_CAP = timedelta(hours=1)


@dataclass(frozen=True)
class LeaseSettlement:
    """Outcome of closing one lease's hold through the finality port."""

    settled_micro_usd: int = 0
    released: bool = False
    pending: bool = False


class LeaseBillingFinality(ABC):
    """How a lease's budget hold closes (T045 R8). No default, no flag."""

    provider_id: str

    @abstractmethod
    def settle_lease(
        self,
        db: Database,
        budget: BudgetService,
        settings: Settings,
        *,
        lease_id: UUID,
        context: str,
        now: datetime | None = None,
    ) -> LeaseSettlement:
        """Close the lease's hold; deterministic and replay-safe.

        ``now`` carries the caller's injected clock (the janitor and the lease service
        have one); wall time is only a fallback for direct callers.
        """


def _reservation_totals(db: Database, reservation_id: UUID) -> tuple[int, int]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT COALESCE(SUM(amount_micro_usd), 0)::bigint AS amount, "
            "COALESCE(SUM(units), 0)::bigint AS units FROM charges "
            "WHERE reservation_id = %s AND kind IN ('ACCRUAL', 'ADJUSTMENT')",
            (reservation_id,),
        )
    assert row is not None
    return int(row["amount"]), int(row["units"])


class SyntheticUsageFinality(LeaseBillingFinality):
    """The offline mock's settlement: recorded usage settles, an unused hold releases."""

    def __init__(self, settings: Settings, *, provider_id: str) -> None:
        if not settings.is_offline_mock:
            raise Conflict(
                "SyntheticUsageFinality is the OFFLINE_MOCK settlement; a live provider "
                "must close holds through its invoice finality",
                provider_id=provider_id,
            )
        self.provider_id = provider_id

    def settle_lease(
        self,
        db: Database,
        budget: BudgetService,
        settings: Settings,
        *,
        lease_id: UUID,
        context: str,
        now: datetime | None = None,
    ) -> LeaseSettlement:
        from microdrama.rendering.leases import settle_from_recorded_usage

        return settle_from_recorded_usage(db, budget, settings, lease_id=lease_id, context=context)


class RunpodInvoiceFinality(BillingRepository, LeaseBillingFinality):
    """Runpod's settlement gate: hold everything until R7 says BILLED (G7)."""

    provider_id = "runpod"

    def __init__(
        self,
        db: Database,
        budget_service: Any | None = None,
        *,
        settle_lag: timedelta | None = None,
    ) -> None:
        super().__init__(db, budget_service, settle_lag=settle_lag or DEFAULT_SETTLE_LAG)

    def settle_lease(
        self,
        db: Database,
        budget: BudgetService,
        settings: Settings,
        *,
        lease_id: UUID,
        context: str,
        now: datetime | None = None,
    ) -> LeaseSettlement:
        with db.transaction(readonly=True) as tx:
            lease = tx.fetchone(
                "SELECT reservation_id, create_requested_at, pod_id FROM pod_leases WHERE id = %s",
                (lease_id,),
            )
            if lease is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
        if lease["create_requested_at"] is None and lease["pod_id"] is None:
            # Durable proof nothing was ever sent: the guard in BudgetService.release
            # accepts exactly this, and a list miss is never consulted.
            try:
                budget.release(
                    lease["reservation_id"],
                    reason=f"pod lease {lease_id} closed without any create ({context})",
                )
            except Conflict:
                pass  # already closed by an earlier attempt (replay)
            return LeaseSettlement(settled_micro_usd=0, released=True)
        readiness = lease_billing_readiness(self.db, lease_id)
        if readiness.state != "BILLED":
            self._schedule_retry(db, lease_id, now or datetime.now(UTC))
            return LeaseSettlement(settled_micro_usd=0, pending=True)
        settled = settle_billed_lease(self.db, budget, lease_id=lease_id, context=context)
        return LeaseSettlement(settled_micro_usd=settled)

    def _schedule_retry(self, db: Database, lease_id: UUID, now: datetime) -> None:
        """Grow the retry backoff on the lease row; pending is never an error."""
        with db.transaction() as tx:
            row = tx.fetchone(
                "SELECT revision, next_finality_check_at FROM pod_leases WHERE id = %s FOR UPDATE",
                (lease_id,),
            )
            if row is None:
                return
            current = row["next_finality_check_at"]
            if current is None or current <= now:
                delay = FINALITY_BACKOFF_BASE
            else:
                delay = min(current - now, FINALITY_BACKOFF_CAP) * 2
            update_with_revision(
                tx,
                "pod_leases",
                lease_id,
                row["revision"],
                {"next_finality_check_at": now + min(delay, FINALITY_BACKOFF_CAP)},
                now=now,
            )


def check_finality_pairing(finality: LeaseBillingFinality, provider_id: str) -> None:
    """Constructor-side pairing check (S6): direct construction cannot bypass the gate."""
    if finality.provider_id != provider_id:
        raise Conflict(
            "billing finality provider does not match the pod manager",
            finality_provider=finality.provider_id,
            manager_provider=provider_id,
        )

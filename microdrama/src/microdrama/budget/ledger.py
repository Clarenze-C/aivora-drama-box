"""Locked ledger rows and in-transaction accounting for the budget service (T005).

Every money movement runs inside a transaction that already holds the ``budget_accounts`` row
lock, so the counters read under that lock are the committed truth. ``Ledger`` mutates the
in-memory rows and writes them back with a revision guard. Amounts are ``int`` micro-USD only.

Counter meaning (kept per account and per category):
- ``reserved``: worst-case exposure still open on ACTIVE reservations (not yet used);
- ``accrued``: usage counted against ACTIVE/EXPIRED reservations, awaiting settlement;
- ``settled``: final spend (settlements, unreserved usage, adjustments, allocations, late usage);
- ``committed = reserved + accrued + settled``. Credits are recorded separately and never
  reduce committed spend or restore allowance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from microdrama.budget import policy
from microdrama.contracts.cost import UsageReceipt
from microdrama.contracts.enums import BudgetCategory, ReceiptKind
from microdrama.contracts.errors import BudgetExhausted, Conflict, NotFound, StaleRevision
from microdrama.persistence.db import Row, Tx


class ReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


# Closing reasons written to reservations.closed_reason (migration 0012 requires one on every
# closed reservation and forbids changing a RELEASED reservation's reason). release() writes the
# caller's validated reason instead of these fixed ones.
EXPIRED_REASON = "expired: past expires_at without settlement"
SETTLED_REASON = "settled"
SETTLED_AFTER_EXPIRY_REASON = "settled after expiry"
MAX_CLOSED_REASON_LENGTH = 500


@dataclass
class AccountRow:
    id: UUID
    scope_kind: str
    season_id: UUID
    episode_id: UUID | None
    cap: int
    shutdown_reserve: int
    reserved: int
    accrued: int
    settled: int
    credits: int
    overrun: int
    blocked: bool
    blocked_reason: str | None
    revision: int

    @property
    def committed(self) -> int:
        return self.reserved + self.accrued + self.settled


@dataclass
class CategoryRow:
    account_id: UUID
    category: BudgetCategory
    allocated: int
    reserved: int
    accrued: int
    settled: int
    protected: bool
    revision: int

    @property
    def committed(self) -> int:
        return self.reserved + self.accrued + self.settled


@dataclass
class ReservationRow:
    id: UUID
    account_id: UUID
    request_id: UUID
    semantic_key: str
    request_hash: str
    category: BudgetCategory
    queue: str
    job_id: UUID | None
    provider: str
    operation_kind: str
    reserved: int
    accrued: int
    settled: int
    state: ReservationState
    expires_at: datetime
    closed_at: datetime | None
    closed_reason: str | None
    is_shutdown_or_cleanup: bool
    season_id: UUID | None
    episode_id: UUID | None
    revision: int

    @property
    def open_remaining(self) -> int:
        """Worst-case exposure not yet consumed by usage (zero once expired or closed)."""
        if self.state is not ReservationState.ACTIVE:
            return 0
        return max(self.reserved - self.accrued, 0)


def account_from_row(row: Row) -> AccountRow:
    return AccountRow(
        id=row["id"],
        scope_kind=row["scope_kind"],
        season_id=row["season_id"],
        episode_id=row["episode_id"],
        cap=row["cap_micro_usd"],
        shutdown_reserve=row["shutdown_reserve_micro_usd"],
        reserved=row["reserved_outstanding_micro_usd"],
        accrued=row["accrued_micro_usd"],
        settled=row["settled_micro_usd"],
        credits=row["credits_micro_usd"],
        overrun=row["overrun_micro_usd"],
        blocked=row["paid_dispatch_blocked"],
        blocked_reason=row["blocked_reason"],
        revision=row["revision"],
    )


def category_from_row(row: Row) -> CategoryRow:
    return CategoryRow(
        account_id=row["account_id"],
        category=BudgetCategory(row["category"]),
        allocated=row["allocated_micro_usd"],
        reserved=row["reserved_outstanding_micro_usd"],
        accrued=row["accrued_micro_usd"],
        settled=row["settled_micro_usd"],
        protected=row["protected"],
        revision=row["revision"],
    )


def reservation_from_row(row: Row) -> ReservationRow:
    return ReservationRow(
        id=row["id"],
        account_id=row["account_id"],
        request_id=row["request_id"],
        semantic_key=row["semantic_key"],
        request_hash=row["request_hash"],
        category=BudgetCategory(row["category"]),
        queue=row["queue"],
        job_id=row["job_id"],
        provider=row["provider"],
        operation_kind=row["operation_kind"],
        reserved=row["reserved_micro_usd"],
        accrued=row["accrued_micro_usd"],
        settled=row["settled_micro_usd"],
        state=ReservationState(row["state"]),
        expires_at=row["expires_at"],
        closed_at=row["closed_at"],
        closed_reason=row["closed_reason"],
        is_shutdown_or_cleanup=row["is_shutdown_or_cleanup"],
        season_id=row["season_id"],
        episode_id=row["episode_id"],
        revision=row["revision"],
    )


# --- lookups and row locks ---------------------------------------------------------------


def episode_account_id(tx: Tx, episode_id: UUID) -> UUID:
    """Budgets are never auto-created: a missing account is a NotFound."""
    row = tx.fetchone(
        "SELECT id FROM budget_accounts WHERE scope_kind = 'EPISODE' AND episode_id = %s",
        (episode_id,),
    )
    if row is None:
        raise NotFound("episode has no budget account", episode_id=str(episode_id))
    return row["id"]


def research_account_id(tx: Tx, season_id: UUID) -> UUID:
    row = tx.fetchone(
        "SELECT id FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
        (season_id,),
    )
    if row is None:
        raise NotFound("season has no research envelope", season_id=str(season_id))
    return row["id"]


def lock_account(tx: Tx, account_id: UUID) -> AccountRow:
    row = tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s FOR UPDATE", (account_id,))
    if row is None:
        raise NotFound("budget account not found", account_id=str(account_id))
    return account_from_row(row)


def lock_categories(tx: Tx, account_id: UUID) -> dict[BudgetCategory, CategoryRow]:
    rows = tx.fetchall(
        "SELECT * FROM budget_category_allocations WHERE account_id = %s "
        "ORDER BY category FOR UPDATE",
        (account_id,),
    )
    categories = {BudgetCategory(row["category"]): category_from_row(row) for row in rows}
    if set(categories) != set(BudgetCategory):
        raise Conflict("budget account is missing category rows", account_id=str(account_id))
    return categories


def lock_reservation(tx: Tx, reservation_id: UUID) -> ReservationRow:
    row = tx.fetchone("SELECT * FROM reservations WHERE id = %s FOR UPDATE", (reservation_id,))
    if row is None:
        raise NotFound("reservation not found", reservation_id=str(reservation_id))
    return reservation_from_row(row)


def reservation_account_id(tx: Tx, reservation_id: UUID) -> UUID:
    row = tx.fetchone("SELECT account_id FROM reservations WHERE id = %s", (reservation_id,))
    if row is None:
        raise NotFound("reservation not found", reservation_id=str(reservation_id))
    return row["account_id"]


def reservations_matching(tx: Tx, request_id: UUID, semantic_key: str) -> list[ReservationRow]:
    rows = tx.fetchall(
        "SELECT * FROM reservations WHERE request_id = %s OR semantic_key = %s",
        (request_id, semantic_key),
    )
    return [reservation_from_row(row) for row in rows]


class Ledger:
    """Accounting for one locked account inside one transaction.

    All methods mutate in-memory rows; ``flush`` writes the changed rows back. Negative counters
    are refused here before any write (the database CHECKs are the backstop).
    """

    def __init__(
        self,
        tx: Tx,
        account: AccountRow,
        categories: dict[BudgetCategory, CategoryRow],
        *,
        now: datetime,
        new_id: Callable[[], UUID],
    ) -> None:
        self.tx = tx
        self.account = account
        self.categories = categories
        self.now = now
        self._new_id = new_id
        self._account_dirty = False
        self._dirty_categories: set[BudgetCategory] = set()
        self._dirty_reservations: dict[UUID, ReservationRow] = {}

    # --- counter moves -----------------------------------------------------------------

    def move(
        self,
        category: BudgetCategory,
        *,
        reserved: int = 0,
        accrued: int = 0,
        settled: int = 0,
    ) -> None:
        cat = self.categories[category]
        acct = self.account
        if (
            min(
                cat.reserved + reserved,
                cat.accrued + accrued,
                cat.settled + settled,
                acct.reserved + reserved,
                acct.accrued + accrued,
                acct.settled + settled,
            )
            < 0
        ):
            raise Conflict(
                "internal accounting invariant violated: a counter would go negative",
                category=category.value,
            )
        cat.reserved += reserved
        cat.accrued += accrued
        cat.settled += settled
        acct.reserved += reserved
        acct.accrued += accrued
        acct.settled += settled
        self._dirty_categories.add(category)
        self._account_dirty = True

    def mark_reservation(self, reservation: ReservationRow) -> None:
        self._dirty_reservations[reservation.id] = reservation

    def apply_receipt(self, receipt: UsageReceipt, reservation: ReservationRow | None) -> None:
        """Post one usage receipt against the locked counters (ACCRUAL/SETTLEMENT/ADJUSTMENT/CREDIT)."""
        amount = receipt.amount_micro_usd
        category = receipt.category
        if receipt.kind is ReceiptKind.CREDIT:
            # Recorded only: a credit never restores allowance or reduces settled spend.
            self.account.credits += amount
            self._account_dirty = True
            return
        if reservation is None:
            # Unreserved real usage is spend in full.
            self.move(category, settled=amount)
            return
        if reservation.state in (ReservationState.SETTLED, ReservationState.RELEASED):
            # Only ADJUSTMENT may follow a close: it is late billing and is added to settled. A
            # restated SETTLEMENT or a new ACCRUAL would be a second final amount, so it is refused
            # before anything is written (summing both would double count).
            if receipt.kind is not ReceiptKind.ADJUSTMENT:
                raise Conflict(
                    "restatements and late billing must be ADJUSTMENT receipts",
                    reservation_id=str(reservation.id),
                    state=reservation.state.value,
                    kind=receipt.kind.value,
                )
            self.move(category, settled=amount)
            reservation.settled += amount
            self.mark_reservation(reservation)
            return
        if receipt.kind is ReceiptKind.SETTLEMENT:
            # Final amount for R: frees the open remainder and replaces the accrued usage
            # (whatever was counted for an expired reservation, max(reserved, usage)).
            was_expired = reservation.state is ReservationState.EXPIRED
            self.move(
                category,
                reserved=-reservation.open_remaining,
                accrued=-reservation.accrued,
                settled=amount,
            )
            reservation.settled = amount
            reservation.state = ReservationState.SETTLED
            reservation.closed_at = self.now
            reservation.closed_reason = (
                SETTLED_AFTER_EXPIRY_REASON if was_expired else SETTLED_REASON
            )
            self.mark_reservation(reservation)
            return
        if reservation.state is ReservationState.EXPIRED:
            self._accrue_on_expired(receipt, reservation)
            return
        # ACCRUAL / ADJUSTMENT on an ACTIVE reservation: incremental usage against the hold.
        moved = min(amount, reservation.open_remaining)
        self.move(category, reserved=-moved, accrued=amount)
        reservation.accrued += amount
        self.mark_reservation(reservation)

    def _accrue_on_expired(self, receipt: UsageReceipt, reservation: ReservationRow) -> None:
        """Late usage on an expired, unsettled reservation counts max(reserved, actual usage).

        ``expire`` already counted max(reserved, usage so far) as accrued. Actual usage is the sum
        of this reservation's ACCRUAL/ADJUSTMENT charges, which all entered accrued while the
        reservation was still open, so it is read from ``charges`` (this receipt is not inserted
        yet). Only the increase above what is already counted moves into accrued: late usage within
        the worst case adds nothing, and usage above it adds exactly the excess.
        """
        amount = receipt.amount_micro_usd
        usage_before = self.tx.fetchval(
            "SELECT COALESCE(SUM(amount_micro_usd), 0)::bigint FROM charges "
            "WHERE reservation_id = %s AND kind IN ('ACCRUAL', 'ADJUSTMENT')",
            (reservation.id,),
        )
        counted_before = max(reservation.reserved, usage_before)
        if reservation.accrued != counted_before:
            raise Conflict(
                "internal accounting invariant violated: expired reservation accrual is out of step",
                reservation_id=str(reservation.id),
                accrued_micro_usd=reservation.accrued,
                expected_micro_usd=counted_before,
            )
        counted_after = max(reservation.reserved, usage_before + amount)
        delta = counted_after - counted_before
        self.move(receipt.category, accrued=delta)
        reservation.accrued += delta
        self.mark_reservation(reservation)

    def expire(self, reservation: ReservationRow) -> None:
        """Conservative expiry: the open remainder is assumed spent until settlement reconciles it."""
        remaining = reservation.open_remaining
        self.move(reservation.category, reserved=-remaining, accrued=remaining)
        reservation.accrued += remaining
        reservation.state = ReservationState.EXPIRED
        reservation.closed_at = self.now
        reservation.closed_reason = EXPIRED_REASON
        self.mark_reservation(reservation)

    def release(self, reservation: ReservationRow, *, reason: str) -> None:
        """Free an ACTIVE reservation that has no usage at all, recording the caller's reason."""
        self.move(reservation.category, reserved=-reservation.open_remaining)
        reservation.state = ReservationState.RELEASED
        reservation.closed_at = self.now
        reservation.closed_reason = reason
        self.mark_reservation(reservation)

    def move_allocation(
        self, *, source: BudgetCategory, target: BudgetCategory, amount: int, reason: str
    ) -> None:
        """Move allocated headroom between categories; the account total stays the same."""
        src = self.categories[source]
        dst = self.categories[target]
        if src.allocated - amount < 0:
            raise Conflict("transfer exceeds the source allocation", category=source.value)
        src.allocated -= amount
        dst.allocated += amount
        self._dirty_categories.update({source, target})
        self.tx.execute(
            "INSERT INTO budget_transfers (id, account_id, from_category, to_category, "
            "amount_micro_usd, reason) VALUES (%s, %s, %s, %s, %s, %s)",
            (self._new_id(), self.account.id, source.value, target.value, amount, reason),
        )

    def spill_from_recovery(
        self, *, target: BudgetCategory, shortfall: int, floor: int, reason: str
    ) -> None:
        """Borrow a category shortfall from recovery headroom, keeping its free amount >= floor."""
        recovery = self.categories[policy.RECOVERY_HEADROOM]
        if recovery.allocated - shortfall - recovery.committed < floor:
            raise BudgetExhausted(
                "recovery headroom cannot cover the spill without breaching the shutdown reserve",
                account_id=str(self.account.id),
                category=target.value,
                shortfall_micro_usd=shortfall,
                recovery_free_micro_usd=recovery.allocated - recovery.committed,
                shutdown_reserve_micro_usd=floor,
            )
        self.move_allocation(
            source=policy.RECOVERY_HEADROOM, target=target, amount=shortfall, reason=reason
        )

    # --- overruns ----------------------------------------------------------------------

    def check_overrun(self, *, charge_id: UUID, profile: str | None) -> int:
        """Record committed spend above the cap as an observed overrun and block paid dispatch.

        Returns the newly recorded increment (0 when committed spend is within the cap). The
        recorded overrun never decreases: a later settlement cannot erase it.
        """
        acct = self.account
        excess = acct.committed - acct.cap
        if excess <= acct.overrun:
            return 0
        increment = excess - acct.overrun
        acct.overrun = excess
        if not acct.blocked:
            acct.blocked = True
            acct.blocked_reason = "observed overrun: committed spend exceeded the cap"
        self._account_dirty = True
        self.tx.execute(
            "INSERT INTO cost_overruns (id, account_id, charge_id, amount_micro_usd, "
            "quarantined_profile, note) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                self._new_id(),
                acct.id,
                charge_id,
                increment,
                profile,
                f"observed overrun of {increment} micro-USD; paid dispatch blocked",
            ),
        )
        return increment

    # --- persistence -------------------------------------------------------------------

    def flush(self) -> None:
        """Write every changed row back under the revision guard."""
        acct = self.account
        if self._account_dirty:
            updated = self.tx.execute(
                "UPDATE budget_accounts SET reserved_outstanding_micro_usd = %s, "
                "accrued_micro_usd = %s, settled_micro_usd = %s, credits_micro_usd = %s, "
                "overrun_micro_usd = %s, paid_dispatch_blocked = %s, blocked_reason = %s, "
                "updated_at = %s, revision = revision + 1 WHERE id = %s AND revision = %s",
                (
                    acct.reserved,
                    acct.accrued,
                    acct.settled,
                    acct.credits,
                    acct.overrun,
                    acct.blocked,
                    acct.blocked_reason,
                    self.now,
                    acct.id,
                    acct.revision,
                ),
            )
            if updated != 1:
                raise StaleRevision("budget account changed while locked", account_id=str(acct.id))
        for category in sorted(self._dirty_categories, key=lambda c: c.value):
            cat = self.categories[category]
            updated = self.tx.execute(
                "UPDATE budget_category_allocations SET allocated_micro_usd = %s, "
                "reserved_outstanding_micro_usd = %s, accrued_micro_usd = %s, "
                "settled_micro_usd = %s, revision = revision + 1 "
                "WHERE account_id = %s AND category = %s AND revision = %s",
                (
                    cat.allocated,
                    cat.reserved,
                    cat.accrued,
                    cat.settled,
                    acct.id,
                    category.value,
                    cat.revision,
                ),
            )
            if updated != 1:
                raise StaleRevision("budget category changed while locked", category=category.value)
        for res in self._dirty_reservations.values():
            updated = self.tx.execute(
                "UPDATE reservations SET accrued_micro_usd = %s, settled_micro_usd = %s, "
                "state = %s, closed_at = %s, closed_reason = %s, updated_at = %s, "
                "revision = revision + 1 WHERE id = %s AND revision = %s",
                (
                    res.accrued,
                    res.settled,
                    res.state.value,
                    res.closed_at,
                    res.closed_reason,
                    self.now,
                    res.id,
                    res.revision,
                ),
            )
            if updated != 1:
                raise StaleRevision("reservation changed while locked", reservation_id=str(res.id))

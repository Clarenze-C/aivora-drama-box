"""Atomic US$10 budget accounting (T005).

Every public method is one database transaction. The first statement that touches an account
takes ``SELECT ... FOR UPDATE`` on its ``budget_accounts`` row, so all money movement for one
account is serialized and reads inside the transaction see the committed counters. Amounts are
``int`` micro-USD; no floats and no Decimal arithmetic are used for money.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from microdrama.budget import policy
from microdrama.budget.ledger import (
    MAX_CLOSED_REASON_LENGTH,
    AccountRow,
    CategoryRow,
    Ledger,
    ReservationRow,
    ReservationState,
    episode_account_id,
    lock_account,
    lock_categories,
    lock_reservation,
    research_account_id,
    reservation_account_id,
    reservation_from_row,
    reservations_matching,
)
from microdrama.budget.reports import cost_view_for_episode, summary_for_episode
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, UsageReceipt
from microdrama.contracts.enums import BudgetCategory, BudgetScopeKind
from microdrama.contracts.errors import (
    BudgetExhausted,
    Conflict,
    DuplicateSemanticKey,
    IdempotencyConflict,
    NotFound,
    ProtectedReserveViolation,
    SchemaInvalid,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.release import CostSummary
from microdrama.contracts.routes import CostView
from microdrama.contracts.season import CostPolicy
from microdrama.persistence.db import Database, Tx, insert_row, jsonb

_RECOVERY = BudgetCategory.RECOVERY_HEADROOM
_RESEARCH = BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA
_METERED = BudgetCategory.METERED_MANAGEMENT

# Research spend that is settled and not yet attributed. Only amounts that entered ``settled``
# are attributable: unreserved non-credit charges, and reservation settlements (the final amount).
# Reservation-linked ACCRUAL/ADJUSTMENT charges on an open reservation sit in ``accrued`` and are
# counted again inside the final settlement, so they are excluded to avoid double attribution.
# Late adjustments on a closed reservation are settled but not attributed: they stay on the
# research account, which is the safe direction for attribution.
_RESEARCH_SOURCE_SQL = """
SELECT c.id, c.receipt_id, c.amount_micro_usd, c.cost_basis
  FROM charges c
 WHERE c.account_id = %s
   AND c.kind <> 'CREDIT'
   AND c.amount_micro_usd > 0
   AND (c.reservation_id IS NULL OR c.kind = 'SETTLEMENT')
   AND NOT EXISTS (SELECT 1 FROM cost_allocations a WHERE a.source_charge_id = c.id)
 ORDER BY c.observed_at, c.receipt_id
"""

_OVERLAP_SQL = """
SELECT id FROM pod_usage_intervals
 WHERE provider = %s AND pod_id = %s
   AND tstzrange(interval_start, interval_end, '[)') && tstzrange(%s, %s, '[)')
"""


@dataclass(frozen=True)
class Reservation:
    """A reservation as the service reports it. ``replayed`` marks an idempotent return."""

    id: UUID
    account_id: UUID
    category: BudgetCategory
    semantic_key: str
    state: ReservationState
    reserved_micro_usd: int
    accrued_micro_usd: int
    settled_micro_usd: int
    replayed: bool = False
    closed_reason: str | None = None


@dataclass(frozen=True)
class ChargeResult:
    charge_id: UUID
    receipt_id: UUID
    account_id: UUID
    replayed: bool
    overrun_recorded_micro_usd: int = 0


@dataclass(frozen=True)
class ResearchAllocation:
    source_charge_id: UUID
    target_account_id: UUID
    episode_id: UUID
    amount_micro_usd: int


def split_first_takes_remainder(amount: int, parts: int) -> list[int]:
    """Integer split: equal shares, with the remainder added to the first share (deterministic)."""
    if parts < 1 or amount < 0:
        raise ValueError("split needs at least one part and a non-negative amount")
    base, remainder = divmod(amount, parts)
    return [base + remainder, *([base] * (parts - 1))]


def _micro(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise SchemaInvalid(f"{name} must be a non-negative integer micro-USD", field=name)
    return value


def _closed_reason(reason: str) -> str:
    """Validate a release reason for reservations.closed_reason (one line, 1..500 characters)."""
    cleaned = reason.strip() if isinstance(reason, str) else ""
    if not cleaned:
        raise SchemaInvalid("release requires a reason")
    if len(cleaned) > MAX_CLOSED_REASON_LENGTH or "\n" in cleaned or "\r" in cleaned:
        raise SchemaInvalid(
            "release reason must be one line of at most 500 characters",
            max_length=MAX_CLOSED_REASON_LENGTH,
        )
    return cleaned


def _as_reservation(row: ReservationRow, *, replayed: bool = False) -> Reservation:
    return Reservation(
        id=row.id,
        account_id=row.account_id,
        category=row.category,
        semantic_key=row.semantic_key,
        state=row.state,
        reserved_micro_usd=row.reserved,
        accrued_micro_usd=row.accrued,
        settled_micro_usd=row.settled,
        replayed=replayed,
        closed_reason=row.closed_reason,
    )


class BudgetService:
    """Money-safe budget accounting over the frozen ``budget_*``/``reservations``/``charges`` tables.

    Rules later lanes depend on:
    - Research attribution (allocate_research_cost): the season research account keeps its full
      settled spend, and each episode's settled spend gains its share as a ``cost_allocations``
      row. Summing research plus episode accounts double-counts by design; any portfolio total must
      read ``cost_allocations`` to avoid it.
    - Overrun block: once an observed overrun is recorded, paid dispatch stops for the episode.
      reserve() refuses new work and replays of earlier reservations (see reserve()).
    - Non-USD receipts are refused with UnknownPrice and are NOT recorded (there is no FX). Operators
      must treat such a refusal as unrecorded real spend (see record_usage()).
    """

    def __init__(self, db: Database, clock: Clock, ids: IdGenerator, settings: Settings) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._id_lock = threading.Lock()

    # --- plumbing ----------------------------------------------------------------------

    def _new_id(self) -> UUID:
        # Serialized so a shared, non-thread-safe IdGenerator stays correct under concurrency.
        with self._id_lock:
            return self._ids.new_id()

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SchemaInvalid("clock must return a timezone-aware instant")
        return now

    def _ledger(
        self, tx: Tx, account: AccountRow, categories: dict[BudgetCategory, CategoryRow]
    ) -> Ledger:
        return Ledger(tx, account, categories, now=self._now(), new_id=self._new_id)

    # --- account opening ---------------------------------------------------------------

    def open_episode_account(
        self, tx: Tx, *, season_id: UUID, episode_id: UUID, policy: CostPolicy
    ) -> UUID:
        """Open the episode budget (idempotent). The cap is fixed here and cannot be raised later."""
        episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound("episode not found", episode_id=str(episode_id))
        if episode["season_id"] != season_id:
            raise Conflict("episode belongs to a different season", episode_id=str(episode_id))
        account_id = self._new_id()
        created = tx.fetchone(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd, "
            "shutdown_reserve_micro_usd) VALUES (%s, 'EPISODE', %s, %s, %s, %s) "
            "ON CONFLICT (episode_id) WHERE scope_kind = 'EPISODE' DO NOTHING RETURNING id",
            (
                account_id,
                season_id,
                episode_id,
                policy.episode_cap_micro_usd,
                policy.shutdown_reserve_micro_usd,
            ),
        )
        if created is None:
            existing = tx.fetchone(
                "SELECT id, cap_micro_usd, shutdown_reserve_micro_usd FROM budget_accounts "
                "WHERE scope_kind = 'EPISODE' AND episode_id = %s",
                (episode_id,),
            )
            if existing is None:
                raise Conflict("episode budget changed while opening", episode_id=str(episode_id))
            allocated = self._allocations(tx, existing["id"])
            if (
                existing["cap_micro_usd"] != policy.episode_cap_micro_usd
                or existing["shutdown_reserve_micro_usd"] != policy.shutdown_reserve_micro_usd
                or allocated != dict(policy.allocation_micro_usd)
            ):
                raise Conflict(
                    "episode budget already opened with a different policy (the cap is immutable)",
                    episode_id=str(episode_id),
                )
            return existing["id"]
        self._insert_categories(tx, account_id, dict(policy.allocation_micro_usd))
        return account_id

    def open_research_account(self, tx: Tx, *, season_id: UUID, envelope_micro_usd: int) -> UUID:
        """Open the pre-Gate-1 research envelope for a season (idempotent, no shutdown reserve)."""
        _micro(envelope_micro_usd, "envelope_micro_usd")
        if not 0 < envelope_micro_usd <= 10_000_000:
            raise SchemaInvalid("research envelope must be within (0, US$10]")
        season = tx.fetchone("SELECT id FROM seasons WHERE id = %s", (season_id,))
        if season is None:
            raise NotFound("season not found", season_id=str(season_id))
        account_id = self._new_id()
        created = tx.fetchone(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, cap_micro_usd, "
            "shutdown_reserve_micro_usd) VALUES (%s, 'SEASON_RESEARCH', %s, %s, 0) "
            "ON CONFLICT (season_id) WHERE scope_kind = 'SEASON_RESEARCH' DO NOTHING RETURNING id",
            (account_id, season_id, envelope_micro_usd),
        )
        if created is None:
            existing = tx.fetchone(
                "SELECT id, cap_micro_usd FROM budget_accounts "
                "WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
                (season_id,),
            )
            if existing is None or existing["cap_micro_usd"] != envelope_micro_usd:
                raise Conflict(
                    "research envelope already opened with a different amount",
                    season_id=str(season_id),
                )
            return existing["id"]
        allocations = {category: 0 for category in BudgetCategory}
        allocations[_RESEARCH] = envelope_micro_usd
        self._insert_categories(tx, account_id, allocations)
        return account_id

    def _insert_categories(
        self, tx: Tx, account_id: UUID, allocations: dict[BudgetCategory, int]
    ) -> None:
        for category in BudgetCategory:
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
                "protected) VALUES (%s, %s, %s, %s)",
                (
                    account_id,
                    category.value,
                    allocations[category],
                    category is not _METERED,
                ),
            )

    @staticmethod
    def _allocations(tx: Tx, account_id: UUID) -> dict[BudgetCategory, int]:
        rows = tx.fetchall(
            "SELECT category, allocated_micro_usd FROM budget_category_allocations "
            "WHERE account_id = %s",
            (account_id,),
        )
        return {BudgetCategory(row["category"]): row["allocated_micro_usd"] for row in rows}

    # --- reservations ------------------------------------------------------------------

    def reserve(self, request: BudgetReservationRequest) -> Reservation:
        """Check and hold worst-case exposure before a paid dispatch, in one transaction.

        Refusals (nothing is held): PolicyDenied for queue/category ownership, UnknownPrice for a
        missing, non-USD, synthetic-outside-mock or zero exposure price, BudgetExhausted for the cap,
        a category without room (production may spill from recovery, others may not), a blocked
        account, or a recovery reservation that would break the shutdown reserve.

        Blocked accounts: once an observed overrun is recorded, every reserve() with
        ``is_shutdown_or_cleanup=False`` is refused with BudgetExhausted, including an idempotent
        replay of an earlier reservation. A caller that retries after an overrun must not dispatch.

        Cleanup: ``is_shutdown_or_cleanup=True`` bypasses only the blocked flag and the shutdown
        reserve. It still has to fit under the cap, so after an overrun it is usually refused too.
        The GPU shutdown path therefore must stop the pod whether or not reserve() succeeds, and
        record the interval through record_gpu_interval(), which is not blocked.

        Recovery: a direct (non-cleanup) reservation in RECOVERY_HEADROOM must leave the shutdown
        reserve free. Spill from recovery into production categories also keeps it free, unless the
        request is cleanup.
        """
        policy.check_queue_may_reserve(request.queue, request.category)
        policy.check_price_admissible(request, self._settings)
        if request.scope_kind is BudgetScopeKind.SEASON_RESEARCH and request.episode_id is not None:
            raise SchemaInvalid("season research reservations must not name an episode")
        request_hash = canonical_hash(request)
        cleanup = request.is_shutdown_or_cleanup
        with self._db.transaction() as tx:
            if request.scope_kind is BudgetScopeKind.EPISODE:
                account_id = episode_account_id(tx, request.episode_id)
            else:
                account_id = research_account_id(tx, request.season_id)
            acct = lock_account(tx, account_id)
            cats = lock_categories(tx, account_id)
            ledger = self._ledger(tx, acct, cats)
            # An observed overrun stops all new paid work; shutdown/cleanup is exempt from this
            # flag but still bound by the cap check below.
            if acct.blocked and not cleanup:
                raise BudgetExhausted(
                    "paid dispatch is blocked by an observed overrun",
                    account_id=str(acct.id),
                    blocked_reason=acct.blocked_reason,
                )
            if request.season_id is not None and request.season_id != acct.season_id:
                raise Conflict("reservation season does not match its budget account")
            existing = reservations_matching(tx, request.request_id, request.semantic_key)
            if existing:
                if (
                    len(existing) == 1
                    and existing[0].account_id == acct.id
                    and existing[0].request_hash == request_hash
                ):
                    return _as_reservation(existing[0], replayed=True)
                raise IdempotencyConflict(
                    "semantic key or request id was reused with different content",
                    semantic_key=request.semantic_key,
                )
            if request.expires_at <= ledger.now:
                raise SchemaInvalid("reservation expiry must be in the future")

            worst = request.worst_case_micro_usd
            floor = 0 if cleanup else acct.shutdown_reserve
            if acct.committed + worst + floor > acct.cap:
                raise BudgetExhausted(
                    "episode allowance exhausted",
                    account_id=str(acct.id),
                    cap_micro_usd=acct.cap,
                    committed_micro_usd=acct.committed,
                    requested_micro_usd=worst,
                    shutdown_reserve_micro_usd=floor,
                )
            category = cats[request.category]
            if (
                request.category is _RECOVERY
                and not cleanup
                and category.committed + worst + acct.shutdown_reserve > category.allocated
            ):
                raise BudgetExhausted(
                    "recovery headroom must keep the shutdown reserve free",
                    account_id=str(acct.id),
                    allocated_micro_usd=category.allocated,
                    committed_micro_usd=category.committed,
                    requested_micro_usd=worst,
                )
            shortfall = category.committed + worst - category.allocated
            if shortfall > 0:
                if not policy.spill_allowed(request.queue, request.category):
                    raise BudgetExhausted(
                        "category allocation exhausted",
                        account_id=str(acct.id),
                        category=request.category.value,
                        allocated_micro_usd=category.allocated,
                        committed_micro_usd=category.committed,
                        requested_micro_usd=worst,
                    )
                ledger.spill_from_recovery(
                    target=request.category,
                    shortfall=shortfall,
                    floor=floor,
                    reason=f"auto-spill:{request.semantic_key}",
                )

            reservation_id = self._new_id()
            insert_row(
                tx,
                "reservations",
                {
                    "id": reservation_id,
                    "account_id": acct.id,
                    "request_id": request.request_id,
                    "semantic_key": request.semantic_key,
                    "request_hash": request_hash,
                    "category": request.category.value,
                    "queue": request.queue.value,
                    "job_id": request.job_id,
                    "provider": request.provider,
                    "operation_kind": request.operation_kind,
                    "price": jsonb(request.price),
                    "ceilings": jsonb(request.ceilings),
                    "is_shutdown_or_cleanup": cleanup,
                    "reserved_micro_usd": worst,
                    "state": ReservationState.ACTIVE.value,
                    "expires_at": request.expires_at,
                    "season_id": acct.season_id,
                    "episode_id": acct.episode_id,
                },
            )
            ledger.move(request.category, reserved=worst)
            ledger.flush()
            return Reservation(
                id=reservation_id,
                account_id=acct.id,
                category=request.category,
                semantic_key=request.semantic_key,
                state=ReservationState.ACTIVE,
                reserved_micro_usd=worst,
                accrued_micro_usd=0,
                settled_micro_usd=0,
            )

    def release(self, reservation_id: UUID, *, reason: str) -> Reservation:
        """Free an ACTIVE reservation that has no usage. Usage must be settled, never released.

        The stripped reason is persisted as ``closed_reason``. It must be non-empty, at most 500
        characters and a single line (SchemaInvalid otherwise). A RELEASED reservation is terminal:
        its state and reason never change again, though late usage may still add to its settled
        amount.
        """
        cleaned = _closed_reason(reason)
        with self._db.transaction() as tx:
            account_id = reservation_account_id(tx, reservation_id)
            acct = lock_account(tx, account_id)
            cats = lock_categories(tx, account_id)
            res = lock_reservation(tx, reservation_id)
            if res.state is not ReservationState.ACTIVE:
                raise Conflict("only an ACTIVE reservation can be released", state=res.state.value)
            if res.accrued != 0:
                raise Conflict(
                    "usage was accrued against this reservation; it must be settled, not released"
                )
            ledger = self._ledger(tx, acct, cats)
            ledger.release(res, reason=cleaned)
            ledger.flush()
            return _as_reservation(res)

    def expire_stale(self, now: datetime | None = None) -> int:
        """Expire ACTIVE reservations past their expiry; their exposure stays counted as spent."""
        when = now if now is not None else self._now()
        if when.tzinfo is None or when.utcoffset() is None:
            raise SchemaInvalid("expire_stale needs a timezone-aware instant")
        expired_total = 0
        with self._db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT DISTINCT account_id FROM reservations "
                "WHERE state = 'ACTIVE' AND expires_at <= %s ORDER BY account_id",
                (when,),
            )
            for row in rows:
                account_id = row["account_id"]
                acct = lock_account(tx, account_id)
                cats = lock_categories(tx, account_id)
                due = tx.fetchall(
                    "SELECT * FROM reservations WHERE account_id = %s AND state = 'ACTIVE' "
                    "AND expires_at <= %s ORDER BY id FOR UPDATE",
                    (account_id, when),
                )
                if not due:
                    continue
                ledger = Ledger(tx, acct, cats, now=when, new_id=self._new_id)
                for res_row in due:
                    res = reservation_from_row(res_row)
                    ledger.expire(res)
                    expired_total += 1
                ledger.flush()
        return expired_total

    # --- usage -------------------------------------------------------------------------

    def record_usage(self, receipt: UsageReceipt) -> ChargeResult:
        """Record one usage receipt. Replays are idempotent; overruns are recorded, never hidden.

        Refusals (nothing is recorded): UnknownPrice for a non-USD receipt. There is no FX, so the
        spend must be investigated by operators, not dropped. PolicyDenied for a synthetic receipt
        outside OFFLINE_MOCK, or a measured receipt inside it. Conflict or IdempotencyConflict for
        mismatched scope, category or provider, or a reused receipt key with different content.

        Recorded receipts never raise for an overrun. An overrun is recorded, blocks further paid
        dispatch, and is returned as ``overrun_recorded_micro_usd``. Late usage on an expired
        reservation counts max(reserved, actual usage), so usage within the worst case adds nothing.
        """
        policy.check_receipt_admissible(receipt, self._settings)
        if (
            receipt.reservation_id is None
            and receipt.episode_id is None
            and receipt.season_id is None
        ):
            raise SchemaInvalid("receipt names neither a reservation, an episode nor a season")
        with self._db.transaction() as tx:
            account_id = self._receipt_account_id(tx, receipt)
            acct = lock_account(tx, account_id)
            cats = lock_categories(tx, account_id)
            ledger = self._ledger(tx, acct, cats)
            replay = self._replay(tx, receipt, acct.id)
            if replay is not None:
                return replay
            self._check_scope(receipt, acct)
            reservation = self._linked_reservation(tx, receipt, acct.id)
            return self._post_charge(tx, ledger, receipt, reservation)

    def _record_gpu_interval(
        self,
        *,
        lease_id: UUID,
        provider: str,
        pod_id: str,
        account_id: UUID,
        interval_start: datetime,
        interval_end: datetime,
        basis: str,
        receipt: UsageReceipt,
    ) -> ChargeResult:
        """Attribute one paid GPU interval to its lease exactly once.

        An exact replay of the same receipt returns the earlier result. Any other overlap on the
        same pod is refused as ``Conflict`` with totals unchanged (warm-pod reuse cannot double
        count an interval).
        """
        if basis not in policy.POD_INTERVAL_BASES:
            raise SchemaInvalid("unknown pod interval basis", basis=basis)
        if interval_end <= interval_start:
            raise SchemaInvalid("pod interval must end after it starts")
        if receipt.provider != provider:
            raise SchemaInvalid("receipt provider does not match the interval provider")
        if receipt.interval_start != interval_start or receipt.interval_end != interval_end:
            raise SchemaInvalid("receipt interval does not match the attributed interval")
        if receipt.reservation_id is None:
            raise Conflict("a GPU interval must be attributed to its lease reservation")
        policy.check_receipt_admissible(receipt, self._settings)
        with self._db.transaction() as tx:
            acct = lock_account(tx, account_id)
            cats = lock_categories(tx, account_id)
            ledger = self._ledger(tx, acct, cats)
            lease = tx.fetchone(
                "SELECT l.provider, l.pod_id, l.reservation_id, r.account_id, r.category "
                "FROM pod_leases l JOIN reservations r ON r.id = l.reservation_id "
                "WHERE l.id = %s",
                (lease_id,),
            )
            if lease is None:
                raise NotFound("pod lease not found", lease_id=str(lease_id))
            if lease["provider"] != provider or lease["pod_id"] != pod_id:
                raise Conflict("interval provider or pod does not match the lease")
            if lease["account_id"] != acct.id:
                raise Conflict("lease belongs to a different budget account")
            if receipt.reservation_id != lease["reservation_id"]:
                raise Conflict("GPU interval must be attributed to the lease reservation")
            if receipt.category.value != lease["category"]:
                raise Conflict("GPU interval category does not match the lease reservation")
            self._check_scope(receipt, acct)
            replay = self._replay(tx, receipt, acct.id)
            if replay is not None:
                self._check_interval_replay(
                    tx, replay.charge_id, lease_id, provider, pod_id, interval_start, interval_end
                )
                return replay
            overlapping = tx.fetchall(
                _OVERLAP_SQL, (provider, pod_id, interval_start, interval_end)
            )
            if overlapping:
                raise Conflict(
                    "interval already attributed",
                    provider=provider,
                    pod_id=pod_id,
                    overlapping_intervals=len(overlapping),
                )
            reservation = self._linked_reservation(tx, receipt, acct.id)
            return self._post_charge(
                tx,
                ledger,
                receipt,
                reservation,
                pod_lease_id=lease_id,
                interval=(provider, pod_id, interval_start, interval_end, basis, lease_id),
            )

    def record_gpu_interval(
        self,
        *,
        lease_id: UUID,
        provider: str,
        pod_id: str,
        account_id: UUID,
        interval_start: datetime,
        interval_end: datetime,
        basis: str,
        receipt: UsageReceipt,
    ) -> ChargeResult:
        """Attribute one paid GPU interval to its lease exactly once.

        An exact replay of the same receipt returns the earlier result. Any other overlap on the
        same pod is refused as ``Conflict`` with totals unchanged. Warm-pod reuse across episodes
        cannot double count an interval either: the database exclusion constraint on the pod's
        intervals (not serialized by one account lock) is mapped to the same conflict.
        """
        try:
            return self._record_gpu_interval(
                lease_id=lease_id,
                provider=provider,
                pod_id=pod_id,
                account_id=account_id,
                interval_start=interval_start,
                interval_end=interval_end,
                basis=basis,
                receipt=receipt,
            )
        except DuplicateSemanticKey as exc:
            if "pod_usage_intervals" in str(exc.details.get("constraint") or ""):
                raise Conflict(
                    "interval already attributed", provider=provider, pod_id=pod_id
                ) from exc
            raise

    def _receipt_account_id(self, tx: Tx, receipt: UsageReceipt) -> UUID:
        if receipt.reservation_id is not None:
            return reservation_account_id(tx, receipt.reservation_id)
        if receipt.episode_id is not None:
            return episode_account_id(tx, receipt.episode_id)
        return research_account_id(tx, receipt.season_id)

    @staticmethod
    def _check_scope(receipt: UsageReceipt, acct: AccountRow) -> None:
        """A receipt may only post to the episode or season its account belongs to."""
        if receipt.episode_id is not None and receipt.episode_id != acct.episode_id:
            raise Conflict(
                "receipt episode does not match its budget account",
                episode_id=str(receipt.episode_id),
            )
        if receipt.season_id is not None and receipt.season_id != acct.season_id:
            raise Conflict(
                "receipt season does not match its budget account", season_id=str(receipt.season_id)
            )

    def _linked_reservation(
        self, tx: Tx, receipt: UsageReceipt, account_id: UUID
    ) -> ReservationRow | None:
        if receipt.reservation_id is None:
            return None
        reservation = lock_reservation(tx, receipt.reservation_id)
        if reservation.account_id != account_id:
            raise Conflict("receipt reservation belongs to a different budget account")
        if reservation.category is not receipt.category:
            raise Conflict("receipt category does not match its reservation")
        if reservation.provider != receipt.provider:
            raise Conflict("receipt provider does not match its reservation")
        return reservation

    def _replay(self, tx: Tx, receipt: UsageReceipt, account_id: UUID) -> ChargeResult | None:
        """Return the earlier result for an identical receipt; refuse any other reuse of its keys."""
        rows = tx.fetchall(
            "SELECT * FROM charges WHERE (provider = %s AND provider_receipt_id = %s) "
            "OR receipt_id = %s",
            (receipt.provider, receipt.provider_receipt_id, receipt.receipt_id),
        )
        if not rows:
            return None
        row = rows[0]
        same_keys = (
            len(rows) == 1
            and row["provider"] == receipt.provider
            and row["provider_receipt_id"] == receipt.provider_receipt_id
            and row["receipt_id"] == receipt.receipt_id
        )
        if not same_keys or row["account_id"] != account_id:
            raise IdempotencyConflict(
                "receipt key was already used for a different receipt",
                provider=receipt.provider,
                provider_receipt_id=receipt.provider_receipt_id,
            )
        stored = UsageReceipt.model_validate(row["receipt"])
        if canonical_hash(stored) != canonical_hash(receipt):
            raise IdempotencyConflict(
                "receipt replayed with different content",
                provider=receipt.provider,
                provider_receipt_id=receipt.provider_receipt_id,
            )
        return ChargeResult(
            charge_id=row["id"],
            receipt_id=row["receipt_id"],
            account_id=row["account_id"],
            replayed=True,
        )

    @staticmethod
    def _check_interval_replay(
        tx: Tx,
        charge_id: UUID,
        lease_id: UUID,
        provider: str,
        pod_id: str,
        start: datetime,
        end: datetime,
    ) -> None:
        row = tx.fetchone("SELECT * FROM pod_usage_intervals WHERE charge_id = %s", (charge_id,))
        if row is None or (
            row["lease_id"],
            row["provider"],
            row["pod_id"],
            row["interval_start"],
            row["interval_end"],
        ) != (lease_id, provider, pod_id, start, end):
            raise Conflict("receipt was already recorded without this pod interval attribution")

    def _post_charge(
        self,
        tx: Tx,
        ledger: Ledger,
        receipt: UsageReceipt,
        reservation: ReservationRow | None,
        *,
        pod_lease_id: UUID | None = None,
        interval: tuple[str, str, datetime, datetime, str, UUID] | None = None,
    ) -> ChargeResult:
        account = ledger.account
        charge_id = self._new_id()
        ledger.apply_receipt(receipt, reservation)
        insert_row(
            tx,
            "charges",
            {
                "id": charge_id,
                "account_id": account.id,
                "reservation_id": reservation.id if reservation is not None else None,
                "receipt_id": receipt.receipt_id,
                "provider": receipt.provider,
                "provider_receipt_id": receipt.provider_receipt_id,
                "kind": receipt.kind.value,
                "cost_basis": receipt.cost_basis.value,
                "provenance": receipt.provenance.value,
                "category": receipt.category.value,
                "amount_micro_usd": receipt.amount_micro_usd,
                "units": receipt.units,
                "unit": receipt.unit.value,
                "interval_start": receipt.interval_start,
                "interval_end": receipt.interval_end,
                "observed_at": receipt.observed_at,
                "job_id": receipt.job_id,
                "season_id": account.season_id,
                "episode_id": account.episode_id,
                "pod_lease_id": pod_lease_id,
                "receipt": jsonb(receipt),
            },
        )
        if interval is not None:
            provider, pod_id, start, end, basis, lease_id = interval
            insert_row(
                tx,
                "pod_usage_intervals",
                {
                    "id": self._new_id(),
                    "provider": provider,
                    "pod_id": pod_id,
                    "lease_id": lease_id,
                    "account_id": account.id,
                    "charge_id": charge_id,
                    "interval_start": start,
                    "interval_end": end,
                    "basis": basis,
                    "amount_micro_usd": receipt.amount_micro_usd,
                },
            )
        profile = (
            f"{reservation.provider}:{reservation.operation_kind}"
            if reservation is not None
            else None
        )
        increment = ledger.check_overrun(charge_id=charge_id, profile=profile)
        ledger.flush()
        return ChargeResult(
            charge_id=charge_id,
            receipt_id=receipt.receipt_id,
            account_id=account.id,
            replayed=False,
            overrun_recorded_micro_usd=increment,
        )

    # --- transfers ---------------------------------------------------------------------

    def transfer(
        self,
        account_id: UUID,
        *,
        from_category: BudgetCategory,
        to_category: BudgetCategory,
        amount: int,
        reason: str,
    ) -> None:
        """Move allocation inside the episode total without touching committed funds."""
        _micro(amount, "amount")
        if amount == 0:
            raise SchemaInvalid("transfer amount must be positive")
        if from_category is to_category:
            raise SchemaInvalid("transfer needs two different categories")
        if not reason or not reason.strip():
            raise SchemaInvalid("transfer requires a reason")
        with self._db.transaction() as tx:
            acct = lock_account(tx, account_id)
            cats = lock_categories(tx, account_id)
            if to_category is _METERED and from_category is not _METERED:
                raise ProtectedReserveViolation(
                    "metered management may never receive protected funds",
                    from_category=from_category.value,
                )
            source = cats[from_category]
            if source.allocated - amount < source.committed:
                raise ProtectedReserveViolation(
                    "transfer would leave the source category below its committed spend",
                    category=from_category.value,
                    committed_micro_usd=source.committed,
                    requested_micro_usd=amount,
                )
            if from_category is _RECOVERY and (
                source.allocated - amount - source.committed < acct.shutdown_reserve
            ):
                raise ProtectedReserveViolation(
                    "transfer would take recovery headroom below the shutdown reserve",
                    shutdown_reserve_micro_usd=acct.shutdown_reserve,
                )
            ledger = self._ledger(tx, acct, cats)
            ledger.move_allocation(
                source=from_category, target=to_category, amount=amount, reason=reason
            )
            ledger.flush()

    # --- research ----------------------------------------------------------------------

    def allocate_research_cost(
        self,
        *,
        season_id: UUID,
        episode_ids: Iterable[UUID],
        basis: str,
    ) -> list[ResearchAllocation]:
        """Attribute settled research spend to episodes, once per (source charge, episode).

        The research account keeps the full settled charge. Each episode's settled spend gains its
        share (integer split, remainder to the first episode in ``episode_ids``). Already-allocated
        charges are skipped, so a rerun changes nothing. Only unreserved charges and reservation
        settlements are attributable. Late ACCRUAL/ADJUSTMENT usage on a closed reservation stays on
        the research account and is not attributed.
        """
        episodes = list(episode_ids)
        if not episodes:
            raise SchemaInvalid("research allocation needs at least one episode")
        if len(set(episodes)) != len(episodes):
            raise SchemaInvalid("research allocation episodes must be distinct")
        if not basis or not basis.strip():
            raise SchemaInvalid("research allocation requires a basis")
        results: list[ResearchAllocation] = []
        with self._db.transaction() as tx:
            research_id = research_account_id(tx, season_id)
            target_ids = {ep: episode_account_id(tx, ep) for ep in episodes}
            locked: dict[UUID, tuple] = {}
            for account_id in sorted({research_id, *target_ids.values()}):
                locked[account_id] = (
                    lock_account(tx, account_id),
                    lock_categories(tx, account_id),
                )
            for episode_id in episodes:
                target = locked[target_ids[episode_id]][0]
                if target.season_id != season_id:
                    raise Conflict("episode budget belongs to a different season")
            ledgers = {
                account_id: self._ledger(tx, acct, cats)
                for account_id, (acct, cats) in locked.items()
            }
            sources = tx.fetchall(_RESEARCH_SOURCE_SQL, (research_id,))
            for source in sources:
                shares = split_first_takes_remainder(source["amount_micro_usd"], len(episodes))
                for episode_id, share in zip(episodes, shares, strict=True):
                    if share == 0:
                        continue
                    target_id = target_ids[episode_id]
                    ledger = ledgers[target_id]
                    insert_row(
                        tx,
                        "cost_allocations",
                        {
                            "id": self._new_id(),
                            "source_charge_id": source["id"],
                            "source_account_id": research_id,
                            "target_account_id": target_id,
                            "amount_micro_usd": share,
                            "basis": basis,
                        },
                    )
                    ledger.move(_RESEARCH, settled=share)
                    ledger.check_overrun(charge_id=source["id"], profile=None)
                    results.append(
                        ResearchAllocation(
                            source_charge_id=source["id"],
                            target_account_id=target_id,
                            episode_id=episode_id,
                            amount_micro_usd=share,
                        )
                    )
            for ledger in ledgers.values():
                ledger.flush()
        return results

    # --- reports -----------------------------------------------------------------------

    def summary(self, episode_id: UUID) -> CostSummary:
        return summary_for_episode(self._db, episode_id)

    def cost_view(self, episode_id: UUID) -> CostView:
        return cost_view_for_episode(self._db, episode_id, self._now())


__all__ = [
    "BudgetService",
    "ChargeResult",
    "Reservation",
    "ResearchAllocation",
    "split_first_takes_remainder",
]

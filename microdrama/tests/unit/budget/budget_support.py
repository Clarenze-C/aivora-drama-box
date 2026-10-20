"""Shared builders and invariant checker for the budget tests (T005). Imported by test modules.

- ``World``: real PostgreSQL per test (root ``db`` fixture), deterministic clock and ids, builders
  for valid contract payloads (requests, fake and measured receipts, pod leases).
- ``assert_consistent``: the accounting invariant checker. It recomputes every counter from the
  reservation, charge, allocation and overrun rows and compares it with the stored counters. Every
  scenario calls it after its last money movement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from microdrama.budget import BudgetService, Reservation
from microdrama.config import Settings
from microdrama.contracts.cost import (
    BudgetReservationRequest,
    ExposureCeilings,
    PriceQuote,
    UsageReceipt,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    CostBasis,
    ExecutionMode,
    PriceUnit,
    Provenance,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.persistence.db import IsolationLevel, insert_row
from microdrama.testing.fakes import FakeClock, SequentialIds, fake_price_quote
from microdrama.testing.fakes.common import receipt_id_for
from microdrama.testing.seed import seed_episode, seed_job, seed_season

T0 = datetime(2026, 10, 20, tzinfo=UTC)
CAP = 10_000_000
SHUTDOWN = 250_000
GPU = BudgetCategory.GPU_GENERATION
REFERENCES = BudgetCategory.REFERENCES_DIALOGUE
QA = BudgetCategory.QA_CAPTIONS
RESEARCH = BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA
CPU = BudgetCategory.CPU_STORAGE_TRANSFER
METERED = BudgetCategory.METERED_MANAGEMENT
RECOVERY = BudgetCategory.RECOVERY_HEADROOM
ALL_CATEGORIES = tuple(BudgetCategory)
_REQUEST_NS = uuid.UUID("6f1c2d9e-0000-4000-8000-00000000b0d6")
# Only used by pure (no-database) tests that need a syntactically valid episode scope.
DEFAULT_EPISODE_ID = uuid.UUID("0a5e0000-0000-4000-8000-00000000e001")


@dataclass(frozen=True)
class Episode:
    season_id: uuid.UUID
    episode_id: uuid.UUID
    account_id: uuid.UUID


def synthetic_quote(unit_price_micro_usd: int = 1) -> PriceQuote:
    """A labelled synthetic price (FAKE_SYNTHETIC) with a 1-micro-USD unit, so probes of any size
    satisfy the contract's worst-case >= unit price x max units rule."""
    base = fake_price_quote(PriceUnit.GPU_SECOND)
    return base.model_copy(update={"unit_price_micro_usd": unit_price_micro_usd})


def request_for(
    *,
    key: str,
    episode_id: uuid.UUID | None = None,
    season_id: uuid.UUID | None = None,
    worst: int = 700_000,
    category: BudgetCategory = GPU,
    queue: QueueName = QueueName.PRODUCTION,
    cleanup: bool = False,
    expires_at: datetime = T0 + timedelta(hours=1),
    price: Any = "default",
    provider: str = "fake-runpod",
    operation_kind: str = "gpu.render_shot",
    job_id: uuid.UUID | None = None,
) -> BudgetReservationRequest:
    """A valid reservation request. Retries of one logical step reuse the same arguments."""
    research = season_id is not None and episode_id is None
    if not research and episode_id is None:
        episode_id = DEFAULT_EPISODE_ID
    if price == "default":
        price = synthetic_quote()
    return BudgetReservationRequest(
        request_id=uuid.uuid5(_REQUEST_NS, f"request:{key}"),
        semantic_key=key,
        scope_kind=BudgetScopeKind.SEASON_RESEARCH if research else BudgetScopeKind.EPISODE,
        episode_id=None if research else episode_id,
        season_id=season_id if research else None,
        category=category,
        queue=queue,
        job_id=job_id,
        provider=provider,
        operation_kind=operation_kind,
        price=price,
        ceilings=ExposureCeilings(timeout_ms=1_000, max_units=1),
        worst_case_micro_usd=worst,
        is_shutdown_or_cleanup=cleanup,
        expires_at=expires_at,
    )


def fake_receipt(
    *,
    provider_receipt_id: str,
    kind: ReceiptKind,
    amount: int,
    category: BudgetCategory = GPU,
    observed_at: datetime = T0,
    reservation: Reservation | None = None,
    episode_id: uuid.UUID | None = None,
    season_id: uuid.UUID | None = None,
    provider: str = "fake-runpod",
    interval: tuple[datetime, datetime] | None = None,
    reservation_id: uuid.UUID | None = None,
) -> UsageReceipt:
    """A SYNTHETIC_FAKE receipt (offline mock). Its id depends only on the provider key."""
    start, end = interval if interval is not None else (None, None)
    return UsageReceipt(
        receipt_id=receipt_id_for(provider, provider_receipt_id),
        provider=provider,
        provider_receipt_id=provider_receipt_id,
        kind=kind,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation.id if reservation is not None else reservation_id,
        episode_id=episode_id,
        season_id=season_id,
        category=category,
        amount_micro_usd=amount,
        units=1,
        unit=PriceUnit.GPU_SECOND,
        interval_start=start,
        interval_end=end,
        observed_at=observed_at,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


def measured_receipt(
    *,
    provider_receipt_id: str,
    kind: ReceiptKind,
    amount: int,
    category: BudgetCategory = GPU,
    reservation: Reservation | None = None,
    episode_id: uuid.UUID | None = None,
    provider: str = "live-provider",
) -> UsageReceipt:
    """A BILLED receipt from a live provider. Refused in OFFLINE_MOCK by the service."""
    return UsageReceipt(
        receipt_id=receipt_id_for(provider, provider_receipt_id),
        provider=provider,
        provider_receipt_id=provider_receipt_id,
        kind=kind,
        cost_basis=CostBasis.BILLED,
        reservation_id=reservation.id if reservation is not None else None,
        episode_id=episode_id,
        category=category,
        amount_micro_usd=amount,
        units=1,
        unit=PriceUnit.GPU_SECOND,
        observed_at=T0,
        provenance=Provenance.LIVE_PROVIDER,
    )


class World:
    """Builds seeded accounts through the real service and reads counters back."""

    def __init__(self, db: Database, settings: Settings | None = None) -> None:
        self.db = db
        self.clock = FakeClock(T0)
        self.settings = settings or Settings(execution_mode=ExecutionMode.OFFLINE_MOCK)
        self.service = BudgetService(db, self.clock, SequentialIds("budget-world"), self.settings)

    def episode(
        self,
        *,
        season: uuid.UUID | None = None,
        number: int = 1,
        policy: CostPolicy | None = None,
    ) -> Episode:
        with self.db.transaction() as tx:
            season_id = season if season is not None else seed_season(tx)
            episode_id = seed_episode(tx, season_id, number=number)
            account_id = self.service.open_episode_account(
                tx, season_id=season_id, episode_id=episode_id, policy=policy or CostPolicy()
            )
        return Episode(season_id=season_id, episode_id=episode_id, account_id=account_id)

    def research(self, season_id: uuid.UUID, envelope: int = 2_000_000) -> uuid.UUID:
        with self.db.transaction() as tx:
            return self.service.open_research_account(
                tx, season_id=season_id, envelope_micro_usd=envelope
            )

    def job(self, key: str) -> uuid.UUID:
        with self.db.transaction() as tx:
            return seed_job(tx, semantic_key=key)

    def counters(self, account_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
        assert row is not None
        return {
            "cap": row["cap_micro_usd"],
            "shutdown": row["shutdown_reserve_micro_usd"],
            "reserved": row["reserved_outstanding_micro_usd"],
            "accrued": row["accrued_micro_usd"],
            "settled": row["settled_micro_usd"],
            "credits": row["credits_micro_usd"],
            "overrun": row["overrun_micro_usd"],
            "blocked": row["paid_dispatch_blocked"],
            "committed": row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"],
        }

    def category(self, account_id: uuid.UUID, category: BudgetCategory) -> dict[str, int]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM budget_category_allocations WHERE account_id = %s AND category = %s",
                (account_id, category.value),
            )
        assert row is not None
        return {
            "allocated": row["allocated_micro_usd"],
            "reserved": row["reserved_outstanding_micro_usd"],
            "accrued": row["accrued_micro_usd"],
            "settled": row["settled_micro_usd"],
            "committed": row["reserved_outstanding_micro_usd"]
            + row["accrued_micro_usd"]
            + row["settled_micro_usd"],
        }

    def count(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            return int(tx.fetchval(sql, params))

    def reservation_state(self, reservation_id: uuid.UUID) -> dict[str, Any]:
        with self.db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
            row = tx.fetchone("SELECT * FROM reservations WHERE id = %s", (reservation_id,))
        assert row is not None
        return {
            "state": row["state"],
            "reserved": row["reserved_micro_usd"],
            "accrued": row["accrued_micro_usd"],
            "settled": row["settled_micro_usd"],
            "closed": row["closed_at"] is not None,
            "closed_reason": row["closed_reason"],
        }

    def production_gpu_headroom(self, account_id: uuid.UUID) -> int:
        """Largest worst-case a new production GPU reservation can hold right now.

        Independent oracle of the policy: the cap leaves the shutdown reserve free, and the GPU
        category may borrow recovery headroom down to the shutdown reserve.
        """
        counters = self.counters(account_id)
        gpu = self.category(account_id, GPU)
        recovery = self.category(account_id, RECOVERY)
        spill_room = max(recovery["allocated"] - recovery["committed"] - counters["shutdown"], 0)
        cap_room = counters["cap"] - counters["shutdown"] - counters["committed"]
        category_room = gpu["allocated"] + spill_room - gpu["committed"]
        return max(min(cap_room, category_room), 0)

    def lease(
        self,
        *,
        episode: Episode,
        reservation: Reservation,
        pod_id: str,
        lease_state: str = "ACTIVE",
        provider: str = "fake-runpod",
    ) -> uuid.UUID:
        """A GPU lease row bound to an existing reservation (as the pod lane creates them)."""
        lease_id = uuid.uuid4()
        with self.db.transaction() as tx:
            insert_row(
                tx,
                "pod_leases",
                {
                    "id": lease_id,
                    "provider": provider,
                    "pod_id": pod_id,
                    "owned_tag": "md-owned",
                    "client_token": f"lease-{lease_id}",
                    "owner_episode_id": episode.episode_id,
                    "reservation_id": reservation.id,
                    "lease_state": lease_state,
                    "pod_state": "RUNNING",
                    "gpu_type": "FAKE-GPU",
                    "hourly_price_micro_usd": 900_000,
                    "lease_expires_at": T0 + timedelta(hours=2),
                },
            )
        return lease_id


def fill_to_cap_minus_shutdown(world: World, ep: Episode) -> dict[str, Any]:
    """Committed spend of exactly cap - shutdown reserve (9,750,000), with recovery left at the
    shutdown reserve. Keys: gpu (4.75M, spilled), ref, qa, res, cpu, met (community), gpu2 (2.25M,
    spilled to exactly the shutdown reserve)."""
    svc = world.service
    episode = ep.episode_id
    out: dict[str, Any] = {}
    out["gpu"] = svc.reserve(request_for(key="fill.gpu", episode_id=episode, worst=2_500_000))
    out["ref"] = svc.reserve(
        request_for(key="fill.ref", episode_id=episode, worst=1_500_000, category=REFERENCES)
    )
    out["qa"] = svc.reserve(
        request_for(key="fill.qa", episode_id=episode, worst=1_000_000, category=QA)
    )
    out["res"] = svc.reserve(
        request_for(key="fill.res", episode_id=episode, worst=1_000_000, category=RESEARCH)
    )
    out["cpu"] = svc.reserve(
        request_for(key="fill.cpu", episode_id=episode, worst=500_000, category=CPU)
    )
    out["met"] = svc.reserve(
        request_for(
            key="fill.met",
            episode_id=episode,
            worst=1_000_000,
            category=METERED,
            queue=QueueName.COMMUNITY,
        )
    )
    out["gpu2"] = svc.reserve(request_for(key="fill.gpu2", episode_id=episode, worst=2_250_000))
    assert world.counters(ep.account_id)["committed"] == CAP - SHUTDOWN
    return out


def assert_consistent(db: Database, account_id: uuid.UUID) -> dict[str, int]:
    """Recompute every counter from the rows and assert it matches the stored value.

    Rules (see ledger.py): ACTIVE contributes its open remainder to reserved and its accrued usage
    to accrued; ACTIVE/EXPIRED contribute accrued; closed reservations contribute only settled;
    unreserved non-credit charges and cost allocations into the account are settled; credits are
    their own total; the overrun is the sum of recorded overruns; allocations sum to the cap.
    """
    with db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
        acct = tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
        cats = tx.fetchall(
            "SELECT * FROM budget_category_allocations WHERE account_id = %s", (account_id,)
        )
        reservations = tx.fetchall(
            "SELECT * FROM reservations WHERE account_id = %s", (account_id,)
        )
        charges = tx.fetchall(
            "SELECT id, kind, reservation_id, category, amount_micro_usd, created_at FROM charges "
            "WHERE account_id = %s",
            (account_id,),
        )
        inbound = tx.fetchall(
            "SELECT amount_micro_usd FROM cost_allocations WHERE target_account_id = %s",
            (account_id,),
        )
        overruns = tx.fetchall(
            "SELECT amount_micro_usd FROM cost_overruns WHERE account_id = %s", (account_id,)
        )
    assert acct is not None
    # Actual usage per reservation: its ACCRUAL/ADJUSTMENT charges. While a reservation is open
    # (ACTIVE or EXPIRED) every such charge entered accrued; closed reservations never take new
    # accruals, so this sum is only used for open reservations below.
    usage: dict[Any, int] = {}
    for charge in charges:
        if charge["reservation_id"] is not None and charge["kind"] in ("ACCRUAL", "ADJUSTMENT"):
            usage[charge["reservation_id"]] = (
                usage.get(charge["reservation_id"], 0) + charge["amount_micro_usd"]
            )
    by_reservation: dict[Any, list[Any]] = {}
    for charge in charges:
        if charge["reservation_id"] is not None:
            by_reservation.setdefault(charge["reservation_id"], []).append(charge)
    expected: dict[str, list[int]] = {c.value: [0, 0, 0] for c in BudgetCategory}
    credits = 0
    for res in reservations:
        cat = res["category"]
        used = usage.get(res["id"], 0)
        worst = res["reserved_micro_usd"]
        # Settled amount derived from the reservation's own charges (V-13): a SETTLED reservation
        # holds its one SETTLEMENT plus the ADJUSTMENTs applied after it (late billing); a RELEASED
        # reservation holds only late ADJUSTMENTs; an open reservation has none.
        mine = by_reservation.get(res["id"], [])
        if res["state"] == "SETTLED":
            settlements = [c for c in mine if c["kind"] == "SETTLEMENT"]
            assert len(settlements) == 1, (
                f"settled reservation {res['id']}: {len(settlements)} finals"
            )
            final = settlements[0]
            late = sum(
                c["amount_micro_usd"]
                for c in mine
                if c["kind"] == "ADJUSTMENT" and c["created_at"] > final["created_at"]
            )
            derived_settled = final["amount_micro_usd"] + late
        elif res["state"] == "RELEASED":
            derived_settled = sum(c["amount_micro_usd"] for c in mine if c["kind"] == "ADJUSTMENT")
        else:
            derived_settled = 0
        assert res["settled_micro_usd"] == derived_settled, (
            f"reservation {res['id']} ({res['state']}): settled {res['settled_micro_usd']} "
            f"!= derived from charges {derived_settled}"
        )
        if res["state"] == "ACTIVE":
            # The hold is consumed by usage; usage beyond the hold is accrued in full.
            assert res["accrued_micro_usd"] == used, (
                f"active reservation {res['id']}: accrued {res['accrued_micro_usd']} "
                f"!= usage {used}"
            )
            expected[cat][0] += max(worst - used, 0)
            expected[cat][1] += used
        elif res["state"] == "EXPIRED":
            # Expiry counts max(worst case, actual usage) until settlement; later usage may only
            # raise that to its own max (never add the whole late amount again).
            counted = max(worst, used)
            assert res["accrued_micro_usd"] == counted, (
                f"expired reservation {res['id']}: accrued {res['accrued_micro_usd']} "
                f"!= max(reserved {worst}, usage {used}) = {counted}"
            )
            expected[cat][1] += counted
        elif res["state"] == "RELEASED":
            assert res["accrued_micro_usd"] == 0, f"released reservation {res['id']} has usage"
        expected[cat][2] += derived_settled
    for charge in charges:
        if charge["kind"] == "CREDIT":
            credits += charge["amount_micro_usd"]
        elif charge["reservation_id"] is None:
            expected[charge["category"]][2] += charge["amount_micro_usd"]
    for allocation in inbound:
        expected[RESEARCH.value][2] += allocation["amount_micro_usd"]

    totals = [0, 0, 0]
    allocated_total = 0
    assert {row["category"] for row in cats} == {c.value for c in BudgetCategory}
    for row in cats:
        want = expected[row["category"]]
        got = [
            row["reserved_outstanding_micro_usd"],
            row["accrued_micro_usd"],
            row["settled_micro_usd"],
        ]
        assert got == want, f"category {row['category']}: stored {got}, recomputed {want}"
        assert min(got) >= 0
        assert row["allocated_micro_usd"] >= 0
        for i in range(3):
            totals[i] += want[i]
        allocated_total += row["allocated_micro_usd"]

    overrun_total = sum(row["amount_micro_usd"] for row in overruns)
    stored = [
        acct["reserved_outstanding_micro_usd"],
        acct["accrued_micro_usd"],
        acct["settled_micro_usd"],
    ]
    assert stored == totals, f"account counters {stored} != category sums {totals}"
    assert acct["credits_micro_usd"] == credits
    assert acct["overrun_micro_usd"] == overrun_total
    assert acct["paid_dispatch_blocked"] == (overrun_total > 0)
    assert allocated_total == acct["cap_micro_usd"], "allocations must always sum to the cap"
    committed = sum(totals)
    assert committed <= acct["cap_micro_usd"] + overrun_total
    return {
        "committed": committed,
        "reserved": totals[0],
        "accrued": totals[1],
        "settled": totals[2],
    }

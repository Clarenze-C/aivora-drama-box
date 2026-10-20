"""Read-only budget reports: the episode cost summary and the cost view (T005).

Reports run in one REPEATABLE READ, READ ONLY transaction so the summary, lines and unknowns
describe one consistent snapshot. Every SUM is cast to bigint so money stays a Python ``int``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from microdrama.budget.ledger import AccountRow, account_from_row, episode_account_id
from microdrama.contracts.enums import BudgetCategory
from microdrama.contracts.release import CostSummary
from microdrama.contracts.routes import CostLine, CostView
from microdrama.persistence.db import Database, IsolationLevel, Tx


def _synthetic_fake_micro_usd(tx: Tx, account_id: UUID) -> int:
    own = tx.fetchval(
        "SELECT COALESCE(SUM(amount_micro_usd), 0)::bigint FROM charges "
        "WHERE account_id = %s AND cost_basis = 'SYNTHETIC_FAKE'",
        (account_id,),
    )
    shared = tx.fetchval(
        "SELECT COALESCE(SUM(a.amount_micro_usd), 0)::bigint FROM cost_allocations a "
        "JOIN charges c ON c.id = a.source_charge_id "
        "WHERE a.target_account_id = %s AND c.cost_basis = 'SYNTHETIC_FAKE'",
        (account_id,),
    )
    return int(own) + int(shared)


def _summary(account: AccountRow, synthetic: int) -> CostSummary:
    committed = account.committed
    return CostSummary(
        episode_cap_micro_usd=account.cap,
        settled_micro_usd=account.settled,
        accrued_micro_usd=account.accrued,
        reserved_outstanding_micro_usd=account.reserved,
        remaining_micro_usd=max(account.cap - committed, 0),
        synthetic_fake_micro_usd=synthetic,
    )


def summary_for_episode(db: Database, episode_id: UUID) -> CostSummary:
    with db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
        account_id = episode_account_id(tx, episode_id)
        account = account_from_row(
            tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
        )
        synthetic = _synthetic_fake_micro_usd(tx, account_id)
    return _summary(account, synthetic)


def cost_view_for_episode(db: Database, episode_id: UUID, now: datetime) -> CostView:
    with db.transaction(isolation=IsolationLevel.REPEATABLE_READ, readonly=True) as tx:
        account_id = episode_account_id(tx, episode_id)
        account = account_from_row(
            tx.fetchone("SELECT * FROM budget_accounts WHERE id = %s", (account_id,))
        )
        synthetic = _synthetic_fake_micro_usd(tx, account_id)
        charges = tx.fetchall(
            "SELECT receipt_id, category, amount_micro_usd, cost_basis, kind, observed_at "
            "FROM charges WHERE account_id = %s ORDER BY observed_at, receipt_id",
            (account_id,),
        )
        allocations = tx.fetchall(
            "SELECT a.amount_micro_usd, a.created_at, c.receipt_id, c.cost_basis "
            "FROM cost_allocations a JOIN charges c ON c.id = a.source_charge_id "
            "WHERE a.target_account_id = %s ORDER BY a.created_at, a.id",
            (account_id,),
        )
        overruns = tx.fetchall(
            "SELECT amount_micro_usd, charge_id, quarantined_profile, detected_at "
            "FROM cost_overruns WHERE account_id = %s ORDER BY detected_at, id",
            (account_id,),
        )
        open_unknowns = tx.fetchall(
            "SELECT id, category, reserved_micro_usd, accrued_micro_usd, state, expires_at "
            "FROM reservations WHERE account_id = %s AND (state = 'EXPIRED' "
            "OR (state = 'ACTIVE' AND expires_at <= %s)) ORDER BY expires_at, id",
            (account_id, now),
        )

    lines = [
        CostLine(
            receipt_id=row["receipt_id"],
            category=row["category"].lower(),
            amount_micro_usd=int(row["amount_micro_usd"]),
            cost_basis=row["cost_basis"].lower(),
            kind=row["kind"].lower(),
            observed_at=row["observed_at"],
        )
        for row in charges
    ]
    # Research spend attributed to this episode appears as its own line, so the lines explain
    # the settled total instead of silently disagreeing with it.
    lines.extend(
        CostLine(
            receipt_id=row["receipt_id"],
            category=BudgetCategory.RESEARCH_SCRIPT_PROMPTS_METADATA.value.lower(),
            amount_micro_usd=int(row["amount_micro_usd"]),
            cost_basis=row["cost_basis"].lower(),
            kind="research_allocation",
            observed_at=row["created_at"],
        )
        for row in allocations
    )
    overrun_lines = [
        (
            f"observed overrun of {row['amount_micro_usd']} micro-USD at "
            f"{row['detected_at'].isoformat()}; charge {row['charge_id']}; "
            f"profile {row['quarantined_profile'] or 'unknown'}; paid dispatch blocked"
        )
        for row in overruns
    ]
    unknown_lines = [
        (
            f"reservation {row['id']} ({row['category']}) expired unsettled; worst-case "
            f"{row['reserved_micro_usd']} micro-USD is counted as spent until a settlement "
            "reconciles it"
            if row["state"] == "EXPIRED"
            else f"reservation {row['id']} ({row['category']}) is past its expiry but not yet "
            f"expired; {row['reserved_micro_usd']} micro-USD is still reserved"
        )
        for row in open_unknowns
    ]
    return CostView(
        episode_id=episode_id,
        summary=_summary(account, synthetic),
        lines=lines,
        overruns=overrun_lines,
        unknowns=unknown_lines,
    )

"""Pure budget rules: queue ownership, admission of prices and receipts, spill eligibility.

Nothing here touches the database. ``BudgetService`` calls these checks before it takes any
row lock, so a refused request never changes accounting state.
"""

from __future__ import annotations

from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    ExecutionMode,
    PriceSource,
    QueueName,
)
from microdrama.contracts.errors import PolicyDenied, UnknownPrice

METERED_MANAGEMENT = BudgetCategory.METERED_MANAGEMENT
RECOVERY_HEADROOM = BudgetCategory.RECOVERY_HEADROOM
PROTECTED_CATEGORIES: frozenset[BudgetCategory] = frozenset(BudgetCategory) - {METERED_MANAGEMENT}
POD_INTERVAL_BASES: frozenset[str] = frozenset(
    {"COLD_START", "DOWNLOAD", "RUNNING", "IDLE", "SHUTDOWN"}
)

# Which budget categories each queue may reserve (SPEC §6 ownership rules).
_OWNED_CATEGORIES: dict[QueueName, frozenset[BudgetCategory]] = {
    QueueName.PRODUCTION: PROTECTED_CATEGORIES,
    QueueName.PUBLICATION: frozenset({BudgetCategory.CPU_STORAGE_TRANSFER}),
    QueueName.COMMUNITY: frozenset({METERED_MANAGEMENT}),
}


def check_queue_may_reserve(queue: QueueName, category: BudgetCategory) -> None:
    """Metered management belongs to community alone; community may touch nothing else."""
    if category not in _OWNED_CATEGORIES[queue]:
        raise PolicyDenied(
            f"queue {queue.value} may not reserve {category.value}",
            queue=queue.value,
            category=category.value,
        )


def spill_allowed(queue: QueueName, category: BudgetCategory) -> bool:
    """Only production may borrow shortfalls from recovery headroom (never into recovery)."""
    return queue is QueueName.PRODUCTION and category is not RECOVERY_HEADROOM


def check_price_admissible(request: BudgetReservationRequest, settings: Settings) -> None:
    """Unknown price, currency or exposure blocks paid dispatch; it is never assumed zero."""
    if request.worst_case_micro_usd <= 0:
        raise UnknownPrice("worst-case exposure is not bounded above zero; paid dispatch blocked")
    price = request.price
    if price is None:
        raise UnknownPrice(
            "price is unknown; paid dispatch blocked",
            provider=request.provider,
            operation_kind=request.operation_kind,
        )
    if price.currency != "USD":
        raise UnknownPrice(
            "price is not in USD and no FX rate is available; paid dispatch blocked",
            currency=price.currency,
        )
    if (
        price.source is PriceSource.FAKE_SYNTHETIC
        and settings.execution_mode is not ExecutionMode.OFFLINE_MOCK
    ):
        raise UnknownPrice(
            "synthetic price is only valid in OFFLINE_MOCK; paid dispatch blocked",
            execution_mode=settings.execution_mode.value,
        )


def check_receipt_admissible(receipt: UsageReceipt, settings: Settings) -> None:
    """Fake receipts exist only in OFFLINE_MOCK; measured receipts are real money outside it."""
    mock = settings.execution_mode is ExecutionMode.OFFLINE_MOCK
    if receipt.currency != "USD":
        raise UnknownPrice(
            "receipt is not in USD and cannot be converted without an FX rate",
            currency=receipt.currency,
        )
    if receipt.cost_basis is CostBasis.SYNTHETIC_FAKE and not mock:
        raise PolicyDenied(
            "synthetic receipts are accepted only in OFFLINE_MOCK",
            execution_mode=settings.execution_mode.value,
        )
    if receipt.measured and mock:
        raise PolicyDenied(
            "measured receipts are real money and are refused in OFFLINE_MOCK",
            cost_basis=receipt.cost_basis.value,
        )

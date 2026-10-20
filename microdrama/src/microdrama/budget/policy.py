"""Pure budget rules: queue ownership, admission of prices and receipts, spill eligibility.

Nothing here touches the database. ``BudgetService`` calls these checks before it takes any
row lock, so a refused request never changes accounting state.
"""

from __future__ import annotations

from microdrama.config import Settings
from microdrama.contracts.cost import (
    CLEANUP_CATEGORIES,
    CLEANUP_OPERATION_KINDS,
    BudgetReservationRequest,
    UsageReceipt,
    exposure_units,
)
from microdrama.contracts.enums import (
    BudgetCategory,
    CostBasis,
    ExecutionMode,
    PriceSource,
    PriceUnit,
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


# Which categories each cleanup operation may draw from (defence in depth behind the contract's
# CLEANUP_CATEGORIES/CLEANUP_OPERATION_KINDS allow-lists): stopping or terminating an owned pod is
# GPU or recovery work; storage cleanup is CPU/storage or recovery work. A flagged storage.cleanup on
# a GPU category, or a flagged render, is refused.
_CLEANUP_CATEGORIES_BY_KIND: dict[str, frozenset[BudgetCategory]] = {
    "pod.stop": frozenset({BudgetCategory.GPU_GENERATION, RECOVERY_HEADROOM}),
    "pod.terminate": frozenset({BudgetCategory.GPU_GENERATION, RECOVERY_HEADROOM}),
    "storage.cleanup": frozenset({BudgetCategory.CPU_STORAGE_TRANSFER, RECOVERY_HEADROOM}),
}
assert frozenset(_CLEANUP_CATEGORIES_BY_KIND) == CLEANUP_OPERATION_KINDS
assert all(categories <= CLEANUP_CATEGORIES for categories in _CLEANUP_CATEGORIES_BY_KIND.values())


def shutdown_grant(
    queue: QueueName, category: BudgetCategory, operation_kind: str, requested: bool
) -> bool:
    """The one rule for shutdown/cleanup privileges (defence in depth behind the contract).

    Returns True when the request may draw on the shutdown reserve and bypass the blocked-account
    flag: only a production request whose operation is a known cleanup kind and whose category fits
    that kind (see ``_CLEANUP_CATEGORIES_BY_KIND``). Any other request that asks for it, including a
    flagged render, is refused with PolicyDenied. The result drives both the reserve floor and the
    blocked-account bypass, so the two can never disagree.
    """
    if not requested:
        return False
    allowed = _CLEANUP_CATEGORIES_BY_KIND.get(operation_kind)
    if queue is QueueName.PRODUCTION and allowed is not None and category in allowed:
        return True
    raise PolicyDenied(
        "only production pod stop/terminate or storage cleanup may use the shutdown reserve",
        queue=queue.value,
        category=category.value,
        operation_kind=operation_kind,
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
    if price.unit_price_micro_usd == 0:
        # A zero price is not a known price, however large the ceilings are (V-20).
        raise UnknownPrice(
            "zero unit price is not a known price; paid dispatch blocked",
            unit=price.unit.value,
        )
    if request.category is BudgetCategory.GPU_GENERATION and price.unit is not PriceUnit.GPU_SECOND:
        # GPU generation is bounded by its timeout only when priced per GPU second (V-21).
        raise UnknownPrice(
            "GPU generation must be priced per GPU_SECOND so the timeout bounds it",
            unit=price.unit.value,
        )
    try:
        units = exposure_units(price.unit, request.ceilings)
    except ValueError as exc:
        # Missing token or duration ceiling: the maximum exposure is uncertain.
        raise UnknownPrice(
            "maximum exposure is uncertain for this price unit; paid dispatch blocked",
            unit=price.unit.value,
            reason=str(exc),
        ) from exc
    if request.worst_case_micro_usd < price.unit_price_micro_usd * units:
        raise UnknownPrice(
            "worst-case exposure is below unit price x the units its ceilings allow",
            unit=price.unit.value,
            bound_micro_usd=price.unit_price_micro_usd * units,
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

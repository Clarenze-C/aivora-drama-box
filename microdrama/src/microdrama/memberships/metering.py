"""Metered-management budget plumbing for the membership/DM lane (T026).

DM sends and provider entitlement checks are metered management actions: they
consume the episode's METERED_MANAGEMENT allocation through the REAL
``BudgetService`` — reserve before the provider call, settle with receipts after.
Budget checks are never stubbed; an insufficient metered allocation suppresses the
optional action truthfully (AT-11) instead of letting it ride on another category.

Offline honesty: the synthetic price table (T007) prices one REQUEST at 1000
micro-USD with ``PriceSource.FAKE_SYNTHETIC``. A live adapter must supply a real
provider quote; an unknown price blocks dispatch (budget policy), it is never
assumed zero.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from microdrama.budget.service import BudgetService, Reservation
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings, UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    PriceUnit,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.infra import Clock
from microdrama.contracts.primitives import Identifier
from microdrama.testing.fakes.common import fake_price_quote, priced, synthetic_receipt

#: One provider request, bounded: the ceiling keeps a runaway loop from exposure.
REQUEST_CEILINGS = ExposureCeilings(timeout_ms=15_000, max_units=1)
#: How long a metered reservation is held when a transient DEFERRED is retried.
RESERVATION_TTL = timedelta(minutes=10)


def reserve_metered_request(
    budget: BudgetService,
    clock: Clock,
    *,
    request_id: UUID,
    semantic_key: str,
    episode_id: UUID,
    provider: Identifier,
    operation_kind: Identifier,
) -> Reservation:
    """Reserve one metered REQUEST (worst case = the synthetic unit price).

    Raises ``BudgetExhausted`` when the metered allocation has no room; the caller
    must suppress the optional action — never fund it from another category.
    """
    return budget.reserve(
        BudgetReservationRequest(
            request_id=request_id,
            semantic_key=semantic_key,
            scope_kind=BudgetScopeKind.EPISODE,
            episode_id=episode_id,
            category=BudgetCategory.METERED_MANAGEMENT,
            queue=QueueName.COMMUNITY,
            provider=provider,
            operation_kind=operation_kind,
            price=fake_price_quote(PriceUnit.REQUEST),
            ceilings=REQUEST_CEILINGS,
            worst_case_micro_usd=priced(PriceUnit.REQUEST, 1),
            expires_at=clock.now() + RESERVATION_TTL,
        )
    )


def settle_metered_request(
    budget: BudgetService,
    clock: Clock,
    *,
    provider: Identifier,
    provider_receipt_id: str,
    reservation_id: UUID,
) -> UsageReceipt:
    """Settle one metered reservation with a synthetic SETTLEMENT receipt (offline)."""
    receipt = synthetic_receipt(
        provider=provider,
        provider_receipt_id=provider_receipt_id,
        kind=ReceiptKind.SETTLEMENT,
        category=BudgetCategory.METERED_MANAGEMENT,
        unit=PriceUnit.REQUEST,
        units=1,
        amount_micro_usd=priced(PriceUnit.REQUEST, 1),
        observed_at=clock.now(),
        reservation_id=reservation_id,
    )
    budget.record_usage(receipt)
    return receipt


__all__ = [
    "REQUEST_CEILINGS",
    "RESERVATION_TTL",
    "Reservation",
    "reserve_metered_request",
    "settle_metered_request",
]

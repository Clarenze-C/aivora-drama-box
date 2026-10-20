"""Budget accounting (T005): micro-USD reservations, usage receipts, pod intervals, allocations.

Public surface:
- ``BudgetService`` (``service``): open accounts, reserve, record usage, GPU intervals, release,
  expire, transfer, allocate research cost, summary and cost view.
- ``build_router`` (``api``): ``GET /episodes/{episode_id}/costs``.
- ``ReservationState`` (``ledger``): reservation lifecycle states.
"""

from microdrama.budget.api import build_router
from microdrama.budget.ledger import ReservationState
from microdrama.budget.service import (
    BudgetService,
    ChargeResult,
    ResearchAllocation,
    Reservation,
)

__all__ = [
    "BudgetService",
    "ChargeResult",
    "Reservation",
    "ReservationState",
    "ResearchAllocation",
    "build_router",
]

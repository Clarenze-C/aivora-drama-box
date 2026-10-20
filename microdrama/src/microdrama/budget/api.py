"""Budget HTTP surface: ``GET /episodes/{episode_id}/costs`` (integrator registers this router).

The read dependency is supplied by the composition root, so authentication stays in one place.
Contract errors (for example NotFound for an episode without a budget) map to HTTP statuses
through the app's exception handlers.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from microdrama.budget.service import BudgetService
from microdrama.contracts.routes import CostView


def build_router(service: BudgetService, *, read_auth: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["budget"])

    @router.get("/episodes/{episode_id}/costs", response_model=CostView)
    def episode_costs(
        episode_id: UUID,
        _principal: Annotated[Any, Depends(read_auth)],
    ) -> CostView:
        return service.cost_view(episode_id)

    return router

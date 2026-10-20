"""Wiring of accepted module factories into one app (integrator-owned).

``build_services`` constructs the shared services once; ``build_components`` turns them into
``AppComponents`` with every accepted module router registered. Owner modules never include
their own routers. Later milestones add their routers here as their tasks are accepted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter, Request

from microdrama.budget import BudgetService
from microdrama.budget import build_router as build_budget_router
from microdrama.config import Settings
from microdrama.contracts.errors import PolicyDenied
from microdrama.contracts.infra import Clock, IdGenerator
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import ComponentState
from microdrama.core.api import build_router as build_core_router
from microdrama.core.auth import OWNER_OR_OPERATOR_KINDS, AuthService, require_principal_kind
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.http import (
    Dependency,
    human_or_service_dependency,
    service_dependency,
)
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database

from .app import AppComponents


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    clock: Clock
    ids: IdGenerator
    auth: AuthService
    jobs: JobService
    idempotency: IdempotencyService
    budget: BudgetService


def build_services(
    settings: Settings,
    db: Database,
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> Services:
    clock = clock or SystemClock()
    ids = ids or UuidIds()
    return Services(
        settings=settings,
        db=db,
        clock=clock,
        ids=ids,
        auth=AuthService(db, clock, ids),
        jobs=JobService(db, clock, ids),
        idempotency=IdempotencyService(db),
        budget=BudgetService(db, clock, ids, settings),
    )


def owner_or_operator_dependency(auth: AuthService) -> Dependency:
    """A human owner session or an operator (worker/scheduler) credential; anything else is 403.

    Runtime models and provider webhooks never read episode data through the API (AT-13).
    """
    authenticate = human_or_service_dependency(auth)

    async def owner_or_operator(request: Request) -> Principal:
        principal = await authenticate(request)
        require_principal_kind(
            principal, OWNER_OR_OPERATOR_KINDS, action="read episode data", error=PolicyDenied
        )
        return principal

    return owner_or_operator


def database_probe(db: Database):
    def probe() -> ComponentState:
        with db.transaction(readonly=True) as tx:
            tx.fetchval("SELECT 1")
        return ComponentState.OK

    return probe


def build_routers(services: Services) -> list[APIRouter]:
    auth = services.auth
    return [
        build_core_router(
            db=services.db,
            jobs=services.jobs,
            idempotency=services.idempotency,
            human_or_service=human_or_service_dependency(auth),
            service=service_dependency(auth),
        ),
        build_budget_router(services.budget, read_auth=owner_or_operator_dependency(auth)),
    ]


def build_components(
    services: Services, *, extra_routers: Sequence[APIRouter] = ()
) -> AppComponents:
    return AppComponents(
        settings=services.settings,
        routers=[*build_routers(services), *extra_routers],
        database_probe=database_probe(services.db),
    )


__all__ = [
    "Services",
    "build_components",
    "build_routers",
    "build_services",
    "database_probe",
    "owner_or_operator_dependency",
]

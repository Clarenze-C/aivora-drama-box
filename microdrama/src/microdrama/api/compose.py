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
from microdrama.contracts.infra import Clock, IdGenerator, ObjectStore
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import ComponentState
from microdrama.core.api import build_router as build_core_router
from microdrama.core.auth import OWNER_OR_OPERATOR_KINDS, AuthService, require_principal_kind
from microdrama.core.clock import SystemClock, UuidIds
from microdrama.core.hooks import ApprovalHook
from microdrama.core.http import (
    Dependency,
    human_or_service_dependency,
    human_session_dependency,
    service_dependency,
)
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.persistence.db import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.review import ReviewService, not_configured_release_conditions
from microdrama.review import build_router as build_review_router
from microdrama.review.gate_conditions import ReleaseConditionsFn

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
    store: ObjectStore | None = None
    review: ReviewService | None = None


def build_services(
    settings: Settings,
    db: Database,
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    store: ObjectStore | None = None,
    release_conditions_fn: ReleaseConditionsFn = not_configured_release_conditions,
    approval_hooks: Sequence[ApprovalHook] = (),
    identity_lock_hook: ApprovalHook | None = None,
) -> Services:
    """Construct every accepted service once.

    The review service exists only with an object store (it streams private media). Until the
    rights/capability conditions are wired (T029), the fail-closed default blocks every Gate 2
    APPROVE, and without an identity-lock hook (T011) every episode-one approval is refused.
    """
    clock = clock or SystemClock()
    ids = ids or UuidIds()
    if store is None and settings.object_store_root is not None:
        store = FilesystemObjectStore(settings.object_store_root)
    jobs = JobService(db, clock, ids)
    idempotency = IdempotencyService(db)
    budget = BudgetService(db, clock, ids, settings)
    review = None
    if store is not None:
        review = ReviewService(
            db,
            clock,
            ids,
            jobs=jobs,
            idempotency=idempotency,
            budget=budget,
            store=store,
            release_conditions_fn=release_conditions_fn,
            approval_hooks=approval_hooks,
            identity_lock_hook=identity_lock_hook,
        )
    return Services(
        settings=settings,
        db=db,
        clock=clock,
        ids=ids,
        auth=AuthService(db, clock, ids),
        jobs=jobs,
        idempotency=idempotency,
        budget=budget,
        store=store,
        review=review,
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


def object_store_probe(store: ObjectStore | None):
    if store is None:
        return None

    def probe() -> ComponentState:
        root = getattr(store, "root", None)
        if root is not None and not root.is_dir():
            return ComponentState.UNAVAILABLE
        return ComponentState.OK

    return probe


def build_routers(services: Services, *, cookie_secure: bool = True) -> list[APIRouter]:
    auth = services.auth
    routers = [
        build_core_router(
            db=services.db,
            jobs=services.jobs,
            idempotency=services.idempotency,
            human_or_service=human_or_service_dependency(auth),
            service=service_dependency(auth),
        ),
        build_budget_router(services.budget, read_auth=owner_or_operator_dependency(auth)),
    ]
    if services.review is not None:
        routers.append(
            build_review_router(
                services.review,
                human_session=human_session_dependency(auth),
                auth=auth,
                cookie_secure=cookie_secure,
            )
        )
    return routers


def build_components(
    services: Services,
    *,
    extra_routers: Sequence[APIRouter] = (),
    cookie_secure: bool = True,
) -> AppComponents:
    return AppComponents(
        settings=services.settings,
        routers=[*build_routers(services, cookie_secure=cookie_secure), *extra_routers],
        database_probe=database_probe(services.db),
        object_store_probe=object_store_probe(services.store),
    )


__all__ = [
    "Services",
    "build_components",
    "build_routers",
    "build_services",
    "database_probe",
    "object_store_probe",
    "owner_or_operator_dependency",
]

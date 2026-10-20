"""HTTP contract for the budget surface: GET /episodes/{episode_id}/costs.

Self-contained (no unit-test helpers): builds one episode with a fake settlement, an unreserved
fake accrual and one expired reservation, then drives the router through the real app.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from microdrama.api.app import AppComponents, create_app
from microdrama.budget import BudgetService, build_router
from microdrama.config import Settings
from microdrama.contracts.cost import BudgetReservationRequest, ExposureCeilings, UsageReceipt
from microdrama.contracts.enums import (
    BudgetCategory,
    BudgetScopeKind,
    CostBasis,
    ExecutionMode,
    PriceUnit,
    PrincipalKind,
    Provenance,
    QueueName,
    ReceiptKind,
)
from microdrama.contracts.errors import Unauthenticated
from microdrama.contracts.principals import Principal
from microdrama.contracts.routes import ROUTES, CostView
from microdrama.contracts.season import CostPolicy
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock, SequentialIds, fake_price_quote
from microdrama.testing.fakes.common import receipt_id_for
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

T0 = datetime(2026, 10, 20, tzinfo=UTC)
COSTS_PATH = "/episodes/{episode_id}/costs"


def _reader() -> Principal:
    return Principal(principal_id="reviewer-service", kind=PrincipalKind.SERVICE_WORKER)


def _refuse() -> Principal:
    raise Unauthenticated("no valid credential")


def _episode(db: Database, service: BudgetService) -> uuid.UUID:
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        service.open_episode_account(tx, season_id=season, episode_id=episode, policy=CostPolicy())
    return episode


def _reserve(service: BudgetService, episode: uuid.UUID, key: str, worst: int, expires: datetime):
    request = BudgetReservationRequest(
        request_id=uuid.uuid4(),
        semantic_key=key,
        scope_kind=BudgetScopeKind.EPISODE,
        episode_id=episode,
        category=BudgetCategory.GPU_GENERATION,
        queue=QueueName.PRODUCTION,
        provider="fake-runpod",
        operation_kind="gpu.render_shot",
        price=fake_price_quote(PriceUnit.GPU_SECOND),
        ceilings=ExposureCeilings(timeout_ms=600_000, max_units=1),
        worst_case_micro_usd=worst,
        expires_at=expires,
    )
    return service.reserve(request)


def _spent_episode(db: Database, service: BudgetService) -> uuid.UUID:
    """One settled reservation (300,000) plus one unreserved fake accrual (100,000)."""
    episode = _episode(db, service)
    reservation = _reserve(service, episode, "api.gpu.settled", 700_000, T0 + timedelta(hours=1))
    service.record_usage(
        _fake("api.settle", ReceiptKind.SETTLEMENT, 300_000, episode, reservation=reservation.id)
    )
    service.record_usage(_fake("api.unreserved", ReceiptKind.ACCRUAL, 100_000, episode))
    return episode


def _fake(key: str, kind: ReceiptKind, amount: int, episode, *, reservation=None) -> UsageReceipt:
    return UsageReceipt(
        receipt_id=receipt_id_for("fake-runpod", key),
        provider="fake-runpod",
        provider_receipt_id=key,
        kind=kind,
        cost_basis=CostBasis.SYNTHETIC_FAKE,
        reservation_id=reservation,
        episode_id=episode,
        category=BudgetCategory.GPU_GENERATION,
        amount_micro_usd=amount,
        units=1,
        unit=PriceUnit.GPU_SECOND,
        observed_at=T0,
        provenance=Provenance.FAKE_SYNTHETIC,
    )


@pytest.fixture
def service(db: Database) -> BudgetService:
    clock = FakeClock(T0)
    return BudgetService(
        db,
        clock,
        SequentialIds("api-contract"),
        Settings(execution_mode=ExecutionMode.OFFLINE_MOCK),
    )


def _client(service: BudgetService, read_auth) -> TestClient:
    router = build_router(service, read_auth=read_auth)
    return TestClient(create_app(AppComponents(settings=Settings(), routers=[router])))


def test_costs_route_serves_lines_synthetic_portion_and_unknowns(
    db: Database, service: BudgetService
) -> None:
    episode = _spent_episode(db, service)
    response = _client(service, _reader).get(COSTS_PATH.format(episode_id=episode))
    assert response.status_code == 200, response.text
    view = CostView.model_validate(response.json())
    assert view.episode_id == episode
    assert view.summary.synthetic_fake_micro_usd == 400_000  # every receipt here is synthetic
    assert view.summary.settled_micro_usd == 400_000
    assert {line.kind for line in view.lines} == {"settlement", "accrual"}
    assert view.overruns == []
    assert view.unknowns == []  # the open reservation is not past its expiry yet


def test_unknown_reservations_are_listed_not_hidden(db: Database) -> None:
    clock = FakeClock(T0)
    service = BudgetService(
        db,
        clock,
        SequentialIds("api-unknowns"),
        Settings(execution_mode=ExecutionMode.OFFLINE_MOCK),
    )
    episode = _spent_episode(db, service)
    _reserve(service, episode, "api.gpu.open", 200_000, T0 + timedelta(hours=1))
    clock.advance(seconds=7200)
    assert service.expire_stale() == 1
    body = _client(service, _reader).get(COSTS_PATH.format(episode_id=episode)).json()
    assert len(body["unknowns"]) == 1
    assert "expired unsettled" in body["unknowns"][0]
    assert body["summary"]["accrued_micro_usd"] == 200_000  # worst case kept as spent


def test_costs_route_refuses_unauthenticated_callers(db: Database, service: BudgetService) -> None:
    episode = _episode(db, service)
    response = _client(service, _refuse).get(COSTS_PATH.format(episode_id=episode))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_costs_route_for_an_unknown_episode_is_not_found(
    db: Database, service: BudgetService
) -> None:
    response = _client(service, _reader).get(COSTS_PATH.format(episode_id=uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_router_registers_exactly_the_contract_route(service: BudgetService) -> None:
    router = build_router(service, read_auth=_reader)
    paths = {(route.path, frozenset(route.methods)) for route in router.routes}
    assert (COSTS_PATH, frozenset({"GET"})) in paths
    contract = [spec for spec in ROUTES if spec.path == COSTS_PATH]
    assert len(contract) == 1 and contract[0].method == "GET"
    assert contract[0].response_model is CostView

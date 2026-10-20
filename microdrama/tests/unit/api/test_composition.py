"""The composition root registers every accepted module router behind real authentication."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from microdrama.api.app import create_app
from microdrama.api.compose import build_components, build_services
from microdrama.config import Settings
from microdrama.contracts.enums import PrincipalKind, RuntimeRole
from microdrama.contracts.routes import ROUTES
from microdrama.contracts.season import CostPolicy
from microdrama.core.http import SESSION_COOKIE
from microdrama.persistence import Database
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

PASSWORD = "correct horse battery"


@pytest.fixture
def wired(db: Database):
    services = build_services(Settings(), db)
    client = TestClient(create_app(build_components(services)), raise_server_exceptions=False)
    with db.transaction() as tx:
        season_id = seed_season(tx)
        episode_id = seed_episode(tx, season_id)
        services.budget.open_episode_account(
            tx, season_id=season_id, episode_id=episode_id, policy=CostPolicy()
        )
    services.auth.create_owner("owner", PASSWORD)
    return services, client, episode_id


def _registered(client: TestClient) -> set[tuple[str, str]]:
    # FastAPI wraps each included router (no prefix is used), so walk into the originals.
    found: set[tuple[str, str]] = set()
    pending = list(client.app.routes)
    while pending:
        route = pending.pop()
        if hasattr(route, "original_router"):
            pending.extend(route.original_router.routes)
            continue
        found.update((method, route.path) for method in getattr(route, "methods", ()) or ())
    return found


def test_core_and_budget_routes_are_registered_as_the_contract_names_them(wired) -> None:
    _, client, _ = wired
    registered = _registered(client)
    expected = {
        (spec.method, spec.path)
        for spec in ROUTES
        if spec.path in {"/episodes/{episode_id}/events", "/episodes/{episode_id}/costs"}
        or spec.path.startswith("/internal/jobs")
    }
    assert len(expected) == 4
    assert expected <= registered


def test_ready_reports_the_database(wired) -> None:
    _, client, _ = wired
    assert client.get("/ready").json()["database"] == "OK"


def test_costs_need_an_owner_session_or_an_operator(wired) -> None:
    services, client, episode_id = wired
    path = f"/episodes/{episode_id}/costs"
    assert client.get(path).status_code == 401

    session = services.auth.login("owner", PASSWORD)
    client.cookies.set(SESSION_COOKIE, session.session_token)
    owner = client.get(path)
    client.cookies.clear()
    assert owner.status_code == 200
    assert owner.json()["summary"]["episode_cap_micro_usd"] == 10_000_000

    worker = services.auth.issue_service_credential("worker-1", PrincipalKind.SERVICE_WORKER)
    headers = {"Authorization": f"Bearer {worker}"}
    assert client.get(path, headers=headers).status_code == 200


@pytest.mark.parametrize(
    ("kind", "role"),
    [(PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC), (PrincipalKind.PROVIDER_WEBHOOK, None)],
)
def test_models_and_webhooks_cannot_read_costs(wired, kind, role) -> None:
    services, client, episode_id = wired
    token = services.auth.issue_service_credential(
        f"{kind.value.lower()}-1", kind, runtime_role=role
    )
    response = client.get(
        f"/episodes/{episode_id}/costs", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "POLICY_DENIED"
    assert "summary" not in response.json()

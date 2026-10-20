"""Composition-root behaviour: health/ready and the contract error → HTTP mapping."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from microdrama.api.app import AppComponents, create_app
from microdrama.config import Settings
from microdrama.contracts import errors as e
from microdrama.contracts.routes import ComponentState
from microdrama.contracts.season import ApprovalCommand


def _client(**kwargs) -> TestClient:
    return TestClient(
        create_app(AppComponents(settings=Settings(), **kwargs)), raise_server_exceptions=False
    )


def test_health_has_no_secrets_and_reports_mode() -> None:
    body = _client().get("/health").json()
    assert body == {"status": "ok", "version": body["version"], "execution_mode": "OFFLINE_MOCK"}


def test_ready_distinguishes_components() -> None:
    r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["database"] == "NOT_CONFIGURED"

    def boom() -> ComponentState:
        raise RuntimeError("db down")

    ok = lambda: ComponentState.OK  # noqa: E731
    r = _client(database_probe=boom, queue_probe=ok, object_store_probe=ok).get("/ready")
    assert (
        r.status_code == 503 and r.json()["database"] == "UNAVAILABLE" and r.json()["queue"] == "OK"
    )
    r = _client(database_probe=ok, queue_probe=ok, object_store_probe=ok).get("/ready")
    assert r.status_code == 200 and r.json()["ready"] is True


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (e.StaleRevision("stale"), 409, "STALE_REVISION"),
        (e.IdempotencyConflict("reuse"), 409, "IDEMPOTENCY_CONFLICT"),
        (e.Unauthorized("no"), 403, "UNAUTHORIZED"),
        (e.Unauthenticated("who"), 401, "UNAUTHENTICATED"),
        (e.EffectDenied("mock"), 403, "EFFECT_DENIED"),
        (e.BudgetExhausted("cap"), 409, "BUDGET_EXHAUSTED"),
        (e.NotFound("x"), 404, "NOT_FOUND"),
    ],
)
def test_contract_errors_map_to_spec_statuses(
    exc: e.MicrodramaError, status: int, code: str
) -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise exc

    r = _client(routers=[router]).get("/boom")
    assert r.status_code == status
    assert r.json()["code"] == code


def test_schema_errors_are_422_and_do_not_echo_input() -> None:
    router = APIRouter()

    @router.post("/cmd")
    def cmd(command: ApprovalCommand) -> dict:
        return {}

    r = _client(routers=[router]).post(
        "/cmd", json={"gate": "SEASON_CONCEPT", "secret_token": "s3cr3t"}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "SCHEMA_INVALID"
    assert "s3cr3t" not in r.text


def test_model_validation_inside_handler_is_422() -> None:
    class M(BaseModel):
        n: int

    router = APIRouter()

    @router.get("/inner")
    def inner() -> None:
        M.model_validate({"n": "not-int"})

    assert _client(routers=[router]).get("/inner").status_code == 422

"""Core HTTP surface through the integrator's app (create_app): status codes and auth channels."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import pytest
from core_support import WORKER, fresh_episode, gate2, make_human, ready_package
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import EpisodeState, PrincipalKind, RuntimeRole
from microdrama.contracts.principals import Principal
from microdrama.core.api import build_router
from microdrama.core.approvals import record_approval_event
from microdrama.core.auth import AuthService
from microdrama.core.http import (
    human_or_service_dependency,
    human_session_dependency,
    service_dependency,
)
from microdrama.core.idempotency import IdempotencyService
from microdrama.core.jobs import JobService
from microdrama.core.state_machine import transition_episode
from microdrama.persistence import Database
from microdrama.testing.fakes import FakeClock
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db
PASSWORD = "a-long-review-password"


@pytest.fixture
def stack(db: Database, clock: FakeClock, ids, offline_settings):
    auth = AuthService(db, clock, ids)
    jobs = JobService(db, clock, ids)
    idempotency = IdempotencyService(db)
    router = build_router(
        db=db,
        jobs=jobs,
        idempotency=idempotency,
        human_or_service=human_or_service_dependency(auth),
        service=service_dependency(auth),
    )
    app = create_app(AppComponents(settings=offline_settings, routers=[router]))
    client = TestClient(app)
    return {"client": client, "auth": auth, "db": db, "jobs": jobs, "settings": offline_settings}


def _service(
    auth: AuthService, principal_id: str, kind: PrincipalKind, role=None
) -> dict[str, str]:
    token = auth.issue_service_credential(principal_id, kind, runtime_role=role)
    return {"Authorization": f"Bearer {token}"}


def _worker(auth) -> dict[str, str]:
    """A fresh worker credential (principal ids are unique, so each call gets its own)."""
    return _service(auth, f"worker:{uuid.uuid4().hex[:12]}", PrincipalKind.SERVICE_WORKER)


def _job_body(
    *,
    key="idem-key-0001",
    semantic="qa:ep:cycle1",
    episode=None,
    job_type="qa.technical",
    payload=None,
) -> dict:
    return {
        "schema_version": "1.0",
        "job_type": job_type,
        "semantic_key": semantic,
        "input": payload if payload is not None else {"episode_id": str(episode or uuid.uuid4())},
        "idempotency_key": key,
    }


def test_enqueue_is_202_then_replayed_as_200_with_the_same_job(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    worker = _worker(auth)
    episode = uuid.uuid4()
    body = _job_body(key="idem-replay-01", episode=episode)
    first = client.post("/internal/jobs", json=body, headers=worker)
    assert first.status_code == 202
    assert first.json()["status"] == "QUEUED"
    job_id = first.json()["job_id"]
    again = client.post("/internal/jobs", json=body, headers=worker)
    assert again.status_code == 200
    assert again.json()["status"] == "REPLAYED" and again.json()["job_id"] == job_id


def test_same_key_with_different_content_is_409(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    client.post(
        "/internal/jobs",
        json=_job_body(key="idem-conflict-1", semantic="a:1"),
        headers=_worker(auth),
    )
    response = client.post(
        "/internal/jobs",
        json=_job_body(key="idem-conflict-1", semantic="a:2"),
        headers=_worker(auth),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_a_new_key_for_an_identical_semantic_command_is_a_replay_not_a_second_job(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    episode = uuid.uuid4()
    first = client.post(
        "/internal/jobs",
        json=_job_body(key="idem-sem-0001", semantic="qa:same", episode=episode),
        headers=_worker(auth),
    )
    second = client.post(
        "/internal/jobs",
        json=_job_body(key="idem-sem-0002", semantic="qa:same", episode=episode),
        headers=_worker(auth),
    )
    assert first.status_code == 202
    assert second.status_code == 200 and second.json()["status"] == "REPLAYED"
    assert second.json()["job_id"] == first.json()["job_id"]


def test_same_semantic_key_with_different_input_is_409(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    client.post(
        "/internal/jobs",
        json=_job_body(key="idem-sem-1001", semantic="qa:clash", episode=uuid.uuid4()),
        headers=_worker(auth),
    )
    response = client.post(
        "/internal/jobs",
        json=_job_body(key="idem-sem-1002", semantic="qa:clash", episode=uuid.uuid4()),
        headers=_worker(auth),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "bad_body",
    [
        {"job_type": "no.such.job", "payload": None},
        {"job_type": "qa.technical", "payload": {"episode_id": "not-a-uuid"}},
        {"job_type": "qa.technical", "payload": {"episode_id": str(uuid.uuid4()), "unexpected": 1}},
        {"job_type": "qa.technical", "payload": {}},
    ],
)
def test_invalid_jobs_are_422_schema_invalid(stack, bad_body) -> None:
    client, auth = stack["client"], stack["auth"]
    body = _job_body(job_type=bad_body["job_type"], payload=bad_body["payload"])
    response = client.post("/internal/jobs", json=body, headers=_worker(auth))
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


def test_envelope_episode_must_match_the_job_input(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    worker = _worker(auth)
    episode = uuid.uuid4()
    body = _job_body(key="idem-episode-01", payload={"episode_id": str(episode)})
    body["episode_id"] = str(uuid.uuid4())
    assert client.post("/internal/jobs", json=body, headers=worker).status_code == 422
    body["episode_id"] = str(episode)
    assert client.post("/internal/jobs", json=body, headers=worker).status_code == 202


def test_malformed_envelope_is_422(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    body = _job_body()
    body["surprise"] = True  # closed schema: unknown fields are refused
    assert client.post("/internal/jobs", json=body, headers=_worker(auth)).status_code == 422
    short_key = _job_body(key="short")
    assert client.post("/internal/jobs", json=short_key, headers=_worker(auth)).status_code == 422


def test_anonymous_and_forged_callers_are_401(stack) -> None:
    client = stack["client"]
    body = _job_body()
    assert client.post("/internal/jobs", json=body).status_code == 401
    assert (
        client.post(
            "/internal/jobs", json=body, headers={"Authorization": "Bearer forged"}
        ).status_code
        == 401
    )
    assert (
        client.post("/internal/jobs", json=body, headers={"Authorization": "Basic abc"}).status_code
        == 401
    )


def test_a_human_session_cookie_cannot_call_the_internal_routes(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    auth.create_owner("reviewer.api", PASSWORD)
    tokens = auth.login("reviewer.api", PASSWORD)
    client.cookies.set("md_session", tokens.session_token)
    assert client.post("/internal/jobs", json=_job_body()).status_code == 401
    job = client.post(
        "/internal/jobs",
        json=_job_body(key="idem-human-01"),
        headers={"X-CSRF-Token": tokens.csrf_token},
    )
    assert job.status_code == 401
    client.cookies.clear()


@pytest.mark.parametrize(
    "principal_id, kind, role",
    [
        ("model:critic-01", PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC),
        ("webhook:provider-a", PrincipalKind.PROVIDER_WEBHOOK, None),
    ],
)
def test_models_and_webhooks_may_not_enqueue_directly(stack, principal_id, kind, role) -> None:
    client, auth = stack["client"], stack["auth"]
    response = client.post(
        "/internal/jobs", json=_job_body(), headers=_service(auth, principal_id, kind, role)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "POLICY_DENIED"


def test_a_scheduler_may_enqueue(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    response = client.post(
        "/internal/jobs",
        json=_job_body(
            key="idem-sched-001",
            job_type="analytics.qualification",
            payload={"season_id": str(uuid.uuid4())},
        ),
        headers=_service(auth, "scheduler:cron-01", PrincipalKind.SCHEDULER),
    )
    assert response.status_code == 202


def test_job_status_is_readable_by_a_service_and_404s_for_unknown_ids(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    worker = _worker(auth)
    created = client.post("/internal/jobs", json=_job_body(key="idem-status-1"), headers=worker)
    job_id = created.json()["job_id"]
    status = client.get(f"/internal/jobs/{job_id}", headers=worker)
    assert status.status_code == 200
    view = status.json()
    assert (
        view["status"] == "QUEUED" and view["job_type"] == "qa.technical" and view["attempt"] == 0
    )
    assert view["queue"] == "production"
    assert client.get(f"/internal/jobs/{uuid.uuid4()}", headers=worker).status_code == 404
    assert client.get(f"/internal/jobs/{job_id}").status_code == 401


def _episode_with_history(stack) -> uuid.UUID:
    """An episode with one recorded state change (AI_REVIEW -> RENDERING by the worker)."""
    db = stack["db"]
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season, state=EpisodeState.AI_REVIEW.value)
    with db.transaction() as tx:
        transition_episode(
            tx,
            episode_id=episode,
            to=EpisodeState.RENDERING,
            expected_revision=0,
            actor=WORKER,
            now=datetime.now(UTC),
            correlation_id=uuid.uuid4(),
        )
    return episode


def test_episode_events_lists_the_outbox_for_that_episode(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    episode = _episode_with_history(stack)
    response = client.get(f"/episodes/{episode}/events", headers=_worker(auth))
    assert response.status_code == 200
    body = response.json()
    assert body["aggregate_id"] == str(episode)
    assert [e["event_type"] for e in body["events"]] == ["episode.state_changed"]
    assert body["events"][0]["sequence"] == 1
    assert body["events"][0]["payload"]["to"] == "RENDERING"


def test_episode_events_accepts_a_human_session_and_refuses_anonymous(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    episode = _episode_with_history(stack)
    assert client.get(f"/episodes/{episode}/events").status_code == 401
    auth.create_owner("reviewer.events", PASSWORD)
    tokens = auth.login("reviewer.events", PASSWORD)
    client.cookies.set("md_session", tokens.session_token)
    assert client.get(f"/episodes/{episode}/events").status_code == 200
    client.cookies.clear()


def test_episode_events_for_an_unknown_episode_is_404(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    assert client.get(f"/episodes/{uuid.uuid4()}/events", headers=_worker(auth)).status_code == 404


# --- human session channel: cookie + CSRF on unsafe methods ------------------------------


@pytest.fixture
def csrf_client(stack):
    """A throwaway review route that uses the production human-session dependency."""
    auth = stack["auth"]
    dependency = human_session_dependency(auth)
    router = APIRouter()

    @router.get("/probe/read")
    def read(principal: Annotated[Principal, Depends(dependency)]):
        return {"principal": principal.principal_id}

    @router.post("/probe/write")
    def write(principal: Annotated[Principal, Depends(dependency)]):
        return {"wrote": True, "by": principal.principal_id}

    app: FastAPI = create_app(AppComponents(settings=stack["settings"], routers=[router]))
    auth.create_owner("reviewer.csrf", PASSWORD)
    tokens = auth.login("reviewer.csrf", PASSWORD)
    client = TestClient(app)
    client.cookies.set("md_session", tokens.session_token)
    return client, tokens


def test_csrf_is_required_on_unsafe_methods_and_not_on_reads(stack, csrf_client) -> None:
    client, tokens = csrf_client
    assert client.get("/probe/read").status_code == 200
    assert client.post("/probe/write").status_code == 403  # no CSRF token
    assert client.post("/probe/write", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert (
        client.post("/probe/write", headers={"X-CSRF-Token": tokens.session_token}).status_code
        == 403
    )
    ok = client.post("/probe/write", headers={"X-CSRF-Token": tokens.csrf_token})
    assert ok.status_code == 200 and ok.json()["wrote"] is True


def test_csrf_form_field_is_accepted_on_form_posts(stack, csrf_client) -> None:
    client, tokens = csrf_client
    response = client.post(
        "/probe/write",
        data={"csrf_token": tokens.csrf_token},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    wrong = client.post(
        "/probe/write",
        data={"csrf_token": "nope"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert wrong.status_code == 403


def test_no_cookie_is_401_and_a_service_token_is_never_a_human(stack, csrf_client) -> None:
    client, tokens = csrf_client
    auth = stack["auth"]
    client.cookies.clear()
    assert client.get("/probe/read").status_code == 401
    assert (
        client.post("/probe/write", headers={"X-CSRF-Token": tokens.csrf_token}).status_code == 401
    )
    token = auth.issue_service_credential("worker:bridge", PrincipalKind.SERVICE_WORKER)
    assert (
        client.get("/probe/read", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_a_bad_bearer_header_is_refused_even_with_a_valid_cookie(stack) -> None:
    """human_or_service never silently falls back to the cookie when a bearer header is present."""
    client, auth = stack["client"], stack["auth"]
    auth.create_owner("reviewer.mixed", PASSWORD)
    tokens = auth.login("reviewer.mixed", PASSWORD)
    client.cookies.set("md_session", tokens.session_token)
    response = client.get(
        f"/episodes/{uuid.uuid4()}/events", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401
    client.cookies.clear()


# --- F-2: read scope. Models and webhooks get 403 POLICY_DENIED; operators and owners pass. ---

MODEL_AND_WEBHOOK = pytest.mark.parametrize(
    "kind, role",
    [(PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC), (PrincipalKind.PROVIDER_WEBHOOK, None)],
    ids=["model", "webhook"],
)


def _episode_with_gate2_decision(stack) -> tuple[uuid.UUID, str]:
    """An AWAITING_FINAL_REVIEW episode with a real Gate 2 APPROVE in its outbox."""
    db = stack["db"]
    with db.transaction() as tx:
        episode = fresh_episode(tx)
        package, package_hash = ready_package(tx, episode, tag="api-read")
        human = make_human(tx)
        revision = tx.fetchval("SELECT revision FROM episodes WHERE id = %s", (episode,))
    with db.transaction() as tx:
        record_approval_event(
            tx,
            principal=human,
            command=gate2(episode, package_hash, revision=revision),
            now=datetime.now(UTC),
            correlation_id=uuid.uuid4(),
        )
    return episode, package_hash


@MODEL_AND_WEBHOOK
def test_models_and_webhooks_cannot_read_the_episode_outbox(stack, kind, role) -> None:
    client, auth = stack["client"], stack["auth"]
    episode, package_hash = _episode_with_gate2_decision(stack)
    headers = _service(auth, f"probe:{uuid.uuid4().hex[:10]}", kind, role)
    response = client.get(f"/episodes/{episode}/events", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "POLICY_DENIED"
    assert "events" not in response.json()
    assert "approval.recorded" not in response.text and package_hash not in response.text


@pytest.mark.parametrize(
    "kind, role",
    [(PrincipalKind.SERVICE_WORKER, None), (PrincipalKind.SCHEDULER, None)],
    ids=["worker", "scheduler"],
)
def test_operators_can_read_the_episode_outbox(stack, kind, role) -> None:
    client, auth = stack["client"], stack["auth"]
    episode, _ = _episode_with_gate2_decision(stack)
    response = client.get(
        f"/episodes/{episode}/events",
        headers=_service(auth, f"op:{uuid.uuid4().hex[:10]}", kind, role),
    )
    assert response.status_code == 200
    assert [e["event_type"] for e in response.json()["events"]] == ["approval.recorded"]


def test_a_human_owner_session_can_read_the_episode_outbox(stack) -> None:
    client, auth = stack["client"], stack["auth"]
    episode, _ = _episode_with_gate2_decision(stack)
    auth.create_owner("reviewer.outbox", PASSWORD)
    tokens = auth.login("reviewer.outbox", PASSWORD)
    client.cookies.set("md_session", tokens.session_token)
    response = client.get(f"/episodes/{episode}/events")
    client.cookies.clear()
    assert response.status_code == 200


@MODEL_AND_WEBHOOK
def test_models_and_webhooks_cannot_read_job_status(stack, kind, role) -> None:
    client, auth = stack["client"], stack["auth"]
    created = client.post(
        "/internal/jobs", json=_job_body(key="idem-readscope-1"), headers=_worker(auth)
    )
    job_id = created.json()["job_id"]
    response = client.get(
        f"/internal/jobs/{job_id}",
        headers=_service(auth, f"probe:{uuid.uuid4().hex[:10]}", kind, role),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "POLICY_DENIED"
    assert job_id not in response.text


@pytest.mark.parametrize(
    "kind, role",
    [(PrincipalKind.SERVICE_WORKER, None), (PrincipalKind.SCHEDULER, None)],
    ids=["worker", "scheduler"],
)
def test_operators_can_read_job_status(stack, kind, role) -> None:
    client, auth = stack["client"], stack["auth"]
    created = client.post(
        "/internal/jobs", json=_job_body(key=f"idem-op-{kind.value[:4]}"), headers=_worker(auth)
    )
    job_id = created.json()["job_id"]
    response = client.get(
        f"/internal/jobs/{job_id}",
        headers=_service(auth, f"op:{uuid.uuid4().hex[:10]}", kind, role),
    )
    assert response.status_code == 200 and response.json()["job_id"] == job_id


def test_a_human_session_cannot_read_job_status_because_internal_routes_are_service_only(
    stack,
) -> None:
    client, auth = stack["client"], stack["auth"]
    worker = _worker(auth)
    job_id = client.post(
        "/internal/jobs", json=_job_body(key="idem-human-read"), headers=worker
    ).json()["job_id"]
    auth.create_owner("reviewer.jobstatus", PASSWORD)
    tokens = auth.login("reviewer.jobstatus", PASSWORD)
    client.cookies.set("md_session", tokens.session_token)
    response = client.get(f"/internal/jobs/{job_id}")
    client.cookies.clear()
    assert response.status_code == 401

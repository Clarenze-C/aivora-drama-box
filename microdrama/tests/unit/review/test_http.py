"""JSON gate routes through the composed app: auth channels, CSRF, status codes and replays."""

import uuid

import pytest
from fastapi.testclient import TestClient
from review_support import World

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import (
    ApprovalAction,
    CoverageStatus,
    FeedbackCategory,
    PrincipalKind,
    QAOutcome,
    RuntimeRole,
    Severity,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.season import ApprovalCommand, TimecodedFeedback
from microdrama.core.http import human_session_dependency
from microdrama.review import build_router

pytestmark = pytest.mark.db
PASSWORD = "a-long-review-password"


@pytest.fixture
def api(world: World, offline_settings):
    """A client for the review router, with a live owner session and its CSRF token."""
    world.auth.create_owner("review.owner", PASSWORD)
    tokens = world.auth.login("review.owner", PASSWORD)
    router = build_router(
        world.service,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
    )
    app = create_app(AppComponents(settings=offline_settings, routers=[router]))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("md_session", tokens.session_token)
    return client, tokens.csrf_token, router


def _bearer(world: World, kind: PrincipalKind, role: RuntimeRole | None = None) -> dict[str, str]:
    token = world.auth.issue_service_credential(
        f"{kind.value.lower()}:{uuid.uuid4().hex[:10]}", kind, runtime_role=role
    )
    return {"Authorization": f"Bearer {token}"}


def _body(command: ApprovalCommand) -> dict:
    return command.model_dump(mode="json")


def test_the_router_exposes_exactly_the_review_routes(api) -> None:
    _client, _csrf, router = api
    surface = {(method, route.path) for route in router.routes for method in route.methods}
    assert ("GET", "/seasons/proposals") in surface
    assert ("GET", "/seasons/{season_id}") in surface
    assert ("POST", "/seasons/{season_id}/approval") in surface
    assert ("GET", "/episodes/{episode_id}/review") in surface
    assert ("POST", "/episodes/{episode_id}/review") in surface
    for method, path in surface:
        assert path.startswith(("/seasons", "/episodes", "/ui", "/auth")), (method, path)


def test_reads_need_a_human_session(api, world: World) -> None:
    client, _csrf, _ = api
    client.cookies.clear()
    response = client.get("/seasons/proposals")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_season_proposals_route_is_not_swallowed_by_the_season_id_route(api, world: World) -> None:
    client, _csrf, _ = api
    world.season(approved=False)
    response = client.get("/seasons/proposals")
    assert response.status_code == 200
    assert isinstance(response.json(), list) and response.json()[0]["state"] == "PROPOSED"


def test_season_view_is_returned_for_the_owner(api, world: World) -> None:
    client, _csrf, _ = api
    season_id, scope = world.season(approved=False)
    response = client.get(f"/seasons/{season_id}")
    assert response.status_code == 200
    assert response.json()["scope"]["title_en"] == scope.title_en


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        (PrincipalKind.SERVICE_WORKER, None),
        (PrincipalKind.SCHEDULER, None),
        (PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC),
        (PrincipalKind.PROVIDER_WEBHOOK, None),
    ],
)
def test_service_and_model_credentials_are_refused_with_403_on_every_gate_route(
    api, world: World, kind, role
) -> None:
    client, csrf, _ = api
    headers = {**_bearer(world, kind, role), "X-CSRF-Token": csrf}
    season_id, scope = world.season(approved=False)
    _s, episode_id, package = world.ready_episode()
    before = world.count("SELECT COUNT(*) FROM approval_events")

    assert client.get("/seasons/proposals", headers=headers).status_code == 403
    assert client.get(f"/seasons/{season_id}", headers=headers).status_code == 403
    assert client.get(f"/episodes/{episode_id}/review", headers=headers).status_code == 403
    gate1 = world.gate1_command(season_id, canonical_hash(scope), 0)
    assert (
        client.post(
            f"/seasons/{season_id}/approval", json=_body(gate1), headers=headers
        ).status_code
        == 403
    )
    gate2 = world.gate2_command(episode_id, package)
    response = client.post(f"/episodes/{episode_id}/review", json=_body(gate2), headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "UNAUTHORIZED"
    assert world.count("SELECT COUNT(*) FROM approval_events") == before


def test_an_invalid_bearer_credential_is_401_not_403(api, world: World) -> None:
    client, _csrf, _ = api
    response = client.get(
        "/seasons/proposals", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_gate1_approve_is_202_then_replayed_as_200(api, world: World) -> None:
    client, csrf, _ = api
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    headers = {"X-CSRF-Token": csrf}

    first = client.post(f"/seasons/{season_id}/approval", json=_body(command), headers=headers)
    assert first.status_code == 202
    assert first.json()["status"] == "QUEUED"

    replay = client.post(f"/seasons/{season_id}/approval", json=_body(command), headers=headers)
    assert replay.status_code == 200
    assert replay.json()["status"] == "REPLAYED"
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert len(world.jobs_of("story.compile_season")) == 1


def test_gate1_post_needs_the_csrf_token(api, world: World) -> None:
    client, csrf, _ = api
    season_id, scope = world.season(approved=False)
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    assert client.post(f"/seasons/{season_id}/approval", json=_body(command)).status_code == 403
    wrong = client.post(
        f"/seasons/{season_id}/approval",
        json=_body(command),
        headers={"X-CSRF-Token": "forged-token"},
    )
    assert wrong.status_code == 403
    assert world.approvals(season_id) == []


def test_gate1_revise_is_refused_as_422(api, world: World) -> None:
    client, csrf, _ = api
    season_id, scope = world.season(approved=False)
    body = {
        "schema_version": "1.0",
        "gate": "SEASON_CONCEPT",
        "action": "REVISE",
        "entity_id": str(season_id),
        "expected_revision": 0,
        "package_hash": canonical_hash(scope),
        "idempotency_key": "gate1-revise-http-0001",
        "feedback": [{"category": "pacing", "start_ms": 0, "end_ms": 1, "comment": "x"}],
    }
    response = client.post(
        f"/seasons/{season_id}/approval", json=body, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


def test_gate1_stale_and_scope_mismatch_are_409(api, world: World) -> None:
    client, csrf, _ = api
    season_id, scope = world.season(approved=False)
    headers = {"X-CSRF-Token": csrf}
    stale = world.gate1_command(season_id, canonical_hash(scope), 4)
    assert (
        client.post(
            f"/seasons/{season_id}/approval", json=_body(stale), headers=headers
        ).status_code
        == 409
    )
    mismatch = world.gate1_command(season_id, "7" * 64, 0)
    response = client.post(f"/seasons/{season_id}/approval", json=_body(mismatch), headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "STALE_REVISION"


def test_a_malformed_identifier_in_the_path_is_422(api) -> None:
    client, csrf, _ = api
    response = client.get("/episodes/not-a-uuid/review")
    assert response.status_code == 422


def test_gate2_approve_over_http_then_replay_then_stale(api, world: World) -> None:
    client, csrf, _ = api
    _s, episode_id, package = world.ready_episode()
    command = world.gate2_command(episode_id, package)
    headers = {"X-CSRF-Token": csrf}

    first = client.post(f"/episodes/{episode_id}/review", json=_body(command), headers=headers)
    assert first.status_code == 202
    assert first.json()["status"] == "QUEUED"
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"

    replay = client.post(f"/episodes/{episode_id}/review", json=_body(command), headers=headers)
    assert replay.status_code == 200 and replay.json()["status"] == "REPLAYED"

    fresh = world.gate2_command(episode_id, package, revision=0)
    stale = client.post(f"/episodes/{episode_id}/review", json=_body(fresh), headers=headers)
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_REVISION"
    assert len(world.approvals(episode_id)) == 1


def test_a_blocked_gate2_approve_is_409_with_the_blockers(api, world: World) -> None:
    client, csrf, _ = api
    _s, episode_id, package = world.ready_episode()
    world.qa_finding(episode_id, severity=Severity.CRITICAL)
    response = client.post(
        f"/episodes/{episode_id}/review",
        json=_body(world.gate2_command(episode_id, package)),
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "GATE_NOT_READY"
    assert any("open CRITICAL" in blocker for blocker in body["details"]["blockers"])


def test_gate2_revise_over_http_needs_timecoded_feedback(api, world: World) -> None:
    client, csrf, _ = api
    _s, episode_id, package = world.ready_episode()
    headers = {"X-CSRF-Token": csrf}
    no_feedback = world.gate2_command(episode_id, package, ApprovalAction.REVISE)
    body = _body(no_feedback)
    body["feedback"] = []
    assert (
        client.post(f"/episodes/{episode_id}/review", json=body, headers=headers).status_code == 422
    )

    revise = world.gate2_command(
        episode_id,
        package,
        ApprovalAction.REVISE,
        feedback=[
            TimecodedFeedback(
                category=FeedbackCategory.SUBTITLES,
                start_ms=12_000,
                end_ms=15_500,
                comment="5,000 vs 50,000 baht",
            )
        ],
    )
    response = client.post(f"/episodes/{episode_id}/review", json=_body(revise), headers=headers)
    assert response.status_code == 202
    assert world.episode_state(episode_id)[0] == "ASSEMBLING"


def test_episode_review_json_lists_unknowns_and_the_gate(api, world: World) -> None:
    client, _csrf, _ = api
    season_id, episode_id, package = world.ready_episode()
    master_id = package.media[0].asset_id
    observation = world.observation(
        episode_id, asset_id=master_id, asset_sha=package.media[0].sha256
    )
    assert observation is not None
    response = client.get(f"/episodes/{episode_id}/review")
    assert response.status_code == 200
    body = response.json()
    assert body["gate_enabled"] is True
    assert body["gate_blockers"] == []
    assert body["coverage"][0]["status"] == "UNSAMPLED"
    assert body["package"]["package_hash"] == package.package_hash
    assert all(link["review_path"].startswith("/ui/media/") for link in body["media"])
    assert "https://" not in response.text and "http://" not in response.text
    assert body["management_policy"]["allowed_actions"]


def test_episode_review_json_reports_the_cost_or_unknown(api, world: World) -> None:
    client, _csrf, _ = api
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode(season_id)  # no budget account: cost is unknown, not zero
    response = client.get(f"/episodes/{episode_id}/review")
    assert response.status_code == 200
    assert response.json()["cost"] is None
    assert response.json()["gate_blockers"][0] == "no release package is prepared for this episode"


def test_a_decision_request_must_name_the_route_entity(api, world: World) -> None:
    client, csrf, _ = api
    _s, episode_id, package = world.ready_episode()
    other = world.gate2_command(episode_id, package, entity_id=uuid.uuid4())
    response = client.post(
        f"/episodes/{episode_id}/review", json=_body(other), headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        (PrincipalKind.SERVICE_WORKER, None),
        (PrincipalKind.SCHEDULER, None),
        (PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC),
        (PrincipalKind.PROVIDER_WEBHOOK, None),
    ],
)
def test_a_non_human_with_an_invalid_body_is_403_not_422(api, world: World, kind, role) -> None:
    """The principal is refused before the body is validated (V-29)."""
    client, csrf, _ = api
    headers = {**_bearer(world, kind, role), "X-CSRF-Token": csrf}
    season_id, _scope = world.season(approved=False)
    _s, episode_id, _package = world.ready_episode()
    for path in (f"/seasons/{season_id}/approval", f"/episodes/{episode_id}/review"):
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["code"] == "UNAUTHORIZED"
        assert response.json()["code"] != "SCHEMA_INVALID"
    assert world.approvals(episode_id) == []


def test_a_request_without_a_session_is_401_even_with_an_invalid_body(api, world: World) -> None:
    client, _csrf, _ = api
    client.cookies.clear()
    season_id, _scope = world.season(approved=False)
    response = client.post(f"/seasons/{season_id}/approval", json={})
    assert response.status_code == 401


def test_a_human_with_an_invalid_body_still_gets_422(api, world: World) -> None:
    client, csrf, _ = api
    season_id, _scope = world.season(approved=False)
    response = client.post(
        f"/seasons/{season_id}/approval", json={}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


# --- the bearer refusal happens before the body is read (V-37) ------------------------------


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        (PrincipalKind.SERVICE_WORKER, None),
        (PrincipalKind.SCHEDULER, None),
        (PrincipalKind.RUNTIME_MODEL, RuntimeRole.CRITIC),
        (PrincipalKind.PROVIDER_WEBHOOK, None),
    ],
)
def test_a_service_bearer_with_malformed_json_is_403_not_422(api, world: World, kind, role) -> None:
    """FastAPI reads and JSON-decodes the body before dependencies run; the route-level guard
    refuses a non-human bearer first, so a worker's malformed body is never 422 (V-37)."""
    client, _csrf, _ = api
    _s, episode_id, _package = world.ready_episode()
    before = world.count("SELECT COUNT(*) FROM approval_events")
    response = client.post(
        f"/episodes/{episode_id}/review",
        content=b'{"gate": "EPISODE_FINAL", broken',
        headers={
            **_bearer(world, kind, role),
            "X-CSRF-Token": "ignored",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "UNAUTHORIZED"
    assert world.count("SELECT COUNT(*) FROM approval_events") == before


def test_a_huge_body_with_a_bearer_is_refused_before_any_of_it_is_read(api, world: World) -> None:
    """A 1 MiB body with a bearer is 403 — valid or not, and so is an empty one; the same 1 MiB
    body on the human channel is parsed (422), so the human channel still reads bodies."""
    client, csrf, _ = api
    _s, episode_id, _package = world.ready_episode()
    bearer_headers = {
        **_bearer(world, PrincipalKind.SERVICE_WORKER),
        "content-type": "application/json",
    }
    blob = b'{"gate":"' + b"A" * (1 << 20) + b'"}'
    unparseable = b'{"gate":"' + b"A" * (1 << 20)
    for content in (blob, unparseable, b""):
        refused = client.post(
            f"/episodes/{episode_id}/review", content=content, headers=bearer_headers
        )
        assert refused.status_code == 403, len(content)
        assert refused.json()["code"] == "UNAUTHORIZED"
    human = client.post(
        f"/episodes/{episode_id}/review",
        content=blob,
        headers={"X-CSRF-Token": csrf, "content-type": "application/json"},
    )
    assert human.status_code == 422
    assert (
        world.count("SELECT COUNT(*) FROM approval_events WHERE entity_id = %s", (episode_id,)) == 0
    )


def test_a_human_session_with_malformed_json_is_still_422(api, world: World) -> None:
    client, csrf, _ = api
    _s, episode_id, _package = world.ready_episode()
    response = client.post(
        f"/episodes/{episode_id}/review",
        content=b'{"gate": "EPISODE_FINAL", broken',
        headers={"X-CSRF-Token": csrf, "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


def test_a_junk_bearer_dominates_a_valid_session_cookie(api, world: World) -> None:
    """An Authorization header switches to the service channel even over a live cookie; junk
    there is 401, never a silent fall-through to the cookie session (and no bypass either way)."""
    client, _csrf, _ = api
    response = client.get(
        "/seasons/proposals", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_the_json_findings_and_the_qa_route_carry_the_same_set_with_cycles(
    api, world: World
) -> None:
    """V-26: every cycle's findings appear, each with its cycle and whether it blocks Gate 2."""
    client, _csrf, _ = api
    _s, episode_id, _package = world.ready_episode()
    old_critical = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec("UPDATE episodes SET qa_cycle = 2 WHERE id = %s", (episode_id,))
    new_pass = world.qa_finding(
        episode_id,
        severity=Severity.CRITICAL,
        outcome=QAOutcome.PASS,
        coverage=CoverageStatus.CHECKED,
        qa_cycle=2,
    )

    review = client.get(f"/episodes/{episode_id}/review").json()
    rows = client.get(f"/ui/episodes/{episode_id}/qa-findings")
    assert rows.status_code == 200
    rows = rows.json()

    assert [str(old_critical), str(new_pass)] == [r["finding_id"] for r in rows]
    assert [r["qa_cycle"] for r in rows] == [1, 2]
    assert [r["blocks_gate"] for r in rows] == [True, False]
    assert len(review["findings"]) == len(rows) == 2
    assert [f["check_id"] for f in review["findings"]] == [r["finding"]["check_id"] for r in rows]
    assert any(f"({old_critical}) from QA cycle 1" in b for b in review["gate_blockers"])


def test_the_qa_findings_route_is_owner_only(api, world: World) -> None:
    client, _csrf, _ = api
    _s, episode_id, _package = world.ready_episode()
    client.cookies.clear()
    assert client.get(f"/ui/episodes/{episode_id}/qa-findings").status_code == 401
    token = world.auth.issue_service_credential("worker:qa-reader", PrincipalKind.SERVICE_WORKER)
    response = client.get(
        f"/ui/episodes/{episode_id}/qa-findings", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

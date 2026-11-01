"""Owner scope of every review read, page, media stream and progress route (T044a).

Two owners with disjoint seasons, plus an unassigned legacy season: each owner
sees only its own rows through the JSON routes, the pages and the media stream;
everything else answers exactly like a missing row (404, no private bytes). A
service bearer is refused on the progress routes before anything is read.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from review_support import World

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import PrincipalKind, RuntimeRole
from microdrama.contracts.errors import NotFound, Unauthorized
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.principals import Principal
from microdrama.core.http import human_session_dependency
from microdrama.review import build_router

pytestmark = pytest.mark.db
PASSWORD = "a-long-review-password"


def _client(world: World, offline_settings, username: str) -> tuple[TestClient, str]:
    tokens = world.auth.login(username, PASSWORD)
    router = build_router(
        world.service,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
    )
    app = create_app(AppComponents(settings=offline_settings, routers=[router]))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("md_session", tokens.session_token)
    return client, tokens.csrf_token


@pytest.fixture
def owners(world: World, offline_settings):
    """owner.one (canonical) and owner.two, each with an approved season + episode."""
    world.set_owner(world.auth.create_owner("owner.one", PASSWORD))
    owner2_id = world.auth.create_owner("owner.two", PASSWORD)
    season1, scope1 = world.season(approved=True)
    season2, scope2 = world.season(approved=True, owner_id=owner2_id)
    episode1 = world.episode(season1)
    episode2 = world.episode(season2)
    one, csrf_one = _client(world, offline_settings, "owner.one")
    two, csrf_two = _client(world, offline_settings, "owner.two")
    return {
        "one": one,
        "two": two,
        "csrf_one": csrf_one,
        "csrf_two": csrf_two,
        "owner2_id": owner2_id,
        "season1": season1,
        "season2": season2,
        "scope1": scope1,
        "scope2": scope2,
        "episode1": episode1,
        "episode2": episode2,
    }


@pytest.fixture
def legacy(world: World):
    """An unapproved, unassigned legacy season with an episode: hidden from everyone."""
    season_id, scope = world.season(approved=False, unassigned=True)
    episode_id = world.episode(season_id)
    return season_id, episode_id, scope


def _bearer(world: World, kind: PrincipalKind) -> dict[str, str]:
    role = RuntimeRole.CRITIC if kind is PrincipalKind.RUNTIME_MODEL else None
    token = world.auth.issue_service_credential(
        f"{kind.value.lower()}:{uuid.uuid4().hex[:10]}", kind, runtime_role=role
    )
    return {"Authorization": f"Bearer {token}"}


# --- enumeration and direct reads -----------------------------------------------------------


def test_each_owner_lists_only_its_own_seasons(owners, world: World) -> None:
    one, two = owners["one"], owners["two"]
    listed_one = {row["season_id"] for row in one.get("/seasons/proposals").json()}
    listed_two = {row["season_id"] for row in two.get("/seasons/proposals").json()}
    assert listed_one == {str(owners["season1"])}
    assert listed_two == {str(owners["season2"])}
    assert world.service.season_proposals(world.human())[0].season_id == owners["season1"]


def test_cross_owner_and_unassigned_season_views_are_404_without_private_bytes(
    owners, legacy, world: World
) -> None:
    one, two = owners["one"], owners["two"]
    legacy_season, _legacy_episode, legacy_scope = legacy

    foreign = two.get(f"/seasons/{owners['season1']}")
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "NOT_FOUND"
    # No private bytes: the other owner's scope text never appears in the refusal.
    assert owners["scope1"].title_en not in foreign.text
    assert owners["scope1"].logline not in foreign.text

    hidden = one.get(f"/seasons/{legacy_season}")
    assert hidden.status_code == 404
    assert legacy_scope.title_en not in hidden.text
    assert (
        world.count("SELECT COUNT(*) FROM season_owners WHERE season_id = %s", (legacy_season,))
        == 0
    )


def test_cross_owner_episode_reads_and_pages_are_404(owners, legacy) -> None:
    one, two = owners["one"], owners["two"]
    legacy_season, legacy_episode, _scope = legacy

    assert two.get(f"/episodes/{owners['episode1']}/review").status_code == 404
    assert one.get(f"/episodes/{owners['episode2']}/review").status_code == 404
    assert one.get(f"/episodes/{legacy_episode}/review").status_code == 404
    assert one.get(f"/ui/episodes/{legacy_episode}").status_code == 404
    assert one.get(f"/ui/seasons/{legacy_season}").status_code == 404
    assert one.get(f"/ui/episodes/{owners['episode2']}").status_code == 404
    # The owner's own episode still reads.
    assert one.get(f"/episodes/{owners['episode1']}/review").status_code == 200


def test_qa_finding_rows_are_owner_scoped(owners, world: World) -> None:
    one, two = owners["one"], owners["two"]
    world.qa_finding(owners["episode1"])
    rows = one.get(f"/ui/episodes/{owners['episode1']}/qa-findings")
    assert rows.status_code == 200 and len(rows.json()) == 1
    assert two.get(f"/ui/episodes/{owners['episode1']}/qa-findings").status_code == 404


def test_the_media_stream_stops_at_the_owner_boundary(owners, world: World) -> None:
    one, two = owners["one"], owners["two"]
    asset_id, _sha = world.asset(
        season_id=owners["season1"], episode_id=owners["episode1"], data=b"owner-one-media"
    )

    own = one.get(f"/ui/media/{asset_id}")
    assert own.status_code == 200
    assert own.content == b"owner-one-media"

    foreign = two.get(f"/ui/media/{asset_id}")
    assert foreign.status_code == 404
    assert b"owner-one-media" not in foreign.content
    # No object-store key leaks in the refusal.
    assert "review-tests" not in foreign.text


def test_comfy_style_episode_only_media_streams_to_its_owner(owners, world: World) -> None:
    """The genuine render-output shape (persist_output): season_id NULL, episode set."""
    one, two = owners["one"], owners["two"]
    asset_id, _sha = world.asset(
        season_id=None, episode_id=owners["episode1"], data=b"comfy-episode-only"
    )
    with world.db.transaction(readonly=True) as tx:
        row = tx.fetchone("SELECT season_id, episode_id FROM assets WHERE id = %s", (asset_id,))
    assert row["season_id"] is None and row["episode_id"] == owners["episode1"]

    own = one.get(f"/ui/media/{asset_id}")
    assert own.status_code == 200
    assert own.content == b"comfy-episode-only"

    foreign = two.get(f"/ui/media/{asset_id}")
    assert foreign.status_code == 404
    assert b"comfy-episode-only" not in foreign.content
    assert "review-tests" not in foreign.text


def test_conflicting_season_and_episode_ids_stream_for_no_owner(owners, world: World) -> None:
    """owner.one's season column on owner.two's episode: inconsistent, denied for both."""
    one, two = owners["one"], owners["two"]
    asset_id, _sha = world.asset(
        season_id=owners["season1"],
        episode_id=owners["episode2"],
        data=b"conflicting-scope-media",
    )
    for client in (one, two):
        refusal = client.get(f"/ui/media/{asset_id}")
        assert refusal.status_code == 404
        assert b"conflicting-scope-media" not in refusal.content
        assert "review-tests" not in refusal.text


def test_an_asset_with_no_scope_at_all_never_streams(owners, world: World) -> None:
    one = owners["one"]
    asset_id, _sha = world.asset(season_id=None, episode_id=None, data=b"unscoped-media")
    assert one.get(f"/ui/media/{asset_id}").status_code == 404


# --- progress routes --------------------------------------------------------------------------


def test_progress_routes_are_owner_scoped(owners, legacy) -> None:
    one, two = owners["one"], owners["two"]
    legacy_season, legacy_episode, _scope = legacy

    own = one.get(f"/ui/seasons/{owners['season1']}/progress.json")
    assert own.status_code == 200
    body = own.json()
    assert body["season_id"] == str(owners["season1"])
    assert [e["episode_id"] for e in body["episodes"]] == [str(owners["episode1"])]
    assert owners["scope2"].logline not in own.text

    assert one.get(f"/ui/episodes/{owners['episode1']}/progress.json").status_code == 200
    assert two.get(f"/ui/seasons/{owners['season1']}/progress.json").status_code == 404
    assert two.get(f"/ui/episodes/{owners['episode1']}/progress.json").status_code == 404
    assert one.get(f"/ui/seasons/{legacy_season}/progress.json").status_code == 404
    assert one.get(f"/ui/episodes/{legacy_episode}/progress.json").status_code == 404


def test_the_progress_page_renders_only_owned_episodes(owners, legacy) -> None:
    one, two = owners["one"], owners["two"]
    legacy_season, _episode, _scope = legacy

    page = one.get(f"/ui/seasons/{owners['season1']}/progress")
    assert page.status_code == 200
    assert "Episode 1" in page.text
    assert 'data-testid="progress-episode"' in page.text

    assert two.get(f"/ui/seasons/{owners['season1']}/progress").status_code == 404
    assert one.get(f"/ui/seasons/{legacy_season}/progress").status_code == 404


@pytest.mark.parametrize(
    "kind",
    [
        PrincipalKind.SERVICE_WORKER,
        PrincipalKind.SCHEDULER,
        PrincipalKind.RUNTIME_MODEL,
        PrincipalKind.PROVIDER_WEBHOOK,
    ],
)
def test_a_service_bearer_cannot_read_owner_workbench_data(owners, world: World, kind) -> None:
    """The progress routes carry the same bearer-first refusal as the gate routes."""
    one = owners["one"]
    headers = _bearer(world, kind)
    assert (
        one.get(f"/ui/seasons/{owners['season1']}/progress.json", headers=headers).status_code
        == 403
    )
    assert (
        one.get(f"/ui/episodes/{owners['episode1']}/progress.json", headers=headers).status_code
        == 403
    )
    assert one.get(f"/ui/seasons/{owners['season1']}/progress", headers=headers).status_code == 403
    assert one.get(f"/ui/media/{uuid.uuid4()}", headers=headers).status_code == 403


def test_unauthenticated_progress_reads_are_401(owners) -> None:
    one = owners["one"]
    one.cookies.clear()
    assert one.get("/seasons/proposals").status_code == 401
    assert one.get(f"/ui/episodes/{uuid.uuid4()}/progress.json").status_code == 401


# --- decisions respect the same boundary ------------------------------------------------------


def test_a_gate1_decision_from_the_wrong_owner_is_404_and_records_nothing(
    owners, world: World
) -> None:
    two = owners["two"]
    season_id, scope = world.season(approved=False)  # owner.one's new intake
    before = world.count("SELECT COUNT(*) FROM approval_events")
    command = world.gate1_command(season_id, canonical_hash(scope), 0)
    refused = two.post(
        f"/seasons/{season_id}/approval",
        json=command.model_dump(mode="json"),
        headers={"X-CSRF-Token": owners["csrf_two"]},
    )
    assert refused.status_code == 404
    assert world.count("SELECT COUNT(*) FROM approval_events") == before
    assert world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"] == (
        "PROPOSED"
    )


def test_a_gate2_decision_on_a_foreign_episode_is_404(owners, world: World) -> None:
    two = owners["two"]
    _season, episode_id, package = world.ready_episode()
    before = world.count("SELECT COUNT(*) FROM approval_events")
    command = world.gate2_command(episode_id, package)
    refused = two.post(
        f"/episodes/{episode_id}/review",
        json=command.model_dump(mode="json"),
        headers={"X-CSRF-Token": owners["csrf_two"]},
    )
    assert refused.status_code == 404
    assert world.count("SELECT COUNT(*) FROM approval_events") == before


def test_service_level_reads_enforce_the_same_scope(owners, world: World) -> None:
    other = world.human_for(owners["owner2_id"])
    asset_id, _sha = world.asset(season_id=owners["season1"], episode_id=owners["episode1"])
    with pytest.raises(NotFound):
        world.service.season_view(other, owners["season1"])
    with pytest.raises(NotFound):
        world.service.episode_review(other, owners["episode1"])
    with pytest.raises(NotFound):
        world.service.media_file(other, asset_id)
    with pytest.raises(NotFound):
        world.service.episode_progress(other, owners["episode1"])
    with pytest.raises(NotFound):
        world.service.season_progress(other, owners["season1"])
    with pytest.raises(NotFound):
        world.service.qa_finding_rows(other, owners["episode1"])

    worker = Principal(principal_id="worker:scope", kind=PrincipalKind.SERVICE_WORKER)
    with pytest.raises(Unauthorized):
        world.service.season_proposals(worker)
    with pytest.raises(Unauthorized):
        world.service.episode_progress(worker, owners["episode1"])

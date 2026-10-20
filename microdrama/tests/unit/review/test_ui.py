"""Server-rendered review pages: sign-in, decision forms, the preview, unknowns and the media stream."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape
from review_support import World

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import AssetKind, CoverageStatus, PrincipalKind, QAOutcome, Severity
from microdrama.contracts.hashing import canonical_hash
from microdrama.core.http import human_session_dependency
from microdrama.review import build_router

pytestmark = pytest.mark.db
PASSWORD = "a-long-review-password"


def _client(world: World, offline_settings, *, cookie_secure: bool = False) -> TestClient:
    router = build_router(
        world.service,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=cookie_secure,
    )
    app = create_app(AppComponents(settings=offline_settings, routers=[router]))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def web(world: World, offline_settings) -> TestClient:
    world.auth.create_owner("review.owner", PASSWORD)
    return _client(world, offline_settings)


def login_token(client: TestClient) -> str:
    """Open the sign-in page; return its pre-session token (cookie and form value must agree)."""
    page = client.get("/auth/login")
    assert page.status_code == 200
    cookie = client.cookies.get("md_login_csrf")
    assert cookie, "the sign-in page sets its token cookie"
    field = re.search(r'name="login_csrf" value="([^"]+)"', page.text)
    assert field and field.group(1) == cookie
    return cookie


def sign_in(client: TestClient) -> str:
    response = client.post(
        "/auth/login",
        data={"username": "review.owner", "password": PASSWORD, "login_csrf": login_token(client)},
    )
    assert response.status_code == 303, response.text
    csrf = client.cookies.get("md_csrf")
    assert csrf
    return csrf


def form_body(pairs: list[tuple[str, str]]) -> dict[str, object]:
    """Repeated fields become lists; httpx only sets the form content type for a mapping."""
    body: dict[str, object] = {}
    for key, value in pairs:
        if key in body:
            current = body[key]
            body[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            body[key] = value
    return body


def _approve_chunk(html: str) -> str:
    start = html.index('data-testid="approve-form"')
    return html[start : html.index("</form>", start)]


def _form_fields(html: str, action: str) -> dict[str, str]:
    """Hidden inputs of the form posting to ``action`` (test helper; the page is not parsed for logic)."""
    start = html.index(f'action="{action}"')
    end = html.index("</form>", start)
    chunk = html[start:end]
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', chunk)
    }


# --- sign in and out ----------------------------------------------------------------------


def test_login_page_renders_without_a_session(web: TestClient) -> None:
    response = web.get("/auth/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text
    assert "md_session" not in response.headers.get("set-cookie", "")


def test_a_wrong_password_is_401_and_gives_no_session(web: TestClient) -> None:
    token = login_token(web)
    response = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": "wrong-password-x", "login_csrf": token},
    )
    assert response.status_code == 401
    assert "Invalid username or password." in response.text
    assert web.cookies.get("md_session") is None


def test_sign_in_sets_hardened_cookies(world: World, offline_settings) -> None:
    world.auth.create_owner("review.secure", PASSWORD)
    secure = _client(world, offline_settings, cookie_secure=True)
    page = secure.get("/auth/login")
    token_cookie = next(
        c for c in page.headers.get_list("set-cookie") if c.startswith("md_login_csrf=")
    )
    token = token_cookie.split(";", 1)[0].split("=", 1)[1]
    # A Secure cookie is not sent back over plain http in the test client, so the pair is sent
    # explicitly; the cookie attributes themselves are what this test checks.
    response = secure.post(
        "/auth/login",
        data={"username": "review.secure", "password": PASSWORD, "login_csrf": token},
        headers={"Cookie": f"md_login_csrf={token}"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/seasons"
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("md_session="))
    csrf = next(c for c in cookies if c.startswith("md_csrf="))
    for cookie in (session, csrf):
        assert "HttpOnly" in cookie
        assert "samesite=strict" in cookie.lower()
        assert "Secure" in cookie


def test_pages_send_an_anonymous_browser_to_the_login_page(web: TestClient) -> None:
    response = web.get("/ui/seasons")
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_the_proposal_list_and_season_page_show_the_concept(web: TestClient, world: World) -> None:
    sign_in(web)
    season_id, scope = world.season(approved=False)
    listing = web.get("/ui/seasons")
    assert listing.status_code == 200
    assert str(escape(scope.title_en)) in listing.text
    page = web.get(f"/ui/seasons/{season_id}")
    assert page.status_code == 200
    assert str(escape(scope.logline)) in page.text
    assert 'data-testid="gate1-approve"' in page.text
    assert 'data-testid="gate1"' in page.text


def test_logout_needs_csrf_and_revokes_the_session(web: TestClient, world: World) -> None:
    csrf = sign_in(web)
    assert web.post("/auth/logout").status_code == 403
    response = web.post("/auth/logout", data={"csrf_token": csrf})
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"
    # The server revoked the session: the old cookie value no longer opens pages.
    assert web.get("/ui/seasons").status_code == 303
    assert world.count("SELECT COUNT(*) FROM human_sessions WHERE revoked_at IS NOT NULL") == 1


# --- gate 1 forms -------------------------------------------------------------------------


def test_season_form_approves_and_redirects_to_the_season(web: TestClient, world: World) -> None:
    csrf = sign_in(web)
    season_id, scope = world.season(approved=False)
    page = web.get(f"/ui/seasons/{season_id}").text
    fields = _form_fields(page, f"/ui/seasons/{season_id}/approval")
    assert fields["package_hash"] == canonical_hash(scope)
    assert fields["csrf_token"] == csrf
    data = {**fields, "action": "APPROVE"}
    response = web.post(f"/ui/seasons/{season_id}/approval", data=data)
    assert response.status_code == 303
    assert response.headers["location"] == f"/ui/seasons/{season_id}"
    assert (
        world.row("SELECT state FROM seasons WHERE id = %s", (season_id,))["state"]
        == "SEASON_APPROVED"
    )
    assert len(world.jobs_of("story.compile_season")) == 1


def test_a_stale_season_form_renders_the_error_with_its_status(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    season_id, scope = world.season(approved=False)
    page = web.get(f"/ui/seasons/{season_id}").text
    fields = _form_fields(page, f"/ui/seasons/{season_id}/approval")
    data = {**fields, "action": "APPROVE", "expected_revision": "42"}
    response = web.post(f"/ui/seasons/{season_id}/approval", data=data)
    assert response.status_code == 409
    assert "STALE_REVISION" in response.text
    assert world.approvals(season_id) == []


def test_a_season_form_without_csrf_is_forbidden(web: TestClient, world: World) -> None:
    sign_in(web)
    season_id, scope = world.season(approved=False)
    response = web.post(
        f"/ui/seasons/{season_id}/approval",
        data={
            "gate": "SEASON_CONCEPT",
            "entity_id": str(season_id),
            "expected_revision": "0",
            "package_hash": canonical_hash(scope),
            "idempotency_key": "gate1-nocsrf-0001",
            "action": "APPROVE",
        },
    )
    assert response.status_code == 403
    assert world.approvals(season_id) == []


# --- gate 2 page --------------------------------------------------------------------------


def test_blocked_episode_shows_the_preview_and_blockers_but_no_approve(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    world.qa_finding(episode_id, severity=Severity.CRITICAL)
    response = web.get(f"/ui/episodes/{episode_id}")
    assert response.status_code == 200
    assert "<video" in response.text, "the playable episode is shown"
    assert "Preview only. Approve is unavailable." in response.text
    assert "open CRITICAL REPAIRABLE QA finding" in response.text
    assert 'data-testid="approve-form"' not in response.text
    assert 'data-testid="approve"' not in response.text
    assert 'data-testid="revise-form"' in response.text, "a blocked preview can still be revised"
    assert 'data-testid="reject-form"' in response.text


def test_an_orphaned_gpu_with_an_unverified_stop_is_shown_as_a_blocker(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    season_id, episode_id, package = world.ready_episode()
    lease = world.open_gpu_lease(episode_id, season_id, state="EXPIRED", stop_verified=False)
    page = web.get(f"/ui/episodes/{episode_id}")
    assert page.status_code == 200
    assert f"GPU pod lease {lease} is EXPIRED and its stop is not verified" in page.text
    assert "the GPU must be confirmed off before Gate 2" in page.text
    assert 'data-testid="approve-form"' not in page.text
    assert "<video" in page.text, "the preview still renders"


def test_an_episode_outside_the_gate_shows_the_preview_without_any_decision(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, state="AI_REVIEW")
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.store_package(world.package(season_id=season_id, episode_id=episode_id, master=master))
    page = web.get(f"/ui/episodes/{episode_id}")
    assert page.status_code == 200
    assert "<video" in page.text
    assert "AI_REVIEW, not AWAITING_FINAL_REVIEW" in page.text
    assert 'data-testid="approve-form"' not in page.text
    assert 'data-testid="revise-form"' not in page.text
    assert "No decision is open" in page.text


def test_ready_episode_offers_approve_with_the_bound_hashes(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert 'data-testid="approve-form"' in page
    fields = _form_fields(page, f"/ui/episodes/{episode_id}/review")
    assert fields["package_hash"] == package.package_hash
    assert fields["release_scope_hash"] == package.release_scope_hash
    assert fields["management_policy_hash"] == package.management_policy_hash
    assert _approve_chunk(page).count('name="media_hash"') == len(package.media_hashes)


def test_each_render_gets_fresh_idempotency_keys(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, _package = world.ready_episode()
    first = web.get(f"/ui/episodes/{episode_id}").text
    second = web.get(f"/ui/episodes/{episode_id}").text
    keys_one = re.findall(r'name="idempotency_key" value="([^"]+)"', first)
    keys_two = re.findall(r'name="idempotency_key" value="([^"]+)"', second)
    assert len(keys_one) == 3 and len(set(keys_one)) == 3
    assert set(keys_one).isdisjoint(keys_two)


def test_unknown_qa_is_listed_explicitly_and_no_aggregate_score_is_shown(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    master = package.media[0]
    world.observation(episode_id, asset_id=master.asset_id, asset_sha=master.sha256)
    world.qa_finding(
        episode_id,
        severity=Severity.MAJOR,
        outcome=QAOutcome.UNKNOWN,
        coverage=CoverageStatus.UNSAMPLED,
        check_id="temporal.lip_sync",
    )
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert "UNKNOWN is not a pass" in page
    assert "Not checked (UNKNOWN)" in page
    assert "temporal.lip_sync" in page
    assert "dense lip-sync sampling was not run" in page
    assert re.search(r"score\s*[:=]\s*\d", page, re.IGNORECASE) is None
    body = page.split("<main>", 1)[1]
    assert re.search(r"\b\d{1,3}\s*%", body) is None, "no percentage summary of checks"


def test_captions_show_timing_and_escape_their_text(web: TestClient, world: World) -> None:
    sign_in(web)
    season_id, scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    world.caption(episode_id, text="<script>alert('x')</script>ทดสอบ")
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;ทดสอบ" in page
    assert "<script>alert" not in page
    assert "00:00:00.000" in page and "00:00:01.000" in page
    assert "releasable" in page


def test_episode_page_shows_cost_remaining_and_the_destinations(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert "Headroom for paid dispatch" in page
    assert "Shutdown reserve (protected)" in page
    assert "US$10.0000" in page  # the cap is always shown; nothing is spent yet
    assert "youtube" in page.lower()
    assert "Asia/Bangkok" in page
    assert "Episode-one reference package" in page


def test_episode_one_shows_the_cast_contact_sheet(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode(number=1)
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert f"/ui/media/{package.cast_package_asset_ids[0]}" in page
    assert "No cast contact sheet" not in page


def test_revise_form_turns_timecodes_into_feedback(web: TestClient, world: World) -> None:
    csrf = sign_in(web)
    _season, episode_id, package = world.ready_episode()
    page = web.get(f"/ui/episodes/{episode_id}").text
    fields = _form_fields(page, f"/ui/episodes/{episode_id}/review")
    pairs = [(k, v) for k, v in fields.items() if k not in ("action", "idempotency_key")]
    pairs += [
        ("action", "REVISE"),
        ("idempotency_key", "revise-ui-key-0001"),
        ("feedback_category", "thai_dialogue"),
        ("feedback_start", "00:12.500"),
        ("feedback_end", "00:15.500"),
        ("feedback_comment", "the line sounds stiff"),
        ("feedback_category", ""),
        ("feedback_start", ""),
        ("feedback_end", ""),
        ("feedback_comment", ""),
    ]
    pairs = [(k, csrf if k == "csrf_token" else v) for k, v in pairs]
    response = web.post(f"/ui/episodes/{episode_id}/review", data=form_body(pairs))
    assert response.status_code == 303, response.text
    assert world.episode_state(episode_id)[0] == "REFERENCES"
    feedback = world.row(
        "SELECT start_ms, end_ms, category FROM feedback_events WHERE episode_id = %s",
        (episode_id,),
    )
    assert (feedback["start_ms"], feedback["end_ms"], feedback["category"]) == (
        12_500,
        15_500,
        "thai_dialogue",
    )


def test_a_stale_episode_form_renders_the_error_page(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    page = web.get(f"/ui/episodes/{episode_id}").text
    fields = _form_fields(page, f"/ui/episodes/{episode_id}/review")
    fields["expected_revision"] = "77"
    fields["action"] = "APPROVE"
    fields["idempotency_key"] = "stale-ui-approve-0001"
    response = web.post(f"/ui/episodes/{episode_id}/review", data=fields)
    assert response.status_code == 409
    assert "STALE_REVISION" in response.text
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"


def test_approve_form_moves_the_episode_and_redirects(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, package = world.ready_episode()
    page = web.get(f"/ui/episodes/{episode_id}").text
    fields = _form_fields(page, f"/ui/episodes/{episode_id}/review")
    fields["action"] = "APPROVE"
    fields["idempotency_key"] = "approve-ui-key-0001"
    response = web.post(f"/ui/episodes/{episode_id}/review", data=fields)
    assert response.status_code == 303
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"


# --- media stream -------------------------------------------------------------------------


def test_media_requires_an_owner_session(web: TestClient, world: World) -> None:
    season_id, _scope = world.season(approved=False)
    asset_id, _sha = world.asset(season_id=season_id, episode_id=None)
    response = web.get(f"/ui/media/{asset_id}")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_media_is_served_only_to_the_owner_with_private_headers(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    from review_support import MASTER_BYTES

    season_id, _scope = world.season(approved=False)
    asset_id, _sha = world.asset(season_id=season_id, episode_id=None)
    response = web.get(f"/ui/media/{asset_id}")
    assert response.status_code == 200
    assert response.content == MASTER_BYTES
    assert response.headers["content-type"].startswith("video/mp4")
    assert "no-store" in response.headers["cache-control"]
    assert "location" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_media_supports_byte_ranges_for_seeking(web: TestClient, world: World) -> None:
    sign_in(web)
    season_id, _scope = world.season(approved=False)
    asset_id, _sha = world.asset(season_id=season_id, episode_id=None)
    response = web.get(f"/ui/media/{asset_id}", headers={"Range": "bytes=0-7"})
    assert response.status_code == 206
    assert len(response.content) == 8


def test_media_refuses_service_credentials_and_unknown_assets(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    season_id, _scope = world.season(approved=False)
    asset_id, _sha = world.asset(season_id=season_id, episode_id=None)
    token = world.auth.issue_service_credential("worker:media-reader", PrincipalKind.SERVICE_WORKER)
    assert (
        web.get(f"/ui/media/{asset_id}", headers={"Authorization": f"Bearer {token}"}).status_code
        == 403
    )
    assert web.get(f"/ui/media/{uuid.uuid4()}").status_code == 404


def test_review_pages_carry_security_headers_and_no_public_urls(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, _package = world.ready_episode()
    response = web.get(f"/ui/episodes/{episode_id}")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "no-store" in response.headers["cache-control"]
    assert "https://" not in response.text and "http://" not in response.text


def test_media_elements_follow_the_stored_media_type(web: TestClient, world: World) -> None:
    sign_in(web)
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id, number=1)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    voice, _ = world.asset(
        season_id=season_id,
        episode_id=episode_id,
        kind=AssetKind.AUDIO,
        data=b"RIFF-voice-anchor",
        media_type="audio/wav",
    )
    cover, cover_sha = world.asset(
        season_id=season_id,
        episode_id=episode_id,
        kind=AssetKind.IMAGE,
        data=b"cover-png",
        media_type="image/png",
    )
    variant, variant_sha = world.asset(
        season_id=season_id,
        episode_id=episode_id,
        kind=AssetKind.IMAGE,
        data=b"not-a-video",
        media_type="image/jpeg",
    )
    package = world.package(
        season_id=season_id,
        episode_id=episode_id,
        master=master,
        extra_media=[(cover, cover_sha, "cover"), (variant, variant_sha, "variant")],
        cast=[voice],
    )
    world.store_package(package)
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert (
        f'<audio controls preload="metadata" aria-label="cast package"><source src="/ui/media/{voice}"'
        in page
    )
    assert f'<img src="/ui/media/{cover}"' in page
    assert f'<img src="/ui/media/{variant}"' in page
    assert f'<source src="/ui/media/{variant}"' not in page, "an image is never a video element"


def test_an_unreadable_stored_caption_is_flagged_not_rendered(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, _package = world.ready_episode()
    world.row_exec(
        "INSERT INTO caption_tracks (id, episode_id, locale, version, timing_source, body, body_hash, "
        "state) VALUES (%s, %s, 'en-US', 1, 'ACTUAL_AUDIO_ALIGNMENT', '{}'::jsonb, %s, 'CURRENT')",
        (uuid.uuid4(), episode_id, "b" * 64),
    )
    page = web.get(f"/ui/episodes/{episode_id}")
    assert page.status_code == 200
    assert "This stored track cannot be read; it is not releasable." in page.text


# --- sign-in forms carry a pre-session token (V-28: login CSRF) ----------------------------


def test_the_sign_in_token_cookie_is_short_lived_and_scoped(web: TestClient) -> None:
    response = web.get("/auth/login")
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith("md_login_csrf=")
    )
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()
    assert "Max-Age=900" in cookie
    assert "Path=/auth" in cookie
    assert "Secure" not in cookie, "cookie_secure=False in this client"


def test_the_sign_in_token_is_secure_when_cookies_are_secure(
    world: World, offline_settings
) -> None:
    secure = _client(world, offline_settings, cookie_secure=True)
    response = secure.get("/auth/login")
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith("md_login_csrf=")
    )
    assert "Secure" in cookie and "HttpOnly" in cookie


def test_a_sign_in_without_the_form_token_is_403_and_never_reaches_the_password(
    web: TestClient, world: World
) -> None:
    login_token(web)  # a real cookie is present, but the form does not echo it
    before = world.count("SELECT COUNT(*) FROM human_sessions")
    response = web.post("/auth/login", data={"username": "review.owner", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "UNAUTHORIZED"
    assert "md_session" not in response.headers.get("set-cookie", "")
    assert world.count("SELECT COUNT(*) FROM human_sessions") == before


def test_a_cross_site_form_without_the_cookie_is_403(web: TestClient, world: World) -> None:
    """The attacker's page can post the form field but cannot read or send the cookie."""
    token = login_token(web)
    web.cookies.clear()  # the browser withholds the SameSite=Strict cookie cross-site
    before = world.count("SELECT COUNT(*) FROM human_sessions")
    response = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": PASSWORD, "login_csrf": token},
    )
    assert response.status_code == 403
    assert world.count("SELECT COUNT(*) FROM human_sessions") == before


def test_a_forged_form_token_is_403_even_with_a_real_cookie(web: TestClient, world: World) -> None:
    login_token(web)
    before = world.count("SELECT COUNT(*) FROM human_sessions")
    response = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": PASSWORD, "login_csrf": "forged-value"},
    )
    assert response.status_code == 403
    assert world.count("SELECT COUNT(*) FROM human_sessions") == before


def test_a_matching_pair_signs_in_and_clears_the_token(web: TestClient) -> None:
    token = login_token(web)
    response = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": PASSWORD, "login_csrf": token},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/seasons"
    cleared = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith("md_login_csrf=")
    )
    assert "Max-Age=0" in cleared or "expires=" in cleared.lower()
    assert web.get("/ui/seasons").status_code == 200


def test_a_wrong_password_renews_the_token(web: TestClient) -> None:
    old = login_token(web)
    response = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": "wrong-password-x", "login_csrf": old},
    )
    assert response.status_code == 401
    renewed = (
        next(c for c in response.headers.get_list("set-cookie") if c.startswith("md_login_csrf="))
        .split(";", 1)[0]
        .split("=", 1)[1]
    )
    assert renewed and renewed != old
    assert f'value="{renewed}"' in response.text
    # The old token no longer matches the page the browser now holds.
    stale = web.post(
        "/auth/login",
        data={"username": "review.owner", "password": PASSWORD, "login_csrf": old},
    )
    assert stale.status_code == 403


def test_the_page_shows_each_finding_with_its_cycle_and_gate_effect(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, _package = world.ready_episode()
    old = world.qa_finding(episode_id, severity=Severity.CRITICAL, qa_cycle=1)
    world.row_exec("UPDATE episodes SET qa_cycle = 2 WHERE id = %s", (episode_id,))
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert 'data-testid="findings"' in page
    row = page[page.index(f'data-finding="{old}"') :]
    row = row[: row.index("</tr>")]
    assert "<td>1</td>" in row, "the cycle the finding was raised in"
    assert '<span class="bad">yes</span>' in row, "it still blocks Gate 2"
    assert f"({old}) from QA cycle 1" in page, "the blocker names the cycle too"
    assert 'data-testid="approve-form"' not in page

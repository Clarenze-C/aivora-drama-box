"""T044b2 owner Script Maker intake pages and service: the three-step flow, security, fail-closed dispatch.

The wizard is the only browser surface: three answers, a closed field set, and
every advanced value from server configuration. These tests pin the HTTP flow
(sign-in, CSRF, bearer-first refusal, owner scope), the idempotent submit, the
fail-closed unconfigured path, and the workbench's honest V2 document views.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from review_support import World

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import PrincipalKind
from microdrama.contracts.examples import EP1_ID, SEASON_ID, season_scope
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import ConceptIntake
from microdrama.core.http import human_session_dependency
from microdrama.persistence import insert_row
from microdrama.pipeline.mocks import MOCK_COMPARATOR_SCENE, MOCK_SOURCES
from microdrama.research import (
    ComparatorCorpus,
    ResearchService,
    build_research_service,
    build_script_maker_service,
)
from microdrama.review import IntakeConfig, IntakeService, build_router
from microdrama.review.intake import INTAKE_JOB_TYPE, intake_record_id
from microdrama.story.v2_store import StoryV2Store
from microdrama.testing.fakes import FakeLLMProvider, FakeSourceProvider

pytestmark = [pytest.mark.db]
PASSWORD = "a-long-review-password"
ENVELOPE = 2_000_000

IDEA = "ครอบครัวพยายามรักษาร้านอาหารเล็ก ๆ ของแม่จากหนี้ที่ไม่มีใครเคยพูดถึง"


class IntakeWorld:
    """A review world plus the composed mock intake services (fake providers)."""

    def __init__(
        self,
        world: World,
        *,
        envelope: int | None = ENVELOPE,
        llm_enabled: bool = True,
        source_providers: dict | None = None,
    ):
        self.world = world
        llm = FakeLLMProvider(clock=world.clock, ids=world.ids) if llm_enabled else None
        self.sources = FakeSourceProvider(clock=world.clock, ids=world.ids)
        self.script_maker = build_script_maker_service(
            world.clock, world.settings, budget=world.budget, llm=llm
        )
        self.research: ResearchService = build_research_service(
            world.db,
            world.clock,
            world.ids,
            world.settings,
            budget=world.budget,
            source_providers=(
                {"fake-sources": self.sources} if source_providers is None else source_providers
            ),
            llm=llm,
        )
        self.service = IntakeService(
            world.db,
            world.clock,
            world.ids,
            world.settings,
            jobs=world.jobs,
            idempotency=world.idempotency,
            budget=world.budget,
            script_maker=self.script_maker,
            research=self.research,
            config=IntakeConfig(
                research_envelope_micro_usd=envelope,
                allowed_source_ids=tuple(MOCK_SOURCES),
                comparator_corpus=ComparatorCorpus(scenes=[MOCK_COMPARATOR_SCENE]),
                scope_template=season_scope(),
            ),
        )


def _client(world: World, intake: IntakeService | None) -> TestClient:
    router = build_router(
        world.service,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
        intake=intake,
    )
    app = create_app(AppComponents(settings=world.settings, routers=[router]))
    return TestClient(app, follow_redirects=False)


def _login(client: TestClient) -> str:
    page = client.get("/auth/login")
    assert page.status_code == 200, page.text
    token = client.cookies.get("md_login_csrf")
    assert token, f"no login csrf cookie after the page; cookies={dict(client.cookies)}"
    response = client.post(
        "/auth/login",
        data={"username": "intake.owner", "password": PASSWORD, "login_csrf": token},
    )
    assert response.status_code == 303, response.text
    csrf = client.cookies.get("md_csrf")
    assert csrf
    return csrf


@pytest.fixture
def intake_world(world: World) -> IntakeWorld:
    world.set_owner(world.auth.create_owner("intake.owner", PASSWORD))
    return IntakeWorld(world)


@pytest.fixture
def web(intake_world: IntakeWorld) -> TestClient:
    return _client(intake_world.world, intake_world.service)


def _wizard_key(page_text: str) -> str:
    match = re.search(r'name="wizard_key" value="([0-9a-f]{32})"', page_text)
    assert match, "the wizard page mints a one-time key"
    return match.group(1)


def _run_intake_jobs(intake_world: IntakeWorld) -> None:
    """Claim and finish every queued intake job the way a worker deployment would."""
    while True:
        job = intake_world.world.jobs.claim(
            "production", worker_id="intake-test-worker", lease_ms=60_000
        )
        if job is None or job.job_type != INTAKE_JOB_TYPE:
            break
        context = intake_world.world.jobs.context(job, "intake-test-worker")
        outcome = intake_world.service.handle_research_job(context)
        assert outcome is not None, "the intake job must be handled by the intake service"
        intake_world.world.jobs.finish(job.id, worker_id="intake-test-worker", outcome=outcome)


# --- the three-step flow ----------------------------------------------------------------------


def test_three_step_wizard_creates_one_season_intake_and_job(web: TestClient, intake_world) -> None:
    csrf = _login(web)
    step1 = web.get("/ui/intake")
    assert step1.status_code == 200
    assert 'data-step="1"' in step1.text
    key = _wizard_key(step1.text)
    assert "180–300" in step1.text and "original fiction" in step1.text, "locked defaults are shown"

    step2 = web.post(
        "/ui/intake",
        data={"csrf_token": csrf, "wizard_key": key, "step": "1", "story_idea": IDEA},
    )
    assert step2.status_code == 200 and 'data-step="2"' in step2.text

    step3 = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "2",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่นแต่มีความลุ้น",
        },
    )
    assert step3.status_code == 200 and 'data-step="3"' in step3.text
    assert f'value="{IDEA}"' in step3.text, "the owner's own idea is carried, not a scope"

    submitted = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่นแต่มีความลุ้น",
            "episode_count": "5",
        },
    )
    assert submitted.status_code == 303, submitted.text
    season_id = uuid.UUID(submitted.headers["location"].rsplit("/", 1)[1])

    world = intake_world.world
    assert world.count("SELECT COUNT(*) FROM seasons") == 1
    season = world.row("SELECT * FROM seasons WHERE id = %s", (season_id,))
    assert season["state"] == "PROPOSED"
    assert season["expected_episode_count"] == 5
    owner_link = world.row("SELECT * FROM season_owners WHERE season_id = %s", (season_id,))
    assert owner_link["source"] == "CREATOR_AT_CREATION"
    assert owner_link["owner_id"] == world.owner_id
    intake_row = world.row(
        "SELECT payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = 'ConceptIntake' AND record_id = %s",
        (intake_record_id(season_id),),
    )
    assert intake_row is not None, "the intake is persisted before any candidate work"
    stored_intake = ConceptIntake.model_validate(intake_row["payload"])
    assert canonical_hash(stored_intake) == intake_row["payload_sha256"], "exact hash round-trip"
    assert intake_row["payload"]["story_idea"] == IDEA
    assert intake_row["payload"]["requested_episode_count"] == 5
    envelope = world.row(
        "SELECT cap_micro_usd FROM budget_accounts "
        "WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
        (season_id,),
    )
    assert envelope is not None and envelope["cap_micro_usd"] == ENVELOPE
    jobs = world.jobs_of(INTAKE_JOB_TYPE)
    assert len(jobs) == 1 and jobs[0]["status"] == "QUEUED"
    assert jobs[0]["season_id"] == season_id

    status = web.get(f"/ui/intake/{season_id}")
    assert status.status_code == 200
    assert "family-drama" in status.text and IDEA in status.text


def test_refresh_and_double_submit_create_exactly_one_season(web, intake_world) -> None:
    csrf = _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    body = {
        "csrf_token": csrf,
        "wizard_key": key,
        "step": "submit",
        "story_idea": IDEA,
        "genre_tags": "family-drama",
        "tone": "อบอุ่นแต่มีความลุ้น",
        "episode_count": "3",
    }
    first = web.post("/ui/intake", data=body)
    assert first.status_code == 303
    # A browser refresh re-posts the same wizard key: one season, one job, replayed.
    second = web.post("/ui/intake", data=body)
    assert second.status_code == 303
    assert second.headers["location"] == first.headers["location"]
    world = intake_world.world
    assert world.count("SELECT COUNT(*) FROM seasons") == 1
    assert len(world.jobs_of(INTAKE_JOB_TYPE)) == 1
    # A restarted wizard is a new key and a deliberate new intake.
    fresh = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": _wizard_key(web.get("/ui/intake").text),
            "step": "submit",
            "story_idea": "แนวคิดใหม่ที่แตกต่างอย่างชัดเจน",
            "genre_tags": "thriller",
            "tone": "ตึงเครียด",
            "episode_count": "2",
        },
    )
    assert fresh.status_code == 303
    assert world.count("SELECT COUNT(*) FROM seasons") == 2


def test_wrong_episode_count_and_policy_override_are_refused(web, intake_world) -> None:
    csrf = _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    world = intake_world.world
    for bad in ("0", "11", "3.5", "", "seven"):
        response = web.post(
            "/ui/intake",
            data={
                "csrf_token": csrf,
                "wizard_key": key,
                "step": "submit",
                "story_idea": IDEA,
                "genre_tags": "family-drama",
                "tone": "อบอุ่นแต่มีความลุ้น",
                "episode_count": bad,
            },
        )
        assert response.status_code == 422, bad
        assert "episode count" in response.text
    # A posted SeasonScope / cost policy / destinations is refused loudly: the
    # form accepts only the three answers, so no browser policy can pose as the
    # approved default.
    override = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่นแต่มีความลุ้น",
            "episode_count": "5",
            "scope": '{"title_th": "หลอก"}',
            "cost_policy": "{}",
            "destinations": "[]",
            "management_policy": "{}",
        },
    )
    assert override.status_code == 422
    assert "three intake answers" in override.text
    assert world.count("SELECT COUNT(*) FROM seasons") == 0
    assert world.count("SELECT COUNT(*) FROM jobs") == 0


# --- security ----------------------------------------------------------------------------------


def test_intake_routes_refuse_missing_csrf_and_service_bearers(web, intake_world) -> None:
    _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    no_csrf = web.post("/ui/intake", data={"wizard_key": key, "step": "1", "story_idea": IDEA})
    assert no_csrf.status_code == 403
    # A service credential is refused before the body, on GET and POST alike.
    bearer = "Bearer " + intake_world.world.auth.issue_service_credential(
        "svc:intake-refused", PrincipalKind.SERVICE_WORKER
    )
    refused = web.get("/ui/intake", headers={"Authorization": bearer})
    assert refused.status_code == 403
    refused_post = web.post(
        "/ui/intake",
        headers={"Authorization": bearer},
        data={"wizard_key": key, "step": "1", "story_idea": "x"},
    )
    assert refused_post.status_code in (401, 403)
    anonymous = TestClient(web.app, follow_redirects=False)
    redirect = anonymous.get("/ui/intake")
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/auth/login"


def test_cross_owner_and_unassigned_seasons_are_invisible(web, intake_world) -> None:
    csrf = _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    submitted = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่น",
            "episode_count": "4",
        },
    )
    season_id = submitted.headers["location"].rsplit("/", 1)[1]
    world = intake_world.world
    world.auth.create_owner("other.owner", PASSWORD)  # a second, empty owner
    with world.db.transaction() as tx:
        unassigned = uuid.uuid4()
        insert_row(
            tx,
            "seasons",
            {"id": unassigned, "state": "PROPOSED", "title_th": "ลับ", "title_en": "Hidden"},
        )
    other_client = _client(world, intake_world.service)
    other_client.get("/auth/login")
    other_login = other_client.post(
        "/auth/login",
        data={
            "username": "other.owner",
            "password": PASSWORD,
            "login_csrf": other_client.cookies.get("md_login_csrf"),
        },
    )
    assert other_login.status_code == 303, other_login.text
    assert other_client.get(f"/ui/intake/{season_id}").status_code == 404
    assert other_client.get(f"/ui/seasons/{season_id}/workbench").status_code == 404
    # An unassigned legacy season is invisible even to its creator-less world's
    # owner, and the owning owner still sees their own pages.
    assert other_client.get(f"/ui/intake/{unassigned}").status_code == 404
    assert web.get(f"/ui/intake/{unassigned}").status_code == 404
    assert web.get(f"/ui/intake/{season_id}").status_code == 200


# --- fail-closed configuration -------------------------------------------------------------------


def test_unconfigured_intake_records_a_blocker_and_never_dispatches(world: World) -> None:
    world.set_owner(world.auth.create_owner("bare.owner", PASSWORD))
    unconfigured = IntakeWorld(world, envelope=None, llm_enabled=False)
    client = _client(world, unconfigured.service)
    client.get("/auth/login")
    client.post(
        "/auth/login",
        data={
            "username": "bare.owner",
            "password": PASSWORD,
            "login_csrf": client.cookies.get("md_login_csrf"),
        },
    )
    csrf = client.cookies.get("md_csrf")
    key = _wizard_key(client.get("/ui/intake").text)
    submitted = client.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่น",
            "episode_count": "3",
        },
    )
    assert submitted.status_code == 303
    season_id = submitted.headers["location"].rsplit("/", 1)[1]
    # No envelope (an unconfigured cap opens none), no job, no spend — but the
    # intake and season exist with the typed blocker visible to the owner.
    assert (
        world.row(
            "SELECT * FROM budget_accounts WHERE scope_kind = 'SEASON_RESEARCH' AND season_id = %s",
            (uuid.UUID(season_id),),
        )
        is None
    )
    assert world.jobs_of(INTAKE_JOB_TYPE) == []
    page = client.get(f"/ui/intake/{season_id}")
    assert page.status_code == 200
    assert "intake-blockers" in page.text
    assert "research envelope is not configured" in page.text
    assert "model provider is not configured" in page.text


def test_live_mode_without_paid_authorization_blocks_dispatch(
    world: World, offline_settings
) -> None:
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode

    live = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    llm = FakeLLMProvider(clock=world.clock, ids=world.ids)
    script_maker = build_script_maker_service(world.clock, live, budget=world.budget, llm=llm)
    blockers = script_maker.dispatch_blockers()
    assert any("paid model requests are not authorized" in b for b in blockers)


# --- the workbench (current typed V2 documents, honest unknowns) ---------------------------------


def test_workbench_shows_current_v2_documents_and_honest_unknowns(world: World) -> None:
    from microdrama.contracts.examples import (
        v2_directing_manifest,
        v2_episode_pack,
        v2_style_bible,
        v2_wardrobe_assignment,
        v2_wardrobe_bible,
    )

    world.set_owner(world.auth.create_owner("bench.owner", PASSWORD))
    intake_world = IntakeWorld(world)
    client = _client(world, intake_world.service)
    client.get("/auth/login")
    login = client.post(
        "/auth/login",
        data={
            "username": "bench.owner",
            "password": PASSWORD,
            "login_csrf": client.cookies.get("md_login_csrf"),
        },
    )
    assert login.status_code == 303, login.text
    # The example documents are bound to the fixed example season/episode ids.
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "seasons",
            {"id": SEASON_ID, "state": "PROPOSED", "title_th": "ตัวอย่าง", "title_en": "Example"},
        )
        insert_row(
            tx,
            "episodes",
            {
                "id": EP1_ID,
                "season_id": SEASON_ID,
                "episode_number": 1,
                "state": "PLANNED",
                "approved_scope_hash": canonical_hash(season_scope()),
            },
        )
    StoryV2Store(world.db).save_bundle(
        [
            v2_episode_pack(),
            v2_directing_manifest(),
            v2_wardrobe_bible(),
            v2_wardrobe_assignment(),
            v2_style_bible(),
        ]
    )
    page = client.get(f"/ui/seasons/{SEASON_ID}/workbench")
    assert page.status_code == 404, "the season has no owner link yet, so it is invisible"
    with world.db.transaction() as tx:
        from microdrama.testing.seed import link_season_owner

        link_season_owner(tx, SEASON_ID, world.owner_id, source="CREATOR_AT_CREATION")
    page = client.get(f"/ui/seasons/{SEASON_ID}/workbench")
    assert page.status_code == 200
    assert "section-example-1" in page.text and "shot-example-1" in page.text
    assert "00:00:15.000" in page.text, "the actual shot duration is shown"
    assert "Series look" in page.text and "Live-action cinematic" in page.text
    assert "fon-apron" in page.text, "the wardrobe assignment is shown"
    assert "no current character logic records" in page.text.lower(), "honest unknowns"
    assert "No current asset sheets" in page.text


def test_workbench_on_a_fresh_intake_season_shows_unknowns(web, intake_world) -> None:
    csrf = _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    submitted = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่น",
            "episode_count": "3",
        },
    )
    season_id = submitted.headers["location"].rsplit("/", 1)[1]
    page = web.get(f"/ui/seasons/{season_id}/workbench")
    assert page.status_code == 200
    assert "no episodes exist" in page.text.lower()
    assert "no current seasonstoryledger" in page.text.lower().replace(" ", "") or (
        "no current" in page.text.lower()
    )


# --- review-fix round: dispatch blockers, provenance, verification ------------------------------


def test_unregistered_source_provider_blocks_dispatch(world: World) -> None:
    """F3: a source provider the composed registry does not know never dispatches.

    The intake is recorded with a typed blocker; no job exists, so candidate
    generation cannot spend into a research run that would silently skip its
    source steps.
    """
    world.set_owner(world.auth.create_owner("noprov.owner", PASSWORD))
    broken = IntakeWorld(world, source_providers={})
    client = _client(world, broken.service)
    client.get("/auth/login")
    client.post(
        "/auth/login",
        data={
            "username": "noprov.owner",
            "password": PASSWORD,
            "login_csrf": client.cookies.get("md_login_csrf"),
        },
    )
    csrf = client.cookies.get("md_csrf")
    key = _wizard_key(client.get("/ui/intake").text)
    submitted = client.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่น",
            "episode_count": "3",
        },
    )
    assert submitted.status_code == 303
    season_id = submitted.headers["location"].rsplit("/", 1)[1]
    assert world.jobs_of(INTAKE_JOB_TYPE) == []
    page = client.get(f"/ui/intake/{season_id}")
    assert page.status_code == 200
    assert "is not registered" in page.text
    assert "Blocked — nothing was dispatched" in page.text


def test_status_shows_current_blockers_alongside_recorded_jobs(web, intake_world) -> None:
    """F6: configuration that breaks AFTER dispatch stays visible on the status page."""
    csrf = _login(web)
    key = _wizard_key(web.get("/ui/intake").text)
    submitted = web.post(
        "/ui/intake",
        data={
            "csrf_token": csrf,
            "wizard_key": key,
            "step": "submit",
            "story_idea": IDEA,
            "genre_tags": "family-drama",
            "tone": "อบอุ่น",
            "episode_count": "3",
        },
    )
    season_id = submitted.headers["location"].rsplit("/", 1)[1]
    assert len(intake_world.world.jobs_of(INTAKE_JOB_TYPE)) == 1
    # The composed registry later loses the provider (a live configuration fault).
    intake_world.service._research = build_research_service(
        intake_world.world.db,
        intake_world.world.clock,
        intake_world.world.ids,
        intake_world.world.settings,
        budget=intake_world.world.budget,
        source_providers={},
        llm=FakeLLMProvider(clock=intake_world.world.clock, ids=intake_world.world.ids),
    )
    page = web.get(f"/ui/intake/{season_id}")
    assert page.status_code == 200
    assert "Background work" in page.text, "the recorded job stays visible"
    assert "Configuration problems present now" in page.text
    assert "is not registered" in page.text


def _resealed(record, **updates):
    from microdrama.contracts.v2 import verify_v2_record_hash

    fields = record.model_dump(mode="python", exclude={"content_sha256"})
    fields.update(updates)
    sealed = type(record).seal(**fields)
    verify_v2_record_hash(sealed)
    return sealed


def _tamper_current(tx, contract_type: str, json_path: str, value_json: str) -> None:
    """Append a new 'current' row whose content does not match its stored hash.

    ``payload`` is immutable on UPDATE by trigger, so tampering (simulating a
    stored document whose hash no longer matches its content) must arrive as a
    fresh INSERT that supersedes the current row while copying the OLD hash.
    """
    from microdrama.persistence.db import jsonb

    row = tx.fetchone(
        "SELECT record_id, version, payload, payload_sha256, rights_route_id,"
        " rights_version, valid_from, valid_until, created_at"
        " FROM v2_contract_documents WHERE contract_type = %s AND current LIMIT 1",
        (contract_type,),
    )
    assert row is not None, contract_type
    tx.execute(
        "UPDATE v2_contract_documents SET current = false "
        "WHERE contract_type = %s AND record_id = %s",
        (contract_type, row["record_id"]),
    )
    tx.execute(
        "INSERT INTO v2_contract_documents (contract_type, record_id, version, payload,"
        " payload_sha256, rights_route_id, rights_version, valid_from, valid_until,"
        " current, created_at) VALUES (%s, %s, %s, jsonb_set(%s, %s, %s), %s, %s, %s,"
        " %s, %s, true, %s)",
        (
            contract_type,
            row["record_id"],
            int(row["version"]) + 1,
            jsonb(dict(row["payload"])),
            f"{{{json_path}}}",
            value_json,
            row["payload_sha256"],  # the STALE hash: content changed, hash did not
            row["rights_route_id"],
            row["rights_version"],
            row["valid_from"],
            row["valid_until"],
            row["created_at"],
        ),
    )


def test_workbench_refuses_unverified_documents_and_foreign_sheets(world: World) -> None:
    """F2/F4/F5: provenance-filtered sheets, verified documents, verified scope.

    Another owner's PropSheet/LocationLayout/AssetSheet sharing the same
    identifiers must never appear on this owner's workbench; a tampered payload
    with a stale hash shows as unknown (and never a media link); a proposal scope
    whose content does not match its hash is not canon.
    """
    from microdrama.contracts.examples import (
        h,
        uid,
        v2_asset_sheet,
        v2_directing_manifest,
        v2_episode_pack,
        v2_location_layout,
        v2_prompt_manifest,
        v2_prop_sheet,
        v2_style_bible,
        v2_wardrobe_assignment,
        v2_wardrobe_bible,
    )
    from microdrama.contracts.v2 import EpisodePack
    from microdrama.persistence.db import jsonb
    from microdrama.testing.seed import link_season_owner

    world.set_owner(world.auth.create_owner("proof.owner", PASSWORD))
    intake_world = IntakeWorld(world)
    client = _client(world, intake_world.service)
    client.get("/auth/login")
    client.post(
        "/auth/login",
        data={
            "username": "proof.owner",
            "password": PASSWORD,
            "login_csrf": client.cookies.get("md_login_csrf"),
        },
    )

    other_season = uuid.uuid4()
    foreign_asset = uid("proof-foreign-asset")
    own_plate_asset = uid("proof-own-plate-asset")

    # A pack whose scene actually demands the shared prop id "ledger".
    pack_fields = v2_episode_pack().model_dump(mode="python", exclude={"content_sha256"})
    pack_fields["scenes"][0]["prop_ids"] = ["ledger"]
    pack = EpisodePack.seal(**pack_fields)

    own_prop_sheet = v2_prop_sheet()  # asset uid("ledger-prop-asset")
    own_plate_sheet = _resealed(
        v2_asset_sheet(),
        record_id=uid("proof-own-plate-sheet"),
        asset_role="location",
        subject_id="stall",
        asset_id=own_plate_asset,
        asset_sha256=h("stall-geometry"),  # matches v2_location_layout()
    )
    foreign_prop_sheet = _resealed(
        v2_prop_sheet(),
        record_id=uid("proof-foreign-prop-sheet"),
        asset_id=foreign_asset,
    )
    foreign_layout = _resealed(
        v2_location_layout(),
        record_id=uid("proof-foreign-layout"),
        geometry_sha256=h("foreign-plate-geometry"),
    )
    foreign_style_sheet = _resealed(
        v2_asset_sheet(),
        record_id=uid("proof-foreign-style-sheet"),
        asset_role="style",
        subject_id="style",
        asset_id=foreign_asset,
    )

    def asset_row(asset_id: uuid.UUID, season_id: uuid.UUID, sha: str) -> None:
        tx.execute(
            "INSERT INTO assets (id, asset_kind, object_key, sha256, size_bytes, media_type,"
            " state, provenance, season_id, descriptor) VALUES (%s, 'IMAGE', %s, %s, 1,"
            " 'image/png', 'ACCEPTED', 'ORIGINAL_FIXTURE', %s, %s)",
            (asset_id, f"fixtures/{asset_id}", sha, season_id, jsonb({})),
        )

    with world.db.transaction() as tx:
        insert_row(
            tx,
            "seasons",
            {"id": SEASON_ID, "state": "PROPOSED", "title_th": "ตัวอย่าง", "title_en": "Example"},
        )
        insert_row(
            tx,
            "episodes",
            {
                "id": EP1_ID,
                "season_id": SEASON_ID,
                "episode_number": 1,
                "state": "PLANNED",
                "approved_scope_hash": canonical_hash(season_scope()),
            },
        )
        insert_row(
            tx,
            "seasons",
            {"id": other_season, "state": "PROPOSED", "title_th": "อื่น", "title_en": "Other"},
        )
        asset_row(own_prop_sheet.asset_id, SEASON_ID, own_prop_sheet.asset_sha256)
        asset_row(own_plate_asset, SEASON_ID, h("stall-geometry"))
        asset_row(foreign_asset, other_season, h("foreign-plate-geometry"))
        link_season_owner(tx, SEASON_ID, world.owner_id, source="CREATOR_AT_CREATION")
        # A verified proposal whose scope matches its hash shows arc and cast.
        tx.execute(
            "INSERT INTO season_proposals (id, season_id, scope_version, scope, scope_hash,"
            " status) VALUES (%s, %s, 1, %s, %s, 'PROPOSED')",
            (
                uid("proof-proposal"),
                SEASON_ID,
                jsonb(season_scope()),
                canonical_hash(season_scope()),
            ),
        )
    StoryV2Store(world.db).save_bundle(
        [
            pack,
            v2_directing_manifest(),
            v2_wardrobe_bible(),
            v2_wardrobe_assignment(),
            v2_style_bible(),
            own_plate_sheet,
            own_prop_sheet,
            foreign_prop_sheet,
            foreign_layout,
            foreign_style_sheet,
            v2_prompt_manifest(),
        ]
    )

    page = client.get(f"/ui/seasons/{SEASON_ID}/workbench")
    assert page.status_code == 200
    # F5: the verified PROPOSED scope is shown honestly — never as "approved".
    assert "Season scope — arc and cast" in page.text
    assert "approved" not in page.text.split("Season scope")[1].split("</section>")[0].lower()
    assert "proposed" in page.text.lower()
    # F2: own proven sheets appear; the foreign season's never do.
    assert "ledger" in page.text, "the season's own prop sheet is displayed"
    assert "stall" in page.text, "the proven location layout is displayed"
    assert str(uid("proof-foreign-prop-sheet")) not in page.text
    assert str(uid("proof-foreign-layout")) not in page.text
    assert "location/stall" in page.text, "the season's own plate asset sheet is listed"
    assert str(uid("proof-foreign-style-sheet")) not in page.text, "foreign style sheet invisible"

    # F4/F5: tampered content with stale hashes becomes unknowns, never content.
    with world.db.transaction() as tx:
        _tamper_current(tx, "SceneWardrobeAssignment", "scene_id", '"tampered-scene"')
        _tamper_current(tx, "PromptManifest", "prompt_text", '"tampered prompt"')
        # The proposal's scope is likewise immutable: a v2 row with edited content
        # but v1's STALE hash is the tampered-scope shape.
        v1 = tx.fetchone(
            "SELECT scope, scope_hash FROM season_proposals WHERE season_id = %s"
            " AND scope_version = 1",
            (SEASON_ID,),
        )
        tx.execute(
            "INSERT INTO season_proposals (id, season_id, scope_version, scope, scope_hash,"
            " status) VALUES (%s, %s, 2, jsonb_set(%s, '{title_en}', '\"Tampered Title\"'),"
            " %s, 'PROPOSED')",
            (
                uid("proof-tampered-proposal"),
                SEASON_ID,
                jsonb(dict(v1["scope"])),
                v1["scope_hash"],
            ),
        )
    page = client.get(f"/ui/seasons/{SEASON_ID}/workbench")
    assert page.status_code == 200
    assert "tampered" not in page.text.lower(), "unverified content is never displayed"
    assert "wardrobe assignment failed verification" in page.text
    assert "prompt manifest failed verification" in page.text
    assert "scope failed hash verification" in page.text
    assert "/ui/media/" not in page.text, "no media link from an unverified document"
    assert "Tampered Title" not in page.text

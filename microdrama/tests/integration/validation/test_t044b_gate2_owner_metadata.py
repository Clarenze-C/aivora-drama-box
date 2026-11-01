"""T044b composed validation: the owner metadata path through the real services.

One composed offline run driven to (not through) Gate 2: the owner signs in and
submits release metadata for every exact current slot on the real episode page,
the preparation seals the V2 manifest without any approval event, the existing
Gate 2 Approve binds that exact hash, and the scheduler's own live-binding +
command projection carry the exact owner values to (never into) transport. No
provider operation is opened anywhere in this path.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.jobs import EpisodeStepInput
from microdrama.core.http import human_session_dependency
from microdrama.pipeline.conditions import MOCK_OUTPUT_ROUTE
from microdrama.pipeline.runner import MockPipelineRunner
from microdrama.publishing import metadata as metadata_versions
from microdrama.publishing.commands import publication_command_for_post
from microdrama.review import build_router

pytestmark = pytest.mark.db

OWNER = "t044b-composed-owner"
PASSWORD = "t044b-not-a-real-password"

SLOT_TITLES = {
    "YOUTUBE": "หนี้ที่แม่ไม่เคยบอก ตอนเต็ม",
    "FACEBOOK": "หนี้ที่แม่ไม่เคยบอก รวมคลิปเดียว",
    "TIKTOK": "หนี้ที่แม่ไม่เคยบอก คลิปสั้น",
    "INSTAGRAM": "หนี้ที่แม่ไม่เคยบอก รีลส์",
}
CAPTION = "เรื่องราวต้นฉบับของแม่และลูกสาว ดูตอนแรกได้แล้ว"
DESCRIPTION = "ละครสั้นต้นฉบับภาษาไทย สร้างด้วยระบบอัตโนมัติ"
HASHTAGS = "ละครไทย, ต้นฉบับ, ครอบครัว"
CTA = "ติดตามตอนต่อไป"

FIELDSET = '<fieldset data-testid="metadata-slot"'


def _form_chunk(html: str, testid: str) -> str:
    start = html.index(f'data-testid="{testid}"')
    return html[start : html.index("</form>", start)]


def _parse_metadata_form(html: str) -> dict:
    chunk = _form_chunk(html, "metadata-form")
    parsed: dict = {
        "package_hash": re.search(r'name="package_hash" value="([^"]+)"', chunk).group(1),
        "slots": [],
    }
    for part in chunk.split(FIELDSET)[1:]:
        sid = re.search(r'data-slot="([^"]+)"', part).group(1)
        platform = re.search(r"<legend>([^<·]+)·", part.replace(" ", "")).group(1)
        parsed["slots"].append(
            {
                "slot_id": sid,
                "platform": platform,
                "disclosures": re.findall(
                    rf'name="md_{re.escape(sid)}_disclosures" value="([^"]+)"', part
                ),
                "covers": re.findall(r'<option value="([0-9a-f]{8}-[0-9a-f-]{27})"', part),
            }
        )
    return parsed


@pytest.fixture
def gate2_world(validation_world):
    """A composed world driven to an undecided Gate 2 package (everything but the decision)."""
    runner = MockPipelineRunner(validation_world, owner_username=OWNER, owner_password=PASSWORD)
    season_id = runner.w01_research()
    runner.gate1(season_id)
    runner.w02_compile(season_id)
    episode_id = runner.create_episode(season_id, number=1)
    runner.w03_write(episode_id)
    runner.w04_references(episode_id)
    runner.w05_render(episode_id)
    runner.w06_edit(episode_id)
    runner.w07_qa(episode_id)
    runner._enqueue(
        "review.prepare_package",
        EpisodeStepInput(episode_id=episode_id),
        episode_id=episode_id,
        semantic_key=f"review.prepare_package:{episode_id}:1",
    )
    runner._drain()
    episode = runner._row("SELECT state FROM episodes WHERE id = %s", (episode_id,))
    assert episode["state"] == "AWAITING_FINAL_REVIEW"
    return validation_world, runner, season_id, episode_id


def _page_client(world):
    router = build_router(
        world.review,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
    )
    app = create_app(AppComponents(settings=world.settings, routers=[router]))
    return TestClient(app, follow_redirects=False)


def _sign_in(client: TestClient) -> str:
    page = client.get("/auth/login")
    token = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/auth/login",
        data={"username": OWNER, "password": PASSWORD, "login_csrf": token},
    )
    assert response.status_code == 303, response.text
    csrf = client.cookies.get("md_csrf")
    assert csrf
    return csrf


def test_owner_metadata_survives_from_the_form_to_the_scheduled_command(gate2_world) -> None:
    world, runner, season_id, episode_id = gate2_world

    # The episode's not-yet-released catalog entry (version 1) backs catalog_version.
    world.memberships.catalog.record_not_released(
        season_id=season_id, episode_id=episode_id, episode_number=1
    )
    # One package cover becomes selectable: its recorded license route resolves to the
    # seeded ELIGIBLE MODEL_OUTPUT rights row (what live submit re-verifies).
    cover = runner._row(
        "SELECT m->>'asset_id' AS asset_id FROM release_packages p, "
        "jsonb_array_elements(p.body->'media') m "
        "WHERE p.episode_id = %s AND p.status = 'READY' AND m->>'role' = 'cover' LIMIT 1",
        (episode_id,),
    )
    assert cover is not None, "the composed package carries cover media"
    with world.db.transaction() as tx:
        tx.execute(
            "UPDATE assets SET license_refs = %s::jsonb WHERE id = %s",
            (json.dumps([MOCK_OUTPUT_ROUTE]), cover["asset_id"]),
        )

    client = _page_client(world)
    csrf = _sign_in(client)
    page = client.get(f"/ui/episodes/{episode_id}")
    assert page.status_code == 200
    parsed = _parse_metadata_form(page.text)
    assert len(parsed["slots"]) >= 2, "the composed release scope has several exact slots"
    assert all(slot["disclosures"] for slot in parsed["slots"])
    approvals_before = runner._row("SELECT count(*) AS n FROM approval_events")["n"]

    pairs: list[tuple[str, str]] = [
        ("csrf_token", csrf),
        ("package_hash", parsed["package_hash"]),
        ("policy_mutable_fields", "title"),
        ("policy_mutable_fields", "caption"),
        ("policy_mutable_fields", "description"),
        ("policy_mutable_fields", "hashtags"),
        ("policy_cooldown_hours", "24"),
        ("policy_max_substantive_edits", "2"),
    ]
    submitted: dict[str, dict] = {}
    for slot in parsed["slots"]:
        sid = slot["slot_id"]
        title = SLOT_TITLES[slot["platform"].upper()]
        values = {
            "title": title,
            "caption": CAPTION,
            "description": DESCRIPTION,
            "hashtags": ["ละครไทย", "ต้นฉบับ", "ครอบครัว"],
            "disclosures": sorted(slot["disclosures"]),
            "cover": slot["covers"][0] if slot["covers"] else None,
            "cta": CTA,
        }
        submitted[sid] = values
        pairs += [
            ("md_slot", sid),
            (f"md_{sid}_title", title),
            (f"md_{sid}_caption", CAPTION),
            (f"md_{sid}_description", DESCRIPTION),
            (f"md_{sid}_hashtags", HASHTAGS),
            (f"md_{sid}_links", ""),
        ]
        pairs += [(f"md_{sid}_disclosures", value) for value in slot["disclosures"]]
        pairs.append((f"md_{sid}_cover", values["cover"] or ""))
        pairs.append((f"md_{sid}_cta", CTA))
    body: dict[str, object] = {}
    for key, value in pairs:
        if key in body:
            current = body[key]
            body[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            body[key] = value

    response = client.post(f"/ui/episodes/{episode_id}/metadata", data=body)
    assert response.status_code == 303, response.text
    # The preparation decided nothing and recorded no third human gate event.
    assert runner._row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "AWAITING_FINAL_REVIEW"
    )
    assert runner._row("SELECT count(*) AS n FROM approval_events")["n"] == approvals_before

    manifest_row = runner._row(
        "SELECT payload FROM release_approval_manifests WHERE release_package_hash = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (parsed["package_hash"],),
    )
    manifest = manifest_row["payload"]
    assert manifest["approval_manifest_sha256"] in client.get(f"/ui/episodes/{episode_id}").text
    assert {slot["slot_id"] for slot in manifest["slots"]} == set(submitted)
    for slot in manifest["slots"]:
        wanted = submitted[slot["slot_id"]]
        assert slot["title"] == wanted["title"]  # per-slot values stay per-slot
        assert slot["hashtags"] == wanted["hashtags"]
        assert sorted(slot["disclosures"]) == wanted["disclosures"]
        assert slot["catalog_version"] == 1
        assert slot["source"] == "OWNER_APPROVED"

    # The existing Gate 2 Approve binds the exact prepared hash (no new gate type).
    approve = _form_chunk(client.get(f"/ui/episodes/{episode_id}").text, "approve-form")
    fields = [
        (m.group(1), m.group(2))
        for m in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', approve)
    ]
    binding = dict(fields)
    assert binding["release_manifest_hash"] == manifest["approval_manifest_sha256"]
    fields += [("action", "APPROVE"), ("idempotency_key", f"gate2:{episode_id}:owner")]
    approve_body: dict[str, object] = {}
    for key, value in fields:
        if key in approve_body:
            current = approve_body[key]
            approve_body[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            approve_body[key] = value
    response = client.post(f"/ui/episodes/{episode_id}/review", data=approve_body)
    assert response.status_code == 303, response.text
    assert runner._row("SELECT state FROM episodes WHERE id = %s", (episode_id,))["state"] == (
        "RELEASE_APPROVED"
    )
    gate2_events = runner._rows(
        "SELECT * FROM approval_events WHERE entity_id = %s AND gate_type = 'EPISODE_FINAL'",
        (episode_id,),
    )
    assert len(gate2_events) == 1
    assert gate2_events[0]["release_manifest_hash"] == manifest["approval_manifest_sha256"]

    # The scheduler's release drain creates the slot posts; then the exact live-mode
    # projection the scheduler performs (approved_live_binding + command builder)
    # carries the owner's values. No submit job runs, no transport is opened.
    runner._drain()
    posts = runner._rows(
        "SELECT * FROM platform_posts WHERE episode_id = %s ORDER BY release_slot, platform",
        (episode_id,),
    )
    assert posts
    # The path stops at the command: every slot is still only SCHEDULED and the
    # publication lane opened no provider operation (earlier stages' research
    # operations are unrelated to transport).
    assert {post["state"] for post in posts} == {"SCHEDULED"}
    assert all(post["provider_operation_id"] is None for post in posts)
    assert (
        runner._row(
            "SELECT count(*) AS n FROM provider_operations WHERE operation_kind LIKE 'publish.%%'"
        )["n"]
        == 0
    )
    for post in posts:
        package = runner._row(
            "SELECT id, body FROM release_packages WHERE id = %s AND status = 'APPROVED'",
            (post["release_package_id"],),
        )
        with world.db.transaction(readonly=True) as tx:
            release_manifest, approved_slot = metadata_versions.approved_live_binding(
                tx, post=dict(post), approval_event_id=post["approval_event_id"]
            )
        command = publication_command_for_post(
            None,
            post=dict(post),
            package_body=package["body"],
            approval_event_id=post["approval_event_id"],
            metadata=None,
            metadata_version_id=None,
            release_manifest=release_manifest,
            approved_slot_metadata=approved_slot,
        )
        wanted = submitted[f"slot-{post['dedupe_key']}"]
        assert command.metadata.title == wanted["title"]
        assert command.metadata.caption == CAPTION
        assert command.metadata.description == DESCRIPTION
        assert command.metadata.hashtags == wanted["hashtags"]
        assert sorted(kind.value for kind in command.metadata.disclosures) == wanted["disclosures"]
        assert command.metadata.catalog_version == 1
        if wanted["cover"]:
            assert str(command.metadata.cover_asset_id) == wanted["cover"]
        else:
            assert command.metadata.cover_asset_id is None  # absence is bound, not filled in
        assert command.metadata.cta_text == CTA
        assert command.release_manifest_sha256 == manifest["approval_manifest_sha256"]
        assert command.approved_metadata_sha256 == approved_slot.content_sha256

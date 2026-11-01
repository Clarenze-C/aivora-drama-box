"""T044b: the owner Gate 2 metadata form through the real HTTP surface.

The owner prepares release metadata for every exact current slot; the preparation
seals the V2 manifest (no ApprovalEvent, no decision change), the same page shows
its exact hash, the existing Approve & schedule form binds it, and only current
owner values survive to the publication command projection. Stale, foreign,
duplicate, unbacked or malformed submissions prepare nothing.
"""

import json
import re
import threading
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from review_support import World
from test_ui import form_body, login_token

from microdrama.api.app import AppComponents, create_app
from microdrama.contracts.enums import (
    AssetKind,
    CapabilityOperation,
    CapabilitySupport,
    DisclosureKind,
    EvidenceSource,
    Platform,
    PrincipalKind,
)
from microdrama.contracts.errors import Conflict
from microdrama.contracts.examples import ACCOUNT_YT
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.release import CapabilityRecord
from microdrama.contracts.season import ApprovalCommand
from microdrama.contracts.v2 import ApprovedSlotMetadata, ReleaseApprovalManifest
from microdrama.core.http import human_session_dependency
from microdrama.persistence import jsonb
from microdrama.persistence.db import insert_row
from microdrama.publishing import metadata as metadata_versions
from microdrama.publishing.commands import publication_command_for_post
from microdrama.review import build_router
from microdrama.review.packages import (
    current_release_approval_manifest,
    store_approved_slot_metadata,
)

pytestmark = pytest.mark.db
PASSWORD = "a-long-t044b-password"
RIGHTS_ROUTE = "t044b-output-route"
ALL_POLICY_FIELDS = ("title", "caption", "description", "hashtags", "cover", "cta")
DEFAULT_POLICY = [("policy_mutable_fields", field) for field in ALL_POLICY_FIELDS] + [
    ("policy_cooldown_hours", "24"),
    ("policy_max_substantive_edits", "2"),
]

TITLE = "หนี้ที่แม่ไม่เคยบอก ตอนที่ ๑"
CAPTION = "เรื่องราวต้นฉบับของแม่และลูกสาว"
DESCRIPTION = "ละครสั้นต้นฉบับภาษาไทย ตอนแรก"
HASHTAGS = "ละครไทย, ต้นฉบับ, ครอบครัว"
CTA = "ติดตามตอนต่อไป"


def _client(world: World, offline_settings) -> TestClient:
    router = build_router(
        world.service,
        human_session=human_session_dependency(world.auth),
        auth=world.auth,
        cookie_secure=False,
    )
    app = create_app(AppComponents(settings=offline_settings, routers=[router]))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def web(world: World, offline_settings) -> TestClient:
    world.set_owner(world.auth.create_owner("t044b.owner", PASSWORD))
    return _client(world, offline_settings)


def sign_in(client: TestClient, username: str = "t044b.owner") -> str:
    response = client.post(
        "/auth/login",
        data={"username": username, "password": PASSWORD, "login_csrf": login_token(client)},
    )
    assert response.status_code == 303, response.text
    csrf = client.cookies.get("md_csrf")
    assert csrf
    return csrf


# --- fixture helpers ----------------------------------------------------------------------


def seed_capability(
    world: World,
    capability_id: uuid.UUID,
    disclosures: list[str],
    *,
    enabled: bool = True,
    current: bool = True,
    account_ref: str = ACCOUNT_YT,
) -> None:
    record = CapabilityRecord(
        capability_id=capability_id,
        version=1,
        platform=Platform.YOUTUBE,
        provider_route=f"fake-youtube-{uuid.uuid4().hex[:8]}",
        account_ref=account_ref,
        account_type="channel",
        operations={
            CapabilityOperation.UPLOAD_FULL_VIDEO: CapabilitySupport.SUPPORTED_TESTED,
            CapabilityOperation.STATUS: CapabilitySupport.SUPPORTED_TESTED,
            CapabilityOperation.READBACK: CapabilitySupport.SUPPORTED_TESTED,
        },
        supported_disclosures=[DisclosureKind(value) for value in disclosures],
        evidence=[EvidenceRef(source=EvidenceSource.FAKE_FIXTURE, ref="fixture:t044b-capability")],
        verified_at=world.clock.now(),
        enabled=enabled,
    )
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "capability_registry",
            {
                "id": uuid.uuid4(),
                "capability_id": capability_id,
                "version": 1,
                "platform": Platform.YOUTUBE.value,
                "provider_route": record.provider_route,
                "account_ref": account_ref,
                "record": jsonb(record),
                "enabled": enabled,
                "evidence_sources": jsonb([EvidenceSource.FAKE_FIXTURE.value]),
                "verified_at": world.clock.now(),
                "current": current,
            },
        )


def seed_output_rights(world: World) -> None:
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "rights_registry",
            {
                "id": uuid.uuid4(),
                "rights_route_id": RIGHTS_ROUTE,
                "version": 1,
                "subject_kind": "MODEL_OUTPUT",
                "subject_ref": RIGHTS_ROUTE,
                "territories": jsonb(["TH", "US"]),
                "commercial_use": True,
                "output_release_allowed": True,
                "required_disclosures": jsonb([DisclosureKind.AI_GENERATED_CONTENT.value]),
                "evidence": jsonb(
                    [
                        {
                            "source": EvidenceSource.FAKE_FIXTURE.value,
                            "ref": "fixture:t044b-rights",
                            "sha256": "ab" * 32,
                        }
                    ]
                ),
                "status": "ELIGIBLE",
            },
        )


def seed_catalog(world: World, season_id, episode_id, *, public_url: str | None) -> None:
    with world.db.transaction() as tx:
        insert_row(
            tx,
            "membership_catalog",
            {
                "id": uuid.uuid4(),
                "season_id": season_id,
                "episode_id": episode_id,
                "catalog_version": 1,
                "public_state": "NOT_RELEASED",
                "media_finished_and_approved": False,
                "public_url": public_url,
                "body": jsonb(
                    {
                        "entry_id": str(uuid.uuid4()),
                        "season_id": str(season_id),
                        "episode_id": str(episode_id),
                        "episode_number": 1,
                        "catalog_version": 1,
                        "public_state": "NOT_RELEASED",
                        "media_finished_and_approved": False,
                        "provenance": "FAKE_SYNTHETIC",
                    }
                ),
            },
        )


def preparable_episode(
    world: World, *, cover: bool = True, catalog_url: str | None = "https://example.invalid/ep/1"
):
    """A Gate 2 episode whose metadata form is fully preparable (capability, rights, catalog)."""
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    extra: list[tuple[uuid.UUID, str, str]] = []
    cover_asset = None
    if cover:
        cover_asset = world.asset(
            season_id=season_id,
            episode_id=episode_id,
            kind=AssetKind.IMAGE,
            data=b"t044b-cover-bytes",
            media_type="image/jpeg",
        )
        extra.append((cover_asset[0], cover_asset[1], "cover"))
    package = world.package(
        season_id=season_id, episode_id=episode_id, master=master, extra_media=extra
    )
    world.store_package(package)
    plan = package.release_scope[0]
    seed_capability(world, plan.capability_id, [d.value for d in plan.disclosures])
    if cover_asset is not None:
        seed_output_rights(world)
        world.row_exec(
            "UPDATE assets SET license_refs = %s::jsonb WHERE id = %s",
            (json.dumps([RIGHTS_ROUTE]), cover_asset[0]),
        )
    if catalog_url is not None:
        seed_catalog(world, season_id, episode_id, public_url=catalog_url)
    return season_id, episode_id, package, cover_asset


# --- page parsing -------------------------------------------------------------------------


def _hidden_fields(chunk: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', chunk)
    }


def _hidden_pairs(chunk: str) -> list[tuple[str, str]]:
    """All hidden inputs as pairs: repeated ``media_hash`` fields must stay repeated."""
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', chunk)
    ]


def _form_chunk(html: str, testid: str) -> str:
    start = html.index(f'data-testid="{testid}"')
    return html[start : html.index("</form>", start)]


FIELDSET = '<fieldset data-testid="metadata-slot"'


def _parse_metadata_form(html: str) -> dict:
    chunk = _form_chunk(html, "metadata-form")
    parsed = {
        "package_hash": re.search(r'name="package_hash" value="([^"]+)"', chunk).group(1),
        "slots": [],
    }
    for part in chunk.split(FIELDSET)[1:]:
        sid = re.search(r'data-slot="([^"]+)"', part).group(1)
        parsed["slots"].append(
            {
                "slot_id": sid,
                "disclosures": re.findall(
                    rf'name="md_{re.escape(sid)}_disclosures" value="([^"]+)"', part
                ),
                "covers": re.findall(r'<option value="([0-9a-f]{8}-[0-9a-f-]{27})"', part),
            }
        )
    return parsed


def _submission(
    parsed: dict,
    csrf: str,
    *,
    cover: bool = True,
    links: str = "",
    slots_override: list[dict] | None = None,
    package_hash: str | None = None,
    policy_pairs: list[tuple[str, str]] | None = None,
    omit: set[str] | None = None,
    values: dict[str, str] | None = None,
) -> dict:
    omit = omit or set()
    values = values or {}
    pairs: list[tuple[str, str]] = [
        ("csrf_token", csrf),
        ("package_hash", package_hash or parsed["package_hash"]),
    ]
    pairs.extend(DEFAULT_POLICY if policy_pairs is None else policy_pairs)
    for slot in parsed["slots"] if slots_override is None else slots_override:
        sid = slot["slot_id"]
        pairs.append(("md_slot", sid))
        for field, default in (
            ("title", TITLE),
            ("caption", CAPTION),
            ("description", DESCRIPTION),
            ("hashtags", HASHTAGS),
            ("links", links),
        ):
            if field not in omit:
                pairs.append((f"md_{sid}_{field}", values.get(field, default)))
        if "disclosures" not in omit:
            for disclosure in slot["disclosures"]:
                pairs.append((f"md_{sid}_disclosures", disclosure))
        if "cover" not in omit:
            pairs.append((f"md_{sid}_cover", slot["covers"][0] if cover and slot["covers"] else ""))
        if "cta" not in omit:
            pairs.append((f"md_{sid}_cta", values.get("cta", CTA)))
    return form_body(pairs)


def _current_manifest(world: World, episode_id):
    row = world.row(
        "SELECT id, package_hash FROM release_packages WHERE episode_id = %s "
        "AND status <> 'SUPERSEDED' ORDER BY version DESC LIMIT 1",
        (episode_id,),
    )
    with world.db.transaction(readonly=True) as tx:
        manifest = current_release_approval_manifest(
            tx, package_id=row["id"], package_hash=row["package_hash"]
        )
    return manifest


def _approve_via_form(web: TestClient, world: World, episode_id, csrf: str, key: str) -> None:
    pairs = _hidden_pairs(_form_chunk(web.get(f"/ui/episodes/{episode_id}").text, "approve-form"))
    pairs += [("action", "APPROVE"), ("idempotency_key", key), ("csrf_token", csrf)]
    response = web.post(f"/ui/episodes/{episode_id}/review", data=form_body(pairs))
    assert response.status_code == 303, response.text
    assert world.episode_state(episode_id)[0] == "RELEASE_APPROVED"


def _post_row(world: World, episode_id, package):
    row = world.row(
        "SELECT id, body FROM release_packages WHERE episode_id = %s AND status = 'APPROVED'",
        (episode_id,),
    )
    approval = world.row(
        "SELECT id FROM approval_events WHERE entity_id = %s AND gate_type = 'EPISODE_FINAL' "
        "AND action = 'APPROVE'",
        (episode_id,),
    )
    plan = package.release_scope[0]
    return (
        {
            "id": uuid.uuid4(),
            "episode_id": episode_id,
            "release_package_id": row["id"],
            "dedupe_key": plan.slot.dedupe_key,
            "release_slot": "full",
        },
        row["body"],
        approval["id"],
    )


# --- the form itself ----------------------------------------------------------------------


def test_the_gate2_page_shows_one_field_set_per_exact_current_slot(
    web: TestClient, world: World
) -> None:
    sign_in(web)
    _season, episode_id, package, cover_asset = preparable_episode(world)
    page = web.get(f"/ui/episodes/{episode_id}").text
    parsed = _parse_metadata_form(page)
    assert parsed["package_hash"] == package.package_hash
    assert [slot["slot_id"] for slot in parsed["slots"]] == [
        f"slot-{plan.slot.dedupe_key}" for plan in package.release_scope
    ]
    assert parsed["slots"][0]["disclosures"] == ["AI_GENERATED_CONTENT"]
    assert parsed["slots"][0]["covers"] == [str(cover_asset[0])]
    # Server-loaded bindings never appear as editable form values.
    assert f'value="{package.package_id}"' not in page


def test_the_form_is_absent_without_a_current_undecided_package(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, _package, _cover = preparable_episode(world)
    _approve_via_form(web, world, episode_id, csrf, "t044b-approve-0001")
    assert 'data-testid="metadata-form"' not in web.get(f"/ui/episodes/{episode_id}").text


def test_a_cover_may_be_explicitly_absent_and_the_manifest_binds_the_absence(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, _package, _cover_asset = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    assert parsed["slots"][0]["covers"], "the package offers a selectable cover"

    response = web.post(
        f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf, cover=False)
    )
    assert response.status_code == 303, response.text
    slot = _current_manifest(world, episode_id).slots[0]
    assert slot.cover_asset_id is None
    assert slot.cover_asset_version is None
    assert slot.cover_asset_sha256 is None
    assert slot.cover_rights is None  # the sealed absence, not an implicit blank


# --- preparation --------------------------------------------------------------------------


def test_owner_submits_metadata_and_gets_the_exact_manifest_without_a_decision(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, package, cover_asset = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    approvals_before = world.count("SELECT COUNT(*) FROM approval_events")

    response = web.post(
        f"/ui/episodes/{episode_id}/metadata",
        data=_submission(parsed, csrf, links="https://example.invalid/ep/1"),
    )
    assert response.status_code == 303, response.text
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"
    assert world.count("SELECT COUNT(*) FROM approval_events") == approvals_before

    manifest = _current_manifest(world, episode_id)
    assert manifest is not None
    slot = manifest.slots[0]
    assert slot.title == TITLE
    assert slot.caption == CAPTION
    assert slot.description == DESCRIPTION
    assert slot.hashtags == ["ละครไทย", "ต้นฉบับ", "ครอบครัว"]
    assert slot.links == ["https://example.invalid/ep/1"]
    assert slot.disclosures == [DisclosureKind.AI_GENERATED_CONTENT]
    assert slot.catalog_version == 1
    assert slot.cover_asset_id == cover_asset[0]
    assert slot.cover_asset_version == 1
    assert slot.cover_asset_sha256 == cover_asset[1]
    assert slot.cover_rights is not None
    assert slot.cover_rights.rights_route_id == RIGHTS_ROUTE
    assert slot.cta_text == CTA
    assert slot.source == "OWNER_APPROVED"
    assert slot.metadata_policy_id == manifest.metadata_policy.policy_id
    assert sorted(manifest.metadata_policy.mutable_fields) == sorted(ALL_POLICY_FIELDS)

    page = web.get(f"/ui/episodes/{episode_id}").text
    assert manifest.approval_manifest_sha256 in page
    approve = _hidden_fields(_form_chunk(page, "approve-form"))
    assert approve["release_manifest_hash"] == manifest.approval_manifest_sha256


def test_approve_binds_the_prepared_manifest_and_no_third_gate_event_appears(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, package, _cover = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    assert (
        web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf)).status_code
        == 303
    )
    manifest = _current_manifest(world, episode_id)
    _approve_via_form(web, world, episode_id, csrf, "t044b-approve-0002")

    events = world.approvals(episode_id)
    assert len(events) == 1  # exactly one Gate 2 human decision; preparation added none
    assert events[0]["release_manifest_hash"] == manifest.approval_manifest_sha256
    assert events[0]["package_hash"] == package.package_hash
    assert world.count("SELECT COUNT(*) FROM approval_events") == 2  # Gate 1 seed + Gate 2


# --- the publication command projection ---------------------------------------------------


def test_owner_values_reach_the_publication_command_projection(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, package, cover_asset = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf))
    _approve_via_form(web, world, episode_id, csrf, "t044b-approve-0003")

    post, package_body, approval_id = _post_row(world, episode_id, package)
    with world.db.transaction(readonly=True) as tx:
        manifest, approved_slot = metadata_versions.approved_live_binding(
            tx, post=post, approval_event_id=approval_id
        )
    command = publication_command_for_post(
        None,
        post=post,
        package_body=package_body,
        approval_event_id=approval_id,
        metadata=None,
        metadata_version_id=None,
        release_manifest=manifest,
        approved_slot_metadata=approved_slot,
    )
    assert command.metadata.title == TITLE
    assert command.metadata.caption == CAPTION
    assert command.metadata.description == DESCRIPTION
    assert command.metadata.hashtags == ["ละครไทย", "ต้นฉบับ", "ครอบครัว"]
    assert command.metadata.disclosures == [DisclosureKind.AI_GENERATED_CONTENT]
    assert command.metadata.cover_asset_id == cover_asset[0]
    assert command.metadata.cover_asset_version == 1
    assert command.metadata.cover_asset_sha256 == cover_asset[1]
    assert command.metadata.cta_text == CTA
    assert command.release_manifest_sha256 == manifest.approval_manifest_sha256
    assert command.approved_metadata_sha256 == approved_slot.content_sha256
    assert command.metadata_policy_id == manifest.metadata_policy.policy_id


def test_v1_only_approval_has_no_live_metadata_authority(web: TestClient, world: World) -> None:
    sign_in(web)
    _season, episode_id, package, _cover = preparable_episode(world)
    # Approve with no prepared manifest: the OFFLINE_MOCK lane still allows it.
    world.service.decide_episode(
        world.human(), episode_id, world.gate2_command(episode_id, package)
    )
    post, _body, approval_id = _post_row(world, episode_id, package)
    with pytest.raises(Conflict, match="V1-only approval"):
        with world.db.transaction(readonly=True) as tx:
            metadata_versions.approved_live_binding(tx, post=post, approval_event_id=approval_id)


def test_stale_slot_metadata_blocks_the_command_before_any_transport(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, package, _cover = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf))
    _approve_via_form(web, world, episode_id, csrf, "t044b-approve-0004")

    post, _body, approval_id = _post_row(world, episode_id, package)
    with world.db.transaction(readonly=True) as tx:
        _manifest, approved_slot = metadata_versions.approved_live_binding(
            tx, post=post, approval_event_id=approval_id
        )
    changed = ApprovedSlotMetadata.seal(
        **{
            **approved_slot.model_dump(mode="python"),
            "record_id": uuid.uuid4(),
            "metadata_id": uuid.uuid4(),
            "metadata_version": approved_slot.metadata_version + 1,
            "version": approved_slot.version + 1,
            "caption": "a substantively changed caption",
        }
    )
    with world.db.transaction() as tx:
        store_approved_slot_metadata(tx, changed)
    with pytest.raises(Conflict, match="absent from Gate 2 manifest"):
        with world.db.transaction(readonly=True) as tx:
            metadata_versions.approved_live_binding(tx, post=post, approval_event_id=approval_id)


# --- rejections ---------------------------------------------------------------------------


def _assert_nothing_prepared(world: World, episode_id) -> None:
    assert world.count("SELECT COUNT(*) FROM release_approval_manifests") == 0
    assert world.count("SELECT COUNT(*) FROM approved_slot_metadata") == 0
    assert world.count("SELECT COUNT(*) FROM approval_events") == 1  # the Gate 1 seed only
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_slot",
        "duplicate_slot",
        "foreign_slot",
        "stale_package",
        "tampered_package",
        "unknown_cover",
        "unbacked_cover",
        "wrong_disclosures",
        "extra_disclosure",
        "disallowed_link",
        "non_https_link",
        "missing_title",
        "blank_title",
        "overlong_cta",
        "bad_cooldown",
        "bad_max_edits",
        "unknown_policy_field",
    ],
)
def test_disallowed_submissions_prepare_nothing(web: TestClient, world: World, mutation) -> None:
    csrf = sign_in(web)
    season_id, episode_id, package, cover_asset = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    slots = [dict(slot) for slot in parsed["slots"]]
    policy: list[tuple[str, str]] | None = None
    kwargs: dict = {}

    if mutation == "missing_slot":
        kwargs["slots_override"] = []
    elif mutation == "duplicate_slot":
        kwargs["slots_override"] = slots + [slots[0]]
    elif mutation == "foreign_slot":
        foreign = dict(slots[0])
        foreign["slot_id"] = f"slot-{'ff' * 32}"
        kwargs["slots_override"] = [foreign]
    elif mutation == "stale_package":
        # a newer current package makes the rendered form's binding stale
        recut = world.asset(season_id=season_id, episode_id=episode_id, data=b"t044b-recut")
        package_v2 = world.package(
            season_id=season_id, episode_id=episode_id, master=recut, version=2
        )
        world.store_package(package_v2)
        kwargs["package_hash"] = package.package_hash  # the pre-recut form's binding
    elif mutation == "tampered_package":
        kwargs["package_hash"] = "0" * 64
    elif mutation == "unknown_cover":
        slots[0]["covers"] = [str(uuid.uuid4())]
        kwargs["slots_override"] = slots
    elif mutation == "unbacked_cover":
        # the registry is append-only: point the cover at a route with no rights record
        world.row_exec(
            "UPDATE assets SET license_refs = %s::jsonb WHERE id = %s",
            (json.dumps(["t044b-route-without-rights"]), cover_asset[0]),
        )
    elif mutation == "wrong_disclosures":
        slots[0]["disclosures"] = []
        kwargs["slots_override"] = slots
    elif mutation == "extra_disclosure":
        slots[0]["disclosures"] = ["AI_GENERATED_CONTENT", "SYNTHETIC_VOICE"]
        kwargs["slots_override"] = slots
    elif mutation == "disallowed_link":
        kwargs["links"] = "https://elsewhere.example.org/not-in-catalog"
    elif mutation == "non_https_link":
        kwargs["links"] = "http://example.invalid/ep/1"
    elif mutation == "missing_title":
        kwargs["omit"] = {"title"}
    elif mutation == "blank_title":
        kwargs["values"] = {"title": "   "}
    elif mutation == "overlong_cta":
        kwargs["values"] = {"cta": "x" * 501}
    elif mutation == "bad_cooldown":
        policy = [
            ("policy_mutable_fields", "title"),
            ("policy_cooldown_hours", "12"),
            ("policy_max_substantive_edits", "2"),
        ]
    elif mutation == "bad_max_edits":
        policy = [
            ("policy_mutable_fields", "title"),
            ("policy_cooldown_hours", "24"),
            ("policy_max_substantive_edits", "3"),
        ]
    elif mutation == "unknown_policy_field":
        policy = [
            ("policy_mutable_fields", "everything"),
            ("policy_cooldown_hours", "24"),
            ("policy_max_substantive_edits", "2"),
        ]
    kwargs["policy_pairs"] = policy
    response = web.post(
        f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf, **kwargs)
    )
    assert response.status_code in (409, 422), (mutation, response.status_code)
    assert response.headers["content-type"].startswith("text/html")
    _assert_nothing_prepared(world, episode_id)


def test_an_unregistered_capability_binding_prepares_nothing(web: TestClient, world: World) -> None:
    csrf = sign_in(web)
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)  # the plan pins a capability id nothing registered
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    response = web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf))
    assert response.status_code == 409
    assert "is not registered" in response.text
    _assert_nothing_prepared(world, episode_id)


@pytest.mark.parametrize(
    ("variant", "seed_kwargs", "reason"),
    [
        ("disabled", {"enabled": False}, "is not enabled with verified evidence"),
        ("superseded", {"current": False}, "is superseded"),
        (
            "wrong_account",
            {"account_ref": "acct:somebody-elses-channel"},
            "not the platform/account this slot publishes to",
        ),
    ],
)
def test_a_registered_but_unusable_pinned_capability_row_blocks_preparation(
    web: TestClient, world: World, variant: str, seed_kwargs: dict, reason: str
) -> None:
    """The pinned (capability_id, version) row existing is not enough (review fix 1).

    A row that is disabled, no longer current, or registered for another
    platform/account than the slot's own must block the owner metadata
    preparation before ``prepare_release_approval_manifest`` stores anything.
    """
    csrf = sign_in(web)
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    seed_capability(
        world, package.release_scope[0].capability_id, ["AI_GENERATED_CONTENT"], **seed_kwargs
    )

    # The page itself already says why the slot cannot carry owner metadata.
    page = web.get(f"/ui/episodes/{episode_id}")
    assert page.status_code == 200
    assert reason in page.text

    parsed = _parse_metadata_form(page.text)
    response = web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf))
    assert response.status_code == 409, (variant, response.status_code)
    assert reason in response.text
    _assert_nothing_prepared(world, episode_id)


def test_metadata_post_needs_csrf_and_refuses_service_bearers(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    _season, episode_id, _package, _cover = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)

    no_csrf = _submission(parsed, csrf)
    no_csrf.pop("csrf_token")
    assert web.post(f"/ui/episodes/{episode_id}/metadata", data=no_csrf).status_code == 403
    assert (
        web.post(
            f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, "forged-token-value")
        ).status_code
        == 403
    )

    token = world.auth.issue_service_credential(
        f"service-worker:{uuid.uuid4().hex[:8]}", PrincipalKind.SERVICE_WORKER
    )
    response = web.post(
        f"/ui/episodes/{episode_id}/metadata",
        data=_submission(parsed, csrf),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "UNAUTHORIZED"
    _assert_nothing_prepared(world, episode_id)


def test_a_second_owner_prepares_nothing(web: TestClient, world: World, offline_settings) -> None:
    sign_in(web)
    _season, episode_id, package, _cover = preparable_episode(world)
    parsed = {
        "package_hash": package.package_hash,
        "slots": [
            {
                "slot_id": f"slot-{plan.slot.dedupe_key}",
                "disclosures": [d.value for d in plan.disclosures],
                "covers": [],
            }
            for plan in package.release_scope
        ],
    }
    other = _client(world, offline_settings)
    world.auth.create_owner("t044b.other", PASSWORD)
    assert (
        other.post(
            "/auth/login",
            data={
                "username": "t044b.other",
                "password": PASSWORD,
                "login_csrf": login_token(other),
            },
        ).status_code
        == 303
    )
    other_csrf = other.cookies.get("md_csrf")
    response = other.post(
        f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, other_csrf)
    )
    assert response.status_code == 404
    assert other.get(f"/ui/episodes/{episode_id}").status_code == 404
    _assert_nothing_prepared(world, episode_id)


# --- revision ------------------------------------------------------------------------------


def test_a_revision_invalidates_the_prepared_metadata_for_any_future_approval(
    web: TestClient, world: World
) -> None:
    csrf = sign_in(web)
    season_id, episode_id, package, _cover = preparable_episode(world)
    parsed = _parse_metadata_form(web.get(f"/ui/episodes/{episode_id}").text)
    assert (
        web.post(f"/ui/episodes/{episode_id}/metadata", data=_submission(parsed, csrf)).status_code
        == 303
    )
    stale_manifest = _current_manifest(world, episode_id)

    revise_pairs = _hidden_pairs(
        _form_chunk(web.get(f"/ui/episodes/{episode_id}").text, "revise-form")
    )
    revise_pairs += [
        ("action", "REVISE"),
        ("idempotency_key", "t044b-revise-0001"),
        ("feedback_category", "subtitles"),
        ("feedback_start", "00:12.500"),
        ("feedback_end", "00:15.500"),
        ("feedback_comment", "คำบรรยายผิดตำแหน่ง"),
        ("csrf_token", csrf),
    ]
    assert (
        web.post(f"/ui/episodes/{episode_id}/review", data=form_body(revise_pairs)).status_code
        == 303
    )
    assert world.episode_state(episode_id)[0] != "AWAITING_FINAL_REVIEW"
    assert 'data-testid="metadata-form"' not in web.get(f"/ui/episodes/{episode_id}").text

    # A newer package returns to the gate; the old manifest no longer binds it.
    world.row_exec(
        "UPDATE episodes SET state = 'AWAITING_FINAL_REVIEW', outcome = NULL WHERE id = %s",
        (episode_id,),
    )
    recut = world.asset(season_id=season_id, episode_id=episode_id, data=b"t044b-recut")
    package_v2 = world.package(season_id=season_id, episode_id=episode_id, master=recut, version=2)
    world.store_package(package_v2)
    seed_capability(world, package_v2.release_scope[0].capability_id, ["AI_GENERATED_CONTENT"])
    command_fields = world.gate2_command(episode_id, package_v2).model_dump(mode="python")
    command_fields["release_manifest_hash"] = stale_manifest.approval_manifest_sha256
    with pytest.raises(Conflict):
        world.service.decide_episode(
            world.human(), episode_id, ApprovalCommand.model_validate(command_fields)
        )
    page = web.get(f"/ui/episodes/{episode_id}").text
    assert _parse_metadata_form(page)["package_hash"] == package_v2.package_hash


# --- concurrent submissions (review fix 2) -----------------------------------------------


class _PostForm(dict):
    """A submitted form as the service reads it (starlette FormData's get/getlist)."""

    def getlist(self, name: str) -> list:
        value = self.get(name)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def _metadata_post_fields(meta: Any) -> _PostForm:
    """One fully valid owner submission for the loaded form context (service level)."""
    fields: dict[str, Any] = {
        "package_hash": meta.package_hash,
        "policy_mutable_fields": ["title"],
        "policy_cooldown_hours": "24",
        "policy_max_substantive_edits": "2",
        "md_slot": [slot.slot_id for slot in meta.slots],
    }
    for slot in meta.slots:
        sid = slot.slot_id
        fields.update(
            {
                f"md_{sid}_title": TITLE,
                f"md_{sid}_caption": CAPTION,
                f"md_{sid}_description": DESCRIPTION,
                f"md_{sid}_hashtags": HASHTAGS,
                f"md_{sid}_links": "",
                f"md_{sid}_disclosures": list(slot.disclosures),
                f"md_{sid}_cover": "",
                f"md_{sid}_cta": CTA,
            }
        )
    return _PostForm(fields)


def test_two_concurrent_submissions_of_one_form_never_share_a_version(world: World) -> None:
    """Two racing submissions of one prepared form on the real database (review fix 2).

    The whole preparation — context load, form conversion, slot metadata and
    manifest storage — runs under the episode row lock, so both responses are
    controlled (each a sealed manifest or a typed Conflict), no version is
    written twice, no raw database error or 500 surfaces, and nothing partial
    is left behind.
    """
    season_id, _scope = world.season(approved=True)
    episode_id = world.episode_with_budget(season_id)
    master = world.asset(season_id=season_id, episode_id=episode_id)
    package = world.package(season_id=season_id, episode_id=episode_id, master=master)
    world.store_package(package)
    seed_capability(world, package.release_scope[0].capability_id, ["AI_GENERATED_CONTENT"])
    service = world.service
    human = world.human()
    meta = service.gate2_metadata_form(human, episode_id)
    assert meta.open
    form = _metadata_post_fields(meta)  # one prepared form, submitted twice at once

    barrier = threading.Barrier(2)
    outcomes: list[object] = [None, None]

    def run(index: int) -> None:
        barrier.wait(timeout=30)
        try:
            outcomes[index] = service.submit_gate2_metadata(human, episode_id, form)
        except Exception as exc:  # the test must see every failure mode, typed or raw
            outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads)
    assert all(outcome is not None for outcome in outcomes)

    # Both responses are controlled: a sealed manifest or a typed Conflict — never a
    # raw database error, a 500-class error, or a half-written row set.
    for outcome in outcomes:
        assert isinstance(outcome, ReleaseApprovalManifest | Conflict), outcome
    winners = [o for o in outcomes if isinstance(o, ReleaseApprovalManifest)]
    assert winners, "at least one concurrent submission seals its manifest"

    # At most one manifest per version, and each winner sealed exactly one.
    assert world.count("SELECT COUNT(*) FROM release_approval_manifests") == len(winners)
    assert not world.row_all(
        "SELECT version FROM release_approval_manifests GROUP BY version HAVING count(*) > 1"
    )
    # The version race itself: no (slot, metadata_version) pair was written twice.
    assert not world.row_all(
        "SELECT slot_id, metadata_version FROM approved_slot_metadata "
        "GROUP BY slot_id, metadata_version HAVING count(*) > 1"
    )
    # No duplicate current slot metadata: exactly one current row per slot.
    assert not world.row_all(
        "SELECT slot_id FROM approved_slot_metadata WHERE is_current "
        "GROUP BY slot_id HAVING count(*) > 1"
    )
    # No partial approval: the gate is untouched and only the Gate 1 seed exists.
    assert world.count("SELECT COUNT(*) FROM approval_events") == 1
    assert world.episode_state(episode_id)[0] == "AWAITING_FINAL_REVIEW"

"""AT-09 reproduced independently: publication cannot duplicate or mis-release.

Duplicate webhook deliveries never repeat their effect; invalid signatures stop
at verification with no row; the webhook routes treat payloads as untrusted
(unknown provider / unparseable / missing event id); an ambiguous upload timeout
reconciles to exactly ONE provider post; expired-token and permission-denied
publishes fail typed without a post; DST gap schedules are refused and overlaps
require an explicit fold.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from microdrama.contracts.enums import Platform
from microdrama.contracts.errors import NeedsReconciliation
from microdrama.contracts.primitives import ScheduleInstant
from microdrama.contracts.release import (
    PostMetadata,
    PublicationCommand,
    ReleaseSlotPlan,
)
from microdrama.publishing import metadata as meta
from microdrama.publishing.service import command_id_for
from microdrama.publishing.slots import publish_client_token
from microdrama.scheduling.webhooks import build_webhook_router
from microdrama.testing.fakes.membership import SIGNATURE_HEADER, fake_signature

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _signed(event: dict) -> tuple[dict, bytes]:
    body = json.dumps(event).encode()
    return {SIGNATURE_HEADER: fake_signature(body)}, body


# --- webhook dedupe and trust (entitlements service) -------------------------------------


def test_duplicate_membership_webhook_delivery_never_repeats_its_effect(
    validation_world,
) -> None:
    world = validation_world
    event = {
        "id": "evt-t030-dedupe",
        "type": "members:pledge:create",
        "member_ref": "member:t030",
        "episode_id": str(uuid.uuid4()),
    }
    headers, body = _signed(event)
    first = world.memberships.entitlements.process_webhook(headers, body)
    assert first.valid is True
    assert first.duplicate is False
    second = world.memberships.entitlements.process_webhook(headers, body)
    assert second.valid is True
    assert second.duplicate is True, "a replayed delivery must be recognized"
    assert second.applied is False, "and must not repeat its effect"
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id FROM webhook_events WHERE provider = %s AND event_id = %s",
            ("PATREON", "evt-t030-dedupe"),
        )
    assert len(rows) == 1


def test_invalid_signature_records_nothing_and_interprets_nothing(validation_world) -> None:
    world = validation_world
    body = json.dumps(
        {"id": "evt-t030-forged", "type": "members:pledge:create", "member_ref": "x"}
    ).encode()
    outcome = world.memberships.entitlements.process_webhook({SIGNATURE_HEADER: "forged"}, body)
    assert outcome.valid is False
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id FROM webhook_events WHERE event_id = %s", ("evt-t030-forged",)
        )
    assert rows == []


# --- webhook routes: untrusted input surfaces ------------------------------------------------


def _client(world) -> TestClient:
    app = FastAPI()
    app.include_router(build_webhook_router(world.db, memberships_service=world.memberships))
    return TestClient(app)


def test_webhook_routes_treat_payloads_as_untrusted(validation_world) -> None:
    world = validation_world
    client = _client(world)

    # Membership: valid signature → PROCESSED; forged → INVALID_SIGNATURE.
    headers, body = _signed(
        {"id": "evt-t030-route", "type": "members:pledge:create", "member_ref": "m"}
    )
    assert (
        client.post("/webhooks/membership/patreon", content=body, headers=headers).json()["status"]
        == "PROCESSED"
    )
    forged = client.post(
        "/webhooks/membership/patreon", content=body, headers={SIGNATURE_HEADER: "nope"}
    )
    assert forged.json()["status"] == "INVALID_SIGNATURE"
    unknown = client.post("/webhooks/membership/doesnotexist", content=b"{}", headers={})
    assert unknown.json()["status"] == "UNKNOWN_PROVIDER"

    # Community: recorded-only, deduped by the provider's own event id, and
    # garbage input gets a typed answer instead of a crash or an action.
    ok = client.post(
        "/webhooks/community/youtube",
        content=json.dumps({"whatever": True, "unknown_field": {"nested": 1}}).encode(),
        headers={"x-provider-event-id": "plat-evt-1"},
    )
    assert ok.json() == {"status": "RECORDED", "verified": False, "mock": True}
    replay = client.post(
        "/webhooks/community/youtube",
        content=json.dumps({"whatever": True}).encode(),
        headers={"x-provider-event-id": "plat-evt-1"},
    )
    assert replay.status_code == 202  # accepted, but deduped:
    with world.db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT id FROM webhook_events WHERE provider = %s AND event_id = %s",
            ("community:youtube", "plat-evt-1"),
        )
    assert len(rows) == 1
    unparseable = client.post(
        "/webhooks/community/youtube", content=b"{not json", headers={"x-provider-event-id": "x"}
    )
    assert unparseable.json()["status"] == "UNPARSEABLE"
    missing = client.post("/webhooks/community/youtube", content=b"{}", headers={})
    assert missing.json()["status"] == "MISSING_EVENT_ID"


# --- ambiguous upload timeout: reconcile to exactly one post ------------------------------


def _pilot_youtube_command(
    world, report, tmp_path: Path, *, token_key: str = "t030"
) -> tuple[PublicationCommand, Path]:
    """Rebuild a pilot-shaped YouTube publication command read-only from durable
    rows (the same construction the runner used), plus the real media file."""
    with world.db.transaction(readonly=True) as tx:
        package = tx.fetchone(
            "SELECT id, body FROM release_packages WHERE episode_id = %s "
            "AND status = 'APPROVED' ORDER BY version DESC LIMIT 1",
            (report.episode_id,),
        )
        post = tx.fetchone(
            "SELECT release_slot FROM platform_posts WHERE episode_id = %s "
            "AND platform = %s ORDER BY release_slot LIMIT 1",
            (report.episode_id, Platform.YOUTUBE.value),
        )
        master_key = tx.fetchone(
            "SELECT object_key FROM assets WHERE id = %s", (report.master_asset_id,)
        )["object_key"]
    plan = next(
        ReleaseSlotPlan.model_validate(p)
        for p in package["body"]["release_scope"]
        if p["slot"]["release_slot"] == post["release_slot"]
    )
    from microdrama.contracts.enums import DisclosureKind

    metadata = PostMetadata(
        locale="th-TH",
        title="t030 fault injection (mock)",
        caption="mock",
        description="mock",
        hashtags=["#mock"],
        disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
        catalog_version=1,
    )
    media = tmp_path / f"{token_key.replace(':', '-')}-master.mp4"
    media.write_bytes(world.store.get_bytes(master_key))
    command = PublicationCommand(
        command_id=command_id_for(f"{token_key}:{post['release_slot']}"),
        release_package_id=package["id"],
        release_package_hash=package["body"]["package_hash"],
        approval_event_id=report.gate2_approval_id,
        slot=plan.slot,
        slot_kind=plan.slot_kind,
        asset_id=plan.asset_id,
        asset_sha256=plan.asset_sha256,
        metadata=metadata,
        metadata_version_id=meta.initial_metadata_version_id(f"{token_key}:{post['release_slot']}"),
        schedule=plan.schedule,
        capability_id=plan.capability_id,
        capability_version=plan.capability_version,
        client_token=publish_client_token(
            f"{token_key}:{post['release_slot']}", package["body"]["package_hash"]
        ),
    )
    return command, media


def _videos_for_token(adapter, client_token: str) -> list[str]:
    transport = adapter.transport
    return [
        video_id
        for video_id, video in transport._videos.items()  # noqa: SLF001 - fake state
        if video.client_token == client_token
    ]


def test_ambiguous_upload_timeout_yields_exactly_one_post(pilot, tmp_path) -> None:
    """TIMEOUT_CREATED through the COMPOSED YouTube adapter: the upload completes
    provider-side but the response is lost; retrying the same command reconciles
    to the SAME video — never a duplicate."""
    from microdrama.publishing.youtube.transport import YouTubeScenario

    world, report = pilot
    command, media = _pilot_youtube_command(world, report, tmp_path)
    adapter = world.publishing._adapters[Platform.YOUTUBE]  # noqa: SLF001 - drive only
    adapter.transport.queue_scenarios(YouTubeScenario.TIMEOUT_CREATED)
    with pytest.raises(NeedsReconciliation):
        adapter.submit(command, media)

    result = adapter.submit(command, media)  # the reconcile retry
    assert result.external_id is not None
    assert _videos_for_token(adapter, command.client_token) == [result.external_id]
    replay = adapter.submit(command, media)
    assert replay.external_id == result.external_id
    assert _videos_for_token(adapter, command.client_token) == [result.external_id], (
        "an ambiguous timeout must never create a second provider post"
    )


def test_expired_token_and_denied_permission_fail_typed_without_posts(pilot, tmp_path) -> None:
    from microdrama.publishing.youtube.transport import YouTubeScenario

    world, report = pilot
    adapter = world.publishing._adapters[Platform.YOUTUBE]  # noqa: SLF001

    command, media = _pilot_youtube_command(world, report, tmp_path, token_key="t030-exp")
    adapter.transport.queue_scenarios(YouTubeScenario.TOKEN_EXPIRED)
    expired = adapter.submit(command, media)
    assert expired.state.value == "FAILED"
    assert expired.error_code == "TOKEN_EXPIRED"
    assert _videos_for_token(adapter, command.client_token) == []

    command2, media2 = _pilot_youtube_command(world, report, tmp_path, token_key="t030-deny")
    adapter.transport.queue_scenarios(YouTubeScenario.DENIED_PERMISSION)
    denied = adapter.submit(command2, media2)
    assert denied.state.value == "FAILED"
    assert denied.error_code == "PERMISSION_DENIED"
    assert _videos_for_token(adapter, command2.client_token) == []


# --- DST scheduling ----------------------------------------------------------------------------


def test_dst_gap_is_refused_and_overlap_requires_explicit_fold() -> None:
    """02:30 on 2026-03-29 does not exist in Europe/Berlin (spring-forward gap);
    02:30 on 2026-10-25 exists twice (fall-back overlap) and is ambiguous unless
    the caller names the fold."""
    with pytest.raises(ValueError):
        ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 3, 29, 2, 30))
    with pytest.raises(ValueError):
        ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 10, 25, 2, 30))
    folded = ScheduleInstant.from_local("Europe/Berlin", datetime(2026, 10, 25, 2, 30), fold=1)
    assert folded.utc_instant.isoformat().endswith("+00:00")

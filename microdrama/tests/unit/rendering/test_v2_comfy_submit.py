"""T041b semantic graph submission through the T013 durable recovery lifecycle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from comfy_support import ComfyWorld

from microdrama.contracts.cost import RenderRequest
from microdrama.contracts.enums import ControlKind, ProviderOperationState, RenderTier
from microdrama.contracts.errors import SchemaInvalid
from microdrama.contracts.examples import v2_prompt_manifest
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.v2 import PromptManifest
from microdrama.persistence import Database, jsonb
from microdrama.rendering.comfy_jobs import RENDER_OPERATION_KIND, render_id_for
from microdrama.rendering.workflows import (
    MOCK_VIDEO_TEMPLATE,
    bind_v2_workflow,
    semantic_template_sha256,
    template_sha256,
)

pytestmark = [pytest.mark.db, pytest.mark.ffmpeg]


@pytest.fixture
def world(db: Database, tmp_path: Path) -> ComfyWorld:
    return ComfyWorld(db, tmp_path / "store")


def _v2_attempt(world: ComfyWorld):
    episode = world.episode()
    key = "render.shot:ep1:sh1:attempt1"
    reservation = world.service.reserve_attempt(episode_id=episode.episode_id, semantic_key=key)
    base = v2_prompt_manifest()
    manifest = PromptManifest.seal(
        **{
            **base.model_dump(mode="python", exclude={"content_sha256"}),
            "episode_id": episode.episode_id,
            "shot_id": "sh1",
            "shot_duration_ms": 4_000,
            "prompt_text": "Fon reads the debt ledger at the stall.",
            "source_hashes": sorted(
                set(base.source_hashes) | {item.asset_sha256 for item in base.bindings}
            ),
        }
    )
    with world.db.transaction() as tx:
        tx.execute(
            "INSERT INTO v2_contract_documents "
            "(contract_type, record_id, version, payload, payload_sha256, rights_route_id, "
            "rights_version, valid_from, valid_until, current) "
            "VALUES ('PromptManifest', %s, %s, %s, %s, NULL, NULL, %s, NULL, true)",
            (
                manifest.record_id,
                manifest.version,
                jsonb(manifest.model_dump(mode="json")),
                canonical_hash(manifest),
                manifest.valid_from,
            ),
        )
    reference_ids = list(dict.fromkeys(item.asset_id for item in manifest.bindings))
    world._seed_reference_assets(reference_ids)
    request = RenderRequest(
        render_id=render_id_for(key),
        semantic_key=key,
        episode_id=episode.episode_id,
        episode_number=1,
        shot_id=manifest.shot_id,
        manifest_version=1,
        attempt_number=1,
        preset_id="fake-quality-8step",
        tier=RenderTier.QUALITY_EIGHT_STEP,
        required_controls=[
            ControlKind.TEXT_PROMPT,
            ControlKind.SEED,
            ControlKind.CHARACTER_REFERENCE,
            ControlKind.WARDROBE_REFERENCE,
            ControlKind.LOCATION_REFERENCE,
        ],
        reference_asset_ids=reference_ids,
        workflow_sha256=template_sha256(MOCK_VIDEO_TEMPLATE),
        seed=1234,
        width=720,
        height=1280,
        fps=24,
        duration_ms=4_000,
        reservation_id=reservation.id,
        prompt_text=manifest.prompt_text,
        prompt_manifest_id=manifest.record_id,
        prompt_manifest_sha256=manifest.content_sha256,
        semantic_workflow_sha256=semantic_template_sha256(MOCK_VIDEO_TEMPLATE),
    )
    with world.db.transaction() as tx:
        job = world.jobs.enqueue(tx, job_type="render.shot", semantic_key=key, payload=request)
    bound = bind_v2_workflow(MOCK_VIDEO_TEMPLATE, request, manifest)
    return episode, request, manifest, bound, job.job_id


def test_v2_submit_reconnects_old_pin_after_semantic_mapping_changes(
    world: ComfyWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _episode, request, _manifest, bound, job_id = _v2_attempt(world)

    first = world.service.submit_v2(request, bound, job_id=job_id)
    assert first.state is ProviderOperationState.SUBMITTED
    assert world.server.submissions == [first.prompt_id]
    (operation,) = world.op_rows()
    assert operation["operation_kind"] == RENDER_OPERATION_KIND
    assert operation["external_id"] == first.prompt_id
    assert operation["request_hash"] == bound.request_hash

    restarted = world.reconnect()
    changed_ports = dict(MOCK_VIDEO_TEMPLATE.semantic_role_ports)
    changed_ports["character_identity"] = "identity_v2_{subject}"
    changed_template = replace(
        MOCK_VIDEO_TEMPLATE,
        semantic_role_ports=MappingProxyType(changed_ports),
    )
    assert semantic_template_sha256(changed_template) != semantic_template_sha256(
        MOCK_VIDEO_TEMPLATE
    )
    monkeypatch.setattr(restarted, "_template_for", lambda _request: changed_template)
    replay = restarted.submit_v2(request, bound, job_id=job_id)
    assert replay.prompt_id == first.prompt_id
    assert world.server.submissions == [first.prompt_id]


def test_v2_invalid_bound_graph_releases_hold_without_provider_call(world: ComfyWorld) -> None:
    _episode, request, _manifest, bound, job_id = _v2_attempt(world)
    before = len(world.server.submissions)
    invalid = replace(bound, request_hash="0" * 64)

    with pytest.raises(SchemaInvalid, match="request hash is invalid"):
        world.service.submit_v2(request, invalid, job_id=job_id)

    assert len(world.server.submissions) == before
    assert world.reservation_row(request.reservation_id)["state"] == "RELEASED"
